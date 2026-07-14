#include "ainekio/platform/sleep_service.h"

#include <math.h>

#include "ainekio/battery.h"
#include "ainekio/platform/battery_adc.h"
#include "esp_attr.h"
#include "esp_sleep.h"
#include "esp_wifi.h"

#define BATTERY_RECHECK_MARKER UINT32_C(0x41424c56)

static RTC_DATA_ATTR uint32_t battery_recheck_marker;

bool ainekio_sleep_battery_recheck_pending(void)
{
    return esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER &&
           battery_recheck_marker == BATTERY_RECHECK_MARKER;
}

esp_err_t ainekio_sleep_battery_recovered(
    float divider_factor,
    float calibration_factor,
    float *volts,
    bool *recovered
)
{
    if (!isfinite(divider_factor) || divider_factor <= 0.0F || volts == NULL ||
        recovered == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_battery_adc_t adc;
    esp_err_t result = ainekio_battery_adc_init(&adc, divider_factor);
    if (result != ESP_OK) {
        return result;
    }
    ainekio_battery_monitor_t monitor;
    ainekio_battery_init(
        &monitor,
        isfinite(calibration_factor) && calibration_factor > 0.0F
            ? calibration_factor
            : 1.0F
    );
    monitor.state = AINEKIO_BATTERY_CUTOFF;
    for (uint32_t sample_set = 0U;
         sample_set < AINEKIO_BATTERY_QUALIFYING_SETS;
         ++sample_set) {
        ainekio_battery_events_t events = AINEKIO_BATTERY_EVENT_NONE;
        result = ainekio_battery_adc_observe(
            &adc,
            &monitor,
            sample_set,
            &events
        );
        if (result != ESP_OK) {
            break;
        }
    }
    *volts = monitor.volts;
    *recovered = result == ESP_OK && monitor.state == AINEKIO_BATTERY_NORMAL;
    ainekio_battery_adc_deinit(&adc);
    return result;
}

void ainekio_sleep_clear_battery_recheck(void)
{
    battery_recheck_marker = 0U;
}

void ainekio_sleep_enter(uint32_t seconds, bool battery_cutoff)
{
    battery_recheck_marker = battery_cutoff ? BATTERY_RECHECK_MARKER : 0U;
    (void)esp_wifi_stop();
    (void)esp_sleep_enable_timer_wakeup((uint64_t)seconds * UINT64_C(1000000));
    esp_deep_sleep_start();
    __builtin_unreachable();
}
