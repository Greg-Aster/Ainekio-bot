#include "ainekio/provisioning_portal.h"

#include <string.h>

#define AINEKIO_PORTAL_WINDOW_MS UINT32_C(60000)

typedef struct {
    const char *name;
    char *destination;
    size_t capacity;
    bool required;
    bool seen;
} portal_field_t;

static int hex_value(char value)
{
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    if (value >= 'a' && value <= 'f') {
        return value - 'a' + 10;
    }
    if (value >= 'A' && value <= 'F') {
        return value - 'A' + 10;
    }
    return -1;
}

static ainekio_portal_parse_result_t decode_value(
    const char *source,
    size_t source_length,
    char *destination,
    size_t capacity
)
{
    size_t output = 0U;
    for (size_t input = 0U; input < source_length; ++input) {
        unsigned char value = (unsigned char)source[input];
        if (value == '+') {
            value = ' ';
        } else if (value == '%') {
            if (input + 2U >= source_length) {
                return AINEKIO_PORTAL_PARSE_MALFORMED;
            }
            const int high = hex_value(source[input + 1U]);
            const int low = hex_value(source[input + 2U]);
            if (high < 0 || low < 0) {
                return AINEKIO_PORTAL_PARSE_MALFORMED;
            }
            value = (unsigned char)((high << 4) | low);
            input += 2U;
        }
        if (value == 0U || value < 0x20U || value == 0x7FU ||
            output + 1U >= capacity) {
            return AINEKIO_PORTAL_PARSE_RANGE;
        }
        destination[output++] = (char)value;
    }
    destination[output] = '\0';
    return AINEKIO_PORTAL_PARSE_OK;
}

static portal_field_t *find_field(
    portal_field_t *fields,
    size_t field_count,
    const char *name,
    size_t name_length
)
{
    for (size_t index = 0U; index < field_count; ++index) {
        if (strlen(fields[index].name) == name_length &&
            memcmp(fields[index].name, name, name_length) == 0) {
            return &fields[index];
        }
    }
    return NULL;
}

void ainekio_portal_rate_limit_init(ainekio_portal_rate_limit_t *limit)
{
    memset(limit, 0, sizeof(*limit));
}

bool ainekio_portal_login_allowed(
    ainekio_portal_rate_limit_t *limit,
    uint32_t now_ms
)
{
    if (limit->lock_until_ms != 0U &&
        (int32_t)(limit->lock_until_ms - now_ms) > 0) {
        return false;
    }
    if (limit->lock_until_ms != 0U) {
        limit->lock_until_ms = 0U;
        limit->consecutive_failures = 0U;
    }
    if (!limit->initialized ||
        (uint32_t)(now_ms - limit->window_started_ms) >= AINEKIO_PORTAL_WINDOW_MS) {
        limit->window_started_ms = now_ms;
        limit->window_attempts = 0U;
        limit->initialized = true;
    }
    if (limit->window_attempts >= AINEKIO_PORTAL_ATTEMPTS_PER_MINUTE) {
        return false;
    }
    ++limit->window_attempts;
    return true;
}

void ainekio_portal_login_failed(
    ainekio_portal_rate_limit_t *limit,
    uint32_t now_ms
)
{
    if (limit->consecutive_failures < UINT8_MAX) {
        ++limit->consecutive_failures;
    }
    if (limit->consecutive_failures >= AINEKIO_PORTAL_LOCK_AFTER_FAILURES) {
        limit->lock_until_ms = now_ms + AINEKIO_PORTAL_LOCK_MS;
    }
}

void ainekio_portal_login_succeeded(ainekio_portal_rate_limit_t *limit)
{
    ainekio_portal_rate_limit_init(limit);
}

ainekio_portal_parse_result_t ainekio_portal_parse_config(
    const char *body,
    size_t body_length,
    bool network_only,
    ainekio_config_record_t *candidate
)
{
    if (body == NULL || candidate == NULL || body_length == 0U) {
        return AINEKIO_PORTAL_PARSE_MALFORMED;
    }
    if (body_length > AINEKIO_PORTAL_BODY_MAX) {
        return AINEKIO_PORTAL_PARSE_TOO_LARGE;
    }
    memset(candidate, 0, sizeof(*candidate));
    portal_field_t fields[] = {
        {"wifi_ssid", candidate->wifi_ssid, sizeof(candidate->wifi_ssid), true, false},
        {"wifi_psk", candidate->wifi_psk, sizeof(candidate->wifi_psk), true, false},
        {"endpoint_url", candidate->endpoint_url, sizeof(candidate->endpoint_url), !network_only, false},
        {"robot_id", candidate->robot_id, sizeof(candidate->robot_id), !network_only, false},
        {"robot_token", candidate->robot_token, sizeof(candidate->robot_token), !network_only, false},
    };
    const size_t field_count = sizeof(fields) / sizeof(fields[0]);

    size_t offset = 0U;
    while (offset < body_length) {
        const size_t pair_start = offset;
        while (offset < body_length && body[offset] != '&') {
            ++offset;
        }
        const size_t pair_end = offset;
        if (offset < body_length) {
            ++offset;
        }
        size_t separator = pair_start;
        while (separator < pair_end && body[separator] != '=') {
            ++separator;
        }
        if (separator == pair_start || separator == pair_end) {
            return AINEKIO_PORTAL_PARSE_MALFORMED;
        }
        portal_field_t *field = find_field(
            fields,
            field_count,
            body + pair_start,
            separator - pair_start
        );
        if (field == NULL) {
            continue;
        }
        if (field->seen) {
            return AINEKIO_PORTAL_PARSE_DUPLICATE;
        }
        const ainekio_portal_parse_result_t result = decode_value(
            body + separator + 1U,
            pair_end - separator - 1U,
            field->destination,
            field->capacity
        );
        if (result != AINEKIO_PORTAL_PARSE_OK) {
            return result;
        }
        field->seen = true;
    }
    for (size_t index = 0U; index < field_count; ++index) {
        if (fields[index].required &&
            (!fields[index].seen || fields[index].destination[0] == '\0')) {
            return AINEKIO_PORTAL_PARSE_MISSING;
        }
    }
    candidate->schema_version = AINEKIO_NVS_SCHEMA_VERSION;
    candidate->generation = 1U;
    candidate->complete = true;
    if (network_only) {
        const size_t psk_length = strlen(candidate->wifi_psk);
        return psk_length >= 8U && psk_length <= 64U
                   ? AINEKIO_PORTAL_PARSE_OK
                   : AINEKIO_PORTAL_PARSE_RANGE;
    }
    return ainekio_config_record_valid(candidate, true)
               ? AINEKIO_PORTAL_PARSE_OK
               : AINEKIO_PORTAL_PARSE_RANGE;
}
