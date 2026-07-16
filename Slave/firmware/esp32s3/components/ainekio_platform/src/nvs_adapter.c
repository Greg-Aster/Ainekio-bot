#include "ainekio/platform/nvs_adapter.h"

#include <math.h>
#include <string.h>

#include "ainekio/assets.h"
#include "ainekio/config_schema.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *slot_namespace(ainekio_config_slot_t slot)
{
    if (slot == AINEKIO_CONFIG_SLOT_A) {
        return AINEKIO_NVS_NAMESPACE_CONFIG_A;
    }
    if (slot == AINEKIO_CONFIG_SLOT_B) {
        return AINEKIO_NVS_NAMESPACE_CONFIG_B;
    }
    return NULL;
}

static ainekio_store_result_t store_result(esp_err_t error)
{
    if (error == ESP_OK) {
        return AINEKIO_STORE_OK;
    }
    if (error == ESP_ERR_NVS_NOT_FOUND) {
        return AINEKIO_STORE_NOT_FOUND;
    }
    if (error == ESP_ERR_NVS_INVALID_LENGTH || error == ESP_ERR_NVS_TYPE_MISMATCH) {
        return AINEKIO_STORE_CORRUPT;
    }
    return AINEKIO_STORE_IO_ERROR;
}

static esp_err_t get_bounded_string(
    nvs_handle_t handle,
    const char *key,
    char *destination,
    size_t capacity
)
{
    size_t required = capacity;
    const esp_err_t error = nvs_get_str(handle, key, destination, &required);
    if (error == ESP_OK && (required == 0U || required > capacity)) {
        return ESP_ERR_NVS_INVALID_LENGTH;
    }
    return error;
}

static ainekio_store_result_t read_meta_port(
    void *context,
    ainekio_config_meta_t *meta
)
{
    (void)context;
    nvs_handle_t handle;
    esp_err_t error = nvs_open(
        AINEKIO_NVS_NAMESPACE_META,
        NVS_READONLY,
        &handle
    );
    if (error != ESP_OK) {
        return store_result(error);
    }

    uint8_t active_slot = 0U;
    error = nvs_get_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, &meta->schema_version);
    if (error == ESP_OK) {
        error = nvs_get_u8(handle, AINEKIO_NVS_KEY_ACTIVE_SLOT, &active_slot);
    }
    nvs_close(handle);
    meta->active_slot = (ainekio_config_slot_t)active_slot;
    return store_result(error);
}

static ainekio_store_result_t write_meta_port(
    void *context,
    const ainekio_config_meta_t *meta
)
{
    (void)context;
    nvs_handle_t handle;
    esp_err_t error = nvs_open(
        AINEKIO_NVS_NAMESPACE_META,
        NVS_READWRITE,
        &handle
    );
    if (error != ESP_OK) {
        return store_result(error);
    }
    error = nvs_set_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, meta->schema_version);
    if (error == ESP_OK) {
        error = nvs_set_u8(
            handle,
            AINEKIO_NVS_KEY_ACTIVE_SLOT,
            (uint8_t)meta->active_slot
        );
    }
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    return store_result(error);
}

static ainekio_store_result_t read_record_port(
    void *context,
    ainekio_config_slot_t slot,
    ainekio_config_record_t *record
)
{
    (void)context;
    const char *namespace_name = slot_namespace(slot);
    if (namespace_name == NULL) {
        return AINEKIO_STORE_CORRUPT;
    }
    nvs_handle_t handle;
    esp_err_t error = nvs_open(namespace_name, NVS_READONLY, &handle);
    if (error != ESP_OK) {
        return store_result(error);
    }

    memset(record, 0, sizeof(*record));
    uint8_t complete = 0U;
    error = nvs_get_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, &record->schema_version);
    if (error == ESP_OK) {
        error = nvs_get_u32(handle, AINEKIO_NVS_KEY_GENERATION, &record->generation);
    }
    if (error == ESP_OK) {
        error = nvs_get_u8(handle, AINEKIO_NVS_KEY_COMPLETE, &complete);
    }
    if (error == ESP_OK) {
        error = get_bounded_string(
            handle,
            AINEKIO_NVS_KEY_WIFI_SSID,
            record->wifi_ssid,
            sizeof(record->wifi_ssid)
        );
    }
    if (error == ESP_OK) {
        error = get_bounded_string(
            handle,
            AINEKIO_NVS_KEY_WIFI_PSK,
            record->wifi_psk,
            sizeof(record->wifi_psk)
        );
    }
    if (error == ESP_OK) {
        error = get_bounded_string(
            handle,
            AINEKIO_NVS_KEY_ENDPOINT_URL,
            record->endpoint_url,
            sizeof(record->endpoint_url)
        );
    }
    if (error == ESP_OK) {
        error = get_bounded_string(
            handle,
            AINEKIO_NVS_KEY_ROBOT_ID,
            record->robot_id,
            sizeof(record->robot_id)
        );
    }
    if (error == ESP_OK) {
        error = get_bounded_string(
            handle,
            AINEKIO_NVS_KEY_ROBOT_TOKEN,
            record->robot_token,
            sizeof(record->robot_token)
        );
    }
    nvs_close(handle);
    record->complete = complete == 1U;
    return store_result(error);
}

