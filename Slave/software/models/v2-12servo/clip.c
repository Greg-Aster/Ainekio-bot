#include "ainekio/v2_motion.h"
#include "ainekio/trajectory.h"
#include "clip_data.h"
#include "ainekio/v2_walk.h"
#include <math.h>
#include <string.h>

float ainekio_v2_speed_limited_rate(double peak, float requested)
{
    if (!isfinite(peak) || peak < 0. || !isfinite(requested) || requested <= 0.F) return 0.F;
    const double limit = ainekio_v2_gait_joint_speed_limit();
    if (peak * requested > limit)
        return (float)(limit / peak);
    return requested;
}

bool ainekio_v2_clip_find(const char *name, size_t *index)
{
    if (!name || !index) return false;
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i) {
        if (!strncmp(name, ainekio_v2_clips[i].command, AINEKIO_ASSET_NAME_MAX + 1U)) {
            *index = i;
            return true;
        }
    }
    return false;
}

bool ainekio_v2_curve_expected_up(const ainekio_v2_curve_t *curve,double tick,float up[3])
{
    if(!curve || !curve->attitude || !curve->attitude->count || !up)return false;
    const ainekio_v2_clip_attitude_track_t *track=curve->attitude;
    if(tick>=track->knots[track->count-1] || track->count==1) {
        memcpy(up,track->up[track->count-1],3*sizeof(*up));return true;
    }
    size_t low=0,high=track->count-1;
    while(high-low>1) {
        const size_t middle=low+(high-low)/2;
        if(track->knots[middle]<=tick)low=middle;else high=middle;
    }
    const double u=(tick-track->knots[low])/(track->knots[high]-track->knots[low]);
    double length=0.;
    for(unsigned j=0;j<3;j++) {
        up[j]=(float)((1.-u)*track->up[low][j]+u*track->up[high][j]);
        length+=up[j]*up[j];
    }
    length=sqrt(length);if(!length)return false;
    for(unsigned j=0;j<3;j++)up[j]/=(float)length;
    return true;
}

bool ainekio_v2_clip_expected_up(size_t index,uint64_t elapsed_us,float up[3])
{
    ainekio_v2_curve_t curve;
    return ainekio_v2_clip_curve(index,&curve) &&
        ainekio_v2_curve_expected_up(&curve,(double)elapsed_us*curve.sample_hz/1e6,up);
}

bool ainekio_v2_clip_request(const ainekio_command_t *command, size_t *index)
{
    if (!command || !index || command->kind != AINEKIO_COMMAND_INTENT) return false;
    if (command->data.intent.kind == AINEKIO_INTENT_EMOTE) {
        size_t found;
        if (!ainekio_v2_clip_find(command->data.intent.data.asset, &found) ||
            ainekio_v2_clips[found].intent != AINEKIO_INTENT_EMOTE) return false;
        *index = found;
        return true;
    }
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i) {
        if (command->data.intent.kind == ainekio_v2_clips[i].intent) {
            *index = i;
            return true;
        }
    }
    return false;
}

bool ainekio_v2_clip_bounds(size_t index, ainekio_v2_frame_t *minimum,
                           ainekio_v2_frame_t *maximum)
{
    if (index >= ainekio_v2_clip_count || !minimum || !maximum || minimum == maximum)
        return false;
    const ainekio_v2_clip_track_t *track = &v2_clip_tracks[index];
    if (!track->count) return false;
    *minimum = (ainekio_v2_frame_t){.geometry_id=V2_CLIP_GEOMETRY_ID};
    *maximum = *minimum;
    /* Compiler retains extrema and proves every segment stays within its
     * endpoint range. Startup reads twelve extrema, not the entire recording. */
    memcpy(minimum->position, track->minimum, sizeof(minimum->position));
    memcpy(maximum->position, track->maximum, sizeof(maximum->position));
    return true;
}

