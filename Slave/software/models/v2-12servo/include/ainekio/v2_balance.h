#ifndef AINEKIO_V2_BALANCE_H
#define AINEKIO_V2_BALANCE_H
#include "ainekio/v2_walk.h"
/* Multipliers of the existing standing/walking gains. Targets are offsets
 * from nominal: positive roll raises the left side, positive pitch the nose. */
typedef struct {
    float strength, damping, roll_deg, pitch_deg;
} ainekio_v2_balance_tuning_t;
#define AINEKIO_V2_BALANCE_TUNING_DEFAULT ((ainekio_v2_balance_tuning_t){1.F,1.F,0.F,0.F})
/* Existing moving-body attitude response, shared by roll/pitch and host yaw.
 * Error is radians; rate is measured minus requested rad/s. Coefficients are
 * the established moving-balance gains: 0.4 proportional, 0.05s derivative,
 * 0.25s response time. This filters only the added correction, not nominal
 * motion, and adds no motion-admission or completion wait. */
double ainekio_v2_moving_attitude_response(double correction,double error,
    double rate,bool usable,double dt,double strength,double damping);
typedef struct {
    double correction[2], measured[2], applied_fraction;
    bool sensor_usable, reduced;
    double actuator_bias_deg[12];
    bool actuator_reference_valid;
} ainekio_v2_balance_t;
/* Standing servo tracking is a separate proportional correction, in model
 * centidegrees. It never integrates a stalled joint's error. The caller keeps
 * the untrimmed gyro target separate from the command sent to the motors. */
typedef struct {
    double error_deg[12], trim_deg[12], applied_fraction;
    double body_lag_rad[2];
    bool reduced, observable;
} ainekio_v2_balance_tracking_t;
void ainekio_v2_balance_track(const ainekio_v2_frame_t *target,
    const ainekio_v2_frame_t *measured,const ainekio_v2_frame_t *previous,
    double dt,double joint_speed_deg_s,ainekio_v2_frame_t *output,
    ainekio_v2_balance_tracking_t *tracking);
/* Position error inside the measured noise band produces no additional trim.
 * Outside it, use only the excess error so the correction is continuous. */
void ainekio_v2_balance_track_tolerant(const ainekio_v2_frame_t *target,
    const ainekio_v2_frame_t *measured,const ainekio_v2_frame_t *previous,
    const double tolerance_deg[12],double dt,double joint_speed_deg_s,
    ainekio_v2_frame_t *output,ainekio_v2_balance_tracking_t *tracking);
/* Body-to-world quaternion and body angular rates. Yaw is not controlled.
 * Unavailable observations fade the correction; nominal motion continues.
 * local_points==NULL selects the ordinary locomotion reference points. */
void ainekio_v2_balance_apply(ainekio_v2_balance_t *state,
    const float orientation[4],const float angular_rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed_deg_s,
    ainekio_v2_walk_pose_t *output);
/* Sustained leveling of a stationary nominal pose. Correction strength tapers
 * toward level; accepted targets have no additional joint-speed ramp. Retains
 * extension at zero error; geometry reduction preserves reachable compensation.
 * Unavailable-sensor fade continues using the existing speed setting. */
void ainekio_v2_balance_hold_apply(ainekio_v2_balance_t *state,
    const float orientation[4],const float angular_rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed_deg_s,
    ainekio_v2_walk_pose_t *output);
/* Explicit settings for the output owner; existing wrappers use defaults. */
void ainekio_v2_balance_configured_apply(ainekio_v2_balance_t *state,
    const float orientation[4],const float angular_rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed_deg_s,
    ainekio_v2_walk_pose_t *output,const ainekio_v2_balance_tuning_t *tuning,bool standing);
/* Stationary outer-loop tracking of measured actuator progress. Joint errors
 * outside tolerance are projected onto the commanded roll/pitch geometry and
 * back-calculated into the accepted offset. No additional joint overdrive. */
void ainekio_v2_balance_feedback_apply(ainekio_v2_balance_t *state,
    const float orientation[4],const float angular_rate[3],double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,const ainekio_v2_frame_t *measured,
    const double tolerance_deg[12],ainekio_v2_walk_pose_t *output,
    const ainekio_v2_balance_tuning_t *tuning,ainekio_v2_balance_tracking_t *tracking);
/* Output-owner response polarity; +1 retains the model convention, -1 reverses
 * both attitude error and rate response. Sensor and saved target signs stay
 * unchanged. This is not a sensor mounting calibration. */
void ainekio_v2_balance_response_apply(ainekio_v2_balance_t *state,
    const float orientation[4],const float angular_rate[3],bool usable,double dt,
    const ainekio_v2_walk_pose_t *nominal,const double local_points[4][3],
    const ainekio_v2_frame_t *previous,double joint_speed_deg_s,
    ainekio_v2_walk_pose_t *output,const ainekio_v2_balance_tuning_t *tuning,
    bool standing,double response_direction);
#endif
