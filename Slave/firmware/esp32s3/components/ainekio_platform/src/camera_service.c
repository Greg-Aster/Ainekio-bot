#include "ainekio/platform/camera_service.h"

#include <string.h>

#include "ainekio/binary_codec.h"
#include "ainekio/platform/pin_map.h"
#include "esp_camera.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sensor.h"

#define CAMERA_COMMAND_QUEUE_LENGTH 4U
#define CAMERA_XCLK_HZ 10000000
#define CAMERA_JPEG_QUALITY 10
#define CAMERA_SNAPSHOT_WIDTH 1024U
#define CAMERA_SNAPSHOT_HEIGHT 768U
/*
 * The pinned OV3660 profile uses 2,300 clocks per XGA line and a 10 MHz
 * pixel clock. A 72-line exposure is therefore approximately 16.6 ms (1/60 s),
 * short enough to reduce motion blur while aligning with 60 Hz indoor light.
 * Moderate manual sensor gain makes the first frame usable immediately without
 * exposing the fixed-pattern noise seen at the driver's upper gain range.
 */
#define CAMERA_FAST_EXPOSURE_LINES 72
#define CAMERA_FAST_SENSOR_GAIN 24
#define CAMERA_FAST_BRIGHTNESS 1
#define CAMERA_FAST_DENOISE 3
#define CAMERA_FAST_SHARPNESS 0

typedef enum {
    CAMERA_COMMAND_CONFIGURE = 0,
    CAMERA_COMMAND_SNAPSHOT,
} camera_command_kind_t;

typedef struct {
    camera_command_kind_t kind;
    bool enabled;
    uint8_t fps;
    ainekio_camera_resolution_t resolution;
    ainekio_camera_origin_t origin;
    uint32_t origin_id;
} camera_command_t;

struct ainekio_camera_service {
    ainekio_camera_callbacks_t callbacks;
    QueueHandle_t queue;
    TaskHandle_t task;
    portMUX_TYPE counter_lock;
    uint32_t counter;
    bool enabled;
    uint8_t fps;
    ainekio_camera_resolution_t resolution;
    camera_fb_t *held_frame;
};

static const char *TAG = "ainekio_camera";
static ainekio_camera_service_t singleton;

static esp_err_t configure_fast_capture_profile(sensor_t *sensor)
{
    if (sensor == NULL || sensor->set_aec2 == NULL ||
        sensor->set_exposure_ctrl == NULL || sensor->set_aec_value == NULL ||
        sensor->set_gain_ctrl == NULL || sensor->set_agc_gain == NULL ||
        sensor->set_brightness == NULL || sensor->set_denoise == NULL ||
        sensor->set_sharpness == NULL) {
        return ESP_ERR_NOT_SUPPORTED;
    }

    /*
     * Night mode and automatic exposure can lengthen the first exposure and
     * blur an action-correlated image. Use a deterministic fast shutter and
     * moderate sensor gain instead; denoise limits amplified sensor patterning
     * and sharpening remains neutral so it cannot emphasize that pattern.
     */
    if (sensor->set_aec2(sensor, 0) != 0 ||
        sensor->set_exposure_ctrl(sensor, 0) != 0 ||
        sensor->set_aec_value(sensor, CAMERA_FAST_EXPOSURE_LINES) != 0 ||
        sensor->set_gain_ctrl(sensor, 0) != 0 ||
        sensor->set_agc_gain(sensor, CAMERA_FAST_SENSOR_GAIN) != 0 ||
        sensor->set_brightness(sensor, CAMERA_FAST_BRIGHTNESS) != 0 ||
        sensor->set_denoise(sensor, CAMERA_FAST_DENOISE) != 0 ||
        sensor->set_sharpness(sensor, CAMERA_FAST_SHARPNESS) != 0) {
        return ESP_FAIL;
    }

    ESP_LOGI(
        TAG,
        "fast capture profile exposure_lines=%d gain=%d brightness=%d "
        "denoise=%d sharpness=%d",
        CAMERA_FAST_EXPOSURE_LINES,
        CAMERA_FAST_SENSOR_GAIN,
        CAMERA_FAST_BRIGHTNESS,
        CAMERA_FAST_DENOISE,
        CAMERA_FAST_SHARPNESS
    );
    return ESP_OK;
}

