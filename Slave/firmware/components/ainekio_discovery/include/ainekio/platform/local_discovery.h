#ifndef AINEKIO_PLATFORM_LOCAL_DISCOVERY_H
#define AINEKIO_PLATFORM_LOCAL_DISCOVERY_H

#include <stddef.h>

#include "esp_err.h"

#define AINEKIO_DISCOVERY_MAX_RESULTS 8U
#define AINEKIO_DISCOVERY_ENDPOINT_CAPACITY 256U

/* Only protocol-v1 LAN gateways on the station's current IPv4 subnet.
 * Advertisements identify candidates; the existing handshake still establishes
 * the controller session. No credential or remote URL comes from DNS-SD. */
esp_err_t ainekio_local_gateways_discover(
    char endpoints[][AINEKIO_DISCOVERY_ENDPOINT_CAPACITY],
    size_t capacity, size_t *count
);

esp_err_t ainekio_local_gateway_discover(
    char *endpoint,
    size_t endpoint_capacity
);

#endif
