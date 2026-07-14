#include "ainekio/binary_codec.h"

#include <string.h>

static bool known_type(uint8_t type)
{
    return type == AINEKIO_FRAME_MIC_PCM || type == AINEKIO_FRAME_CAMERA_JPEG ||
           type == AINEKIO_FRAME_SPEAKER_PCM;
}

static ainekio_binary_result_t validate_payload(
    uint8_t type,
    const uint8_t *payload,
    size_t length
)
{
    if (type == AINEKIO_FRAME_MIC_PCM || type == AINEKIO_FRAME_SPEAKER_PCM) {
        return length == AINEKIO_AUDIO_PAYLOAD_BYTES ? AINEKIO_BINARY_OK
                                                     : AINEKIO_BINARY_LENGTH;
    }
    if (type == AINEKIO_FRAME_CAMERA_JPEG) {
        if (length > AINEKIO_MAX_JPEG_BYTES) {
            return AINEKIO_BINARY_LENGTH;
        }
        if (length < 4U || payload == NULL || payload[0] != 0xFFU ||
            payload[1] != 0xD8U || payload[length - 2U] != 0xFFU ||
            payload[length - 1U] != 0xD9U) {
            return AINEKIO_BINARY_FORMAT;
        }
    }
    return AINEKIO_BINARY_OK;
}

ainekio_binary_result_t ainekio_binary_decode(
    const uint8_t *bytes,
    size_t length,
    ainekio_binary_frame_t *frame
)
{
    if (bytes == NULL || frame == NULL || length < AINEKIO_BINARY_HEADER_BYTES) {
        return AINEKIO_BINARY_TRUNCATED;
    }
    *frame = (ainekio_binary_frame_t){
        .type = bytes[0],
        .counter = (uint32_t)bytes[1] | ((uint32_t)bytes[2] << 8U) |
                   ((uint32_t)bytes[3] << 16U) | ((uint32_t)bytes[4] << 24U),
        .payload = bytes + AINEKIO_BINARY_HEADER_BYTES,
        .payload_length = length - AINEKIO_BINARY_HEADER_BYTES,
        .known_type = known_type(bytes[0]),
    };
    return frame->known_type
               ? validate_payload(frame->type, frame->payload, frame->payload_length)
               : AINEKIO_BINARY_OK;
}

ainekio_binary_result_t ainekio_binary_encode(
    uint8_t type,
    uint32_t counter,
    const uint8_t *payload,
    size_t payload_length,
    uint8_t *output,
    size_t capacity,
    size_t *output_length
)
{
    if ((payload == NULL && payload_length != 0U) || output == NULL ||
        output_length == NULL) {
        return AINEKIO_BINARY_FORMAT;
    }
    const ainekio_binary_result_t validation =
        known_type(type) ? validate_payload(type, payload, payload_length)
                         : AINEKIO_BINARY_OK;
    if (validation != AINEKIO_BINARY_OK) {
        return validation;
    }
    if (payload_length > SIZE_MAX - AINEKIO_BINARY_HEADER_BYTES ||
        capacity < AINEKIO_BINARY_HEADER_BYTES + payload_length) {
        return AINEKIO_BINARY_CAPACITY;
    }
    output[0] = type;
    output[1] = (uint8_t)(counter & 0xFFU);
    output[2] = (uint8_t)((counter >> 8U) & 0xFFU);
    output[3] = (uint8_t)((counter >> 16U) & 0xFFU);
    output[4] = (uint8_t)((counter >> 24U) & 0xFFU);
    if (payload_length > 0U) {
        memcpy(output + AINEKIO_BINARY_HEADER_BYTES, payload, payload_length);
    }
    *output_length = AINEKIO_BINARY_HEADER_BYTES + payload_length;
    return AINEKIO_BINARY_OK;
}
