#include "ainekio/v2_walk.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static double peak,flagged_peak;
static unsigned limited,frames,margin_frames;
static void tick(ainekio_v2_walk_state_t *s,uint64_t now)
{
    ainekio_v2_walk_pose_t before=s->pose;
    double seconds=(now-s->last_us)/1e6;
    assert(ainekio_v2_walk_tick(s,now));
    assert(s->phase>=before.phase && s->clock_scale>0. && s->clock_scale<=1.);
    for(unsigned leg=0;leg<4;leg++) {
        for(unsigned joint=0;joint<3;joint++) {
            double speed=fabs(s->pose.joints[leg][joint]-before.joints[leg][joint])*57.29577951308232/seconds;
            double bound=s->speed_flagged?ainekio_v2_gait_joint_speed_limit():ainekio_v2_gait_joint_speed_flag_threshold();
            assert(isfinite(speed) && speed<=bound+.001);
            if(s->speed_flagged)flagged_peak=fmax(flagged_peak,speed);
            else if(speed>ainekio_v2_gait_joint_speed_limit()){
                assert(s->clock_scale==1.);margin_frames++;
            }
            peak=fmax(peak,speed);
        }
        if(before.grounded[leg]&&s->pose.grounded[leg])
            for(unsigned axis=0;axis<2;axis++)assert(fabs(before.feet[leg][axis]-s->pose.feet[leg][axis])<1e-8);
    }
    limited+=s->clock_scale<.999;frames++;
}
int main(void)
{
    /* Independent controls cannot bypass timing, including entry and Finish.
     * Irregular wall intervals must not accumulate or replay unused gait time. */
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
        /* Deadline rejection leaves the last valid geometry intact. */
        assert(ainekio_v2_gait_begin(&s,(ainekio_walk_direction_t)dir,(ainekio_gait_t)gait,0,controls,now));
        ainekio_v2_frame_t before=s.pose.frame;
        assert(!ainekio_v2_walk_tick(&s,now+40001));
        for(unsigned j=0;j<12;j++)assert(before.position[j]==s.pose.frame.position[j]);
    }
    /* A slow request retains its original common clock. */
    ainekio_v2_walk_state_t s={0};
    assert(ainekio_v2_walk_begin(&s,0,(ainekio_v2_walk_controls_t){5.,.25},0));
    for(uint64_t now=20000;now<=10000000;now+=20000){tick(&s,now);assert(s.clock_scale==1.);}
    assert(limited>100 && margin_frames>0);
    printf("Gait timing: %u frames, %u limited, unmodified margin samples %u; peak %.6f deg/s < %.3f flag threshold; flagged peak %.6f <= %.3f rated. Common clock, anchors, Finish and deadlines verified.\n",
        frames,limited,margin_frames,peak,ainekio_v2_gait_joint_speed_flag_threshold(),flagged_peak,ainekio_v2_gait_joint_speed_limit());
}
