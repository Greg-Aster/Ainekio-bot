#include "ainekio/v2_posture.h"
#include "walk_data.h"
#include <math.h>
#include <string.h>

/* Geometric stage coordinates: shift, lift, translate while clear, lower.
 * They define path shape; posture_advance assigns time by angular travel. */
static const double shift_s=.6,lift_s=.3,place_s=.5,lower_s=.3,settle_s=1.2;
static const double lift_mm=8.;
static const unsigned order[4]={0,3,1,2};
static double clamp(double u){return fmax(0.,fmin(1.,u));}
static double fraction(double u){return clamp(u);}
bool ainekio_v2_rise_begin(ainekio_v2_rise_t *s)
{
    if(!s)return false;
    *s=(ainekio_v2_rise_t){0};
    if(!ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&s->stand) ||
       !ainekio_v2_contact_forward(&s->stand,s->anchors,true))return false;
    for(unsigned l=0;l<4;l++)s->stand.grounded[l]=true;
    s->crouch=s->stand;
    s->crouch.body[2]-=25.;
    if(!ainekio_v2_contact_solve(&s->crouch,(const double (*)[3])s->anchors))return false;
    s->pose=s->crouch;
    return true;
}
bool ainekio_v2_rise_sample(ainekio_v2_rise_t *s,double front_fraction,double rear_fraction)
{
    if(!s||!isfinite(front_fraction)||!isfinite(rear_fraction))return false;
    ainekio_v2_walk_pose_t p=s->crouch;
    memcpy(p.joints,s->pose.joints,sizeof(p.joints));
    const double height=s->stand.body[2]-s->crouch.body[2];
    const double front=fraction(front_fraction)*height,rear=fraction(rear_fraction)*height;
    /* Source leg order is physical front pair, rear pair (CAD RL/RR/FL/FR).
     * A slight body pitch expresses the delayed rear lift without splicing
     * incompatible leg frames or moving the planted contact targets. */
    const double fx=.5*(v2_walk_legs[0].shoulder_translation[0]+v2_walk_legs[1].shoulder_translation[0]);
    const double rx=.5*(v2_walk_legs[2].shoulder_translation[0]+v2_walk_legs[3].shoulder_translation[0]);
    const double fz=.5*(v2_walk_legs[0].shoulder_translation[2]+v2_walk_legs[1].shoulder_translation[2]);
    p.euler[1]=asin((rear-front)/(fx-rx));
    p.body[2]+=front+sin(p.euler[1])*(fx-v2_walk_pivot[0])-
        (cos(p.euler[1])-1.)*(fz-v2_walk_pivot[2]);
    if(!ainekio_v2_contact_solve(&p,(const double (*)[3])s->anchors))return false;
    s->pose=p;
    return true;
}
static double step_s(void){return shift_s+lift_s+place_s+lower_s;}
double ainekio_v2_posture_path_length(void){return 4.*step_s()+settle_s;}
static void joints(ainekio_v2_walk_pose_t *p,const ainekio_v2_frame_t *f)
{
    for(unsigned l=0;l<4;l++)for(unsigned j=0;j<3;j++)
        p->joints[l][j]=f->position[3*(l<2?l+2:l-2)+j]*0.00017453292519943296;
    p->frame=*f;
}
bool ainekio_v2_posture_begin(ainekio_v2_posture_t *s,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,const double euler[3])
{
    if(!s||!from||!to||!euler)return false;
    *s=(ainekio_v2_posture_t){.from=*from,.to=*to};
    joints(&s->start,from);joints(&s->target,to);
    memcpy(s->start.euler,euler,sizeof(s->start.euler));
    if(!ainekio_v2_contact_forward(&s->start,s->anchors,true)||
       !ainekio_v2_contact_forward(&s->target,s->anchors,false))return false;
    double bottom=INFINITY,goal=INFINITY;
    for(unsigned l=0;l<4;l++) {
        bottom=fmin(bottom,s->start.sole_height[l]);goal=fmin(goal,s->target.sole_height[l]);
        s->start.grounded[l]=s->target.grounded[l]=true;
    }
    s->start.body[2]=-bottom;s->target.body[2]=-goal;
    if(!ainekio_v2_contact_forward(&s->start,s->anchors,false)||
       !ainekio_v2_contact_forward(&s->target,s->anchors,false))return false;
    double feet[4][3];memcpy(feet,s->start.feet,sizeof(feet));
    for(unsigned k=0;k<4;k++) {
        unsigned moving=order[k];
        for(unsigned axis=0;axis<2;axis++) {
            double all=0.,tripod=0.;
            for(unsigned l=0;l<4;l++){all+=feet[l][axis]/4.;if(l!=moving)tripod+=feet[l][axis]/3.;}
            /* Shift estimated COM toward the three supporting feet. */
            s->shift[k][axis]=.75*all+.25*tripod-v2_walk_pivot[axis];
        }
        memcpy(feet[moving],s->target.feet[moving],sizeof(feet[moving]));
    }
    s->pose=s->start;return true;
}
bool ainekio_v2_posture_sample(ainekio_v2_posture_t *s,double elapsed)
{
    if(!s||!isfinite(elapsed)||elapsed<0.)return false;
    if(elapsed==0.){s->pose=s->start;return true;}
    if(elapsed>=ainekio_v2_posture_path_length()){s->pose=s->target;return true;}
    ainekio_v2_walk_pose_t p=s->start;
    memcpy(p.joints,s->pose.joints,sizeof(p.joints));
    const unsigned step=(unsigned)fmin(4.,floor(elapsed/step_s()));
    double local=elapsed-step*step_s();
    for(unsigned l=0;l<4;l++)p.grounded[l]=true;
    for(unsigned k=0;k<step;k++) {
        unsigned l=order[k];memcpy(p.feet[l],s->target.feet[l],sizeof(p.feet[l]));
        p.sole_height[l]=s->target.sole_height[l];
    }
    double u=fraction(elapsed/(4.*step_s()));
    p.body[2]=s->start.body[2]+u*(s->target.body[2]-s->start.body[2]);
    for(unsigned j=0;j<3;j++)p.euler[j]=(1.-u)*s->start.euler[j];
    if(step<4) {
        const unsigned l=order[step];
        for(unsigned axis=0;axis<2;axis++) {
            double previous=step?s->shift[step-1][axis]:0.;
            p.body[axis]=previous+fraction(local/shift_s)*(s->shift[step][axis]-previous);
        }
        double swing=local-shift_s;
        if(swing>0.) {
            double xy=fraction((swing-lift_s)/place_s);
            for(unsigned axis=0;axis<2;axis++)p.feet[l][axis]=s->start.feet[l][axis]+xy*(s->target.feet[l][axis]-s->start.feet[l][axis]);
            double clear=fmax(s->start.sole_height[l],s->target.sole_height[l])+lift_mm;
            if(swing<lift_s)p.sole_height[l]=s->start.sole_height[l]+fraction(swing/lift_s)*(clear-s->start.sole_height[l]);
            else if(swing<lift_s+place_s)p.sole_height[l]=clear;
            else p.sole_height[l]=clear+fraction((swing-lift_s-place_s)/lower_s)*(s->target.sole_height[l]-clear);
            p.grounded[l]=swing>=lift_s+place_s+lower_s;
        }
    } else for(unsigned axis=0;axis<2;axis++)p.body[axis]=(1.-fraction(local/settle_s))*s->shift[3][axis];
    if(!ainekio_v2_contact_solve(&p,(const double (*)[3])s->anchors))return false;
    s->pose=p;return true;
}

