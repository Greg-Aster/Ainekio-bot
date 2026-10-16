#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "leverage_checks.h"

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
            leverage_step(&old,&state.pose);
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
        assert(fabs(state.pose.body[2]-(family==2?V2_CRAB_BODY_Z:crawl?V2_CRAWL_BODY_Z:V2_BODY_Z))<1e-6);
        for(unsigned i=0;i<4;i++)assert(state.pose.grounded[i]&&state.pose.sole_height[i]==0.);
        /* body_x records commanded travel from zero. Crawl's rearward bias
         * belongs to its foot-placement targets, not the entry root position. */
        if(direction==AINEKIO_WALK_FORWARD)assert(state.body_x>0.);
        if(direction==AINEKIO_WALK_BACKWARD)assert(state.body_x<0.);
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
    assert(state.phase==0 && state.body_x==0. && fabs(state.pose.body[2]-V2_CRAWL_BODY_Z)<1e-8);
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
    /* Compose translation and yaw, then reverse steering on the same running
     * command. Neither an update nor a fresh heading restarts the gait phase. */
    const char *arc="{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":40,\"forward\":65,\"turn\":25}";
    ainekio_control_message_t command;
    assert(ainekio_control_decode(arc,strlen(arc),&command)!=AINEKIO_DECODE_OK);
    assert(ainekio_control_decode_for_body(arc,strlen(arc),&command)==AINEKIO_DECODE_OK);
    assert(command.command.data.intent.data.walk.steering);
    assert(command.command.data.intent.data.walk.forward==65.F);
    assert(command.command.data.intent.data.walk.turn==25.F);
    const char *bad_steering[]={
        "{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"forward\":70}",
        "{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"turn\":25}",
        "{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"forward\":101,\"turn\":25}",
        "{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"forward\":70,\"turn\":-101}",
        "{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"forward\":70,\"turn\":true}"};
    for(unsigned i=0;i<sizeof(bad_steering)/sizeof(bad_steering[0]);i++){
        ainekio_control_message_t rejected;
        assert(ainekio_control_decode_for_body(bad_steering[i],strlen(bad_steering[i]),&rejected)!=AINEKIO_DECODE_OK);
    }
    state=(ainekio_v2_walk_state_t){0};assert(ainekio_v2_walk_accept(&state,&command.command,0));
    uint64_t arc_time=0;
    while(state.phase<5){arc_time+=20000;assert(ainekio_v2_walk_tick(&state,arc_time));}
    assert(state.body_x>0&&state.body_y>0&&state.body_yaw>0&&!state.complete);
    double arc_phase=state.phase,left_yaw=state.body_yaw;
    command.command.sequence=2;command.command.data.intent.data.walk.update_sequence=1;
    command.command.data.intent.data.walk.turn=-25;
    assert(ainekio_v2_walk_accept(&state,&command.command,arc_time));
    assert(state.phase==arc_phase&&state.command_sequence==1);
    while(state.phase<arc_phase+4){arc_time+=20000;assert(ainekio_v2_walk_tick(&state,arc_time));}
    assert(state.body_yaw<left_yaw&&!state.complete);
    /* Full-stroke curved reversal exposed leverage loss missed by the earlier
     * 40% arc test. Preserve sequence, planted anchors and the existing floors
     * through direction changes, then finish the same command. */
    const char *reversal="{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":100,\"forward\":100,\"turn\":0}";
    assert(ainekio_control_decode_for_body(reversal,strlen(reversal),&command)==AINEKIO_DECODE_OK);
    state=(ainekio_v2_walk_state_t){0};
    assert(ainekio_v2_walk_accept(&state,&command.command,0));
    for(uint64_t now=20000;now<=40000000&&!state.complete;now+=20000){
        ainekio_v2_walk_pose_t old=state.pose;
        assert(ainekio_v2_walk_tick(&state,now));
        leverage_step(&old,&state.pose);
        for(unsigned leg=0;leg<4;leg++)if(old.grounded[leg]&&state.pose.grounded[leg])
            assert(hypot(old.feet[leg][0]-state.pose.feet[leg][0],old.feet[leg][1]-state.pose.feet[leg][1])<1e-8);
        if(now==6000000||now==12000000||now==20000000){
            double phase=state.phase;
            command.command.sequence++;
            command.command.data.intent.data.walk.update_sequence=1;
            command.command.data.intent.data.walk.forward=now==6000000?75:-75;
            command.command.data.intent.data.walk.turn=now==6000000?75:-75;
            if(now==20000000)command.command.data.intent.data.walk.speed_percent=0;
            assert(ainekio_v2_walk_accept(&state,&command.command,now));
            assert(state.phase==phase&&state.command_sequence==1);
        }
    }
    assert(state.complete);
    /* Lateral reversal and cross-track correction retain the original running
     * action, phase and planted contacts, then Finish that same action. */
    const char *crab="{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"side_l\",\"steps\":0,\"gait\":\"crab\",\"speed\":50,\"forward\":0,\"turn\":0,\"lateral\":100}";
    for(unsigned initially_steered=0;initially_steered<2;initially_steered++){
    assert(ainekio_control_decode_for_body(crab,strlen(crab),&command)==AINEKIO_DECODE_OK);
    assert(command.command.data.intent.data.walk.lateral==100);
    command.command.data.intent.data.walk.steering=initially_steered!=0;
    state=(ainekio_v2_walk_state_t){0};
    assert(ainekio_v2_walk_accept(&state,&command.command,0));
    uint64_t crab_time=0;
    while(state.phase<5){crab_time+=20000;assert(ainekio_v2_walk_tick(&state,crab_time));}
    assert(state.body_y>0 && fabs(state.body_x)<1e-8);
    double lateral_peak=state.body_y,crab_phase=state.phase;
    command.command.sequence=2;command.command.data.intent.data.walk.update_sequence=1;
    command.command.data.intent.data.walk.steering=true;
    command.command.data.intent.data.walk.forward=25;
    command.command.data.intent.data.walk.lateral=-100;
    assert(ainekio_v2_walk_accept(&state,&command.command,crab_time));
    assert(state.phase==crab_phase&&state.command_sequence==1);
    while(state.phase<crab_phase+8){
        ainekio_v2_walk_pose_t old=state.pose;
        crab_time+=20000;assert(ainekio_v2_walk_tick(&state,crab_time));
        leverage_step(&old,&state.pose);
        for(unsigned leg=0;leg<4;leg++)if(old.grounded[leg]&&state.pose.grounded[leg])
            assert(hypot(old.feet[leg][0]-state.pose.feet[leg][0],old.feet[leg][1]-state.pose.feet[leg][1])<1e-8);
    }
    assert(state.body_y<lateral_peak&&state.body_x>0&&!state.complete);
    command.command.sequence=3;command.command.data.intent.data.walk.speed_percent=0;
    assert(ainekio_v2_walk_accept(&state,&command.command,crab_time));
    while(!state.complete){crab_time+=20000;assert(ainekio_v2_walk_tick(&state,crab_time));}
    assert(state.command_sequence==1);
    }
    printf("84 locomotion envelopes at10/20/30/40 ms, planted XY drift %.9g mm; max output joint change %.6g rad. Finish during lowering and profile matching passed.\n",drift,step);
    leverage_report();
    return 0;
}
