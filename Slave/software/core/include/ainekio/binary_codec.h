#ifndef AINEKIO_BINARY_CODEC_H
#define AINEKIO_BINARY_CODEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_BINARY_HEADER_BYTES 5U
#define AINEKIO_AUDIO_PAYLOAD_BYTES 640U
#define AINEKIO_MAX_JPEG_BYTES (120U * 1024U)
#define AINEKIO_FRAME_MIC_PCM 0x01U
#define AINEKIO_FRAME_CAMERA_JPEG 0x02U
#define AINEKIO_FRAME_SPEAKER_PCM 0x10U

typedef enum {
    AINEKIO_BINARY_OK = 0,
    AINEKIO_BINARY_TRUNCATED,
    AINEKIO_BINARY_LENGTH,
    AINEKIO_BINARY_FORMAT,
    AINEKIO_BINARY_CAPACITY,
} ainekio_binary_result_t;

typedef struct {
    uint8_t type;
    uint32_t counter;
    const uint8_t *payload;
    size_t payload_length;
    bool known_type;
} ainekio_binary_frame_t;

ainekio_binary_result_t ainekio_binary_decode(
    const uint8_t *bytes,
    size_t length,
    ainekio_binary_frame_t *frame
);
ainekio_binary_result_t ainekio_binary_encode(
    uint8_t type,
    uint32_t counter,
    const uint8_t *payload,
    size_t payload_length,
    uint8_t *output,
    size_t capacity,
    size_t *output_length
);

#endif
