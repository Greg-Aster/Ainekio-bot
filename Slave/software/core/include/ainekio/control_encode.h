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

/* Optional body declarations share the same wire encoder as the base messages. */
typedef struct {
    const char *const *commands;
    size_t command_count;
    bool motion, camera, microphone, speaker, wake, profile, power, storage, display;
    const char *motion_reason, *camera_reason, *microphone_reason, *speaker_reason, *display_reason;
} ainekio_capabilities_t;

typedef struct {
    const char *firmware, *robot_id, *auth_token;
    const char *const *features;
    size_t feature_count;
    const char *model;
    uint64_t clock_ms;
    const ainekio_capabilities_t *capabilities;
} ainekio_hello_t;

typedef struct {
    ainekio_mode_t mode;
    bool output_ready, output_armed;
    unsigned output_fault;
    bool calibration_dirty, calibration_saved, power_monitor_ready;
    bool microphone_ready, speaker_ready, display_ready;
    const ainekio_capabilities_t *capabilities;
} ainekio_body_status_fields_t;

typedef struct {
    float battery_voltage;
    int8_t rssi;
    ainekio_body_state_t state;
    uint32_t uptime_seconds;
    uint32_t free_heap;
    bool sd_available;
    bool camera_ready;
    uint32_t camera_drops;
    const ainekio_camera_capture_t *camera_capture;
    uint32_t speaker_underruns;
    uint32_t microphone_drops;
    bool wake_enabled;
    bool wake_ready;
    char wake_model[AINEKIO_WAKE_MODEL_MAX + 1U];
    const ainekio_body_status_fields_t *body;
} ainekio_status_t;

size_t ainekio_encode_hello(
    const ainekio_hello_t *hello,
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
size_t ainekio_encode_event(
    ainekio_event_t event,
    bool has_origin_id,
    uint32_t origin_id,
    char *output,
    size_t capacity
);
size_t ainekio_encode_camera_meta(
    ainekio_camera_resolution_t resolution,
    uint8_t fps,
    uint32_t counter_base,
    ainekio_camera_origin_t origin,
    uint32_t origin_id,
    char *output,
    size_t capacity
);
size_t ainekio_encode_ping(bool pong, char *output, size_t capacity);

#endif
