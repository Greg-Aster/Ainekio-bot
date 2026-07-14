#include "ainekio/platform/battery_adc.h"

#include <math.h>
#include <string.h>

#include "ainekio/platform/pin_map.h"
#include "esp_adc/adc_cali_scheme.h"
#include "soc/adc_channel.h"
#include "soc/soc_caps.h"

#define AINEKIO_BATTERY_ADC_CHANNEL ADC_CHANNEL_2
#define AINEKIO_BATTERY_ADC_ATTENUATION ADC_ATTEN_DB_12

_Static_assert(ADC1_CHANNEL_2_GPIO_NUM == AINEKIO_PIN_BATTERY_ADC,
               "battery ADC channel no longer maps to GPIO3");

esp_err_t ainekio_battery_adc_init(
    ainekio_battery_adc_t *adapter,
    float divider_factor
)
{
    if (adapter == NULL || !isfinite(divider_factor) || divider_factor <= 0.0F) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(adapter, 0, sizeof(*adapter));
    adapter->divider_factor = divider_factor;
    const adc_oneshot_unit_init_cfg_t unit_config = {
        .unit_id = ADC_UNIT_1,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    esp_err_t result = adc_oneshot_new_unit(&unit_config, &adapter->unit);
    if (result != ESP_OK) {
        return result;
    }
    const adc_oneshot_chan_cfg_t channel_config = {
        .atten = AINEKIO_BATTERY_ADC_ATTENUATION,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    result = adc_oneshot_config_channel(
        adapter->unit,
        AINEKIO_BATTERY_ADC_CHANNEL,
        &channel_config
    );
    if (result != ESP_OK) {
        return result;
    }
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    const adc_cali_curve_fitting_config_t calibration_config = {
        .unit_id = ADC_UNIT_1,
        .chan = AINEKIO_BATTERY_ADC_CHANNEL,
        .atten = AINEKIO_BATTERY_ADC_ATTENUATION,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    result = adc_cali_create_scheme_curve_fitting(
        &calibration_config,
        &adapter->calibration
    );
#else
    result = ESP_ERR_NOT_SUPPORTED;
#endif
    if (result != ESP_OK) {
        return result;
    }
    adapter->initialized = true;
    return ESP_OK;
}

esp_err_t ainekio_battery_adc_observe(
    ainekio_battery_adc_t *adapter,
    ainekio_battery_monitor_t *monitor,
    uint32_t now_ms,
    ainekio_battery_events_t *events
)
{
    if (adapter == NULL || monitor == NULL || events == NULL ||
        !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    float samples[AINEKIO_BATTERY_MIN_SAMPLES];
    for (size_t index = 0U; index < AINEKIO_BATTERY_MIN_SAMPLES; ++index) {
        int millivolts = 0;
        const esp_err_t result = adc_oneshot_get_calibrated_result(
            adapter->unit,
            adapter->calibration,
            AINEKIO_BATTERY_ADC_CHANNEL,
            &millivolts
        );
        if (result != ESP_OK) {
            return result;
        }
        samples[index] = ((float)millivolts / 1000.0F) * adapter->divider_factor;
    }
    *events = ainekio_battery_observe(
        monitor,
        samples,
        AINEKIO_BATTERY_MIN_SAMPLES,
        now_ms
    );
    return ESP_OK;
}

void ainekio_battery_adc_deinit(ainekio_battery_adc_t *adapter)
{
    if (adapter == NULL) {
        return;
    }
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    if (adapter->calibration != NULL) {
        (void)adc_cali_delete_scheme_curve_fitting(adapter->calibration);
    }
#endif
    if (adapter->unit != NULL) {
        (void)adc_oneshot_del_unit(adapter->unit);
    }
    memset(adapter, 0, sizeof(*adapter));
}
