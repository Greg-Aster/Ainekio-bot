#include "ainekio/v2_walk.h"
#include "walk_data.h"
#include "servo_data.h"
#include <math.h>
#include <stdatomic.h>
#include <string.h>

static const double pi=3.14159265358979323846;
static double smooth(double u) {if(u<=0.)return 0.;if(u>=1.)return 1.;return u*u*u*(10.+u*(-15.+6.*u));}
/* Integrate short endpoint ramps around constant swing velocity. Walk and
 * Run return the foot promptly instead of carrying it beyond the intended
 * stance endpoints while the body continues moving. */
static double run_swing(double u)
{
    const double r=V2_RUN_SWING_RAMP,v=1./(1.-r);
    if(u<r){double t=u/r;return v*r*(t*t*t-.5*t*t*t*t);}
    if(u>1.-r){double t=(1.-u)/r;return 1.-v*r*(t*t*t-.5*t*t*t*t);}
    return v*(u-r*.5);
}
static double bump(double u) {return 64.*u*u*u*(1.-u)*(1.-u)*(1.-u);}
/* Walk clears the floor earlier and returns later than the narrow sixth-
 * degree arch, while retaining zero vertical velocity at both contacts. */
static double walk_lift(double u) {return 16.*u*u*(1.-u)*(1.-u);}
static _Atomic float joint_speed_limit = V2_GAIT_MAX_JOINT_SPEED_DEGREES_S;
double ainekio_v2_joint_speed_default(void){return V2_GAIT_MAX_JOINT_SPEED_DEGREES_S;}
bool ainekio_v2_joint_speed_set(float value)
{
    if (!isfinite(value) || value <= 0.F) return false;
    atomic_store(&joint_speed_limit,value); return true;
}
double ainekio_v2_gait_joint_speed_limit(void){return atomic_load(&joint_speed_limit);}
double ainekio_v2_gait_joint_speed_flag_threshold(void){return ainekio_v2_gait_joint_speed_limit();}

bool ainekio_v2_walk_controls_valid(ainekio_v2_walk_controls_t c)
{
    return isfinite(c.stride_percent)&&isfinite(c.motion_rate)&&c.stride_percent>=0.&&c.stride_percent<=100.&&c.motion_rate>=.25&&c.motion_rate<=3.;
}
bool ainekio_v2_walk_controls(double speed,ainekio_v2_walk_controls_t *out)
{
    if(!out||!isfinite(speed)||speed<0||speed>100)return false;
    *out=(ainekio_v2_walk_controls_t){speed,2.};return true;
}
bool ainekio_v2_walk_request(const ainekio_command_t *command,uint8_t *cycles)
{
    if(!command||!cycles||command->kind!=AINEKIO_COMMAND_INTENT||command->data.intent.kind!=AINEKIO_INTENT_WALK||
       command->data.intent.data.walk.direction>AINEKIO_WALK_SIDE_RIGHT||command->data.intent.data.walk.gait>AINEKIO_GAIT_CRAB||
       (command->data.intent.data.walk.direction>=AINEKIO_WALK_SIDE_LEFT&&command->data.intent.data.walk.gait!=AINEKIO_GAIT_CRAB)||command->data.intent.data.walk.steps>10)return false;
    *cycles=command->data.intent.data.walk.steps;return true;
}
static double run_at(const ainekio_v2_walk_state_t *s,double phase)
{
    if(s->run_from==s->run_target)return s->run_from;
    return s->run_from+(s->run_target-s->run_from)*smooth((phase-s->run_transition_phase)/V2_RUN_TRANSITION);
}
static double mixed(const ainekio_v2_walk_state_t *s,double phase,double walk,double run)
{
    return walk+(run-walk)*run_at(s,phase);
}
static double duty_at(const ainekio_v2_walk_state_t *s,double phase) {return s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_DUTY:mixed(s,phase,s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_DUTY:V2_WALK_DUTY,V2_RUN_DUTY);}
static double sweep_at(const ainekio_v2_walk_state_t *s,double phase) {return s->gait_mode==AINEKIO_GAIT_CRAB?(s->direction>=AINEKIO_WALK_SIDE_LEFT?V2_CRAB_SIDE_SWEEP:V2_CRAB_SWEEP):s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_SWEEP:mixed(s,phase,V2_WALK_SWEEP,s->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_SWEEP:V2_RUN_SWEEP);}
static double offset_at(const ainekio_v2_walk_state_t *s,unsigned leg,double phase) {return s->offset_from[leg]==s->offset_target[leg]?s->offset_from[leg]:s->offset_from[leg]+(s->offset_target[leg]-s->offset_from[leg])*smooth((phase-s->run_transition_phase)/V2_RUN_TRANSITION);}
/* Locate contact events on the changing phase schedule. During Walk/Run
 * blending, the offset and duty at touchdown differ from those at liftoff. */
static double contact_event(const ainekio_v2_walk_state_t *s,unsigned leg,
                            double cycle,bool liftoff,double near)
{
    double end=s->run_transition_phase+V2_RUN_TRANSITION;
    double steady=cycle+offset_at(s,leg,end)+(liftoff?duty_at(s,end):0.);
    if(s->run_from==s->run_target || steady>=end)return steady;
    /* The six-cycle blend keeps phase minus offset/duty monotonic. Its
     * adjacent contact event lies within two cycles of this planning point. */
    double lo=near-2.,hi=near+2.;
    for(unsigned i=0;i<32;i++) {
        double mid=(lo+hi)*.5;
        double phase=mid-offset_at(s,leg,mid)-(liftoff?duty_at(s,mid):0.);
        if(phase<cycle)lo=mid;else hi=mid;
    }
    return (lo+hi)*.5;
}
static void set_run_target(ainekio_v2_walk_state_t *s,double target)
{
    if(s->run_target==target)return;
    for(unsigned i=0;i<4;i++) {
        double offset=offset_at(s,i,s->phase),next=target?(i<2?0.:.5):v2_walk_offsets[i];
        /* Select the nearest equivalent phase. Always rounding downward
         * makes a tiny interrupted Run transition advance a returning Walk
         * foot by almost a whole cycle. Half-cycle ties still advance. */
        next+=ceil(offset-next-.5-1e-9);
        s->offset_from[i]=offset;s->offset_target[i]=next;
    }
    s->run_from=run_at(s,s->phase);s->run_target=target;s->run_transition_phase=s->phase;
}
/* Authored body transfer follows the footfall schedule in the body frame.
 * Establish it during the initial four-foot overlap; it neither changes
 * the gait clock nor moves planted foot anchors. */
