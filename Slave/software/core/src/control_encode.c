#include "ainekio/control_encode.h"

#include <math.h>
#include <inttypes.h>
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

static void bool_field(json_writer_t *writer, const char *name, bool value)
{
    append_literal(writer, ",");
    append_string(writer, name, SIZE_MAX);
    append_literal(writer, value ? ":true" : ":false");
}

static void string_array(json_writer_t *writer, const char *const *values, size_t count)
{
    if (count && !values) { writer->failed = true; return; }
    append_literal(writer, "[");
    for (size_t i = 0; i < count; ++i) {
        if (i) append_literal(writer, ",");
        append_string(writer, values[i], SIZE_MAX);
    }
    append_literal(writer, "]");
}

static void capabilities(json_writer_t *writer, const ainekio_capabilities_t *caps)
{
    if (!caps) return;
    append_literal(writer, ",\"capabilities\":{\"commands\":");
    string_array(writer, caps->commands, caps->command_count);
    bool_field(writer, "motion", caps->motion);
    bool_field(writer, "camera", caps->camera);
    bool_field(writer, "microphone", caps->microphone);
    bool_field(writer, "speaker", caps->speaker);
    bool_field(writer, "wake", caps->wake);
    bool_field(writer, "profile", caps->profile);
    bool_field(writer, "power", caps->power);
    bool_field(writer, "storage", caps->storage);
    bool_field(writer, "display", caps->display);
    const char *names[] = {"motion", "camera", "microphone", "speaker", "display"};
    const char *reasons[] = {caps->motion_reason, caps->camera_reason, caps->microphone_reason,
                             caps->speaker_reason, caps->display_reason};
    append_literal(writer, ",\"reasons\":{");
    bool comma = false;
    for (size_t i = 0; i < sizeof(names)/sizeof(names[0]); ++i) {
        if (!reasons[i]) continue;
        if (comma) append_literal(writer, ",");
        append_string(writer, names[i], SIZE_MAX);
        append_literal(writer, ":");
        append_string(writer, reasons[i], SIZE_MAX);
        comma = true;
    }
    append_literal(writer, "}}");
}

