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
/* A changing scene still produces a photo. This is a settling budget, not an
 * exposure cap; the result reports whether the measured settings stabilized. */
#define STILL_SETTLE_US 4000000
#define STABLE_WINDOW_US 300000

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
static ainekio_camera_resolution_t snapshot_resolution = AINEKIO_CAMERA_AUTO;
static ainekio_camera_capture_t last_capture;
static uint32_t generation, frame_counter;
static uint64_t session;

typedef struct {
    int fd;
    bool streaming, still;
    unsigned width, height, hts, vts, pclk;
    void *buffers[CAMERA_BUFFERS];
    size_t lengths[CAMERA_BUFFERS];
} capture_device_t;

typedef struct { uint32_t exposure_us, gain_x16; } exposure_t;

/* Go through esp_video and the sensor driver's lock, including for the few
 * OV5647 controls not exposed as standard V4L2 controls by esp_cam_sensor. */
static int sensor_register(int fd, bool write, uint32_t address, uint32_t *value)
{
    esp_cam_sensor_reg_val_t reg = {.regaddr = address, .value = *value};
    struct v4l2_ext_control control = {
        .id = write ? ESP_CAM_SENSOR_IOC_S_REG : ESP_CAM_SENSOR_IOC_G_REG,
        .p_u8 = (uint8_t *)&reg, .size = sizeof(reg),
    };
    struct v4l2_ext_controls controls = {
        .ctrl_class = V4L2_CTRL_CLASS_ESP_CAM_IOCTL, .count = 1, .controls = &control,
    };
    int result = ioctl(fd, write ? VIDIOC_S_EXT_CTRLS : VIDIOC_G_EXT_CTRLS, &controls);
    if (!result) *value = reg.value;
    return result;
}

static int read_register(int fd, uint32_t address, uint32_t *value)
{ *value = 0; return sensor_register(fd, false, address, value); }

static int write_register(int fd, uint32_t address, uint32_t value)
{ return sensor_register(fd, true, address, &value); }

static int read_word(int fd, uint32_t address, unsigned *value)
{
    uint32_t high, low;
    if (read_register(fd, address, &high) || read_register(fd, address + 1, &low)) return -1;
    *value = (high << 8) | low;
    return 0;
}

static int write_word(int fd, uint32_t address, unsigned value)
{ return write_register(fd, address, value >> 8) || write_register(fd, address + 1, value & 255); }

static int stop_capture(capture_device_t *device)
{
    const int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (device->streaming && ioctl(device->fd, VIDIOC_STREAMOFF, &type)) return -1;
    device->streaming = false;
    atomic_store(&capture_running, false);
    return 0;
}

static int release_buffers(capture_device_t *device)
{
    for (unsigned i = 0; i < CAMERA_BUFFERS; ++i) {
        if (device->buffers[i]) munmap(device->buffers[i], device->lengths[i]);
        device->buffers[i] = NULL;
    }
    struct v4l2_requestbuffers req = {.count = 0, .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
        .memory = V4L2_MEMORY_MMAP};
    return ioctl(device->fd, VIDIOC_REQBUFS, &req);
}

