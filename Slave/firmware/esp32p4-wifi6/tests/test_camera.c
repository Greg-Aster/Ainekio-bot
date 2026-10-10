/* Run the production camera owner with virtual capture/encoder/scheduler I/O.
 * Images, sensor electrical behavior and actual encoding speed remain hardware
 * qualification; this exercises scheduling, profiles and session fencing. */
#include "media_internal.h"
#include "ainekio/control_encode.h"
#include "driver/jpeg_encode.h"
#include "esp_video_init.h"
#include "esp_video_device.h"
#include "esp_video_ioctl.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include <assert.h>
#include <fcntl.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/time.h>

struct test_queue { unsigned capacity, size, count; uint8_t *data; };
static void (*camera_task_entry)(void *);
static SemaphoreHandle_t initialized;
static jmp_buf scheduler;
static bool booting, finished, inject_snapshot, change_session_during_capture;
static unsigned target_frames, received_frames, failures_received;
static uint16_t *capture_pixels;
static int64_t clock_us;
static unsigned jpeg_width, jpeg_height, stream_fps;
static unsigned sensor_width = 1280, sensor_height = 960, sensor_regs[65536];
static unsigned sensor_gain = 16, sample_count;
static bool changing_light;
static ainekio_camera_capture_t captures[16];
static void *allocations[32];
static size_t allocation_count;
static struct {
    uint64_t session;
    ainekio_camera_origin_t origin;
    uint32_t id, counter;
    ainekio_camera_resolution_t resolution;
    int64_t time;
} frames[16];

static void *allocate(size_t size)
{
    assert(allocation_count < 32);
    void *memory = calloc(1, size);
    assert(memory);
    allocations[allocation_count++] = memory;
    return memory;
}
static void release_allocations(void)
{
    for (size_t i = 0; i < allocation_count; ++i) free(allocations[i]);
    allocation_count = 0;
}

