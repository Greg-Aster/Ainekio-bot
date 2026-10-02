#pragma once
#include "esp_netif.h"
#define ESP_IPADDR_TYPE_V4 0
#define ESP_IPADDR_TYPE_V6 6
typedef struct mdns_ip_addr {
    struct mdns_ip_addr *next;
    struct { int type; union { esp_ip4_addr_t ip4; } u_addr; } addr;
} mdns_ip_addr_t;
typedef struct { const char *key, *value; } mdns_txt_item_t;
typedef struct mdns_result {
    struct mdns_result *next;
    uint16_t port;
    size_t txt_count;
    mdns_txt_item_t *txt;
    size_t *txt_value_len;
    mdns_ip_addr_t *addr;
} mdns_result_t;
esp_err_t mdns_init(void);
esp_err_t mdns_query_ptr(const char *service, const char *protocol, uint32_t timeout,
                         size_t capacity, mdns_result_t **results);
void mdns_query_results_free(mdns_result_t *results);
