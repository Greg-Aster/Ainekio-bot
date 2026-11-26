#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif

enum { AINEKIO_FEEDBACK_CHANNELS=16, AINEKIO_FEEDBACK_JOINTS=12,
       AINEKIO_FEEDBACK_POINTS=3, AINEKIO_FEEDBACK_VERSION=4 };
#ifdef CONFIG_AINEKIO_MODEL_V1_8SERVO
#define AINEKIO_FEEDBACK_ACTIVE_JOINTS 8U
#define AINEKIO_FEEDBACK_ACTIVE_MASK 0x00FFU
#else
#define AINEKIO_FEEDBACK_ACTIVE_JOINTS 12U
#define AINEKIO_FEEDBACK_ACTIVE_MASK 0x0FFFU
#endif
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
    uint16_t tolerance_us; /* Jam error band; retained wire/NVS name. */
    ainekio_feedback_joint_t joint[AINEKIO_FEEDBACK_JOINTS];
    uint32_t no_progress_ms; /* Owner-selected observation window; 0 disables jam reports. */
    uint16_t progress_us; /* Minimum new shaft travel toward target. */
    uint8_t jam_enabled, reserved; /* Independent of measured motion coordination. */
    uint16_t arrival_tolerance_us, reserved_arrival;
} ainekio_feedback_config_t;
bool ainekio_feedback_config_decode(const void *blob,size_t size,ainekio_feedback_config_t *out);
void ainekio_feedback_defaults(ainekio_feedback_config_t *config);
bool ainekio_feedback_config_valid(const ainekio_feedback_config_t *config);
bool ainekio_feedback_calibrated(const ainekio_feedback_joint_t *joint);
/* Returns pulse-equivalent shaft position, not a command or mechanical angle.
 * Outside the captured range, extrapolate explicitly; never clip travel. */
bool ainekio_feedback_position(const ainekio_feedback_joint_t *joint,
    double raw,double *pulse_us,bool *in_range);
/* Motion-adaptive measurement filter. Raw calibration samples stay separate.
 * Timestamped per channel; no target commands, travel clipping or blocking. */
typedef struct {
    double raw, position, derivative, velocity;
    int64_t sampled_us;
    bool initialized;
} ainekio_feedback_filter_t;
void ainekio_feedback_filter_update(ainekio_feedback_filter_t *filter,
    double raw,int64_t sampled_us);

#define AINEKIO_FEEDBACK_THERMAL_DEADBAND_DEG 7.0f
#define AINEKIO_FEEDBACK_THERMAL_SLEW_DEG_S 12.0f
#define AINEKIO_FEEDBACK_THERMAL_FULL_SPAN_DEG 11.0f
#define AINEKIO_FEEDBACK_THERMAL_MAX_DUTY 1.25f
#define AINEKIO_FEEDBACK_THERMAL_TRIP_SECONDS 9.0f
#define AINEKIO_FEEDBACK_THERMAL_COOL_SECONDS 12.0f
#define AINEKIO_FEEDBACK_THERMAL_REARM_LOAD 0.35f

float ainekio_feedback_thermal_update(float load,bool energized,
    bool measured_valid,float err_deg,float vel_toward_deg_s,float dt_s);
