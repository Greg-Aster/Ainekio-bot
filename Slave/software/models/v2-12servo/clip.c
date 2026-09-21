#include "ainekio/v2_motion.h"
#include "ainekio/trajectory.h"
#include "clip_data.h"
#include <string.h>

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

static float tangent(const ainekio_v2_clip_track_t *track, size_t knot, size_t joint)
{
    if (!knot || knot == track->count - 1) return 0;
    const float a = (track->positions[knot][joint] - track->positions[knot-1][joint]) * V2_CLIP_SAMPLE_HZ;
    const float b = (track->positions[knot+1][joint] - track->positions[knot][joint]) * V2_CLIP_SAMPLE_HZ;
    return a * b > 0 ? 2 * a * b / (a + b) : 0;
}

bool ainekio_v2_clip_sample(size_t index, uint64_t elapsed_us, ainekio_v2_frame_t *frame)
{
    if (index >= ainekio_v2_clip_count || !frame) return false;
    const ainekio_v2_clip_track_t *track = &v2_clip_tracks[index];
    *frame = (ainekio_v2_frame_t){0};
    /* Check completion before scaling to keep arbitrary late times bounded.
     * Each clip is finite: hold its recorded terminal pose, never wrap/reset. */
    if (elapsed_us >= ainekio_v2_clips[index].duration_us) {
        frame->phase = AINEKIO_V2_COMPLETE;
        memcpy(frame->position, track->positions[track->count-1], sizeof(frame->position));
        return true;
    }
    frame->phase = elapsed_us < track->active_start_us ? AINEKIO_V2_ENTRY :
                   elapsed_us < track->active_end_us ? track->active_phase : AINEKIO_V2_EXIT;
    const uint64_t scaled = elapsed_us * V2_CLIP_SAMPLE_HZ;
    const size_t knot = scaled / UINT64_C(1000000);
    const float fraction = (float)(scaled % UINT64_C(1000000)) / 1000000.0F;
    for (size_t joint = 0; joint < AINEKIO_V2_JOINT_COUNT; ++joint) {
        if (!ainekio_trajectory_sample(track->positions[knot][joint], track->positions[knot+1][joint],
            tangent(track, knot, joint), tangent(track, knot+1, joint), 1.0F / V2_CLIP_SAMPLE_HZ,
            fraction, &frame->position[joint], &frame->velocity[joint], &frame->acceleration[joint])) return false;
    }
    return true;
}
