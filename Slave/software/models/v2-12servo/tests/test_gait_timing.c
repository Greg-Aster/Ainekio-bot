#include "ainekio/v2_walk.h"
#include "walk_data.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static double peak;
static unsigned frames;
static void tick(ainekio_v2_walk_state_t *s,uint64_t now)
{
    ainekio_v2_walk_pose_t before=s->pose;
    const double preparation=s->preparation_seconds;
    double touchdown[4];for(unsigned leg=0;leg<4;leg++)touchdown[leg]=s->feet[leg].touchdown_phase;
    double seconds=(now-s->last_us)/1e6;
    assert(ainekio_v2_walk_tick(s,now));
    assert(s->phase>=before.phase && s->clock_scale==1. && !s->speed_flagged);
    for(unsigned leg=0;leg<4;leg++) {
        for(unsigned joint=0;joint<3;joint++) {
            double speed=fabs(s->pose.joints[leg][joint]-before.joints[leg][joint])*57.29577951308232/seconds;
            assert(isfinite(speed));
            peak=fmax(peak,speed);
        }
        /* A long interval can include a full swing between two grounded
         * samples. Anchor continuity applies to the same planted interval. */
        if(before.grounded[leg]&&s->pose.grounded[leg]&&touchdown[leg]==s->feet[leg].touchdown_phase&&
           (seconds<=.04||preparation==s->preparation_seconds))
            for(unsigned axis=0;axis<2;axis++)assert(fabs(before.feet[leg][axis]-s->pose.feet[leg][axis])<1e-8);
    }
    frames++;
}
int main(void)
{
    /* Cadence uses elapsed wall time through entry, steering and Finish.
     * Irregular intervals must not accumulate or replay unused gait time. */
    const unsigned intervals[]={10000,20000,40000,13000,31000};
    for(unsigned gait=0;gait<4;gait++)for(unsigned dir=0;dir<(gait==AINEKIO_GAIT_CRAB?6:4);dir++)
    for(unsigned clock=0;clock<4;clock++) {
        ainekio_v2_walk_state_t s={0};uint64_t now=0;unsigned n=0;bool stop=false;
        ainekio_v2_walk_controls_t controls={100.,3.};
        assert(ainekio_v2_gait_begin(&s,(ainekio_walk_direction_t)dir,(ainekio_gait_t)gait,0,controls,0));
        while(!s.complete) {
            assert(now<180000000);
            now+=intervals[clock==3?n++%5:clock];tick(&s,now);
            if(!stop&&s.phase>=7.){controls.stride_percent=0.;assert(ainekio_v2_walk_update(&s,controls));stop=true;}
        }
        assert(stop);for(unsigned leg=0;leg<4;leg++)assert(s.pose.grounded[leg]);
        /* A scheduling gap does not fault the planner or alter the command. */
        controls.stride_percent=100.;
        assert(ainekio_v2_gait_begin(&s,(ainekio_walk_direction_t)dir,(ainekio_gait_t)gait,0,controls,now));
        tick(&s,now+40001);
        assert(!s.failed && s.last_us==now+40001);
        tick(&s,now+140001);
        tick(&s,now+1140001);
        assert(!s.failed && s.last_us==now+1140001);
    }
    /* The posture/gesture joint setting must not change gait phase, contacts
     * or servo commands. Compare identical requests at two very different
     * settings on every output frame, including irregular scheduling. */
    const float limits[]={100.F,20000.F};
    ainekio_v2_walk_state_t paired[2]={0};
    for(unsigned k=0;k<2;k++)
        assert(ainekio_v2_gait_begin(&paired[k],AINEKIO_WALK_FORWARD,AINEKIO_GAIT_RUN,0,(ainekio_v2_walk_controls_t){100.,3.},0));
    uint64_t now=0;
    for(unsigned n=0;now<10000000;n++) {
        now+=intervals[n%5];
        for(unsigned k=0;k<2;k++) {
            assert(ainekio_v2_joint_speed_set(limits[k]));tick(&paired[k],now);
        }
        assert(paired[0].phase==paired[1].phase);
        for(unsigned j=0;j<12;j++)assert(paired[0].pose.frame.position[j]==paired[1].pose.frame.position[j]);
        for(unsigned leg=0;leg<4;leg++)assert(paired[0].pose.grounded[leg]==paired[1].pose.grounded[leg]);
        if(paired[0].phase>V2_RUN_TRANSITION+2.)
            assert(fabs(paired[0].cycles_s-3./V2_RUN_PERIOD)<1e-8);
    }
    assert(ainekio_v2_joint_speed_set(ainekio_v2_joint_speed_default()));
    /* A steady Walk's return must stay near its planted-stroke endpoints.
     * The former whole-swing quintic let continued body travel carry the foot
     * several millimetres beyond each endpoint, wasting joint travel. This is
     * an offline trajectory regression, not a runtime reach restriction. */
    ainekio_v2_walk_state_t walking={0};
    assert(ainekio_v2_walk_begin(&walking,0,(ainekio_v2_walk_controls_t){100.,2.},0));
    double overshoot=0.;
    for(uint64_t at=10000;at<=12000000;at+=10000) {
        tick(&walking,at);
        if(at<8000000)continue;
        for(unsigned leg=0;leg<4;leg++) {
            double x=walking.pose.feet[leg][0]-walking.body_x-v2_walk_stance[leg][0];
            overshoot=fmax(overshoot,fabs(x+V2_WALK_BIAS)-V2_WALK_SWEEP*.5);
        }
    }
    assert(overshoot<V2_WALK_SWEEP*.01);
    /* A slow request retains its original common clock. */
    ainekio_v2_walk_state_t s={0};
    assert(ainekio_v2_walk_begin(&s,0,(ainekio_v2_walk_controls_t){5.,.25},0));
    for(uint64_t now=20000;now<=10000000;now+=20000){tick(&s,now);assert(s.clock_scale==1.);}
    printf("Gait timing: %u frames, peak %.6f deg/s; Body Control cadence, setting-independent commands, anchors, Finish and delayed resumption verified.\n",frames,peak);
}
