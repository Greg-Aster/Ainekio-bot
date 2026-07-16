#include "ainekio/control_codec.h"
#include "ainekio/control_encode.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void valid(const char *json, size_t length, ainekio_message_kind_t kind)
{
    assert(length > 0U);
    ainekio_control_message_t message;
    assert(ainekio_control_decode(json, length, &message) == AINEKIO_DECODE_OK);
    assert(message.kind == kind);
}

int main(void)
{
    char output[512];
    size_t length = ainekio_encode_hello(
        "0.1.0\"test",
        "ainekio-01",
        "token\\value",
        output,
        sizeof(output)
    );
    valid(output, length, AINEKIO_MESSAGE_HELLO);
    length = ainekio_encode_ack(1U, 0U, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_ACK);
    length = ainekio_encode_ack(2U, 28800U, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_ACK);
    length = ainekio_encode_nak(false, 0U, AINEKIO_NAK_MALFORMED, NULL, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_NAK);
    length = ainekio_encode_nak(true, 3U, AINEKIO_NAK_UNSAFE, "battery low", output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_NAK);
    length = ainekio_encode_done(4U, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_DONE);
    length = ainekio_encode_cancelled(5U, AINEKIO_CANCEL_STOP, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_CANCELLED);
    const ainekio_status_t status = {
        .battery_voltage = 7.42F,
        .rssi = -52,
        .state = AINEKIO_STATE_ACTIVE,
        .uptime_seconds = 312U,
        .free_heap = 183000U,
        .sd_available = true,
        .camera_drops = 4U,
        .microphone_drops = 2U,
        .wake_enabled = false,
        .wake_ready = false,
        .wake_model = AINEKIO_DEFAULT_WAKE_MODEL,
    };
    length = ainekio_encode_status(&status, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_STATUS);
    assert(strstr(output, "\"wake_enabled\":false") != NULL);
    assert(strstr(output, "\"wake_model\":\"ainekio\"") != NULL);
    assert(strstr(output, "\"wake_ready\":false") != NULL);
    length = ainekio_encode_event(AINEKIO_EVENT_LITTLEFS_FAIL, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_EVENT);
    length = ainekio_encode_camera_meta(AINEKIO_CAMERA_VGA, 5U, UINT32_MAX, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_CAMERA_META);
    length = ainekio_encode_ping(false, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_PING);
    length = ainekio_encode_ping(true, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_PONG);
    assert(ainekio_encode_ack(0U, 0U, output, sizeof(output)) == 0U);
    assert(ainekio_encode_hello("0.1.0", "id", "token", output, 8U) == 0U);
    puts("control encoder tests passed");
    return 0;
}
