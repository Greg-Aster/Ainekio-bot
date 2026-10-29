#include "ainekio/v2_walk.h"
#include "ainekio/v2_learning.h"
#include "ainekio/v2_limits.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static ainekio_command_t command(const char *gait,const char *direction,unsigned stride)
{
    char wire[256];ainekio_control_message_t message;
    snprintf(wire,sizeof wire,"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"gait\":\"%s\",\"dir\":\"%s\",\"steps\":0,\"stride\":%u,\"rate\":2}",gait,direction,stride);
    assert(ainekio_control_decode_with_walk_controls(wire,strlen(wire),&message)==AINEKIO_DECODE_OK);
    return message.command;
}
static void unchanged_when_off(void)
{
    const char *gaits[]={"walk","run","crawl","crab"};
    for(unsigned g=0;g<4;g++) {
        ainekio_command_t c=command(gaits[g],"fwd",100);
        ainekio_v2_walk_state_t plain={0},feedback={0};
        assert(ainekio_v2_walk_accept(&plain,&c,0));feedback=plain;
        for(uint64_t t=20000;t<=4000000;t+=20000) {
            assert(ainekio_v2_walk_tick(&plain,t));
            assert(ainekio_v2_walk_feedback_tick(&feedback,t,false,true,1.,NULL,NULL));
            assert(plain.phase==feedback.phase);
            assert(!memcmp(&plain.pose,&feedback.pose,sizeof plain.pose));
        }
    }
}
static void disturbance(int sign)
{
    ainekio_command_t c=command("walk","fwd",100);
    ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
    double measured=3.1,initial=measured;
    for(uint64_t t=20000;t<=16000000;t+=20000) {
        double phase=s.phase,body_yaw=s.body_yaw;
        double wrapped=atan2(sin(measured),cos(measured));
        if(!ainekio_v2_walk_feedback_tick(&s,t,true,true,wrapped,NULL,NULL)) {
            fprintf(stderr,"failed sign %d at %llu phase %g turn %g\n",sign,(unsigned long long)t,s.phase,s.feedback_turn);assert(0);
        }
        assert(s.fast_stroke && s.phase>phase);
        assert(ainekio_v2_limits_frame(&s.pose.frame));
        measured+=s.body_yaw-body_yaw+sign*.065*(s.phase-phase);
    }
    printf("disturbance %d: heading error %.3f degrees, turn %.2f%%\n",sign,(measured-initial)*180/3.141592653589793,s.feedback_turn*100);
    assert(fabs(measured-initial)<.04); /* Open-loop would turn over 80 degrees. */
    assert(sign*s.feedback_turn<0.);
    double correction=fabs(s.feedback_turn),phase=s.phase;
    for(uint64_t t=16020000;t<=18000000;t+=20000)
        assert(ainekio_v2_walk_feedback_tick(&s,t,true,false,NAN,NULL,NULL));
    assert(s.phase>phase && fabs(s.feedback_turn)<correction*.02 && !s.heading_active);
    /* Recovery rebases sensor heading, not gait phase or operator controls. */
    assert(ainekio_v2_walk_feedback_tick(&s,18020000,true,true,-2.,NULL,NULL));
    assert(s.heading_active && fabs(s.heading_error)<1e-9);
}
static bool same_frame(const ainekio_v2_frame_t *frame,void *context)
{
    const ainekio_v2_frame_t *expected=context;
    for(unsigned j=0;j<12;j++)if(frame->position[j]!=expected->position[j])return false;
    return true;
}
static void correction_only_reduction(void)
{
    ainekio_command_t c=command("walk","fwd",100);
    ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
    for(uint64_t t=20000;t<=2000000;t+=20000)
        assert(ainekio_v2_walk_feedback_tick(&s,t,true,true,0.,NULL,NULL));
    ainekio_v2_walk_state_t nominal=s;assert(ainekio_v2_walk_tick(&nominal,2020000));
    /* Emulate a calibrated envelope with room only for the nominal target. */
    assert(ainekio_v2_walk_feedback_tick(&s,2020000,true,true,-.2,same_frame,&nominal.pose.frame));
    assert(s.heading_reduced && s.phase==nominal.phase && s.feedback_turn==0.);
    assert(s.forward_target==100. && s.fast_stroke && !s.failed);
}
static void families(void)
{
    const char *gaits[]={"walk","run","crawl","crab"};
    const char *dirs[]={"fwd","back","turn_l","turn_r","side_l","side_r"};
    for(unsigned g=0;g<4;g++)for(unsigned d=0;d<(g==3?6:4);d++)for(unsigned speed=25;speed<=100;speed+=25) {
        ainekio_command_t c=command(gaits[g],dirs[d],speed);
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        double measured=0.;
        for(uint64_t t=20000;t<=6000000;t+=20000) {
            double phase=s.phase,yaw=s.body_yaw;
            if(!ainekio_v2_walk_feedback_tick(&s,t,true,true,measured,NULL,NULL)) {
                fprintf(stderr,"family %s %s %u t=%llu phase=%g turn=%g\n",gaits[g],dirs[d],speed,(unsigned long long)t,s.phase,s.feedback_turn);assert(0);
            }
            measured+=s.body_yaw-yaw-.02*(s.phase-phase);
        }
    }
}
static void intentional_turn(void)
{
    ainekio_command_t c=command("walk","fwd",70);
    c.data.intent.data.walk.steering=true;
    c.data.intent.data.walk.forward=70;c.data.intent.data.walk.turn=30;
    ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
    for(uint64_t t=20000;t<=6000000;t+=20000) {
        assert(ainekio_v2_walk_feedback_tick(&s,t,true,true,s.body_yaw,NULL,NULL));
        assert(fabs(s.feedback_turn)<1e-5 && fabs(s.heading_error)<1e-5);
        if(t==2000000) {
            c.sequence=2;c.data.intent.data.walk.update_sequence=1;c.data.intent.data.walk.turn=-30;
            assert(ainekio_v2_walk_accept(&s,&c,t));
        }
    }
    assert(s.turn_target==-30 && s.phase>4.);
}
static void host_geometry_heading(void)
{
    ainekio_v2_walk_state_t s={.initialized=true,.host_nominal=true};
    ainekio_v2_walk_pose_t stand;assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
    s.host_reference=stand.frame;
    const float offsets[4][3]={{0}};
    assert(ainekio_v2_nominal_foot_pose(&s.host_reference,offsets,NULL,NULL,&s.pose,
        s.host_anchors,s.host_applied,s.host_fit));
    const ainekio_v2_walk_pose_t nominal=s.pose;
    assert(ainekio_v2_walk_host_heading(&s,20000,true,true,3.1,NULL,NULL));
    s.pose=nominal;
    assert(ainekio_v2_walk_host_heading(&s,40000,true,true,-3.1,NULL,NULL));
    assert(s.heading_measured>0. && fabs(s.heading_error+(.083185307179586))<1e-6);
    assert(s.pose.euler[2]<0. && s.phase==0.); /* No procedural clock or sampled gait. */
    for(unsigned l=0;l<4;l++)for(unsigned a=0;a<2;a++)assert(s.pose.feet[l][a]==nominal.feet[l][a]);
    s.pose=nominal;s.host_twist[2]=.5;
    const double reference=s.heading_reference;
    assert(ainekio_v2_walk_host_heading(&s,60000,true,true,-3.1,same_frame,(void *)&nominal.frame));
    assert(fabs(s.heading_reference-reference-.01)<1e-9 && s.heading_reduced);
    assert(!memcmp(&s.pose.frame,&nominal.frame,sizeof nominal.frame));
    s.pose=nominal;
    assert(ainekio_v2_walk_host_heading(&s,80000,true,false,NAN,NULL,NULL));
    assert(!s.heading_active && !s.heading_acquired && !memcmp(&s.pose.frame,&nominal.frame,sizeof nominal.frame));
    assert(s.host_heading_correction==0.);
}