static int select_format(capture_device_t *device, unsigned width, unsigned height)
{
    if (device->width == width && device->height == height) return 0;
    if (stop_capture(device) || release_buffers(device)) return -1;
    struct v4l2_sensor_format_enum sensor = {0};
    for (;;) {
        if (ioctl(device->fd, VIDIOC_ENUM_SENSOR_FMT, &sensor)) return -1;
        if (sensor.format.width == width && sensor.format.height == height) break;
        ++sensor.index;
    }
    if (ioctl(device->fd, VIDIOC_S_SENSOR_FMT, &sensor.format) || !sensor.format.isp_info) return -1;
    device->pclk = sensor.format.isp_info->isp_v1_info.pclk;
    /* Read the actual timing registers: the vendor 960p ISP metadata swaps
     * HTS and VTS, so using its tline/hts fields would misreport shutter time. */
    if (!device->pclk || read_word(device->fd, 0x380c, &device->hts) ||
        read_word(device->fd, 0x380e, &device->vts)) return -1;
    struct v4l2_format format = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .fmt.pix = {
        .width = width, .height = height, .pixelformat = V4L2_PIX_FMT_RGB565}};
    if (ioctl(device->fd, VIDIOC_S_FMT, &format) || format.fmt.pix.width != width ||
        format.fmt.pix.height != height || format.fmt.pix.pixelformat != V4L2_PIX_FMT_RGB565) return -1;
    struct v4l2_requestbuffers req = {.count = CAMERA_BUFFERS, .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
        .memory = V4L2_MEMORY_MMAP};
    if (ioctl(device->fd, VIDIOC_REQBUFS, &req) || req.count != CAMERA_BUFFERS) return -1;
    for (unsigned i = 0; i < CAMERA_BUFFERS; ++i) {
        struct v4l2_buffer buffer = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
            .memory = V4L2_MEMORY_MMAP, .index = i};
        if (ioctl(device->fd, VIDIOC_QUERYBUF, &buffer) || buffer.length < width * height * 2U ||
            buffer.length > width * height * 2U + 4096U) return -1;
        device->buffers[i] = mmap(NULL, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED,
            device->fd, buffer.m.offset);
        if (!device->buffers[i] || device->buffers[i] == MAP_FAILED) {
            device->buffers[i] = NULL;
            return -1;
        }
        device->lengths[i] = buffer.length;
    }
    device->width = width;
    device->height = height;
    return 0;
}

static int exposure_profile(capture_device_t *device, bool still)
{
    uint32_t mode, manual;
    if (read_register(device->fd, 0x3a00, &mode) || read_register(device->fd, 0x3503, &manual)) return -1;
    /* Keep sensor AEC, AGC and frame length automatic (datasheet 4.6).
     * Preview previously allowed only one frame while AGC could reach 64x.
     * Allow a 1/15 s preview shutter and automatic 1..32x gain (ISO 100..3200
     * on the published OV5647 scale). These are ceilings, not fixed settings.
     * Stills retain their eight-frame integration range. No host AE loop. */
    const unsigned preview_lines = (uint64_t)66667U * device->pclk /
                                   ((uint64_t)device->hts * 1000000ULL);
    const unsigned lines = still ? device->vts * 8U - 4U : preview_lines;
    if (write_register(device->fd, 0x3503, manual & ~7U) ||
        write_word(device->fd, 0x3a18, 32U * 16U) ||
        write_word(device->fd, 0x3a02, lines) || write_word(device->fd, 0x3a14, lines) ||
        write_register(device->fd, 0x3a00, (mode | 4U) & ~1U)) return -1;
    device->still = still;
    return 0;
}

static int read_exposure(capture_device_t *device, exposure_t *exposure)
{
    uint32_t high, middle, low;
    unsigned gain;
    if (read_register(device->fd, 0x3500, &high) || read_register(device->fd, 0x3501, &middle) ||
        read_register(device->fd, 0x3502, &low) || read_word(device->fd, 0x350a, &gain)) return -1;
    const uint32_t sixteenth_lines = ((high & 15U) << 16) | (middle << 8) | low;
    exposure->exposure_us = (uint64_t)sixteenth_lines * device->hts * 1000000ULL / (16ULL * device->pclk);
    exposure->gain_x16 = gain & 1023U;
    return 0;
}

