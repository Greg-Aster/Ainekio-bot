#ifndef AINEKIO_V2_POSTURE_H
#define AINEKIO_V2_POSTURE_H
#include "ainekio/v2_walk.h"
/* Contact points and COM (body pivot) are modeled estimates, not sensors. */
typedef struct {
    ainekio_v2_walk_pose_t start, target, pose;
    double anchors[4][3], shift[4][2];
    ainekio_v2_frame_t from, to;
} ainekio_v2_posture_t;
double ainekio_v2_posture_path_length(void);
bool ainekio_v2_posture_begin(ainekio_v2_posture_t *state,
    const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,const double starting_euler[3]);
/* Geometric path coordinate, not a mandatory wall-clock duration. */
bool ainekio_v2_posture_sample(ainekio_v2_posture_t *state,double elapsed);
/* Traverse at the same full nominal joint rate as automatic Walk, independent
 * of the stored slow-motion/playback settings. Emit each lift/place landmark. */
bool ainekio_v2_posture_advance(ainekio_v2_posture_t *state,double *progress,double seconds);
/* Startup shoulder PWM may engage once that source leg has been lifted. */
bool ainekio_v2_posture_shoulder_engaged(double progress,unsigned model_leg);
bool ainekio_v2_posture_landmark(double progress);
/* Startup rise: crouch 25 mm below Stand, then raise the body over the same
 * four modeled sole contacts. Shoulder engagement is owned by the body task. */
typedef struct {
    ainekio_v2_walk_pose_t crouch, stand, pose;
    double anchors[4][3];
} ainekio_v2_rise_t;
bool ainekio_v2_rise_begin(ainekio_v2_rise_t *state);
/* Front and rear lift progress produce one rigid body pose with planted feet. */
bool ainekio_v2_rise_sample(ainekio_v2_rise_t *state,double front_fraction,double rear_fraction);
#endif