static ainekio_store_result_t write_record_port(
    void *context,
    ainekio_config_slot_t slot,
    const ainekio_config_record_t *record
)
{
    (void)context;
    const char *namespace_name = slot_namespace(slot);
    if (namespace_name == NULL) {
        return AINEKIO_STORE_CORRUPT;
    }
    nvs_handle_t handle;
    esp_err_t error = nvs_open(namespace_name, NVS_READWRITE, &handle);
    if (error != ESP_OK) {
        return store_result(error);
    }

    error = nvs_erase_all(handle);
    if (error == ESP_OK) {
        error = nvs_set_u8(handle, AINEKIO_NVS_KEY_COMPLETE, 0U);
    }
    if (error == ESP_OK) {
        error = nvs_set_u32(
            handle,
            AINEKIO_NVS_KEY_SCHEMA_VERSION,
            record->schema_version
        );
    }
    if (error == ESP_OK) {
        error = nvs_set_u32(handle, AINEKIO_NVS_KEY_GENERATION, record->generation);
    }
    if (error == ESP_OK) {
        error = nvs_set_str(handle, AINEKIO_NVS_KEY_WIFI_SSID, record->wifi_ssid);
    }
    if (error == ESP_OK) {
        error = nvs_set_str(handle, AINEKIO_NVS_KEY_WIFI_PSK, record->wifi_psk);
    }
    if (error == ESP_OK) {
        error = nvs_set_str(
            handle,
            AINEKIO_NVS_KEY_ENDPOINT_URL,
            record->endpoint_url
        );
    }
    if (error == ESP_OK) {
        error = nvs_set_str(handle, AINEKIO_NVS_KEY_ROBOT_ID, record->robot_id);
    }
    if (error == ESP_OK) {
        error = nvs_set_str(handle, AINEKIO_NVS_KEY_ROBOT_TOKEN, record->robot_token);
    }
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    if (error == ESP_OK) {
        error = nvs_set_u8(handle, AINEKIO_NVS_KEY_COMPLETE, 1U);
    }
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    return store_result(error);
}

static ainekio_store_result_t erase_record_port(
    void *context,
    ainekio_config_slot_t slot
)
{
    (void)context;
    const char *namespace_name = slot_namespace(slot);
    if (namespace_name == NULL) {
        return AINEKIO_STORE_CORRUPT;
    }
    nvs_handle_t handle;
    esp_err_t error = nvs_open(namespace_name, NVS_READWRITE, &handle);
    if (error != ESP_OK) {
        return store_result(error);
    }
    error = nvs_erase_all(handle);
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    return store_result(error);
}

esp_err_t ainekio_nvs_adapter_init(ainekio_nvs_adapter_t *adapter)
{
    memset(adapter, 0, sizeof(*adapter));
    esp_err_t error = nvs_flash_init();
    if (error == ESP_ERR_NVS_NO_FREE_PAGES || error == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        error = nvs_flash_erase();
        if (error != ESP_OK) {
            return error;
        }
        adapter->partition_erased_during_init = true;
        error = nvs_flash_init();
    }
    return error;
}

ainekio_config_store_port_t ainekio_nvs_adapter_port(ainekio_nvs_adapter_t *adapter)
{
    return (ainekio_config_store_port_t){
        .context = adapter,
        .read_meta = read_meta_port,
        .write_meta = write_meta_port,
        .read_record = read_record_port,
        .write_record = write_record_port,
        .erase_record = erase_record_port,
    };
}

