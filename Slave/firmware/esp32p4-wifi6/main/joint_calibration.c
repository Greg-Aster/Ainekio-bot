#include "joint_calibration.h"
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
#include "ainekio/v1_model.h"
#elif defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
#include "ainekio/v3_model.h"
#endif
#include "ainekio/v2_limits.h"
#include "ainekio/v2_walk.h"

#include <math.h>
#include <string.h>

#if defined(CONFIG_AINEKIO_MODEL_V1_8SERVO) || defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
bool ainekio_p4_joint_ramp_frame(const ainekio_v2_frame_t *from,
    const float *goal,double speed_cd_s,double dt,ainekio_v2_frame_t *out)
{
    if(!from||!goal||!out||!isfinite(speed_cd_s)||speed_cd_s<=0.||!isfinite(dt)||dt<0.)return false;
    double remaining=0.;
    for(unsigned j=0;j<AINEKIO_P4_ACTIVE_JOINTS;j++)
        remaining=fmax(remaining,fabs((double)goal[j]-(double)from->position[j]));
    const double travel=speed_cd_s*dt;
    const double u=remaining>0. ? fmin(1.,travel/remaining) : 1.;
    *out=*from;
    for(unsigned j=0;j<AINEKIO_P4_ACTIVE_JOINTS;j++) {
        const double next=(double)from->position[j]+u*((double)goal[j]-(double)from->position[j]);
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
        const float clamped_deg=ainekio_v1_clamp_joint_deg((uint8_t)j,(float)(next/100.0));
#else
        const float clamped_deg=ainekio_v3_clamp_joint_deg((uint8_t)j,(float)(next/100.0));
#endif
        out->position[j]=clamped_deg*100.0f;
        out->velocity[j]=u<1. && dt>0. ? (float)((out->position[j]-from->position[j])/dt) : 0.0f;
    }
    for(unsigned j=AINEKIO_P4_ACTIVE_JOINTS;j<AINEKIO_BODY_JOINT_COUNT;j++) {
        out->position[j]=0.0f;
        out->velocity[j]=0.0f;
    }
    return true;
}
#else
bool ainekio_p4_joint_ramp_frame(const ainekio_v2_frame_t *from,
    const float *goal,double speed_cd_s,double dt,ainekio_v2_frame_t *out)
{
    if(!from||!goal||!out||!isfinite(speed_cd_s)||speed_cd_s<=0.||!isfinite(dt)||dt<0.)return false;
    ainekio_v2_frame_t target=*from;
    memcpy(target.position,goal,sizeof target.position);
    double remaining=0.;
    for(unsigned j=0;j<12;j++)remaining=fmax(remaining,fabs(goal[j]-from->position[j]));
    const double travel=speed_cd_s*dt;
    double u=remaining ? fmin(1.,travel/remaining) : 1.;
    ainekio_v2_frame_t candidate;
    if(!ainekio_v2_transition(from,&target,u,&candidate))return false;
    if(u>0. && u<1.) {
        /* A straight carrier/crank interpolation can leave the four-bar's
         * closure region even when both endpoints are feasible. Follow the
         * existing geometry path and use the requested angular travel budget.
         * The carrier is nonlinear along that path, so endpoint distance alone
         * is not its per-frame travel. Bisection resolves float output precision. */
        double low=0.,high=1.;*out=*from;
        for(unsigned iteration=0;iteration<32;iteration++) {
            double distance=0.;
            for(unsigned j=0;j<12;j++)distance=fmax(distance,fabs(candidate.position[j]-from->position[j]));
            if(distance<=travel){low=u;*out=candidate;}else high=u;
            if(distance==travel)break;
            const double next=(low+high)*.5;
            if((float)next==(float)u)break;
            u=next;
            if(!ainekio_v2_transition(from,&target,u,&candidate))return false;
        }
        u=low;
    } else *out=candidate;
    for(unsigned j=0;j<12;j++) {
        out->velocity[j]=u<1. && dt>0. ? (float)((out->position[j]-from->position[j])/dt) : 0;
    }
    return true;
}
#endif

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
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        candidate[i] = (ainekio_p4_joint_config_t){
            .channel = i < AINEKIO_V1_JOINT_COUNT ? (int8_t)i : (int8_t)-1,
            .home_us = AINEKIO_V1_PULSE_NEUTRAL_US,
            .home_cd = 0,
            .us_per_degree = AINEKIO_V1_US_PER_DEGREE,
        };
    }
#elif defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        candidate[i] = (ainekio_p4_joint_config_t){
            .channel = (int8_t)i,
            .home_us = AINEKIO_V3_PULSE_CENTER_US,
            .home_cd = 0,
            .us_per_degree = AINEKIO_V3_US_PER_DEGREE,
        };
    }
#else
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        candidate[i] = (ainekio_p4_joint_config_t){.channel = (int8_t)i,
            .home_us = ainekio_v2_pulse_reference(i),
            .home_cd = (int32_t)lround(100.*ainekio_v2_center_degrees(i)), .us_per_degree = (float)ainekio_v2_us_per_degree()};
    }
#endif
    memcpy(joints, candidate, sizeof(candidate));
    return true;
}

/* Display-only mounting reference at the model assembly marks. Mirrored
 * servos use the reflected pulse around the reported servo-profile window. This
 * does not change the operator-owned calibration or write NVS. */
