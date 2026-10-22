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

static void entry(double roll,double pitch,bool fast)
{
    ainekio_v2_walk_pose_t stand;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
    ainekio_v2_frame_t home=stand.frame;
    for(unsigned l=0;l<4;l++){home.position[3*l]=0;home.position[3*l+1]=117;home.position[3*l+2]=-4041;}
    double euler[3]={roll,pitch,0};ainekio_v2_posture_t s;
    assert(ainekio_v2_posture_begin(&s,&home,&stand.frame,euler));
    double error=0,speed=0,lift[4]={0},margin=INFINITY;
    ainekio_v2_walk_pose_t previous=s.pose;
    unsigned n=0;double t=0.;
    while(t<ainekio_v2_posture_path_length()) {
        n++;
        bool ok=fast?ainekio_v2_posture_advance(&s,&t,.02):ainekio_v2_posture_sample(&s,t=n/50.);
        if(!ok){fprintf(stderr,"posture failed at %.3f roll %.3f pitch %.3f\n",t,roll,pitch);assert(0);}
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
    printf("fast=%u wall_s=%g roll=%g pitch=%g anchor_error_mm=%g peak_joint_deg_s=%g support_margin_mm=%g\n",fast,n/50.,roll,pitch,error,speed,margin);
    if(fast)assert(n<75);
    assert(margin>0.);
}
static bool reject_second(ainekio_v2_frame_t *frame,void *context)
{
    (void)frame;
    return ++*(unsigned *)context<2;
}
static void transactional_planning(void)
{
    ainekio_v2_rise_t rise;assert(ainekio_v2_rise_begin(&rise));
    const double level[3]={0};
    for(unsigned joint=0;joint<12;joint++) {
        unsigned offset=ainekio_v2_posture_order_for_joints(1U<<joint,0);
        ainekio_v2_posture_t s={.order_offset=offset};
        assert(ainekio_v2_posture_arrival_joints(&s,.9)==(7U<<(3*(joint/3))));
    }
    for(unsigned order=0;order<4;order++) {
        ainekio_v2_posture_t s;
        assert(ainekio_v2_posture_begin_ordered(&s,&rise.crouch.frame,&rise.stand.frame,level,order));
        ainekio_v2_posture_t before=s;double progress=0.;unsigned calls=0;
        assert(!ainekio_v2_posture_advance_mapped(&s,&progress,.02,reject_second,&calls));
        assert(calls==2 && progress==0. && !memcmp(&s,&before,sizeof s));
        unsigned seen=0;
        while(progress<ainekio_v2_posture_path_length()) {
            assert(ainekio_v2_posture_advance(&s,&progress,.02));
            uint16_t mask=ainekio_v2_posture_arrival_joints(&s,progress);
            if(mask && mask!=0xfff) {
                unsigned leg=0;while(!(mask&(1U<<(3*leg))))leg++;
                assert(mask==(7U<<(3*leg)));seen|=1U<<leg;
            }
        }
        assert(seen==15 && ainekio_v2_posture_arrival_joints(&s,progress)==0xfff);
        assert(!memcmp(s.pose.frame.position,rise.stand.frame.position,sizeof s.pose.frame.position));
    }
}
int main(void)
{
    transactional_planning();
    for(unsigned fast=0;fast<2;fast++) {
        entry(0,0,fast);
        entry(.05,0,fast);entry(-.05,0,fast);entry(0,.05,fast);entry(0,-.05,fast);
    }
    return 0;
}
