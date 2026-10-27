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
    return ainekio_v2_posture_begin_ordered(s,from,to,euler,0);
}
bool ainekio_v2_posture_begin_ordered(ainekio_v2_posture_t *s,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,const double euler[3],
    unsigned order_offset)
{
    if(!s||!from||!to||!euler)return false;
    *s=(ainekio_v2_posture_t){.from=*from,.to=*to,.order_offset=order_offset%4};
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
        unsigned moving=order[(k+s->order_offset)%4];
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
        unsigned l=order[(k+s->order_offset)%4];memcpy(p.feet[l],s->target.feet[l],sizeof(p.feet[l]));
        p.sole_height[l]=s->target.sole_height[l];
    }
    double u=fraction(elapsed/(4.*step_s()));
    p.body[2]=s->start.body[2]+u*(s->target.body[2]-s->start.body[2]);
    for(unsigned j=0;j<3;j++)p.euler[j]=(1.-u)*s->start.euler[j];
    if(step<4) {
        const unsigned l=order[(step+s->order_offset)%4];
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

static bool sample_mapped(ainekio_v2_posture_t *s,double progress,
    ainekio_v2_posture_fit_t fit,void *context)
{
    if(!ainekio_v2_posture_sample(s,progress))return false;
    if(!fit)return true;
    ainekio_v2_frame_t frame=s->pose.frame;
    if(!fit(&frame,context))return false;
    joints(&s->pose,&frame);
    return ainekio_v2_contact_forward(&s->pose,s->anchors,false);
}
static bool advance(ainekio_v2_posture_t *s,double *progress,double seconds,
    ainekio_v2_posture_fit_t fit,void *context)
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
        if(!sample_mapped(&next,*progress+segment,fit,context))return false;
        double distance=0.;
        for(unsigned j=0;j<12;j++)distance=fmax(distance,
            fabs(next.pose.frame.position[j]-s->pose.frame.position[j])/100.);
        double duration=distance/ainekio_v2_joint_speed_default();
        if(duration<=remaining) {
            *s=next;*progress+=segment;remaining-=duration;
            if(*progress>=event-1e-9) {
                if(!sample_mapped(s,event,fit,context))return false;
                *progress=event;return true;
            }
        } else {
            segment*=remaining/duration;
            if(!sample_mapped(s,*progress+segment,fit,context))return false;
            *progress+=segment;remaining=0.;
        }
    }
    return true;
}
bool ainekio_v2_posture_advance_mapped(ainekio_v2_posture_t *s,double *progress,
    double seconds,ainekio_v2_posture_fit_t fit,void *context)
{
    if(!s||!progress)return false;
    ainekio_v2_posture_t next=*s;double at=*progress;
    if(!advance(&next,&at,seconds,fit,context))return false;
    *s=next;*progress=at;return true;
}
bool ainekio_v2_posture_advance(ainekio_v2_posture_t *s,double *progress,double seconds)
{
    return ainekio_v2_posture_advance_mapped(s,progress,seconds,NULL,NULL);
}
uint16_t ainekio_v2_posture_arrival_joints(const ainekio_v2_posture_t *s,double progress)
{
    if(progress>=ainekio_v2_posture_path_length())return 0xfff;
    for(unsigned k=0;k<4;k++) {
        double local=progress-k*step_s();
        if(fabs(local-(shift_s+lift_s))<1e-9 ||
           fabs(local-(shift_s+lift_s+place_s))<1e-9) {
            unsigned model=(order[(k+s->order_offset)%4]+2)%4;
            return (uint16_t)(7U<<(3*model));
        }
    }
    return 0;
}
unsigned ainekio_v2_posture_order_for_joints(uint16_t mask,unsigned start)
{
    for(unsigned k=0;k<4;k++) {
        unsigned at=(start+k)%4,model=(order[at]+2)%4;
        if(mask&(7U<<(3*model)))return at;
    }
    return start%4;
}

/* A measured step must retain its Cartesian clearance. If the installed
 * travel cannot realize it at the current height, solve a higher supporting
 * body position within the requested final elevation instead of clipping the
 * leg and declaring that shortened lift to be the new goal. */
