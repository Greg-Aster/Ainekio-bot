#pragma once
#include "robot_settings.h"
#include "ainekio/platform/local_discovery.h"

#define AINEKIO_GATEWAY_CONNECT_TIMEOUT_US UINT64_C(10000000)

/* State of the existing link task, never a second connection or command queue. */
typedef struct {
    int network, profile;
    size_t count, cursor;
    bool needs_discovery;
    char discovered[AINEKIO_DISCOVERY_MAX_RESULTS][AINEKIO_DISCOVERY_ENDPOINT_CAPACITY];
} ainekio_p4_gateway_selection_t;

void ainekio_p4_gateway_select_network(ainekio_p4_gateway_selection_t *selection,
                                     const ainekio_p4_robot_settings_t *settings, int network);
const char *ainekio_p4_gateway_endpoint(const ainekio_p4_gateway_selection_t *selection,
                                      const ainekio_p4_robot_settings_t *settings);
/* Called only once the old client is stopped/destroyed and admission closed. */
void ainekio_p4_gateway_failed(ainekio_p4_gateway_selection_t *selection,
                              const ainekio_p4_robot_settings_t *settings);
void ainekio_p4_gateway_discovered(ainekio_p4_gateway_selection_t *selection,
                                  const ainekio_p4_robot_settings_t *settings, size_t count);
bool ainekio_p4_gateway_connect_expired(uint64_t started_us, uint64_t now_us, bool authenticated);
