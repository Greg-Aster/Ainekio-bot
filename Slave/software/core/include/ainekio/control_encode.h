#ifndef AINEKIO_CONTROL_ENCODE_H
#define AINEKIO_CONTROL_ENCODE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/protocol.h"

typedef enum {
    AINEKIO_NAK_STALE = 0,
    AINEKIO_NAK_MODE,
    AINEKIO_NAK_UNSAFE,
    AINEKIO_NAK_LIMIT,
    AINEKIO_NAK_UNKNOWN,
    AINEKIO_NAK_BUSY,
    AINEKIO_NAK_PROFILE,
    AINEKIO_NAK_MALFORMED,
    AINEKIO_NAK_ASSET_MISSING,
} ainekio_nak_code_t;

typedef enum {
    AINEKIO_CANCEL_STOP = 0,
    AINEKIO_CANCEL_DISCONNECT,
    AINEKIO_CANCEL_RECONNECT,
    AINEKIO_CANCEL_OVERFLOW,
} ainekio_cancel_code_t;

typedef enum {
    AINEKIO_EVENT_VAD_OPEN = 0,
    AINEKIO_EVENT_VAD_CLOSE,
    AINEKIO_EVENT_WAKE_WORD,
    AINEKIO_EVENT_BATTERY_WARN,
    AINEKIO_EVENT_BATTERY_CUTOFF,
    AINEKIO_EVENT_BROWNOUT_RECOVERED,
    AINEKIO_EVENT_BOOT,
    AINEKIO_EVENT_SD_FAIL,
    AINEKIO_EVENT_SD_CORRUPT,
    AINEKIO_EVENT_LITTLEFS_FAIL,
    AINEKIO_EVENT_ASSET_MISSING,
    AINEKIO_EVENT_TTS_ORPHAN,
    AINEKIO_EVENT_TTS_OVERFLOW,
} ainekio_event_t;

typedef struct {
    float battery_voltage;
    int8_t rssi;
    ainekio_body_state_t state;
    uint32_t uptime_seconds;
    uint32_t free_heap;
    bool sd_available;
    uint32_t camera_drops;
    uint32_t speaker_underruns;
    uint32_t microphone_drops;
} ainekio_status_t;

size_t ainekio_encode_hello(
    const char *firmware,
    const char *robot_id,
    const char *auth_token,
    char *output,
    size_t capacity
);
size_t ainekio_encode_ack(
    uint32_t sequence,
    uint32_t sleep_seconds,
    char *output,
    size_t capacity
);
size_t ainekio_encode_nak(
    bool has_sequence,
    uint32_t sequence,
    ainekio_nak_code_t code,
    const char *message,
    char *output,
    size_t capacity
);
size_t ainekio_encode_done(uint32_t sequence, char *output, size_t capacity);
size_t ainekio_encode_cancelled(
    uint32_t sequence,
    ainekio_cancel_code_t code,
    char *output,
    size_t capacity
);
size_t ainekio_encode_status(
    const ainekio_status_t *status,
    char *output,
    size_t capacity
);
size_t ainekio_encode_event(ainekio_event_t event, char *output, size_t capacity);
size_t ainekio_encode_camera_meta(
    ainekio_camera_resolution_t resolution,
    uint8_t fps,
    uint32_t counter_base,
    char *output,
    size_t capacity
);
size_t ainekio_encode_ping(bool pong, char *output, size_t capacity);

#endif
