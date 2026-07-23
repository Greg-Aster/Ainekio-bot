#ifndef AINEKIO_PLATFORM_LOCAL_DISCOVERY_H
#define AINEKIO_PLATFORM_LOCAL_DISCOVERY_H

#include <stddef.h>

#include "esp_err.h"

#define AINEKIO_LOCAL_GATEWAY_ID "ainekio-gateway-01"

esp_err_t ainekio_local_gateway_discover(
    const char *expected_gateway_id,
    char *endpoint,
    size_t endpoint_capacity
);

#endif