static bool close_setting(uint32_t value, uint32_t previous)
{
    const uint32_t difference = value > previous ? value - previous : previous - value;
    return difference <= previous / 16U + 1U;
}

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
    capture_device_t device = {.fd = -1};
    jpeg_encoder_handle_t encoder = NULL;
    uint8_t *jpeg = NULL;
    uint16_t *scaled = NULL;
    size_t jpeg_size = 0, scaled_size = 0;
    bool video_initialized = false;
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
    device.fd = open(ESP_VIDEO_MIPI_CSI_DEVICE_NAME, O_RDONLY);
    if (device.fd < 0 || select_format(&device, CAMERA_WIDTH, CAMERA_HEIGHT)) goto cleanup;
    /* The longest supported night exposure is about 267 ms at 1080p. */
    const struct timeval timeout = {.tv_sec = 0, .tv_usec = 500000};
    if (ioctl(device.fd, VIDIOC_S_DQBUF_TIMEOUT, &timeout) != 0) goto cleanup;
    const jpeg_encode_engine_cfg_t engine = {.timeout_ms = 200};
    if (jpeg_new_encoder_engine(&engine, &encoder) != ESP_OK) goto cleanup;
    const jpeg_encode_memory_alloc_cfg_t output_memory = {.buffer_direction = JPEG_ENC_ALLOC_OUTPUT_BUFFER};
    const jpeg_encode_memory_alloc_cfg_t input_memory = {.buffer_direction = JPEG_ENC_ALLOC_INPUT_BUFFER};
    jpeg = jpeg_alloc_encoder_mem(JPEG_CAPACITY, &output_memory, &jpeg_size);
    scaled = jpeg_alloc_encoder_mem(1024U * 768U * 2U, &input_memory, &scaled_size);
    if (!jpeg || !scaled) goto cleanup;
    atomic_store(&ready, true);
    xSemaphoreGive(initialized);
    ESP_LOGI("p4_camera", "OV5647 ready; automatic exposure, native 960p/1080p stills");
    int64_t next_frame = 0, settle_start = 0, stable_since = 0, request_start = 0;
    unsigned consecutive_failures = 0, settle_frames = 0;
    exposure_t anchor = {0}, measured = {0};
    snapshot_t request = {0};
    bool pending = false, auto_metering = false;
    for (;;) {
        xSemaphoreTake(state_lock, portMAX_DELAY);
        const bool preview = enabled && !suspended && session;
        const uint8_t active_fps = fps;
        if (pending && (request.generation != generation || suspended || request.session != session || !snapshot_active))
            pending = false;
        bool new_request = false;
        if (!pending) {
            request = (snapshot_t){.resolution = resolution, .generation = generation, .session = session};
            pending = xQueueReceive(requests, &request, 0) == pdTRUE;
            const bool admitted = request.generation == generation && !suspended &&
                                  request.session && request.session == session;
            if (pending && admitted) {
                active_request = request;
                snapshot_active = true;
                new_request = true;
            } else if (pending) {
                pending = false;
                xSemaphoreGive(state_lock);
                continue;
            }
        }
        xSemaphoreGive(state_lock);
        if (!pending && !preview) {
            if (stop_capture(&device)) goto cleanup;
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        if (new_request) {
            request_start = settle_start = esp_timer_get_time();
            stable_since = 0;
            settle_frames = 0;
            anchor = (exposure_t){0};
            auto_metering = request.resolution == AINEKIO_CAMERA_AUTO;
        }
        const bool fhd = pending && request.resolution == AINEKIO_CAMERA_FHD;
        const unsigned capture_width = fhd ? 1920U : CAMERA_WIDTH;
        const unsigned capture_height = fhd ? 1080U : CAMERA_HEIGHT;
        const bool format_changed = device.width != capture_width || device.height != capture_height;
        if (select_format(&device, capture_width, capture_height)) {
            failed(request, ESP_FAIL);
            goto cleanup;
        }
        if (!device.streaming || format_changed || device.still != pending) {
            if (exposure_profile(&device, pending)) { failed(request, ESP_FAIL); goto cleanup; }
        }
        if (!device.streaming) {
            xSemaphoreTake(state_lock, portMAX_DELAY);
            const bool may_start = !suspended && request.session == session && request.generation == generation;
            if (may_start) atomic_store(&capture_running, true);
            xSemaphoreGive(state_lock);
            if (!may_start) continue;
            for (unsigned i = 0; i < CAMERA_BUFFERS; ++i) {
                struct v4l2_buffer buffer = {.type = type, .memory = V4L2_MEMORY_MMAP, .index = i};
                if (ioctl(device.fd, VIDIOC_QBUF, &buffer)) { failed(request, ESP_FAIL); goto cleanup; }
            }
            if (ioctl(device.fd, VIDIOC_STREAMON, &type)) { failed(request, ESP_FAIL); goto cleanup; }
            device.streaming = true;
            atomic_store(&capture_running, true);
        }
        struct v4l2_buffer frame = {.type = type, .memory = V4L2_MEMORY_MMAP};
        if (ioctl(device.fd, VIDIOC_DQBUF, &frame) != 0) {
            failed(request, ESP_ERR_TIMEOUT);
            pending = false;
            if (++consecutive_failures >= 5) goto cleanup;
            continue;
        }
        consecutive_failures = 0;
        result = ESP_OK;
        if (frame.index >= CAMERA_BUFFERS || frame.bytesused < device.width * device.height * 2U ||
            (frame.flags & V4L2_BUF_FLAG_ERROR)) result = ESP_FAIL;
        const int64_t now = esp_timer_get_time();
        bool settled = false;
        if (result == ESP_OK && (pending || now >= next_frame)) {
            if (read_exposure(&device, &measured)) result = ESP_FAIL;
            else if (pending) {
                ++settle_frames;
                if (!anchor.exposure_us || !anchor.gain_x16 ||
                    !close_setting(measured.exposure_us, anchor.exposure_us) ||
                    !close_setting(measured.gain_x16, anchor.gain_x16)) {
                    anchor = measured;
                    stable_since = now;
                }
                settled = settle_frames >= 8 && measured.exposure_us && measured.gain_x16 &&
                          now - stable_since >= STABLE_WINDOW_US;
            }
        }
        bool emit = pending ? settled || now - settle_start >= STILL_SETTLE_US : now >= next_frame;
        if (result == ESP_OK && pending && emit && auto_metering) {
            auto_metering = false;
            /* Practical selection policy, not a claim of measured optical
             * optimality: prefer the binned full-field 960p mode in dim light;
             * use the sensor's cropped 1080p mode when the metered exposure
             * product fits 1/30 second at unity gain. Both are selectable. */
            if (settled && (uint64_t)measured.exposure_us * measured.gain_x16 <= 33333ULL * 16U) {
                request.resolution = AINEKIO_CAMERA_FHD;
                settle_start = now;
                stable_since = 0;
                settle_frames = 0;
                anchor = (exposure_t){0};
                emit = false;
            } else request.resolution = AINEKIO_CAMERA_960P;
        }
        uint32_t encoded = 0;
        unsigned width = 0, height = 0;
        if (result == ESP_OK && emit) {
            const unsigned widths[] = {320, 640, 1024, 1280, 1920};
            const unsigned heights[] = {240, 480, 768, 960, 1080};
            width = widths[request.resolution];
            height = heights[request.resolution];
            uint16_t *source = device.buffers[frame.index];
            const uint16_t *input = source;
            /* The installed camera is upside down. Rotate the actual image,
             * before JPEG, so every consumer gets the same upright pixels.
             * RGB rotation preserves the sensor/ISP Bayer and exposure setup.
             * Resized images fold rotation into the existing sampling pass;
             * native stills reverse the dequeued buffer in place (no copy). */
            if (width != device.width || height != device.height) {
                for (unsigned y = 0; y < height; ++y) {
                    const uint16_t *row = source + ((height - 1U - y) * device.height / height) * device.width;
                    for (unsigned x = 0; x < width; ++x)
                        scaled[y * width + x] = row[(width - 1U - x) * device.width / width];
                }
                input = scaled;
            } else {
                const size_t count = (size_t)width * height;
                for (size_t i = 0; i < count / 2; ++i) {
                    const uint16_t pixel = source[i];
                    source[i] = source[count - 1 - i];
                    source[count - 1 - i] = pixel;
                }
            }
            const jpeg_encode_cfg_t encode = {.src_type = JPEG_ENCODE_IN_FORMAT_RGB565,
                .sub_sample = JPEG_DOWN_SAMPLING_YUV420, .image_quality = 75, .width = width, .height = height};
            result = jpeg_encoder_process(encoder, &encode, (uint8_t *)input, width * height * 2U,
                                          jpeg, jpeg_size, &encoded);
            if (result == ESP_OK && (encoded < 4 || encoded > JPEG_CAPACITY)) result = ESP_ERR_INVALID_SIZE;
        }
        if (ioctl(device.fd, VIDIOC_QBUF, &frame)) { failed(request, ESP_FAIL); goto cleanup; }
        if (result != ESP_OK) { failed(request, result); pending = false; continue; }
        xSemaphoreTake(state_lock, portMAX_DELAY);
        const bool current = request.generation == generation && !suspended && request.session &&
                             request.session == session && (pending ? snapshot_active : enabled);
        if (emit && current) {
            if (pending) snapshot_active = false;
            last_capture = (ainekio_camera_capture_t){
                .counter = ++frame_counter, .width = width, .height = height,
                .exposure_us = measured.exposure_us, .gain_x16 = measured.gain_x16,
                .settle_ms = pending ? (uint32_t)((now - request_start) / 1000) : 0,
                .settled = pending && settled,
            };
        }
        xSemaphoreGive(state_lock);
        if (emit && current && callbacks.camera_frame) {
            callbacks.camera_frame(callbacks.context, request.session, request.origin, request.origin_id,
                request.resolution, frame_counter, jpeg, encoded);
            if (!pending && active_fps > 0)
                next_frame = esp_timer_get_time() + 1000000 / active_fps;
        }
        if (emit) pending = false;
    }
cleanup:
    if (result == ESP_OK) result = ESP_FAIL;
    atomic_store(&ready, false);
    xSemaphoreGive(initialized);
    atomic_fetch_add(&failures, 1);
    if (device.fd >= 0) {
        (void)stop_capture(&device);
        (void)release_buffers(&device);
        close(device.fd);
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

ainekio_camera_capture_t ainekio_p4_media_camera_capture(void)
{
    if (!state_lock) return (ainekio_camera_capture_t){0};
    xSemaphoreTake(state_lock, portMAX_DELAY);
    ainekio_camera_capture_t capture = last_capture;
    xSemaphoreGive(state_lock);
    return capture;
}

esp_err_t ainekio_p4_media_camera_configure(bool stream, uint8_t rate, ainekio_camera_resolution_t size,
                                         const ainekio_camera_resolution_t *snapshot_size)
{
    if (rate > 15 || size < AINEKIO_CAMERA_QVGA || size > AINEKIO_CAMERA_XGA ||
        (snapshot_size && (*snapshot_size < AINEKIO_CAMERA_QVGA || *snapshot_size > AINEKIO_CAMERA_AUTO)))
        return ESP_ERR_INVALID_ARG;
    if (!p4_camera_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    if (suspended || !session) { xSemaphoreGive(state_lock); return ESP_ERR_INVALID_STATE; }
    enabled = stream && rate > 0;
    fps = rate;
    resolution = size;
    if (snapshot_size) snapshot_resolution = *snapshot_size;
    xSemaphoreGive(state_lock);
    return ESP_OK;
}

esp_err_t ainekio_p4_media_snapshot(ainekio_camera_origin_t origin, uint32_t id)
{
    if (origin < AINEKIO_CAMERA_ORIGIN_REQUEST || origin > AINEKIO_CAMERA_ORIGIN_AUDIO ||
        (origin != AINEKIO_CAMERA_ORIGIN_AUDIO && !id))
        return ESP_ERR_INVALID_ARG;
    if (!p4_camera_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(state_lock, portMAX_DELAY);
    bool paused = suspended || !session;
    snapshot_t request = {.origin = origin, .origin_id = id, .generation = generation,
        .resolution = snapshot_resolution, .session = session};
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
