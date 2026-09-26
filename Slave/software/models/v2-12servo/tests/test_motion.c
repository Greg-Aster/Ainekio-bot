#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static ainekio_command_t decode(const char *text)
{
    ainekio_control_message_t m;
    assert(ainekio_control_decode_with_walk_controls(text,strlen(text),&m)==AINEKIO_DECODE_OK);
    return m.command;
}
int main(void)
{
    ainekio_v2_walk_controls_t c;
    ainekio_v2_walk_pose_t stand;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
    assert(stand.body[2]==-2.); /* Named Stand retains its reviewed height. */
    assert(ainekio_v2_walk_controls(25,&c)&&c.stride_percent==50&&c.motion_rate==1);
    assert(ainekio_v2_walk_controls(50,&c)&&c.stride_percent==100&&c.motion_rate==1);
    assert(ainekio_v2_walk_controls(75,&c)&&c.stride_percent==100&&c.motion_rate==1.5);
    assert(ainekio_v2_walk_controls(100,&c)&&c.stride_percent==100&&c.motion_rate==2);
    assert(!ainekio_v2_walk_controls(NAN,&c));assert(!ainekio_v2_walk_controls(101,&c));
    assert(!ainekio_v2_walk_hardware_qualified);
    assert(!strcmp(ainekio_v2_joints[0].name,"rear_left_shoulder"));
    assert(!strcmp(ainekio_v2_joints[11].name,"front_right_crank"));
    ainekio_control_message_t message;
    const char *extended="{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":3,\"speed\":100}";
    assert(ainekio_control_decode(extended,strlen(extended),&message)!=AINEKIO_DECODE_OK);
    ainekio_command_t command=decode(extended);ainekio_v2_walk_state_t s={0};
    assert(ainekio_v2_walk_accept(&s,&command,0));assert(!ainekio_v2_walk_accept(&s,&command,0));
    double drift=0,max_step=0;bool updated=false;
    for(unsigned t=10000;t<=30000000;t+=10000) {
        ainekio_v2_walk_pose_t old=s.pose;
        assert(ainekio_v2_walk_tick(&s,t));
        assert(s.phase>=old.phase);
        for(unsigned i=0;i<4;i++) {
            if(old.grounded[i]&&s.pose.grounded[i])drift=fmax(drift,fabs(old.feet[i][0]-s.pose.feet[i][0]));
            for(unsigned j=0;j<3;j++)max_step=fmax(max_step,fabs(old.joints[i][j]-s.pose.joints[i][j]));
        }
        if(t==3500000){
            command=decode("{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":1,\"speed\":25,\"update\":99}");
            assert(!ainekio_v2_walk_accept(&s,&command,t));command.data.intent.data.walk.update_sequence=1;
            double phase=s.phase,end=s.end_phase,x=s.body_x;
            assert(ainekio_v2_walk_accept(&s,&command,t));assert(s.phase==phase&&s.end_phase==end&&s.body_x==x);
            assert(!ainekio_v2_walk_accept(&s,&command,t));updated=true;
        }
        if(s.complete)break;
    }
    assert(updated&&s.complete&&drift<1e-10&&max_step<.3);
    for(unsigned i=0;i<4;i++)assert(s.pose.grounded[i]&&s.pose.sole_height[i]==0);
    for(unsigned j=0;j<12;j++)assert(s.pose.frame.velocity[j]==0&&s.pose.frame.acceleration[j]==0);
    assert(ainekio_v2_walk_begin(&s,3,(ainekio_v2_walk_controls_t){100,1},0));
    assert(!ainekio_v2_walk_tick(&s,40001)&&s.failed);
    assert(!ainekio_v2_walk_tick(&s,40002));
    /* Reversal while ramping keeps current parameters; latest target wins. */
    for(unsigned speed=0;speed<=100;speed+=25){
        assert(ainekio_v2_walk_controls(speed,&c));assert(ainekio_v2_walk_begin(&s,1,c,0));
        for(unsigned t=10000;t<=30000000&&!s.complete;t+=10000)assert(ainekio_v2_walk_tick(&s,t));
        assert(s.complete);
    }
    printf("Automatic/manual walking, planted anchors, active-command updates, finish and stale-clock rejection passed; max joint step %.6g rad.\n",max_step);
    return 0;
}
