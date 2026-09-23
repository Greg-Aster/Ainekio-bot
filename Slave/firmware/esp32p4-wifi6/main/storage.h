#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

typedef struct {
    bool mounted;
    bool busy;
    uint64_t total_bytes;
    uint64_t free_bytes;
    uint32_t dropped_records;
    esp_err_t last_error;
} ainekio_p4_storage_status_t;

/* Start after Hosted initializes SDMMC slot 1; storage owns slot 0 only. */
esp_err_t ainekio_p4_storage_start(void);
ainekio_p4_storage_status_t ainekio_p4_storage_status(void);
esp_err_t ainekio_p4_storage_retry(void);
/* Retry and clear wait for their own worker result (maximum 4 seconds).
 * Explicit local/authenticated operator clear erases only our logs/captures. */
esp_err_t ainekio_p4_storage_clear(void);
/* Nonblocking bounded copies. No credentials or PCM should be appended. */
esp_err_t ainekio_p4_storage_record(uint8_t type, const void *payload, size_t size);
esp_err_t ainekio_p4_storage_capture(const void *jpeg, size_t size);
/* Drains queued writes, syncs and unmounts; fails closed on timeout. */
esp_err_t ainekio_p4_storage_suspend(uint32_t timeout_ms);
/* Cancel a failed power handoff and reopen producer/operator admission.
 * A card already unmounted by the handoff can be mounted with retry(). */
esp_err_t ainekio_p4_storage_resume(void);
