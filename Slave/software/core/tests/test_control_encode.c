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
    const char *detach_json = "{\"t\":\"stop\",\"seq\":1,\"detach\":true}";
    ainekio_control_message_t detach_message;
    assert(
        ainekio_control_decode(
            detach_json,
            strlen(detach_json),
            &detach_message
        ) == AINEKIO_DECODE_OK
    );
    assert(detach_message.command.kind == AINEKIO_COMMAND_STOP);
    assert(detach_message.command.data.stop.detach);

    const char *camera_json = "{\"t\":\"cam\",\"seq\":2,\"on\":true,\"fps\":5,\"res\":\"QVGA\",\"snapshot_res\":\"XGA\"}";
    ainekio_control_message_t camera_message;
    assert(ainekio_control_decode_for_body(camera_json, strlen(camera_json), &camera_message) == AINEKIO_DECODE_OK);
    assert(camera_message.command.data.camera.enabled && camera_message.command.data.camera.fps == 5);
    assert(camera_message.command.data.camera.resolution == AINEKIO_CAMERA_QVGA);
    assert(camera_message.command.data.camera.has_snapshot_resolution);
    assert(camera_message.command.data.camera.snapshot_resolution == AINEKIO_CAMERA_XGA);
    camera_json = "{\"t\":\"cam\",\"seq\":3,\"on\":false,\"fps\":0,\"res\":\"VGA\"}";
    assert(ainekio_control_decode_for_body(camera_json, strlen(camera_json), &camera_message) == AINEKIO_DECODE_OK);
    assert(!camera_message.command.data.camera.enabled && camera_message.command.data.camera.fps == 0);
    assert(!camera_message.command.data.camera.has_snapshot_resolution);

    const char *features[] = {"motion_plan_v1"};
    ainekio_hello_t hello = {.firmware="0.1.0\"test", .robot_id="ainekio-01", .auth_token="token\\value",
        .features=features, .feature_count=1};
    size_t length = ainekio_encode_hello(&hello, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_HELLO);
    assert(strstr(output, "\"features\":[\"motion_plan_v1\"]") != NULL);
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
        .camera_ready = true,
        .camera_drops = 4U,
        .microphone_drops = 2U,
        .wake_enabled = false,
        .wake_ready = false,
        .wake_model = AINEKIO_DEFAULT_WAKE_MODEL,
    };
    length = ainekio_encode_status(&status, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_STATUS);
    assert(strstr(output, "\"wake_enabled\":false") != NULL);
    assert(strstr(output, "\"camera_ready\":true") != NULL);
    assert(strstr(output, "\"wake_model\":\"ainekio\"") != NULL);
    assert(strstr(output, "\"wake_ready\":false") != NULL);
    length = ainekio_encode_event(
        AINEKIO_EVENT_LITTLEFS_FAIL,
        false,
        0U,
        output,
        sizeof(output)
    );
    valid(output, length, AINEKIO_MESSAGE_EVENT);
    length = ainekio_encode_event(
        AINEKIO_EVENT_VAD_OPEN,
        true,
        UINT32_MAX,
        output,
        sizeof(output)
    );
    valid(output, length, AINEKIO_MESSAGE_EVENT);
    assert(strstr(output, "\"origin_id\":4294967295") != NULL);
    length = ainekio_encode_camera_meta(
        AINEKIO_CAMERA_VGA,
        5U,
        UINT32_MAX,
        AINEKIO_CAMERA_ORIGIN_NONE,
        0U,
        output,
        sizeof(output)
    );
    valid(output, length, AINEKIO_MESSAGE_CAMERA_META);
    assert(strstr(output, "\"fps\":5") != NULL);
    length = ainekio_encode_camera_meta(
        AINEKIO_CAMERA_XGA,
        5U,
        1U,
        AINEKIO_CAMERA_ORIGIN_ACTION,
        4U,
        output,
        sizeof(output)
    );
    valid(output, length, AINEKIO_MESSAGE_CAMERA_META);
    assert(strstr(output, "\"res\":\"XGA\"") != NULL);
    assert(strstr(output, "\"origin\":\"action\"") != NULL);
    assert(strstr(output, "\"origin_id\":4") != NULL);
    assert(strstr(output, "\"fps\":0") != NULL);
    length = ainekio_encode_ping(false, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_PING);
    length = ainekio_encode_ping(true, output, sizeof(output));
    valid(output, length, AINEKIO_MESSAGE_PONG);
    assert(ainekio_encode_ack(0U, 0U, output, sizeof(output)) == 0U);
    assert(ainekio_encode_hello(&hello, output, 8U) == 0U);
    char body_output[4096];
    const char *commands[] = {"stop", "say", "walk", "bow"};
    const ainekio_capabilities_t caps = {.commands=commands, .command_count=4,
        .motion=true, .camera=true, .microphone=true, .speaker=true, .profile=true,
        .display_reason="Display \"pending\"."};
    hello.model = "v2-12servo";
    hello.clock_ms = UINT64_C(4294967296);
    hello.capabilities = &caps;
    length = ainekio_encode_hello(&hello, body_output, sizeof(body_output));
    valid(body_output, length, AINEKIO_MESSAGE_HELLO);
    assert(strstr(body_output, "\"clock_ms\":4294967296") != NULL);
    assert(strstr(body_output, "\"commands\":[\"stop\",\"say\",\"walk\",\"bow\"]") != NULL);
    assert(strstr(body_output, "Display \\\"pending\\\".") != NULL);
    const ainekio_body_status_fields_t body = {.mode=AINEKIO_MODE_CALIBRATE,
        .output_ready=true, .output_fault=3, .calibration_saved=true, .capabilities=&caps};
    ainekio_status_t body_status = status;
    body_status.body = &body;
    length = ainekio_encode_status(&body_status, body_output, sizeof(body_output));
    valid(body_output, length, AINEKIO_MESSAGE_STATUS);
    assert(strstr(body_output, "\"mode\":\"calibrate\"") != NULL);
    assert(strstr(body_output, "\"output_fault\":3") != NULL);
    assert(strstr(body_output, "\"motion\":true") != NULL);
    assert(ainekio_encode_status(&body_status, body_output, length) == 0);
    assert(ainekio_encode_hello(&hello, body_output, 0) == 0);
    puts("control encoder tests passed");
    return 0;
}