SemaphoreHandle_t xSemaphoreCreateMutex(void) { return (void *)1; }
SemaphoreHandle_t xSemaphoreCreateBinary(void) { initialized = (void *)2; return initialized; }
void vSemaphoreDelete(SemaphoreHandle_t semaphore) { (void)semaphore; }
BaseType_t xSemaphoreTake(SemaphoreHandle_t semaphore, TickType_t timeout)
{
    (void)timeout;
    if (semaphore == initialized) {
        booting = true;
        if (setjmp(scheduler) == 0) camera_task_entry(NULL);
        booting = false;
        release_allocations();
    }
    return pdTRUE;
}
BaseType_t xSemaphoreGive(SemaphoreHandle_t semaphore)
{
    if (booting && semaphore == initialized) longjmp(scheduler, 1);
    return pdTRUE;
}
QueueHandle_t xQueueCreate(UBaseType_t capacity, UBaseType_t size)
{
    struct test_queue *queue = calloc(1, sizeof(*queue));
    assert(queue);
    *queue = (struct test_queue){.capacity=capacity, .size=size, .data=calloc(capacity, size)};
    assert(queue->data);
    return queue;
}
BaseType_t xQueueSend(QueueHandle_t queue, const void *item, TickType_t timeout)
{
    (void)timeout;
    if (queue->count == queue->capacity) return 0;
    memcpy(queue->data + queue->count++ * queue->size, item, queue->size);
    return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t queue, void *item, TickType_t timeout)
{
    (void)timeout;
    if (!queue->count) return 0;
    memcpy(item, queue->data, queue->size);
    --queue->count;
    memmove(queue->data, queue->data + queue->size, queue->count * queue->size);
    return pdTRUE;
}
BaseType_t xQueueReset(QueueHandle_t queue) { queue->count = 0; return pdTRUE; }
void vQueueDelete(QueueHandle_t queue) { free(queue->data); free(queue); }
BaseType_t xTaskCreate(void (*function)(void *), const char *name, unsigned stack,
                      void *argument, unsigned priority, void *handle)
{
    (void)name; (void)stack; (void)argument; (void)priority; (void)handle;
    camera_task_entry = function;
    return pdPASS;
}
void vTaskDelete(void *task) { (void)task; assert(!"unexpected camera task exit"); }
void vTaskDelay(TickType_t ticks)
{
    clock_us += (int64_t)ticks * 1000;
    if (finished) longjmp(scheduler, 1);
    assert(!"camera became idle before the expected frames arrived");
}
int64_t esp_timer_get_time(void) { return clock_us; }
void test_camera_log(const char *tag, const char *format, ...) { (void)tag; (void)format; }
const char *esp_err_to_name(esp_err_t error) { (void)error; return "test error"; }
esp_err_t i2c_master_probe(i2c_master_bus_handle_t bus, uint16_t address, int timeout)
{ (void)bus; (void)timeout; assert(address == 0x36); return ESP_OK; }
esp_err_t esp_video_init_with_flags(const esp_video_init_config_t *config, int flags)
{ (void)config; (void)flags; return ESP_OK; }
esp_err_t esp_video_deinit_with_flags(int flags) { (void)flags; return ESP_OK; }
int open(const char *path, int flags, ...) {
    (void)flags; assert(strcmp(path, ESP_VIDEO_MIPI_CSI_DEVICE_NAME) == 0);
    memset(sensor_regs, 0, sizeof(sensor_regs));
    sample_count = 0;
    return 10;
}
int close(int fd) { assert(fd == 10); return 0; }
void *mmap(void *address, size_t size, int protection, int flags, int fd, off_t offset)
{
    (void)address; (void)protection; (void)flags; assert(fd == 10);
    uint16_t *pixels = allocate(size);
    if (!offset) capture_pixels = pixels;
    return pixels;
}
int munmap(void *address, size_t size) { (void)address; (void)size; return 0; }
int ioctl(int fd, unsigned long operation, ...)
{
    assert(fd == 10);
    va_list args;
    va_start(args, operation);
    void *argument = va_arg(args, void *);
    va_end(args);
    if (operation == VIDIOC_ENUM_SENSOR_FMT) {
        static const esp_cam_sensor_isp_info_t info[] = {
            {.isp_v1_info.pclk = 88333333}, {.isp_v1_info.pclk = 81666700}};
        struct v4l2_sensor_format_enum *sensor = argument;
        if (sensor->index > 1) return -1;
        sensor->format = (esp_cam_sensor_format_t){
            .width = sensor->index ? 1920 : 1280, .height = sensor->index ? 1080 : 960,
            .isp_info = &info[sensor->index]};
    } else if (operation == VIDIOC_S_SENSOR_FMT) {
        const esp_cam_sensor_format_t *format = argument;
        sensor_width = format->width; sensor_height = format->height;
        unsigned hts = sensor_width == 1280 ? 1796 : 2271, vts = sensor_width == 1280 ? 1093 : 1199;
        sensor_regs[0x380c] = hts >> 8; sensor_regs[0x380d] = hts & 255;
        sensor_regs[0x380e] = vts >> 8; sensor_regs[0x380f] = vts & 255;
    } else if (operation == VIDIOC_G_EXT_CTRLS || operation == VIDIOC_S_EXT_CTRLS) {
        struct v4l2_ext_controls *controls = argument;
        assert(controls->ctrl_class == V4L2_CTRL_CLASS_ESP_CAM_IOCTL && controls->count == 1);
        esp_cam_sensor_reg_val_t *reg = (void *)controls->controls->p_u8;
        assert(reg->regaddr < 65536);
        if (operation == VIDIOC_G_EXT_CTRLS) reg->value = sensor_regs[reg->regaddr];
        else {
            assert(reg->regaddr < 0x3500 || reg->regaddr > 0x3502);
            assert(reg->regaddr != 0x350a && reg->regaddr != 0x350b);
            sensor_regs[reg->regaddr] = reg->value;
        }
    } else if (operation == VIDIOC_QUERYBUF) {
        struct v4l2_buffer *buffer = argument;
        buffer->length = sensor_width * sensor_height * 2U;
        buffer->m.offset = buffer->index * buffer->length;
    } else if (operation == VIDIOC_DQBUF) {
        if (finished) longjmp(scheduler, 1);
        clock_us += 50000;
        struct v4l2_buffer *buffer = argument;
        buffer->index = 0;
        buffer->bytesused = sensor_width * sensor_height * 2U;
        ++sample_count;
        /* Spatially distinct source pixels verify both axes of rotation,
         * including native stills, downsampled preview and format switches. */
        for (unsigned i = 0; i < sensor_width * sensor_height; ++i)
            capture_pixels[i] = i % 65521U;
        /* Initial exposure is rising; afterwards the camera converges unless
         * this test simulates continuously changing illumination. */
        unsigned exposure = sample_count < 6 ? sample_count * 1000 : 8000;
        if (changing_light) exposure = sample_count % 2 ? 8000 : 24000;
        sensor_regs[0x3500] = exposure >> 16;
        sensor_regs[0x3501] = (exposure >> 8) & 255;
        sensor_regs[0x3502] = exposure & 255;
        sensor_regs[0x350a] = sensor_gain >> 8; sensor_regs[0x350b] = sensor_gain & 255;
        if (change_session_during_capture) {
            change_session_during_capture = false;
            p4_camera_session(8);
            finished = true;
        }
    }
    return 0;
}
esp_err_t jpeg_new_encoder_engine(const jpeg_encode_engine_cfg_t *config, jpeg_encoder_handle_t *encoder)
{ (void)config; *encoder = (void *)3; return ESP_OK; }
void *jpeg_alloc_encoder_mem(size_t size, const jpeg_encode_memory_alloc_cfg_t *config, size_t *allocated)
{ (void)config; *allocated = size; return allocate(size); }
esp_err_t jpeg_encoder_process(jpeg_encoder_handle_t encoder, const jpeg_encode_cfg_t *config,
                              uint8_t *input, size_t input_size, uint8_t *output,
                              size_t capacity, uint32_t *encoded)
{
    (void)encoder;
    const uint16_t *pixels = (const uint16_t *)input;
    const unsigned probes[][2] = {{0, 0}, {config->width - 1, 0},
        {0, config->height - 1}, {config->width - 1, config->height - 1},
        {config->width / 3, config->height / 3}};
    for (unsigned i = 0; i < sizeof(probes) / sizeof(probes[0]); ++i) {
        const unsigned x = probes[i][0], y = probes[i][1];
        const unsigned sx = (config->width - 1 - x) * sensor_width / config->width;
        const unsigned sy = (config->height - 1 - y) * sensor_height / config->height;
        assert(pixels[y * config->width + x] == (sy * sensor_width + sx) % 65521U);
    }
    assert(config->image_quality == 75 && input_size == config->width * config->height * 2U && capacity >= 4);
    jpeg_width = config->width;
    jpeg_height = config->height;
    memcpy(output, "\xff\xd8\xff\xd9", 4);
    *encoded = 4;
    return ESP_OK;
}
esp_err_t jpeg_del_encoder_engine(jpeg_encoder_handle_t encoder) { (void)encoder; return ESP_OK; }
void heap_caps_free(void *memory) { (void)memory; }

