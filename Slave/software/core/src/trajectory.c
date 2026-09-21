#include "ainekio/trajectory.h"
#include <math.h>

bool ainekio_trajectory_sample(float start, float end, float start_velocity,
    float end_velocity, float seconds, float fraction,
    float *position, float *velocity, float *acceleration)
{
    if (!position || !velocity || !acceleration || !isfinite(start) || !isfinite(end) ||
        !isfinite(start_velocity) || !isfinite(end_velocity) || !isfinite(seconds) ||
        seconds <= 0 || !isfinite(fraction) || fraction < 0 || fraction > 1) return false;
    /* Work relative to the first position to avoid cancellation for tiny
     * changes about a large geometric angle. */
    const float delta = end - start, m0 = start_velocity * seconds, m1 = end_velocity * seconds;
    const float a = m0 + m1 - 2 * delta, b = 3 * delta - 2 * m0 - m1;
    *position = start + fraction * (m0 + fraction * (b + fraction * a));
    *velocity = (m0 + fraction * (2 * b + fraction * 3 * a)) / seconds;
    *acceleration = (2 * b + fraction * 6 * a) / (seconds * seconds);
    return isfinite(*position) && isfinite(*velocity) && isfinite(*acceleration);
}