static void support_pose(ainekio_v2_walk_pose_t *p,const double k[5],double duty)
{
    double a=2.*pi*p->phase,entry=smooth(p->phase/(duty-.75));
    p->body[0]+=entry*(k[0]+k[1]*sin(2.*a)+k[2]*cos(2.*a));
    p->body[1]+=entry*(k[3]*sin(a)+k[4]*cos(a));
}
static void body_pose(ainekio_v2_walk_pose_t *p,double stride,double height_phase)
{
    p->body[0]=0.;
    if(p->gait==AINEKIO_GAIT_CRAB){p->body[1]=0.;p->body[2]=V2_CRAB_BODY_Z;p->euler[0]=p->euler[1]=p->euler[2]=0.;support_pose(p,v2_crab_support[p->direction],V2_CRAB_DUTY);return;}
    double strength=stride/100.,a=2.*pi*p->phase;
    double walk_strength=strength*V2_WALK_BODY_SCALE;
    double base_strength=p->gait==AINEKIO_GAIT_CRAWL?strength:walk_strength;
    p->body[1]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_SWAY:V2_SWAY)*base_strength*sin(a);
    p->body[2]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_BODY_Z:V2_BODY_Z)+(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_BOB:V2_BOB)*base_strength*cos(2*a);
    p->euler[0]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_ROLL:V2_ROLL)*base_strength*sin(a);p->euler[1]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_PITCH:V2_PITCH)*base_strength*sin(2*a);p->euler[2]=0.;
    if(p->gait==AINEKIO_GAIT_CRAWL)support_pose(p,v2_crawl_support[p->direction],V2_CRAWL_DUTY);
    if(p->gait==AINEKIO_GAIT_WALK) {
        /* Full-stroke support follows the actual linkage workspace. Allow
         * the body to rise/fall while planted anchors remain on the ground,
         * instead of requiring every loaded pose at one body height. */
        const bool backward=p->direction==AINEKIO_WALK_BACKWARD;
        const double *height=backward?v2_walk_back_height:v2_walk_height;
        double ha=2.*pi*height_phase;
        p->body[2]+=strength*((backward?V2_WALK_BACK_BODY_Z_FULL:V2_WALK_BODY_Z_FULL)-V2_BODY_Z+
            height[0]*sin(2.*ha)+height[1]*cos(2.*ha)+
            height[2]*sin(4.*ha)+height[3]*cos(4.*ha));
        /* Transfer body load toward the three planted feet. This changes the
         * body pose, never the gait clock or world-space stance anchors.
         * Establish the shift during the first contact overlap, then keep it
         * through low-speed steps; support is needed even for a short stride. */
        /* Keep the forward support placement through short/medium steps;
         * shift toward the long-stride placement with squared stride gain. */
        double support_phase=a+2.*pi*V2_WALK_SUPPORT_PHASE;
        double support=smooth(p->phase/(V2_WALK_DUTY-.75))*(1.-p->run_blend);
        p->body[0]=support*(V2_WALK_SUPPORT_X_MEAN+(V2_WALK_SUPPORT_X_MEAN_FULL-V2_WALK_SUPPORT_X_MEAN)*strength*strength+V2_WALK_SUPPORT_X*sin(2.*support_phase));
        p->body[1]=support*V2_WALK_SUPPORT_Y*sin(support_phase);
    }
    if(p->run_blend>0.) {
        /* Paired front stance, flight, paired rear stance, flight. This is a
         * kinematic reference, not a force/balance controller. */
        double z=V2_BODY_Z+((p->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_BODY_Z:V2_RUN_BODY_Z)-V2_BODY_Z)*smooth(p->phase/3.)+V2_RUN_BOB*strength*cos(2.*a-4.*pi*(V2_RUN_DUTY+.5)/2.);
        double pitch=(p->direction==AINEKIO_WALK_FORWARD ?
            V2_RUN_FORWARD_PITCH*sin(a+V2_RUN_FORWARD_PITCH_PHASE)+V2_RUN_FORWARD_PITCH_BIAS : V2_RUN_PITCH*sin(a))*strength;
        p->body[1]*=1.-p->run_blend;p->euler[0]*=1.-p->run_blend;
        p->body[2]+=(z-p->body[2])*p->run_blend;
        p->euler[1]+=(pitch-p->euler[1])*p->run_blend;
        /* The changing footfall schedule retains already planted anchors.
         * Its fitted body path passes behind the linear Walk/Run midpoint,
         * then rejoins both steady postures without altering either stride. */
        p->body[0]+=(p->direction==AINEKIO_WALK_BACKWARD?V2_WALK_RUN_BACK_TRANSFER_X:V2_WALK_RUN_TRANSFER_X)*4.*p->run_blend*(1.-p->run_blend);
    }
}
static bool standing(ainekio_v2_walk_pose_t *p,double height)
{
    *p=(ainekio_v2_walk_pose_t){0};p->body[2]=height;
    for(unsigned i=0;i<4;i++){p->feet[i][0]=v2_walk_stance[i][0];p->feet[i][1]=v2_walk_stance[i][1];p->grounded[i]=true;}
    return ainekio_v2_walk_solve(p);
}
bool ainekio_v2_walk_pose(double phase,ainekio_v2_walk_controls_t c,ainekio_v2_walk_pose_t *p)
{
    if(!p||!isfinite(phase)||fabs(phase)>1e6||!ainekio_v2_walk_controls_valid(c))return false;
    if(!standing(p,V2_STAND_BODY_Z))return false;
    if(c.stride_percent==0.)return true;
    ainekio_v2_walk_pose_t target=*p;target.phase=phase;
    double advance=V2_WALK_SWEEP*c.stride_percent/100./V2_WALK_DUTY;
    body_pose(&target,c.stride_percent,phase);target.body[0]+=phase*advance;
    for(unsigned i=0;i<4;i++) {
        double touchdown=floor(phase-v2_walk_offsets[i])+v2_walk_offsets[i],local=phase-touchdown;
        double anchor=touchdown*advance+V2_WALK_DUTY*advance*(.5-V2_WALK_BIAS/V2_WALK_SWEEP),height=0.;
        if(local>=V2_WALK_DUTY){double u=(local-V2_WALK_DUTY)/(1.-V2_WALK_DUTY);anchor+=advance*run_swing(u);height=(V2_WALK_MIN_LIFT+(V2_WALK_LIFT-V2_WALK_MIN_LIFT)*c.stride_percent/100.)*walk_lift(u);}
        target.feet[i][0]=v2_walk_stance[i][0]+anchor;target.sole_height[i]=height;target.grounded[i]=local<V2_WALK_DUTY;
    }
    /* Direct geometry also initializes arbitrary diagnostic phases. */
    if(!ainekio_v2_walk_solve(&target))return false;
    *p=target;
    p->frame.phase=AINEKIO_V2_LOOP;return true;
}
static ainekio_v2_walk_controls_t controls_at(const ainekio_v2_walk_state_t *s,double phase)
{
    if(s->from.stride_percent==s->target.stride_percent && s->from.motion_rate==s->target.motion_rate)return s->target;
    double u=smooth((phase-s->transition_phase)/s->transition_span);
    return (ainekio_v2_walk_controls_t){s->from.stride_percent+(s->target.stride_percent-s->from.stride_percent)*u,
        s->from.motion_rate+(s->target.motion_rate-s->from.motion_rate)*u};
}
/* Integrate bounded profile values on the P4's single-precision FPU. Phase
 * differences are formed in double first; world anchors and the clock retain
 * double precision. The same 32 Simpson intervals preserve the planned path. */
