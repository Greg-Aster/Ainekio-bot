#include "ainekio/platform/telemetry_service.h"

#include <math.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define TELEMETRY_TASK_PRIORITY 2U
#define TELEMETRY_QUIET_WAIT_MS 40U

struct ainekio_telemetry_service {
    ainekio_battery_adc_t adc;
    ainekio_battery_monitor_t battery;
    ainekio_motion_service_t *motion;
    ainekio_telemetry_callbacks_t callbacks;
    TaskHandle_t task;
};

static const char *TAG = "ainekio_telemetry";
static ainekio_telemetry_service_t singleton;

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static TickType_t battery_wait_ticks(
    const ainekio_battery_monitor_t *battery,
    uint32_t now
)
{
    if (!battery->has_sample_time) {
        return 0U;
    }
    const uint32_t elapsed = (uint32_t)(now - battery->last_sample_ms);
    if (elapsed >= AINEKIO_BATTERY_SAMPLE_INTERVAL_MS) {
        return 0U;
    }
    TickType_t wait = pdMS_TO_TICKS(
        AINEKIO_BATTERY_SAMPLE_INTERVAL_MS - elapsed
    );
    return wait > 0U ? wait : 1U;
}

static void telemetry_task(void *argument)
{
    ainekio_telemetry_service_t *service = argument;
    while (true) {
        const uint32_t now = now_ms();
        const TickType_t wait = battery_wait_ticks(&service->battery, now);
        if (wait > 0U) {
            vTaskDelay(wait);
            continue;
        }
        const bool quiet = ainekio_motion_service_begin_quiet_window(
            service->motion,
            pdMS_TO_TICKS(TELEMETRY_QUIET_WAIT_MS)
        );
        if (!quiet) {
            ESP_LOGW(TAG, "motion quiet window acknowledgement timed out");
        }
        ainekio_battery_events_t events = AINEKIO_BATTERY_EVENT_NONE;
        const ainekio_battery_state_t previous_state = service->battery.state;
        const esp_err_t result = ainekio_battery_adc_observe(
            &service->adc,
            &service->battery,
            now,
            &events
        );
        if (quiet) {
            ainekio_motion_service_end_quiet_window(service->motion);
        }
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "battery sample failed: %s", esp_err_to_name(result));
            vTaskDelay(pdMS_TO_TICKS(100U));
        } else if (service->callbacks.battery != NULL) {
            if (previous_state != service->battery.state &&
                service->battery.state == AINEKIO_BATTERY_DISCONNECTED) {
                ESP_LOGI(
                    TAG,
                    "battery input disconnected at %.3f V; USB-only operation remains enabled",
                    (double)service->battery.volts
                );
            } else if (previous_state == AINEKIO_BATTERY_DISCONNECTED &&
                       service->battery.state != AINEKIO_BATTERY_DISCONNECTED) {
                ESP_LOGI(
                    TAG,
                    "battery input detected at %.3f V; low-voltage protection armed",
                    (double)service->battery.volts
                );
            }
            service->callbacks.battery(
                service->callbacks.context,
                service->battery.volts,
                service->battery.state,
                events
            );
        }
    }
}

esp_err_t ainekio_telemetry_service_start(
    float divider_factor,
    float calibration_factor,
    ainekio_motion_service_t *motion,
    const ainekio_telemetry_callbacks_t *callbacks,
    ainekio_telemetry_service_t **service_output
)
{
    if (!isfinite(divider_factor) || divider_factor <= 0.0F || motion == NULL ||
        service_output == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_telemetry_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));
    service->motion = motion;
    if (callbacks != NULL) {
        service->callbacks = *callbacks;
    }
    ainekio_battery_init(
        &service->battery,
        isfinite(calibration_factor) && calibration_factor > 0.0F
            ? calibration_factor
            : 1.0F
    );
    esp_err_t result = ainekio_battery_adc_init(&service->adc, divider_factor);
    if (result != ESP_OK) {
        return result;
    }
    if (xTaskCreate(
            telemetry_task,
            "telemetry",
            3072U,
            service,
            TELEMETRY_TASK_PRIORITY,
            &service->task
        ) != pdPASS) {
        ainekio_battery_adc_deinit(&service->adc);
        return ESP_ERR_NO_MEM;
    }
    *service_output = service;
    return ESP_OK;
}
