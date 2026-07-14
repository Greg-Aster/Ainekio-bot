#ifndef AINEKIO_PROTOCOL_H
#define AINEKIO_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_PROTOCOL_VERSION 1U
#define AINEKIO_ASSET_NAME_MAX 32U
#define AINEKIO_SERVO_COUNT 8U
#define AINEKIO_MAX_SEQUENCE 0x7FFFFFFFU
#define AINEKIO_JOINT_MAP_VERSION 1U

typedef enum {
    AINEKIO_JOINT_R1 = 0,
    AINEKIO_JOINT_R2,
    AINEKIO_JOINT_L1,
    AINEKIO_JOINT_L2,
    AINEKIO_JOINT_R4,
    AINEKIO_JOINT_R3,
    AINEKIO_JOINT_L3,
    AINEKIO_JOINT_L4,
} ainekio_joint_id_t;

typedef enum {
    AINEKIO_COMMAND_INTENT = 0,
    AINEKIO_COMMAND_STOP,
    AINEKIO_COMMAND_TTS,
    AINEKIO_COMMAND_CAMERA,
    AINEKIO_COMMAND_SNAPSHOT,
    AINEKIO_COMMAND_MICROPHONE,
    AINEKIO_COMMAND_PROFILE,
    AINEKIO_COMMAND_STATE,
    AINEKIO_COMMAND_MODE,
    AINEKIO_COMMAND_SERVO,
    AINEKIO_COMMAND_LIMITS,
    AINEKIO_COMMAND_POSE_SAVE,
    AINEKIO_COMMAND_CALIBRATION_SAVE,
} ainekio_command_kind_t;

typedef enum {
    AINEKIO_INTENT_SIT = 0,
    AINEKIO_INTENT_STAND,
    AINEKIO_INTENT_NEUTRAL,
    AINEKIO_INTENT_LOOK,
    AINEKIO_INTENT_WALK,
    AINEKIO_INTENT_EMOTE,
    AINEKIO_INTENT_FACE,
    AINEKIO_INTENT_SAY,
} ainekio_intent_kind_t;

typedef enum {
    AINEKIO_WALK_FORWARD = 0,
    AINEKIO_WALK_BACKWARD,
    AINEKIO_WALK_TURN_LEFT,
    AINEKIO_WALK_TURN_RIGHT,
} ainekio_walk_direction_t;

typedef enum {
    AINEKIO_TTS_START = 0,
    AINEKIO_TTS_END,
    AINEKIO_TTS_CANCEL,
} ainekio_tts_operation_t;

typedef enum {
    AINEKIO_PROFILE_HOME = 0,
    AINEKIO_PROFILE_TETHER,
} ainekio_profile_t;

typedef enum {
    AINEKIO_CAMERA_QVGA = 0,
    AINEKIO_CAMERA_VGA,
} ainekio_camera_resolution_t;

typedef enum {
    AINEKIO_MIC_GATE_OPEN = 0,
    AINEKIO_MIC_GATE_VAD,
    AINEKIO_MIC_GATE_WAKE,
} ainekio_microphone_gate_t;

typedef enum {
    AINEKIO_STATE_ACTIVE = 0,
    AINEKIO_STATE_IDLE,
    AINEKIO_STATE_DOZING,
    AINEKIO_STATE_DEEP_SLEEP,
    AINEKIO_STATE_FAILSAFE,
} ainekio_body_state_t;

typedef enum {
    AINEKIO_STATE_REQUEST_IDLE = 0,
    AINEKIO_STATE_REQUEST_DOZE,
    AINEKIO_STATE_REQUEST_SLEEP,
} ainekio_state_request_t;

typedef enum {
    AINEKIO_MODE_NORMAL = 0,
    AINEKIO_MODE_CALIBRATE,
} ainekio_mode_t;

typedef struct {
    uint8_t id;
    float degrees;
} ainekio_servo_target_t;

typedef struct {
    ainekio_intent_kind_t kind;
    union {
        struct {
            int16_t yaw;
            int16_t pitch;
            uint16_t duration_ms;
        } look;
        struct {
            ainekio_walk_direction_t direction;
            uint8_t steps;
        } walk;
        char asset[AINEKIO_ASSET_NAME_MAX + 1U];
    } data;
} ainekio_intent_t;

typedef struct {
    uint32_t sequence;
    ainekio_command_kind_t kind;
    union {
        ainekio_intent_t intent;
        ainekio_tts_operation_t tts_operation;
        struct {
            bool enabled;
            uint8_t fps;
            ainekio_camera_resolution_t resolution;
        } camera;
        struct {
            bool enabled;
            ainekio_microphone_gate_t gate;
        } microphone;
        ainekio_profile_t profile;
        struct {
            ainekio_state_request_t request;
            uint32_t sleep_seconds;
        } state;
        ainekio_mode_t mode;
        struct {
            uint8_t id;
            float degrees;
            uint16_t duration_ms;
        } servo;
        struct {
            uint8_t id;
            float minimum;
            float maximum;
            float center;
            bool invert;
        } limits;
        struct {
            char name[AINEKIO_ASSET_NAME_MAX + 1U];
            uint8_t count;
            ainekio_servo_target_t targets[AINEKIO_SERVO_COUNT];
        } pose;
    } data;
} ainekio_command_t;

bool ainekio_intent_is_movement(ainekio_intent_kind_t intent);
const char *ainekio_joint_label(uint8_t joint_id);

#endif