static float smoothf(float u)
{
    if(u<=0.f)return 0.f;
    if(u>=1.f)return 1.f;
    return u*u*u*(10.f+u*(-15.f+6.f*u));
}
static double profile_travel(const ainekio_v2_walk_state_t *s,double lo,double hi,bool turning)
{
    double first=controls_at(s,lo).stride_percent,last=controls_at(s,hi).stride_percent;
    double r0=run_at(s,lo),r1=run_at(s,hi);
    const double angle=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_TURN:s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_TURN:V2_WALK_TURN;
    const double sign=s->direction==AINEKIO_WALK_TURN_LEFT?1.:-1.;
    if(first==last && r0==r1) {
        double distance=first*(hi-lo)/100.;
        return distance*(turning?mixed(s,lo,angle,V2_RUN_TURN)*sign:sweep_at(s,lo)/duty_at(s,lo));
    }
    float u0=(float)((lo-s->transition_phase)/s->transition_span);
    float du=(float)((hi-lo)/(32.*s->transition_span));
    float rphase=(float)((lo-s->run_transition_phase)/V2_RUN_TRANSITION);
    float dr=(float)((hi-lo)/(32.*V2_RUN_TRANSITION));
    float from=(float)s->from.stride_percent,change=(float)(s->target.stride_percent-s->from.stride_percent);
    float rfrom=(float)s->run_from,rchange=(float)(s->run_target-s->run_from);
    float run_sweep=(float)(s->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_SWEEP:V2_RUN_SWEEP);
    float sum=0.f;
    for(unsigned i=0;i<=32;i++) {
        float run=r0==r1?(float)r0:rfrom+rchange*smoothf(rphase+dr*i);
        float stride=first==last?(float)first:from+change*smoothf(u0+du*i);
        float ratio;
        if(turning)ratio=(float)angle+((float)V2_RUN_TURN-(float)angle)*run;
        else {
            float sweep=s->gait_mode==AINEKIO_GAIT_CRAB?(float)sweep_at(s,lo):s->gait_mode==AINEKIO_GAIT_CRAWL?(float)V2_CRAWL_SWEEP:
                (float)V2_WALK_SWEEP+(run_sweep-(float)V2_WALK_SWEEP)*run;
            ratio=sweep/(s->gait_mode==AINEKIO_GAIT_CRAB?(float)V2_CRAB_DUTY:((float)(s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_DUTY:V2_WALK_DUTY)+((float)V2_RUN_DUTY-(float)(s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_DUTY:V2_WALK_DUTY))*run));
        }
        sum+=(i==0||i==32?1.f:(i%2?4.f:2.f))*stride*ratio;
    }
    return (double)sum*(hi-lo)/9600.*(turning?sign:1.);
}
static double travel(const ainekio_v2_walk_state_t *s,double lo,double hi)
{
    return profile_travel(s,lo,hi,false);
}
static double turn_travel(const ainekio_v2_walk_state_t *s,double lo,double hi)
{
    return profile_travel(s,lo,hi,true);
}
static double steering_at(const ainekio_v2_walk_state_t *s,double phase,unsigned axis)
{
    /* Feet already in swing retain landings chosen for the previous heading.
     * Use the same two-cycle blend as the full Walk stroke so a reversal does
     * not pull the body away from those committed anchors in a single cycle.
     * This changes interpolation time, not the requested forward/turn range. */
    double u=smooth((phase-s->steering_phase)/V2_WALK_TRANSITION);
    double from=axis==2?s->lateral_from:axis==1?s->turn_from:s->forward_from;
    double target=axis==2?s->lateral_target:axis==1?s->turn_target:s->forward_target;
    return (from+(target-from)*u)/100.;
}
/* A curve spends the same available foot stroke on translation and yaw.
 * Use the outer foot's radius, rather than adding a full straight stroke
 * and a full turning stroke. Straight travel and turn-in-place retain their
 * complete requested ranges. This is the owner's approved shared range. */
static double steering_scale(const ainekio_v2_walk_state_t *s,double phase)
{
    if(s->gait_mode!=AINEKIO_GAIT_WALK)return 1.;
    double forward=fabs(steering_at(s,phase,0)),turn=fabs(steering_at(s,phase,1));
    double radius=0.;
    for(unsigned i=0;i<4;i++)radius=fmax(radius,hypot(
        fabs(v2_walk_stance[i][0])+fabs(V2_WALK_BIAS)+V2_WALK_SWEEP*.5,
        v2_walk_stance[i][1]));
    double yaw=mixed(s,phase,V2_WALK_TURN,V2_RUN_TURN);
    double scale=fmax(1.,forward+turn*radius*yaw*duty_at(s,phase)/sweep_at(s,phase));
    return 1.+(scale-1.)*(1.-run_at(s,phase));
}
/* Integrate a body-frame translation and yaw together. Planted foot anchors
 * stay fixed; each swing chooses its landing from the same predicted body path. */