uint16_t ainekio_p4_joint_recommended_home(unsigned joint_id, bool inverted)
{
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
    (void)joint_id; (void)inverted;
    return AINEKIO_V1_PULSE_NEUTRAL_US;
#elif defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
    (void)joint_id; (void)inverted;
    return AINEKIO_V3_PULSE_CENTER_US;
#else
    const uint16_t reference = ainekio_v2_pulse_reference(joint_id);
    return inverted ? (uint16_t)lround(2.*ainekio_v2_pulse_midpoint()-reference) : reference;
#endif
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
 * shaft feedback. Unpowered channels seed from the CAD assembly reference. */
bool ainekio_p4_joint_unmap_frame(const ainekio_p4_joint_config_t *joints,
                                const uint16_t *pulses,ainekio_v2_frame_t *frame)
{
    if(!frame||!pulses||!ainekio_p4_joints_valid(joints))return false;
#if defined(CONFIG_AINEKIO_MODEL_V1_8SERVO) || defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
    ainekio_v2_frame_t candidate={.geometry_id=ainekio_v1_geometry_id};
#else
    ainekio_v2_frame_t candidate={.geometry_id=AINEKIO_V3_GEOMETRY_ID};
#endif
    for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++) {
        const ainekio_p4_joint_config_t *joint=&joints[i];
        candidate.position[i]=0.0f;
        if(joint->channel<0) {
            candidate.position[i]=(float)joint->home_cd;
            continue;
        }
        unsigned pulse=pulses[joint->channel];
        if(!pulse)continue;
        candidate.position[i]=(float)ainekio_p4_joint_pulse_to_cd(joint,(double)pulse);
    }
#else
    ainekio_v2_frame_t candidate={.geometry_id=ainekio_v2_walk_geometry_id};
    for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++) {
        const ainekio_p4_joint_config_t *joint=&joints[i];
        candidate.position[i]=(float)(100.*ainekio_v2_center_degrees(i));
        if(joint->channel<0) {
            candidate.position[i]=joint->home_cd;
            continue;
        }
        unsigned pulse=pulses[joint->channel];
        if(!pulse)continue;
        candidate.position[i]=(float)ainekio_p4_joint_pulse_to_cd(joint,(double)pulse);
    }
#endif
    *frame=candidate;return true;
}
bool ainekio_p4_joint_fit_frame(const ainekio_p4_joint_config_t *joints,ainekio_v2_frame_t *frame)
{
#if defined(CONFIG_AINEKIO_MODEL_V1_8SERVO) || defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
    if(!joints||!frame)return false;
    for(unsigned j=0;j<AINEKIO_P4_ACTIVE_JOINTS;j++) {
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
        float deg=ainekio_v1_clamp_joint_deg((uint8_t)j,frame->position[j]/100.0f);
        const double pmin=AINEKIO_V1_PULSE_MIN_US, pmax=AINEKIO_V1_PULSE_MAX_US;
#else
        float deg=ainekio_v3_clamp_joint_deg((uint8_t)j,frame->position[j]/100.0f);
        const double pmin=AINEKIO_V3_PULSE_MIN_US, pmax=AINEKIO_V3_PULSE_MAX_US;
#endif
        if(joints[j].channel>=0) {
            const double a=ainekio_p4_joint_pulse_to_cd(&joints[j],pmin)/100.0;
            const double b=ainekio_p4_joint_pulse_to_cd(&joints[j],pmax)/100.0;
            const float lo=(float)fmin(a,b), hi=(float)fmax(a,b);
            if(deg<lo)deg=lo;
            if(deg>hi)deg=hi;
        }
        frame->position[j]=deg*100.0f;
    }
    return true;
#else
    float low[12],high[12];
    for(unsigned j=0;j<12;j++) {
        low[j]=-INFINITY;high[j]=INFINITY;
        if(j%3==0||joints[j].channel<0)continue;
        const ainekio_p4_joint_config_t *m=&joints[j];
        double a=ainekio_p4_joint_pulse_to_cd(m,300.);
        double b=ainekio_p4_joint_pulse_to_cd(m,2950.);
        low[j]=(float)fmin(a,b);high[j]=(float)fmax(a,b);
    }
    return ainekio_v2_feet_bounded(frame,low,high);
#endif
}
bool ainekio_p4_joint_frame_in_travel(const ainekio_p4_joint_config_t *joints,const ainekio_v2_frame_t *frame)
{
    uint16_t pulses[12];if(!ainekio_p4_joint_map_frame(joints,frame,pulses))return false;
#if defined(CONFIG_AINEKIO_MODEL_V1_8SERVO) || defined(CONFIG_AINEKIO_MODEL_V3_12SERVO)
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
    const unsigned pmin=AINEKIO_V1_PULSE_MIN_US, pmax=AINEKIO_V1_PULSE_MAX_US;
#else
    const unsigned pmin=AINEKIO_V3_PULSE_MIN_US, pmax=AINEKIO_V3_PULSE_MAX_US;
#endif
    for(unsigned j=0;j<AINEKIO_P4_ACTIVE_JOINTS;j++)if(joints[j].channel>=0) {
        unsigned p=pulses[joints[j].channel];
        if(p<pmin||p>pmax)return false;
    }
#else
    for(unsigned j=0;j<12;j++)if(j%3&&joints[j].channel>=0) {
        unsigned p=pulses[joints[j].channel];if(p<300||p>2950)return false;
    }
#endif
    return true;
}
