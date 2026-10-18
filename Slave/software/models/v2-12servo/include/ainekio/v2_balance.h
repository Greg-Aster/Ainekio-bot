#ifndef AINEKIO_V2_BALANCE_H
#define AINEKIO_V2_BALANCE_H
#include "ainekio/v2_walk.h"
/* Multipliers of the existing standing/walking gains. Targets are offsets
 * from nominal: positive roll raises the left side, positive pitch the nose. */
typedef struct {
    float strength, damping, roll_deg, pitch_deg;
} ainekio_v2_balance_tuning_t;
#define AINEKIO_V2_BALANCE_TUNING_DEFAULT ((ainekio_v2_balance_tuning_t){1.F,1.F,0.F,0.F})
typedef struct {
    double correction[2], measured[2], applied_fraction;
    bool sensor_usable, reduced;
} ainekio_v2_balance_t;
/* Standing servo tracking is a separate proportional correction, in model
 * centidegrees. It never integrates a stalled joint's error. The caller keeps
 * the untrimmed gyro target separate from the command sent to the motors. */
typedef struct {
    double error_deg[12], trim_deg[12], applied_fraction;
    bool reduced;
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
/* Sustained leveling of a stationary nominal pose. Retains accepted extension
 * at zero error; existing geometry/speed reduction applies to the next
 * increment, so an unreachable request does not erase prior compensation. */
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