static void steered_path(const ainekio_v2_walk_state_t *s,double lo,double hi,double *x,double *y,double *yaw)
{
    /* Predict landings with the same varying twist as intervening ticks.
     * A single midpoint over an entire future stance misses range-sharing
     * and steering changes during Walk/Run transitions. */
    unsigned segments=(unsigned)fmax(1.,ceil((hi-lo)*32.));
    double span=(hi-lo)/segments;
    for(unsigned i=0;i<segments;i++) {
        double begin=lo+i*span,end=begin+span,phase=(begin+end)*.5;
        double scale=steering_scale(s,phase);
        double distance=travel(s,begin,end)*steering_at(s,phase,false)/scale;
        double angle=fabs(turn_travel(s,begin,end))*steering_at(s,phase,true)/scale;
        double lateral=travel(s,begin,end)*steering_at(s,phase,2);
        if(fabs(angle)<1e-9){*x+=distance*cos(*yaw)-lateral*sin(*yaw);*y+=distance*sin(*yaw)+lateral*cos(*yaw);}
        else{double radius=distance/angle,side_radius=lateral/angle;
            *x+=radius*(sin(*yaw+angle)-sin(*yaw))+side_radius*(cos(*yaw+angle)-cos(*yaw));
            *y+=radius*(cos(*yaw)-cos(*yaw+angle))+side_radius*(sin(*yaw+angle)-sin(*yaw));}
        *yaw+=angle;
    }
}
bool ainekio_v2_gait_begin(ainekio_v2_walk_state_t *s,ainekio_walk_direction_t direction,ainekio_gait_t gait,unsigned cycles,ainekio_v2_walk_controls_t c,uint64_t now)
{
    if(!s||direction>AINEKIO_WALK_SIDE_RIGHT||gait>AINEKIO_GAIT_CRAB||(direction>=AINEKIO_WALK_SIDE_LEFT&&gait!=AINEKIO_GAIT_CRAB)||cycles>10||!ainekio_v2_walk_controls_valid(c))return false;
    /* Give the wide Crab stance two cycles to establish its first anchors.
     * A one-cycle launch left too little margin at the planted inside leg.
     * Wider Walk also establishes its new fore/aft anchors over two cycles. */
    *s=(ainekio_v2_walk_state_t){.last_us=now,.end_phase=cycles?2.+cycles:INFINITY,.direction=direction,.gait_mode=gait,.run_from=gait==AINEKIO_GAIT_RUN?1.:0.,.run_target=gait==AINEKIO_GAIT_RUN?1.:0.,.transition_span=direction==AINEKIO_WALK_BACKWARD||gait==AINEKIO_GAIT_RUN?3.:gait==AINEKIO_GAIT_WALK?V2_WALK_TRANSITION:gait==AINEKIO_GAIT_CRAB?V2_CRAB_STARTUP_CYCLES:1.,.from={0.,1.},.target=c,.stopping=c.stride_percent==0.};
    for(unsigned i=0;i<4;i++)s->offset_from[i]=s->offset_target[i]=gait==AINEKIO_GAIT_CRAB?v2_crab_offsets[i]:gait==AINEKIO_GAIT_RUN?(i<2?0.:.5):v2_walk_offsets[i];
    s->clock_scale=1.;
    if(!standing(&s->pose,gait==AINEKIO_GAIT_CRAWL?V2_STAND_BODY_Z:V2_BODY_Z)){s->failed=true;return false;}
    s->pose.gait=gait;s->pose.direction=direction;s->pose.run_blend=s->run_target;
    if((gait==AINEKIO_GAIT_CRAWL||gait==AINEKIO_GAIT_CRAB)&&!ainekio_v2_walk_solve(&s->pose)){s->failed=true;return false;}
    s->initialized=true;s->pose.frame.phase=AINEKIO_V2_ENTRY;return true;
}
bool ainekio_v2_locomotion_begin(ainekio_v2_walk_state_t *s,ainekio_walk_direction_t direction,bool crawl,unsigned cycles,ainekio_v2_walk_controls_t c,uint64_t now)
{
    return ainekio_v2_gait_begin(s,direction,crawl?AINEKIO_GAIT_CRAWL:AINEKIO_GAIT_WALK,cycles,c,now);
}
bool ainekio_v2_walk_begin(ainekio_v2_walk_state_t *s,unsigned cycles,ainekio_v2_walk_controls_t c,uint64_t now)
{
    return ainekio_v2_locomotion_begin(s,AINEKIO_WALK_FORWARD,false,cycles,c,now);
}
static double control_transition_start(const ainekio_v2_walk_state_t *s,ainekio_v2_walk_controls_t c)
{
    double phase=s->phase;
    /* During Run or its transitions, airborne feet already have landing targets based
     * on current travel. Finish honors those landings before decelerating;
     * newly planned swings see the scheduled stop profile. */
    if(c.stride_percent==0. && run_at(s,s->phase)>0.)
        for(unsigned i=0;i<4;i++)if(s->feet[i].swinging)phase=fmax(phase,s->feet[i].touchdown_phase);
    return phase;
}
static double control_transition_span(const ainekio_v2_walk_state_t *s,ainekio_v2_walk_controls_t c)
{
    /* Run's committed swing destinations were planned at the previous stride.
     * Use its existing three-cycle entry profile to open or close the stroke,
     * so body bounding and new landings evolve together. Walk/Run rephasing
     * uses the full six-cycle blend; Run Finish uses three cycles. Rate-only
     * changes retain one-cycle interpolation. Wider Walk uses its
     * two-cycle interpolation so planted feet stay within the authored path.
     * Crab likewise needs its existing two-cycle anchor-establishment profile
     * when changing stride: its wide feet were planted for the previous sweep.
     * This changes the stride path across cycles, not the joint movement rate. */
    return s->from.stride_percent!=c.stride_percent &&
        (s->run_target>0. || run_at(s,s->phase)>0.) ?
        (c.stride_percent>0. && s->run_from!=s->run_target && s->phase<s->run_transition_phase+V2_RUN_TRANSITION ? V2_RUN_TRANSITION : 3.) :
        s->gait_mode==AINEKIO_GAIT_WALK&&run_at(s,s->phase)==0. ? V2_WALK_TRANSITION :
        s->gait_mode==AINEKIO_GAIT_CRAB ? V2_CRAB_STARTUP_CYCLES : 1.;
}
bool ainekio_v2_walk_update(ainekio_v2_walk_state_t *s,ainekio_v2_walk_controls_t c)
{
    if(!s||!s->initialized||s->failed||s->complete||!ainekio_v2_walk_controls_valid(c))return false;
    if(s->stopping&&c.stride_percent>0.)return false; /* A stopped command is never resurrected. */
    /* Before the first tick there are no committed swings: replace the launch
     * target, rather than queueing it behind an unused startup trajectory. */
    if(s->phase==0. && s->preparation_seconds==0.) {
        s->target=c;s->pending_update=false;
        if(c.stride_percent==0.)s->stopping=true;
        return true;
    }
    if((s->gait_mode==AINEKIO_GAIT_CRAB&&s->preparation_seconds<V2_CRAB_ENTRY)||
       (s->pose.gait==AINEKIO_GAIT_CRAWL&&s->preparation_seconds<V2_CRAWL_ENTRY)){
        s->target=c;s->pending_update=false;
        if(c.stride_percent==0.)s->stopping=true;
        return true;
    }
    /* Walk/Run phase updates begin immediately in accept(). Retarget the
     * stride from its current value at the same time; queuing it behind the
     * previous stride transition lets the body and feet follow different
     * commands. Already committed airborne landings remain unchanged. */
    if(s->phase<s->transition_phase+s->transition_span &&
       !(s->gait_mode==AINEKIO_GAIT_WALK && c.stride_percent>0.)){
        s->pending=c;s->pending_update=true;
    }
    else {s->from=controls_at(s,s->phase);s->target=c;s->transition_phase=control_transition_start(s,c);s->transition_span=control_transition_span(s,c);s->pending_update=false;}
    if(c.stride_percent==0.)s->stopping=true;
    return true;
}
static bool advance(ainekio_v2_walk_state_t *s,double dt,bool emit)
{
    if(s->gait_mode==AINEKIO_GAIT_CRAB&&s->preparation_seconds<V2_CRAB_ENTRY){
        s->preparation_seconds=fmin(V2_CRAB_ENTRY,s->preparation_seconds+dt);
        if(s->preparation_seconds>V2_CRAB_ENTRY-1e-9)s->preparation_seconds=V2_CRAB_ENTRY;
        s->pose.body[2]=V2_BODY_Z+(V2_CRAB_BODY_Z-V2_BODY_Z)*smooth(s->preparation_seconds/.6);
        for(unsigned i=0;i<4;i++){
            unsigned cad=(i+2)%4;
            double u=fmax(0.,fmin(1.,(s->preparation_seconds-.4-cad*.6)/.6));
            double y=copysign(V2_CRAB_WIDTH,v2_walk_stance[i][1])-v2_walk_stance[i][1];
            s->feet[i].start_y=s->feet[i].end_y=y*smooth(u);
            s->pose.feet[i][1]=v2_walk_stance[i][1]+s->feet[i].start_y;
            s->pose.sole_height[i]=8.*bump(u);s->pose.grounded[i]=u<=0.||u>=1.;
        }
        if(s->stopping&&s->preparation_seconds>=V2_CRAB_ENTRY){s->complete=true;s->pose.frame.phase=AINEKIO_V2_COMPLETE;}
        return true;
    }
    if((s->pose.gait==AINEKIO_GAIT_CRAWL)&&s->preparation_seconds<V2_CRAWL_ENTRY){
        s->preparation_seconds=fmin(V2_CRAWL_ENTRY,s->preparation_seconds+dt);
        if(s->preparation_seconds>V2_CRAWL_ENTRY-1e-9)s->preparation_seconds=V2_CRAWL_ENTRY;
        s->pose.body[2]=V2_STAND_BODY_Z+(V2_CRAWL_BODY_Z-V2_STAND_BODY_Z)*smooth(s->preparation_seconds/V2_CRAWL_ENTRY);
        if(s->stopping&&s->preparation_seconds>=V2_CRAWL_ENTRY){s->complete=true;s->pose.frame.phase=AINEKIO_V2_COMPLETE;}
        return true;
    }
    double previous=s->phase;
    if(s->pending_update&&s->phase>=s->transition_phase+s->transition_span){
        s->from=s->target;s->target=s->pending;s->transition_phase=control_transition_start(s,s->pending);s->transition_span=control_transition_span(s,s->pending);s->pending_update=false;
    }
    if(!s->stopping&&s->phase>=s->end_phase){
        ainekio_v2_walk_controls_t c=controls_at(s,s->phase);c.stride_percent=0.;
        if(!ainekio_v2_walk_update(s,c))return false;
    }
    ainekio_v2_walk_controls_t c=controls_at(s,s->phase);
    double period=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_PERIOD:mixed(s,s->phase,V2_PERIOD,V2_RUN_PERIOD);
    double dp=dt*controls_at(s,s->phase+.5*dt*c.motion_rate/period).motion_rate/period;
    s->phase+=dp;
    const bool turning=s->direction==AINEKIO_WALK_TURN_LEFT||s->direction==AINEKIO_WALK_TURN_RIGHT;
    const bool sideways=s->direction>=AINEKIO_WALK_SIDE_LEFT;
    const double sign=s->direction==AINEKIO_WALK_BACKWARD||s->direction==AINEKIO_WALK_SIDE_RIGHT?-1.:1.;
    if(s->steering)steered_path(s,previous,s->phase,&s->body_x,&s->body_y,&s->body_yaw);
    else if(turning)s->body_yaw+=turn_travel(s,previous,s->phase);
    else if(sideways)s->body_y+=sign*travel(s,previous,s->phase);
    else s->body_x+=sign*travel(s,previous,s->phase);
    c=controls_at(s,s->phase);
    /* Intermediate substeps update contacts and anchors; only the emitted
     * pose needs world transforms and swing interpolation. */
    if(emit) {
        s->pose.phase=s->phase;s->pose.run_blend=run_at(s,s->phase);
        double height_phase=s->phase;
        /* Keep the height trajectory aligned with the changing footfall
         * schedule. Its fitted phase lead follows the mean offset shift;
         * a fixed global phase made returning Walk legs straighten under load. */
        for(unsigned leg=0;leg<4;leg++) {
            double shift=offset_at(s,leg,s->phase)-v2_walk_offsets[leg];
            if(s->direction==AINEKIO_WALK_BACKWARD)
                height_phase-=(shift-round(shift))*.25*V2_WALK_HEIGHT_REPHASE_GAIN;
        }
        body_pose(&s->pose,c.stride_percent,height_phase);
        double fore=s->pose.body[0],sway=s->pose.body[1];s->pose.body[0]=s->body_x+fore*cos(s->body_yaw)-sway*sin(s->body_yaw);
        s->pose.body[1]=s->body_y+fore*sin(s->body_yaw)+sway*cos(s->body_yaw);s->pose.euler[2]=s->body_yaw;
    }
    const bool settling=s->stopping&&c.stride_percent<1e-8&&!s->pending_update;
    bool resting=settling;
    const double contact=duty_at(s,s->phase),previous_contact=duty_at(s,previous);
    for(unsigned i=0;i<4;i++) {
        ainekio_v2_foot_state_t *f=&s->feet[i];double offset=offset_at(s,i,s->phase),previous_offset=offset_at(s,i,previous);
        if(f->swinging&&s->phase>=f->touchdown_phase){f->start_x=f->end_x;f->start_y=f->end_y;f->swinging=false;}
        bool transitioning=s->run_from!=s->run_target&&s->phase<s->run_transition_phase+V2_RUN_TRANSITION+1.;
        bool due=floor(s->phase-offset-contact)>floor(previous-previous_offset-previous_contact);
        if(transitioning && s->phase-offset-floor(s->phase-offset)>=contact)due=true;
        if(!f->swinging&&!settling&&due) {
            double cycle=floor(s->phase-offset);
            f->touchdown_phase=contact_event(s,i,cycle+1.,false,s->phase);
            double liftoff=contact_event(s,i,cycle,true,s->phase);
            f->swing_span=f->touchdown_phase-(transitioning?fmax(liftoff,s->phase):liftoff);
            double td=f->touchdown_phase;
            double stance_end=contact_event(s,i,cycle+1.,true,td);
            double stance=travel(s,td,stance_end),stance_middle=(td+stance_end)*.5;
            if(s->steering){
                double x=s->body_x,y=s->body_y,yaw=s->body_yaw;
                steered_path(s,s->phase,stance_middle,&x,&y,&yaw);
                double lane=s->gait_mode==AINEKIO_GAIT_CRAB?copysign(V2_CRAB_WIDTH,v2_walk_stance[i][1]):v2_walk_stance[i][1];
                if(s->gait_mode!=AINEKIO_GAIT_CRAB){
                    double bias=s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_BIAS/V2_CRAWL_SWEEP:mixed(s,td,V2_WALK_BIAS/V2_WALK_SWEEP,V2_RUN_FORWARD_BIAS/V2_RUN_FORWARD_SWEEP);
                    double translation=fabs(steering_at(s,td,0))/steering_scale(s,td);
                    x-=stance*bias*translation*cos(yaw);y-=stance*bias*translation*sin(yaw);
                    lane+=copysign(1.,lane)*(i<2?-1.:1.)*V2_RUN_FORWARD_LANE*run_at(s,td)*controls_at(s,td).stride_percent/100.;
                }
                f->end_x=x+v2_walk_stance[i][0]*cos(yaw)-lane*sin(yaw)-v2_walk_stance[i][0];
                f->end_y=y+v2_walk_stance[i][0]*sin(yaw)+lane*cos(yaw)-v2_walk_stance[i][1];
            } else if(turning){
                double yaw=s->body_yaw+turn_travel(s,s->phase,stance_middle);
                double x=v2_walk_stance[i][0],y=s->gait_mode==AINEKIO_GAIT_CRAB?copysign(V2_CRAB_WIDTH,v2_walk_stance[i][1]):v2_walk_stance[i][1];
                f->end_x=x*cos(yaw)-y*sin(yaw)-x;f->end_y=x*sin(yaw)+y*cos(yaw)-v2_walk_stance[i][1];
            } else if(s->gait_mode==AINEKIO_GAIT_CRAB){
                double lead=sign*(travel(s,s->phase,td)+stance*.5);
                f->end_x=s->body_x+(sideways?0.:lead);
                f->end_y=s->body_y+(sideways?lead:0.)+copysign(V2_CRAB_WIDTH,v2_walk_stance[i][1])-v2_walk_stance[i][1];
            } else {
                double bias=s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_BIAS/V2_CRAWL_SWEEP:mixed(s,td,V2_WALK_BIAS/V2_WALK_SWEEP,s->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_BIAS/V2_RUN_FORWARD_SWEEP:V2_RUN_BIAS/V2_RUN_SWEEP);
                /* Bias stays rearward in the physical body frame even when reversing. */
                f->end_x=s->body_x+sign*travel(s,s->phase,td)+stance*(sign*.5-bias);
                /* Select the next foot lane at liftoff and retain that target
                 * through swing. Existing stance anchors never move sideways.
                 * Source order RL/RR is the physical front pair. */
                double side=v2_walk_stance[i][1]>0.?1.:-1.;
                f->end_y=s->direction==AINEKIO_WALK_FORWARD?
                    side*(i<2?-1.:1.)*V2_RUN_FORWARD_LANE*run_at(s,td)*controls_at(s,td).stride_percent/100.:0.;
            }
            double lift=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_LIFT:s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_LIFT:mixed(s,s->phase,V2_WALK_LIFT,V2_RUN_LIFT);
            double min_lift=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_MIN_LIFT:s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_MIN_LIFT:mixed(s,s->phase,V2_WALK_MIN_LIFT,V2_RUN_MIN_LIFT);
            f->run_shape=1.;
            f->lift=min_lift+(lift-min_lift)*controls_at(s,s->stopping&&run_at(s,s->phase)>0. ? td : td-(1.-contact)/2.).stride_percent/100.;f->swinging=true;
        }
        if(emit) {
            double x=f->start_x,y=f->start_y,height=0.;
            if(f->swinging){double u=(s->phase-(f->touchdown_phase-f->swing_span))/f->swing_span;u=fmax(0.,fmin(1.,u));double horizontal=smooth(u)+f->run_shape*(run_swing(u)-smooth(u));x+=(f->end_x-f->start_x)*horizontal;y+=(f->end_y-f->start_y)*horizontal;double arch=bump(u);if(s->gait_mode!=AINEKIO_GAIT_RUN)arch+=(walk_lift(u)-arch)*(1.-run_at(s,s->phase));height=f->lift*arch;}
            s->pose.feet[i][0]=v2_walk_stance[i][0]+x;s->pose.feet[i][1]=v2_walk_stance[i][1]+y;s->pose.sole_height[i]=height;s->pose.grounded[i]=!f->swinging;
        }
        if(f->swinging)resting=false;
    }
    if(emit && s->steering && s->gait_mode==AINEKIO_GAIT_WALK && s->pose.run_blend<1.) {
        /* Turning brings the inside feet closer to their shoulder axes.
         * Preserve the straight-path shoulder-to-ground radius by allowing
         * the body to rise, instead of folding that leg farther at the same
         * height. Derive the rise from actual foot anchors and fixed shafts. */
        double co=cos(s->body_yaw),si=sin(s->body_yaw),rise=0.;
        double sway=-(s->pose.body[0]-s->body_x)*si+(s->pose.body[1]-s->body_y)*co;
        for(unsigned leg=0;leg<4;leg++) {
            double dx=s->pose.feet[leg][0]-s->pose.body[0],dy=s->pose.feet[leg][1]-s->pose.body[1];
            double lateral=-dx*si+dy*co-v2_walk_legs[leg].shoulder_translation[1];
            double nominal=v2_walk_stance[leg][1]-sway-v2_walk_legs[leg].shoulder_translation[1];
            double delta=nominal*nominal-lateral*lateral;
            if(delta>0.) {
                double height=v2_walk_legs[leg].shoulder_translation[2]+s->pose.body[2]-s->pose.sole_height[leg];
                rise=fmax(rise,delta/(sqrt(height*height+delta)+height));
            }
        }
        s->pose.body[2]+=rise*(1.-s->pose.run_blend)*fabs(steering_at(s,s->phase,1));
    }
    if(resting)s->complete=true;
    s->pose.frame.phase=s->complete?AINEKIO_V2_COMPLETE:(s->stopping?AINEKIO_V2_EXIT:(s->phase<2.?AINEKIO_V2_ENTRY:AINEKIO_V2_LOOP));
    s->pose.frame.cycle=(uint8_t)fmax(0.,fmin(255.,floor(s->phase-2.)));
    return true;
}
static bool advance_interval(ainekio_v2_walk_state_t *s,double seconds)
{
    unsigned steps=(unsigned)ceil(seconds/.004167);
    double dt=seconds/steps;
    for(unsigned i=0;i<steps;i++)if(!advance(s,dt,i+1==steps))return false;
    return ainekio_v2_walk_solve(&s->pose);
}

