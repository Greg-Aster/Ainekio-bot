#include "ainekio/v2_motion.h"
#include "ainekio/trajectory.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void boundary(uint8_t cycles, uint64_t time)
{
    ainekio_v2_frame_t before, at, after;
    assert(ainekio_v2_walk_sample(cycles,time-1,&before));
    assert(ainekio_v2_walk_sample(cycles,time,&at));
    assert(ainekio_v2_walk_sample(cycles,time+1,&after));
    for (unsigned j=0; j<12; ++j) {
        assert(fabsf(before.position[j]-at.position[j]) < 0.1F);
        assert(fabsf(after.position[j]-at.position[j]) < 0.1F);
        assert(fabsf(before.velocity[j]-at.velocity[j]) < 5.0F);
        assert(fabsf(after.velocity[j]-at.velocity[j]) < 5.0F);
    }
}

int main(void)
{
    float p,v,a;
    assert(ainekio_trajectory_sample(0,100,100,100,1,.25F,&p,&v,&a));
    assert(p==25 && v==100 && a==0);
    assert(!ainekio_trajectory_sample(0,100,0,0,0,0,&p,&v,&a));
    assert(!ainekio_trajectory_sample(0,100,0,0,1,1.01F,&p,&v,&a));
    assert(!ainekio_trajectory_sample(NAN,100,0,0,1,.5F,&p,&v,&a));
    ainekio_command_t command = {.kind=AINEKIO_COMMAND_INTENT,
        .data.intent={.kind=AINEKIO_INTENT_WALK, .data.walk={AINEKIO_WALK_FORWARD,3}}};
    uint8_t cycles=0;
    assert(ainekio_v2_walk_request(&command,&cycles) && cycles==3);
    command.data.intent.data.walk.direction=AINEKIO_WALK_BACKWARD;
    assert(!ainekio_v2_walk_request(&command,&cycles));
    command.data.intent.data.walk.direction=AINEKIO_WALK_FORWARD;
    command.data.intent.data.walk.steps=0;
    assert(!ainekio_v2_walk_request(&command,&cycles));
    command.data.intent.data.walk.steps=11;
    assert(!ainekio_v2_walk_request(&command,&cycles));
    command.data.intent.kind=AINEKIO_INTENT_STAND;
    assert(!ainekio_v2_walk_request(&command,&cycles));
    assert(!ainekio_v2_walk_hardware_qualified);
    assert(!strcmp(ainekio_v2_joints[0].name,"rear_left_shoulder"));
    assert(!strcmp(ainekio_v2_joints[11].name,"front_right_crank"));
    ainekio_v2_frame_t f,g;
    assert(!ainekio_v2_walk_sample(0,0,&f));
    assert(!ainekio_v2_walk_sample(11,0,&f));
    assert(ainekio_v2_walk_duration_us(1)==UINT64_C(24400000));
    assert(ainekio_v2_walk_duration_us(10)==UINT64_C(60400000));
    assert(ainekio_v2_walk_sample(3,0,&f) && f.phase==AINEKIO_V2_ENTRY);
    for (unsigned j=0; j<12; ++j) assert(f.position[j]==0 && f.velocity[j]==0);
    for (uint64_t t=0; t<UINT64_C(4000000); t+=1003) {
        assert(ainekio_v2_walk_loop_sample(t,&f));
        assert(ainekio_v2_walk_loop_sample(t+UINT64_C(4000000),&g));
        assert(!memcmp(f.position,g.position,sizeof(f.position)));
        assert(!memcmp(f.velocity,g.velocity,sizeof(f.velocity)));
        for (unsigned j=0; j<12; ++j) assert(isfinite(f.position[j]) && isfinite(f.acceleration[j]));
    }
    for (uint64_t t=UINT64_C(12200000); t<=UINT64_C(24200000); t+=UINT64_C(4000000)) boundary(3,t);
    assert(ainekio_v2_walk_sample(3,UINT64_C(16200000),&f));
    assert(f.phase==AINEKIO_V2_LOOP && f.cycle==1);
    assert(ainekio_v2_walk_sample(3,UINT64_C(24200000),&f) && f.phase==AINEKIO_V2_EXIT);
    assert(ainekio_v2_walk_sample(3,UINT64_MAX,&f) && f.phase==AINEKIO_V2_COMPLETE);
    for (unsigned j=0; j<12; ++j) assert(f.velocity[j]==0 && f.acceleration[j]==0);
    /* The recorded final pose is not silently replaced by CAD zero. */
    assert(fabsf(f.position[11]) > 100);
    puts("V2 request mapping, timing, 12-joint sampling and phase continuity passed.");
    return 0;
}
