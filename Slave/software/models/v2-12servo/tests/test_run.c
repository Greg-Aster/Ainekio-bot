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
    if(!ainekio_v2_walk_tick(s,now)){
        fprintf(stderr,"Run solve failed dir=%u blend=%g phase=%g now=%llu\n",s->direction,s->pose.run_blend,s->phase,(unsigned long long)now);assert(false);
    }
    leverage_step(&old,&s->pose);
    for(unsigned i=0;i<4;i++){
        if(old.grounded[i]&&s->pose.grounded[i])for(unsigned k=0;k<2;k++)drift=fmax(drift,fabs(s->pose.feet[i][k]-old.feet[i][k]));
        assert(s->pose.sole_height[i]>=-1e-8);
        for(unsigned j=0;j<3;j++)max_step=fmax(max_step,fabs(s->pose.joints[i][j]-old.joints[i][j]));
    }
    if(s->pose.run_blend==1. && s->phase>s->run_transition_phase+5. && !s->stopping){
        assert(s->pose.grounded[0]==s->pose.grounded[1]);assert(s->pose.grounded[2]==s->pose.grounded[3]);paired++;
        if(!s->pose.grounded[0]&&!s->pose.grounded[2])flight++;
    }
}
int main(void)
{
    const unsigned intervals[]={10000,20000,30000,40000};
    const double speeds[]={100.001,125,150,200};
    for(unsigned interval=0;interval<4;interval++)for(unsigned dir=0;dir<4;dir++)for(unsigned start=0;start<4;start++){
        ainekio_v2_walk_state_t s={0};uint64_t now=0;
        ainekio_command_t c=command(1,0,dir,AINEKIO_GAIT_WALK,speeds[start]);assert(ainekio_v2_walk_accept(&s,&c,0));
        while(s.phase<10.){now+=intervals[interval];tick(&s,now);}
        c=command(2,1,dir,AINEKIO_GAIT_WALK,75);assert(ainekio_v2_walk_accept(&s,&c,now));
        double back=s.phase;
        while(s.phase<back+7.){now+=intervals[interval];tick(&s,now);}
        assert(s.pose.run_blend==0.);
        c=command(3,1,dir,AINEKIO_GAIT_WALK,200);assert(ainekio_v2_walk_accept(&s,&c,now));
        while(s.phase<back+14.){now+=intervals[interval];tick(&s,now);}
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
        while(!s.complete){assert(now<10000000);now+=intervals[interval];tick(&s,now);}
        for(unsigned i=0;i<4;i++)assert(s.pose.grounded[i]);
    }
    /* Threshold reversals and Finish while feet are being resynchronized. */
    for(unsigned dir=0;dir<4;dir++)for(unsigned stop=0;stop<3;stop++){
        ainekio_v2_walk_state_t s={0};uint64_t now=0;ainekio_command_t c=command(1,0,dir,AINEKIO_GAIT_WALK,100);assert(ainekio_v2_walk_accept(&s,&c,0));
        while(s.phase<5.){now+=10000;tick(&s,now);}assert(s.pose.run_blend==0.);
        for(unsigned n=0;n<8;n++){
            c=command(n+2,1,dir,AINEKIO_GAIT_WALK,n%2?85:200);assert(ainekio_v2_walk_accept(&s,&c,now));
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
    /* Independent stride/cadence still works on an explicit bound. */
    for(unsigned interval=0;interval<4;interval++)for(unsigned dir=0;dir<4;dir++)for(unsigned si=0;si<3;si++)for(unsigned ri=0;ri<2;ri++){
        const double strides[]={1,50,100},rates[]={.25,3};
        ainekio_v2_walk_state_t s={0};uint64_t now=0;ainekio_v2_walk_controls_t c={strides[si],rates[ri]};
        assert(ainekio_v2_gait_begin(&s,(ainekio_walk_direction_t)dir,AINEKIO_GAIT_RUN,0,c,0));
        while(s.phase<7.){now+=intervals[interval];tick(&s,now);}
        c.stride_percent=0;assert(ainekio_v2_walk_update(&s,c));
        while(!s.complete){assert(now<90000000);now+=intervals[interval];tick(&s,now);}
    }
    /* Observe modeled translation through a steady cycle at two speeds.
     * Speed must open the stroke as well as increase cadence. */
    for(unsigned n=0;n<2;n++){
        const double speed[]={150,200},sweep[]={92,104};
        ainekio_v2_walk_state_t state={0};uint64_t now=0;
        ainekio_command_t request=command(1,0,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_WALK,speed[n]);
        assert(ainekio_v2_walk_accept(&state,&request,0));
        while(state.phase<8.){now+=10000;tick(&state,now);}
        if(n==1){
            /* Full forward Run keeps the physical front pair inside and rear
             * pair outside; contacts keep their lateral anchors. */
            ainekio_v2_walk_pose_t neutral;assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&neutral));
            for(unsigned leg=0;leg<4;leg++){
                double lateral=fabs(state.pose.feet[leg][1])-fabs(neutral.feet[leg][1]);
                assert(fabs(lateral-(leg<2?-8.:8.))<1e-6);
                assert(leg<2?state.pose.joints[leg][0]>0.:state.pose.joints[leg][0]<0.);
            }
        }
        double phase=state.phase,x=state.pose.body[0];
        while(state.phase<phase+1.){now+=10000;tick(&state,now);}
        assert(fabs(fabs(state.pose.body[0]-x)/(state.phase-phase)-sweep[n]/.42)<1e-5);
    }
    const char *valid[]={"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":200}","{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"gait\":\"run\",\"stride\":100,\"rate\":3}"};
    for(unsigned i=0;i<2;i++){ainekio_control_message_t m;assert(ainekio_control_decode(valid[i],strlen(valid[i]),&m)!=AINEKIO_DECODE_OK);assert(ainekio_control_decode_with_walk_controls(valid[i],strlen(valid[i]),&m)==AINEKIO_DECODE_OK);}
    ainekio_v2_walk_state_t s={0};ainekio_command_t c=command(1,0,0,AINEKIO_GAIT_WALK,201);assert(!ainekio_v2_walk_accept(&s,&c,0));
    c=command(1,0,0,AINEKIO_GAIT_CRAWL,101);assert(!ainekio_v2_walk_accept(&s,&c,0));
    assert(drift<1e-9&&paired>100&&flight>100);
    printf("Run: 64 automatic round trips, 8 early exits, 12 rapid reversals/Finish, 96 advanced envelopes; planted drift %.9g mm, max emitted step %.6g rad, paired=%u flight=%u\n",drift,max_step,paired,flight);
    leverage_report();
}
