#include "ainekio/sd_record.h"

#include <string.h>

static const uint8_t record_magic[4] = {'A', 'L', 'O', 'G'};

static void write_u16(uint8_t *output, uint16_t value)
{
    output[0] = (uint8_t)value;
    output[1] = (uint8_t)(value >> 8U);
}

static void write_u32(uint8_t *output, uint32_t value)
{
    for (uint8_t index = 0U; index < 4U; ++index) {
        output[index] = (uint8_t)(value >> (index * 8U));
    }
}

static void write_u64(uint8_t *output, uint64_t value)
{
    for (uint8_t index = 0U; index < 8U; ++index) {
        output[index] = (uint8_t)(value >> (index * 8U));
    }
}

static uint16_t read_u16(const uint8_t *input)
{
    return (uint16_t)input[0] | ((uint16_t)input[1] << 8U);
}

static uint32_t read_u32(const uint8_t *input)
{
    uint32_t value = 0U;
    for (uint8_t index = 0U; index < 4U; ++index) {
        value |= (uint32_t)input[index] << (index * 8U);
    }
    return value;
}

static uint64_t read_u64(const uint8_t *input)
{
    uint64_t value = 0U;
    for (uint8_t index = 0U; index < 8U; ++index) {
        value |= (uint64_t)input[index] << (index * 8U);
    }
    return value;
}

uint32_t ainekio_sd_crc32_begin(void)
{
    return UINT32_MAX;
}

uint32_t ainekio_sd_crc32_update(
    uint32_t state,
    const uint8_t *bytes,
    size_t length
)
{
    if (bytes == NULL && length != 0U) {
        return state;
    }
    for (size_t index = 0U; index < length; ++index) {
        state ^= bytes[index];
        for (uint8_t bit = 0U; bit < 8U; ++bit) {
            const uint32_t mask = (uint32_t)-(int32_t)(state & 1U);
            state = (state >> 1U) ^ (UINT32_C(0xedb88320) & mask);
        }
    }
    return state;
}

uint32_t ainekio_sd_crc32_finish(uint32_t state)
{
    return state ^ UINT32_MAX;
}

uint32_t ainekio_sd_record_crc(
    uint8_t type,
    uint32_t payload_length,
    uint64_t timestamp_ms,
    const uint8_t *payload
)
{
    if (payload_length > AINEKIO_SD_RECORD_MAX_PAYLOAD ||
        (payload == NULL && payload_length != 0U)) {
        return 0U;
    }
    uint8_t metadata[16] = {AINEKIO_SD_RECORD_VERSION, type};
    write_u16(&metadata[2], AINEKIO_SD_RECORD_HEADER_BYTES);
    write_u32(&metadata[4], payload_length);
    write_u64(&metadata[8], timestamp_ms);
    uint32_t state = ainekio_sd_crc32_begin();
    state = ainekio_sd_crc32_update(state, metadata, sizeof(metadata));
    state = ainekio_sd_crc32_update(state, payload, payload_length);
    return ainekio_sd_crc32_finish(state);
}

bool ainekio_sd_record_encode_header(
    uint8_t output[AINEKIO_SD_RECORD_HEADER_BYTES],
    const ainekio_sd_record_header_t *header
)
{
    if (output == NULL || header == NULL ||
        header->payload_length > AINEKIO_SD_RECORD_MAX_PAYLOAD) {
        return false;
    }
    memcpy(output, record_magic, sizeof(record_magic));
    output[4] = AINEKIO_SD_RECORD_VERSION;
    output[5] = header->type;
    write_u16(&output[6], AINEKIO_SD_RECORD_HEADER_BYTES);
    write_u32(&output[8], header->payload_length);
    write_u64(&output[12], header->timestamp_ms);
    write_u32(&output[20], header->crc32);
    return true;
}

bool ainekio_sd_record_decode_header(
    const uint8_t input[AINEKIO_SD_RECORD_HEADER_BYTES],
    ainekio_sd_record_header_t *header
)
{
    if (input == NULL || header == NULL ||
        memcmp(input, record_magic, sizeof(record_magic)) != 0 ||
        input[4] != AINEKIO_SD_RECORD_VERSION ||
        read_u16(&input[6]) != AINEKIO_SD_RECORD_HEADER_BYTES) {
        return false;
    }
    const uint32_t payload_length = read_u32(&input[8]);
    if (payload_length > AINEKIO_SD_RECORD_MAX_PAYLOAD) {
        return false;
    }
    *header = (ainekio_sd_record_header_t){
        .type = input[5],
        .payload_length = payload_length,
        .timestamp_ms = read_u64(&input[12]),
        .crc32 = read_u32(&input[20]),
    };
    return true;
}
