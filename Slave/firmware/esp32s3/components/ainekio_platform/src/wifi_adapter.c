#include "ainekio/platform/wifi_adapter.h"

#include <string.h>
#include <stdio.h>

#include "esp_check.h"

#define WIFI_IP_BIT BIT0
#define WIFI_AP_BIT BIT1
#define SETUP_AP_READY_TIMEOUT_MS 3000U

static const char *TAG = "ainekio_wifi";

static bool bounded_copy(uint8_t *destination, size_t capacity, const char *source)
{
    if (source == NULL) {
        return false;
    }
    const size_t length = strnlen(source, capacity);
    if (length == 0U || length >= capacity) {
        return false;
    }
    memcpy(destination, source, length);
    destination[length] = 0U;
    return true;
}

static void wifi_event(
    void *argument,
    esp_event_base_t base,
    int32_t event_id,
    void *event_data
)
{
    (void)event_data;
    ainekio_wifi_adapter_t *adapter = argument;
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(adapter->events, WIFI_IP_BIT);
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_AP_START) {
        xEventGroupSetBits(adapter->events, WIFI_AP_BIT);
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_AP_STOP) {
        xEventGroupClearBits(adapter->events, WIFI_AP_BIT);
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(adapter->events, WIFI_IP_BIT);
    }
}

esp_err_t ainekio_wifi_adapter_init(ainekio_wifi_adapter_t *adapter)
{
    if (adapter == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(adapter, 0, sizeof(*adapter));
    adapter->events = xEventGroupCreateStatic(&adapter->events_storage);
    if (adapter->events == NULL) {
        return ESP_ERR_NO_MEM;
    }
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init failed");
    esp_err_t result = esp_event_loop_create_default();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) {
        return result;
    }
    adapter->station_netif = esp_netif_create_default_wifi_sta();
    adapter->setup_netif = esp_netif_create_default_wifi_ap();
    if (adapter->station_netif == NULL || adapter->setup_netif == NULL) {
        return ESP_ERR_NO_MEM;
    }
    const wifi_init_config_t wifi_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&wifi_config), TAG, "wifi init failed");
    ESP_RETURN_ON_ERROR(
        esp_event_handler_instance_register(
            WIFI_EVENT,
            ESP_EVENT_ANY_ID,
            wifi_event,
            adapter,
            &adapter->wifi_handler
        ),
        TAG,
        "wifi event registration failed"
    );
    ESP_RETURN_ON_ERROR(
        esp_event_handler_instance_register(
            IP_EVENT,
            IP_EVENT_STA_GOT_IP,
            wifi_event,
            adapter,
            &adapter->ip_handler
        ),
        TAG,
        "ip event registration failed"
    );
    adapter->initialized = true;
    return ESP_OK;
}

static esp_err_t ensure_started(ainekio_wifi_adapter_t *adapter)
{
    if (!adapter->started) {
        const esp_err_t result = esp_wifi_start();
        if (result != ESP_OK) {
            return result;
        }
        adapter->started = true;
    }
    /* The robot gateway is a low-latency control link. Home-AP DTIM intervals
     * can otherwise delay the WebSocket handshake beyond its bounded
     * transport window. */
    return esp_wifi_set_ps(WIFI_PS_NONE);
}

esp_err_t ainekio_wifi_connect(
    ainekio_wifi_adapter_t *adapter,
    const char *ssid,
    const char *psk
)
{
    if (adapter == NULL || !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    wifi_config_t config = {0};
    if (!bounded_copy(config.sta.ssid, sizeof(config.sta.ssid), ssid) ||
        !bounded_copy(config.sta.password, sizeof(config.sta.password), psk)) {
        return ESP_ERR_INVALID_ARG;
    }
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    config.sta.pmf_cfg.capable = true;
    config.sta.pmf_cfg.required = false;
    xEventGroupClearBits(adapter->events, WIFI_IP_BIT);
    ESP_RETURN_ON_ERROR(
        esp_wifi_set_mode(adapter->setup_active ? WIFI_MODE_APSTA : WIFI_MODE_STA),
        TAG,
        "wifi mode failed"
    );
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &config), TAG,
                        "station config failed");
    ESP_RETURN_ON_ERROR(ensure_started(adapter), TAG, "wifi start failed");
    return esp_wifi_connect();
}

