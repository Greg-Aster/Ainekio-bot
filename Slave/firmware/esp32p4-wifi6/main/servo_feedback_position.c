#include "servo_feedback.h"
#include <math.h>
#include <string.h>

void ainekio_p4_feedback_health(const ainekio_p4_feedback_snapshot_t *s,
    ainekio_p4_feedback_health_t *health)
{
    *health=(ainekio_p4_feedback_health_t){0};
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        const ainekio_feedback_joint_t *joint=&s->config.joint[j];
        const unsigned c=joint->channel,bit=1U<<j;
        if(!ainekio_feedback_calibrated(joint))continue;
        health->calibrated|=bit;
        if(!s->config.enabled || !s->initialized || !(s->valid_mask&(1U<<c))) {
            health->unavailable|=bit;continue;
        }
        if(s->raw[c]==0 || s->raw[c]==4095)health->clipped|=bit;
        const double low=fmin(joint->point[0].raw,joint->point[2].raw);
        const double high=fmax(joint->point[0].raw,joint->point[2].raw);
        if(s->raw[c]<low || s->filtered_raw[c]<low)health->below_calibration|=bit;
        if(s->raw[c]>high || s->filtered_raw[c]>high)health->above_calibration|=bit;
    }
}

/* Extrapolation remains visible in diagnostics. Motion commands can use their
 * full range, but extrapolated/clipped signals do not establish shaft arrival
 * or a jam. Authored execution continues without this feedback. */
static bool joint_pulse(const ainekio_p4_feedback_snapshot_t *s,unsigned j,double *pulse)
{
    const unsigned c=s->config.joint[j].channel;
    double raw_pulse;bool raw_in_range,filtered_in_range;
    return s->config.enabled && s->initialized && (s->valid_mask&(1U<<c)) &&
        s->raw[c]!=0 && s->raw[c]!=4095 &&
        ainekio_feedback_position(&s->config.joint[j],s->raw[c],&raw_pulse,&raw_in_range) &&
        ainekio_feedback_position(&s->config.joint[j],s->filtered_raw[c],pulse,&filtered_in_range) &&
        raw_in_range && filtered_in_range;
}

/* An endpoint command can arrive on either side of the measured endpoint.
 * Apply the already configured arrival tolerance there too: raw 254 versus
 * a calibrated raw 258 at 500 us is noise around arrival, not missing data.
 * This does not make extrapolated positions usable for balance or jam checks. */
static bool arrival_pulse(const ainekio_p4_feedback_snapshot_t *s,unsigned j,
    unsigned target,double *pulse)
{
    if(joint_pulse(s,j,pulse))return true;
    const ainekio_feedback_joint_t *joint=&s->config.joint[j];
    const unsigned c=joint->channel;
    double raw_pulse;bool in_range;
    return s->config.enabled && s->initialized && (s->valid_mask&(1U<<c)) &&
        s->raw[c]!=0 && s->raw[c]!=4095 &&
        ainekio_feedback_position(joint,s->raw[c],&raw_pulse,&in_range) &&
        ainekio_feedback_position(joint,s->filtered_raw[c],pulse,&in_range) &&
        fabs(raw_pulse-target)<=s->config.arrival_tolerance_us &&
        fabs(*pulse-target)<=s->config.arrival_tolerance_us;
}

/* A single conversion owner serves posture verification and live balance. */
static bool joint_position(const ainekio_p4_feedback_snapshot_t *s,
    const ainekio_p4_joint_config_t *mapping,unsigned j,double *pulse,
    ainekio_v2_frame_t *frame)
{
    const unsigned c=s->config.joint[j].channel;
    double neighbor;bool in_range;
    if(!s->config.enabled || !s->initialized || !(s->valid_mask&(1U<<c)) ||
       mapping[j].us_per_degree<=0.f ||
       !ainekio_feedback_position(&s->config.joint[j],s->filtered_raw[c],pulse,&in_range) ||
       !ainekio_feedback_position(&s->config.joint[j],s->filtered_raw[c]+1.,&neighbor,&in_range))return false;
    const double direction=mapping[j].invert?-1.:1.;
    frame->position[j]=(float)ainekio_p4_joint_pulse_to_cd(&mapping[j],*pulse);
    frame->velocity[j]=100.*direction*(neighbor-*pulse)*s->velocity_raw_s[c]/mapping[j].us_per_degree;
    return true;
}

