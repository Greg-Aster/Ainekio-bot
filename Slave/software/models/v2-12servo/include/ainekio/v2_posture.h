#ifndef AINEKIO_V2_POSTURE_H
#define AINEKIO_V2_POSTURE_H
#include "ainekio/v2_walk.h"
/* Contact points and COM (body pivot) are modeled estimates, not sensors. */
typedef struct {
    ainekio_v2_walk_pose_t start, target, pose;
    double anchors[4][3], shift[4][2];
    ainekio_v2_frame_t from, to;
    unsigned order_offset;
    bool initial_landing; /* Optional geometric segment -1..0; ordinary path unchanged. */
} ainekio_v2_posture_t;
double ainekio_v2_posture_path_length(void);
bool ainekio_v2_posture_begin(ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,const double starting_euler[3]);
bool ainekio_v2_posture_begin_ordered(ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,
    const double starting_euler[3],unsigned order_offset);
/* Begin at progress -1: lower raised modeled soles vertically to the lowest
 * starting sole plane before lifting/placing toward the final posture. The
 * caller supplies measured shafts when available; this is not contact sensing. */
bool ainekio_v2_posture_begin_landing(ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,const double starting_euler[3]);
/* Geometric path coordinate, not a mandatory wall-clock duration. */
bool ainekio_v2_posture_sample(ainekio_v2_posture_t *state,double elapsed);
/* Traverse at the same full nominal joint rate as automatic Walk, independent
 * of the stored slow-motion/playback settings. Emit each lift/place landmark. */
bool ainekio_v2_posture_advance(ainekio_v2_posture_t *state,double *progress,double seconds);
/* Include the installed joint mapping in planning, before committing path
 * progress. A failed candidate leaves both state and progress unchanged. */
typedef bool (*ainekio_v2_posture_fit_t)(ainekio_v2_frame_t *frame,void *context);
bool ainekio_v2_posture_advance_mapped(ainekio_v2_posture_t *state,double *progress,
    double seconds,ainekio_v2_posture_fit_t fit,void *context);
/* Lift and placement depend on the moving leg, not all supporting joints.
 * The final target depends on all joints; lowering can load the supporting
 * legs before the next step redistributes their load. */
uint16_t ainekio_v2_posture_arrival_joints(const ainekio_v2_posture_t *state,double progress);
unsigned ainekio_v2_posture_order_for_joints(uint16_t joints,unsigned start);
/* Geometric targets for measured execution. The coordinate is not elapsed
 * time: the caller advances it only after the preceding target is observed. */
bool ainekio_v2_posture_next_target(ainekio_v2_posture_t *state,double *progress,
    uint16_t *moving_joints);
bool ainekio_v2_posture_next_target_mapped(ainekio_v2_posture_t *state,double *progress,
    uint16_t *moving_joints,ainekio_v2_posture_fit_t fit,void *context);
/* Reconstruct sole clearance and body height from shafts and attitude using
 * the current supporting feet as the estimated ground plane. No contact sensor
 * is implied by this estimate. */
bool ainekio_v2_posture_observe(const ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *measured,const double euler[3],
    ainekio_v2_walk_pose_t *observed);
/* Target and open-loop startup fold reference, not a second motion planner. */
typedef struct {
    ainekio_v2_walk_pose_t crouch, stand;
    double anchors[4][3];
} ainekio_v2_rise_t;
bool ainekio_v2_rise_begin(ainekio_v2_rise_t *state);
#endif
