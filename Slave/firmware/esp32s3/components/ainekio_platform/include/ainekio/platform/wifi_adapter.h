#ifndef AINEKIO_PLATFORM_WIFI_ADAPTER_H
#define AINEKIO_PLATFORM_WIFI_ADAPTER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/config_store.h"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define AINEKIO_SETUP_SSID "Ainekio-Setup"
#define AINEKIO_SETUP_SECRET_CHARS 12U
#define AINEKIO_WIFI_SCAN_MAX 16U

typedef struct {
    char ssid[AINEKIO_WIFI_SSID_BYTES];
    int8_t rssi;
    uint8_t channel;
    wifi_auth_mode_t auth_mode;
} ainekio_wifi_scan_entry_t;

typedef struct {
    EventGroupHandle_t events;
    StaticEventGroup_t events_storage;
    esp_netif_t *station_netif;
    esp_netif_t *setup_netif;
    esp_event_handler_instance_t wifi_handler;
    esp_event_handler_instance_t ip_handler;
    bool initialized;
    bool started;
    bool setup_active;
} ainekio_wifi_adapter_t;

esp_err_t ainekio_wifi_adapter_init(ainekio_wifi_adapter_t *adapter);
esp_err_t ainekio_wifi_connect(
    ainekio_wifi_adapter_t *adapter,
    const char *ssid,
    const char *psk
);
esp_err_t ainekio_wifi_disconnect(ainekio_wifi_adapter_t *adapter);
esp_err_t ainekio_wifi_start_setup(
    ainekio_wifi_adapter_t *adapter,
    const char secret[AINEKIO_SETUP_SECRET_CHARS + 1U]
);
esp_err_t ainekio_wifi_stop_setup(ainekio_wifi_adapter_t *adapter);
bool ainekio_wifi_has_ip(const ainekio_wifi_adapter_t *adapter);
bool ainekio_wifi_wait_for_ip(
    ainekio_wifi_adapter_t *adapter,
    uint32_t timeout_ms
);
esp_err_t ainekio_wifi_scan(
    ainekio_wifi_adapter_t *adapter,
    ainekio_wifi_scan_entry_t *entries,
    size_t capacity,
    size_t *count
);

#endif
