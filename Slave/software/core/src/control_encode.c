#include "ainekio/control_encode.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "ainekio/assets.h"

typedef struct {
    char *output;
    size_t capacity;
    size_t length;
    bool failed;
} json_writer_t;

static void append_bytes(json_writer_t *writer, const char *value, size_t length)
{
    if (writer->failed || length > writer->capacity - writer->length - 1U) {
        writer->failed = true;
        return;
    }
    memcpy(writer->output + writer->length, value, length);
    writer->length += length;
    writer->output[writer->length] = '\0';
}

static void append_literal(json_writer_t *writer, const char *value)
{
    append_bytes(writer, value, strlen(value));
}

static void append_u32(json_writer_t *writer, uint32_t value)
{
    char buffer[16];
    const int length = snprintf(buffer, sizeof(buffer), "%lu", (unsigned long)value);
    if (length <= 0 || (size_t)length >= sizeof(buffer)) {
        writer->failed = true;
        return;
    }
    append_bytes(writer, buffer, (size_t)length);
}

static void append_i32(json_writer_t *writer, int32_t value)
{
    char buffer[16];
    const int length = snprintf(buffer, sizeof(buffer), "%ld", (long)value);
    if (length <= 0 || (size_t)length >= sizeof(buffer)) {
        writer->failed = true;
        return;
    }
    append_bytes(writer, buffer, (size_t)length);
}

static void append_float(json_writer_t *writer, float value)
{
    if (!isfinite(value)) {
        writer->failed = true;
        return;
    }
    char buffer[32];
    const int length = snprintf(buffer, sizeof(buffer), "%.3f", (double)value);
    if (length <= 0 || (size_t)length >= sizeof(buffer)) {
        writer->failed = true;
        return;
    }
    append_bytes(writer, buffer, (size_t)length);
}

static void append_string(json_writer_t *writer, const char *value, size_t maximum)
{
    if (value == NULL) {
        writer->failed = true;
        return;
    }
    append_literal(writer, "\"");
    size_t count = 0U;
    while (value[count] != '\0') {
        if (++count > maximum) {
            writer->failed = true;
            return;
        }
        const unsigned char character = (unsigned char)value[count - 1U];
        if (character < 0x20U) {
            char escaped[7];
            const int length = snprintf(escaped, sizeof(escaped), "\\u%04x", character);
            if (length != 6) {
                writer->failed = true;
                return;
            }
            append_bytes(writer, escaped, 6U);
        } else if (character == '"' || character == '\\') {
            const char escaped[2] = {'\\', (char)character};
            append_bytes(writer, escaped, sizeof(escaped));
        } else {
            append_bytes(writer, (const char *)&value[count - 1U], 1U);
        }
    }
    append_literal(writer, "\"");
}

static size_t finish(json_writer_t *writer)
{
    return writer->failed ? 0U : writer->length;
}

static json_writer_t begin(char *output, size_t capacity)
{
    json_writer_t writer = {.output = output, .capacity = capacity};
    if (output == NULL || capacity == 0U) {
        writer.failed = true;
    } else {
        output[0] = '\0';
    }
    return writer;
}

size_t ainekio_encode_hello(
    const char *firmware,
    const char *robot_id,
    const char *auth_token,
    char *output,
    size_t capacity
)
{
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"hello\",\"ver\":1,\"fw\":");
    append_string(&writer, firmware, 32U);
    append_literal(&writer, ",\"id\":");
    append_string(&writer, robot_id, 64U);
    append_literal(&writer, ",\"auth\":");
    append_string(&writer, auth_token, 128U);
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_ack(
    uint32_t sequence,
    uint32_t sleep_seconds,
    char *output,
    size_t capacity
)
{
    if (sequence == 0U || sequence > AINEKIO_MAX_SEQUENCE ||
        (sleep_seconds != 0U && (sleep_seconds < 60U || sleep_seconds > 86400U))) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"ack\",\"seq\":");
    append_u32(&writer, sequence);
    if (sleep_seconds != 0U) {
        append_literal(&writer, ",\"sleep_s\":");
        append_u32(&writer, sleep_seconds);
    }
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_nak(
    bool has_sequence,
    uint32_t sequence,
    ainekio_nak_code_t code,
    const char *message,
    char *output,
    size_t capacity
)
{
    static const char *const codes[] = {
        "stale", "mode", "unsafe", "limit", "unknown", "busy",
        "profile", "malformed", "asset_missing",
    };
    if ((unsigned int)code >= sizeof(codes) / sizeof(codes[0]) ||
        (!has_sequence && code != AINEKIO_NAK_MALFORMED) ||
        (has_sequence && (sequence == 0U || sequence > AINEKIO_MAX_SEQUENCE))) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"nak\"");
    if (has_sequence) {
        append_literal(&writer, ",\"seq\":");
        append_u32(&writer, sequence);
    }
    append_literal(&writer, ",\"code\":\"");
    append_literal(&writer, codes[code]);
    append_literal(&writer, "\"");
    if (message != NULL && message[0] != '\0') {
        append_literal(&writer, ",\"msg\":");
        append_string(&writer, message, 160U);
    }
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_done(uint32_t sequence, char *output, size_t capacity)
{
    if (sequence == 0U || sequence > AINEKIO_MAX_SEQUENCE) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"done\",\"seq\":");
    append_u32(&writer, sequence);
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_cancelled(
    uint32_t sequence,
    ainekio_cancel_code_t code,
    char *output,
    size_t capacity
)
{
    static const char *const codes[] = {"stop", "disconnect", "reconnect", "overflow"};
    if (sequence == 0U || sequence > AINEKIO_MAX_SEQUENCE ||
        (unsigned int)code >= sizeof(codes) / sizeof(codes[0])) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"cancelled\",\"seq\":");
    append_u32(&writer, sequence);
    append_literal(&writer, ",\"code\":\"");
    append_literal(&writer, codes[code]);
    append_literal(&writer, "\"}");
    return finish(&writer);
}