size_t ainekio_encode_hello(const ainekio_hello_t *hello, char *output, size_t capacity)
{
    if (!hello || (hello->feature_count && !hello->features)) return 0;
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"hello\",\"ver\":1,\"fw\":");
    append_string(&writer, hello->firmware, 32U);
    append_literal(&writer, ",\"id\":");
    append_string(&writer, hello->robot_id, 64U);
    append_literal(&writer, ",\"auth\":");
    append_string(&writer, hello->auth_token, 128U);
    if (hello->feature_count) {
        append_literal(&writer, ",\"features\":");
        string_array(&writer, hello->features, hello->feature_count);
    }
    if (hello->model) {
        append_literal(&writer, ",\"model\":");
        append_string(&writer, hello->model, SIZE_MAX);
        char clock[32];
        snprintf(clock, sizeof(clock), "%" PRIu64, hello->clock_ms);
        append_literal(&writer, ",\"clock_ms\":");
        append_literal(&writer, clock);
    }
    capabilities(&writer, hello->capabilities);
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
    if (status->camera_capture && status->camera_capture->counter) {
        const ainekio_camera_capture_t *capture = status->camera_capture;
        append_literal(&writer, ",\"camera_capture\":{\"counter\":");
        append_u32(&writer, capture->counter);
        append_literal(&writer, ",\"width\":"); append_u32(&writer, capture->width);
        append_literal(&writer, ",\"height\":"); append_u32(&writer, capture->height);
        append_literal(&writer, ",\"exposure_us\":"); append_u32(&writer, capture->exposure_us);
        append_literal(&writer, ",\"gain_x16\":"); append_u32(&writer, capture->gain_x16);
        append_literal(&writer, ",\"settle_ms\":"); append_u32(&writer, capture->settle_ms);
        append_literal(&writer, ",\"settled\":"); append_literal(&writer, capture->settled ? "true}" : "false}");
    }
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
    if (status->body) {
        const ainekio_body_status_fields_t *body = status->body;
        append_literal(&writer, ",\"mode\":");
        append_string(&writer, body->mode == AINEKIO_MODE_CALIBRATE ? "calibrate" : "normal", SIZE_MAX);
        bool_field(&writer, "output_ready", body->output_ready);
        bool_field(&writer, "output_armed", body->output_armed);
        append_literal(&writer, ",\"output_fault\":");
        append_u32(&writer, body->output_fault);
        bool_field(&writer, "calibration_dirty", body->calibration_dirty);
        bool_field(&writer, "calibration_saved", body->calibration_saved);
        bool_field(&writer, "power_monitor_ready", body->power_monitor_ready);
        bool_field(&writer, "microphone_ready", body->microphone_ready);
        bool_field(&writer, "speaker_ready", body->speaker_ready);
        bool_field(&writer, "display_ready", body->display_ready);
        capabilities(&writer, body->capabilities);
    }
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_event(
    ainekio_event_t event,
    bool has_origin_id,
    uint32_t origin_id,
    char *output,
    size_t capacity
)
{
    static const char *const names[] = {
        "vad_open", "vad_close", "wake_word", "battery_warn", "battery_cutoff",
        "brownout_recovered", "boot", "sd_fail", "sd_corrupt", "littlefs_fail",
        "asset_missing", "tts_orphan", "tts_overflow",
    };
    if ((unsigned int)event >= sizeof(names) / sizeof(names[0]) ||
        (has_origin_id && event != AINEKIO_EVENT_VAD_OPEN &&
         event != AINEKIO_EVENT_VAD_CLOSE)) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"event\",\"name\":\"");
    append_literal(&writer, names[event]);
    append_literal(&writer, "\"");
    if (has_origin_id) {
        append_literal(&writer, ",\"origin_id\":");
        append_u32(&writer, origin_id);
    }
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_camera_meta(
    ainekio_camera_resolution_t resolution,
    uint8_t fps,
    uint32_t counter_base,
    ainekio_camera_origin_t origin,
    uint32_t origin_id,
    char *output,
    size_t capacity
)
{
    static const char *const resolutions[] = {"QVGA", "VGA", "XGA", "960P", "FHD"};
    static const char *const origins[] = {"", "request", "action", "audio"};
    if ((unsigned int)resolution >=
            sizeof(resolutions) / sizeof(resolutions[0]) ||
        fps > 15U ||
        (unsigned int)origin >= sizeof(origins) / sizeof(origins[0]) ||
        (origin == AINEKIO_CAMERA_ORIGIN_NONE && origin_id != 0U) ||
        ((origin == AINEKIO_CAMERA_ORIGIN_REQUEST ||
          origin == AINEKIO_CAMERA_ORIGIN_ACTION) &&
         (origin_id == 0U || origin_id > AINEKIO_MAX_SEQUENCE))) {
        return 0U;
    }
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, "{\"t\":\"cam_meta\",\"res\":\"");
    append_literal(&writer, resolutions[resolution]);
    append_literal(&writer, "\",\"fps\":");
    /* Correlated stills have no cadence, even while preview is streaming. */
    append_u32(&writer, origin == AINEKIO_CAMERA_ORIGIN_NONE ? fps : 0U);
    append_literal(&writer, ",\"counter_base\":");
    append_u32(&writer, counter_base);
    if (origin != AINEKIO_CAMERA_ORIGIN_NONE) {
        append_literal(&writer, ",\"origin\":\"");
        append_literal(&writer, origins[origin]);
        append_literal(&writer, "\",\"origin_id\":");
        append_u32(&writer, origin_id);
    }
    append_literal(&writer, "}");
    return finish(&writer);
}

size_t ainekio_encode_ping(bool pong, char *output, size_t capacity)
{
    json_writer_t writer = begin(output, capacity);
    append_literal(&writer, pong ? "{\"t\":\"pong\"}" : "{\"t\":\"ping\"}");
    return finish(&writer);
}
