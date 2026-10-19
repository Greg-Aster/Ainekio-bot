#include "ainekio/v2_balance.h"
#include "ainekio/v2_limits.h"
#include <math.h>
#include <string.h>

void ainekio_v2_balance_track_tolerant(const ainekio_v2_frame_t *target,
    const ainekio_v2_frame_t *measured,const ainekio_v2_frame_t *previous,
    const double tolerance_deg[12],double dt,double joint_speed,ainekio_v2_frame_t *out,
    ainekio_v2_balance_tracking_t *tracking)
{
    *out=*target;memset(tracking,0,sizeof(*tracking));
    /* Half-error proportional tracking, outside the MG90's own position loop.
     * No accumulating trim, extra trajectory easing, or arrival barrier. A
     * delayed ideal actuator therefore has a decaying (0.5x) correction rather
     * than a growing integral demand. Calibration noise remains observable. */
    for(unsigned j=0;j<12;j++)tracking->error_deg[j]=
        (target->position[j]-measured->position[j])*.01;
    /* Reuse balance's correction-only geometry/speed reduction. Never shorten
     * or discard the gyro target to accommodate the additional tracking trim. */
    for(unsigned attempt=0;attempt<13;attempt++) {
        const double fraction=attempt==12?0.:ldexp(1.,-(int)attempt);
        ainekio_v2_frame_t candidate=*target;
        bool fits=true;
        for(unsigned j=0;j<12;j++) {
            double error=tracking->error_deg[j];
            double excess=copysign(fmax(0.,fabs(error)-(tolerance_deg?tolerance_deg[j]:0.)),error);
            candidate.position[j]+=(float)(50.*fraction*excess);
            double allowed=fmax(joint_speed*dt*100.,fabs(target->position[j]-previous->position[j]));
            if(fabs(candidate.position[j]-previous->position[j])>allowed+.01)fits=false;
        }
        if(fraction==0. || (fits&&ainekio_v2_limits_frame(&candidate))) {
            *out=candidate;tracking->applied_fraction=fraction;tracking->reduced=attempt>0;
            for(unsigned j=0;j<12;j++)tracking->trim_deg[j]=
                (candidate.position[j]-target->position[j])*.01;
            return;
        }
    }
}

void ainekio_v2_balance_track(const ainekio_v2_frame_t *target,
    const ainekio_v2_frame_t *measured,const ainekio_v2_frame_t *previous,
    double dt,double joint_speed,ainekio_v2_frame_t *out,
    ainekio_v2_balance_tracking_t *tracking)
{
    ainekio_v2_balance_track_tolerant(target,measured,previous,NULL,dt,joint_speed,out,tracking);
}

/* Project measured joint lag onto the two body-control axes. Only the target
 * needs to close mechanically: noisy measured joint triples need not form a
 * perfect linkage. Numerical derivatives retain the target assembly branch. */
static void actuator_lag(ainekio_v2_balance_t *state,
    const ainekio_v2_walk_pose_t *nominal,const double points[4][3],
    const ainekio_v2_frame_t *previous,const ainekio_v2_frame_t *measured,
    const double tolerance[12],ainekio_v2_balance_tracking_t *tracking)
{
    memset(tracking,0,sizeof(*tracking));
    double residual[12],jacobian[12][2];bool any=false;
    for(unsigned j=0;j<12;j++) {
        const double error=(previous->position[j]-measured->position[j])*.01;
        tracking->error_deg[j]=error;
        if(!state->actuator_reference_valid)state->actuator_bias_deg[j]=error;
        const double relative=error-state->actuator_bias_deg[j];
        residual[j]=copysign(fmax(0.,fabs(relative)-tolerance[j]),relative)*100.;
        any=any||residual[j]!=0.;
    }
    state->actuator_reference_valid=true;
    tracking->observable=true;
    if(!any)return;
    for(unsigned axis=0;axis<2;axis++) {
        bool solved=false;
        for(int direction=1;direction>=-1;direction-=2) {
            const double step=direction*.0008726646259971648; /* 0.05deg derivative */
            ainekio_v2_walk_pose_t displaced=*nominal;
            for(unsigned a=0;a<2;a++)displaced.euler[a]+=state->correction[a];
            displaced.euler[axis]+=step;displaced.frame=*previous;
            for(unsigned l=0;l<4;l++)for(unsigned j=0;j<3;j++)
                displaced.joints[l][j]=previous->position[(l<2?l+2:l-2)*3+j]*.00017453292519943296;
            if(points ? ainekio_v2_contact_solve(&displaced,points) : ainekio_v2_walk_solve(&displaced)) {
                for(unsigned j=0;j<12;j++)jacobian[j][axis]=(displaced.frame.position[j]-previous->position[j])/step;
                solved=true;break;
            }
        }
        if(!solved){tracking->observable=false;return;}
    }
    double aa=0.,ab=0.,bb=0.,ar=0.,br=0.;
    for(unsigned j=0;j<12;j++) {
        const double a=jacobian[j][0],b=jacobian[j][1];
        aa+=a*a;ab+=a*b;bb+=b*b;ar+=a*residual[j];br+=b*residual[j];
    }
    const double determinant=aa*bb-ab*ab;
    if(!(determinant>1e-12*aa*bb)){tracking->observable=false;return;}
    tracking->body_lag_rad[0]=(bb*ar-ab*br)/determinant;
    tracking->body_lag_rad[1]=(aa*br-ab*ar)/determinant;
}

