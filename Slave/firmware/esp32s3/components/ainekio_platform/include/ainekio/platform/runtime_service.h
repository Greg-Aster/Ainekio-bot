#ifndef AINEKIO_PLATFORM_RUNTIME_SERVICE_H
#define AINEKIO_PLATFORM_RUNTIME_SERVICE_H

#include <stdbool.h>

#include "ainekio/config_store.h"
#include "ainekio/core.h"
#include "ainekio/platform/asset_store.h"
#include "ainekio/platform/mcpwm_adapter.h"
#include "ainekio/platform/provisioning_service.h"
#include "ainekio/settings.h"
#include "esp_err.h"

typedef struct ainekio_runtime ainekio_runtime_t;

typedef struct {
    ainekio_core_t *core;
    ainekio_servo_bank_t *servos;
    ainekio_pose_bank_t *poses;
    ainekio_mcpwm_adapter_t *mcpwm;
    ainekio_asset_store_t *assets;
    ainekio_provisioning_service_t *provisioning;
    const char *firmware_version;
    float battery_divider_factor;
    float battery_adc_factor;
    bool wake_enabled;
    const char *wake_model;
    bool boot_event_pending;
    bool brownout_recovered_pending;
    bool littlefs_failure_pending;
} ainekio_runtime_dependencies_t;

esp_err_t ainekio_runtime_start(
    const ainekio_runtime_dependencies_t *dependencies,
    ainekio_runtime_t **runtime
);
esp_err_t ainekio_runtime_network_online(
    ainekio_runtime_t *runtime,
    const ainekio_config_record_t *active_config
);
bool ainekio_runtime_audio_ready(const ainekio_runtime_t *runtime);
bool ainekio_runtime_camera_ready(const ainekio_runtime_t *runtime);
bool ainekio_runtime_display_ready(const ainekio_runtime_t *runtime);
bool ainekio_runtime_telemetry_ready(const ainekio_runtime_t *runtime);
bool ainekio_runtime_sd_ready(const ainekio_runtime_t *runtime);
bool ainekio_runtime_sd_mounted(const ainekio_runtime_t *runtime);
esp_err_t ainekio_runtime_provision_display(
    ainekio_runtime_t *runtime,
    ainekio_provision_display_t status,
    const char *setup_secret
);
esp_err_t ainekio_runtime_provision_cue(
    ainekio_runtime_t *runtime,
    ainekio_provision_cue_t cue
);

#endif