static void frame_received(void *context, uint64_t session, ainekio_camera_origin_t origin,
                           uint32_t id, ainekio_camera_resolution_t resolution,
                           uint32_t counter, const uint8_t *jpeg, size_t length)
{
    (void)context;
    assert(jpeg && length == 4 && received_frames < 16);
    const unsigned widths[] = {320, 640, 1024, 1280, 1920}, heights[] = {240, 480, 768, 960, 1080};
    assert(jpeg_width == widths[resolution] && jpeg_height == heights[resolution]);
    assert((sensor_regs[0x3503] & 7U) == 0); /* shutter, gain and VTS stay automatic */
    assert((sensor_regs[0x3a00] & 5U) == 4U); /* night integration, not frozen */
    assert(((sensor_regs[0x3a18] << 8) | sensor_regs[0x3a19]) == 512);
    const unsigned maximum_lines = (sensor_regs[0x3a02] << 8) | sensor_regs[0x3a03];
    assert(maximum_lines == ((sensor_regs[0x3a14] << 8) | sensor_regs[0x3a15]));
    if (origin == AINEKIO_CAMERA_ORIGIN_NONE) {
        const unsigned hts = sensor_width == 1280 ? 1796 : 2271;
        const unsigned pclk = sensor_width == 1280 ? 88333333 : 81666700;
        const unsigned maximum_us = (uint64_t)maximum_lines * hts * 1000000ULL / pclk;
        assert(maximum_us >= 66630 && maximum_us <= 66667);
    } else {
        assert(maximum_lines == (sensor_width == 1280 ? 1093U : 1199U) * 8U - 4U);
    }
    captures[received_frames] = ainekio_p4_media_camera_capture();
    frames[received_frames].session = session;
    frames[received_frames].origin = origin;
    frames[received_frames].id = id;
    frames[received_frames].counter = counter;
    frames[received_frames].resolution = resolution;
    frames[received_frames++].time = clock_us;
    char metadata[256];
    assert(ainekio_encode_camera_meta(resolution, stream_fps, counter, origin, id, metadata, sizeof(metadata)));
    assert(strstr(metadata, origin == AINEKIO_CAMERA_ORIGIN_NONE ? "\"fps\":5" : "\"fps\":0"));
    if (inject_snapshot && received_frames == 1)
        assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 42) == ESP_OK);
    if (received_frames == target_frames) finished = true;
}
static void frame_failed(void *context, uint64_t session, ainekio_camera_origin_t origin, uint32_t id, esp_err_t error)
{ (void)context; (void)session; (void)origin; (void)id; assert(error == ESP_ERR_INVALID_STATE); ++failures_received; }
static void capture(unsigned count)
{
    target_frames = count;
    received_frames = 0;
    finished = count == 0;
    clock_us = 0;
    if (setjmp(scheduler) == 0) camera_task_entry(NULL);
    release_allocations();
    assert(received_frames == count);
}
static void configure(bool on, uint8_t rate, const ainekio_camera_resolution_t *snapshot)
{
    assert(ainekio_p4_media_camera_configure(on, rate, AINEKIO_CAMERA_QVGA, snapshot) == ESP_OK);
    stream_fps = rate;
}

