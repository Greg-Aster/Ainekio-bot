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

bool ainekio_v2_clip_expected_up(size_t index, uint64_t elapsed_us, float up[3])
{
    if(index>=ainekio_v2_clip_count || !up)return false;
    const ainekio_v2_clip_attitude_track_t *track=&v2_clip_attitudes[index];
    const uint64_t duration=ainekio_v2_clips[index].duration_us;
    if(elapsed_us>=duration) {
        memcpy(up,track->up[track->count-1],3*sizeof(*up));
        return true;
    }
    const double knot=(double)elapsed_us*V2_CLIP_SAMPLE_HZ/1000000.;
    size_t low=0,high=track->count-1;
    while(high-low>1) {
        const size_t middle=low+(high-low)/2;
        if(track->knots[middle]<=knot)low=middle;else high=middle;
    }
    const double u=(knot-track->knots[low])/(track->knots[high]-track->knots[low]);
    double length=0.;
    for(unsigned j=0;j<3;j++) {
        up[j]=(float)((1.-u)*track->up[low][j]+u*track->up[high][j]);
        length+=up[j]*up[j];
    }
    length=sqrt(length);
    for(unsigned j=0;j<3;j++)up[j]/=(float)length;
    return true;
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

static bool sample_tick(size_t index, double tick, ainekio_v2_frame_t *frame)
{
    if (index >= ainekio_v2_clip_count || !frame) return false;
    const ainekio_v2_clip_track_t *track = &v2_clip_tracks[index];
    *frame = (ainekio_v2_frame_t){.geometry_id=V2_CLIP_GEOMETRY_ID};
    /* Check completion before scaling to keep arbitrary late times bounded.
     * Each clip is finite: hold its recorded terminal pose, never wrap/reset. */
    if (tick >= track->knots[track->count-1]) {
        frame->phase = AINEKIO_V2_COMPLETE;
        memcpy(frame->position, track->positions[track->count-1], sizeof(frame->position));
        return true;
    }
    frame->phase = tick*1000000. < track->active_end_us*V2_CLIP_SAMPLE_HZ ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    size_t low=0, high=track->count-1;
    while(high-low>1) {
        size_t middle=low+(high-low)/2;
        if(track->knots[middle]<=tick)low=middle;else high=middle;
    }
    const size_t knot=low;
    const unsigned width=track->knots[high]-track->knots[low];
    const float fraction=(float)((tick-track->knots[low])/width);
    for (size_t joint = 0; joint < AINEKIO_V2_JOINT_COUNT; ++joint) {
        if (!ainekio_trajectory_sample(track->positions[knot][joint], track->positions[knot+1][joint],
            track->velocities[knot][joint], track->velocities[knot+1][joint], (float)width / V2_CLIP_SAMPLE_HZ,
            fraction, &frame->position[joint], &frame->velocity[joint], &frame->acceleration[joint])) return false;
    }
    return true;
}

bool ainekio_v2_clip_sample(size_t index, uint64_t elapsed_us, ainekio_v2_frame_t *frame)
{
    return sample_tick(index, (double)elapsed_us*V2_CLIP_SAMPLE_HZ/1000000., frame);
}

static double taper_distance(size_t index)
{
    const char *name=ainekio_v2_clips[index].command;
    if(strcmp(name,"sit") && strcmp(name,"rest") && strcmp(name,"crouch"))return 0.;
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    return fmin(10.,.2*clock->knots[clock->count-1].travel_degrees);
}

static double travel_seconds(size_t index,double distance,double speed)
{
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    const double total=clock->knots[clock->count-1].travel_degrees;
    const double taper=taper_distance(index),start=total-taper;
    if(!taper || distance<=start)return distance/speed;
    return start/speed+2.*taper/speed*(1.-sqrt(fmax(0.,(total-distance)/taper)));
}

static double travel_distance(size_t index,double seconds,double speed)
{
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    const double total=clock->knots[clock->count-1].travel_degrees;
    const double taper=taper_distance(index),start=total-taper;
    if(!taper || seconds<=start/speed)return seconds*speed;
    const double u=fmax(0.,1.-(seconds*speed-start)/(2.*taper));
    return total-taper*u*u;
}

static double clock_seconds(size_t index,const ainekio_v2_clip_clock_knot_t *k,double speed)
{
    return travel_seconds(index,k->travel_degrees,speed)+k->hold_seconds;
}

double ainekio_v2_clip_playback_seconds(size_t index, double speed, float rate)
{
    if(index>=ainekio_v2_clip_count || !isfinite(speed) || speed<=0. || !isfinite(rate) || rate<=0.F)
        return NAN;
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    return clock_seconds(index,&clock->knots[clock->count-1],speed);
}

bool ainekio_v2_clip_playback_sample(size_t index, double seconds, double speed,
    float rate, bool reverse, ainekio_v2_frame_t *frame, uint64_t *source_us)
{
    const double duration=ainekio_v2_clip_playback_seconds(index,speed,rate);
    if(!frame || !source_us || !isfinite(duration) || !isfinite(seconds) || seconds<0.)return false;
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    const bool complete=seconds>=duration;
    double time=fmin(seconds,duration);
    if(reverse)time=duration-time;
    size_t low=0,high=clock->count-1;
    while(high-low>1) {
        const size_t middle=low+(high-low)/2;
        if(clock_seconds(index,&clock->knots[middle],speed)<=time)low=middle;else high=middle;
    }
    const ainekio_v2_clip_clock_knot_t *a=&clock->knots[low],*b=&clock->knots[high];
    const double start=clock_seconds(index,a,speed),end=clock_seconds(index,b,speed);
    const bool held=b->hold_seconds>a->hold_seconds;
    const double distance=travel_distance(index,time-a->hold_seconds,speed);
    const double fraction=held ? fmax(0.,fmin(1.,(time-start)/(end-start))) :
        b->travel_degrees>a->travel_degrees ?
        fmax(0.,fmin(1.,(distance-a->travel_degrees)/(b->travel_degrees-a->travel_degrees))) : 1.;
    double tick=a->tick+(b->tick-a->tick)*fraction;
    if(!held && fraction>0. && fraction<1.) {
        /* This interval has one fastest joint. Invert its monotone cubic
         * angle, retaining the exact coordinated path of every other joint. */
        const ainekio_v2_clip_track_t *track=&v2_clip_tracks[index];
        const unsigned j=a->joint,k=a->segment;
        const double width=track->knots[k+1]-track->knots[k],dt=width/V2_CLIP_SAMPLE_HZ;
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
    if(!sample_tick(index,tick,frame))return false;
    *source_us=(uint64_t)llround(tick*1000000./V2_CLIP_SAMPLE_HZ);
    if(complete)frame->phase=AINEKIO_V2_COMPLETE;
    else frame->phase=*source_us<v2_clip_tracks[index].active_end_us ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    double peak=0.;unsigned fastest=0;
    for(unsigned j=0;j<12;j++)if(fabs(frame->velocity[j])>peak) {
        peak=fabs(frame->velocity[j]);fastest=j;
    }
    const double total=clock->knots[clock->count-1].travel_degrees;
    const double taper=taper_distance(index);
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

bool ainekio_v2_clip_player_tick(size_t index,ainekio_v2_clip_player_t *player,
    double seconds,double speed,float rate,bool arrived,
    ainekio_v2_frame_t *frame,uint64_t *source_us)
{
    if(!player || !frame || !source_us || !isfinite(seconds) || seconds<0. ||
       !isfinite(ainekio_v2_clip_playback_seconds(index,speed,rate)))return false;
    const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[index];
    if(player->waiting && arrived) {
        player->waiting=false;
        player->target++;
        seconds=0.; /* Arrival starts the next phase, including its full hold. */
    }
    if(player->target>=clock->target_count) {
        *source_us=ainekio_v2_clips[index].duration_us;
        return sample_tick(index,clock->knots[clock->count-1].tick,frame);
    }
    const double tick=clock->targets[player->target];
    size_t lo=0,hi=clock->count-1;
    while(lo<hi) {
        const size_t mid=lo+(hi-lo)/2;
        if(clock->knots[mid].tick<tick)lo=mid+1;else hi=mid;
    }
    /* Compiler retains each target as an exact clock/trajectory knot. */
    const double target_time=clock_seconds(index,&clock->knots[lo],speed);
    if(!player->waiting) {
        player->seconds=fmin(target_time,player->seconds+seconds);
        player->waiting=player->seconds>=target_time;
    }
    if(player->waiting) {
        if(!sample_tick(index,tick,frame))return false;
        *source_us=(uint64_t)llround(tick*1000000./V2_CLIP_SAMPLE_HZ);
        memset(frame->velocity,0,sizeof frame->velocity);
        memset(frame->acceleration,0,sizeof frame->acceleration);
    } else if(!ainekio_v2_clip_playback_sample(index,player->seconds,speed,rate,false,frame,source_us))return false;
    /* The terminal pose is not completion until the output owner confirms it. */
    frame->phase=*source_us<v2_clip_tracks[index].active_end_us ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    return true;
}
