#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "leverage_checks.h"

static ainekio_command_t command(unsigned sequence,unsigned update,unsigned direction,ainekio_gait_t gait,double speed)
{
    ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=sequence};
    c.data.intent.kind=AINEKIO_INTENT_WALK;
    c.data.intent.data.walk.direction=(ainekio_walk_direction_t)direction;
    c.data.intent.data.walk.gait=gait;c.data.intent.data.walk.controls=1;
    c.data.intent.data.walk.speed_percent=speed;c.data.intent.data.walk.update_sequence=update;
    return c;
}
static double drift,max_step;static unsigned paired,flight;
static void tick(ainekio_v2_walk_state_t *s,uint64_t now)
{
    ainekio_v2_walk_pose_t old=s->pose;
    double touchdown[4];for(unsigned i=0;i<4;i++)touchdown[i]=s->feet[i].touchdown_phase;
    if(!ainekio_v2_walk_tick(s,now)){
        fprintf(stderr,"Run solve failed dir=%u blend=%g phase=%g now=%llu\n",s->direction,s->pose.run_blend,s->phase,(unsigned long long)now);assert(false);
    }
    leverage_step(&old,&s->pose);
    for(unsigned i=0;i<4;i++){
        if(old.grounded[i]&&!s->pose.grounded[i]) {
            /* Newly committed touchdown must meet the FUTURE phase schedule,
             * including an offset still moving during Walk/Run blending. */
            double td=s->feet[i].touchdown_phase;
            double u=fmax(0.,fmin(1.,(td-s->run_transition_phase)/V2_RUN_TRANSITION));
            double blend=u*u*u*(10.+u*(-15.+6.*u));
            double offset=s->offset_from[i]+(s->offset_target[i]-s->offset_from[i])*blend;
            assert(td>s->phase && fabs(td-offset-round(td-offset))<1e-7);
        }
        /* A complete fast swing can occur between two 40 ms samples.
         * Compare planted anchors only within the same contact interval. */
        if(old.grounded[i]&&s->pose.grounded[i]&&touchdown[i]==s->feet[i].touchdown_phase)for(unsigned k=0;k<2;k++)drift=fmax(drift,fabs(s->pose.feet[i][k]-old.feet[i][k]));
        assert(s->pose.sole_height[i]>=-1e-8);
        for(unsigned j=0;j<3;j++)max_step=fmax(max_step,fabs(s->pose.joints[i][j]-old.joints[i][j]));
    }
    if(s->pose.run_blend==1. && s->phase>s->run_transition_phase+V2_RUN_TRANSITION+1. && !s->stopping){
        assert(s->pose.grounded[0]==s->pose.grounded[1]);assert(s->pose.grounded[2]==s->pose.grounded[3]);paired++;
        if(!s->pose.grounded[0]&&!s->pose.grounded[2])flight++;
        /* Run must not recreate the low, forward-reaching crouch. These
         * checks accompany the retained paired support/flight assertions. */
        assert(s->pose.body[2]>=V2_RUN_FORWARD_BODY_Z-1e-6);
        assert(fabs(s->pose.euler[1])<1e-9);
        if(s->direction==AINEKIO_WALK_FORWARD)for(unsigned leg=0;leg<4;leg++) {
            double relative=s->pose.feet[leg][0]-s->pose.body[0]-v2_walk_stance[leg][0];
            assert(relative<V2_RUN_FORWARD_SWEEP*.6 && relative>-V2_RUN_FORWARD_SWEEP*.75);
        }
    }
}
int main(void)
{
    const unsigned intervals[]={10000,20000,30000,40000};
    const double speeds[]={100.001,125,150,200};
    for(unsigned interval=0;interval<4;interval++)for(unsigned dir=0;dir<4;dir++)for(unsigned start=0;start<4;start++){
        ainekio_v2_walk_state_t s={0};uint64_t now=0;
        ainekio_command_t c=command(1,0,dir,AINEKIO_GAIT_WALK,speeds[start]);assert(ainekio_v2_walk_accept(&s,&c,0));
        assert(s.run_from==1. && s.run_target==1.);
        for(unsigned leg=0;leg<4;leg++)assert(s.offset_target[leg]==(leg<2?0.:.5));
        while(s.phase<10.){now+=intervals[interval];tick(&s,now);}
        c=command(2,1,dir,AINEKIO_GAIT_WALK,75);assert(ainekio_v2_walk_accept(&s,&c,now));
        double back=s.phase;
        while(s.phase<back+V2_RUN_TRANSITION+4.){now+=intervals[interval];tick(&s,now);}
        assert(s.pose.run_blend==0.);
        c=command(3,1,dir,AINEKIO_GAIT_WALK,200);assert(ainekio_v2_walk_accept(&s,&c,now));
        while(s.phase<back+2.*(V2_RUN_TRANSITION+4.)){now+=intervals[interval];tick(&s,now);}
        c=command(4,1,dir,AINEKIO_GAIT_WALK,0);assert(ainekio_v2_walk_accept(&s,&c,now));
        while(!s.complete){assert(now<120000000);now+=intervals[interval];tick(&s,now);}
        for(unsigned i=0;i<4;i++)assert(s.pose.grounded[i]);
    }
    /* One cycle ends during the Walk-to-Run blend. Immediate deceleration
     * used to leave an airborne foot's committed landing unreachable at
     * 2460 ms with 20 ms ticks. Explicit Finish near phase 3 had the same bug. */
    for(unsigned interval=0;interval<4;interval++)for(unsigned finite=0;finite<2;finite++){
        ainekio_v2_walk_state_t s={0};uint64_t now=0;
        ainekio_command_t c=command(1,0,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,200);
        c.data.intent.data.walk.steps=finite?1:0;assert(ainekio_v2_walk_accept(&s,&c,0));
        if(!finite){
            while(s.phase<3.){now+=intervals[interval];tick(&s,now);}
            c=command(2,1,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,0);assert(ainekio_v2_walk_accept(&s,&c,now));
        }
        while(!s.complete){assert(now<30000000);now+=intervals[interval];tick(&s,now);}
        for(unsigned i=0;i<4;i++)assert(s.pose.grounded[i]);
    }
    /* Threshold reversals and Finish while feet are being resynchronized. */
    for(unsigned dir=0;dir<4;dir++)for(unsigned stop=0;stop<3;stop++){
        ainekio_v2_walk_state_t s={0};uint64_t now=0;ainekio_command_t c=command(1,0,dir,AINEKIO_GAIT_WALK,100);assert(ainekio_v2_walk_accept(&s,&c,0));
        while(s.phase<5.){now+=10000;tick(&s,now);}assert(s.pose.run_blend==0.);
        for(unsigned n=0;n<8;n++){
            c=command(n+2,1,dir,AINEKIO_GAIT_WALK,n%2?85:200);assert(ainekio_v2_walk_accept(&s,&c,now));
            assert(!s.pending_update && s.target.stride_percent==s.requested_stride_percent);
            for(unsigned leg=0;leg<4;leg++)
                assert(fabs(s.offset_target[leg]-s.offset_from[leg])<=.5+1e-8);
            uint64_t end=now+(stop+1)*170000;
            while(now<end){now+=10000;tick(&s,now);}
        }
        c=command(10,1,dir,AINEKIO_GAIT_WALK,0);assert(ainekio_v2_walk_accept(&s,&c,now));
        while(!s.complete){assert(now<30000000);now+=10000;tick(&s,now);}
    }
    /* Finish after several explicit Run rate changes must honor an airborne
     * pair's already committed landing, just like Finish during blending. */
    for(unsigned interval=0;interval<4;interval++) {
        ainekio_v2_walk_state_t s={0};uint64_t now=0;
        ainekio_command_t c=command(1,0,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_RUN,100);
        assert(ainekio_v2_walk_accept(&s,&c,0));
        const unsigned at[]={2000000,4000000,6000000,8500000};
        const double speed[]={200,75,200,0};unsigned event=0;
        while(!s.complete) {
            assert(now<20000000);now+=intervals[interval];tick(&s,now);
            if(event<4 && now>=at[event]) {
                c=command(event+2,1,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_RUN,speed[event]);
                assert(ainekio_v2_walk_accept(&s,&c,now));event++;
            }
        }
        assert(event==4);for(unsigned i=0;i<4;i++)assert(s.pose.grounded[i]);
    }
    /* The offline reference-time API still supports explicit cadence. */
    for(unsigned interval=0;interval<4;interval++)for(unsigned dir=0;dir<4;dir++)for(unsigned si=0;si<3;si++)for(unsigned ri=0;ri<2;ri++){
        const double strides[]={1,50,100},rates[]={.25,3};
        ainekio_v2_walk_state_t s={0};uint64_t now=0;ainekio_v2_walk_controls_t c={strides[si],rates[ri]};
        assert(ainekio_v2_gait_begin(&s,(ainekio_walk_direction_t)dir,AINEKIO_GAIT_RUN,0,c,0));
        while(s.phase<7.){now+=intervals[interval];tick(&s,now);}
        c.stride_percent=0;assert(ainekio_v2_walk_update(&s,c));
        while(!s.complete){assert(now<90000000);now+=intervals[interval];tick(&s,now);}
    }
    assert(ainekio_v2_joint_speed_set(20000.F));
    /* Observe modeled translation through a steady cycle at two speeds.
     * Speed must open the stroke; angular travel determines cadence. */
    for(unsigned n=0;n<2;n++){
        const double speed[]={150,200},sweep[]={(V2_RUN_START_SWEEP+V2_RUN_FORWARD_SWEEP)*.5,V2_RUN_FORWARD_SWEEP};
        ainekio_v2_walk_state_t state={0};uint64_t now=0;
        ainekio_command_t request=command(1,0,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,speed[n]);
        assert(ainekio_v2_walk_accept(&state,&request,0));
        while(state.phase<state.run_transition_phase+V2_RUN_TRANSITION+4.){now+=10000;tick(&state,now);}
        assert(state.pose.run_blend==1.);
        if(n==1){
            /* Full forward Run keeps the physical front pair inside and rear
             * pair outside; contacts keep their lateral anchors. */
            ainekio_v2_walk_pose_t neutral;assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&neutral));
            for(unsigned leg=0;leg<4;leg++){
                double lateral=fabs(state.pose.feet[leg][1])-fabs(neutral.feet[leg][1]);
                assert(fabs(lateral-(leg<2?-V2_RUN_FORWARD_LANE:V2_RUN_FORWARD_LANE))<1e-6);
                if(V2_RUN_FORWARD_LANE>0.)assert(leg<2?state.pose.joints[leg][0]>0.:state.pose.joints[leg][0]<0.);
            }
        }
        double phase=state.phase,x=state.pose.body[0];
        while(state.phase<phase+1.){now+=10000;tick(&state,now);}
        /* The bound advances uniformly per gait phase at requested cadence. */
        double normalized_progress=(state.phase-phase)/V2_RUN_DUTY;
        assert(fabs(fabs(state.pose.body[0]-x)-sweep[n]*normalized_progress)<1e-4);
    }
    /* Speed opens stride and foot lift while retaining upright body attitude in both the
     * Walk-to-Run family and explicit Run. The posture/gesture speed setting
     * must not reduce walking cadence or translation. */
    const double cadence_speeds[]={105,125,150,175,200};
    const float limits[]={200.F,20000.F};
    for(unsigned li=0;li<2;li++)for(unsigned family=0;family<2;family++) {
      assert(ainekio_v2_joint_speed_set(limits[li]));
      double previous_cadence=INFINITY,previous_stride=0.,previous_lift=0.,previous_travel_speed=0.;
      for(unsigned n=0;n<5;n++) {
        ainekio_v2_walk_state_t state={0};uint64_t now=0;
        ainekio_command_t request=command(1,0,AINEKIO_WALK_FORWARD,family?AINEKIO_GAIT_RUN:AINEKIO_GAIT_WALK,cadence_speeds[n]);
        assert(ainekio_v2_walk_accept(&state,&request,0));
        double phase_at_50=0.,x_at_50=0.,lift=0.,pitch_min=INFINITY,pitch_max=-INFINITY;bool flagged=false;
        while(now<60000000) {
            now+=now<50000000?20000:1000;tick(&state,now);
            assert(state.fast_stroke && state.clock_scale>0.);
            if(now==50000000){phase_at_50=state.phase;x_at_50=state.pose.body[0];}
            if(now>=50000000) {
                flagged|=state.speed_flagged;
                for(unsigned leg=0;leg<4;leg++)lift=fmax(lift,state.pose.sole_height[leg]);
                pitch_min=fmin(pitch_min,state.pose.euler[1]);pitch_max=fmax(pitch_max,state.pose.euler[1]);
            }
        }
        const double cadence=(state.phase-phase_at_50)/10.;
        const double requested=state.requested_cycles_s;
        const double stride=100.*(V2_RUN_START_SWEEP+(V2_RUN_FORWARD_SWEEP-V2_RUN_START_SWEEP)*(cadence_speeds[n]-100.)/100.)/V2_RUN_FORWARD_SWEEP;
        const double travel_speed=(state.pose.body[0]-x_at_50)/10.;
        assert(state.automatic_run && fabs(state.target.stride_percent-stride)<1e-9);
        assert(state.target.stride_percent==state.requested_stride_percent);
        assert(fabs(state.stride_percent-stride)<1e-9);
        assert(stride>previous_stride && lift>previous_lift);
        assert(fabs(pitch_min)<1e-9 && fabs(pitch_max)<1e-9);
        /* Longer strokes take longer at the same angular movement rate. */
        assert(cadence<previous_cadence && cadence>0.);
        assert(travel_speed>previous_travel_speed && !flagged);
        printf("%s Run %.0f%% at %.0f deg/s: %.4f / %.4f cycles/s, stride %.2f%%, lift %.2f mm, pitch %.2f deg\n",family?"Explicit":"Automatic",cadence_speeds[n],limits[li],cadence,requested,stride,lift,(pitch_max-pitch_min)*180./acos(-1.));
        previous_cadence=cadence;previous_stride=stride;previous_lift=lift;previous_travel_speed=travel_speed;
      }
    }
    /* Increasing Speed on one ongoing command preserves its ownership and
     * responds after coordinated transitions, including a return to Walk. */
    ainekio_v2_walk_state_t ongoing={0};uint64_t ongoing_now=0;
    assert(ainekio_v2_joint_speed_set(1000.F));
    ainekio_command_t initial=command(1,0,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,100);
    assert(ainekio_v2_walk_accept(&ongoing,&initial,0));
    for(unsigned n=0;n<5;n++) {
        ainekio_command_t update=command(n+2,1,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,cadence_speeds[n]);
        assert(ainekio_v2_walk_accept(&ongoing,&update,ongoing_now));
        const uint64_t end=ongoing_now+60000000;
        while(ongoing_now<end){ongoing_now+=20000;tick(&ongoing,ongoing_now);}
        assert(ongoing.command_sequence==1 && ongoing.automatic_run);
        assert(ongoing.target.stride_percent==ongoing.requested_stride_percent);
    }
    ainekio_command_t back=command(7,1,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,75);
    assert(ainekio_v2_walk_accept(&ongoing,&back,ongoing_now) && !ongoing.automatic_run);
    assert(ainekio_v2_joint_speed_set(ainekio_v2_joint_speed_default()));
    const char *valid[]={"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":200}","{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"gait\":\"run\",\"stride\":100,\"rate\":3}"};
    for(unsigned i=0;i<2;i++){ainekio_control_message_t m;assert(ainekio_control_decode(valid[i],strlen(valid[i]),&m)!=AINEKIO_DECODE_OK);assert(ainekio_control_decode_with_walk_controls(valid[i],strlen(valid[i]),&m)==AINEKIO_DECODE_OK);}
    ainekio_v2_walk_state_t s={0};ainekio_command_t c=command(1,0,0,AINEKIO_GAIT_WALK,201);assert(!ainekio_v2_walk_accept(&s,&c,0));
    c=command(1,0,0,AINEKIO_GAIT_CRAWL,101);assert(!ainekio_v2_walk_accept(&s,&c,0));
    assert(drift<1e-9&&paired>100&&flight>100);
    printf("Run: 64 automatic round trips, 8 early exits, 12 rapid reversals/Finish, 96 advanced envelopes; planted drift %.9g mm, max emitted step %.6g rad, paired=%u flight=%u\n",drift,max_step,paired,flight);
    leverage_report();
}
