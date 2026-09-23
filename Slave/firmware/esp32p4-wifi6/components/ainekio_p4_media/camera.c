#include "media_internal.h"

#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <unistd.h>
#include "driver/jpeg_encode.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_video_device.h"
#include "esp_video_init.h"
#include "esp_video_ioctl.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#define CAMERA_WIDTH 1280U
#define CAMERA_HEIGHT 960U
#define JPEG_CAPACITY AINEKIO_MAX_JPEG_BYTES
#define CAMERA_BUFFERS 2U

typedef struct {
    ainekio_camera_origin_t origin;
    uint32_t origin_id, generation;
    uint64_t session;
    ainekio_camera_resolution_t resolution;
} snapshot_t;

static SemaphoreHandle_t state_lock;
static SemaphoreHandle_t initialized;
static snapshot_t active_request;
static bool snapshot_active;
static atomic_bool ready;
static atomic_bool capture_running;
static atomic_uint failures;
static QueueHandle_t requests;
static ainekio_p4_media_callbacks_t callbacks;
static i2c_master_bus_handle_t bus;
static bool enabled, suspended;
static uint8_t fps = 2;
static ainekio_camera_resolution_t resolution = AINEKIO_CAMERA_VGA;
static uint32_t generation, frame_counter;
static uint64_t session;

static void failed(snapshot_t request, esp_err_t error)
{
    atomic_fetch_add(&failures, 1);
    xSemaphoreTake(state_lock, portMAX_DELAY);
    bool current = request.generation == generation && !suspended && request.session && request.session == session;
    if (request.origin != AINEKIO_CAMERA_ORIGIN_NONE) {
        current = current && snapshot_active && active_request.origin_id == request.origin_id &&
                  active_request.session == request.session;
        if (current) snapshot_active = false;
    }
    xSemaphoreGive(state_lock);
    if (current && callbacks.camera_failed && request.origin != AINEKIO_CAMERA_ORIGIN_NONE)
        callbacks.camera_failed(callbacks.context, request.session, request.origin, request.origin_id, error);
}

