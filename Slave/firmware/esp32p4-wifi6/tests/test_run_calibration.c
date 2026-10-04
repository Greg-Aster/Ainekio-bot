/* Production Run planner and pulse mapper with the installed mounting profile.
 * Offline commands only: no robot or servo I/O. */
#include "joint_calibration.h"
#include "ainekio/v2_walk.h"
#include <assert.h>
#include <stdio.h>

static ainekio_p4_joint_config_t joints[12];
static unsigned minimum=65535,maximum;
static void check(ainekio_v2_walk_state_t *s,uint64_t now,unsigned family,unsigned speed)
{
    assert(ainekio_v2_walk_tick(s,now));
    uint16_t pulses[12];assert(ainekio_p4_joint_map_frame(joints,&s->pose.frame,pulses));
    for(unsigned i=0;i<12;i++) {
        if(pulses[i]<400||pulses[i]>2900)
            fprintf(stderr,"Run pulse: family=%u dir=%u speed=%u time=%llu phase=%g blend=%g joint=%u pulse=%u\n",family,s->direction,speed,(unsigned long long)now,s->phase,s->pose.run_blend,i,pulses[i]);
        assert(pulses[i]>=400&&pulses[i]<=2900);
        if(pulses[i]<minimum)minimum=pulses[i];
        if(pulses[i]>maximum)maximum=pulses[i];
    }
}
int main(void)
{
    const unsigned home[12]={1600,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
    assert(ainekio_p4_joint_defaults(joints));
    for(unsigned i=0;i<12;i++){joints[i].home_us=home[i];joints[i].invert=(i/3)%2==0;}
    assert(ainekio_v2_joint_speed_set(1000));
    const unsigned speeds[]={101,125,150,175,200};
    for(unsigned dir=0;dir<4;dir++)for(unsigned family=0;family<3;family++)for(unsigned n=0;n<(family==2?1:5);n++) {
        unsigned speed=speeds[n];
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;c.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;
        c.data.intent.data.walk.gait=family?AINEKIO_GAIT_RUN:AINEKIO_GAIT_WALK;
        c.data.intent.data.walk.controls=family==2?2:1;c.data.intent.data.walk.speed_percent=family?speed:100;
        c.data.intent.data.walk.stride_percent=100;c.data.intent.data.walk.motion_rate=3;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=20000;now<70000000&&!s.complete;now+=20000) {
            check(&s,now,family,speed);
            if(now==8000000||now==22000000||now==30000000||now==43000000) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;c.data.intent.data.walk.controls=1;
                c.data.intent.data.walk.speed_percent=now==8000000?speed:now==22000000?75:now==30000000?200:0;
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
    /* Slider crosses into Run during Walk startup, including before tick one. */
    for(unsigned delay=0;delay<=2000;delay+=100) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=0;now<45000000&&!s.complete;now+=20000) {
            check(&s,now,3,200);
            if(now==delay*1000ULL||now==30000000) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;c.data.intent.data.walk.speed_percent=now==30000000?0:200;
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
    /* Finish at 32 points through a full cycle in each Run direction/family. */
    for(unsigned dir=0;dir<4;dir++)for(unsigned family=0;family<2;family++)for(unsigned stop=0;stop<32;stop++) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=200;
        c.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;c.data.intent.data.walk.gait=family?AINEKIO_GAIT_RUN:AINEKIO_GAIT_WALK;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=20000;now<60000000&&!s.complete;now+=20000) {
            check(&s,now,family,200);
            if(!s.stopping&&s.phase>=9.+stop/32.) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;c.data.intent.data.walk.speed_percent=0;
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
    printf("Run entry, steady paths, speed changes, Walk returns and Finish: %u-%u us.\n",minimum,maximum);
}
