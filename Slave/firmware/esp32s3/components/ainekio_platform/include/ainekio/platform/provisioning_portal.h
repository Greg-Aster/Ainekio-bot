#ifndef AINEKIO_PLATFORM_PROVISIONING_PORTAL_H
#define AINEKIO_PLATFORM_PROVISIONING_PORTAL_H

#include <stdbool.h>

#include "ainekio/config_store.h"
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
    bool network_only;
} ainekio_provisioning_portal_t;

esp_err_t ainekio_provisioning_portal_init(ainekio_provisioning_portal_t *portal);
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
