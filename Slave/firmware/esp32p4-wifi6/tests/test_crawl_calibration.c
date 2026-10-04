/* Offline production Crawl and pulse mapping with the mounted servo profile. */
#include "joint_calibration.h"
#include "ainekio/v2_walk.h"
#include <assert.h>
#include <stdio.h>

static ainekio_p4_joint_config_t joints[12];
static unsigned minimum=65535,maximum;
static void check(ainekio_v2_walk_state_t *s,uint64_t now)
{
    assert(ainekio_v2_walk_tick(s,now));
    uint16_t pulses[12];assert(ainekio_p4_joint_map_frame(joints,&s->pose.frame,pulses));
    for(unsigned i=0;i<12;i++) {
        if(pulses[i]<400||pulses[i]>2900)
            fprintf(stderr,"Crawl dir=%u time=%llu phase=%g joint=%u pulse=%u\n",s->direction,(unsigned long long)now,s->phase,i,pulses[i]);
        assert(pulses[i]>=400&&pulses[i]<=2900);
        if(pulses[i]<minimum)minimum=pulses[i];
        if(pulses[i]>maximum)maximum=pulses[i];
    }
}
static ainekio_command_t command(unsigned direction)
{
    ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
    c.data.intent.kind=AINEKIO_INTENT_WALK;
    c.data.intent.data.walk.gait=AINEKIO_GAIT_CRAWL;
    c.data.intent.data.walk.direction=(ainekio_walk_direction_t)direction;
    c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
    return c;
}
static void update(ainekio_v2_walk_state_t *s,ainekio_command_t *c,unsigned speed,uint64_t now)
{
    c->sequence++;c->data.intent.data.walk.update_sequence=1;
    c->data.intent.data.walk.controls=1;c->data.intent.data.walk.speed_percent=speed;
    assert(ainekio_v2_walk_accept(s,c,now));
}
int main(void)
{
    const unsigned home[12]={1600,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
    assert(ainekio_p4_joint_defaults(joints));
    for(unsigned i=0;i<12;i++){joints[i].home_us=home[i];joints[i].invert=(i/3)%2==0;}
    assert(ainekio_v2_joint_speed_set(1000));
    const unsigned speeds[]={1,25,50,75,100};
    const unsigned intervals[]={10000,20000,40000};
    for(unsigned d=0;d<4;d++)for(unsigned dt=0;dt<3;dt++)for(unsigned mode=0;mode<8;mode++) {
        ainekio_command_t c=command(d);
        if(mode<5)c.data.intent.data.walk.speed_percent=speeds[mode];
        else {c.data.intent.data.walk.controls=2;c.data.intent.data.walk.stride_percent=100;c.data.intent.data.walk.motion_rate=(float[]){.25F,1.F,3.F}[mode-5];}
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        unsigned stage=0;
        for(uint64_t now=intervals[dt];now<120000000&&!s.complete;now+=intervals[dt]) {
            check(&s,now);
            if(stage<4&&s.phase>=2.+2.*stage){update(&s,&c,(unsigned[]){25,100,1,0}[stage],now);stage++;}
        }
        assert(s.complete);
    }
    /* Finish during lowering, then throughout a steady cycle at both rate extremes. */
    for(unsigned d=0;d<4;d++)for(unsigned rate=0;rate<2;rate++)for(unsigned stop=0;stop<37;stop++) {
        ainekio_command_t c=command(d);c.data.intent.data.walk.controls=2;
        c.data.intent.data.walk.stride_percent=100;c.data.intent.data.walk.motion_rate=rate?3.F:.25F;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        for(uint64_t now=20000;now<120000000&&!s.complete;now+=20000) {
            check(&s,now);
            if(!s.stopping&&(stop<21?now>=stop*100000ULL:s.phase>=4.+(stop-21)/16.))update(&s,&c,0,now);
        }
        assert(s.complete);
    }
    printf("Crawl entry, four directions, speed changes and Finish: %u-%u us.\n",minimum,maximum);
}
