#ifndef AINEKIO_CONTROL_CODEC_H
#define AINEKIO_CONTROL_CODEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/protocol.h"

#define AINEKIO_CONTROL_MAX_BYTES 4096U

typedef enum {
    AINEKIO_MESSAGE_HELLO = 0,
    AINEKIO_MESSAGE_ERROR,
    AINEKIO_MESSAGE_WELCOME,
    AINEKIO_MESSAGE_INTENT,
    AINEKIO_MESSAGE_STOP,
    AINEKIO_MESSAGE_MOTION_PLAN,
    AINEKIO_MESSAGE_TTS,
    AINEKIO_MESSAGE_CAMERA,
    AINEKIO_MESSAGE_SNAPSHOT,
    AINEKIO_MESSAGE_MICROPHONE,
    AINEKIO_MESSAGE_WAKE_CONFIG,
    AINEKIO_MESSAGE_PROFILE,
    AINEKIO_MESSAGE_STATE,
    AINEKIO_MESSAGE_PING,
    AINEKIO_MESSAGE_MODE,
    AINEKIO_MESSAGE_SERVO,
    AINEKIO_MESSAGE_LIMITS,
    AINEKIO_MESSAGE_POSE_SAVE,
    AINEKIO_MESSAGE_CALIBRATION_SAVE,
    AINEKIO_MESSAGE_ACK,
    AINEKIO_MESSAGE_NAK,
    AINEKIO_MESSAGE_DONE,
    AINEKIO_MESSAGE_CANCELLED,
    AINEKIO_MESSAGE_STATUS,
    AINEKIO_MESSAGE_EVENT,
    AINEKIO_MESSAGE_CAMERA_META,
    AINEKIO_MESSAGE_PONG,
    AINEKIO_MESSAGE_BODY_CALIBRATION,
    AINEKIO_MESSAGE_STORAGE,
} ainekio_message_kind_t;

typedef enum {
    AINEKIO_DECODE_OK = 0,
    AINEKIO_DECODE_OVERSIZE,
    AINEKIO_DECODE_JSON,
    AINEKIO_DECODE_TOKENS,
    AINEKIO_DECODE_TYPE,
    AINEKIO_DECODE_MISSING,
    AINEKIO_DECODE_RANGE,
    AINEKIO_DECODE_VALUE,
    AINEKIO_DECODE_UNKNOWN,
} ainekio_decode_result_t;

typedef enum {
    AINEKIO_SESSION_ERROR_AUTH = 0,
    AINEKIO_SESSION_ERROR_VERSION,
} ainekio_session_error_t;

typedef struct {
    ainekio_message_kind_t kind;
    bool has_sequence;
    bool has_command;
    uint32_t sequence;
    bool has_epoch;
    uint32_t epoch;
    bool has_deadline;
    uint64_t deadline_ms;
    ainekio_command_t command;
    union {
        struct {
            uint32_t epoch;
            ainekio_profile_t profile;
            bool deadline_supported;
        } welcome;
        ainekio_session_error_t session_error;
    } data;
} ainekio_control_message_t;

ainekio_decode_result_t ainekio_control_decode(
    const char *json,
    size_t length,
    ainekio_control_message_t *message
);
/* P4 calibration, storage and walking extensions; V1 decoding is unchanged. */
ainekio_decode_result_t ainekio_control_decode_for_body(
    const char *json, size_t length, ainekio_control_message_t *message);
const char *ainekio_decode_result_name(ainekio_decode_result_t result);

/* Explicit V2 extension. Default/V1 decoding rejects these fields. */
ainekio_decode_result_t ainekio_control_decode_with_walk_controls(
    const char *json, size_t length, ainekio_control_message_t *message);

#endif