bool ainekio_v2_posture_advance(ainekio_v2_posture_t *s,double *progress,double seconds)
{
    if(!s||!progress||!isfinite(seconds)||seconds<0.)return false;
    const double end=ainekio_v2_posture_path_length();
    double remaining=seconds;
    while(remaining>0. && *progress<end) {
        double event=end;
        const double landmarks[4]={shift_s,shift_s+lift_s,
            shift_s+lift_s+place_s,step_s()};
        for(unsigned leg=0;leg<4;leg++)for(unsigned k=0;k<4;k++) {
            double at=leg*step_s()+landmarks[k];
            if(at>*progress+1e-9)event=fmin(event,at);
        }
        double segment=fmin(.01,event-*progress);
        ainekio_v2_posture_t next=*s;
        if(!ainekio_v2_posture_sample(&next,*progress+segment))return false;
        double distance=0.;
        for(unsigned j=0;j<12;j++)distance=fmax(distance,
            fabs(next.pose.frame.position[j]-s->pose.frame.position[j])/100.);
        double duration=distance/ainekio_v2_joint_speed_default();
        if(duration<=remaining) {
            *s=next;*progress+=segment;remaining-=duration;
            if(*progress>=event-1e-9){*progress=event;return true;}
        } else {
            segment*=remaining/duration;
            if(!ainekio_v2_posture_sample(s,*progress+segment))return false;
            *progress+=segment;remaining=0.;
        }
    }
    return true;
}

bool ainekio_v2_posture_shoulder_engaged(double progress,unsigned model_leg)
{
    unsigned source=model_leg<2?model_leg+2:model_leg-2;
    for(unsigned k=0;k<4;k++)if(order[k]==source)
        return progress>=k*step_s()+shift_s+lift_s;
    return false;
}

bool ainekio_v2_posture_landmark(double progress)
{
    const double landmarks[4]={shift_s,shift_s+lift_s,shift_s+lift_s+place_s,step_s()};
    for(unsigned leg=0;leg<4;leg++)for(unsigned k=0;k<4;k++)
        if(fabs(progress-(leg*step_s()+landmarks[k]))<1e-9)return true;
    return fabs(progress-ainekio_v2_posture_path_length())<1e-9;
}
