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

void ainekio_v2_balance_response_apply(ainekio_v2_balance_t *s,
    const float q[4],const float rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed,ainekio_v2_walk_pose_t *out,
    const ainekio_v2_balance_tuning_t *tuning,bool standing,double response_direction)
{
    *out=*nominal;
    s->sensor_usable=usable;s->reduced=false;s->applied_fraction=1.;
    if(usable) {
        double w=q[0],x=q[1],y=q[2],z=q[3];
        s->measured[0]=atan2(2.*(w*x+y*z),1.-2.*(x*x+y*y));
        s->measured[1]=asin(fmax(-1.,fmin(1.,2.*(w*y-z*x))));
    }
    /* Standing integrates attitude error into the accepted body offset. A
     * persistent tilt keeps moving the planted linkage instead of settling
     * at 40% of the error. Gyro rate damps the approach to level. Moving gaits
     * retain their existing filtered PD correction around the authored pose. */
    double desired[2];
    for(unsigned j=0;j<2;j++) {
        const double offset=(j==0 ? tuning->roll_deg : -tuning->pitch_deg)*.017453292519943295;
        const double direction=response_direction;
        const double error=direction*(nominal->euler[j]+offset-s->measured[j]);
        const double angular_rate=direction*rate[j];
        double target=usable ? .4*tuning->strength*error-.05*tuning->damping*angular_rate : 0.;
        desired[j]=standing && usable ? s->correction[j]+
            dt*(2.*tuning->strength*error-.2*tuning->damping*angular_rate) :
            s->correction[j]+dt/(.25+dt)*(target-s->correction[j]);
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
        if(fits && fraction>0.)for(unsigned j=0;j<12;j++) {
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
