#ifndef AINEKIO_V2_LIMITS_H
#define AINEKIO_V2_LIMITS_H
#include "ainekio/v2_motion.h"
/* Actual direct-linkage closure in CAD coordinates; no provisional angle caps. */
bool ainekio_v2_limits_leg(const double joints_rad[3]);
bool ainekio_v2_limits_frame(const ainekio_v2_frame_t *frame);

double ainekio_v2_center_degrees(unsigned joint);
/* Reported servo-profile window midpoint; distinct from driver timer capacity. */
double ainekio_v2_pulse_midpoint(void);
double ainekio_v2_us_per_degree(void);
unsigned ainekio_v2_pulse_reference(unsigned joint);
const char *ainekio_v2_servo_profile_id(void);
/* progress is in [0,1]. Bounds conservatively enclose the full direct
 * linkage path; derivatives are centidegrees per unit progress. */
bool ainekio_v2_transition(const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,
                          double progress,ainekio_v2_frame_t *out);
bool ainekio_v2_transition_bounds(const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,
    ainekio_v2_frame_t *minimum,ainekio_v2_frame_t *maximum,double max_derivative_cd[12]);
#endif
