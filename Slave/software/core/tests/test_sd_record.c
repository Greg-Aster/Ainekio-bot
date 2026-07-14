#include "ainekio/sd_record.h"

#include <assert.h>
#include <string.h>

int main(void)
{
    const uint8_t payload[] = "battery_warn";
    const uint32_t payload_length = (uint32_t)(sizeof(payload) - 1U);
    const uint64_t timestamp_ms = UINT64_C(1720000123456);
    const uint32_t crc = ainekio_sd_record_crc(
        3U,
        payload_length,
        timestamp_ms,
        payload
    );
    assert(crc != 0U);

    const ainekio_sd_record_header_t expected = {
        .type = 3U,
        .payload_length = payload_length,
        .timestamp_ms = timestamp_ms,
        .crc32 = crc,
    };
    uint8_t encoded[AINEKIO_SD_RECORD_HEADER_BYTES];
    assert(ainekio_sd_record_encode_header(encoded, &expected));
    ainekio_sd_record_header_t decoded;
    assert(ainekio_sd_record_decode_header(encoded, &decoded));
    assert(decoded.type == expected.type);
    assert(decoded.payload_length == expected.payload_length);
    assert(decoded.timestamp_ms == expected.timestamp_ms);
    assert(decoded.crc32 == expected.crc32);

    uint8_t changed[sizeof(payload)];
    memcpy(changed, payload, sizeof(payload));
    changed[0] ^= 1U;
    assert(ainekio_sd_record_crc(
               decoded.type,
               decoded.payload_length,
               decoded.timestamp_ms,
               changed
           ) != decoded.crc32);

    encoded[0] = 'X';
    assert(!ainekio_sd_record_decode_header(encoded, &decoded));
    assert(ainekio_sd_record_crc(
               1U,
               AINEKIO_SD_RECORD_MAX_PAYLOAD + 1U,
               0U,
               payload
           ) == 0U);
    return 0;
}
