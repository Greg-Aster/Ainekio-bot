/* Production Walk/Run planner and pulse mapper with the installed mounting profile.
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
        if(family==5 && i%3==2) {
            unsigned normalized=joints[i].invert?pulses[i]:3300-pulses[i];
            if(normalized>2800)fprintf(stderr,"Crank housing endpoint: dir=%u speed=%u phase=%g joint=%u pulse=%u\n",s->direction,speed,s->phase,i,pulses[i]);
            assert(normalized<=2800);
        }
        if(pulses[i]<minimum)minimum=pulses[i];
        if(pulses[i]>maximum)maximum=pulses[i];
    }
}
/* The owner supplied real pulse endpoints. Check emitted targets, not just
 * mathematical extrema between frames, across supported output cadences. */
static void check_reindexed_walk_endpoints(void)
{
    const unsigned rates[]={25,50,100};
    for(unsigned direction=0;direction<2;direction++)for(unsigned rate=0;rate<3;rate++) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.direction=(ainekio_walk_direction_t)direction;
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
        ainekio_v2_walk_state_t state={0};assert(ainekio_v2_walk_accept(&state,&c,0));
        unsigned low=65535,high=0;
        for(uint64_t now=1000000/rates[rate];now<=16000000;now+=1000000/rates[rate]) {
            assert(ainekio_v2_walk_tick(&state,now));
            uint16_t pulses[12];assert(ainekio_p4_joint_map_frame(joints,&state.pose.frame,pulses));
            for(unsigned joint=2;joint<12;joint+=3) {
                unsigned value=joints[joint].invert?pulses[joint]:3300-pulses[joint];
                if(value>2800 || (state.phase>4. && value<1600))
                    fprintf(stderr,"Endpoint: dir=%u hz=%u phase=%g joint=%u pulse=%u\n",direction,rates[rate],state.phase,joint,pulses[joint]);
                assert(value<=2800);
                if(state.phase>4.)assert(value>=1600);
            }
            if(state.phase>4.){if(pulses[2]<low)low=pulses[2];if(pulses[2]>high)high=pulses[2];}
        }
        assert(low==1600 && high==2800);
    }
}
int main(void)
{
    const unsigned home[12]={1500,2444,2800,1670,856,500,1670,2444,2800,1760,856,500};
    assert(ainekio_p4_joint_defaults(joints));
    for(unsigned i=0;i<12;i++){joints[i].home_us=home[i];joints[i].invert=i%3==0?(i==3||i==6):(i/3)%2==0;}
    /* Provisional photo-derived mounting after owner reindexed all cranks. */
    for(unsigned i=2;i<12;i+=3)joints[i].home_cd=-11768;
    assert(ainekio_v2_joint_speed_set(1000));
    check_reindexed_walk_endpoints();
    /* Match the independent geometry validator's timed updates as well as
     * phase-based tests: a command can arrive midway through Run rephasing. */
    for(unsigned dir=0;dir<4;dir++)for(unsigned hz=25;hz<=50;hz+=25) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        const unsigned at[]={2000000,4000000,6000000,8500000};
        const unsigned speed[]={200,75,200,0};unsigned event=0;
        for(uint64_t now=1000000/hz;now<=20000000&&!s.complete;now+=1000000/hz) {
            check(&s,now,7,(unsigned)c.data.intent.data.walk.speed_percent);
            if(event<4 && now>=at[event]) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;
                c.data.intent.data.walk.speed_percent=speed[event++];
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
    /* Every Body Control Walk speed, both travel directions, including entry
     * and Finish. These are offline reviewed-window checks, not runtime caps. */
    for(unsigned dir=0;dir<2;dir++)for(unsigned speed=1;speed<=100;speed++) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=speed;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=20000;now<30000000&&!s.complete;now+=20000) {
            check(&s,now,5,speed);
            if(!s.stopping&&s.phase>=6.) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;
                c.data.intent.data.walk.speed_percent=0;
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
    /* Historical owner failure: full curve, Speed 50 -> 89 -> 145. */
    for(unsigned hz=50;hz<=100;hz+=50) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=50;
        c.data.intent.data.walk.steering=true;
        c.data.intent.data.walk.forward=100;c.data.intent.data.walk.turn=100;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=1000000/hz;now<=90000000&&!s.complete;now+=1000000/hz) {
            check(&s,now,6,(unsigned)c.data.intent.data.walk.speed_percent);
            if(now==21000000||now==32000000||now==55000000) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;
                c.data.intent.data.walk.speed_percent=now==21000000?89:now==32000000?145:0;
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
    /* Taller Walk's complete curved path must fit the mounted mapping too.
     * Checking only straight stance endpoints missed a swing pulse excursion. */
    for(unsigned reverse=0;reverse<2;reverse++)for(unsigned negative=0;negative<2;negative++)
    for(unsigned turn=50;turn<=100;turn+=50)for(unsigned hz=50;hz<=100;hz+=50)
    for(unsigned speed=100;speed<=200;speed+=50) {
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=speed;
        c.data.intent.data.walk.steering=true;
        c.data.intent.data.walk.forward=reverse?-100:100;
        c.data.intent.data.walk.turn=negative?-(float)turn:(float)turn;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=1000000/hz;now<=40000000&&!s.complete;now+=1000000/hz) {
            check(&s,now,4,speed);
            if(now==20000000) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;
                c.data.intent.data.walk.speed_percent=0;
                assert(ainekio_v2_walk_accept(&s,&c,now));
            }
        }
        assert(s.complete);
    }
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
