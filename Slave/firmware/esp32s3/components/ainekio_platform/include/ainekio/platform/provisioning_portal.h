#ifndef AINEKIO_PLATFORM_PROVISIONING_PORTAL_H
#define AINEKIO_PLATFORM_PROVISIONING_PORTAL_H

#include <stdbool.h>

#include "ainekio/config_store.h"
#include "ainekio/platform/nvs_adapter.h"
#include "ainekio/platform/wifi_adapter.h"
#include "ainekio/provisioning_portal.h"
#include "esp_err.h"
#include "esp_http_server.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

typedef struct {
    ainekio_config_record_t record;
    bool network_only;
} ainekio_portal_candidate_t;

typedef struct {
    httpd_handle_t server;
    QueueHandle_t candidate_queue;
    StaticQueue_t candidate_queue_storage;
    uint8_t candidate_queue_bytes[sizeof(ainekio_portal_candidate_t)];
    ainekio_portal_rate_limit_t rate_limit;
    uint8_t secret_hash[AINEKIO_SETUP_HASH_BYTES];
    char session_token[33];
    bool network_only;
    bool secret_ready;
} ainekio_provisioning_portal_t;

esp_err_t ainekio_provisioning_portal_init(ainekio_provisioning_portal_t *portal);
esp_err_t ainekio_provisioning_portal_generate_secret(
    ainekio_provisioning_portal_t *portal,
    char secret[AINEKIO_SETUP_SECRET_CHARS + 1U]
);
esp_err_t ainekio_provisioning_portal_start(
    ainekio_provisioning_portal_t *portal,
    bool network_only
);
esp_err_t ainekio_provisioning_portal_suspend(ainekio_provisioning_portal_t *portal);
esp_err_t ainekio_provisioning_portal_stop(ainekio_provisioning_portal_t *portal);
bool ainekio_provisioning_portal_take_candidate(
    ainekio_provisioning_portal_t *portal,
    ainekio_portal_candidate_t *candidate,
    TickType_t wait_ticks
);

#endif