static bool jam_measurement(const ainekio_p4_feedback_snapshot_t *s,
    const ainekio_p4_joint_config_t *mapping,unsigned j,
    double *measured_us,double *velocity_us_s)
{
    const ainekio_feedback_joint_t *joint=&s->config.joint[j];
    const unsigned c=joint->channel;
    ainekio_v2_frame_t frame={0};
    if(!s->config.enabled || !s->initialized || !(s->valid_mask&(1U<<c)) ||
       s->raw[c]==0 || s->raw[c]==4095 || !ainekio_feedback_calibrated(joint) ||
       !joint_position(s,mapping,j,measured_us,&frame))return false;
    const double direction=mapping[j].invert?-1.:1.;
    *velocity_us_s=direction*((double)frame.velocity[j]/100.)*mapping[j].us_per_degree;
    return isfinite(*measured_us) && isfinite(*velocity_us_s);
}
bool ainekio_p4_feedback_frame(const ainekio_p4_joint_config_t *mapping,
    ainekio_v2_frame_t *frame)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    ainekio_v2_frame_t result=*frame;
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        double pulse;
        if(mapping[j].channel>=0 && (!joint_pulse(&s,j,&pulse) ||
            !joint_position(&s,mapping,j,&pulse,&result)))return false;
    }
    *frame=result;return true;
}
void ainekio_p4_feedback_walk_frame(const ainekio_p4_joint_config_t *mapping,
    ainekio_v2_frame_t *frame)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        if(mapping[j].channel<0)continue;
        const unsigned c=s.config.joint[j].channel;
        if(s.raw[c]==0 || s.raw[c]==4095)continue;
        double pulse;
        (void)joint_position(&s,mapping,j,&pulse,frame);
    }
}
void ainekio_p4_feedback_observe(const ainekio_p4_feedback_snapshot_t *s,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets,
    ainekio_p4_feedback_observation_t *out)
{
    *out=(ainekio_p4_feedback_observation_t){.enabled=s->config.enabled,
        .scan=s->scan,.scan_us=s->scan_us,.revision=s->revision};
    ainekio_p4_feedback_health(s,&out->health);
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        const unsigned channel=s->config.joint[j].channel;
        out->sampled_us[j]=s->sampled_us[channel];
        out->raw_adc[j]=s->raw[channel];
        out->signal_millivolts[j]=s->millivolts[channel];
        if(mapping[j].channel<0)continue;
        double pulse;
        if(joint_position(s,mapping,j,&pulse,&out->measured)) {
            out->measured_mask|=1U<<j;
            if(joint_pulse(s,j,&pulse))out->usable_mask|=1U<<j;
        }
        const unsigned target=targets[mapping[j].channel];
        if(target) {
            out->commanded.position[j]=(float)ainekio_p4_joint_pulse_to_cd(&mapping[j],(double)target);
            out->commanded_mask|=1U<<j;
        }
    }
}
/* Check targets after their successful output write. Zero targets omit joints,
 * allowing a moving leg's lift/place check without requiring support arrival.
 * Remaining describes goal error; observations never replace the trajectory. */
bool ainekio_p4_feedback_check(const ainekio_p4_joint_config_t *mapping,
    const uint16_t *targets,int64_t commanded_us,uint16_t *remaining)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    bool observed=true;*remaining=0;
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        const int output=mapping[j].channel;
        if(output<0 || !targets[output])continue;
        const unsigned c=s.config.joint[j].channel;
        double pulse;
        if(s.sampled_us[c]<=commanded_us || !arrival_pulse(&s,j,targets[output],&pulse)) {
            observed=false;*remaining|=1U<<j;
        } else if(fabs(pulse-targets[output])>s.config.arrival_tolerance_us)*remaining|=1U<<j;
    }
    return observed;
}

#define JAM_DEADBAND_MIN_US 80.0
#define JAM_NEAR_ZERO_VEL_US_S 80.0
#define JAM_TARGET_SHIFT_MIN_US 25.0

