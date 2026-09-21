#include "ainekio/v2_motion.h"
#include "ainekio/trajectory.h"
#include "walk_data.h"
#include <string.h>

bool ainekio_v2_walk_request(const ainekio_command_t *command, uint8_t *cycles)
{
    if (!command || !cycles || command->kind != AINEKIO_COMMAND_INTENT ||
        command->data.intent.kind != AINEKIO_INTENT_WALK ||
        command->data.intent.data.walk.direction != AINEKIO_WALK_FORWARD ||
        command->data.intent.data.walk.steps < 1 || command->data.intent.data.walk.steps > 10) return false;
    *cycles = command->data.intent.data.walk.steps;
    return true;
}

uint64_t ainekio_v2_walk_duration_us(uint8_t cycles)
{
    return cycles < 1 || cycles > 10 ? 0 : V2_ENTRY_US + cycles * AINEKIO_V2_WALK_PERIOD_US + V2_EXIT_US;
}

static bool sample(const ainekio_v2_knot_t *knots, size_t count, uint64_t time_us,
                   ainekio_v2_frame_t *frame)
{
    /* Rational 120 Hz indexing preserves exactly 480 intervals in 4 seconds. */
    const uint64_t scaled = time_us * V2_SAMPLE_HZ;
    const size_t index = scaled / UINT64_C(1000000);
    if (index >= count - 1) return false;
    const float fraction = (float)(scaled % UINT64_C(1000000)) / 1000000.0F;
    for (size_t joint = 0; joint < AINEKIO_V2_JOINT_COUNT; ++joint) {
        if (!ainekio_trajectory_sample(knots[index].position[joint], knots[index+1].position[joint],
            knots[index].velocity[joint], knots[index+1].velocity[joint], 1.0F / V2_SAMPLE_HZ,
            fraction, &frame->position[joint], &frame->velocity[joint], &frame->acceleration[joint])) return false;
    }
    return true;
}

bool ainekio_v2_walk_loop_sample(uint64_t elapsed_us, ainekio_v2_frame_t *frame)
{
    if (!frame) return false;
    *frame = (ainekio_v2_frame_t){.phase=AINEKIO_V2_LOOP};
    return sample(v2_walk_loop, V2_LOOP_COUNT, elapsed_us % AINEKIO_V2_WALK_PERIOD_US, frame);
}

bool ainekio_v2_walk_sample(uint8_t cycles, uint64_t elapsed_us, ainekio_v2_frame_t *frame)
{
    const uint64_t duration = ainekio_v2_walk_duration_us(cycles);
    if (!duration || !frame) return false;
    *frame = (ainekio_v2_frame_t){0};
    if (elapsed_us >= duration) {
        frame->phase = AINEKIO_V2_COMPLETE;
        memcpy(frame->position, v2_walk_exit[V2_EXIT_COUNT-1].position, sizeof(frame->position));
        return true;
    }
    if (elapsed_us < V2_ENTRY_US) {
        frame->phase = AINEKIO_V2_ENTRY;
        return sample(v2_walk_entry, V2_ENTRY_COUNT, elapsed_us, frame);
    }
    elapsed_us -= V2_ENTRY_US;
    if (elapsed_us < cycles * AINEKIO_V2_WALK_PERIOD_US) {
        frame->phase = AINEKIO_V2_LOOP;
        frame->cycle = elapsed_us / AINEKIO_V2_WALK_PERIOD_US;
        return sample(v2_walk_loop, V2_LOOP_COUNT, elapsed_us % AINEKIO_V2_WALK_PERIOD_US, frame);
    }
    frame->phase = AINEKIO_V2_EXIT;
    return sample(v2_walk_exit, V2_EXIT_COUNT, elapsed_us - cycles * AINEKIO_V2_WALK_PERIOD_US, frame);
}
