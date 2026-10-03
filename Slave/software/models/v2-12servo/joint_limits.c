#include "ainekio/v2_limits.h"
#include "servo_data.h"
#include <math.h>
double ainekio_v2_center_degrees(unsigned joint){return joint<12?v2_joint_center_degrees[joint%3]:NAN;}
double ainekio_v2_pulse_midpoint(void){return V2_SERVO_PULSE_MIDPOINT_US;}
double ainekio_v2_us_per_degree(void){return V2_SERVO_US_PER_DEGREE;}
unsigned ainekio_v2_pulse_reference(unsigned joint){return joint<12?v2_joint_reference_us[joint%3]:0;}
const char *ainekio_v2_servo_profile_id(void){return V2_SERVO_PROFILE_ID;}
