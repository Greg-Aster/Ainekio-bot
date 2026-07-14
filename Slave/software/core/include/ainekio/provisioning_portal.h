#ifndef AINEKIO_PROVISIONING_PORTAL_H
#define AINEKIO_PROVISIONING_PORTAL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/config_store.h"

#define AINEKIO_PORTAL_BODY_MAX 1024U
#define AINEKIO_PORTAL_ATTEMPTS_PER_MINUTE 5U
#define AINEKIO_PORTAL_LOCK_AFTER_FAILURES 10U
#define AINEKIO_PORTAL_LOCK_MS UINT32_C(300000)

typedef struct {
    uint32_t window_started_ms;
    uint32_t lock_until_ms;
    uint8_t window_attempts;
    uint8_t consecutive_failures;
    bool initialized;
} ainekio_portal_rate_limit_t;

typedef enum {
    AINEKIO_PORTAL_PARSE_OK = 0,
    AINEKIO_PORTAL_PARSE_TOO_LARGE,
    AINEKIO_PORTAL_PARSE_MALFORMED,
    AINEKIO_PORTAL_PARSE_DUPLICATE,
    AINEKIO_PORTAL_PARSE_MISSING,
    AINEKIO_PORTAL_PARSE_RANGE,
} ainekio_portal_parse_result_t;

void ainekio_portal_rate_limit_init(ainekio_portal_rate_limit_t *limit);
bool ainekio_portal_login_allowed(
    ainekio_portal_rate_limit_t *limit,
    uint32_t now_ms
);
void ainekio_portal_login_failed(
    ainekio_portal_rate_limit_t *limit,
    uint32_t now_ms
);
void ainekio_portal_login_succeeded(ainekio_portal_rate_limit_t *limit);
ainekio_portal_parse_result_t ainekio_portal_parse_config(
    const char *body,
    size_t body_length,
    bool network_only,
    ainekio_config_record_t *candidate
);

#endif