esp_err_t ainekio_nvs_adapter_erase_config_namespaces(void)
{
    const char *namespaces[] = {
        AINEKIO_NVS_NAMESPACE_META,
        AINEKIO_NVS_NAMESPACE_CONFIG_A,
        AINEKIO_NVS_NAMESPACE_CONFIG_B,
    };
    for (size_t index = 0U; index < sizeof(namespaces) / sizeof(namespaces[0]); ++index) {
        nvs_handle_t handle;
        esp_err_t error = nvs_open(namespaces[index], NVS_READWRITE, &handle);
        if (error != ESP_OK) {
            return error;
        }
        error = nvs_erase_all(handle);
        if (error == ESP_OK) {
            error = nvs_commit(handle);
        }
        nvs_close(handle);
        if (error != ESP_OK) {
            return error;
        }
    }
    return ESP_OK;
}

esp_err_t ainekio_nvs_adapter_store_setup_hash(
    const uint8_t hash[AINEKIO_SETUP_HASH_BYTES]
)
{
    if (hash == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_META, NVS_READWRITE, &handle);
    if (error != ESP_OK) {
        return error;
    }
    error = nvs_set_blob(
        handle,
        AINEKIO_NVS_KEY_SETUP_HASH,
        hash,
        AINEKIO_SETUP_HASH_BYTES
    );
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    return error;
}

esp_err_t ainekio_nvs_adapter_read_setup_hash(
    uint8_t hash[AINEKIO_SETUP_HASH_BYTES]
)
{
    if (hash == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_META, NVS_READONLY, &handle);
    if (error != ESP_OK) {
        return error;
    }
    size_t size = AINEKIO_SETUP_HASH_BYTES;
    error = nvs_get_blob(handle, AINEKIO_NVS_KEY_SETUP_HASH, hash, &size);
    nvs_close(handle);
    return error == ESP_OK && size != AINEKIO_SETUP_HASH_BYTES
               ? ESP_ERR_NVS_INVALID_LENGTH
               : error;
}

static esp_err_t reset_namespace(const char *namespace_name)
{
    nvs_handle_t handle;
    esp_err_t error = nvs_open(namespace_name, NVS_READWRITE, &handle);
    if (error != ESP_OK) {
        return error;
    }
    error = nvs_erase_all(handle);
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    return error;
}

static esp_err_t write_schema(nvs_handle_t handle)
{
    return nvs_set_u32(
        handle,
        AINEKIO_NVS_KEY_SCHEMA_VERSION,
        AINEKIO_NVS_SCHEMA_VERSION
    );
}

esp_err_t ainekio_nvs_adapter_save_calibration(const ainekio_servo_bank_t *servos)
{
    if (!ainekio_servo_bank_calibration_valid(servos)) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_servo_calibration_t values[AINEKIO_SERVO_COUNT];
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        values[index] = servos->channels[index].calibration;
    }
    nvs_handle_t handle = 0U;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_CALIBRATION, NVS_READWRITE, &handle);
    if (error == ESP_OK) {
        error = write_schema(handle);
    }
    if (error == ESP_OK) {
        error = nvs_set_blob(handle, AINEKIO_NVS_KEY_SERVO_CALIBRATION,
                             values, sizeof(values));
    }
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    if (handle != 0U) {
        nvs_close(handle);
    }
    return error;
}

esp_err_t ainekio_nvs_adapter_load_calibration(
    ainekio_servo_bank_t *servos,
    bool *recovered
)
{
    if (servos == NULL || recovered == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *recovered = false;
    ainekio_servo_bank_init(servos);
    nvs_handle_t handle = 0U;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_CALIBRATION, NVS_READONLY, &handle);
    uint32_t schema = 0U;
    ainekio_servo_calibration_t values[AINEKIO_SERVO_COUNT];
    size_t size = sizeof(values);
    if (error == ESP_OK) error = nvs_get_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, &schema);
    if (error == ESP_OK) error = nvs_get_blob(handle, AINEKIO_NVS_KEY_SERVO_CALIBRATION, values, &size);
    if (handle != 0U) nvs_close(handle);
    bool valid = error == ESP_OK && schema == AINEKIO_NVS_SCHEMA_VERSION &&
                 size == sizeof(values);
    if (valid) {
        for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
            valid = valid && ainekio_servo_set_calibration(servos, index, &values[index]) ==
                                   AINEKIO_SERVO_OK;
        }
    }
    if (valid) {
        return ESP_OK;
    }
    if (error != ESP_ERR_NVS_NOT_FOUND && error != ESP_OK &&
        error != ESP_ERR_NVS_INVALID_LENGTH && error != ESP_ERR_NVS_TYPE_MISMATCH) {
        return error;
    }
    *recovered = error != ESP_ERR_NVS_NOT_FOUND || schema != 0U;
    const esp_err_t reset_error =
        reset_namespace(AINEKIO_NVS_NAMESPACE_CALIBRATION);
    if (reset_error != ESP_OK) {
        return reset_error;
    }
    ainekio_servo_bank_init(servos);
    return ainekio_nvs_adapter_save_calibration(servos);
}

