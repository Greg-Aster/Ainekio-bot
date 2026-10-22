#include "ainekio/v2_motion.h"
#include "ainekio/admission.h"
#include "ainekio/v2_walk.h"
#include "clip_data.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    assert(ainekio_v2_clip_count == 23);
    assert(!ainekio_v2_joint_speed_set(0.F));
    assert(!ainekio_v2_joint_speed_set(NAN));
    assert(ainekio_v2_joint_speed_set(100.F));
    assert(ainekio_v2_speed_limited_rate(200.,2.F)==.5F);
    assert(ainekio_v2_joint_speed_set(2000.F));
    assert(ainekio_v2_speed_limited_rate(200.,2.F)==2.F);
    assert(ainekio_v2_joint_speed_set(ainekio_v2_joint_speed_default()));
    ainekio_v2_frame_t frame, held, standing, entry;
    assert(ainekio_v2_clip_sample(0, 0, &standing));
    size_t selected;
    assert(!ainekio_v2_clip_request(NULL, &selected));
    assert(!ainekio_v2_clip_find(NULL, &selected));
    assert(!ainekio_v2_clip_find("wave", NULL));
    assert(!ainekio_v2_clip_sample(ainekio_v2_clip_count, 0, &frame));
    assert(!ainekio_v2_clip_sample(0, 0, NULL));
    float up[3];
    assert(!ainekio_v2_clip_expected_up(ainekio_v2_clip_count,0,up));
    assert(!ainekio_v2_clip_expected_up(0,0,NULL));
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i) {
        const ainekio_v2_clip_t *clip = &ainekio_v2_clips[i];
        assert(ainekio_v2_clip_find(clip->command, &selected) && selected == i);
        assert(!clip->hardware_qualified);
        assert(clip->peak_joint_speed_degrees_s > 0.F);
        const double speed=ainekio_v2_gait_joint_speed_limit()*AINEKIO_V2_GESTURE_SPEED_SCALE;
        const bool taper=!strcmp(clip->command,"sit") || !strcmp(clip->command,"rest") || !strcmp(clip->command,"crouch");
        const double duration=ainekio_v2_clip_playback_seconds(i,speed,2.F);
        uint64_t source_us=0,previous_us=0,reverse_us;
        unsigned travelling=0;
        for(unsigned step=0;step<=2000;step++) {
            const double time=duration*step/2000.;
            ainekio_v2_frame_t playback,source,reverse;
            assert(ainekio_v2_clip_playback_sample(i,time,speed,2.F,false,&playback,&source_us));
            assert(source_us>=previous_us && source_us<=clip->duration_us);
            previous_us=source_us;
            assert(ainekio_v2_clip_sample(i,source_us,&source));
            assert(ainekio_v2_clip_playback_sample(i,duration-time,speed,2.F,true,&reverse,&reverse_us));
            double peak=0.;
            for(unsigned j=0;j<12;j++) {
                /* Retiming preserves the existing cubic path and reverses it
                 * exactly, including all extrema and terminal poses. */
                assert(fabs(playback.position[j]-source.position[j])<.2);
                assert(fabs(playback.position[j]-reverse.position[j])<.02);
                assert(isfinite(playback.velocity[j]) && isfinite(playback.acceleration[j]));
                peak=fmax(peak,fabs(playback.velocity[j])/100.);
            }
            if(peak>0.) {
                assert(peak<=speed+.001);
                if(!taper)assert(fabs(peak-speed)<.001);
                travelling++;
            }
        }
        assert(travelling>0 && source_us==clip->duration_us);
        /* Position differences inside every travel span independently prove
         * the clock moves at full speed, rather than just reporting it. A
         * window crossing a reversal measures net travel, not motor speed. */
        const ainekio_v2_clip_clock_t *clock=&v2_clip_clocks[i];
        unsigned measured_spans=0;
        for(size_t k=0;k+1<clock->count;k++) {
            const ainekio_v2_clip_clock_knot_t *a=&clock->knots[k],*b=&clock->knots[k+1];
            if(taper && b->travel_degrees>.8*clock->knots[clock->count-1].travel_degrees)continue;
            const double begin=a->travel_degrees/speed+a->hold_seconds;
            const double end=b->travel_degrees/speed+b->hold_seconds;
            if(end<=begin)continue;
            ainekio_v2_frame_t before,after;uint64_t ignored;
            assert(ainekio_v2_clip_playback_sample(i,begin+.2*(end-begin),speed,2.F,false,&before,&ignored));
            assert(ainekio_v2_clip_playback_sample(i,begin+.8*(end-begin),speed,2.F,false,&after,&ignored));
            double distance=0.;
            for(unsigned j=0;j<12;j++)distance=fmax(distance,fabs(after.position[j]-before.position[j])/100.);
            if(b->hold_seconds>a->hold_seconds)assert(distance<.005);
            else if(b->travel_degrees-a->travel_degrees>.01) {
                assert(fabs(distance/(.6*(end-begin))-speed)<speed*.02);
                measured_spans++;
            }
        }
        assert(measured_spans>0);
        /* Output-cadence regression: a late frame cannot jump past a phase
         * endpoint or reversal, and a delayed shaft cannot consume a hold.
         * All targets, including the final target, need separate arrival. */
        for(unsigned cadence=0;cadence<2;cadence++) {
            ainekio_v2_clip_player_t player={0};
            unsigned seen=0,steps=0;
            double minimum[12],maximum[12];
            for(unsigned j=0;j<12;j++){minimum[j]=INFINITY;maximum[j]=-INFINITY;}
            while(seen<clock->target_count) {
                assert(++steps<20000);
                assert(ainekio_v2_clip_player_tick(i,&player,cadence?.137:.020,speed,3.F,false,&frame,&source_us));
                assert(frame.phase!=AINEKIO_V2_COMPLETE);
                for(unsigned j=0;j<12;j++){
                    minimum[j]=fmin(minimum[j],frame.position[j]);maximum[j]=fmax(maximum[j],frame.position[j]);
                }
                if(!player.waiting)continue;
                assert(source_us==(uint64_t)llround(clock->targets[seen]*1000000./V2_CLIP_SAMPLE_HZ));
                const double stopped=player.seconds;
                const ainekio_v2_frame_t target=frame;
                assert(ainekio_v2_clip_player_tick(i,&player,5.,speed,3.F,false,&frame,&source_us));
                assert(player.waiting && player.seconds==stopped);
                assert(!memcmp(target.position,frame.position,sizeof frame.position));
                assert(frame.phase!=AINEKIO_V2_COMPLETE);
                assert(ainekio_v2_clip_player_tick(i,&player,5.,speed,3.F,true,&frame,&source_us));
                assert(player.seconds==stopped); /* No catch-up after arrival. */
                seen++;
            }
            assert(frame.phase==AINEKIO_V2_COMPLETE);
            ainekio_v2_frame_t low,high;
            assert(ainekio_v2_clip_bounds(i,&low,&high));
            for(unsigned j=0;j<12;j++) {
                assert(fabs(minimum[j]-low.position[j])<=.51);
                assert(fabs(maximum[j]-high.position[j])<=.51);
            }
        }
        printf("%-10s %.3f s travel + original holds, %zu feedback targets\n",clip->command,duration,clock->target_count);
        char wire[256];
        if (clip->intent == AINEKIO_INTENT_SIT)
            snprintf(wire, sizeof(wire), "{\"t\":\"intent\",\"name\":\"sit\",\"seq\":1,\"epoch\":7,\"deadline_ms\":1000}");
        else snprintf(wire, sizeof(wire), "{\"t\":\"intent\",\"name\":\"emote\",\"asset\":\"%s\","
                      "\"seq\":1,\"epoch\":7,\"deadline_ms\":1000}", clip->command);
        ainekio_control_message_t message;
        assert(ainekio_control_decode(wire, strlen(wire), &message) == AINEKIO_DECODE_OK);
        assert(ainekio_v2_clip_request(&message.command, &selected) && selected == i);
        assert(!ainekio_v2_clip_request(&message.command, NULL));

        ainekio_admission_t admission;
        ainekio_admission_init(&admission, AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_INTENT), true);
        const uint64_t generation = ainekio_admission_open(&admission);
        assert(!ainekio_admission_accept(&admission, generation, &message, 1, 2, true).accepted);
        assert(ainekio_admission_welcome(&admission, generation, 7, AINEKIO_PROFILE_HOME, true, 0));
        assert(ainekio_admission_accept(&admission, generation, &message, 1, 2, true).rejection == AINEKIO_REJECT_BUSY);
        assert(ainekio_admission_accept(&admission, generation, &message, 1, 2, true).rejection == AINEKIO_REJECT_STALE);
        message.sequence = message.command.sequence = 2;
        message.deadline_ms = 0;
        assert(ainekio_admission_accept(&admission, generation, &message, 1, 2, true).rejection == AINEKIO_REJECT_STALE);
        ainekio_admission_close(&admission, generation);
        assert(!ainekio_admission_accept(&admission, generation, &message, 1, 2, true).accepted);

        assert(ainekio_v2_clip_sample(i, 0, &frame));
        assert(frame.phase == AINEKIO_V2_CLIP);
        entry = frame;
        for (unsigned j = 0; j < 12; ++j) {
            if (!strcmp(clip->command,"crouch")) {
                /* Crouch is a retained gesture recorded with its historical
                 * contact hull. It does not share the revised bare-foot Crawl
                 * entry pose. Pin that archive rather than equating the two. */
                const float archived_crouch_entry[12]={-0.000565F,77.274028F,-2122.527730F,0.000377F,77.271296F,-2122.530462F,-0.000565F,77.278126F,-2122.523632F,0.000377F,77.275394F,-2122.523632F};
                assert(fabsf(frame.position[j]-archived_crouch_entry[j])<.02F);
            } else if (!strcmp(clip->command,"wave") || !strcmp(clip->command,"point") ||
                       !strcmp(clip->command,"pushup") || !strcmp(clip->command,"bow") ||
                       !strcmp(clip->command,"worm")) {
                /* Expressive revisions solve the installed bare Part027 shape.
                 * Other archived gestures still use the boot contact shape. */
                const float bare_wave_entry[12]={-0.000040F,365.732312F,-2166.238998F,-0.000081F,365.730312F,-2166.238547F,0.000023F,365.735294F,-2166.239746F,-0.000040F,365.732351F,-2166.239148F};
                assert(fabsf(frame.position[j]-bare_wave_entry[j])<.02F);
            } else {
                /* Independent hull solves differ below 0.0002 degrees. */
                assert(fabsf(frame.position[j] - standing.position[j]) < .02F);
            }
            assert(frame.velocity[j] == 0);
        }
        assert(ainekio_v2_clip_sample(i, clip->duration_us, &frame) && frame.phase == AINEKIO_V2_COMPLETE);
        assert(ainekio_v2_clip_sample(i, UINT64_MAX, &held));
        assert(!memcmp(&frame, &held, sizeof(frame)));
        bool nonzero = false;
        for (unsigned j = 0; j < 12; ++j) {
            assert(frame.velocity[j] == 0 && frame.acceleration[j] == 0);
            nonzero |= fabsf(frame.position[j] - entry.position[j]) > 1.0F;
        }
        assert(nonzero == (!strcmp(clip->command, "sit") || !strcmp(clip->command, "rest") || !strcmp(clip->command, "dead") || !strcmp(clip->command, "lay_down") || !strcmp(clip->command, "crouch") || !strcmp(clip->command, "upright")));
        for (uint64_t t = 0; t < clip->duration_us; t += UINT64_C(19997)) {
            assert(ainekio_v2_clip_expected_up(i,t,up));
            assert(fabs(up[0]*up[0]+up[1]*up[1]+up[2]*up[2]-1.)<1e-6);
            assert(ainekio_v2_clip_sample(i, t, &frame));
            for (unsigned j = 0; j < 12; ++j) {
                assert(isfinite(frame.position[j]) && isfinite(frame.velocity[j]) && isfinite(frame.acceleration[j]));
                assert(fabs(frame.velocity[j])/100. <= clip->peak_joint_speed_degrees_s);
            }
        }
    }
    /* Sit keeps its full two-second hold at every legacy playback rate. */
    const double speed=ainekio_v2_gait_joint_speed_limit();
    assert(fabs(ainekio_v2_clip_playback_seconds(0,speed,.25F)-
                ainekio_v2_clip_playback_seconds(0,speed,2.F))<1e-6);
    const double travel=ainekio_v2_clip_playback_seconds(0,speed,2.F)-2.;
    assert(fabs(ainekio_v2_clip_playback_seconds(0,speed/2.,2.F)-2.-2.*travel)<1e-6);
    ainekio_v2_frame_t fast,slow,other_rate;uint64_t fast_us,slow_us,other_us;
    assert(ainekio_v2_clip_playback_sample(0,travel*.3,speed,2.F,false,&fast,&fast_us));
    assert(ainekio_v2_clip_playback_sample(0,travel*.6,speed/2.,2.F,false,&slow,&slow_us));
    assert(ainekio_v2_clip_playback_sample(0,travel*.3,speed,.25F,false,&other_rate,&other_us));
    assert(fast_us==slow_us && fast_us==other_us);
    assert(!memcmp(fast.position,slow.position,sizeof fast.position));
    assert(!memcmp(fast.position,other_rate.position,sizeof fast.position));
    const char *tapered[]={"sit","rest","crouch"};
    for(unsigned i=0;i<3;i++) {
        size_t clip;assert(ainekio_v2_clip_find(tapered[i],&clip));
        const double moving=ainekio_v2_clip_playback_seconds(clip,speed,3.F)-2.;
        assert(ainekio_v2_clip_playback_sample(clip,.25*moving,speed,3.F,false,&fast,&fast_us));
        assert(ainekio_v2_clip_playback_sample(clip,.99*moving,speed,3.F,false,&slow,&slow_us));
        double fast_peak=0.,slow_peak=0.;
        for(unsigned j=0;j<12;j++) {
            fast_peak=fmax(fast_peak,fabs(fast.velocity[j])/100.);
            slow_peak=fmax(slow_peak,fabs(slow.velocity[j])/100.);
        }
        assert(fabs(fast_peak-speed)<.001 && slow_peak<speed*.15);
        assert(ainekio_v2_clip_playback_sample(clip,moving+1.999,speed,3.F,false,&held,&slow_us));
        assert(ainekio_v2_clip_sample(clip,UINT64_MAX,&frame));
        for(unsigned j=0;j<12;j++)assert(fabs(held.position[j]-frame.position[j])<.01);
    }
    const char *names[] = {"sit", "rest", "wave", "dance", "swim", "point", "nod", "pushup", "bow",
        "cute", "freaky", "worm", "shake", "shrug", "dead", "lay_down", "celebrate", "stretch", "surprised", "sad", "curious"};
    const uint64_t durations[] = {5000, 5000, 6200, 12500, 23500, 6100, 8500, 14200, 7300,
        13500, 9200, 6400, 7000, 14000, 7000, 7000, 12500, 6700, 11950, 8800, 9750};
    for (size_t i = 0; i < sizeof(names)/sizeof(names[0]); ++i) {
        assert(ainekio_v2_clip_find(names[i], &selected));
        assert(ainekio_v2_clips[selected].duration_us == durations[i]*1000U);
    }
    size_t nod, pushup;
    assert(ainekio_v2_clip_find("nod", &nod) && ainekio_v2_clip_find("pushup", &pushup));
    assert(ainekio_v2_clip_sample(nod, UINT64_C(3000000), &frame));
    assert(ainekio_v2_clip_sample(pushup, UINT64_C(3000000), &held));
    assert(fabsf(frame.position[1] - held.position[1]) > 100); /* distinct rear crouches */
    size_t dead;
    assert(ainekio_v2_clip_find("dead", &dead));
    assert(ainekio_v2_clip_sample(dead, UINT64_C(7400000), &frame));
    /* Play Dead holds its outstretched pose until another command. */
    for (uint64_t t = UINT64_C(7400000); t < UINT64_C(13000000); t += UINT64_C(8333)) {
        assert(ainekio_v2_clip_sample(dead, t, &held));
        assert(!memcmp(&frame, &held, sizeof(frame)));
    }
    size_t lay_down;
    assert(ainekio_v2_clip_find("lay_down", &lay_down));
    assert(ainekio_v2_clip_sample(lay_down, UINT64_MAX, &held));
    /* Same rear support, distinct front-arm reach. */
    for(unsigned j=0;j<6;j++)assert(fabsf(frame.position[j]-held.position[j])<.01F);
    assert(fabsf(frame.position[7]-held.position[7])>1000.F);
    assert(fabsf(frame.position[10]-held.position[10])>1000.F);
    assert(!ainekio_v2_clip_find("crab", &selected));
    ainekio_command_t unknown = {.kind=AINEKIO_COMMAND_INTENT, .data.intent.kind=AINEKIO_INTENT_EMOTE};
    const char *removed[] = {"turn_left_15", "turn_right_15", "turn_left_45", "turn_right_45",
        "turn_left_90", "turn_right_90", "turn_left_180", "turn_right_180"};
    for (size_t i=0;i<sizeof(removed)/sizeof(removed[0]);++i) {
        assert(!ainekio_v2_clip_find(removed[i], &selected));
        strcpy(unknown.data.intent.data.asset, removed[i]);
        assert(!ainekio_v2_clip_request(&unknown, &selected));
    }
    strcpy(unknown.data.intent.data.asset, "unknown");
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    strcpy(unknown.data.intent.data.asset, "sit");
    assert(!ainekio_v2_clip_request(&unknown, &selected)); /* native intent, not emote */
    memset(unknown.data.intent.data.asset, 'x', sizeof(unknown.data.intent.data.asset));
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    strcpy(unknown.data.intent.data.asset, "wave");
    unknown.data.intent.kind = AINEKIO_INTENT_WALK;
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    unknown.data.intent.kind = AINEKIO_INTENT_STAND;
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    puts("Twenty-three finite gestures: semantic decoding, admission, timing, terminal hold and invalid requests passed.");
    return 0;
}