bool ainekio_v2_curve_sample(const ainekio_v2_curve_t *curve, double tick, ainekio_v2_frame_t *frame)
{
    if (!curve || !curve->track || !frame) return false;
    const ainekio_v2_clip_track_t *track = curve->track;
    *frame = (ainekio_v2_frame_t){.geometry_id=curve->geometry_id};
    /* Check completion before scaling to keep arbitrary late times bounded.
     * Each clip is finite: hold its recorded terminal pose, never wrap/reset. */
    if (tick >= track->knots[track->count-1]) {
        frame->phase = AINEKIO_V2_COMPLETE;
        memcpy(frame->position, track->positions[track->count-1], sizeof(frame->position));
        return true;
    }
    frame->phase = tick*1000000. < track->active_end_us*curve->sample_hz ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    size_t low=0, high=track->count-1;
    while(high-low>1) {
        size_t middle=low+(high-low)/2;
        if(track->knots[middle]<=tick)low=middle;else high=middle;
    }
    const size_t knot=low;
    const double width=track->knots[high]-track->knots[low];
    const float fraction=(float)((tick-track->knots[low])/width);
    for (size_t joint = 0; joint < AINEKIO_V2_JOINT_COUNT; ++joint) {
        if (!ainekio_trajectory_sample(track->positions[knot][joint], track->positions[knot+1][joint],
            track->velocities[knot][joint], track->velocities[knot+1][joint], (float)width / curve->sample_hz,
            fraction, &frame->position[joint], &frame->velocity[joint], &frame->acceleration[joint])) return false;
    }
    return true;
}

bool ainekio_v2_clip_curve(size_t index, ainekio_v2_curve_t *curve)
{
    if(index>=ainekio_v2_clip_count || !curve)return false;
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    const char *name=ainekio_v2_clips[index].command;
    const bool posture=!strcmp(name,"sit") || !strcmp(name,"rest") || !strcmp(name,"crouch");
    *curve=(ainekio_v2_curve_t){.track=&v2_clip_tracks[index],.clock=clock,
        .sample_hz=V2_CLIP_SAMPLE_HZ,.duration_us=ainekio_v2_clips[index].duration_us,
        .geometry_id=V2_CLIP_GEOMETRY_ID,.attitude=&v2_clip_attitudes[index],
        .taper_degrees=posture?fmin(10.,.2*clock->knots[clock->count-1].travel_degrees):0.};
    return true;
}

bool ainekio_v2_curve_bounds(const ainekio_v2_curve_t *curve,
    ainekio_v2_frame_t *minimum,ainekio_v2_frame_t *maximum)
{
    if(!curve || !curve->track || curve->track->count<2 || !minimum || !maximum)return false;
    const ainekio_v2_clip_track_t *track=curve->track;
    *minimum=(ainekio_v2_frame_t){.geometry_id=curve->geometry_id};*maximum=*minimum;
    memcpy(minimum->position,track->positions[0],sizeof minimum->position);
    memcpy(maximum->position,track->positions[0],sizeof maximum->position);
    for(size_t i=0;i+1<track->count;i++)for(unsigned j=0;j<12;j++) {
        const double dt=(track->knots[i+1]-track->knots[i])/curve->sample_hz;
        const double p0=track->positions[i][j],p1=track->positions[i+1][j];
        const double m0=track->velocities[i][j]*dt,m1=track->velocities[i+1][j]*dt;
        const double a=2*p0-2*p1+m0+m1,b=-3*p0+3*p1-2*m0-m1;
        double roots[4]={0.,1.};unsigned count=2;
        if(fabs(a)>1e-15) {
            const double disc=4*b*b-12*a*m0;
            if(disc>=0.) { roots[count++]=(-2*b-sqrt(disc))/(6*a);roots[count++]=(-2*b+sqrt(disc))/(6*a); }
        } else if(fabs(b)>1e-15)roots[count++]=-m0/(2*b);
        for(unsigned r=0;r<count;r++)if(roots[r]>=0. && roots[r]<=1.) {
            const double u=roots[r],p=((a*u+b)*u+m0)*u+p0;
            if(!isfinite(p))return false;
            minimum->position[j]=fmin(minimum->position[j],p);
            maximum->position[j]=fmax(maximum->position[j],p);
        }
    }
    return true;
}

bool ainekio_v2_clip_sample(size_t index,uint64_t elapsed_us,ainekio_v2_frame_t *frame)
{
    ainekio_v2_curve_t curve;
    return ainekio_v2_clip_curve(index,&curve) &&
        ainekio_v2_curve_sample(&curve,(double)elapsed_us*curve.sample_hz/1000000.,frame);
}

static double travel_seconds(const ainekio_v2_curve_t *curve,double distance,double speed)
{
    const ainekio_v2_clip_clock_t *clock=curve->clock;
    const double total=clock->knots[clock->count-1].travel_degrees;
    const double taper=curve->taper_degrees,start=total-taper;
    if(!taper || distance<=start)return distance/speed;
    return start/speed+2.*taper/speed*(1.-sqrt(fmax(0.,(total-distance)/taper)));
}

