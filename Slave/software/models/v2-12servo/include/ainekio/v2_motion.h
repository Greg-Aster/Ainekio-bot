#ifndef AINEKIO_V2_MOTION_H
#define AINEKIO_V2_MOTION_H

#include "ainekio/protocol.h"

#define AINEKIO_V2_JOINT_COUNT 12U

typedef struct {
    const char *name;
    const char *cad_leg;
    const char *actuator;
    const char *positive_body_axis;
} ainekio_v2_joint_t;

typedef enum {
    AINEKIO_V2_ENTRY, AINEKIO_V2_LOOP, AINEKIO_V2_EXIT, AINEKIO_V2_COMPLETE,
    AINEKIO_V2_CLIP
} ainekio_v2_phase_t;

typedef struct {
    float position[AINEKIO_V2_JOINT_COUNT];
    float velocity[AINEKIO_V2_JOINT_COUNT];
    float acceleration[AINEKIO_V2_JOINT_COUNT]; /* centidegrees/second squared */
    ainekio_v2_phase_t phase;
    uint8_t cycle;
    const char *geometry_id; /* identifies the geometry shared by current walk and finite clips */
} ainekio_v2_frame_t;

extern const ainekio_v2_joint_t ainekio_v2_joints[AINEKIO_V2_JOINT_COUNT];
extern const char ainekio_v2_walk_id[];
extern const bool ainekio_v2_walk_hardware_qualified;

/* Existing wire command, independently of WebSocket, controller location or
 * pulse backend. Other semantic motions are not mapped to walking. */
bool ainekio_v2_walk_request(const ainekio_command_t *command, uint8_t *cycles);

typedef struct {
    const char *command;
    const char *gait_id;
    ainekio_intent_kind_t intent;
    uint64_t duration_us;
    bool hardware_qualified;
} ainekio_v2_clip_t;

extern const ainekio_v2_clip_t ainekio_v2_clips[];
extern const size_t ainekio_v2_clip_count;
/* Resolve existing native sit / semantic emote envelopes to finite clips.
 * Indexes identify model assets only; they are never PCA channel assignments. */
bool ainekio_v2_clip_find(const char *name, size_t *index);
bool ainekio_v2_clip_request(const ainekio_command_t *command, size_t *index);
bool ainekio_v2_clip_sample(size_t index, uint64_t elapsed_us, ainekio_v2_frame_t *frame);
/* Position envelopes include every knot and every interpolated segment. The
 * extrema for different joints need not occur in the same sampled frame. */
bool ainekio_v2_clip_bounds(size_t index, ainekio_v2_frame_t *minimum,
                           ainekio_v2_frame_t *maximum);

#endif
