#include <math.h>
#include <stdlib.h>

#include "ainekio/core.h"
#include "ainekio/config_store.h"
#include "ainekio/platform/asset_store.h"
#include "ainekio/platform/mcpwm_adapter.h"
#include "ainekio/platform/nvs_adapter.h"
#include "ainekio/platform/provisioning_portal.h"
#include "ainekio/platform/provisioning_service.h"
#include "ainekio/platform/runtime_service.h"
#include "ainekio/platform/sleep_service.h"
#include "ainekio/platform/wifi_adapter.h"
#include "ainekio/provisioning.h"
#include "ainekio/settings.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_system.h"
#include "sdkconfig.h"

static const char *TAG = "ainekio_boot";
static ainekio_core_t slave_brain;
static ainekio_nvs_adapter_t nvs_adapter;
static ainekio_config_store_t config_store;
static ainekio_provisioning_t provisioning;
static ainekio_wifi_adapter_t wifi_adapter;
static ainekio_provisioning_portal_t provisioning_portal;
static ainekio_provisioning_service_t provisioning_service;
static ainekio_servo_bank_t servo_bank;
static ainekio_pose_bank_t pose_bank;
static ainekio_mcpwm_adapter_t mcpwm_adapter;
static ainekio_asset_store_t asset_store;
static float battery_adc_factor;
static bool littlefs_failure_pending;
static ainekio_runtime_t *runtime_service;

static float configured_battery_divider(void)
{
    const char *input = CONFIG_AINEKIO_BATTERY_DIVIDER_FACTOR;
    char *end = NULL;
    const float value = strtof(input, &end);
    return end != input && end != NULL &&
                   *end == '\0' && isfinite(value) && value > 0.0F
               ? value
               : 0.0F;
}

static esp_err_t runtime_online(
    void *context,
    const ainekio_config_record_t *active_config
)
{
    return ainekio_runtime_network_online(context, active_config);
}

static esp_err_t runtime_display(
    void *context,
    ainekio_provision_display_t status,
    const char *setup_secret
)
{
    return ainekio_runtime_provision_display(context, status, setup_secret);
}

static esp_err_t runtime_cue(void *context, ainekio_provision_cue_t cue)
{
    return ainekio_runtime_provision_cue(context, cue);
}