uint16_t ainekio_p4_feedback_stalled(ainekio_p4_feedback_progress_t *p,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    if(!s.config.enabled || !s.config.jam_enabled || !s.config.no_progress_ms) {
        memset(p,0,sizeof *p);return 0;
    }
    const double deadband_us=fmax((double)s.config.tolerance_us,JAM_DEADBAND_MIN_US);
    const double shift_us=fmax((double)s.config.progress_us,JAM_TARGET_SHIFT_MIN_US);
    uint16_t stalled=0;
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        const int output=mapping[j].channel;
        const unsigned c=s.config.joint[j].channel;
        double measured=0.,velocity_us_s=0.;
        if(output<0 || !targets[output] || !jam_measurement(&s,mapping,j,&measured,&velocity_us_s)) {
            memset(&p->joint[j],0,sizeof p->joint[j]);
            continue;
        }
        const uint16_t target=targets[output];
        const int64_t at=s.sampled_us[c];
        if(at<=p->joint[j].sampled_us)continue;
        p->joint[j].sampled_us=at;
        const double error=(double)target-measured;
        const int direction=fabs(error)<=deadband_us ? 0 : error>0. ? 1 : -1;
        const double vel_toward_us_s=direction*velocity_us_s;
        if(!direction || direction!=p->joint[j].direction || !p->joint[j].progress_at) {
            p->joint[j].direction=direction;
            p->joint[j].best=measured;
            p->joint[j].progress_at=at;
            p->joint[j].last_target_us=target;
            p->joint[j].reported=false;
            continue;
        }
        if(vel_toward_us_s>=JAM_NEAR_ZERO_VEL_US_S ||
           direction*(measured-p->joint[j].best)>=s.config.progress_us) {
            /* Active slewing toward the goal or a new high-water mark starts a
             * fresh window; stationary wiper noise cannot claim progress. */
            p->joint[j].best=measured;
            p->joint[j].progress_at=at;
            p->joint[j].last_target_us=target;
            p->joint[j].reported=false;
            continue;
        }
        if(fabs((double)target-(double)p->joint[j].last_target_us)>=shift_us) {
            /* Streaming targets (walk_target / MicroDuck / NeuralPose) reverse
             * without crossing measured_us under load. Unlock stale peaks. */
            p->joint[j].last_target_us=target;
            if(direction*(measured-p->joint[j].best)<0.)
                p->joint[j].best=measured;
        }
        if(!p->joint[j].reported &&
           at-p->joint[j].progress_at>=(int64_t)s.config.no_progress_ms*1000) {
            stalled|=1U<<j;
            p->joint[j].reported=true;
        }
    }
    return stalled;
}

uint16_t ainekio_p4_feedback_thermal_step(ainekio_p4_feedback_thermal_t *thermal,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets,
    bool armed,uint64_t now_us)
{
    if(!thermal)return 0;
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    float dt_s=0.02f;
    if(thermal->updated_us) {
        if(now_us<=thermal->updated_us)return 0;
        dt_s=(float)(now_us-thermal->updated_us)*1e-6f;
    }
    thermal->updated_us=now_us;
    const bool jam_active=armed && s.config.enabled && s.config.jam_enabled;
    uint16_t tripped=0;
    for(unsigned j=0;j<AINEKIO_FEEDBACK_ACTIVE_JOINTS;j++) {
        const int output=mapping ? mapping[j].channel : -1;
        const uint16_t target_us=(armed && targets && output>=0) ? targets[output] : 0;
        double measured_us=0.,velocity_us_s=0.;
        bool valid=false;
        float err_deg=0.0f,vel_toward_deg_s=0.0f;
        if(target_us!=0 && mapping[j].us_per_degree>0.0f &&
           jam_measurement(&s,mapping,j,&measured_us,&velocity_us_s)) {
            valid=true;
            const double error_us=(double)target_us-measured_us;
            const double sign=error_us>=0.0 ? 1.0 : -1.0;
            err_deg=(float)(fabs(error_us)/(double)mapping[j].us_per_degree);
            vel_toward_deg_s=(float)((sign*velocity_us_s)/(double)mapping[j].us_per_degree);
        }
        thermal->thermal_load[j]=ainekio_feedback_thermal_update(
            thermal->thermal_load[j],target_us!=0,valid,err_deg,vel_toward_deg_s,dt_s);
        if(jam_active && target_us!=0 && valid && thermal->thermal_load[j]>=1.0f)
            tripped|=(uint16_t)(1U<<j);
    }
    return tripped;
}
