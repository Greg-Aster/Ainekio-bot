#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "ainekio/v2_motion.h"

typedef struct {
    int8_t channel; /* -1 disables this joint; other channels must be unique. */
    uint8_t invert;
    uint16_t home_us;
    int32_t home_cd; /* Model angle at home_us, in centidegrees. */
    float us_per_degree; /* Positive; invert selects the direction. */
} ainekio_p4_joint_config_t;

typedef struct {
    uint32_t version;
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
} ainekio_p4_joint_record_t;

bool ainekio_p4_joints_valid(const ainekio_p4_joint_config_t *joints);
bool ainekio_p4_joint_defaults(ainekio_p4_joint_config_t *joints);
/* Display-only mounting reference; saved mappings remain unchanged. */
uint16_t ainekio_p4_joint_recommended_home(unsigned joint_id, bool inverted);
/* All-or-nothing: failure clears every pulse; enabled joints never clamp. */
bool ainekio_p4_joint_map_frame(const ainekio_p4_joint_config_t *joints,
                              const ainekio_v2_frame_t *frame,
                              uint16_t *pulses);

bool ainekio_p4_joint_unmap_frame(const ainekio_p4_joint_config_t *joints,
                                const uint16_t *pulses,ainekio_v2_frame_t *frame);
