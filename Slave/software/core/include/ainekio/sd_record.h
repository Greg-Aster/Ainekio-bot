#ifndef AINEKIO_SD_RECORD_H
#define AINEKIO_SD_RECORD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_SD_RECORD_HEADER_BYTES 24U
#define AINEKIO_SD_RECORD_MAX_PAYLOAD 4096U
#define AINEKIO_SD_RECORD_VERSION 1U

typedef struct {
    uint8_t type;
    uint32_t payload_length;
    uint64_t timestamp_ms;
    uint32_t crc32;
} ainekio_sd_record_header_t;

uint32_t ainekio_sd_crc32_begin(void);
uint32_t ainekio_sd_crc32_update(
    uint32_t state,
    const uint8_t *bytes,
    size_t length
);
uint32_t ainekio_sd_crc32_finish(uint32_t state);
uint32_t ainekio_sd_record_crc(
    uint8_t type,
    uint32_t payload_length,
    uint64_t timestamp_ms,
    const uint8_t *payload
);
bool ainekio_sd_record_encode_header(
    uint8_t output[AINEKIO_SD_RECORD_HEADER_BYTES],
    const ainekio_sd_record_header_t *header
);
bool ainekio_sd_record_decode_header(
    const uint8_t input[AINEKIO_SD_RECORD_HEADER_BYTES],
    ainekio_sd_record_header_t *header
);

#endif
