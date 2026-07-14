#ifndef AINEKIO_ASSETS_H
#define AINEKIO_ASSETS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/protocol.h"
#include "ainekio/servo.h"

#define AINEKIO_MOTION_BINARY_HEADER_BYTES 24U
#define AINEKIO_MOTION_MAX_FRAMES 256U
#define AINEKIO_MOTION_MAX_FACE_CUES 16U
#define AINEKIO_MOTION_MAX_EXPANDED_FRAMES 4096U

typedef enum {
    AINEKIO_FACE_MODE_ONCE = 0,
    AINEKIO_FACE_MODE_LOOP,
    AINEKIO_FACE_MODE_BOOMERANG,
} ainekio_face_mode_t;

typedef struct {
    uint8_t joint_id;
    uint16_t centidegrees;
} ainekio_motion_target_t;

typedef struct {
    uint16_t duration_ms;
    uint8_t target_count;
    ainekio_motion_target_t targets[AINEKIO_SERVO_COUNT];
} ainekio_motion_frame_t;

typedef struct {
    uint16_t frame_index;
    ainekio_face_mode_t mode;
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
} ainekio_motion_face_cue_t;

typedef struct {
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    char return_pose[AINEKIO_ASSET_NAME_MAX + 1U];
    uint16_t frame_count;
    uint8_t repeat_count;
    uint8_t face_cue_count;
    ainekio_motion_face_cue_t face_cues[AINEKIO_MOTION_MAX_FACE_CUES];
    ainekio_motion_frame_t frames[AINEKIO_MOTION_MAX_FRAMES];
} ainekio_motion_asset_t;

typedef enum {
    AINEKIO_ASSET_OK = 0,
    AINEKIO_ASSET_TRUNCATED,
    AINEKIO_ASSET_VERSION,
    AINEKIO_ASSET_MALFORMED,
    AINEKIO_ASSET_CHECKSUM,
    AINEKIO_ASSET_LIMIT,
} ainekio_asset_result_t;

typedef enum {
    AINEKIO_FALLBACK_NEUTRAL = 0,
    AINEKIO_FALLBACK_STAND,
} ainekio_fallback_motion_t;

bool ainekio_asset_name_valid(const char *name);
ainekio_asset_result_t ainekio_motion_asset_decode(
    const uint8_t *bytes,
    size_t length,
    ainekio_motion_asset_t *asset
);
ainekio_asset_result_t ainekio_motion_asset_check_limits(
    const ainekio_motion_asset_t *asset,
    const ainekio_servo_bank_t *servos
);
void ainekio_motion_asset_fallback(
    ainekio_fallback_motion_t fallback,
    ainekio_motion_asset_t *asset
);

#endif
