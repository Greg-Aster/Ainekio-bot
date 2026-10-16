#include "ainekio/v2_posture.h"
#include "walk_data.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

/* Signed distance of the modeled body pivot from each support-triangle edge.
 * This checks the static geometric estimate, not measured mass distribution. */
static double support_margin(const ainekio_v2_walk_pose_t *p)
{
    unsigned legs[3],n=0;
    for(unsigned l=0;l<4;l++)if(p->grounded[l])legs[n++]=l;
    assert(n==3);
    double margin=INFINITY;
    for(unsigned i=0;i<3;i++) {
        const double *a=p->feet[legs[i]],*b=p->feet[legs[(i+1)%3]],*c=p->feet[legs[(i+2)%3]];
        double dx=b[0]-a[0],dy=b[1]-a[1];
        double interior=dx*(c[1]-a[1])-dy*(c[0]-a[0]);
        double distance=(dx*(p->body[1]+v2_walk_pivot[1]-a[1])-
            dy*(p->body[0]+v2_walk_pivot[0]-a[0]))/hypot(dx,dy);
        margin=fmin(margin,copysign(1.,interior)*distance);
    }
    return margin;
}

static void entry(double roll,double pitch)
{
    ainekio_v2_walk_pose_t stand;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
    ainekio_v2_frame_t home=stand.frame;
    for(unsigned l=0;l<4;l++){home.position[3*l]=0;home.position[3*l+1]=117;home.position[3*l+2]=-4041;}
    double euler[3]={roll,pitch,0};ainekio_v2_posture_t s;
    assert(ainekio_v2_posture_begin(&s,&home,&stand.frame,euler));
    double error=0,speed=0,lift[4]={0},margin=INFINITY;
    ainekio_v2_walk_pose_t previous=s.pose;
    for(unsigned n=1;n<=(unsigned)lround(ainekio_v2_posture_duration()*50);n++) {
        double t=n/50.;
        if(!ainekio_v2_posture_sample(&s,t)){fprintf(stderr,"posture failed at %.3f roll %.3f pitch %.3f\n",t,roll,pitch);assert(0);}
        ainekio_v2_walk_pose_t actual=s.pose;
        assert(ainekio_v2_contact_forward(&actual,s.anchors,false));
        unsigned airborne=0;
        for(unsigned l=0;l<4;l++) {
            if(!s.pose.grounded[l])airborne++;
            lift[l]=fmax(lift[l],actual.sole_height[l]-fmax(s.start.sole_height[l],s.target.sole_height[l]));
            for(unsigned j=0;j<2;j++) {
                error=fmax(error,fabs(actual.feet[l][j]-s.pose.feet[l][j]));
                if(previous.grounded[l] && s.pose.grounded[l])
                    assert(fabs(s.pose.feet[l][j]-previous.feet[l][j])<.001);
            }
            assert(fabs(actual.sole_height[l]-s.pose.sole_height[l])<.002);
        }
        assert(airborne<=1);
        if(airborne==1)margin=fmin(margin,support_margin(&s.pose));
        for(unsigned j=0;j<12;j++)speed=fmax(speed,fabs(s.pose.frame.position[j]-previous.frame.position[j])*.5);
        previous=s.pose;
    }
    for(unsigned l=0;l<4;l++)assert(lift[l]>7.99);
    assert(error<.002);
    assert(!memcmp(s.pose.frame.position,stand.frame.position,sizeof(stand.frame.position)));
    printf("roll=%g pitch=%g anchor_error_mm=%g peak_joint_deg_s=%g support_margin_mm=%g\n",roll,pitch,error,speed,margin);
    assert(margin>0.);
}
int main(void)
{
    entry(0,0);
    entry(.05,0);entry(-.05,0);entry(0,.05);entry(0,-.05);
    return 0;
}