static framesize_t frame_size(ainekio_camera_resolution_t resolution)
{
    switch (resolution) {
    case AINEKIO_CAMERA_QVGA:
        return FRAMESIZE_QVGA;
    case AINEKIO_CAMERA_VGA:
        return FRAMESIZE_VGA;
    case AINEKIO_CAMERA_XGA:
        return FRAMESIZE_XGA;
    default:
        return FRAMESIZE_INVALID;
    }
}

static bool set_resolution(
    ainekio_camera_service_t *service,
    ainekio_camera_resolution_t resolution
)
{
    if (resolution > AINEKIO_CAMERA_XGA) {
        return false;
    }
    if (service->resolution == resolution) {
        return true;
    }
    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor == NULL || sensor->set_framesize(sensor, frame_size(resolution)) != 0) {
        return false;
    }
    service->resolution = resolution;
    return true;
}

static uint32_t next_counter(ainekio_camera_service_t *service)
{
    taskENTER_CRITICAL(&service->counter_lock);
    const uint32_t counter = service->counter++;
    taskEXIT_CRITICAL(&service->counter_lock);
    return counter;
}

static void fail_capture(
    ainekio_camera_service_t *service,
    ainekio_camera_origin_t origin,
    uint32_t origin_id
)
{
    (void)next_counter(service);
    if (service->callbacks.failed != NULL) {
        service->callbacks.failed(
            service->callbacks.context,
            origin,
            origin_id
        );
    }
}

static void capture_frame(
    ainekio_camera_service_t *service,
    ainekio_camera_origin_t origin,
    uint32_t origin_id
)
{
    const bool snapshot = origin != AINEKIO_CAMERA_ORIGIN_NONE;
    /*
     * Keep the single framebuffer checked out between captures. Returning it
     * here wakes the sensor for one new frame, so an explicit snapshot or
     * preview interval receives a fresh image instead of the driver's queued
     * frame from the previous interval. This also leaves the capture engine
     * idle while streaming is disabled without allocating a second buffer.
     */
    if (service->held_frame != NULL) {
        esp_camera_fb_return(service->held_frame);
        service->held_frame = NULL;
    }
    camera_fb_t *frame = esp_camera_fb_get();
    service->held_frame = frame;
    if (frame == NULL || frame->format != PIXFORMAT_JPEG || frame->len < 4U ||
        frame->len > AINEKIO_MAX_JPEG_BYTES) {
        fail_capture(service, origin, origin_id);
        return;
    }
    if (snapshot &&
        (frame->width != CAMERA_SNAPSHOT_WIDTH ||
         frame->height != CAMERA_SNAPSHOT_HEIGHT)) {
        ESP_LOGE(
            TAG,
            "snapshot dimensions invalid: %ux%u",
            (unsigned int)frame->width,
            (unsigned int)frame->height
        );
        fail_capture(service, origin, origin_id);
        return;
    }
    const uint32_t counter = next_counter(service);
    if (service->callbacks.frame != NULL) {
        service->callbacks.frame(
            service->callbacks.context,
            origin,
            origin_id,
            service->resolution,
            counter,
            frame->buf,
            frame->len
        );
    }
    if (snapshot) {
        const int64_t captured_us =
            (int64_t)frame->timestamp.tv_sec * INT64_C(1000000) +
            frame->timestamp.tv_usec;
        const int64_t age_us = esp_timer_get_time() - captured_us;
        ESP_LOGI(
            TAG,
            "snapshot XGA %ux%u bytes=%u age_ms=%lld",
            (unsigned int)frame->width,
            (unsigned int)frame->height,
            (unsigned int)frame->len,
            (long long)(age_us > 0 ? age_us / 1000 : 0)
        );
    }
}

