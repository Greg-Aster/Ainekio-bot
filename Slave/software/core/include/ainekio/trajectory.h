#ifndef AINEKIO_TRAJECTORY_H
#define AINEKIO_TRAJECTORY_H

#include <stdbool.h>

/* One cubic Hermite segment. Positions and velocities use the caller's
 * consistent units; duration is seconds. No clipping or extrapolation. */
bool ainekio_trajectory_sample(float start, float end, float start_velocity,
    float end_velocity, float seconds, float fraction,
    float *position, float *velocity, float *acceleration);

#endif