static void camera_task(void *unused)
{
    (void)unused;
    int fd = -1;
    void *buffers[CAMERA_BUFFERS] = {0};
    size_t lengths[CAMERA_BUFFERS] = {0};
    jpeg_encoder_handle_t encoder = NULL;
    uint8_t *jpeg = NULL;
    uint16_t *scaled = NULL;
    size_t jpeg_size = 0, scaled_size = 0;
    bool video_initialized = false, streaming = false;
    esp_err_t result = ESP_FAIL;
    const int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (i2c_master_probe(bus, 0x36, 30) != ESP_OK) {
        ESP_LOGI("p4_camera", "OV5647 not connected");
        xSemaphoreGive(initialized);
        vTaskDelete(NULL);
        return;
    }
    const esp_video_init_csi_config_t csi = {
        .sccb_config = {.init_sccb = false, .i2c_handle = bus, .freq = 100000},
        .reset_pin = -1, .pwdn_pin = -1,
    };
    const esp_video_init_config_t config = {.csi = &csi};
    result = esp_video_init_with_flags(&config, ESP_VIDEO_INIT_FLAGS_MIPI_CSI | ESP_VIDEO_INIT_FLAGS_ISP);
    if (result != ESP_OK) goto cleanup;
    video_initialized = true;
    fd = open(ESP_VIDEO_MIPI_CSI_DEVICE_NAME, O_RDONLY);
    if (fd < 0) goto cleanup;
    struct v4l2_format format = {.type = type, .fmt.pix = {
        .width = CAMERA_WIDTH, .height = CAMERA_HEIGHT, .pixelformat = V4L2_PIX_FMT_RGB565}};
    if (ioctl(fd, VIDIOC_S_FMT, &format) != 0 || format.fmt.pix.width != CAMERA_WIDTH ||
        format.fmt.pix.height != CAMERA_HEIGHT || format.fmt.pix.pixelformat != V4L2_PIX_FMT_RGB565)
        goto cleanup;
    const struct timeval timeout = {.tv_sec = 0, .tv_usec = 200000};
    if (ioctl(fd, VIDIOC_S_DQBUF_TIMEOUT, &timeout) != 0) goto cleanup;
    struct v4l2_requestbuffers req = {.count = CAMERA_BUFFERS, .type = type, .memory = V4L2_MEMORY_MMAP};
    if (ioctl(fd, VIDIOC_REQBUFS, &req) != 0 || req.count != CAMERA_BUFFERS) goto cleanup;
    for (unsigned i = 0; i < CAMERA_BUFFERS; ++i) {
        struct v4l2_buffer buffer = {.type = type, .memory = V4L2_MEMORY_MMAP, .index = i};
        if (ioctl(fd, VIDIOC_QUERYBUF, &buffer) != 0 ||
            buffer.length < CAMERA_WIDTH * CAMERA_HEIGHT * 2U ||
            buffer.length > CAMERA_WIDTH * CAMERA_HEIGHT * 2U + 4096U) goto cleanup;
        buffers[i] = mmap(NULL, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buffer.m.offset);
        if (!buffers[i] || buffers[i] == MAP_FAILED) { buffers[i] = NULL; goto cleanup; }
        lengths[i] = buffer.length;
    }
    const jpeg_encode_engine_cfg_t engine = {.timeout_ms = 200};
    if (jpeg_new_encoder_engine(&engine, &encoder) != ESP_OK) goto cleanup;
    const jpeg_encode_memory_alloc_cfg_t output_memory = {.buffer_direction = JPEG_ENC_ALLOC_OUTPUT_BUFFER};
    const jpeg_encode_memory_alloc_cfg_t input_memory = {.buffer_direction = JPEG_ENC_ALLOC_INPUT_BUFFER};
    jpeg = jpeg_alloc_encoder_mem(JPEG_CAPACITY, &output_memory, &jpeg_size);
    scaled = jpeg_alloc_encoder_mem(1024U * 768U * 2U, &input_memory, &scaled_size);
    if (!jpeg || !scaled) goto cleanup;
    atomic_store(&ready, true);
    xSemaphoreGive(initialized);
    ESP_LOGI("p4_camera", "OV5647 ready; 1280x960 capture, QVGA/VGA/XGA JPEG output");
    int64_t next_frame = 0;
    unsigned consecutive_failures = 0;
    for (;;) {
        snapshot_t request = {0};
        xSemaphoreTake(state_lock, portMAX_DELAY);
        bool preview = enabled && !suspended && session;
        uint8_t active_fps = fps;
        request.resolution = resolution;
        request.generation = generation;
        request.session = session;
        bool snapshot = xQueueReceive(requests, &request, 0) == pdTRUE;
        bool admitted = request.generation == generation && !suspended && request.session && request.session == session;
        if (snapshot && admitted) { active_request = request; snapshot_active = true; }
        xSemaphoreGive(state_lock);
        if (snapshot && !admitted) continue;
        if (!snapshot && !preview) {
            if (streaming) {
                if (ioctl(fd, VIDIOC_STREAMOFF, &type) != 0) goto cleanup;
                streaming = false;
                atomic_store(&capture_running, false);
            }
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        if (!streaming) {
            xSemaphoreTake(state_lock, portMAX_DELAY);
            const bool may_start = !suspended && request.session == session &&
                                   request.generation == generation;
            if (may_start) atomic_store(&capture_running, true);
            xSemaphoreGive(state_lock);
            if (!may_start) continue;
            for (unsigned i = 0; i < CAMERA_BUFFERS; ++i) {
                struct v4l2_buffer buffer = {.type = type, .memory = V4L2_MEMORY_MMAP, .index = i};
                if (ioctl(fd, VIDIOC_QBUF, &buffer) != 0) { failed(request, ESP_FAIL); goto cleanup; }
            }
            if (ioctl(fd, VIDIOC_STREAMON, &type) != 0) { failed(request, ESP_FAIL); goto cleanup; }
            streaming = true;
            atomic_store(&capture_running, true);
            next_frame = 0;
        }
        struct v4l2_buffer frame = {.type = type, .memory = V4L2_MEMORY_MMAP};
        if (ioctl(fd, VIDIOC_DQBUF, &frame) != 0) {
            failed(request, ESP_ERR_TIMEOUT);
            if (++consecutive_failures >= 5) goto cleanup;
            continue;
        }
        consecutive_failures = 0;
        result = ESP_OK;
        if (frame.index >= CAMERA_BUFFERS || frame.bytesused < CAMERA_WIDTH * CAMERA_HEIGHT * 2U ||
            (frame.flags & V4L2_BUF_FLAG_ERROR)) result = ESP_FAIL;
        const bool emit = snapshot || esp_timer_get_time() >= next_frame;
        uint32_t encoded = 0;
        if (result == ESP_OK && emit) {
            const unsigned widths[] = {320, 640, 1024};
            const unsigned heights[] = {240, 480, 768};
            unsigned width = widths[request.resolution], height = heights[request.resolution];
            const uint16_t *source = buffers[frame.index];
            for (unsigned y = 0; y < height; ++y) {
                const uint16_t *row = source + (y * CAMERA_HEIGHT / height) * CAMERA_WIDTH;
                for (unsigned x = 0; x < width; ++x) scaled[y * width + x] = row[x * CAMERA_WIDTH / width];
            }
            const jpeg_encode_cfg_t encode = {.src_type = JPEG_ENCODE_IN_FORMAT_RGB565,
                .sub_sample = JPEG_DOWN_SAMPLING_YUV420, .image_quality = 75, .width = width, .height = height};
            result = jpeg_encoder_process(encoder, &encode, (uint8_t *)scaled, width * height * 2U,
                                          jpeg, jpeg_size, &encoded);
            if (result == ESP_OK && (encoded < 4 || encoded > JPEG_CAPACITY)) result = ESP_ERR_INVALID_SIZE;
        }
        if (ioctl(fd, VIDIOC_QBUF, &frame) != 0) { failed(request, ESP_FAIL); goto cleanup; }
        if (result != ESP_OK) { failed(request, result); continue; }
        xSemaphoreTake(state_lock, portMAX_DELAY);
        const bool current = request.generation == generation && !suspended && request.session &&
                             request.session == session && (snapshot ? snapshot_active : enabled);
        if (snapshot && current) snapshot_active = false;
        xSemaphoreGive(state_lock);
        if (emit && current && callbacks.camera_frame) {
            callbacks.camera_frame(callbacks.context, request.session, request.origin, request.origin_id,
                request.resolution, ++frame_counter, jpeg, encoded);
            next_frame = esp_timer_get_time() + 1000000 / active_fps;
        }
    }
cleanup:
    if (result == ESP_OK) result = ESP_FAIL;
    atomic_store(&ready, false);
    xSemaphoreGive(initialized);
    atomic_fetch_add(&failures, 1);
    if (fd >= 0) {
        if (streaming) (void)ioctl(fd, VIDIOC_STREAMOFF, &type);
        for (unsigned i = 0; i < CAMERA_BUFFERS; ++i)
            if (buffers[i]) munmap(buffers[i], lengths[i]);
        close(fd);
    }
    if (encoder) jpeg_del_encoder_engine(encoder);
    heap_caps_free(jpeg);
    heap_caps_free(scaled);
    if (video_initialized) esp_video_deinit_with_flags(ESP_VIDEO_INIT_FLAGS_MIPI_CSI | ESP_VIDEO_INIT_FLAGS_ISP);
    atomic_store(&capture_running, false);
    (void)p4_camera_suspend(true);
    ESP_LOGW("p4_camera", "camera unavailable: %s", esp_err_to_name(result));
    vTaskDelete(NULL);
}

esp_err_t p4_camera_start(i2c_master_bus_handle_t shared_bus, const ainekio_p4_media_callbacks_t *configuration)
{
    if (requests) return ESP_ERR_INVALID_STATE;
    bus = shared_bus;
    callbacks = *configuration;
    state_lock = xSemaphoreCreateMutex();
    initialized = xSemaphoreCreateBinary();
    requests = xQueueCreate(4, sizeof(snapshot_t));
    if (!state_lock || !initialized || !requests) {
        if (state_lock) vSemaphoreDelete(state_lock);
        if (initialized) vSemaphoreDelete(initialized);
        if (requests) vQueueDelete(requests);
        state_lock = initialized = NULL;
        requests = NULL;
        return ESP_ERR_NO_MEM;
    }
    if (xTaskCreate(camera_task, "p4_camera", 6144, NULL, 2, NULL) != pdPASS) {
        vQueueDelete(requests);
        vSemaphoreDelete(state_lock);
        vSemaphoreDelete(initialized);
        state_lock = initialized = NULL;
        requests = NULL;
        return ESP_ERR_NO_MEM;
    }
    if (xSemaphoreTake(initialized, pdMS_TO_TICKS(5000)) != pdTRUE) return ESP_ERR_TIMEOUT;
    return p4_camera_ready() ? ESP_OK : ESP_ERR_NOT_FOUND;
}

bool p4_camera_ready(void) { return atomic_load(&ready); }
uint32_t p4_camera_failures(void) { return atomic_load(&failures); }

esp_err_t ainekio_p4_media_camera_configure(bool stream, uint8_t rate, ainekio_camera_resolution_t size)
{
    if (rate > 15 || size < AINEKIO_CAMERA_QVGA || size > AINEKIO_CAMERA_XGA)
        return ESP_ERR_INVALID_ARG;
    if (!p4_camera_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    if (suspended || !session) { xSemaphoreGive(state_lock); return ESP_ERR_INVALID_STATE; }
    enabled = stream && rate > 0;
    fps = rate;
    resolution = size;
    xSemaphoreGive(state_lock);
    return ESP_OK;
}

esp_err_t ainekio_p4_media_snapshot(ainekio_camera_origin_t origin, uint32_t id)
{
    if (origin < AINEKIO_CAMERA_ORIGIN_REQUEST || origin > AINEKIO_CAMERA_ORIGIN_AUDIO || !id)
        return ESP_ERR_INVALID_ARG;
    if (!p4_camera_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    bool paused = suspended || !session;
    snapshot_t request = {.origin = origin, .origin_id = id, .generation = generation,
        .resolution = resolution, .session = session};
    esp_err_t result = paused ? ESP_ERR_INVALID_STATE :
        (xQueueSend(requests, &request, 0) == pdTRUE ? ESP_OK : ESP_ERR_NO_MEM);
    xSemaphoreGive(state_lock);
    return result;
}

esp_err_t p4_camera_suspend(bool paused)
{
    if (!state_lock) return ESP_OK;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    suspended = paused;
    if (paused) enabled = false;
    xSemaphoreGive(state_lock);
    if (paused) ainekio_p4_media_cancel_snapshots();
    const int64_t deadline = esp_timer_get_time() + 1000000;
    while (paused && atomic_load(&capture_running)) {
        if (esp_timer_get_time() >= deadline) return ESP_ERR_TIMEOUT;
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return ESP_OK;
}

void ainekio_p4_media_cancel_snapshots(void)
{
    if (!state_lock) return;
    snapshot_t cancelled[5];
    size_t count = 0;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    ++generation;
    if (snapshot_active) { cancelled[count++] = active_request; snapshot_active = false; }
    if (requests) {
        while (count < 5 && xQueueReceive(requests, &cancelled[count], 0) == pdTRUE) ++count;
    }
    xSemaphoreGive(state_lock);
    for (size_t i = 0; i < count; ++i) {
        if (callbacks.camera_failed)
            callbacks.camera_failed(callbacks.context, cancelled[i].session, cancelled[i].origin,
                                    cancelled[i].origin_id, ESP_ERR_INVALID_STATE);
    }
}

void p4_camera_session(uint64_t next_session)
{
    if (!state_lock) return;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    session = next_session;
    enabled = false;
    snapshot_active = false;
    ++generation;
    if (requests) xQueueReset(requests);
    xSemaphoreGive(state_lock);
}