size_t ainekio_encode_status(
    const ainekio_status_t *status,
    char *output,
    size_t capacity
)
{
    static const char *const states[] = {
        "active", "idle", "dozing", "deep-sleep", "failsafe",
    };
    if (status == NULL || (unsigned int)status->state >= sizeof(states) / sizeof(states[0]) ||
        status->rssi > 0 || !isfinite(status->battery_voltage) ||
        !ainekio_asset_name_valid(status->wake_model)) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"status\",\"vbat\":");
    append_float(&writer, status->battery_voltage);
    append_literal(&writer, ",\"rssi\":");
    append_i32(&writer, status->rssi);
    append_literal(&writer, ",\"state\":\"");
    append_literal(&writer, states[status->state]);
    append_literal(&writer, "\",\"uptime\":");
    append_u32(&writer, status->uptime_seconds);
    append_literal(&writer, ",\"heap\":");
    append_u32(&writer, status->free_heap);
    append_literal(&writer, ",\"sd\":");
    append_literal(&writer, status->sd_available ? "true" : "false");
    append_literal(&writer, ",\"camera_ready\":");
    append_literal(&writer, status->camera_ready ? "true" : "false");
    append_literal(&writer, ",\"cam_drops\":");
    append_u32(&writer, status->camera_drops);
    append_literal(&writer, ",\"spk_underruns\":");
    append_u32(&writer, status->speaker_underruns);
    append_literal(&writer, ",\"mic_drops\":");
    append_u32(&writer, status->microphone_drops);
    append_literal(&writer, ",\"wake_enabled\":");
    append_literal(&writer, status->wake_enabled ? "true" : "false");
    append_literal(&writer, ",\"wake_model\":\"");
    append_literal(&writer, status->wake_model);
    append_literal(&writer, "\",\"wake_ready\":");
    append_literal(&writer, status->wake_ready ? "true" : "false");
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_event(ainekio_event_t event, char *output, size_t capacity)
{
    static const char *const names[] = {
        "vad_open", "vad_close", "wake_word", "battery_warn", "battery_cutoff",
        "brownout_recovered", "boot", "sd_fail", "sd_corrupt", "littlefs_fail",
        "asset_missing", "tts_orphan", "tts_overflow",
    };
    if ((unsigned int)event >= sizeof(names) / sizeof(names[0])) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"event\",\"name\":\"");
    append_literal(&writer, names[event]);
    append_literal(&writer, "\"}");
    return finish(&writer);
}

size_t ainekio_encode_camera_meta(
    ainekio_camera_resolution_t resolution,
    uint8_t fps,
    uint32_t counter_base,
    char *output,
    size_t capacity
)
{
    if (resolution > AINEKIO_CAMERA_VGA || fps > 15U) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"cam_meta\",\"res\":\"");
    append_literal(&writer, resolution == AINEKIO_CAMERA_QVGA ? "QVGA" : "VGA");
    append_literal(&writer, "\",\"fps\":");
    append_u32(&writer, fps);
    append_literal(&writer, ",\"counter_base\":");
    append_u32(&writer, counter_base);
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_ping(bool pong, char *output, size_t capacity)
{
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, pong ? "{\"t\":\"pong\"}" : "{\"t\":\"ping\"}");
    return finish(&writer);
}
