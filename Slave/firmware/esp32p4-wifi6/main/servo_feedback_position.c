#include "servo_feedback.h"
#include <math.h>

/* Interpret one coherent acquisition snapshot using the saved joint mapping. */
bool ainekio_p4_feedback_frame(const ainekio_p4_joint_config_t *mapping,
    ainekio_v2_frame_t *frame)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    if(!s.config.enabled||!s.initialized)return false;
    ainekio_v2_frame_t result=*frame;
    for(unsigned j=0;j<12;j++) {
        if(mapping[j].channel<0)continue;
        unsigned channel=s.config.joint[j].channel;
        double pulse;bool in_range;
        if(!(s.valid_mask&(1U<<channel))||
           !ainekio_feedback_position(&s.config.joint[j],s.raw[channel],&pulse,&in_range))return false;
        double delta=(pulse-mapping[j].home_us)/mapping[j].us_per_degree;
        result.position[j]=mapping[j].home_cd+100.*(mapping[j].invert?-delta:delta);
        result.velocity[j]=0;
    }
    *frame=result;return true;
}
bool ainekio_p4_feedback_arrived(const ainekio_p4_joint_config_t *mapping,
    const uint16_t *targets,int64_t commanded_us,uint16_t *waiting)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    *waiting=0;
    for(unsigned j=0;j<12;j++) {
        int output=mapping[j].channel;
        if(output<0||!targets[output])continue;
        unsigned c=s.config.joint[j].channel;
        double measured=0.;bool in_range=false;
        if(!s.config.enabled||!s.initialized||!(s.valid_mask&(1U<<c))||
           s.sampled_us[c]<=commanded_us||
           !ainekio_feedback_position(&s.config.joint[j],s.raw[c],&measured,&in_range)||
           fabs(measured-targets[output])>s.config.tolerance_us)
            *waiting|=1U<<j;
    }
    return *waiting==0;
}
