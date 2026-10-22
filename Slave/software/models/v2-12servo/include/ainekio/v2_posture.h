#ifndef AINEKIO_V2_POSTURE_H
#define AINEKIO_V2_POSTURE_H
#include "ainekio/v2_walk.h"
/* Contact points and COM (body pivot) are modeled estimates, not sensors. */
typedef struct {
    ainekio_v2_walk_pose_t start, target, pose;
    double anchors[4][3], shift[4][2];
    ainekio_v2_frame_t from, to;
    unsigned order_offset;
} ainekio_v2_posture_t;
double ainekio_v2_posture_path_length(void);
bool ainekio_v2_posture_begin(ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,const double starting_euler[3]);
bool ainekio_v2_posture_begin_ordered(ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,
    const double starting_euler[3],unsigned order_offset);
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
/* Target and open-loop startup fold reference, not a second motion planner. */
typedef struct {
    ainekio_v2_walk_pose_t crouch, stand;
    double anchors[4][3];
} ainekio_v2_rise_t;
bool ainekio_v2_rise_begin(ainekio_v2_rise_t *state);
#endif
