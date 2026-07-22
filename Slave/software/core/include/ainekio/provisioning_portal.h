#ifndef AINEKIO_PROVISIONING_PORTAL_H
#define AINEKIO_PROVISIONING_PORTAL_H

#include <stddef.h>

#include "ainekio/config_store.h"

#define AINEKIO_PORTAL_BODY_MAX 1024U

typedef enum {
    AINEKIO_PORTAL_PARSE_OK = 0,
    AINEKIO_PORTAL_PARSE_TOO_LARGE,
    AINEKIO_PORTAL_PARSE_MALFORMED,
    AINEKIO_PORTAL_PARSE_DUPLICATE,
    AINEKIO_PORTAL_PARSE_MISSING,
    AINEKIO_PORTAL_PARSE_RANGE,
} ainekio_portal_parse_result_t;

ainekio_portal_parse_result_t ainekio_portal_parse_config(
    const char *body,
    size_t body_length,
    bool network_only,
    ainekio_config_record_t *candidate
);

#endif
