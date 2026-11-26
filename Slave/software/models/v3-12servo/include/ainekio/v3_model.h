#ifndef AINEKIO_V3_MODEL_H
#define AINEKIO_V3_MODEL_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define AINEKIO_V3_MODEL_NAME "v3-12servo"
#define AINEKIO_V3_GEOMETRY_ID "v3-p4-ds3225pro-optA1-ankle-20261122"
#define AINEKIO_V3_SERVO_PROFILE_ID "ds3225pro-270-v3-p4"

#define AINEKIO_V3_JOINT_COUNT 12U
#define AINEKIO_V3_LEG_COUNT 4U

/* DSServo DS3225 PRO (270 deg, 7.4V HV coreless) nominal PWM contract */
#define AINEKIO_V3_PULSE_MIN_US 500U
#define AINEKIO_V3_PULSE_MAX_US 2500U
#define AINEKIO_V3_PULSE_CENTER_US 1500U
#define AINEKIO_V3_US_PER_DEGREE 7.4074f
#define AINEKIO_V3_MAX_SPEED_DEG_S 800.0f

/* Option A-1 4-bar linkage dimensions (mm) */
#define AINEKIO_V3_CARRIER_MM 54.0f
#define AINEKIO_V3_CRANK_MM 22.0f
#define AINEKIO_V3_PICKUP_MM 46.0f
#define AINEKIO_V3_ROD_MM 56.0f
#define AINEKIO_V3_ALPHA_ZERO_RAD (-2.202809465985f)
#define AINEKIO_V3_THETA_ZERO_RAD (3.055204643652f)
#define AINEKIO_V3_BETA_OFFSET_RAD (3.5672784535897932f)
#define AINEKIO_V3_STAND_SHOULDER_Z_MM 180.9336f

/* Embedded 12-DOF V2-aligned proprioceptive foot-offset IK gait contract:
 * ainekio-v3-neural-gait-v2-proprio (50 features x 12 frames = 600 obs, speed-adaptive 1.30..2.00 Hz trot clock).
 * Policy outputs 12 normalized [-1, 1] Cartesian foot offsets [dx, dy, dz] per leg,
 * scaled by action_scale_mm and decoded through ainekio_v3_leg_ik_offset() with
 * 8-step boundary bisection projection (1/256 resolution, matching V3TensorBody.decode()). */
#define AINEKIO_V3_MICRODUCK_SCHEMA "ainekio-v3-neural-gait-v2-proprio"
#define AINEKIO_V3_MICRODUCK_FEATURES 50U
#define AINEKIO_V3_MICRODUCK_SAMPLES 12U
#define AINEKIO_V3_MICRODUCK_OBS_SIZE (AINEKIO_V3_MICRODUCK_FEATURES * AINEKIO_V3_MICRODUCK_SAMPLES)
#define AINEKIO_V3_MICRODUCK_H0 128U
#define AINEKIO_V3_MICRODUCK_H1 64U
#define AINEKIO_V3_MICRODUCK_H2 32U
#define AINEKIO_V3_MICRODUCK_ACTIONS 12U
#define AINEKIO_V3_MICRODUCK_RING_CAPACITY 32U
#define AINEKIO_V3_MICRODUCK_GAIT_HZ 1.65
#define AINEKIO_V3_MICRODUCK_GAIT_HZ_MIN 1.30
#define AINEKIO_V3_MICRODUCK_GAIT_HZ_MAX 2.00
#define AINEKIO_V3_FOOT_SCALE_X_MM 78.0f
#define AINEKIO_V3_FOOT_SCALE_Y_MM 28.0f
#define AINEKIO_V3_FOOT_SCALE_Z_MM 36.0f

typedef enum {
    AINEKIO_V3_LEG_RL = 0,
    AINEKIO_V3_LEG_RR = 1,
    AINEKIO_V3_LEG_FL = 2,
    AINEKIO_V3_LEG_FR = 3,
} ainekio_v3_leg_id_t;

typedef enum {
    AINEKIO_V3_AXIS_SHOULDER = 0,
    AINEKIO_V3_AXIS_CARRIER = 1,
    AINEKIO_V3_AXIS_CRANK = 2,
} ainekio_v3_axis_t;

typedef struct {
    uint8_t id;
    const char *name;
    ainekio_v3_leg_id_t leg;
    ainekio_v3_axis_t axis;
    float min_deg;
    float max_deg;
} ainekio_v3_joint_spec_t;

typedef struct {
    ainekio_v3_leg_id_t id;
    const char *name;
    uint8_t shoulder_joint;
    uint8_t carrier_joint;
    uint8_t crank_joint;
    float roll_sign;
    float shoulder_in_robot_mm[3];
    float carrier_in_shoulder_mm[3];
    float crank_in_shoulder_mm[3];
    float sole_in_knee_mm[3];
    float neutral_sole_in_robot_mm[3];
} ainekio_v3_leg_spec_t;

typedef struct {
    float foot_robot_mm[3];
    float knee_shoulder_mm[3];
    float knee_rot_y_rad;
    float separation_mm;
    float sin_transmission;
} ainekio_v3_fk_result_t;