static bool target_fits(const ainekio_v2_walk_pose_t *pose,
    ainekio_v2_posture_fit_t fit,void *context)
{
    if(!fit)return true;
    ainekio_v2_frame_t fitted=pose->frame;
    if(!fit(&fitted,context))return false;
    for(unsigned j=0;j<12;j++)if(fabs(fitted.position[j]-pose->frame.position[j])>.1)return false;
    return true;
}
static bool sample_target(ainekio_v2_posture_t *s,double at,
    ainekio_v2_posture_fit_t fit,void *context)
{
    const double previous_height=s->pose.body[2];
    if(!ainekio_v2_posture_sample(s,at))return false;
    ainekio_v2_walk_pose_t pose=s->pose;
    if(s->target.body[2]>=s->start.body[2] && pose.body[2]<previous_height) {
        pose.body[2]=previous_height;
        if(!ainekio_v2_contact_solve(&pose,(const double (*)[3])s->anchors))return false;
    }
    if(target_fits(&pose,fit,context)){s->pose=pose;return true;}
    double lower=pose.body[2],upper=s->target.body[2];
    if(upper<=lower)return false;
    ainekio_v2_walk_pose_t raised=pose;raised.body[2]=upper;
    if(!ainekio_v2_contact_solve(&raised,(const double (*)[3])s->anchors) ||
       !target_fits(&raised,fit,context))return false;
    while(upper-lower>.01) {
        ainekio_v2_walk_pose_t candidate=pose;candidate.body[2]=(lower+upper)/2.;
        if(ainekio_v2_contact_solve(&candidate,(const double (*)[3])s->anchors) &&
           target_fits(&candidate,fit,context)){upper=candidate.body[2];raised=candidate;}
        else lower=candidate.body[2];
    }
    s->pose=raised;return true;
}

bool ainekio_v2_posture_next_target_mapped(ainekio_v2_posture_t *s,double *progress,
    uint16_t *moving,ainekio_v2_posture_fit_t fit,void *context)
{
    const double landmarks[]={shift_s,shift_s+lift_s,shift_s+lift_s+place_s,step_s()};
    double next=ainekio_v2_posture_path_length();
    for(unsigned leg=0;leg<4;leg++)for(unsigned k=0;k<4;k++) {
        const double at=leg*step_s()+landmarks[k];
        if(at>*progress+1e-9)next=fmin(next,at);
    }
    ainekio_v2_posture_t candidate=*s;
    /* Preserve the linkage branch through the existing geometric sampling
     * resolution. This is planning, not a wall-clock motion sequence. */
    for(double at=*progress;at<next;) {
        at=fmin(next,at+.01);
        if(!sample_target(&candidate,at,fit,context))return false;
    }
    *s=candidate;*progress=next;
    *moving=ainekio_v2_posture_arrival_joints(s,next);
    if(!*moving)*moving=0xfff;
    return true;
}

bool ainekio_v2_posture_next_target(ainekio_v2_posture_t *s,double *progress,uint16_t *moving)
{
    return ainekio_v2_posture_next_target_mapped(s,progress,moving,NULL,NULL);
}

bool ainekio_v2_posture_observe(const ainekio_v2_posture_t *s,
    const ainekio_v2_frame_t *measured,const double euler[3],ainekio_v2_walk_pose_t *out)
{
    *out=s->pose;joints(out,measured);
    memcpy(out->euler,euler,sizeof out->euler);out->body[2]=0.;
    double anchors[4][3];memcpy(anchors,s->anchors,sizeof anchors);
    if(!ainekio_v2_contact_forward(out,anchors,false))return false;
    double ground=0.;unsigned contacts=0;
    for(unsigned leg=0;leg<4;leg++)if(s->pose.grounded[leg]) {
        ground+=out->sole_height[leg];contacts++;
    }
    if(!contacts)return false;
    out->body[2]=-ground/contacts;
    return ainekio_v2_contact_forward(out,anchors,false);
}