static void process_command(
    ainekio_camera_service_t *service,
    const camera_command_t *command,
    int64_t *next_stream_us
)
{
    if (command->kind == CAMERA_COMMAND_CONFIGURE) {
        if (!set_resolution(service, command->resolution)) {
            service->enabled = false;
            ESP_LOGE(TAG, "camera resolution change failed");
        } else {
            service->enabled = command->enabled && command->fps > 0U;
            service->fps = command->fps;
            *next_stream_us = 0;
        }
        return;
    }

    const bool restore_preview = service->enabled && service->fps > 0U;
    const ainekio_camera_resolution_t preview_resolution = service->resolution;
    if (!set_resolution(service, AINEKIO_CAMERA_XGA)) {
        ESP_LOGE(TAG, "snapshot XGA resolution change failed");
        fail_capture(service, command->origin, command->origin_id);
        return;
    }
    capture_frame(service, command->origin, command->origin_id);
    if (restore_preview && !set_resolution(service, preview_resolution)) {
        service->enabled = false;
        ESP_LOGE(TAG, "camera preview resolution restore failed");
    }
}

static void camera_task(void *argument)
{
    ainekio_camera_service_t *service = argument;
    int64_t next_stream_us = 0;

    /*
     * The driver fills one frame immediately after initialization. Hold that
     * frame so the sensor is quiescent until a command requests a fresh one.
     */
    service->held_frame = esp_camera_fb_get();
    if (service->held_frame == NULL) {
        ESP_LOGE(TAG, "initial camera frame unavailable");
    }

    while (true) {
        camera_command_t command;
        if (xQueueReceive(service->queue, &command, 0U) == pdTRUE) {
            process_command(service, &command, &next_stream_us);
            continue;
        }

        TickType_t wait_ticks = portMAX_DELAY;
        if (service->enabled && service->fps > 0U) {
            const int64_t now = esp_timer_get_time();
            if (next_stream_us == 0 || now >= next_stream_us) {
                capture_frame(
                    service,
                    AINEKIO_CAMERA_ORIGIN_NONE,
                    0U
                );
                next_stream_us = now + INT64_C(1000000) / service->fps;
                continue;
            }
            const uint64_t wait_ms =
                (uint64_t)(next_stream_us - now + INT64_C(999)) / 1000U;
            wait_ticks = pdMS_TO_TICKS(wait_ms);
            if (wait_ticks == 0U) {
                wait_ticks = 1U;
            }
        }
        if (xQueueReceive(service->queue, &command, wait_ticks) == pdTRUE) {
            process_command(service, &command, &next_stream_us);
            continue;
        }
    }
}