/* Swing apices and full-stroke reversals belong to the authored path. Emit
 * them as frame targets instead of integrating past them between output frames.
 * The next tick resumes immediately; there is no dwell or command clamp. */
static double walk_landmark(const ainekio_v2_walk_state_t *s)
{
    if(s->gait_mode!=AINEKIO_GAIT_WALK || run_at(s,s->phase)!=0.)return INFINITY;
    double next=INFINITY;
    for(unsigned i=0;i<4;i++)if(s->feet[i].swinging) {
        double apex=s->feet[i].touchdown_phase-.5*s->feet[i].swing_span;
        if(apex>s->phase+1e-9)next=fmin(next,apex);
    }
    if(controls_at(s,s->phase).stride_percent!=100. ||
       s->direction>AINEKIO_WALK_BACKWARD)return next;
    if(s->steering && (fabs(steering_at(s,s->phase,0))!=1. ||
       steering_at(s,s->phase,1)!=0.))return next;
    const double *points=s->direction==AINEKIO_WALK_BACKWARD?
        v2_walk_back_key_phases:v2_walk_key_phases;
    double cycle=floor(s->phase);
    for(unsigned i=0;i<8;i++) {
        double at=cycle+points[i];
        if(at<=s->phase+1e-9)at+=1.;
        next=fmin(next,at);
    }
    return next;
}

