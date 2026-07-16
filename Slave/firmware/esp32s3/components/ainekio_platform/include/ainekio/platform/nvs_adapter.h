#ifndef AINEKIO_PLATFORM_NVS_ADAPTER_H
#define AINEKIO_PLATFORM_NVS_ADAPTER_H

#include <stdbool.h>

#include "ainekio/config_store.h"
#include "ainekio/settings.h"
#include "esp_err.h"

typedef struct {
    bool partition_erased_during_init;
} ainekio_nvs_adapter_t;

#define AINEKIO_SETUP_HASH_BYTES 32U

esp_err_t ainekio_nvs_adapter_init(ainekio_nvs_adapter_t *adapter);
ainekio_config_store_port_t ainekio_nvs_adapter_port(ainekio_nvs_adapter_t *adapter);
esp_err_t ainekio_nvs_adapter_erase_config_namespaces(void);
esp_err_t ainekio_nvs_adapter_store_setup_hash(
    const uint8_t hash[AINEKIO_SETUP_HASH_BYTES]
);
esp_err_t ainekio_nvs_adapter_read_setup_hash(
    uint8_t hash[AINEKIO_SETUP_HASH_BYTES]
);
esp_err_t ainekio_nvs_adapter_load_calibration(
    ainekio_servo_bank_t *servos,
    bool *recovered
);
esp_err_t ainekio_nvs_adapter_save_calibration(const ainekio_servo_bank_t *servos);
esp_err_t ainekio_nvs_adapter_load_poses(
    ainekio_pose_bank_t *poses,
    bool *recovered
);
esp_err_t ainekio_nvs_adapter_save_poses(const ainekio_pose_bank_t *poses);
esp_err_t ainekio_nvs_adapter_load_preferences(
    ainekio_profile_t *profile,
    float *adc_factor,
    bool *recovered
);
esp_err_t ainekio_nvs_adapter_save_profile(ainekio_profile_t profile);
esp_err_t ainekio_nvs_adapter_save_adc_factor(float adc_factor);
esp_err_t ainekio_nvs_adapter_load_wake_preferences(
    bool *enabled,
    char model[AINEKIO_WAKE_MODEL_MAX + 1U],
    bool *recovered
);
esp_err_t ainekio_nvs_adapter_save_wake_preferences(
    bool enabled,
    const char *model
);

#endif
