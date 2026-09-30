#ifndef AINEKIO_PROTOCOL_H
#define AINEKIO_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_PROTOCOL_VERSION 1U
#define AINEKIO_MOTION_RATE_DEFAULT 2.F
#define AINEKIO_ASSET_NAME_MAX 32U
#define AINEKIO_WAKE_MODEL_MAX AINEKIO_ASSET_NAME_MAX
#define AINEKIO_DEFAULT_WAKE_MODEL "ainekio"
#define AINEKIO_SERVO_COUNT 8U
#define AINEKIO_MAX_SEQUENCE 0x7FFFFFFFU
#define AINEKIO_JOINT_MAP_VERSION 1U
#define AINEKIO_MOTION_PLAN_MAX_FRAMES 32U
#define AINEKIO_MOTION_PLAN_MIN_FRAME_MS 100U
#define AINEKIO_MOTION_PLAN_MAX_FRAME_MS 5000U
#define AINEKIO_MOTION_PLAN_MAX_TOTAL_MS 10000U
#define AINEKIO_MOTION_PLAN_MAX_CENTIDEGREES 18000U

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
    AINEKIO_COMMAND_MOTION_PLAN,
    AINEKIO_COMMAND_TTS,
    AINEKIO_COMMAND_CAMERA,
    AINEKIO_COMMAND_SNAPSHOT,
    AINEKIO_COMMAND_MICROPHONE,
    AINEKIO_COMMAND_WAKE_CONFIG,
    AINEKIO_COMMAND_PROFILE,
    AINEKIO_COMMAND_STATE,
    AINEKIO_COMMAND_MODE,
    AINEKIO_COMMAND_SERVO,
    AINEKIO_COMMAND_LIMITS,
    AINEKIO_COMMAND_POSE_SAVE,
    AINEKIO_COMMAND_CALIBRATION_SAVE,
    AINEKIO_COMMAND_BODY_CALIBRATION,
    AINEKIO_COMMAND_STORAGE,
    AINEKIO_COMMAND_MOTION_SPEED,
    AINEKIO_COMMAND_ROBOT_SETTINGS,
} ainekio_command_kind_t;

#define AINEKIO_NETWORK_SLOTS 4U
typedef enum {
    AINEKIO_SETTINGS_GET, AINEKIO_SETTINGS_NETWORK, AINEKIO_SETTINGS_REMOVE,
    AINEKIO_SETTINGS_SECURITY, AINEKIO_SETTINGS_APPLY,
} ainekio_robot_settings_operation_t;
typedef struct {
    ainekio_robot_settings_operation_t operation;
    uint32_t revision;
    uint8_t index;
    bool has_wifi_password, has_robot_token, has_setup_password;
    char ssid[33], wifi_password[65], endpoint[256], robot_token[129], setup_password[64];
} ainekio_robot_settings_command_t;

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
    AINEKIO_WALK_SIDE_LEFT,
    AINEKIO_WALK_SIDE_RIGHT,
} ainekio_walk_direction_t;

typedef enum {
    AINEKIO_GAIT_WALK = 0,
    AINEKIO_GAIT_CRAWL,
    AINEKIO_GAIT_RUN,
    AINEKIO_GAIT_CRAB,
} ainekio_gait_t;

typedef enum {
    AINEKIO_TTS_START = 0,
    AINEKIO_TTS_END,
    AINEKIO_TTS_CANCEL,
} ainekio_tts_operation_t;

typedef enum {
    AINEKIO_STORAGE_GET = 0,
    AINEKIO_STORAGE_RETRY,
    AINEKIO_STORAGE_CLEAR,
} ainekio_storage_operation_t;

typedef enum {
    AINEKIO_PROFILE_HOME = 0,
    AINEKIO_PROFILE_TETHER,
} ainekio_profile_t;

typedef enum {
    AINEKIO_CAMERA_QVGA = 0,
    AINEKIO_CAMERA_VGA,
    AINEKIO_CAMERA_XGA,
} ainekio_camera_resolution_t;

typedef enum {
    AINEKIO_CAMERA_ORIGIN_NONE = 0,
    AINEKIO_CAMERA_ORIGIN_REQUEST,
    AINEKIO_CAMERA_ORIGIN_ACTION,
    AINEKIO_CAMERA_ORIGIN_AUDIO,
} ainekio_camera_origin_t;

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

#define AINEKIO_BODY_JOINT_COUNT 12U
typedef enum {
    AINEKIO_CALIBRATION_GET = 0,
    AINEKIO_CALIBRATION_SET,
    AINEKIO_CALIBRATION_MOVE,
    AINEKIO_CALIBRATION_HOME,
    AINEKIO_CALIBRATION_SAVE,
} ainekio_calibration_operation_t;

typedef enum {
    AINEKIO_MOTION_PLAN_END_HOLD = 0,
    AINEKIO_MOTION_PLAN_END_STAND,
    AINEKIO_MOTION_PLAN_END_NEUTRAL,
} ainekio_motion_plan_end_t;

typedef struct {
    uint16_t duration_ms;
    uint16_t targets[AINEKIO_SERVO_COUNT];
} ainekio_motion_plan_frame_t;

typedef struct {
    uint8_t joint_map_version;
    uint8_t frame_count;
    uint16_t total_duration_ms;
    ainekio_motion_plan_end_t end;
    ainekio_motion_plan_frame_t frames[AINEKIO_MOTION_PLAN_MAX_FRAMES];
} ainekio_motion_plan_t;

typedef struct {
    ainekio_intent_kind_t kind;
    float playback_rate; /* 0 uses the saved body setting; named motions only. */
    union {
        struct {
            int16_t yaw;
            int16_t pitch;
            uint16_t duration_ms;
        } look;
        struct {
            ainekio_walk_direction_t direction;
            uint8_t steps; /* zero means ongoing in the V2 decoder */
            ainekio_gait_t gait;
            uint8_t controls; /* 0 legacy/default, 1 automatic speed, 2 stride/rate */
            float speed_percent;
            float stride_percent;
            float motion_rate;
            uint32_t update_sequence; /* active walk sequence; zero starts a walk */
        } walk;
        char asset[AINEKIO_ASSET_NAME_MAX + 1U];
    } data;
} ainekio_intent_t;

typedef struct {
    uint32_t sequence;
    ainekio_command_kind_t kind;
    union {
        struct {
            ainekio_calibration_operation_t operation;
            int8_t id; /* -1 means all joints for home/get/save. */
            int8_t channel; /* -1 disables a joint. */
            /* Positive uint16 wire values; the body checks PWM representability.
             * The protocol does not prescribe a servo's usable travel. */
            uint16_t home_us;
            uint16_t pulse_us;
            bool invert;
            bool has_mapping; /* Absent optional fields preserve the saved mapping. */
            int32_t home_cd;
            float us_per_degree;
        } calibration;
        struct {
            bool detach;
        } stop;
        ainekio_intent_t intent;
        ainekio_motion_plan_t motion_plan;
        ainekio_tts_operation_t tts_operation;
        ainekio_storage_operation_t storage_operation;
        ainekio_robot_settings_command_t robot_settings;
        struct { bool save; float rate; } motion_speed;
        struct {
            bool enabled;
            uint8_t fps;
            ainekio_camera_resolution_t resolution;
        } camera;
        struct {
            bool enabled;
            ainekio_microphone_gate_t gate;
        } microphone;
        struct {
            bool enabled;
            char model[AINEKIO_WAKE_MODEL_MAX + 1U];
        } wake;
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