typedef struct {
    uint16_t h0;
    uint16_t h1;
    uint16_t h2;
    bool trained;
    float obs_mean[AINEKIO_V3_MICRODUCK_OBS_SIZE];
    float obs_std[AINEKIO_V3_MICRODUCK_OBS_SIZE];
    float action_scale_mm[3];
    int8_t weight0_q[AINEKIO_V3_MICRODUCK_H0][AINEKIO_V3_MICRODUCK_OBS_SIZE];
    float scale0[AINEKIO_V3_MICRODUCK_H0];
    float bias0[AINEKIO_V3_MICRODUCK_H0];
    int8_t weight1_q[AINEKIO_V3_MICRODUCK_H1][AINEKIO_V3_MICRODUCK_H0];
    float scale1[AINEKIO_V3_MICRODUCK_H1];
    float bias1[AINEKIO_V3_MICRODUCK_H1];
    int8_t weight2_q[AINEKIO_V3_MICRODUCK_H2][AINEKIO_V3_MICRODUCK_H1];
    float scale2[AINEKIO_V3_MICRODUCK_H2];
    float bias2[AINEKIO_V3_MICRODUCK_H2];
    int8_t weight3_q[AINEKIO_V3_MICRODUCK_ACTIONS][AINEKIO_V3_MICRODUCK_H2];
    float scale3[AINEKIO_V3_MICRODUCK_ACTIONS];
    float bias3[AINEKIO_V3_MICRODUCK_ACTIONS];
} ainekio_v3_microduck_model_t;

typedef struct {
    bool initialized;
    double last_time_s;
    double phase_rad;
    unsigned count;
    double sample_time_s[AINEKIO_V3_MICRODUCK_RING_CAPACITY];
    float samples[AINEKIO_V3_MICRODUCK_RING_CAPACITY][AINEKIO_V3_MICRODUCK_FEATURES];
    float previous_action[AINEKIO_V3_MICRODUCK_ACTIONS];
    float scratch_features[AINEKIO_V3_MICRODUCK_FEATURES];
    float scratch_observation[AINEKIO_V3_MICRODUCK_OBS_SIZE];
    float scratch_action[AINEKIO_V3_MICRODUCK_ACTIONS];
} ainekio_v3_microduck_state_t;

extern const ainekio_v3_joint_spec_t ainekio_v3_joints[AINEKIO_V3_JOINT_COUNT];
extern const ainekio_v3_leg_spec_t ainekio_v3_legs[AINEKIO_V3_LEG_COUNT];
extern const ainekio_v3_microduck_model_t ainekio_v3_microduck_default_model;

float ainekio_v3_clamp_joint_deg(uint8_t joint_id, float deg);

bool ainekio_v3_leg_fk(
    ainekio_v3_leg_id_t leg,
    float h_deg,
    float alpha_deg,
    float theta_deg,
    ainekio_v3_fk_result_t *out);

bool ainekio_v3_leg_ik_offset(
    ainekio_v3_leg_id_t leg,
    float dx_mm,
    float dy_mm,
    float dz_mm,
    float *h_deg_out,
    float *alpha_deg_out,
    float *theta_deg_out);

bool ainekio_v3_posture_angles(
    const char *name,
    float angles_deg_out[AINEKIO_V3_JOINT_COUNT]);

void ainekio_v3_analytic_trot(
    double phase_cycles,
    float vx_m_s,
    float vy_m_s,
    float wz_rad_s,
    float angles_deg_out[AINEKIO_V3_JOINT_COUNT]);

void ainekio_v3_microduck_reset(ainekio_v3_microduck_state_t *state);
bool ainekio_v3_microduck_model_valid(const ainekio_v3_microduck_model_t *model);

bool ainekio_v3_microduck_features(
    const float joint_pos_deg[AINEKIO_V3_JOINT_COUNT],
    const float joint_vel_deg_s[AINEKIO_V3_JOINT_COUNT],
    const float orientation_wxyz[4],
    const float gyro_rad_s[3],
    const float accel_m_s2[3],
    const float command_twist[3],
    const float previous_action[AINEKIO_V3_MICRODUCK_ACTIONS],
    double timestamp_s,
    float features_out[AINEKIO_V3_MICRODUCK_FEATURES]);

bool ainekio_v3_microduck_observe(
    ainekio_v3_microduck_state_t *state,
    double timestamp_s,
    const float features[AINEKIO_V3_MICRODUCK_FEATURES],
    float observation_out[AINEKIO_V3_MICRODUCK_OBS_SIZE]);

bool ainekio_v3_microduck_predict(
    const ainekio_v3_microduck_model_t *model,
    const float observation[AINEKIO_V3_MICRODUCK_OBS_SIZE],
    float action_out[AINEKIO_V3_MICRODUCK_ACTIONS],
    float joint_targets_deg_out[AINEKIO_V3_JOINT_COUNT]);

bool ainekio_v3_microduck_step(
    ainekio_v3_microduck_state_t *state,
    const ainekio_v3_microduck_model_t *model,
    double timestamp_s,
    const float joint_pos_deg[AINEKIO_V3_JOINT_COUNT],
    const float joint_vel_deg_s[AINEKIO_V3_JOINT_COUNT],
    const float orientation_wxyz[4],
    const float gyro_rad_s[3],
    const float accel_m_s2[3],
    const float command_twist[3],
    float joint_targets_deg_out[AINEKIO_V3_JOINT_COUNT]);

#ifdef __cplusplus
}
#endif

#endif
