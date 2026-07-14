#ifndef AINEKIO_PLATFORM_BATTERY_ADC_H
#define AINEKIO_PLATFORM_BATTERY_ADC_H

#include "ainekio/battery.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"

typedef struct {
    adc_oneshot_unit_handle_t unit;
    adc_cali_handle_t calibration;
    float divider_factor;
    bool initialized;
} ainekio_battery_adc_t;

esp_err_t ainekio_battery_adc_init(
    ainekio_battery_adc_t *adapter,
    float divider_factor
);
esp_err_t ainekio_battery_adc_observe(
    ainekio_battery_adc_t *adapter,
    ainekio_battery_monitor_t *monitor,
    uint32_t now_ms,
    ainekio_battery_events_t *events
);
void ainekio_battery_adc_deinit(ainekio_battery_adc_t *adapter);

#endif