esp_err_t ainekio_wifi_disconnect(ainekio_wifi_adapter_t *adapter)
{
    if (adapter == NULL || !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    xEventGroupClearBits(adapter->events, WIFI_IP_BIT);
    const esp_err_t result = esp_wifi_disconnect();
    return result == ESP_ERR_WIFI_NOT_CONNECT ? ESP_OK : result;
}

esp_err_t ainekio_wifi_start_setup(
    ainekio_wifi_adapter_t *adapter,
    const char setup_key[AINEKIO_SETUP_KEY_CHARS + 1U]
)
{
    if (adapter == NULL || !adapter->initialized || setup_key == NULL ||
        strnlen(setup_key, AINEKIO_SETUP_KEY_CHARS + 1U) !=
            AINEKIO_SETUP_KEY_CHARS) {
        return ESP_ERR_INVALID_ARG;
    }
    wifi_config_t config = {0};
    memcpy(config.ap.ssid, AINEKIO_SETUP_SSID, sizeof(AINEKIO_SETUP_SSID) - 1U);
    config.ap.ssid_len = sizeof(AINEKIO_SETUP_SSID) - 1U;
    memcpy(config.ap.password, setup_key, AINEKIO_SETUP_KEY_CHARS);
    config.ap.channel = 1U;
    config.ap.max_connection = 4U;
    config.ap.authmode = WIFI_AUTH_WPA2_PSK;
    config.ap.pmf_cfg.capable = true;
    config.ap.pmf_cfg.required = false;
    adapter->setup_active = true;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA), TAG,
                        "APSTA mode failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &config), TAG,
                        "setup AP config failed");
    ESP_RETURN_ON_ERROR(ensure_started(adapter), TAG, "setup AP start failed");
    const EventBits_t ready = xEventGroupWaitBits(
        adapter->events,
        WIFI_AP_BIT,
        pdFALSE,
        pdTRUE,
        pdMS_TO_TICKS(SETUP_AP_READY_TIMEOUT_MS)
    );
    if ((ready & WIFI_AP_BIT) == 0U) {
        ESP_LOGE(TAG, "setup AP did not become ready");
        return ESP_ERR_TIMEOUT;
    }
    const esp_err_t dhcp_result = esp_netif_dhcps_start(adapter->setup_netif);
    if (dhcp_result != ESP_OK &&
        dhcp_result != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STARTED) {
        ESP_LOGE(
            TAG,
            "setup DHCP server failed: %s",
            esp_err_to_name(dhcp_result)
        );
        return dhcp_result;
    }
    return ESP_OK;
}

esp_err_t ainekio_wifi_stop_setup(ainekio_wifi_adapter_t *adapter)
{
    if (adapter == NULL || !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    adapter->setup_active = false;
    const esp_err_t result = esp_wifi_set_mode(WIFI_MODE_STA);
    if (result == ESP_OK) {
        xEventGroupClearBits(adapter->events, WIFI_AP_BIT);
    }
    return result;
}

bool ainekio_wifi_has_ip(const ainekio_wifi_adapter_t *adapter)
{
    return adapter != NULL && adapter->events != NULL &&
           (xEventGroupGetBits(adapter->events) & WIFI_IP_BIT) != 0U;
}

bool ainekio_wifi_wait_for_ip(
    ainekio_wifi_adapter_t *adapter,
    uint32_t timeout_ms
)
{
    if (adapter == NULL || adapter->events == NULL) {
        return false;
    }
    return (xEventGroupWaitBits(
                adapter->events,
                WIFI_IP_BIT,
                pdFALSE,
                pdTRUE,
                pdMS_TO_TICKS(timeout_ms)
            ) &
            WIFI_IP_BIT) != 0U;
}

bool ainekio_wifi_station_address(
    const ainekio_wifi_adapter_t *adapter,
    char address[AINEKIO_IPV4_ADDRESS_CHARS + 1U]
)
{
    if (adapter == NULL || adapter->station_netif == NULL || address == NULL) {
        return false;
    }
    esp_netif_ip_info_t info;
    if (esp_netif_get_ip_info(adapter->station_netif, &info) != ESP_OK ||
        info.ip.addr == 0U) {
        address[0] = '\0';
        return false;
    }
    const int written = snprintf(
        address,
        AINEKIO_IPV4_ADDRESS_CHARS + 1U,
        IPSTR,
        IP2STR(&info.ip)
    );
    return written > 0 && written <= (int)AINEKIO_IPV4_ADDRESS_CHARS;
}

esp_err_t ainekio_wifi_scan(
    ainekio_wifi_adapter_t *adapter,
    ainekio_wifi_scan_entry_t *entries,
    size_t capacity,
    size_t *count
)
{
    if (adapter == NULL || entries == NULL || count == NULL ||
        capacity == 0U || capacity > AINEKIO_WIFI_SCAN_MAX || !adapter->started) {
        return ESP_ERR_INVALID_ARG;
    }
    const wifi_scan_config_t scan_config = {
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
    };
    ESP_RETURN_ON_ERROR(esp_wifi_scan_start(&scan_config, true), TAG,
                        "wifi scan failed");
    uint16_t requested = (uint16_t)capacity;
    wifi_ap_record_t records[AINEKIO_WIFI_SCAN_MAX];
    ESP_RETURN_ON_ERROR(esp_wifi_scan_get_ap_records(&requested, records), TAG,
                        "wifi scan read failed");
    for (uint16_t index = 0U; index < requested; ++index) {
        memset(&entries[index], 0, sizeof(entries[index]));
        memcpy(entries[index].ssid, records[index].ssid, sizeof(records[index].ssid));
        entries[index].ssid[sizeof(entries[index].ssid) - 1U] = '\0';
        entries[index].rssi = records[index].rssi;
        entries[index].channel = records[index].primary;
        entries[index].auth_mode = records[index].authmode;
    }
    *count = requested;
    return ESP_OK;
}