/* Traverse the existing coordinated path by angular distance, rather than
 * stretching a shorter stroke over a fixed cycle. The largest joint change
 * determines each small segment's duration; the other joints stay coordinated.
 * This is a commanded movement rate, not measured motor speed or torque.
 * No dwell, pulse clamp or new movement rejection is introduced. */
static bool advance_fast_stroke(ainekio_v2_walk_state_t *s,double seconds,double *reference_time)
{
    double remaining=seconds;
    *reference_time=0.;
    while(remaining>0. && !s->complete) {
        const ainekio_v2_walk_controls_t c=controls_at(s,s->phase);
        const double period=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_PERIOD:mixed(s,s->phase,V2_PERIOD,V2_RUN_PERIOD);
        double segment=period/(64.*c.motion_rate);
        const double event=walk_landmark(s);
        const double until=(event-s->phase)*period/c.motion_rate;
        const bool endpoint=until<=segment;
        if(endpoint)segment=until;
        ainekio_v2_walk_state_t next=*s;
        if(!advance_interval(&next,segment))return false;
        double distance=0.;
        for(unsigned j=0;j<12;j++)distance=fmax(distance,
            fabs(next.pose.frame.position[j]-s->pose.frame.position[j])/100.);
        const double duration=distance/V2_GAIT_MAX_JOINT_SPEED_DEGREES_S;
        if(duration<=remaining) {
            *s=next;
            remaining-=duration;
            *reference_time+=segment;
            if(endpoint)return true;
        } else {
            const double part=segment*remaining/duration;
            if(!advance_interval(s,part))return false;
            *reference_time+=part;
            remaining=0.;
        }
    }
    return true;
}

