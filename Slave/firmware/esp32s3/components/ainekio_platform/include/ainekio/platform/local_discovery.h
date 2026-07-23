#ifndef AINEKIO_PLATFORM_LOCAL_DISCOVERY_H
#define AINEKIO_PLATFORM_LOCAL_DISCOVERY_H

#include <stddef.h>

#include "esp_err.h"

esp_err_t ainekio_local_gateway_discover(
    char *endpoint,
    size_t endpoint_capacity
);

#endif
