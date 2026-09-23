#include "joint_calibration.h"
#include "ainekio/v2_limits.h"
#include "ainekio/v2_walk.h"

#include <math.h>
#include <string.h>

_Static_assert(sizeof(ainekio_p4_joint_config_t) == 12, "calibration layout changed");
_Static_assert(sizeof(ainekio_p4_joint_record_t) == 148, "calibration record layout changed");
_Static_assert(AINEKIO_BODY_JOINT_COUNT == AINEKIO_V2_JOINT_COUNT, "Joint count mismatch");

bool ainekio_p4_joints_valid(const ainekio_p4_joint_config_t *joints)
{
    if (!joints) return false;
    uint16_t channels = 0;
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        const ainekio_p4_joint_config_t *joint = &joints[i];
        if (joint->channel < -1 || joint->channel >= (int)AINEKIO_BODY_JOINT_COUNT ||
            joint->invert > 1 || joint->home_us == 0 ||
            joint->home_cd < -36000 || joint->home_cd > 36000 ||
            !isfinite(joint->us_per_degree) || joint->us_per_degree <= 0 || joint->us_per_degree > 100)
            return false;
        if (joint->channel >= 0) {
            const uint16_t bit = (uint16_t)(1U << joint->channel);
            if (channels & bit) return false;
            channels |= bit;
        }
    }
    return true;
}

bool ainekio_p4_joint_defaults(ainekio_p4_joint_config_t *joints)
{
    if (!joints) return false;
    ainekio_p4_joint_config_t candidate[AINEKIO_BODY_JOINT_COUNT] = {0};
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        candidate[i] = (ainekio_p4_joint_config_t){.channel = (int8_t)i,
            .home_us = ainekio_v2_pulse_reference(),
            .home_cd = (int32_t)lround(100.*ainekio_v2_center_degrees(i)), .us_per_degree = (float)ainekio_v2_us_per_degree()};
    }
    memcpy(joints, candidate, sizeof(candidate));
    return true;
}

bool ainekio_p4_joint_map_frame(const ainekio_p4_joint_config_t *joints,
                              const ainekio_v2_frame_t *frame, uint16_t *pulses)
{
    if (!pulses) return false;
    memset(pulses, 0, sizeof(uint16_t) * AINEKIO_BODY_JOINT_COUNT);
    if (!frame || !ainekio_p4_joints_valid(joints)) return false;
    uint16_t candidate[AINEKIO_BODY_JOINT_COUNT] = {0};
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        const ainekio_p4_joint_config_t *joint = &joints[i];
        if (joint->channel < 0) continue;
        if (!isfinite(frame->position[i])) return false;
        const double degrees = ((double)frame->position[i] - joint->home_cd) / 100.0;
        const double pulse = joint->home_us + (joint->invert ? -degrees : degrees) * joint->us_per_degree;
        /* The output driver owns timer representability. */
        if (!isfinite(pulse) || pulse < 1 || pulse > UINT16_MAX) return false;
        candidate[joint->channel] = (uint16_t)lround(pulse);
    }
    memcpy(pulses, candidate, sizeof(candidate));
    return true;
}

/* Inverse of the operator mapping. A pulse is a commanded reference, not
 * shaft feedback. All enabled channels must already have a known command. */
bool ainekio_p4_joint_unmap_frame(const ainekio_p4_joint_config_t *joints,
                                const uint16_t *pulses,ainekio_v2_frame_t *frame)
{
    if(!frame||!pulses||!ainekio_p4_joints_valid(joints))return false;
    ainekio_v2_frame_t candidate={.geometry_id=ainekio_v2_walk_geometry_id};
    for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++) {
        const ainekio_p4_joint_config_t *joint=&joints[i];
        candidate.position[i]=joint->home_cd;
        if(joint->channel<0)continue;
        unsigned pulse=pulses[joint->channel];
        if(!pulse)return false;
        double delta=((double)pulse-joint->home_us)/joint->us_per_degree;
        candidate.position[i]=(float)(joint->home_cd+100.*(joint->invert?-delta:delta));
    }
    *frame=candidate;return true;
}
