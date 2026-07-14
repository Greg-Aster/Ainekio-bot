#ifndef AINEKIO_PLATFORM_SD_SERVICE_H
#define AINEKIO_PLATFORM_SD_SERVICE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/sd_record.h"
#include "esp_err.h"

typedef struct ainekio_sd_service ainekio_sd_service_t;

#define AINEKIO_SD_APPEND_MAX_BYTES 1024U

typedef enum {
    AINEKIO_SD_UNAVAILABLE = 0,
    AINEKIO_SD_MOUNTED,
    AINEKIO_SD_CORRUPT,
} ainekio_sd_state_t;

typedef void (*ainekio_sd_state_fn)(
    void *context,
    ainekio_sd_state_t state
);

typedef struct {
    void *context;
    ainekio_sd_state_fn state;
} ainekio_sd_callbacks_t;

esp_err_t ainekio_sd_service_start(
    const ainekio_sd_callbacks_t *callbacks,
    ainekio_sd_service_t **service
);
bool ainekio_sd_available(const ainekio_sd_service_t *service);
esp_err_t ainekio_sd_request_retry(ainekio_sd_service_t *service);
esp_err_t ainekio_sd_append(
    ainekio_sd_service_t *service,
    uint8_t record_type,
    uint64_t timestamp_ms,
    const void *payload,
    size_t payload_length
);
esp_err_t ainekio_sd_request_clear(ainekio_sd_service_t *service);
esp_err_t ainekio_sd_prepare_reformat(
    ainekio_sd_service_t *service,
    uint32_t *confirmation
);
esp_err_t ainekio_sd_confirm_reformat(
    ainekio_sd_service_t *service,
    uint32_t confirmation
);

#endif
