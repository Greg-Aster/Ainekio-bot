#include "network.h"
#include "board.h"
#include "config.h"
#include "controller.h"
#include "ainekio/provisioning.h"

#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "esp_event.h"
#include "esp_hosted.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static atomic_bool online, manual_ap, retry, lost, initialized, ap_running;
static atomic_bool maintenance;
#ifdef AINEKIO_C6_IMAGE_INCLUDED
static atomic_bool update_c6;
extern const uint8_t c6_firmware_start[] asm("_binary_c6_firmware_start");
extern const uint8_t c6_firmware_end[] asm("_binary_c6_firmware_end");

static void update_coprocessor(void)
{
    atomic_store(&maintenance, true);
    ainekio_p4_controller_quiesce();
    const size_t size = c6_firmware_end - c6_firmware_start;
    ESP_LOGI("network", "C6 update bytes=%u SHA256=%s", (unsigned)size, AINEKIO_C6_SHA256);
    esp_hosted_coprocessor_fwver_t version = {0};
    const bool known_version = esp_hosted_get_coprocessor_fwversion(&version) == ESP_OK;
    /* Espressif's host_performs_slave_ota example distinguishes pre-2.6
     * firmware (end activates) from >=2.6 (separate activate RPC). */
    const bool activate = known_version && (version.major1 > 2 || (version.major1 == 2 && version.minor1 >= 6));
    esp_err_t result = esp_hosted_slave_ota_begin();
    uint8_t chunk[1024];
    size_t offset = 0;
    while (result == ESP_OK && offset < size) {
        size_t count = size - offset;
        if (count > sizeof(chunk)) count = sizeof(chunk);
        memcpy(chunk, c6_firmware_start + offset, count);
        result = esp_hosted_slave_ota_write(chunk, count);
        if (result == ESP_OK) offset += count;
    }
    if (result == ESP_OK) result = esp_hosted_slave_ota_end();
    if (result == ESP_OK && activate) result = esp_hosted_slave_ota_activate();
    if (result != ESP_OK) {
        ESP_LOGE("network", "C6 update failed at %u/%u: %s; maintenance remains latched",
                 (unsigned)offset, (unsigned)size, esp_err_to_name(result));
        return;
    }
    ESP_LOGI("network", "C6 image transferred; restarting to verify actual firmware and networking");
    vTaskDelay(pdMS_TO_TICKS(3000));
    esp_restart();
}
#endif
static char ap_name[33], ap_key[17];
static esp_netif_t *station;

bool ainekio_p4_network_online(void) { return atomic_load(&online) && !atomic_load(&maintenance); }

static void event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        atomic_store(&online, false);
        atomic_store(&lost, true);
        /* No motion queue, RPC or I2C is involved in loss handling. */
        ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
        ESP_LOGI("network", "Station disconnected reason=%u", ((wifi_event_sta_disconnected_t *)data)->reason);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        atomic_store(&online, true);
        const ip_event_got_ip_t *ip = data;
        ESP_LOGI("network", "Station IPv4=" IPSTR, IP2STR(&ip->ip_info.ip));
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STACONNECTED) {
        ESP_LOGI("network", "Setup AP client associated");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STADISCONNECTED) {
        ESP_LOGI("network", "Setup AP client disconnected");
    }
}

static esp_err_t setup_ap(bool enable)
{
    ESP_LOGI("network", "Setup AP %s", enable ? "starting" : "stopping");
    esp_err_t result = esp_wifi_set_mode(enable ? WIFI_MODE_APSTA : WIFI_MODE_STA);
    if (result == ESP_OK) atomic_store(&ap_running, enable);
    return result;
}