static void balance_response(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed,ainekio_v2_walk_pose_t *out,
    const ainekio_v2_balance_tuning_t *tuning,bool standing,double response_direction,
    const ainekio_v2_frame_t *measured,const double tolerance[12],
    ainekio_v2_balance_tracking_t *tracking)
{
    *out=*nominal;
    s->sensor_usable=usable;s->reduced=false;s->applied_fraction=1.;
    if(usable) {
        double w=q[0],x=q[1],y=q[2],z=q[3];
        s->measured[0]=atan2(2.*(w*x+y*z),1.-2.*(x*x+y*y));
        s->measured[1]=asin(fmax(-1.,fmin(1.,2.*(w*y-z*x))));
    }
    if(tracking)actuator_lag(s,nominal,local_points,previous,measured,tolerance,tracking);
    /* Taper stationary correction as attitude error shrinks. At Strength 1
     * the response rate approaches 2/s near level and 8/s at large tilt, with
     * 5deg at the middle of that curve. Exponential gain keeps the requested
     * fraction consistent across update intervals. Targets still go directly
     * to PWM; moving-gait filtering and unavailable-sensor fade are unchanged. */
    double desired[2];
    for(unsigned j=0;j<2;j++) {
        const double offset=(j==0 ? tuning->roll_deg : -tuning->pitch_deg)*.017453292519943295;
        const double direction=response_direction;
        const double error=direction*(nominal->euler[j]+offset-s->measured[j]);
        const double angular_rate=direction*rate[j];
        if(standing && usable) {
            const double relative_error=error/(5.*.017453292519943295);
            const double squared=relative_error*relative_error;
            const double response_rate=2.+6.*squared/(1.+squared);
            const double gain=-expm1(-response_rate*tuning->strength*dt);
            const double back_calculation=tracking && tracking->observable ?
                -expm1(-4.*dt)*tracking->body_lag_rad[j] : 0.;
            desired[j]=s->correction[j]+gain*error-dt*.2*tuning->damping*angular_rate-back_calculation;
        } else {
            const double target=usable ? .4*tuning->strength*error-.05*tuning->damping*angular_rate : 0.;
            desired[j]=s->correction[j]+dt/(.25+dt)*(target-s->correction[j]);
        }
    }
    if(desired[0]==0. && desired[1]==0. && s->correction[0]==0. && s->correction[1]==0.)return;
    for(unsigned attempt=0;attempt<13;attempt++) {
        double fraction=attempt==12?0.:ldexp(1.,-(int)attempt);
        ainekio_v2_walk_pose_t candidate=*nominal;
        double accepted[2];
        for(unsigned j=0;j<2;j++) {
            accepted[j]=standing ? s->correction[j]+fraction*(desired[j]-s->correction[j]) :
                fraction*desired[j];
            candidate.euler[j]+=accepted[j];
        }
        if(standing) {
            /* Continue from the last commanded assembly branch. At zero
             * increment retain that exact frame and its encoded angles. */
            candidate.frame=*previous;
            for(unsigned l=0;l<4;l++)for(unsigned j=0;j<3;j++)
                candidate.joints[l][j]=previous->position[(l<2?l+2:l-2)*3+j]*
                    .00017453292519943296;
        }
        bool fits=fraction==0. || (local_points ? ainekio_v2_contact_solve(&candidate,local_points)
                                                          : ainekio_v2_walk_solve(&candidate));
        if(fits && fraction>0. && !(standing && usable))for(unsigned j=0;j<12;j++) {
            /* Preserve the base trajectory even when its existing owner is
             * retiming it. A correction may not increase an existing excess. */
            double allowed=joint_speed*dt*100.;
            if(!standing)allowed=fmax(allowed,fabs(nominal->frame.position[j]-previous->position[j]));
            if(fabs(candidate.frame.position[j]-previous->position[j])>allowed+.01)fits=false;
        }
        if(fits) {
            *out=candidate;s->applied_fraction=fraction;s->reduced=attempt>0;
            /* Store only the increment the solver could actually accept.
             * Unreachable demand is not accumulated for later release. */
            for(unsigned j=0;j<2;j++)s->correction[j]=accepted[j];
            return;
        }
    }
}

void ainekio_v2_balance_response_apply(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed,ainekio_v2_walk_pose_t *out,
    const ainekio_v2_balance_tuning_t *tuning,bool standing,double direction)
{
    balance_response(s,q,rate,usable,dt,nominal,points,previous,joint_speed,out,
        tuning,standing,direction,NULL,NULL,NULL);
}

void ainekio_v2_balance_feedback_apply(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],double dt,
    const ainekio_v2_walk_pose_t *nominal,const double points[4][3],
    const ainekio_v2_frame_t *previous,const ainekio_v2_frame_t *measured,
    const double tolerance[12],ainekio_v2_walk_pose_t *out,
    const ainekio_v2_balance_tuning_t *tuning,ainekio_v2_balance_tracking_t *tracking)
{
    balance_response(s,q,rate,true,dt,nominal,points,previous,INFINITY,out,
        tuning,true,1.,measured,tolerance,tracking);
}

void ainekio_v2_balance_configured_apply(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed,ainekio_v2_walk_pose_t *out,
    const ainekio_v2_balance_tuning_t *tuning,bool standing)
{
    ainekio_v2_balance_response_apply(s,q,rate,usable,dt,nominal,local_points,
        previous,joint_speed,out,tuning,standing,1.);
}

void ainekio_v2_balance_apply(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed,ainekio_v2_walk_pose_t *out)
{
    const ainekio_v2_balance_tuning_t tuning=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
    ainekio_v2_balance_configured_apply(s,q,rate,usable,dt,nominal,local_points,previous,joint_speed,out,&tuning,false);
}

void ainekio_v2_balance_hold_apply(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed,ainekio_v2_walk_pose_t *out)
{
    const ainekio_v2_balance_tuning_t tuning=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
    ainekio_v2_balance_configured_apply(s,q,rate,usable,dt,nominal,local_points,previous,joint_speed,out,&tuning,true);
}