int main(void)
{
    const ainekio_p4_media_callbacks_t callbacks = {.camera_frame=frame_received, .camera_failed=frame_failed};
    assert(p4_camera_start(NULL, &callbacks) == ESP_OK);
    p4_camera_session(7);
    configure(true, 5, NULL);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 1) == ESP_OK);
    capture(2);
    assert(frames[0].resolution == AINEKIO_CAMERA_FHD && frames[1].resolution == AINEKIO_CAMERA_QVGA);
    assert(captures[0].settled && captures[0].settle_ms >= 600 && captures[0].gain_x16 == 16);

    const ainekio_camera_resolution_t xga = AINEKIO_CAMERA_XGA, vga = AINEKIO_CAMERA_VGA, invalid = 99;
    configure(false, 0, &xga);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 2) == ESP_OK);
    capture(1); /* Must finish the iteration without a zero-FPS division. */
    assert(frames[0].resolution == AINEKIO_CAMERA_XGA);

    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 0) == ESP_ERR_INVALID_ARG);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_AUDIO, 0) == ESP_OK);
    capture(1);
    assert(frames[0].origin == AINEKIO_CAMERA_ORIGIN_AUDIO && frames[0].id == 0);
    assert(frames[0].resolution == xga && frames[0].session == 7);


    configure(true, 5, NULL);
    for (unsigned i = 0; i < 3; ++i)
        assert(ainekio_p4_media_snapshot((ainekio_camera_origin_t)(i + 1), i + 3) == ESP_OK);
    capture(4);
    for (unsigned i = 0; i < 3; ++i) assert(frames[i].resolution == xga && frames[i].id == i + 3);
    assert(frames[3].origin == AINEKIO_CAMERA_ORIGIN_NONE && frames[3].resolution == AINEKIO_CAMERA_QVGA);

    inject_snapshot = true;
    capture(3);
    inject_snapshot = false;
    assert(frames[0].origin == AINEKIO_CAMERA_ORIGIN_NONE && frames[1].id == 42);
    assert(frames[2].origin == AINEKIO_CAMERA_ORIGIN_NONE && frames[2].time - frames[1].time == 50000);

    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 6) == ESP_OK);
    configure(true, 5, &vga);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 7) == ESP_OK);
    capture(2);
    assert(frames[0].resolution == xga && frames[1].resolution == vga);

    configure(true, 5, &xga);
    assert(ainekio_p4_media_camera_configure(false, 0, AINEKIO_CAMERA_VGA, &invalid) == ESP_ERR_INVALID_ARG);
    assert(ainekio_p4_media_camera_configure(false, 16, AINEKIO_CAMERA_VGA, &vga) == ESP_ERR_INVALID_ARG);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 8) == ESP_OK);
    capture(2);
    assert(frames[0].resolution == xga && frames[1].resolution == AINEKIO_CAMERA_QVGA);

    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 9) == ESP_OK);
    p4_camera_session(8);
    capture(0);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 10) == ESP_OK);
    capture(1);
    assert(frames[0].session == 8 && frames[0].id == 10 && frames[0].resolution == xga);

    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 11) == ESP_OK);
    ainekio_p4_media_cancel_snapshots();
    assert(failures_received == 1);
    capture(0);

    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 12) == ESP_OK);
    change_session_during_capture = true;
    target_frames = 1; received_frames = 0; finished = false; clock_us = 0;
    if (setjmp(scheduler) == 0) camera_task_entry(NULL);
    release_allocations();
    assert(received_frames == 0);

    const ainekio_camera_resolution_t automatic = AINEKIO_CAMERA_AUTO, native = AINEKIO_CAMERA_960P;
    configure(false, 0, &automatic);
    sensor_gain = 128;
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 13) == ESP_OK);
    capture(1);
    assert(frames[0].resolution == native && captures[0].settled);
    assert(captures[0].exposure_us == 10166 && captures[0].gain_x16 == 128);
    assert(((sensor_regs[0x3a02] << 8) | sensor_regs[0x3a03]) == 1093 * 8 - 4);

    configure(false, 0, &native);
    changing_light = true;
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 14) == ESP_OK);
    capture(1);
    assert(frames[0].resolution == native && !captures[0].settled && captures[0].settle_ms == 4000);
    changing_light = false;
    configure(true, 5, NULL);
    sensor_gain = 32; capture(1);
    const unsigned bright_exposure = captures[0].exposure_us;
    assert(captures[0].gain_x16 == 32);
    changing_light = true; sensor_gain = 512; capture(2);
    assert(captures[0].gain_x16 == 512 && captures[1].gain_x16 == 512);
    assert(captures[0].exposure_us != bright_exposure || captures[1].exposure_us != bright_exposure);
    return 0;
}
