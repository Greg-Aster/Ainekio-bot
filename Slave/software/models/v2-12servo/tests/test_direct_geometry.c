/* Exercise the actual direct solver, including its reach inequalities. */
#include "../walk_kinematics.c"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    float along,height;
    const float low=(38.f-24.f)*(38.f-24.f),high=(38.f+24.f)*(38.f+24.f);
    assert(!circle(nextafterf(low,0.f),24,38,&along,&height));
    assert(!circle(nextafterf(high,INFINITY),24,38,&along,&height));
    assert(circle(nextafterf(low,INFINITY),24,38,&along,&height));
    assert(circle(nextafterf(high,0.f),24,38,&along,&height));
    assert(!circle(0,24,38,&along,&height));
    assert(!circle(NAN,24,38,&along,&height));
    assert(!circle(INFINITY,24,38,&along,&height));
    ainekio_v2_walk_state_t state={0};
    assert(ainekio_v2_locomotion_begin(&state,AINEKIO_WALK_FORWARD,false,0,
        (ainekio_v2_walk_controls_t){100,1},0));
    for(unsigned invalid=0;invalid<5;invalid++) {
        ainekio_v2_walk_pose_t pose=state.pose;
        if(invalid==0)pose.feet[3][0]+=1000; /* Last leg failure is atomic too. */
        if(invalid==1)pose.sole_height[2]=-1000;
        if(invalid==2)pose.body[0]=NAN;
        if(invalid==3)pose.joints[1][2]=INFINITY;
        if(invalid==4)pose.euler[1]=NAN;
        ainekio_v2_walk_pose_t before=pose;
        assert(!ainekio_v2_walk_solve(&pose));
        assert(!memcmp(&before,&pose,sizeof(pose)));
    }
    puts("Explicit unreachable-circle rejection and atomic failed frames passed.");
}