static double travel_distance(const ainekio_v2_curve_t *curve,double seconds,double speed)
{
    const ainekio_v2_clip_clock_t *clock=curve->clock;
    const double total=clock->knots[clock->count-1].travel_degrees;
    const double taper=curve->taper_degrees,start=total-taper;
    if(!taper || seconds<=start/speed)return seconds*speed;
    const double u=fmax(0.,1.-(seconds*speed-start)/(2.*taper));
    return total-taper*u*u;
}

static double clock_seconds(const ainekio_v2_curve_t *curve,const ainekio_v2_clip_clock_knot_t *k,double speed)
{
    return travel_seconds(curve,k->travel_degrees,speed)+k->hold_seconds;
}

double ainekio_v2_curve_seconds(const ainekio_v2_curve_t *curve, double speed)
{
    if(!curve || !curve->clock || !isfinite(speed) || speed<=0.)
        return NAN;
    const ainekio_v2_clip_clock_t *clock=curve->clock;
    return clock_seconds(curve,&clock->knots[clock->count-1],speed);
}

bool ainekio_v2_curve_playback(const ainekio_v2_curve_t *curve, double seconds, double speed,
    bool reverse, ainekio_v2_frame_t *frame, uint64_t *source_us)
{
    const double duration=ainekio_v2_curve_seconds(curve,speed);
    if(!frame || !source_us || !isfinite(duration) || !isfinite(seconds) || seconds<0.)return false;
    const ainekio_v2_clip_clock_t *clock=curve->clock;
    const bool complete=seconds>=duration;
    double time=fmin(seconds,duration);
    if(reverse)time=duration-time;
    size_t low=0,high=clock->count-1;
    while(high-low>1) {
        const size_t middle=low+(high-low)/2;
        if(clock_seconds(curve,&clock->knots[middle],speed)<=time)low=middle;else high=middle;
    }
    const ainekio_v2_clip_clock_knot_t *a=&clock->knots[low],*b=&clock->knots[high];
    const double start=clock_seconds(curve,a,speed),end=clock_seconds(curve,b,speed);
    const bool held=b->hold_seconds>a->hold_seconds;
    const double distance=travel_distance(curve,time-a->hold_seconds,speed);
    const double fraction=held ? fmax(0.,fmin(1.,(time-start)/(end-start))) :
        b->travel_degrees>a->travel_degrees ?
        fmax(0.,fmin(1.,(distance-a->travel_degrees)/(b->travel_degrees-a->travel_degrees))) : 1.;
    double tick=a->tick+(b->tick-a->tick)*fraction;
    if(!held && fraction>0. && fraction<1.) {
        /* This interval has one fastest joint. Invert its monotone cubic
         * angle, retaining the exact coordinated path of every other joint. */
        const ainekio_v2_clip_track_t *track=curve->track;
        const unsigned j=a->joint,k=a->segment;
        const double width=track->knots[k+1]-track->knots[k],dt=width/curve->sample_hz;
        const double delta=(double)track->positions[k+1][j]-track->positions[k][j];
        const double m0=track->velocities[k][j]*dt,m1=track->velocities[k+1][j]*dt;
        const double c3=m0+m1-2.*delta,c2=3.*delta-2.*m0-m1;
        double lo=(a->tick-track->knots[k])/width,hi=(b->tick-track->knots[k])/width;
        const double p0=lo*(m0+lo*(c2+lo*c3)),p1=hi*(m0+hi*(c2+hi*c3));
        const double target=p0+(p1-p0)*fraction;
        for(unsigned n=0;n<32;n++) {
            const double u=(lo+hi)*.5,p=u*(m0+u*(c2+u*c3));
            if((p<target)==(p1>p0))lo=u;else hi=u;
        }
        tick=track->knots[k]+width*(lo+hi)*.5;
    }
    if(complete)tick=reverse ? 0. : clock->knots[clock->count-1].tick;
    if(!ainekio_v2_curve_sample(curve,tick,frame))return false;
    *source_us=(uint64_t)llround(tick*1000000./curve->sample_hz);
    if(complete)frame->phase=AINEKIO_V2_COMPLETE;
    else frame->phase=*source_us<curve->track->active_end_us ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    double peak=0.;unsigned fastest=0;
    for(unsigned j=0;j<12;j++)if(fabs(frame->velocity[j])>peak) {
        peak=fabs(frame->velocity[j]);fastest=j;
    }
    const double total=clock->knots[clock->count-1].travel_degrees;
    const double taper=curve->taper_degrees;
    const bool slowing=taper>0. && distance>total-taper;
    const double velocity=slowing ? speed*sqrt(fmax(0.,(total-distance)/taper)) : speed;
    const double deceleration=slowing ? -speed*speed/(2.*taper) : 0.;
    const double scale=!held && !complete && peak>0. ? velocity*100./peak : 0.;
    const double curvature=scale>0. ? frame->acceleration[fastest]/frame->velocity[fastest] : 0.;
    for(unsigned j=0;j<12;j++) {
        frame->acceleration[j]=(float)(scale*scale*(frame->acceleration[j]-frame->velocity[j]*curvature)+
            (scale>0. ? frame->velocity[j]*scale*deceleration/velocity : 0.));
        frame->velocity[j]*=(float)(reverse ? -scale : scale);
    }
    return true;
}

