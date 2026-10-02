#include "ainekio/platform/local_discovery.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_netif.h"
#include "mdns.h"

#define DISCOVERY_TIMEOUT_MS 2500U

static const char *TAG = "ainekio_discovery";
static bool mdns_initialized;

static bool txt_equals(
    const mdns_result_t *result,
    const char *key,
    const char *expected
)
{
    if (result == NULL || key == NULL || expected == NULL) {
        return false;
    }
    const size_t expected_length = strlen(expected);
    for (size_t index = 0U; index < result->txt_count; ++index) {
        const char *value = result->txt[index].value;
        if (result->txt[index].key != NULL && value != NULL &&
            strcmp(result->txt[index].key, key) == 0 &&
            result->txt_value_len[index] == expected_length &&
            memcmp(value, expected, expected_length) == 0) {
            return true;
        }
    }
    return false;
}

static const esp_ip4_addr_t *select_local_ipv4(const mdns_result_t *result)
{
    esp_netif_t *station = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_ip_info_t station_info = {0};
    const bool has_station_info = station != NULL &&
                                  esp_netif_get_ip_info(station, &station_info) == ESP_OK;
    if (!has_station_info || station_info.netmask.addr == 0U) {
        return NULL;
    }
    for (const mdns_ip_addr_t *address = result->addr;
         address != NULL;
         address = address->next) {
        if (address->addr.type != ESP_IPADDR_TYPE_V4) {
            continue;
        }
        const esp_ip4_addr_t *ipv4 = &address->addr.u_addr.ip4;
        if ((ipv4->addr & station_info.netmask.addr) ==
                (station_info.ip.addr & station_info.netmask.addr) &&
            ipv4->addr != station_info.ip.addr) {
            return ipv4;
        }
    }
    return NULL;
}

static esp_err_t ensure_mdns(void)
{
    if (mdns_initialized) {
        return ESP_OK;
    }
    const esp_err_t result = mdns_init();
    if (result == ESP_OK) {
        mdns_initialized = true;
    }
    return result;
}

esp_err_t ainekio_local_gateways_discover(
    char endpoints[][AINEKIO_DISCOVERY_ENDPOINT_CAPACITY], size_t capacity, size_t *count)
{
    if (endpoints == NULL || count == NULL || capacity == 0U || capacity > AINEKIO_DISCOVERY_MAX_RESULTS) {
        return ESP_ERR_INVALID_ARG;
    }
    *count = 0;
    esp_err_t result = ensure_mdns();
    if (result != ESP_OK) {
        return result;
    }

    mdns_result_t *results = NULL;
    result = mdns_query_ptr(
        "_ainekio",
        "_tcp",
        DISCOVERY_TIMEOUT_MS,
        AINEKIO_DISCOVERY_MAX_RESULTS,
        &results
    );
    if (result != ESP_OK) {
        mdns_query_results_free(results);
        return result;
    }

    result = ESP_ERR_NOT_FOUND;
    for (const mdns_result_t *candidate = results;
         candidate != NULL;
         candidate = candidate->next) {
        if (candidate->port == 0U ||
            !txt_equals(candidate, "protocol", "1") ||
            !txt_equals(candidate, "path", "/robot") ||
            !txt_equals(candidate, "transport", "lan") ||
            !txt_equals(candidate, "tls", "0")) {
            continue;
        }
        const esp_ip4_addr_t *address = select_local_ipv4(candidate);
        if (address == NULL) {
            continue;
        }
        char address_text[16] = {0};
        if (esp_ip4addr_ntoa(
                address,
                address_text,
                sizeof(address_text)
            ) == NULL) {
            continue;
        }
        char endpoint[AINEKIO_DISCOVERY_ENDPOINT_CAPACITY];
        const int written = snprintf(endpoint, sizeof(endpoint), "ws://%s:%u/robot",
                                     address_text, (unsigned int)candidate->port);
        if (written < 0 || (size_t)written >= sizeof(endpoint)) continue;
        bool duplicate = false;
        for (size_t i=0; i<*count; ++i)
            if (!strcmp(endpoints[i], endpoint)) duplicate = true;
        if (duplicate) continue;
        strcpy(endpoints[(*count)++], endpoint);
        result = ESP_OK;
        if (*count == capacity) break;
    }
    mdns_query_results_free(results);
    return result;
}

/* The S3 single-candidate consumer retains its explicit ambiguity result. */
esp_err_t ainekio_local_gateway_discover(char *endpoint, size_t endpoint_capacity)
{
    if (!endpoint || !endpoint_capacity) return ESP_ERR_INVALID_ARG;
    endpoint[0] = '\0';
    char endpoints[2][AINEKIO_DISCOVERY_ENDPOINT_CAPACITY];
    size_t count;
    esp_err_t result = ainekio_local_gateways_discover(endpoints, 2, &count);
    if (result != ESP_OK) return result;
    if (count != 1) {
        ESP_LOGW(TAG, "multiple local gateways discovered");
        return ESP_ERR_INVALID_STATE;
    }
    if (strlen(endpoints[0]) >= endpoint_capacity) return ESP_ERR_INVALID_SIZE;
    strcpy(endpoint, endpoints[0]);
    return ESP_OK;
}
