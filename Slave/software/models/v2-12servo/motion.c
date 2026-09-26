#include "ainekio/v2_walk.h"
#include "walk_data.h"
#include <math.h>
#include <string.h>

static const double pi=3.14159265358979323846;
static double smooth(double u) {if(u<=0.)return 0.;if(u>=1.)return 1.;return u*u*u*(10.+u*(-15.+6.*u));}
static double bump(double u) {return 64.*u*u*u*(1.-u)*(1.-u)*(1.-u);}

bool ainekio_v2_walk_controls_valid(ainekio_v2_walk_controls_t c)
{
    return isfinite(c.stride_percent)&&isfinite(c.motion_rate)&&c.stride_percent>=0.&&c.stride_percent<=100.&&c.motion_rate>=.25&&c.motion_rate<=3.;
}
bool ainekio_v2_walk_controls(double speed,ainekio_v2_walk_controls_t *out)
{
    if(!out||!isfinite(speed)||speed<0||speed>100)return false;
    *out=(ainekio_v2_walk_controls_t){fmin(100.,2.*speed),fmax(1.,speed/50.)};return true;
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
static double duty_at(const ainekio_v2_walk_state_t *s,double phase) {return s->gait_mode==AINEKIO_GAIT_CRAB?.75:mixed(s,phase,V2_DUTY,V2_RUN_DUTY);}
static double sweep_at(const ainekio_v2_walk_state_t *s,double phase) {return s->gait_mode==AINEKIO_GAIT_CRAB?(s->direction>=AINEKIO_WALK_SIDE_LEFT?V2_CRAB_SIDE_SWEEP:V2_CRAB_SWEEP):s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_SWEEP:mixed(s,phase,V2_SWEEP,s->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_SWEEP:V2_RUN_SWEEP);}
static double offset_at(const ainekio_v2_walk_state_t *s,unsigned leg,double phase) {return s->offset_from[leg]==s->offset_target[leg]?s->offset_from[leg]:s->offset_from[leg]+(s->offset_target[leg]-s->offset_from[leg])*smooth((phase-s->run_transition_phase)/V2_RUN_TRANSITION);}
static void set_run_target(ainekio_v2_walk_state_t *s,double target)
{
    if(s->run_target==target)return;
    for(unsigned i=0;i<4;i++) {
        double offset=offset_at(s,i,s->phase),next=target?(i<2?0.:.5):v2_walk_offsets[i];
        /* Equivalent cyclic phases always advance liftoff. Delaying a planted
         * foot to synchronize pairs would overextend its existing stance. */
        next+=floor(offset-next+1e-9);
        s->offset_from[i]=offset;s->offset_target[i]=next;
    }
    s->run_from=run_at(s,s->phase);s->run_target=target;s->run_transition_phase=s->phase;
}
static void body_pose(ainekio_v2_walk_pose_t *p,double stride)
{
    if(p->gait==AINEKIO_GAIT_CRAB){p->body[1]=0.;p->body[2]=V2_CRAB_BODY_Z;p->euler[0]=p->euler[1]=p->euler[2]=0.;return;}
    double strength=stride/100.,a=2.*pi*p->phase;
    p->body[1]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_SWAY:V2_SWAY)*strength*sin(a);
    p->body[2]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_BODY_Z:V2_BODY_Z)+(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_BOB:V2_BOB)*strength*cos(2*a);
    p->euler[0]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_ROLL:V2_ROLL)*strength*sin(a);p->euler[1]=(p->gait==AINEKIO_GAIT_CRAWL?V2_CRAWL_PITCH:V2_PITCH)*strength*sin(2*a);p->euler[2]=0.;
    if(p->run_blend>0.) {
        /* Paired front stance, flight, paired rear stance, flight. This is a
         * kinematic reference, not a force/balance controller. */
        double z=V2_BODY_Z+((p->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_BODY_Z:V2_RUN_BODY_Z)-V2_BODY_Z)*smooth(p->phase/3.)+V2_RUN_BOB*strength*cos(2.*a-4.*pi*(V2_RUN_DUTY+.5)/2.);
        double pitch=(V2_RUN_PITCH*sin(a)+(p->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_PITCH_BIAS:0.))*strength;
        p->body[1]*=1.-p->run_blend;p->euler[0]*=1.-p->run_blend;
        p->body[2]+=(z-p->body[2])*p->run_blend;
        p->euler[1]+=(pitch-p->euler[1])*p->run_blend;
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
    double advance=V2_SWEEP*c.stride_percent/100./V2_DUTY;
    target.body[0]=phase*advance;body_pose(&target,c.stride_percent);
    for(unsigned i=0;i<4;i++) {
        double touchdown=floor(phase-v2_walk_offsets[i])+v2_walk_offsets[i],local=phase-touchdown;
        double anchor=touchdown*advance+V2_DUTY*advance*(.5-V2_BIAS/V2_SWEEP),height=0.;
        if(local>=V2_DUTY){double u=(local-V2_DUTY)/(1.-V2_DUTY);anchor+=advance*smooth(u);height=(V2_MIN_LIFT+(V2_LIFT-V2_MIN_LIFT)*c.stride_percent/100.)*bump(u);}
        target.feet[i][0]=v2_walk_stance[i][0]+anchor;target.sole_height[i]=height;target.grounded[i]=local<V2_DUTY;
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
                (float)V2_SWEEP+(run_sweep-(float)V2_SWEEP)*run;
            ratio=sweep/(s->gait_mode==AINEKIO_GAIT_CRAB?.75f:((float)V2_DUTY+((float)V2_RUN_DUTY-(float)V2_DUTY)*run));
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
bool ainekio_v2_gait_begin(ainekio_v2_walk_state_t *s,ainekio_walk_direction_t direction,ainekio_gait_t gait,unsigned cycles,ainekio_v2_walk_controls_t c,uint64_t now)
{
    if(!s||direction>AINEKIO_WALK_SIDE_RIGHT||gait>AINEKIO_GAIT_CRAB||(direction>=AINEKIO_WALK_SIDE_LEFT&&gait!=AINEKIO_GAIT_CRAB)||cycles>10||!ainekio_v2_walk_controls_valid(c))return false;
    /* Give the wide Crab stance two cycles to establish its first anchors.
     * A one-cycle launch left too little margin at the planted inside leg. */
    *s=(ainekio_v2_walk_state_t){.last_us=now,.end_phase=cycles?2.+cycles:INFINITY,.direction=direction,.gait_mode=gait,.run_from=gait==AINEKIO_GAIT_RUN?1.:0.,.run_target=gait==AINEKIO_GAIT_RUN?1.:0.,.transition_span=direction==AINEKIO_WALK_BACKWARD||gait==AINEKIO_GAIT_RUN?3.:gait==AINEKIO_GAIT_CRAB?V2_CRAB_STARTUP_CYCLES:1.,.from={0.,1.},.target=c,.stopping=c.stride_percent==0.};
    for(unsigned i=0;i<4;i++)s->offset_from[i]=s->offset_target[i]=gait==AINEKIO_GAIT_CRAB?v2_crab_offsets[i]:gait==AINEKIO_GAIT_RUN?(i<2?0.:.5):v2_walk_offsets[i];
    if(!standing(&s->pose,V2_BODY_Z)){s->failed=true;return false;}
    s->pose.gait=gait;s->pose.direction=direction;s->pose.run_blend=s->run_target;
    if(gait==AINEKIO_GAIT_CRAWL&&!ainekio_v2_walk_solve(&s->pose)){s->failed=true;return false;}
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
bool ainekio_v2_walk_update(ainekio_v2_walk_state_t *s,ainekio_v2_walk_controls_t c)
{
    if(!s||!s->initialized||s->failed||s->complete||!ainekio_v2_walk_controls_valid(c))return false;
    if(s->stopping&&c.stride_percent>0.)return false; /* A stopped command is never resurrected. */
    if((s->gait_mode==AINEKIO_GAIT_CRAB&&s->preparation_seconds<V2_CRAB_ENTRY)||
       (s->pose.gait==AINEKIO_GAIT_CRAWL&&s->preparation_seconds<V2_CRAWL_ENTRY)){
        s->target=c;s->pending_update=false;
        if(c.stride_percent==0.)s->stopping=true;
        return true;
    }
    if(s->phase<s->transition_phase+s->transition_span){s->pending=c;s->pending_update=true;}
    else {s->from=controls_at(s,s->phase);s->target=c;s->transition_phase=control_transition_start(s,c);s->transition_span=1.;}
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
        s->pose.body[2]=V2_BODY_Z+(V2_CRAWL_BODY_Z-V2_BODY_Z)*smooth(s->preparation_seconds/V2_CRAWL_ENTRY);
        if(s->stopping&&s->preparation_seconds>=V2_CRAWL_ENTRY){s->complete=true;s->pose.frame.phase=AINEKIO_V2_COMPLETE;}
        return true;
    }
    double previous=s->phase;
    if(s->pending_update&&s->phase>=s->transition_phase+s->transition_span){
        s->from=s->target;s->target=s->pending;s->transition_phase=control_transition_start(s,s->pending);s->transition_span=1.;s->pending_update=false;
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
    if(turning)s->body_yaw+=turn_travel(s,previous,s->phase);
    else if(sideways)s->body_y+=sign*travel(s,previous,s->phase);
    else s->body_x+=sign*travel(s,previous,s->phase);
    c=controls_at(s,s->phase);
    /* Intermediate substeps update contacts and anchors; only the emitted
     * pose needs world transforms and swing interpolation. */
    if(emit) {
        s->pose.phase=s->phase;s->pose.run_blend=run_at(s,s->phase);body_pose(&s->pose,c.stride_percent);
        double sway=s->pose.body[1];s->pose.body[0]=s->body_x-sway*sin(s->body_yaw);
        s->pose.body[1]=s->body_y+sway*cos(s->body_yaw);s->pose.euler[2]=s->body_yaw;
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
            f->touchdown_phase=floor(s->phase-offset)+offset+1.;f->swing_span=transitioning?f->touchdown_phase-s->phase:1.-contact;
            double td=f->touchdown_phase,stance=travel(s,td,td+duty_at(s,td));
            if(turning){
                double yaw=s->body_yaw+turn_travel(s,s->phase,td+contact*.5);
                double x=v2_walk_stance[i][0],y=s->gait_mode==AINEKIO_GAIT_CRAB?copysign(V2_CRAB_WIDTH,v2_walk_stance[i][1]):v2_walk_stance[i][1];
                f->end_x=x*cos(yaw)-y*sin(yaw)-x;f->end_y=x*sin(yaw)+y*cos(yaw)-v2_walk_stance[i][1];
            } else if(s->gait_mode==AINEKIO_GAIT_CRAB){
                double lead=sign*(travel(s,s->phase,td)+stance*.5);
                f->end_x=s->body_x+(sideways?0.:lead);
                f->end_y=s->body_y+(sideways?lead:0.)+copysign(V2_CRAB_WIDTH,v2_walk_stance[i][1])-v2_walk_stance[i][1];
            } else {
                double bias=s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_BIAS/V2_CRAWL_SWEEP:mixed(s,td,V2_BIAS/V2_SWEEP,s->direction==AINEKIO_WALK_FORWARD?V2_RUN_FORWARD_BIAS/V2_RUN_FORWARD_SWEEP:V2_RUN_BIAS/V2_RUN_SWEEP);
                /* Bias stays rearward in the physical body frame even when reversing. */
                f->end_x=s->body_x+sign*travel(s,s->phase,td)+stance*(sign*.5-bias);
                /* Select the next foot lane at liftoff and retain that target
                 * through swing. Existing stance anchors never move sideways.
                 * Source order RL/RR is the physical front pair. */
                double side=v2_walk_stance[i][1]>0.?1.:-1.;
                f->end_y=s->direction==AINEKIO_WALK_FORWARD?
                    side*(i<2?-1.:1.)*V2_RUN_FORWARD_LANE*run_at(s,td)*controls_at(s,td).stride_percent/100.:0.;
            }
            double lift=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_LIFT:s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_LIFT:mixed(s,s->phase,V2_LIFT,V2_RUN_LIFT);
            double min_lift=s->gait_mode==AINEKIO_GAIT_CRAB?V2_CRAB_MIN_LIFT:s->gait_mode==AINEKIO_GAIT_CRAWL?V2_CRAWL_MIN_LIFT:mixed(s,s->phase,V2_MIN_LIFT,V2_RUN_MIN_LIFT);
            f->lift=min_lift+(lift-min_lift)*controls_at(s,td-(1.-contact)/2.).stride_percent/100.;f->swinging=true;
        }
        if(emit) {
            double x=f->start_x,y=f->start_y,height=0.;
            if(f->swinging){double u=(s->phase-(f->touchdown_phase-f->swing_span))/f->swing_span;u=fmax(0.,fmin(1.,u));x+=(f->end_x-f->start_x)*smooth(u);y+=(f->end_y-f->start_y)*smooth(u);height=f->lift*bump(u);}
            s->pose.feet[i][0]=v2_walk_stance[i][0]+x;s->pose.feet[i][1]=v2_walk_stance[i][1]+y;s->pose.sole_height[i]=height;s->pose.grounded[i]=!f->swinging;
        }
        if(f->swinging)resting=false;
    }
    if(resting)s->complete=true;
    s->pose.frame.phase=s->complete?AINEKIO_V2_COMPLETE:(s->stopping?AINEKIO_V2_EXIT:(s->phase<2.?AINEKIO_V2_ENTRY:AINEKIO_V2_LOOP));
    s->pose.frame.cycle=(uint8_t)fmax(0.,fmin(255.,floor(s->phase-2.)));
    return true;
}
bool ainekio_v2_walk_tick(ainekio_v2_walk_state_t *s,uint64_t now)
{
    if(!s||!s->initialized||s->failed)return false;
    if(now<s->last_us){s->failed=true;return false;}
    if(s->complete){s->last_us=now;return true;}
    uint64_t elapsed=now-s->last_us;
    if(elapsed>40000){s->failed=true;return false;} /* fault, never replay missed output */
    if(!elapsed)return true;
    unsigned steps=(unsigned)((elapsed+4166)/4167);double dt=elapsed/1e6/steps;
    ainekio_v2_frame_t before=s->pose.frame;
    for(unsigned i=0;i<steps;i++)if(!advance(s,dt,i+1==steps)){s->failed=true;return false;}
    /* Contact/control integration retains its small steps. Only the final pose
     * is emitted, so solve that pose once from the previous output's joints. */
    if(!ainekio_v2_walk_solve(&s->pose)){s->failed=true;return false;}
    s->last_us=now;
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
            double stride=fmin(100.,2.*speed);
            if(intent->data.walk.gait==AINEKIO_GAIT_WALK&&intent->data.walk.direction==AINEKIO_WALK_FORWARD)
                stride=100.*(V2_RUN_SWEEP+(V2_RUN_FORWARD_SWEEP-V2_RUN_SWEEP)*(speed-100.)/100.)/V2_RUN_FORWARD_SWEEP;
            controls=(ainekio_v2_walk_controls_t){stride,intent->data.walk.gait==AINEKIO_GAIT_RUN?fmax(2./3.,speed/75.):2.+(speed-100.)/150.};run_target=1.;
        } else if(!ainekio_v2_walk_controls(speed,&controls))return false;
    }
    else if(intent->data.walk.controls==2){controls=(ainekio_v2_walk_controls_t){intent->data.walk.stride_percent,intent->data.walk.motion_rate};if(controls.stride_percent<1||!ainekio_v2_walk_controls_valid(controls))return false;}
    else if(intent->data.walk.controls!=0)return false;
    if(intent->data.walk.update_sequence){
        if(!s->initialized||s->failed||s->complete||intent->data.walk.controls==0||
           intent->data.walk.direction!=s->direction||intent->data.walk.gait!=s->gait_mode||
           intent->data.walk.update_sequence!=s->command_sequence||command->sequence<=s->latest_sequence||now!=s->last_us)return false;
        if(!ainekio_v2_walk_update(s,controls))return false;
        if(controls.stride_percent>0.)set_run_target(s,run_target);
        s->latest_sequence=command->sequence;return true;
    }
    if(s->initialized&&!s->complete)return false;
    if(!ainekio_v2_gait_begin(s,intent->data.walk.direction,intent->data.walk.gait,cycles,controls,now))return false;
    if(controls.stride_percent>0.)set_run_target(s,run_target);
    s->command_sequence=s->latest_sequence=command->sequence;return true;
}
