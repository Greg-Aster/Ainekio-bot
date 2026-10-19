#include "servo_feedback_model.h"
#include <math.h>
#include <string.h>

static double filter_alpha(double cutoff,double dt)
{
    return 1./(1.+1./(6.2831853071795864769*cutoff*dt));
}
void ainekio_feedback_filter_update(ainekio_feedback_filter_t *f,double raw,int64_t now)
{
    if(!f->initialized) {
        *f=(ainekio_feedback_filter_t){.raw=raw,.position=raw,.sampled_us=now,.initialized=true};
        return;
    }
    if(now<=f->sampled_us)return; /* A duplicate observation is not new motion. */
    const double dt=(now-f->sampled_us)/1e6;
    const double derivative_alpha=filter_alpha(5.,dt);
    f->derivative+=derivative_alpha*((raw-f->raw)/dt-f->derivative);
    /* One-Euro style adaptive cutoff, in ADC counts: quiet at rest, faster
     * through real motion. These are measurement bandwidths, not motor rates. */
    const double alpha=filter_alpha(1.5+.002*fabs(f->derivative),dt);
    const double position=f->position+alpha*(raw-f->position);
    f->velocity+=derivative_alpha*((position-f->position)/dt-f->velocity);
    f->position=position;f->raw=raw;f->sampled_us=now;
}

void ainekio_feedback_defaults(ainekio_feedback_config_t *c)
{
    memset(c,0,sizeof(*c));
    c->version=AINEKIO_FEEDBACK_VERSION;c->tolerance_us=30;
    for(unsigned j=0;j<AINEKIO_FEEDBACK_JOINTS;j++)c->joint[j].channel=j;
}
bool ainekio_feedback_calibrated(const ainekio_feedback_joint_t *j)
{
    if(!j||j->points!=7)return false;
    bool ascending=j->point[2].raw>j->point[0].raw;
    for(unsigned p=0;p<3;p++) {
        if(j->point[p].raw>4095||!j->point[p].pulse_us)return false;
        if(p && (j->point[p].pulse_us<=j->point[p-1].pulse_us ||
            (ascending ? j->point[p].raw<=j->point[p-1].raw :
                j->point[p].raw>=j->point[p-1].raw)))return false;
    }
    return true;
}
bool ainekio_feedback_config_valid(const ainekio_feedback_config_t *c)
{
    if(!c||c->version!=AINEKIO_FEEDBACK_VERSION||c->enabled>1||
       c->stand_enabled>1||!c->tolerance_us|| (c->stand_enabled&&!c->enabled))return false;
    unsigned channels=0;
    for(unsigned j=0;j<AINEKIO_FEEDBACK_JOINTS;j++) {
        const ainekio_feedback_joint_t *v=&c->joint[j];
        if(v->channel>=16||v->points>7||(channels&(1U<<v->channel)))return false;
        channels|=1U<<v->channel;
        for(unsigned p=0;p<3;p++)if((v->points&(1U<<p)) &&
            (v->point[p].raw>4095||!v->point[p].pulse_us))return false;
        if(v->points==7&&!ainekio_feedback_calibrated(v))return false;
        if(c->stand_enabled&&!ainekio_feedback_calibrated(v))return false;
    }
    return true;
}
bool ainekio_feedback_position(const ainekio_feedback_joint_t *j,double raw,
    double *pulse,bool *in_range)
{
    if(!pulse||!in_range||!isfinite(raw)||!ainekio_feedback_calibrated(j))return false;
    const bool ascending=j->point[2].raw>j->point[0].raw;
    unsigned hi=(ascending ? raw<=j->point[1].raw : raw>=j->point[1].raw)?1:2;
    const ainekio_feedback_point_t a=j->point[hi-1],b=j->point[hi];
    *pulse=a.pulse_us+(raw-a.raw)*(b.pulse_us-a.pulse_us)/((double)b.raw-a.raw);
    *in_range=raw>=fmin(j->point[0].raw,j->point[2].raw)&&
        raw<=fmax(j->point[0].raw,j->point[2].raw);
    return isfinite(*pulse);
}
