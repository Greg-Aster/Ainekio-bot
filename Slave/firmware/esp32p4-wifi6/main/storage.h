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

typedef struct {
    bool recording;
    uint32_t frames, dropped, segments, max_write_us, overwritten;
    esp_err_t error;
    char path[96];
} ainekio_p4_video_status_t;
ainekio_p4_video_status_t ainekio_p4_video_status(void);
esp_err_t ainekio_p4_video_start(void);
esp_err_t ainekio_p4_video_stop(void);
/* Copies before returning; never waits for card I/O or a queue slot. */
void ainekio_p4_video_frame(const void *jpeg, size_t size, unsigned width, unsigned height, unsigned fps);

typedef struct {
    char name[64];
    uint64_t bytes;
    bool complete;
} ainekio_p4_recording_file_t;
/* The existing HTTP owner serializes consumers. Each operation releases the
 * storage I/O mutex before any network send; unmount cancels open readers. */
esp_err_t ainekio_p4_recording_list_open(void);
esp_err_t ainekio_p4_recording_list_next(ainekio_p4_recording_file_t *file, bool *done);
esp_err_t ainekio_p4_recording_read_open(const char *name, uint64_t *bytes);
esp_err_t ainekio_p4_recording_read(void *buffer, size_t capacity, size_t *bytes);
void ainekio_p4_recording_read_close(void);

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
