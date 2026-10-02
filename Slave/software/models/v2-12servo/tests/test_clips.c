#include "ainekio/v2_motion.h"
#include "ainekio/admission.h"
#include "ainekio/v2_walk.h"
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
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i) {
        const ainekio_v2_clip_t *clip = &ainekio_v2_clips[i];
        assert(ainekio_v2_clip_find(clip->command, &selected) && selected == i);
        assert(!clip->hardware_qualified);
        assert(clip->peak_joint_speed_degrees_s > 0.F);
        const float below = 0.99 * ainekio_v2_gait_joint_speed_limit() / clip->peak_joint_speed_degrees_s;
        const float above = 1.01 * ainekio_v2_gait_joint_speed_limit() / clip->peak_joint_speed_degrees_s;
        assert(ainekio_v2_clip_playback_rate(i, below) == below);
        const float limited = ainekio_v2_clip_playback_rate(i, above);
        assert(fabs(limited * clip->peak_joint_speed_degrees_s - ainekio_v2_gait_joint_speed_limit()) < .001);
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
                ainekio_v2_walk_pose_t native_stand;
                assert(ainekio_v2_walk_pose(0., (ainekio_v2_walk_controls_t){0,1}, &native_stand));
                assert(fabsf(frame.position[j]-native_stand.frame.position[j])<.02F);
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
            assert(ainekio_v2_clip_sample(i, t, &frame));
            for (unsigned j = 0; j < 12; ++j) {
                assert(isfinite(frame.position[j]) && isfinite(frame.velocity[j]) && isfinite(frame.acceleration[j]));
                assert(fabs(frame.velocity[j])/100. <= clip->peak_joint_speed_degrees_s);
            }
        }
    }
    const char *names[] = {"sit", "rest", "wave", "dance", "swim", "point", "nod", "pushup", "bow",
        "cute", "freaky", "worm", "shake", "shrug", "dead", "lay_down", "celebrate", "stretch", "surprised", "sad", "curious"};
    const uint64_t durations[] = {5000, 5000, 16000, 12500, 23500, 11000, 8500, 14500, 8500,
        13500, 9200, 20000, 7000, 14000, 7000, 7000, 12500, 6700, 11950, 8800, 9750};
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
