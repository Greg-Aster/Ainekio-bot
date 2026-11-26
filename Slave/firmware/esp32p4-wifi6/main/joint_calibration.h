#pragma once

#include <stdbool.h>
#include <stdint.h>
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#include "ainekio/v2_motion.h"

#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
#define AINEKIO_P4_ACTIVE_JOINTS 8U
#define AINEKIO_P4_ACTIVE_MASK 0x00FFU
#define AINEKIO_P4_JOINT_MAP_VERSION AINEKIO_JOINT_MAP_VERSION
#define AINEKIO_P4_MODEL_NAME "v1-8servo"
#elif defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
#define AINEKIO_P4_ACTIVE_JOINTS AINEKIO_BODY_JOINT_COUNT
#define AINEKIO_P4_ACTIVE_MASK 0x0FFFU
#define AINEKIO_P4_JOINT_MAP_VERSION AINEKIO_V2_JOINT_MAP_VERSION
#define AINEKIO_P4_MODEL_NAME "v3-12servo"
#else
#define AINEKIO_P4_ACTIVE_JOINTS AINEKIO_BODY_JOINT_COUNT
#define AINEKIO_P4_ACTIVE_MASK 0x0FFFU
#define AINEKIO_P4_JOINT_MAP_VERSION AINEKIO_V2_JOINT_MAP_VERSION
#define AINEKIO_P4_MODEL_NAME "v2-12servo"
#endif

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
/* Authoritative single-joint pulse-to-model-centidegree conversion. */
static inline double ainekio_p4_joint_pulse_to_cd(
    const ainekio_p4_joint_config_t *joint, double pulse_us)
{
    const double direction = joint->invert ? -1. : 1.;
    return joint->home_cd + 100. * direction * (pulse_us - joint->home_us) / joint->us_per_degree;
}
/* Owner-measured carrier/crank collision endpoints; shoulders are unchanged. */
bool ainekio_p4_joint_fit_frame(const ainekio_p4_joint_config_t *joints,ainekio_v2_frame_t *frame);
bool ainekio_p4_joint_frame_in_travel(const ainekio_p4_joint_config_t *joints,const ainekio_v2_frame_t *frame);
/* Geometry-preserving coordinated target ramp shared by P4 and host dynamics.
 * False retains the caller's existing mapping-failure path. */
bool ainekio_p4_joint_ramp_frame(const ainekio_v2_frame_t *from,
    const float *goal,double speed_cd_s,double dt,ainekio_v2_frame_t *out);
