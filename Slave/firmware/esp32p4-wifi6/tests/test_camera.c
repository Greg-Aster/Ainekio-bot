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
static int64_t clock_us;
static unsigned jpeg_width, jpeg_height, stream_fps;
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
int open(const char *path, int flags, ...) { (void)flags; assert(strcmp(path, ESP_VIDEO_MIPI_CSI_DEVICE_NAME) == 0); return 10; }
int close(int fd) { assert(fd == 10); return 0; }
void *mmap(void *address, size_t size, int protection, int flags, int fd, off_t offset)
{ (void)address; (void)protection; (void)flags; (void)offset; assert(fd == 10); return allocate(size); }
int munmap(void *address, size_t size) { (void)address; (void)size; return 0; }
int ioctl(int fd, unsigned long operation, ...)
{
    assert(fd == 10);
    va_list args;
    va_start(args, operation);
    void *argument = va_arg(args, void *);
    va_end(args);
    if (operation == VIDIOC_QUERYBUF) {
        struct v4l2_buffer *buffer = argument;
        buffer->length = 1280U * 960U * 2U;
    } else if (operation == VIDIOC_DQBUF) {
        if (finished) longjmp(scheduler, 1);
        clock_us += 50000;
        struct v4l2_buffer *buffer = argument;
        buffer->index = 0;
        buffer->bytesused = 1280U * 960U * 2U;
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
    (void)encoder; (void)input;
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
    const unsigned widths[] = {320, 640, 1024}, heights[] = {240, 480, 768};
    assert(jpeg_width == widths[resolution] && jpeg_height == heights[resolution]);
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
    assert(frames[0].resolution == AINEKIO_CAMERA_VGA && frames[1].resolution == AINEKIO_CAMERA_QVGA);

    const ainekio_camera_resolution_t xga = AINEKIO_CAMERA_XGA, vga = AINEKIO_CAMERA_VGA, invalid = 99;
    configure(false, 0, &xga);
    assert(ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, 2) == ESP_OK);
    capture(1); /* Must finish the iteration without a zero-FPS division. */
    assert(frames[0].resolution == AINEKIO_CAMERA_XGA);

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
    assert(frames[2].origin == AINEKIO_CAMERA_ORIGIN_NONE && frames[2].time - frames[0].time == 200000);

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
    return 0;
}