esp_err_t ainekio_nvs_adapter_save_poses(const ainekio_pose_bank_t *poses)
{
    if (!ainekio_pose_bank_valid(poses)) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle = 0U;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_POSES, NVS_READWRITE, &handle);
    if (error == ESP_OK) error = write_schema(handle);
    if (error == ESP_OK) error = nvs_set_blob(handle, AINEKIO_NVS_KEY_NAMED_POSES, poses, sizeof(*poses));
    if (error == ESP_OK) error = nvs_commit(handle);
    if (handle != 0U) nvs_close(handle);
    return error;
}

esp_err_t ainekio_nvs_adapter_load_poses(
    ainekio_pose_bank_t *poses,
    bool *recovered
)
{
    if (poses == NULL || recovered == NULL) return ESP_ERR_INVALID_ARG;
    *recovered = false;
    ainekio_pose_bank_init(poses);
    nvs_handle_t handle = 0U;
    uint32_t schema = 0U;
    size_t size = sizeof(*poses);
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_POSES, NVS_READONLY, &handle);
    if (error == ESP_OK) error = nvs_get_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, &schema);
    if (error == ESP_OK) error = nvs_get_blob(handle, AINEKIO_NVS_KEY_NAMED_POSES, poses, &size);
    if (handle != 0U) nvs_close(handle);
    if (error == ESP_OK && schema == AINEKIO_NVS_SCHEMA_VERSION &&
        size == sizeof(*poses) && ainekio_pose_bank_valid(poses)) {
        return ESP_OK;
    }
    if (error != ESP_ERR_NVS_NOT_FOUND && error != ESP_OK &&
        error != ESP_ERR_NVS_INVALID_LENGTH && error != ESP_ERR_NVS_TYPE_MISMATCH) {
        return error;
    }
    *recovered = error != ESP_ERR_NVS_NOT_FOUND || schema != 0U;
    const esp_err_t reset_error = reset_namespace(AINEKIO_NVS_NAMESPACE_POSES);
    if (reset_error != ESP_OK) {
        return reset_error;
    }
    ainekio_pose_bank_init(poses);
    return ainekio_nvs_adapter_save_poses(poses);
}

static esp_err_t save_preferences(ainekio_profile_t profile, float adc_factor)
{
    if (profile > AINEKIO_PROFILE_TETHER || !isfinite(adc_factor) || adc_factor < 0.0F) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle = 0U;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_PREFERENCES, NVS_READWRITE, &handle);
    if (error == ESP_OK) error = write_schema(handle);
    if (error == ESP_OK) error = nvs_set_u8(handle, AINEKIO_NVS_KEY_DEFAULT_PROFILE, (uint8_t)profile);
    if (error == ESP_OK) error = nvs_set_blob(handle, AINEKIO_NVS_KEY_ADC_FACTOR, &adc_factor, sizeof(adc_factor));
    if (error == ESP_OK) error = nvs_commit(handle);
    if (handle != 0U) nvs_close(handle);
    return error;
}

esp_err_t ainekio_nvs_adapter_load_preferences(
    ainekio_profile_t *profile,
    float *adc_factor,
    bool *recovered
)
{
    if (profile == NULL || adc_factor == NULL || recovered == NULL) return ESP_ERR_INVALID_ARG;
    *profile = AINEKIO_PROFILE_HOME;
    *adc_factor = 0.0F;
    *recovered = false;
    nvs_handle_t handle = 0U;
    uint32_t schema = 0U;
    uint8_t profile_value = 0U;
    size_t size = sizeof(*adc_factor);
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_PREFERENCES, NVS_READONLY, &handle);
    if (error == ESP_OK) error = nvs_get_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, &schema);
    if (error == ESP_OK) error = nvs_get_u8(handle, AINEKIO_NVS_KEY_DEFAULT_PROFILE, &profile_value);
    if (error == ESP_OK) error = nvs_get_blob(handle, AINEKIO_NVS_KEY_ADC_FACTOR, adc_factor, &size);
    if (handle != 0U) nvs_close(handle);
    if (error == ESP_OK && schema == AINEKIO_NVS_SCHEMA_VERSION &&
        profile_value <= AINEKIO_PROFILE_TETHER && size == sizeof(*adc_factor) &&
        isfinite(*adc_factor) && *adc_factor >= 0.0F) {
        *profile = (ainekio_profile_t)profile_value;
        return ESP_OK;
    }
    if (error != ESP_ERR_NVS_NOT_FOUND && error != ESP_OK &&
        error != ESP_ERR_NVS_INVALID_LENGTH && error != ESP_ERR_NVS_TYPE_MISMATCH) {
        return error;
    }
    *recovered = error != ESP_ERR_NVS_NOT_FOUND || schema != 0U;
    const esp_err_t reset_error =
        reset_namespace(AINEKIO_NVS_NAMESPACE_PREFERENCES);
    if (reset_error != ESP_OK) {
        return reset_error;
    }
    *profile = AINEKIO_PROFILE_HOME;
    *adc_factor = 0.0F;
    return save_preferences(*profile, *adc_factor);
}

