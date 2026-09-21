#include "ainekio/v2_motion.h"
#include "ainekio/admission.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    assert(ainekio_v2_clip_count == 29);
    ainekio_v2_frame_t frame, held;
    size_t selected;
    assert(!ainekio_v2_clip_request(NULL, &selected));
    assert(!ainekio_v2_clip_find(NULL, &selected));
    assert(!ainekio_v2_clip_find("wave", NULL));
    assert(!ainekio_v2_clip_sample(ainekio_v2_clip_count, 0, &frame));
    assert(!ainekio_v2_clip_sample(0, 0, NULL));
    unsigned turns = 0, gestures = 0;
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i) {
        const ainekio_v2_clip_t *turn = &ainekio_v2_clips[i];
        assert(ainekio_v2_clip_find(turn->command, &selected) && selected == i);
        assert(!turn->hardware_qualified);
        const int magnitude = turn->heading_degrees < 0 ? -turn->heading_degrees : turn->heading_degrees;
        const uint64_t seconds = magnitude == 15 ? 15 : magnitude == 45 ? 19 : magnitude == 90 ? 23 : 35;
        if (magnitude) {
            ++turns;
            assert(turn->duration_us == seconds * UINT64_C(1000000));
            assert((strstr(turn->command, "left") != NULL) == (turn->heading_degrees > 0));
        } else ++gestures;
        char wire[256];
        if (turn->intent == AINEKIO_INTENT_SIT)
            snprintf(wire, sizeof(wire), "{\"t\":\"intent\",\"name\":\"sit\",\"seq\":1,\"epoch\":7,\"deadline_ms\":1000}");
        else snprintf(wire, sizeof(wire), "{\"t\":\"intent\",\"name\":\"emote\",\"asset\":\"%s\","
                      "\"seq\":1,\"epoch\":7,\"deadline_ms\":1000}", turn->command);
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
        assert(frame.phase == (magnitude ? AINEKIO_V2_ENTRY : AINEKIO_V2_CLIP));
        for (unsigned j = 0; j < 12; ++j) assert(frame.position[j] == 0 && frame.velocity[j] == 0);
        if (magnitude) {
            assert(ainekio_v2_clip_sample(i, UINT64_C(5000000), &frame) && frame.phase == AINEKIO_V2_TURN);
            assert(ainekio_v2_clip_sample(i, turn->duration_us - UINT64_C(6000000), &frame) && frame.phase == AINEKIO_V2_EXIT);
        }
        assert(ainekio_v2_clip_sample(i, turn->duration_us, &frame) && frame.phase == AINEKIO_V2_COMPLETE);
        assert(ainekio_v2_clip_sample(i, UINT64_MAX, &held));
        assert(!memcmp(&frame, &held, sizeof(frame)));
        bool nonzero = false;
        for (unsigned j = 0; j < 12; ++j) {
            assert(frame.velocity[j] == 0 && frame.acceleration[j] == 0);
            nonzero |= fabsf(frame.position[j]) > 1.0F;
        }
        assert(nonzero == (magnitude || !strcmp(turn->command, "sit") || !strcmp(turn->command, "rest") || !strcmp(turn->command, "dead")));
        for (uint64_t t = 0; t < turn->duration_us; t += UINT64_C(19997)) {
            assert(ainekio_v2_clip_sample(i, t, &frame));
            for (unsigned j = 0; j < 12; ++j)
                assert(isfinite(frame.position[j]) && isfinite(frame.velocity[j]) && isfinite(frame.acceleration[j]));
        }
    }
    assert(turns == 8 && gestures == 21);
    const char *names[] = {"sit", "rest", "wave", "dance", "swim", "point", "nod", "pushup", "bow",
        "cute", "freaky", "worm", "shake", "shrug", "dead", "crab", "celebrate", "stretch", "surprised", "sad", "curious"};
    const uint64_t durations[] = {5000, 5000, 16000, 12500, 23500, 11000, 14500, 14500, 8500,
        13500, 9200, 12000, 7000, 10200, 7400, 30100, 12500, 6700, 11950, 8800, 9750};
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
    /* Every time in the optional demonstration recovery must hold dead, not
     * fold the linkages, replace the feet or seek the playlist standing pose. */
    for (uint64_t t = UINT64_C(7400000); t < UINT64_C(13000000); t += UINT64_C(8333)) {
        assert(ainekio_v2_clip_sample(dead, t, &held));
        assert(!memcmp(&frame, &held, sizeof(frame)));
    }
    assert(fabsf(frame.position[0] - 9000.0F) < 0.001F);
    assert(fabsf(frame.position[3] + 9000.0F) < 0.001F);
    ainekio_command_t unknown = {.kind=AINEKIO_COMMAND_INTENT, .data.intent.kind=AINEKIO_INTENT_EMOTE};
    strcpy(unknown.data.intent.data.asset, "turn_left_16");
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    strcpy(unknown.data.intent.data.asset, "sit");
    assert(!ainekio_v2_clip_request(&unknown, &selected)); /* native intent, not emote */
    memset(unknown.data.intent.data.asset, 'x', sizeof(unknown.data.intent.data.asset));
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    strcpy(unknown.data.intent.data.asset, "turn_left_15");
    unknown.data.intent.kind = AINEKIO_INTENT_WALK;
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    unknown.data.intent.kind = AINEKIO_INTENT_STAND;
    assert(!ainekio_v2_clip_request(&unknown, &selected));
    puts("Twenty-nine finite clips: semantic decoding, admission, timing, terminal hold and invalid requests passed.");
    return 0;
}