void app_main(void)
{
    const esp_app_desc_t *app = esp_app_get_description();

    ainekio_core_init(&slave_brain);
    const esp_err_t nvs_error = ainekio_nvs_adapter_init(&nvs_adapter);
    bool calibration_recovered = false;
    bool poses_recovered = false;
    bool preferences_recovered = false;
    ainekio_profile_t saved_profile = AINEKIO_PROFILE_HOME;
    esp_err_t settings_error = nvs_error;
    if (settings_error == ESP_OK) {
        settings_error = ainekio_nvs_adapter_load_calibration(
            &servo_bank,
            &calibration_recovered
        );
    }
    if (settings_error == ESP_OK) {
        settings_error =
            ainekio_nvs_adapter_load_poses(&pose_bank, &poses_recovered);
    }
    if (settings_error == ESP_OK) {
        settings_error = ainekio_nvs_adapter_load_preferences(
            &saved_profile,
            &battery_adc_factor,
            &preferences_recovered
        );
    }
    if (settings_error == ESP_OK) {
        ainekio_core_set_profile(&slave_brain, saved_profile);
    }

    const float battery_divider_factor = configured_battery_divider();
    bool brownout_recovered_pending = false;
    float recovery_voltage = 0.0F;
    if (ainekio_sleep_battery_recheck_pending()) {
        bool recovered = false;
        const esp_err_t recovery_error =
            battery_divider_factor > 0.0F
                ? ainekio_sleep_battery_recovered(
                      battery_divider_factor,
                      battery_adc_factor,
                      &recovery_voltage,
                      &recovered
                  )
                : ESP_ERR_INVALID_STATE;
        if (recovery_error != ESP_OK || !recovered) {
            ESP_LOGW(
                TAG,
                "battery cutoff recheck failed or remains unsafe: error=%s volts=%.3f",
                esp_err_to_name(recovery_error),
                (double)recovery_voltage
            );
            ainekio_sleep_enter(30U * 60U, true);
        }
        ainekio_sleep_clear_battery_recheck();
        brownout_recovered_pending = true;
        ESP_LOGI(
            TAG,
            "battery recovered before platform startup: volts=%.3f",
            (double)recovery_voltage
        );
    }

    const esp_err_t mcpwm_error = ainekio_mcpwm_adapter_init(&mcpwm_adapter);
    const esp_err_t asset_error = settings_error == ESP_OK
                                      ? ainekio_asset_store_init(
                                            &asset_store,
                                            &servo_bank
                                        )
                                      : ESP_ERR_INVALID_STATE;
    littlefs_failure_pending = asset_error != ESP_OK;
    ainekio_core_set_boot_ready(
        &slave_brain,
        settings_error == ESP_OK && mcpwm_error == ESP_OK &&
            battery_divider_factor > 0.0F
    );
    const ainekio_runtime_dependencies_t runtime_dependencies = {
        .core = &slave_brain,
        .servos = &servo_bank,
        .poses = &pose_bank,
        .mcpwm = &mcpwm_adapter,
        .assets = &asset_store,
        .provisioning = &provisioning_service,
        .firmware_version = app->version,
        .battery_divider_factor = battery_divider_factor,
        .battery_adc_factor = battery_adc_factor,
        .boot_event_pending = true,
        .brownout_recovered_pending = brownout_recovered_pending,
        .littlefs_failure_pending = littlefs_failure_pending,
    };
    const esp_err_t runtime_error = mcpwm_error == ESP_OK
                                        ? ainekio_runtime_start(
                                              &runtime_dependencies,
                                              &runtime_service
                                          )
                                        : mcpwm_error;
    ainekio_config_load_result_t config_result = AINEKIO_CONFIG_LOAD_IO_ERROR;
    if (nvs_error == ESP_OK) {
        const ainekio_config_store_port_t storage_port =
            ainekio_nvs_adapter_port(&nvs_adapter);
        ainekio_config_store_init(&config_store, &storage_port);
        config_result = ainekio_config_store_load(&config_store);
        if (config_result == AINEKIO_CONFIG_LOAD_CORRUPT &&
            ainekio_nvs_adapter_erase_config_namespaces() == ESP_OK) {
            ainekio_config_store_init(&config_store, &storage_port);
            config_result = ainekio_config_store_load(&config_store);
        }
    }
    const ainekio_config_status_t provision_config_status =
        config_result == AINEKIO_CONFIG_LOAD_VALID
            ? AINEKIO_CONFIG_STATUS_VALID
            : (config_result == AINEKIO_CONFIG_LOAD_MIGRATED
                   ? AINEKIO_CONFIG_STATUS_MIGRATED
            : (config_result == AINEKIO_CONFIG_LOAD_CORRUPT ||
                       config_result == AINEKIO_CONFIG_LOAD_IO_ERROR
                   ? AINEKIO_CONFIG_STATUS_CORRUPT
                   : AINEKIO_CONFIG_STATUS_MISSING));
    ainekio_provisioning_init(&provisioning, provision_config_status, 0U);

    esp_err_t provisioning_error =
        config_result == AINEKIO_CONFIG_LOAD_SCHEMA_MISMATCH
            ? ESP_ERR_INVALID_VERSION
            : nvs_error;
    if (provisioning_error == ESP_OK) {
        provisioning_error = ainekio_wifi_adapter_init(&wifi_adapter);
    }
    if (provisioning_error == ESP_OK) {
        provisioning_error =
            ainekio_provisioning_portal_init(&provisioning_portal);
    }
    if (provisioning_error == ESP_OK) {
        const ainekio_provision_io_t provisioning_io = {
            .context = runtime_service,
            .display = runtime_display,
            .cue = runtime_cue,
            .online = runtime_online,
        };
        provisioning_error = ainekio_provisioning_service_start(
            &provisioning_service,
            &provisioning,
            &config_store,
            &wifi_adapter,
            &provisioning_portal,
            runtime_error == ESP_OK ? &provisioning_io : NULL
        );
    }

    ESP_LOGI(TAG,
             "{\"event\":\"boot\",\"firmware\":\"%s\",\"protocol\":%u,"
             "\"idf\":\"%s\",\"state\":%u,\"servos_attached\":false,"
             "\"boot_ready\":%s,"
             "\"config_status\":%u,\"nvs_recovered\":%s,"
             "\"settings_recovered\":%s,\"assets_mounted\":%s,"
             "\"asset_unavailable\":%u,\"littlefs_fail_pending\":%s,"
             "\"runtime_service\":%s,\"audio_service\":%s,"
             "\"display_service\":%s,\"telemetry_service\":%s,"
             "\"sd_service\":%s,\"sd_mounted\":%s,"
             "\"battery_divider_configured\":%s,"
             "\"provisioning_service\":%s}",
             app->version,
             AINEKIO_PROTOCOL_VERSION,
             esp_get_idf_version(),
             (unsigned int)slave_brain.state,
             slave_brain.boot_ready ? "true" : "false",
             (unsigned int)config_result,
             nvs_adapter.partition_erased_during_init ? "true" : "false",
             calibration_recovered || poses_recovered || preferences_recovered
                 ? "true"
                 : "false",
             asset_error == ESP_OK ? "true" : "false",
             (unsigned int)asset_store.unavailable_count,
             littlefs_failure_pending ? "true" : "false",
             runtime_error == ESP_OK ? "true" : "false",
             runtime_error == ESP_OK && ainekio_runtime_audio_ready(runtime_service)
                 ? "true"
                 : "false",
             runtime_error == ESP_OK && ainekio_runtime_display_ready(runtime_service)
                 ? "true"
                 : "false",
             runtime_error == ESP_OK && ainekio_runtime_telemetry_ready(runtime_service)
                 ? "true"
                 : "false",
             runtime_error == ESP_OK && ainekio_runtime_sd_ready(runtime_service)
                 ? "true"
                 : "false",
             runtime_error == ESP_OK && ainekio_runtime_sd_mounted(runtime_service)
                 ? "true"
                 : "false",
             battery_divider_factor > 0.0F ? "true" : "false",
             provisioning_error == ESP_OK ? "true" : "false");
    if (settings_error != ESP_OK) {
        ESP_LOGE(TAG, "settings unavailable: %s", esp_err_to_name(settings_error));
    }
    if (mcpwm_error != ESP_OK) {
        ESP_LOGE(TAG, "servo PWM unavailable: %s", esp_err_to_name(mcpwm_error));
    }
    if (battery_divider_factor <= 0.0F) {
        ESP_LOGW(
            TAG,
            "battery divider is not configured; telemetry disabled and movement gated"
        );
    }
    if (asset_error != ESP_OK) {
        ESP_LOGE(TAG,
                 "event=littlefs_fail error=%s fallback=compiled-neutral-stand",
                 esp_err_to_name(asset_error));
    }
    if (runtime_error != ESP_OK) {
        ESP_LOGE(TAG, "runtime service unavailable: %s", esp_err_to_name(runtime_error));
    }
    if (provisioning_error != ESP_OK) {
        ESP_LOGE(TAG,
                 "provisioning service unavailable: %s",
                 esp_err_to_name(provisioning_error));
    }
}