esp_err_t ainekio_nvs_adapter_save_profile(ainekio_profile_t profile)
{
    float adc_factor = 0.0F;
    bool recovered = false;
    ainekio_profile_t current = AINEKIO_PROFILE_HOME;
    const esp_err_t loaded = ainekio_nvs_adapter_load_preferences(&current, &adc_factor, &recovered);
    return loaded == ESP_OK ? save_preferences(profile, adc_factor) : loaded;
}

esp_err_t ainekio_nvs_adapter_save_adc_factor(float adc_factor)
{
    float current_factor = 0.0F;
    bool recovered = false;
    ainekio_profile_t profile = AINEKIO_PROFILE_HOME;
    const esp_err_t loaded = ainekio_nvs_adapter_load_preferences(&profile, &current_factor, &recovered);
    return loaded == ESP_OK ? save_preferences(profile, adc_factor) : loaded;
}

esp_err_t ainekio_nvs_adapter_save_wake_preferences(
    bool enabled,
    const char *model
)
{
    if (!ainekio_asset_name_valid(model)) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle = 0U;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_PREFERENCES, NVS_READWRITE, &handle);
    if (error == ESP_OK) error = write_schema(handle);
    if (error == ESP_OK) {
        error = nvs_set_u8(handle, AINEKIO_NVS_KEY_WAKE_ENABLED, enabled ? 1U : 0U);
    }
    if (error == ESP_OK) {
        error = nvs_set_str(handle, AINEKIO_NVS_KEY_WAKE_MODEL, model);
    }
    if (error == ESP_OK) error = nvs_commit(handle);
    if (handle != 0U) nvs_close(handle);
    return error;
}

esp_err_t ainekio_nvs_adapter_load_wake_preferences(
    bool *enabled,
    char model[AINEKIO_WAKE_MODEL_MAX + 1U],
    bool *recovered
)
{
    if (enabled == NULL || model == NULL || recovered == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *enabled = false;
    (void)strcpy(model, AINEKIO_DEFAULT_WAKE_MODEL);
    *recovered = false;

    nvs_handle_t handle = 0U;
    uint32_t schema = 0U;
    uint8_t enabled_value = 0U;
    esp_err_t error = nvs_open(AINEKIO_NVS_NAMESPACE_PREFERENCES, NVS_READONLY, &handle);
    if (error == ESP_OK) error = nvs_get_u32(handle, AINEKIO_NVS_KEY_SCHEMA_VERSION, &schema);
    if (error == ESP_OK) error = nvs_get_u8(handle, AINEKIO_NVS_KEY_WAKE_ENABLED, &enabled_value);
    if (error == ESP_OK) {
        error = get_bounded_string(
            handle,
            AINEKIO_NVS_KEY_WAKE_MODEL,
            model,
            AINEKIO_WAKE_MODEL_MAX + 1U
        );
    }
    if (handle != 0U) nvs_close(handle);
    if (error == ESP_OK && schema == AINEKIO_NVS_SCHEMA_VERSION && enabled_value <= 1U &&
        ainekio_asset_name_valid(model)) {
        *enabled = enabled_value != 0U;
        return ESP_OK;
    }
    if (error != ESP_ERR_NVS_NOT_FOUND && error != ESP_OK &&
        error != ESP_ERR_NVS_INVALID_LENGTH && error != ESP_ERR_NVS_TYPE_MISMATCH) {
        return error;
    }

    *recovered = error != ESP_ERR_NVS_NOT_FOUND ||
                 (schema != 0U && schema != AINEKIO_NVS_SCHEMA_VERSION);
    *enabled = false;
    (void)strcpy(model, AINEKIO_DEFAULT_WAKE_MODEL);
    return ainekio_nvs_adapter_save_wake_preferences(*enabled, model);
}