bool ainekio_v2_walk_tick(ainekio_v2_walk_state_t *s,uint64_t now)
{
    if(!s||!s->initialized||s->failed)return false;
    if(now<s->last_us){s->failed=true;return false;}
    if(s->complete){s->last_us=now;return true;}
    uint64_t elapsed=now-s->last_us;
    if(!elapsed)return true;
    const double seconds=elapsed/1e6, previous_phase=s->phase;
    /* Both timing modes advance the same body, contact and steering path.
     * Solve on a copy so failed IK cannot partly update contacts. */
    ainekio_v2_walk_state_t candidate=*s;
    const bool fast=s->fast_stroke;
    double reference_time=seconds;
    if(!(fast?advance_fast_stroke(&candidate,seconds,&reference_time):
              advance_interval(&candidate,seconds))){s->failed=true;return false;}
    ainekio_v2_frame_t before=s->pose.frame;
    *s=candidate;s->clock_scale=reference_time/seconds;s->speed_flagged=false;
    s->last_us=now;
    s->cycles_s=(s->phase-previous_phase)/seconds;
    const double period=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_PERIOD:mixed(s,s->phase,V2_PERIOD,V2_RUN_PERIOD);
    const ainekio_v2_walk_controls_t current=controls_at(s,s->phase);
    s->requested_cycles_s=fast?s->cycles_s:current.motion_rate/period;s->stride_percent=current.stride_percent;
    for(unsigned j=0;j<12;j++){
        double v=s->complete?0.:(s->pose.frame.position[j]-before.position[j])/(elapsed/1e6);
        s->pose.frame.velocity[j]=(float)v;s->pose.frame.acceleration[j]=s->complete?0.:(float)((v-before.velocity[j])/(elapsed/1e6));
    }
    return true;
}
bool ainekio_v2_walk_accept(ainekio_v2_walk_state_t *s,const ainekio_command_t *command,uint64_t now)
{
    uint8_t cycles;ainekio_v2_walk_controls_t controls={100.,1.};
    if(!s||!ainekio_v2_walk_request(command,&cycles)||command->sequence<1||command->sequence>AINEKIO_MAX_SEQUENCE)return false;
    const ainekio_intent_t *intent=&command->data.intent;
    double run_target=intent->data.walk.gait==AINEKIO_GAIT_RUN?1.:0.;
    if(intent->data.walk.controls==1){
        double speed=intent->data.walk.speed_percent;
        if(!isfinite(speed)||speed<0.||speed>200.||((intent->data.walk.gait==AINEKIO_GAIT_CRAWL||intent->data.walk.gait==AINEKIO_GAIT_CRAB)&&speed>100.))return false;
        if(intent->data.walk.gait==AINEKIO_GAIT_RUN||speed>100.){
            /* Open the Run stroke, lift and body bounding together from the
             * initial Run amplitude at 100% to its full envelope at 200%.
             * Explicit Run uses the same amplitude profile at lower speeds.
             * Angular travel sets stroke timing independently of Speed. */
            double stride=speed>100. ?
                100.*(V2_RUN_START_SWEEP+(V2_RUN_FORWARD_SWEEP-V2_RUN_START_SWEEP)*(speed-100.)/100.)/V2_RUN_FORWARD_SWEEP :
                speed*V2_RUN_START_SWEEP/V2_RUN_FORWARD_SWEEP;
            controls=(ainekio_v2_walk_controls_t){stride,2.};run_target=1.;
        } else if(intent->data.walk.gait==AINEKIO_GAIT_WALK){
            if(!ainekio_v2_walk_controls(speed,&controls))return false;
        } else controls=(ainekio_v2_walk_controls_t){speed,2.};
    }
    else if(intent->data.walk.controls==2){controls=(ainekio_v2_walk_controls_t){intent->data.walk.stride_percent,intent->data.walk.motion_rate};if(controls.stride_percent<1||!ainekio_v2_walk_controls_valid(controls))return false;}
    else if(intent->data.walk.controls!=0)return false;
    /* All semantic gait commands use angular-distance timing. Retain the
     * legacy rate field on the wire, but do not let it slow physical strokes.
     * A common reference rate also makes legacy requests geometrically identical. */
    controls.motion_rate=2.;
    const bool automatic_run=intent->data.walk.controls==1 && run_target==1. && controls.stride_percent>0.;
    const double requested_stride=controls.stride_percent;
    if(intent->data.walk.update_sequence){
        if(!s->initialized||s->failed||s->complete||intent->data.walk.controls==0||
           intent->data.walk.direction!=s->direction||intent->data.walk.gait!=s->gait_mode||
           intent->data.walk.update_sequence!=s->command_sequence||command->sequence<=s->latest_sequence||now!=s->last_us)return false;
        if(!ainekio_v2_walk_update(s,controls))return false;
        if(intent->data.walk.steering){
            s->forward_from=s->steering?100.*steering_at(s,s->phase,false):(s->direction==AINEKIO_WALK_BACKWARD?-100.:s->direction==AINEKIO_WALK_FORWARD?100.:0.);
            s->turn_from=s->steering?100.*steering_at(s,s->phase,true):(s->direction==AINEKIO_WALK_TURN_LEFT?100.:s->direction==AINEKIO_WALK_TURN_RIGHT?-100.:0.);
            s->lateral_from=s->steering?100.*steering_at(s,s->phase,2):(s->direction==AINEKIO_WALK_SIDE_LEFT?100.:s->direction==AINEKIO_WALK_SIDE_RIGHT?-100.:0.);
            s->lateral_target=intent->data.walk.lateral;
            s->forward_target=intent->data.walk.forward;s->turn_target=intent->data.walk.turn;s->steering_phase=s->phase;s->steering=true;
        }
        if(controls.stride_percent>0.)set_run_target(s,run_target);
        if(!s->pending_update && controls.stride_percent>0.)s->transition_span=control_transition_span(s,controls);
        if(automatic_run && s->phase==0.)s->transition_span=V2_RUN_TRANSITION;
        s->fast_stroke=true;
        s->automatic_run=automatic_run;s->requested_stride_percent=requested_stride;
        s->latest_sequence=command->sequence;return true;
    }
    if(s->initialized&&!s->complete)return false;
    /* A fresh automatic Run command starts in the Run geometry. There is no
     * preceding Walk to blend from; using the new maximum Walk envelope as
     * a synthetic starting gait gives Run inappropriate initial anchors.
     * Keep the command family for updates; active Walk-to-Run still blends. */
    ainekio_gait_t initial_gait=automatic_run?AINEKIO_GAIT_RUN:intent->data.walk.gait;
    if(!ainekio_v2_gait_begin(s,intent->data.walk.direction,initial_gait,cycles,controls,now))return false;
    s->gait_mode=intent->data.walk.gait;s->pose.gait=intent->data.walk.gait;
    if(intent->data.walk.steering){
        s->lateral_from=s->lateral_target=intent->data.walk.lateral;
        s->steering=true;s->forward_from=s->forward_target=intent->data.walk.forward;
        s->turn_from=s->turn_target=intent->data.walk.turn;
    }
    if(controls.stride_percent>0.)set_run_target(s,run_target);
    s->fast_stroke=true;
    s->automatic_run=automatic_run;s->requested_stride_percent=requested_stride;
    s->command_sequence=s->latest_sequence=command->sequence;return true;
}
