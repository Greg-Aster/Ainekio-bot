#include "ainekio/v2_learning.h"
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

static void measured_target_replay(void)
{
    ainekio_v2_rise_t rise;assert(ainekio_v2_rise_begin(&rise));
    const double level[3]={0};
    ainekio_v2_posture_t reference;
    assert(ainekio_v2_posture_begin(&reference,&rise.stand.frame,&rise.stand.frame,level));
    ainekio_v2_walk_pose_t low=reference.target,high=reference.target;
    low.body[2]-=5.;high.body[2]+=2.;
    assert(ainekio_v2_contact_solve(&low,(const double (*)[3])reference.anchors));
    assert(ainekio_v2_contact_solve(&high,(const double (*)[3])reference.anchors));
    ainekio_v2_frame_t starts[2]={low.frame,low.frame};
    for(unsigned leg=0;leg<4;leg++) {
        starts[1].position[3*leg]=0;
        starts[1].position[3*leg+1]=117;
        starts[1].position[3*leg+2]=-4041;
    }
    for(unsigned initial=0;initial<2;initial++)for(unsigned order=0;order<4;order++) {
        ainekio_v2_posture_t s;
        assert(ainekio_v2_posture_begin_ordered(&s,&starts[initial],&high.frame,level,order));
        double reposition=0.;
        for(unsigned leg=0;leg<4;leg++)reposition=fmax(reposition,
            hypot(s.target.feet[leg][0]-s.start.feet[leg][0],s.target.feet[leg][1]-s.start.feet[leg][1]));
        if(initial==1)assert(reposition>1.);
        ainekio_v2_posture_t before=s;double at=0.;uint16_t moving=0;
        unsigned calls=0;
        assert(!ainekio_v2_posture_next_target_mapped(&s,&at,&moving,reject_second,&calls));
        assert(at==0. && !memcmp(&s,&before,sizeof s));
        unsigned targets=0;double swept_clearance=INFINITY;
        while(at<ainekio_v2_posture_path_length()) {
            ainekio_v2_walk_pose_t previous=s.pose;
            assert(ainekio_v2_posture_next_target(&s,&at,&moving));
            targets++;
            ainekio_v2_walk_pose_t measured;
            assert(ainekio_v2_posture_observe(&s,&s.pose.frame,level,&measured));
            for(unsigned leg=0;leg<4;leg++)
                assert(fabs(measured.sole_height[leg]-s.pose.sole_height[leg])<.002);
            /* The target executor interpolates shaft angles. Check that the
             * airborne placement remains clear between its endpoints, not
             * just at the teacher's lift/placement landmarks. This is FK,
             * not carpet contact, loaded dynamics or a hardware trial. */
            for(unsigned leg=0;leg<4;leg++) {
                if(previous.sole_height[leg]<7.98 || s.pose.sole_height[leg]<7.98)continue;
                for(unsigned sample=0;sample<=20;sample++) {
                    ainekio_v2_frame_t frame=s.pose.frame;
                    for(unsigned j=0;j<12;j++)frame.position[j]=previous.frame.position[j]+
                        (s.pose.frame.position[j]-previous.frame.position[j])*sample/20.;
                    assert(ainekio_v2_posture_observe(&s,&frame,level,&measured));
                    swept_clearance=fmin(swept_clearance,measured.sole_height[leg]);
                }
            }
        }
        assert(targets==17 && moving==0xfff);
        printf("target_replay_start=%u order=%u targets=%u reposition_mm=%g swept_placement_clearance_mm=%g\n",initial,order,targets,reposition,swept_clearance);
        fflush(stdout);
        /* Joint interpolation is not an exact Cartesian horizontal segment.
         * The splayed fixture must remain above the modeled floor throughout
         * its inward step; report its actual minimum separately from the
         * 8mm endpoint target. The in-place fixture retains its full lift. */
        assert(isfinite(swept_clearance) && swept_clearance>(initial==0 ? 7.98 : 0.));
        assert(fabs(s.pose.body[2]-high.body[2])<.002);
    }
}
static void airborne_landing_keeps_horizontal_anchors(void)
{
    ainekio_v2_walk_pose_t stand,raised;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
    float desired[4][3]={{0}},applied[4][3],fit[4];double anchors[4][3];desired[2][2]=15;
    assert(ainekio_v2_nominal_foot_pose(&stand.frame,(const float (*)[3])desired,NULL,NULL,
        &raised,anchors,applied,fit));
    ainekio_v2_posture_t p;double level[3]={0};
    assert(ainekio_v2_posture_begin_landing(&p,&raised.frame,&stand.frame,level));
    unsigned airborne=0;for(unsigned l=0;l<4;l++)airborne+=!p.start.grounded[l];assert(airborne);
    for(unsigned k=0;k<=4;k++) {
        const double coordinate=-1.+k*.25;
        assert(ainekio_v2_posture_sample(&p,coordinate));
        for(unsigned l=0;l<4;l++) {
            for(unsigned a=0;a<2;a++)assert(p.pose.feet[l][a]==p.start.feet[l][a]);
            assert(fabs(p.pose.sole_height[l]+coordinate*p.start.sole_height[l])<1e-9);
        }
    }
    assert(ainekio_v2_posture_arrival_joints(&p,0));
    assert(ainekio_v2_posture_sample(&p,.01)); /* Ordinary step path follows landing. */
}

int main(void)
{
    airborne_landing_keeps_horizontal_anchors();
    transactional_planning();
    measured_target_replay();
    for(unsigned fast=0;fast<2;fast++) {
        entry(0,0,fast);
        entry(.05,0,fast);entry(-.05,0,fast);entry(0,.05,fast);entry(0,-.05,fast);
    }
    return 0;
}
