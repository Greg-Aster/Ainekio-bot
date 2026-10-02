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

float ainekio_v2_clip_playback_rate(size_t index, float requested)
{
    if (index >= ainekio_v2_clip_count) return 0.F;
    return ainekio_v2_speed_limited_rate(ainekio_v2_clips[index].peak_joint_speed_degrees_s, requested);
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

bool ainekio_v2_clip_sample(size_t index, uint64_t elapsed_us, ainekio_v2_frame_t *frame)
{
    if (index >= ainekio_v2_clip_count || !frame) return false;
    const ainekio_v2_clip_track_t *track = &v2_clip_tracks[index];
    *frame = (ainekio_v2_frame_t){.geometry_id=V2_CLIP_GEOMETRY_ID};
    /* Check completion before scaling to keep arbitrary late times bounded.
     * Each clip is finite: hold its recorded terminal pose, never wrap/reset. */
    if (elapsed_us >= ainekio_v2_clips[index].duration_us) {
        frame->phase = AINEKIO_V2_COMPLETE;
        memcpy(frame->position, track->positions[track->count-1], sizeof(frame->position));
        return true;
    }
    frame->phase = elapsed_us < track->active_end_us ? AINEKIO_V2_CLIP : AINEKIO_V2_EXIT;
    const uint64_t scaled = elapsed_us * V2_CLIP_SAMPLE_HZ;
    const uint64_t source_knot = scaled / UINT64_C(1000000);
    size_t low=0, high=track->count-1;
    while(high-low>1) {
        size_t middle=low+(high-low)/2;
        if(track->knots[middle]<=source_knot)low=middle;else high=middle;
    }
    const size_t knot=low;
    const unsigned width=track->knots[high]-track->knots[low];
    const float fraction=(float)(scaled-(uint64_t)track->knots[low]*UINT64_C(1000000))/(width*1000000.0F);
    for (size_t joint = 0; joint < AINEKIO_V2_JOINT_COUNT; ++joint) {
        if (!ainekio_trajectory_sample(track->positions[knot][joint], track->positions[knot+1][joint],
            track->velocities[knot][joint], track->velocities[knot+1][joint], (float)width / V2_CLIP_SAMPLE_HZ,
            fraction, &frame->position[joint], &frame->velocity[joint], &frame->acceleration[joint])) return false;
    }
    return true;
}