static void network_task(void *arg)
{
    (void)arg;
    const ainekio_config_record_t *config = ainekio_p4_config();
    /* Network initialization can block or fail without blocking board startup,
     * the console, or the independent output supervisor. */
    esp_err_t result = esp_netif_init();
    if (result == ESP_OK) result = esp_event_loop_create_default();
    if (result != ESP_OK) goto failed;
    station = esp_netif_create_default_wifi_sta();
    if (!station || !esp_netif_create_default_wifi_ap()) { result = ESP_ERR_NO_MEM; goto failed; }
    result = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, event, NULL);
    if (result == ESP_OK) result = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, event, NULL);
    if (result != ESP_OK) goto failed;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    result = esp_wifi_init(&init);
    if (result != ESP_OK) goto failed;
    result = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (result != ESP_OK) goto failed;
    esp_hosted_coprocessor_fwver_t version = {0};
    result = esp_hosted_get_coprocessor_fwversion(&version);
    if (result == ESP_OK)
        ESP_LOGI("network", "C6 firmware=%" PRIu32 ".%" PRIu32 ".%" PRIu32 " rev=%" PRId32,
                 version.major1, version.minor1, version.patch1, version.revision);
    else ESP_LOGE("network", "C6 firmware query failed: %s; pairing UNVERIFIED", esp_err_to_name(result));
    wifi_config_t ap = {.ap={.ssid_len=strlen(ap_name), .channel=1, .max_connection=2, .authmode=WIFI_AUTH_WPA2_PSK}};
    memcpy(ap.ap.ssid, ap_name, strlen(ap_name));
    memcpy(ap.ap.password, ap_key, strlen(ap_key));
    result = esp_wifi_set_mode(WIFI_MODE_APSTA);
    if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_AP, &ap);
    if (config && config->wifi_ssid[0]) {
        wifi_config_t sta = {0};
        memcpy(sta.sta.ssid, config->wifi_ssid, strlen(config->wifi_ssid));
        memcpy(sta.sta.password, config->wifi_psk, strlen(config->wifi_psk));
        sta.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
        if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_STA, &sta);
    }
    if (result == ESP_OK) result = esp_wifi_set_mode(config ? WIFI_MODE_STA : WIFI_MODE_APSTA);
    if (result == ESP_OK) result = esp_wifi_start();
    if (result != ESP_OK) goto failed;
    atomic_store(&initialized, true);
    atomic_store(&ap_running, !config);
    ainekio_provisioning_t provision;
    ainekio_provisioning_init(&provision, config ? AINEKIO_CONFIG_STATUS_VALID : AINEKIO_CONFIG_STATUS_MISSING,
                              esp_timer_get_time() / 1000U);
    uint64_t last_connect_ms = 0;
    bool time_service_started = false;
    for (;;) {
#ifdef AINEKIO_C6_IMAGE_INCLUDED
        if (atomic_exchange(&update_c6, false)) update_coprocessor();
#endif
        if (atomic_load(&maintenance)) { vTaskDelay(pdMS_TO_TICKS(100)); continue; }
        const uint64_t now_ms = esp_timer_get_time() / 1000U;
        if (!time_service_started && atomic_load(&online) && config &&
            strcmp(config->transport_mode, AINEKIO_TRANSPORT_REMOTE) == 0) {
            /* TLS needs wall-clock certificate validation. Time sync never
             * blocks board startup; command deadlines remain monotonic. */
            esp_sntp_config_t time_config = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
            time_config.wait_for_sync = false;
            const esp_err_t time_result = esp_netif_sntp_init(&time_config);
            time_service_started = true;
            if (time_result != ESP_OK) ESP_LOGE("network", "TLS time service: %s", esp_err_to_name(time_result));
        }
        if (atomic_exchange(&lost, false)) ainekio_provisioning_on_wifi_lost(&provision, now_ms);
        if (atomic_exchange(&manual_ap, false)) {
            ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
            ainekio_provisioning_request_manual(&provision, AINEKIO_PROVISION_REASON_DASHBOARD_REQUEST, now_ms);
        }
        if (atomic_exchange(&retry, false)) {
            ainekio_provisioning_init(&provision, config ? AINEKIO_CONFIG_STATUS_VALID : AINEKIO_CONFIG_STATUS_MISSING, now_ms);
            if (config) setup_ap(false);
        }
        ainekio_provisioning_tick(&provision, now_ms);
        /* AP+STA can retain its address throughout manual setup. Returning to
         * station operation must report that existing link; there may be no
         * new GOT_IP event to finish the provisioning transition. */
        if (atomic_load(&online)) ainekio_provisioning_on_active_wifi_ip(&provision, now_ms);
        const ainekio_provision_actions_t actions = ainekio_provisioning_take_actions(&provision);
        if (actions & AINEKIO_PROVISION_ACTION_START_SETUP_AP) setup_ap(true);
        if (actions & AINEKIO_PROVISION_ACTION_STOP_SETUP_AP) setup_ap(false);
        if (config && !atomic_load(&online) &&
            ((actions & AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI) || now_ms - last_connect_ms >= 5000U)) {
            result = esp_wifi_connect();
            last_connect_ms = now_ms;
            if (result != ESP_OK) ESP_LOGW("network", "Station connect: %s", esp_err_to_name(result));
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
failed:
    ESP_LOGE("network", "Network initialization failed: %s; outputs disabled, console available", esp_err_to_name(result));
    vTaskDelete(NULL);
}

esp_err_t ainekio_p4_network_start(void)
{
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_BASE);
    snprintf(ap_name, sizeof(ap_name), "Ainekio-P4-%02X%02X%02X", mac[3], mac[4], mac[5]);
    snprintf(ap_key, sizeof(ap_key), "%08" PRIx32 "%08" PRIx32, esp_random(), esp_random());
    return xTaskCreate(network_task, "network", 8192, NULL, 4, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}

int ainekio_p4_network_command(int argc, char **argv)
{
#ifdef AINEKIO_C6_IMAGE_INCLUDED
    if (argc == 2 && strcmp(argv[1], "c6-update") == 0) {
        if (!atomic_load(&initialized) || atomic_load(&maintenance)) return 1;
        atomic_store(&maintenance, true);
        ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
        atomic_store(&update_c6, true);
        return 0;
    }
#endif
    if (argc == 2 && strcmp(argv[1], "ap") == 0) atomic_store(&manual_ap, true);
    else if (argc == 2 && strcmp(argv[1], "retry") == 0) atomic_store(&retry, true);
    else if (argc == 2 && strcmp(argv[1], "key") == 0) printf("Setup SSID=%s password=%s\n", ap_name, ap_key);
    else if (argc != 1) return 1;
    printf("network initialized=%d station=%d setup_ap=%d SSID=%s\n",
           atomic_load(&initialized), atomic_load(&online), atomic_load(&ap_running), ap_name);
    if (atomic_load(&online)) {
        esp_netif_ip_info_t info;
        if (esp_netif_get_ip_info(station, &info) == ESP_OK) printf("station ip=" IPSTR "\n", IP2STR(&info.ip));
    }
    return 0;
}
