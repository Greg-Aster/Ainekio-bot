#include "ainekio/control_codec.h"

#include <stdio.h>

int main(void)
{
    char input[AINEKIO_CONTROL_MAX_BYTES + 2U];
    const size_t length = fread(input, 1U, sizeof(input), stdin);
    if (ferror(stdin) || length == 0U || length > AINEKIO_CONTROL_MAX_BYTES) {
        return 3;
    }
    ainekio_control_message_t message;
    const ainekio_decode_result_t result =
        ainekio_control_decode(input, length, &message);
    if (result != AINEKIO_DECODE_OK) {
        (void)fprintf(stderr, "%s\n", ainekio_decode_result_name(result));
        return 2;
    }
    return 0;
}
