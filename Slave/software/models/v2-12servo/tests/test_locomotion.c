#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    double drift=0,step=0;
    const double strides[]={1,50,100},rates[]={.25,3};
    const unsigned intervals[]={10000,20000,30000,40000};
    for(unsigned cadence=0;cadence<4;cadence++)
    for(unsigned family=0;family<3;family++)for(unsigned direction=0;direction<(family==2?6:4);direction++)
    for(unsigned si=0;si<3;si++)for(unsigned ri=0;ri<2;ri++){
        ainekio_v2_walk_state_t state={0};
        ainekio_v2_walk_controls_t controls={strides[si],rates[ri]};
        bool crawl=family==1;
        assert(ainekio_v2_gait_begin(&state,(ainekio_walk_direction_t)direction,family==2?AINEKIO_GAIT_CRAB:crawl?AINEKIO_GAIT_CRAWL:AINEKIO_GAIT_WALK,0,controls,0));
        uint64_t now=0;bool stopped=false;
        while(!state.complete&&now<UINT64_C(120000000)){
            ainekio_v2_walk_pose_t old=state.pose;now+=intervals[cadence];
            if(!ainekio_v2_walk_tick(&state,now)){
                fprintf(stderr,"failed dt=%u crawl=%u dir=%u stride=%g rate=%g phase=%g\n",intervals[cadence],crawl,direction,controls.stride_percent,controls.motion_rate,state.phase);return 1;
            }
            for(unsigned i=0;i<4;i++){
                if(old.grounded[i]&&state.pose.grounded[i])for(unsigned k=0;k<2;k++)
                    drift=fmax(drift,fabs(old.feet[i][k]-state.pose.feet[i][k]));
                for(unsigned k=0;k<3;k++)step=fmax(step,fabs(old.joints[i][k]-state.pose.joints[i][k]));
            }
            if(!stopped&&state.phase>=7){
                assert(!state.complete); /* No old ten-cycle/time limit. */
                controls.stride_percent=0;assert(ainekio_v2_walk_update(&state,controls));stopped=true;
                controls.stride_percent=50;assert(!ainekio_v2_walk_update(&state,controls));
            }
        }
        assert(stopped&&state.complete&&!state.failed);
        assert(fabs(state.pose.body[2]-(family==2?-18.:crawl?-35.:-2.))<1e-8);
        for(unsigned i=0;i<4;i++)assert(state.pose.grounded[i]&&state.pose.sole_height[i]==0.);
        if(direction==AINEKIO_WALK_FORWARD)assert(state.body_x>0);
        if(direction==AINEKIO_WALK_BACKWARD)assert(state.body_x<0);
        if(direction==AINEKIO_WALK_SIDE_LEFT)assert(state.body_y>0);
        if(direction==AINEKIO_WALK_SIDE_RIGHT)assert(state.body_y<0);
        if(direction==AINEKIO_WALK_TURN_LEFT||direction==AINEKIO_WALK_TURN_RIGHT){assert(state.body_x==0.);assert(direction==AINEKIO_WALK_TURN_LEFT?state.body_yaw>0:state.body_yaw<0);}
    }
    assert(drift<1e-9);
    ainekio_v2_walk_state_t state={0};
    assert(ainekio_v2_locomotion_begin(&state,AINEKIO_WALK_FORWARD,true,0,(ainekio_v2_walk_controls_t){100,2},0));
    assert(ainekio_v2_walk_tick(&state,10000));
    assert(ainekio_v2_walk_update(&state,(ainekio_v2_walk_controls_t){0,1}));
    for(uint64_t now=20000;!state.complete;now+=10000)assert(ainekio_v2_walk_tick(&state,now));
    assert(state.phase==0 && state.body_x==0 && fabs(state.pose.body[2]+35)<1e-8);
    const char *directions[]={"fwd","back","turn_l","turn_r"};
    for(unsigned i=0;i<4;i++){
        char wire[256];snprintf(wire,sizeof(wire),"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"%s\",\"steps\":0,\"gait\":\"crawl\",\"speed\":25}",directions[i]);
        ainekio_control_message_t m;assert(ainekio_control_decode(wire,strlen(wire),&m)!=AINEKIO_DECODE_OK);
        assert(ainekio_control_decode_with_walk_controls(wire,strlen(wire),&m)==AINEKIO_DECODE_OK);
        state=(ainekio_v2_walk_state_t){0};assert(ainekio_v2_walk_accept(&state,&m.command,0));
        m.command.sequence=2;m.command.data.intent.data.walk.update_sequence=1;
        m.command.data.intent.data.walk.direction=(ainekio_walk_direction_t)((i+1)%4);
        assert(!ainekio_v2_walk_accept(&state,&m.command,0));
        m.command.data.intent.data.walk.direction=(ainekio_walk_direction_t)i;m.command.data.intent.data.walk.gait=AINEKIO_GAIT_WALK;
        assert(!ainekio_v2_walk_accept(&state,&m.command,0));
    }
    printf("84 locomotion envelopes at10/20/30/40 ms, planted XY drift %.9g mm; max output joint change %.6g rad. Finish during lowering and profile matching passed.\n",drift,step);
    return 0;
}