esp_err_t ainekio_camera_service_start(
    const ainekio_camera_callbacks_t *callbacks,
    ainekio_camera_service_t **service_output
)
{
    if (callbacks == NULL || callbacks->frame == NULL || service_output == NULL ||
        !ainekio_pin_map_valid()) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!esp_psram_is_initialized() ||
        esp_psram_get_size() < AINEKIO_EXPECTED_PSRAM_BYTES) {
        return ESP_ERR_INVALID_SIZE;
    }

    const camera_config_t config = {
        .pin_pwdn = AINEKIO_PIN_CAMERA_PWDN,
        .pin_reset = AINEKIO_PIN_CAMERA_RESET,
        .pin_xclk = AINEKIO_PIN_CAMERA_XCLK,
        .pin_sccb_sda = AINEKIO_PIN_CAMERA_SCCB_SDA,
        .pin_sccb_scl = AINEKIO_PIN_CAMERA_SCCB_SCL,
        .pin_d7 = AINEKIO_PIN_CAMERA_D7,
        .pin_d6 = AINEKIO_PIN_CAMERA_D6,
        .pin_d5 = AINEKIO_PIN_CAMERA_D5,
        .pin_d4 = AINEKIO_PIN_CAMERA_D4,
        .pin_d3 = AINEKIO_PIN_CAMERA_D3,
        .pin_d2 = AINEKIO_PIN_CAMERA_D2,
        .pin_d1 = AINEKIO_PIN_CAMERA_D1,
        .pin_d0 = AINEKIO_PIN_CAMERA_D0,
        .pin_vsync = AINEKIO_PIN_CAMERA_VSYNC,
        .pin_href = AINEKIO_PIN_CAMERA_HREF,
        .pin_pclk = AINEKIO_PIN_CAMERA_PCLK,
        .xclk_freq_hz = CAMERA_XCLK_HZ,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        /*
         * The driver sizes its only PSRAM framebuffer at initialization.
         * Initialize at the largest supported still size so later XGA captures
         * cannot inherit a QVGA-sized buffer.
         */
        .frame_size = FRAMESIZE_XGA,
        .jpeg_quality = CAMERA_JPEG_QUALITY,
        .fb_count = 1,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
    };
    ESP_RETURN_ON_ERROR(esp_camera_init(&config), TAG, "camera init failed");

    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor == NULL || sensor->id.PID != OV3660_PID) {
        (void)esp_camera_deinit();
        return ESP_ERR_NOT_SUPPORTED;
    }
    esp_err_t profile_result = configure_fast_capture_profile(sensor);
    if (profile_result != ESP_OK) {
        ESP_LOGE(
            TAG,
            "fast capture profile failed: %s",
            esp_err_to_name(profile_result)
        );
        (void)esp_camera_deinit();
        return profile_result;
    }

    ainekio_camera_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));
    service->callbacks = *callbacks;
    service->resolution = AINEKIO_CAMERA_XGA;
    service->counter_lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    service->queue = xQueueCreate(
        CAMERA_COMMAND_QUEUE_LENGTH,
        sizeof(camera_command_t)
    );
    if (service->queue == NULL) {
        (void)esp_camera_deinit();
        return ESP_ERR_NO_MEM;
    }
    if (xTaskCreatePinnedToCore(
            camera_task,
            "camera",
            4096U,
            service,
            6U,
            &service->task,
            0
        ) != pdPASS) {
        vQueueDelete(service->queue);
        service->queue = NULL;
        (void)esp_camera_deinit();
        return ESP_ERR_NO_MEM;
    }
    *service_output = service;
    ESP_LOGI(
        TAG,
        "OV3660 ready profile=%s psram=%u",
        AINEKIO_BOARD_PROFILE_ID,
        (unsigned int)esp_psram_get_size()
    );
    return ESP_OK;
}

esp_err_t ainekio_camera_configure(
    ainekio_camera_service_t *service,
    bool enabled,
    uint8_t fps,
    ainekio_camera_resolution_t resolution
)
{
    if (service == NULL || fps > 15U || resolution > AINEKIO_CAMERA_VGA) {
        return ESP_ERR_INVALID_ARG;
    }
    const camera_command_t command = {
        .kind = CAMERA_COMMAND_CONFIGURE,
        .enabled = enabled,
        .fps = fps,
        .resolution = resolution,
    };
    return xQueueSend(service->queue, &command, 0U) == pdTRUE ? ESP_OK
                                                              : ESP_ERR_TIMEOUT;
}

esp_err_t ainekio_camera_snapshot(
    ainekio_camera_service_t *service,
    ainekio_camera_origin_t origin,
    uint32_t origin_id
)
{
    if (service == NULL || origin == AINEKIO_CAMERA_ORIGIN_NONE ||
        origin > AINEKIO_CAMERA_ORIGIN_AUDIO ||
        ((origin == AINEKIO_CAMERA_ORIGIN_REQUEST ||
          origin == AINEKIO_CAMERA_ORIGIN_ACTION) &&
         (origin_id == 0U || origin_id > AINEKIO_MAX_SEQUENCE))) {
        return ESP_ERR_INVALID_ARG;
    }
    const camera_command_t command = {
        .kind = CAMERA_COMMAND_SNAPSHOT,
        .origin = origin,
        .origin_id = origin_id,
    };
    return xQueueSend(service->queue, &command, 0U) == pdTRUE ? ESP_OK
                                                              : ESP_ERR_TIMEOUT;
}

uint32_t ainekio_camera_counter_base(const ainekio_camera_service_t *service)
{
    if (service == NULL) {
        return 0U;
    }
    ainekio_camera_service_t *mutable_service = (ainekio_camera_service_t *)service;
    taskENTER_CRITICAL(&mutable_service->counter_lock);
    const uint32_t counter = mutable_service->counter;
    taskEXIT_CRITICAL(&mutable_service->counter_lock);
    return counter;
}
