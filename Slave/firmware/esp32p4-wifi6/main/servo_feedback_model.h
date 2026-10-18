#pragma once
#include <stdbool.h>
#include <stdint.h>

enum { AINEKIO_FEEDBACK_CHANNELS=16, AINEKIO_FEEDBACK_JOINTS=12,
       AINEKIO_FEEDBACK_POINTS=3, AINEKIO_FEEDBACK_VERSION=1 };
typedef struct {
    uint16_t raw, pulse_us;
} ainekio_feedback_point_t;
typedef struct {
    uint8_t channel, points;
    uint16_t reserved;
    ainekio_feedback_point_t point[AINEKIO_FEEDBACK_POINTS];
} ainekio_feedback_joint_t;
typedef struct {
    uint32_t version;
    uint8_t enabled, stand_enabled;
    uint16_t tolerance_us;
    ainekio_feedback_joint_t joint[AINEKIO_FEEDBACK_JOINTS];
} ainekio_feedback_config_t;
void ainekio_feedback_defaults(ainekio_feedback_config_t *config);
bool ainekio_feedback_config_valid(const ainekio_feedback_config_t *config);
bool ainekio_feedback_calibrated(const ainekio_feedback_joint_t *joint);
/* Returns pulse-equivalent shaft position, not a command or mechanical angle.
 * Outside the captured range, extrapolate explicitly; never clip travel. */
bool ainekio_feedback_position(const ainekio_feedback_joint_t *joint,
    double raw,double *pulse_us,bool *in_range);
