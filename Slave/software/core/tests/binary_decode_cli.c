#include "ainekio/binary_codec.h"

#include <stdio.h>

int main(void)
{
    uint8_t bytes[AINEKIO_MAX_JPEG_BYTES + AINEKIO_BINARY_HEADER_BYTES + 1U];
    const size_t length = fread(bytes, 1U, sizeof(bytes), stdin);
    if (ferror(stdin) || length == sizeof(bytes)) {
        return 3;
    }
    ainekio_binary_frame_t frame;
    const ainekio_binary_result_t result = ainekio_binary_decode(bytes, length, &frame);
    if (result != AINEKIO_BINARY_OK) {
        return 2;
    }
    (void)puts(frame.known_type ? "known" : "unknown");
    return 0;
}