static void host_delayed_body_response(void)
{
    for(int sign=-1;sign<=1;sign+=2) {
        ainekio_v2_walk_state_t s={.initialized=true,.host_nominal=true};
        ainekio_v2_walk_pose_t stand;
        assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
        s.host_reference=stand.frame;
        const float offsets[4][3]={{0}};
        assert(ainekio_v2_nominal_foot_pose(&s.host_reference,offsets,NULL,NULL,&s.pose,
            s.host_anchors,s.host_applied,s.host_fit));
        const ainekio_v2_walk_pose_t nominal=s.pose;
        assert(ainekio_v2_walk_host_heading(&s,20000,true,true,0.,NULL,NULL));
        assert(!memcmp(&s.pose.frame,&nominal.frame,sizeof nominal.frame));
        double measured=sign*.04, late_peak=0.;
        for(uint64_t t=40000;t<=12000000;t+=20000) {
            s.pose=nominal;
            assert(ainekio_v2_walk_host_heading(&s,t,true,true,measured,NULL,NULL));
            if(t==40000)assert(sign*s.pose.euler[2]<0.);
            /* An ideal body follows the previous output on the next tick.
             * The old full-error controller oscillated forever here. */
            measured=s.pose.euler[2];
            if(t>6000000)late_peak=fmax(late_peak,fabs(measured));
            assert(s.phase==0. && ainekio_v2_limits_frame(&s.pose.frame));
        }
        assert(late_peak<1e-6);
        /* Matching an intentional turn has no derivative braking or retained
         * disturbance correction. Both turn signs use the same reference. */
        s.host_twist[2]=sign*.2;
        for(uint64_t t=12020000;t<=14000000;t+=20000) {
            s.pose=nominal;measured=(t-12000000)/1e6*s.host_twist[2];
            assert(ainekio_v2_walk_host_heading(&s,t,true,true,measured,NULL,NULL));
            assert(fabs(s.heading_error)<1e-6 && fabs(s.host_heading_correction)<1e-6);
        }
        s.pose=nominal;
        assert(ainekio_v2_walk_host_heading(&s,14020000,true,false,NAN,NULL,NULL));
        assert(s.host_heading_correction==0. && !s.heading_acquired);
        s.host_twist[2]=0.;s.pose=nominal;
        assert(ainekio_v2_walk_host_heading(&s,14040000,true,true,2.,NULL,NULL));
        assert(s.heading_error==0. && s.host_heading_correction==0.);
        assert(!memcmp(&s.pose.frame,&nominal.frame,sizeof nominal.frame));
    }
}

int main(void)
{
    host_geometry_heading();host_delayed_body_response();
    unchanged_when_off();correction_only_reduction();families();disturbance(-1);disturbance(1);intentional_turn();
    puts("Walking feedback: nominal parity, both heading signs, yaw wrap, requested curves, dropout and recovery passed.");
}
