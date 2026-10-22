#include "ainekio/v2_learning.h"
#include "ainekio/control_codec.h"
#include "ainekio/v2_balance.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void zero_parity(void)
{
    for(unsigned direction=0;direction<4;direction++) {
        ainekio_v2_walk_state_t a={0},b;ainekio_v2_gait_profile_t profile={0};
        assert(ainekio_v2_gait_begin(&a,direction,AINEKIO_GAIT_WALK,3,(ainekio_v2_walk_controls_t){70,2},0));
        b=a;ainekio_v2_walk_profile_begin(&b,&profile);
        for(uint64_t now=20000;!a.complete;now+=20000) {
            assert(ainekio_v2_walk_tick(&a,now)&&ainekio_v2_walk_tick(&b,now));
            assert(!memcmp(&a,&b,sizeof a));
        }
    }
}
static void landing_and_lift(void)
{
    ainekio_v2_walk_state_t baseline={0},learned;
    assert(ainekio_v2_walk_begin(&baseline,4,(ainekio_v2_walk_controls_t){50,1},0));
    learned=baseline;
    ainekio_v2_gait_profile_t profile={0};
    profile.landing_mm[0][0]=.5f;profile.landing_mm[0][1]=.2f;profile.lift_delta_mm[0]=.7f;
    assert(ainekio_v2_gait_profile_valid(&profile));ainekio_v2_walk_profile_begin(&learned,&profile);
    unsigned swings=0,planted=0;
    for(uint64_t now=20000;!baseline.complete;now+=20000) {
        ainekio_v2_walk_state_t before=learned;
        assert(ainekio_v2_walk_tick(&baseline,now)&&ainekio_v2_walk_tick(&learned,now));
        assert(baseline.phase==learned.phase);
        for(unsigned leg=0;leg<4;leg++) {
            if(!before.feet[leg].swinging&&!learned.feet[leg].swinging) {
                assert(before.feet[leg].start_x==learned.feet[leg].start_x);
                assert(before.feet[leg].start_y==learned.feet[leg].start_y);planted++;
            }
            if(leg!=2)assert(!memcmp(&baseline.feet[leg],&learned.feet[leg],sizeof baseline.feet[leg]));
        }
        if(learned.feet[2].swinging) {
            assert(fabs(learned.feet[2].end_x-baseline.feet[2].end_x-.5)<1e-6);
            assert(fabs(learned.feet[2].end_y-baseline.feet[2].end_y-.2)<1e-6);
            assert(fabs(learned.feet[2].lift-baseline.feet[2].lift-.7)<1e-6);swings++;
        }
    }
    assert(swings>20&&planted>200);
}
static void timing_body_and_steering(void)
{
    ainekio_v2_gait_profile_t profile={.duty_delta=-.01f,.sweep_delta_mm=-1.f,
        .phase_offset={.01f,-.01f,.02f,-.02f},.lift_delta_mm={.3f,.3f,.3f,.3f}};
    profile.body_mm[2][0]=.1f;
    for(unsigned direction=0;direction<4;direction++) {
        ainekio_v2_walk_state_t walk={0},base;
        assert(ainekio_v2_gait_begin(&walk,direction,AINEKIO_GAIT_WALK,4,(ainekio_v2_walk_controls_t){50,1},0));
        base=walk;ainekio_v2_walk_profile_begin(&walk,&profile);
        for(unsigned leg=0;leg<4;leg++)assert(fabs(walk.offset_target[leg]-base.offset_target[leg]-profile.phase_offset[(leg+2)%4])<1e-7);
        unsigned changed_support=0,changed_body=0;
        for(uint64_t now=20000;!walk.complete;now+=20000) {
            assert(ainekio_v2_walk_feedback_tick(&walk,now,true,true,0,NULL,NULL));
            assert(ainekio_v2_walk_tick(&base,now));
            for(unsigned leg=0;leg<4;leg++)changed_support+=walk.pose.grounded[leg]!=base.pose.grounded[leg];
            changed_body+=fabs(walk.pose.body[2]-base.pose.body[2])>.001;
            assert(walk.heading_active);
        }
        assert(changed_support>10&&changed_body>100);
    }
    profile.duty_delta=1;assert(!ainekio_v2_gait_profile_valid(&profile));
    profile.duty_delta=-1;assert(!ainekio_v2_gait_profile_valid(&profile));
    profile.duty_delta=0;profile.body_mm[0][0]=NAN;assert(!ainekio_v2_gait_profile_valid(&profile));
}
static void command_updates_and_run(void)
{
    ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
    c.data.intent.kind=AINEKIO_INTENT_WALK;
    c.data.intent.data.walk.gait=AINEKIO_GAIT_WALK;
    c.data.intent.data.walk.direction=AINEKIO_WALK_FORWARD;
    c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=70;
    ainekio_v2_walk_state_t walk={0};assert(ainekio_v2_walk_accept(&walk,&c,0));
    const ainekio_v2_gait_profile_t profile={.duty_delta=-.001f,.sweep_delta_mm=-.2f,
        .phase_offset={.001f,-.001f,.002f,-.002f},.lift_delta_mm={.1f,.1f,.1f,.1f}};
    ainekio_v2_walk_profile_begin(&walk,&profile);
    double offsets[4];memcpy(offsets,walk.offset_target,sizeof offsets);
    uint64_t now=0;ainekio_v2_balance_t balance={0};
    const float q[4]={.9999875f,.005f,0,0},rate[3]={0,0,0};
    for(unsigned stage=0;stage<4;stage++) {
        double end=walk.phase+(stage==0?4.:12.);
        while(walk.phase<end) {
            now+=20000;
            ainekio_v2_walk_state_t previous=walk;
            if(!ainekio_v2_walk_feedback_tick(&walk,now,true,true,walk.body_yaw,NULL,NULL)) {
                fprintf(stderr,"profile transition stage=%u phase=%g run=%g\n",stage,previous.phase,previous.pose.run_blend);assert(0);
            }
            assert(walk.fast_stroke&&walk.phase>previous.phase);
            for(unsigned l=0;l<4;l++)if(previous.feet[l].swinging&&walk.feet[l].touchdown_phase==previous.feet[l].touchdown_phase) {
                assert(walk.feet[l].end_x==previous.feet[l].end_x&&walk.feet[l].end_y==previous.feet[l].end_y);
            }
            ainekio_v2_walk_pose_t adjusted;
            ainekio_v2_balance_apply(&balance,q,rate,true,.02,&walk.pose,NULL,&previous.pose.frame,
                ainekio_v2_gait_joint_speed_limit(),&adjusted);
            assert(!memcmp(&walk.profile,&profile,sizeof profile));
            for(unsigned j=0;j<12;j++)assert(isfinite(adjusted.frame.position[j]));
        }
        if(stage==2) {
            assert(walk.pose.run_blend==1.);
            assert(walk.pose.grounded[0]==walk.pose.grounded[1]&&walk.pose.grounded[2]==walk.pose.grounded[3]);
        }
        if(stage==3) {
            assert(walk.pose.run_blend==0.);
            for(unsigned l=0;l<4;l++)assert(fabs(remainder(walk.offset_target[l]-offsets[l],1.))<1e-8);
            break;
        }
        c.sequence++;c.data.intent.data.walk.update_sequence=1;
        c.data.intent.data.walk.steering=true;
        c.data.intent.data.walk.forward=stage==0?70:100;
        c.data.intent.data.walk.turn=stage==0?30:0;
        c.data.intent.data.walk.speed_percent=stage==1?200:70;
        ainekio_v2_foot_state_t feet[4];memcpy(feet,walk.feet,sizeof feet);
        assert(ainekio_v2_walk_accept(&walk,&c,now));
        assert(!memcmp(feet,walk.feet,sizeof feet));
        float command_before[4],command_after[4];
        ainekio_v2_walk_command_features(&walk,command_before);
        double feedback=walk.feedback_turn;walk.feedback_turn=.5;
        ainekio_v2_walk_command_features(&walk,command_after);walk.feedback_turn=feedback;
        assert(!memcmp(command_before,command_after,sizeof command_before));
    }
}
int main(void)
{
    zero_parity();landing_and_lift();timing_body_and_steering();command_updates_and_run();
    puts("Gait profiles: zero parity, physical leg order, anchored support, learned lift/landings/body/timing and heading feedback passed");
}
