#include "servo_feedback.h"
#include <math.h>
#include <string.h>

void ainekio_p4_feedback_health(const ainekio_p4_feedback_snapshot_t *s,
    ainekio_p4_feedback_health_t *health)
{
    *health=(ainekio_p4_feedback_health_t){0};
    for(unsigned j=0;j<12;j++) {
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
    return (target==joint->point[0].pulse_us || target==joint->point[2].pulse_us) &&
        s->config.enabled && s->initialized && (s->valid_mask&(1U<<c)) &&
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
    if(!joint_pulse(s,j,pulse) ||
       !ainekio_feedback_position(&s->config.joint[j],s->filtered_raw[c]+1.,&neighbor,&in_range))return false;
    const double direction=mapping[j].invert?-1.:1.;
    frame->position[j]=mapping[j].home_cd+100.*direction*(*pulse-mapping[j].home_us)/mapping[j].us_per_degree;
    frame->velocity[j]=100.*direction*(neighbor-*pulse)*s->velocity_raw_s[c]/mapping[j].us_per_degree;
    return true;
}
bool ainekio_p4_feedback_frame(const ainekio_p4_joint_config_t *mapping,
    ainekio_v2_frame_t *frame)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    ainekio_v2_frame_t result=*frame;
    for(unsigned j=0;j<12;j++) {
        double pulse;
        if(mapping[j].channel>=0 && !joint_position(&s,mapping,j,&pulse,&result))return false;
    }
    *frame=result;return true;
}
/* Check targets after their successful output write. Zero targets omit joints,
 * allowing a moving leg's lift/place check without requiring support arrival.
 * Remaining describes goal error; observations never replace the trajectory. */
bool ainekio_p4_feedback_check(const ainekio_p4_joint_config_t *mapping,
    const uint16_t *targets,int64_t commanded_us,uint16_t *remaining)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    bool observed=true;*remaining=0;
    for(unsigned j=0;j<12;j++) {
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

uint16_t ainekio_p4_feedback_stalled(ainekio_p4_feedback_progress_t *p,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    if(!s.config.enabled || !s.config.jam_enabled || !s.config.no_progress_ms) {
        memset(p,0,sizeof *p);return 0;
    }
    uint16_t stalled=0;
    for(unsigned j=0;j<12;j++) {
        const int output=mapping[j].channel;
        const unsigned c=s.config.joint[j].channel;
        double measured;
        if(output<0 || !targets[output] || !joint_pulse(&s,j,&measured)) {
            memset(&p->joint[j],0,sizeof p->joint[j]);
            continue;
        }
        const int64_t at=s.sampled_us[c];
        if(at<=p->joint[j].sampled_us)continue;
        p->joint[j].sampled_us=at;
        const double error=targets[output]-measured;
        const int direction=fabs(error)<=s.config.tolerance_us ? 0 : error>0 ? 1 : -1;
        if(!direction || direction!=p->joint[j].direction || !p->joint[j].progress_at) {
            p->joint[j].direction=direction;p->joint[j].best=measured;p->joint[j].progress_at=at;
            p->joint[j].reported=false;
        } else if(direction*(measured-p->joint[j].best)>=s.config.progress_us) {
            /* A high-water mark: oscillating noise cannot repeatedly claim
             * progress by moving back and forth over the same position. */
            p->joint[j].best=measured;p->joint[j].progress_at=at;
            p->joint[j].reported=false;
        } else if(!p->joint[j].reported && at-p->joint[j].progress_at>=(int64_t)s.config.no_progress_ms*1000) {
            stalled|=1U<<j;
            p->joint[j].reported=true;
        }
    }
    return stalled;
}