bool ainekio_v2_curve_player_tick(const ainekio_v2_curve_t *curve,ainekio_v2_clip_player_t *player,
    double seconds,double speed,bool arrived,
    ainekio_v2_frame_t *frame,uint64_t *source_us)
{
    if(!player || !frame || !source_us || !isfinite(seconds) || seconds<0. ||
       !isfinite(ainekio_v2_curve_seconds(curve,speed)))return false;
    const ainekio_v2_clip_clock_t *clock=curve->clock;
    if(player->waiting && arrived) {
        player->waiting=false;
        player->target++;
        seconds=0.; /* Arrival starts the next phase, including its full hold. */
    }
    if(player->target>=clock->target_count) {
        *source_us=curve->duration_us;
        return ainekio_v2_curve_sample(curve,clock->knots[clock->count-1].tick,frame);
    }
    const double tick=clock->targets[player->target];
    size_t lo=0,hi=clock->count-1;
    while(lo<hi) {
        const size_t mid=lo+(hi-lo)/2;
        if(clock->knots[mid].tick<tick)lo=mid+1;else hi=mid;
    }
    /* Compiler retains each target as an exact clock/trajectory knot. */
    const double target_time=clock_seconds(curve,&clock->knots[lo],speed);
    if(!player->waiting) {
        player->seconds=fmin(target_time,player->seconds+seconds);
        player->waiting=player->seconds>=target_time;
    }
    if(player->waiting) {
        if(!ainekio_v2_curve_sample(curve,tick,frame))return false;
        *source_us=(uint64_t)llround(tick*1000000./curve->sample_hz);
        memset(frame->velocity,0,sizeof frame->velocity);
        memset(frame->acceleration,0,sizeof frame->acceleration);
    } else if(!ainekio_v2_curve_playback(curve,player->seconds,speed,false,frame,source_us))return false;
    /* The terminal pose is not completion until the output owner confirms it. */
    frame->phase=*source_us<curve->track->active_end_us ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    return true;
}

/* Native entrypoints retain their public contract and delegate to the same
 * generated-curve player. No independent playback clock is introduced. */
double ainekio_v2_clip_playback_seconds(size_t index,double speed,float rate)
{
    ainekio_v2_curve_t curve;
    return isfinite(rate) && rate>0.F && ainekio_v2_clip_curve(index,&curve) ?
        ainekio_v2_curve_seconds(&curve,speed):NAN;
}
bool ainekio_v2_clip_playback_sample(size_t index,double seconds,double speed,float rate,
    bool reverse,ainekio_v2_frame_t *frame,uint64_t *source_us)
{
    ainekio_v2_curve_t curve;
    return isfinite(rate) && rate>0.F && ainekio_v2_clip_curve(index,&curve) &&
        ainekio_v2_curve_playback(&curve,seconds,speed,reverse,frame,source_us);
}
bool ainekio_v2_clip_player_tick(size_t index,ainekio_v2_clip_player_t *player,
    double seconds,double speed,float rate,bool arrived,ainekio_v2_frame_t *frame,uint64_t *source_us)
{
    ainekio_v2_curve_t curve;
    return isfinite(rate) && rate>0.F && ainekio_v2_clip_curve(index,&curve) &&
        ainekio_v2_curve_player_tick(&curve,player,seconds,speed,arrived,frame,source_us);
}
