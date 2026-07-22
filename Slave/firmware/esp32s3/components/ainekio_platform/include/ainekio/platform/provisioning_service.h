#ifndef AINEKIO_PLATFORM_PROVISIONING_SERVICE_H
#define AINEKIO_PLATFORM_PROVISIONING_SERVICE_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/config_store.h"
#include "ainekio/platform/provisioning_portal.h"
#include "ainekio/platform/wifi_adapter.h"
#include "ainekio/provisioning.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef enum {
    AINEKIO_PROVISION_DISPLAY_CONNECTING = 0,
    AINEKIO_PROVISION_DISPLAY_UNAVAILABLE,
    AINEKIO_PROVISION_DISPLAY_SETUP,
    AINEKIO_PROVISION_DISPLAY_CONNECTED,
    AINEKIO_PROVISION_DISPLAY_GATEWAY_AUTH_FAILED,
} ainekio_provision_display_t;

typedef enum {
    AINEKIO_PROVISION_CUE_SETUP = 0,
    AINEKIO_PROVISION_CUE_CONNECTED,
} ainekio_provision_cue_t;

typedef struct {
    const char *setup_key;
    const char *wifi_ssid;
    const char *ip_address;
} ainekio_provision_display_info_t;

typedef esp_err_t (*ainekio_provision_display_fn)(
    void *context,
    ainekio_provision_display_t status,
    const ainekio_provision_display_info_t *info
);
typedef esp_err_t (*ainekio_provision_cue_fn)(
    void *context,
    ainekio_provision_cue_t cue
);
typedef esp_err_t (*ainekio_provision_online_fn)(
    void *context,
    const ainekio_config_record_t *active_config
);

typedef struct {
    void *context;
    ainekio_provision_display_fn display;
    ainekio_provision_cue_fn cue;
    ainekio_provision_online_fn online;
} ainekio_provision_io_t;

typedef struct {
    ainekio_provisioning_t *machine;
    ainekio_config_store_t *config_store;
    ainekio_wifi_adapter_t *wifi;
    ainekio_provisioning_portal_t *portal;
    ainekio_provision_io_t io;
    TaskHandle_t task;
    char setup_key[AINEKIO_SETUP_KEY_CHARS + 1U];
    char staged_ssid[AINEKIO_WIFI_SSID_BYTES];
    char staged_psk[AINEKIO_WIFI_PSK_BYTES];
    uint32_t retry_at_ms;
    uint32_t retry_delay_ms;
    uint32_t setup_retry_at_ms;
    uint32_t boot_pressed_at_ms;
    bool setup_requested;
    bool setup_services_ready;
    bool setup_network_only;
    bool boot_press_active;
    bool boot_press_triggered;
    bool previous_ip;
    bool serial_key_printed;
} ainekio_provisioning_service_t;

esp_err_t ainekio_provisioning_service_start(
    ainekio_provisioning_service_t *service,
    ainekio_provisioning_t *machine,
    ainekio_config_store_t *config_store,
    ainekio_wifi_adapter_t *wifi,
    ainekio_provisioning_portal_t *portal,
    const ainekio_provision_io_t *io
);
void ainekio_provisioning_service_request_manual(
    ainekio_provisioning_service_t *service
);
void ainekio_provisioning_service_request_network_reset(
    ainekio_provisioning_service_t *service
);
void ainekio_provisioning_service_request_gateway_auth_failure(
    ainekio_provisioning_service_t *service
);

#endif
