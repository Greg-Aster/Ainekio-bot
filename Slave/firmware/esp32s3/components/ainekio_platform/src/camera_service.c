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

typedef enum {
    CAMERA_COMMAND_CONFIGURE = 0,
    CAMERA_COMMAND_SNAPSHOT,
} camera_command_kind_t;

typedef struct {
    camera_command_kind_t kind;
    bool enabled;
    uint8_t fps;
    ainekio_camera_resolution_t resolution;
    uint32_t sequence;
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
};

static const char *TAG = "ainekio_camera";
static ainekio_camera_service_t singleton;

static framesize_t frame_size(ainekio_camera_resolution_t resolution)
{
    return resolution == AINEKIO_CAMERA_VGA ? FRAMESIZE_VGA : FRAMESIZE_QVGA;
}

static bool set_resolution(
    ainekio_camera_service_t *service,
    ainekio_camera_resolution_t resolution
)
{
    if (resolution > AINEKIO_CAMERA_VGA) {
        return false;
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

static void capture_frame(
    ainekio_camera_service_t *service,
    bool snapshot,
    uint32_t sequence
)
{
    camera_fb_t *frame = esp_camera_fb_get();
    if (frame == NULL || frame->format != PIXFORMAT_JPEG || frame->len < 4U ||
        frame->len > AINEKIO_MAX_JPEG_BYTES) {
        (void)next_counter(service);
        if (service->callbacks.failed != NULL) {
            service->callbacks.failed(
                service->callbacks.context,
                snapshot,
                sequence
            );
        }
        if (frame != NULL) {
            esp_camera_fb_return(frame);
        }
        return;
    }
    const uint32_t counter = next_counter(service);
    if (service->callbacks.frame != NULL) {
        service->callbacks.frame(
            service->callbacks.context,
            snapshot,
            sequence,
            service->resolution,
            counter,
            frame->buf,
            frame->len
        );
    }
    esp_camera_fb_return(frame);
}

static void camera_task(void *argument)
{
    ainekio_camera_service_t *service = argument;
    int64_t next_stream_us = 0;
    while (true) {
        TickType_t wait_ticks = portMAX_DELAY;
        if (service->enabled && service->fps > 0U) {
            const int64_t now = esp_timer_get_time();
            if (next_stream_us == 0 || now >= next_stream_us) {
                capture_frame(service, false, 0U);
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
        camera_command_t command;
        if (xQueueReceive(service->queue, &command, wait_ticks) == pdTRUE) {
            if (command.kind == CAMERA_COMMAND_CONFIGURE) {
                if (!set_resolution(service, command.resolution)) {
                    service->enabled = false;
                    ESP_LOGE(TAG, "camera resolution change failed");
                } else {
                    service->enabled = command.enabled && command.fps > 0U;
                    service->fps = command.fps;
                    next_stream_us = 0;
                }
            } else {
                capture_frame(service, true, command.sequence);
            }
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
        .frame_size = FRAMESIZE_QVGA,
        .jpeg_quality = 10,
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

    ainekio_camera_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));
    service->callbacks = *callbacks;
    service->resolution = AINEKIO_CAMERA_QVGA;
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
    uint32_t sequence
)
{
    if (service == NULL || sequence == 0U) {
        return ESP_ERR_INVALID_ARG;
    }
    const camera_command_t command = {
        .kind = CAMERA_COMMAND_SNAPSHOT,
        .sequence = sequence,
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
