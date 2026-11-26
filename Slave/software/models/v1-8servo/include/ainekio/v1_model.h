#ifndef AINEKIO_V1_MODEL_H
#define AINEKIO_V1_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Frozen V1 map-1 joint order (matches Slave/software/protocol/joints_v1.py):
 *   0: R1 (front_right hip)   4: R4 (rear_right knee)
 *   1: R2 (rear_right hip)    5: R3 (front_right knee)
 *   2: L1 (front_left hip)    6: L3 (front_left knee)
 *   3: L2 (rear_left hip)     7: L4 (rear_left knee)
 *
 * Signed model units: centidegrees from standing neutral (0 = standing pose).
 *   +hip  = swing leg forward (+X body) on all 4 legs
 *   +knee = lift / splay leg outward and upward (+Z) on all 4 legs
 */
#define AINEKIO_V1_JOINT_COUNT 8U
#define AINEKIO_V1_LEG_COUNT 4U
#define AINEKIO_V1_PULSE_MIN_US 500U
#define AINEKIO_V1_PULSE_NEUTRAL_US 1500U
#define AINEKIO_V1_PULSE_MAX_US 2500U
#define AINEKIO_V1_US_PER_DEGREE (1000.0f / 90.0f)
#define AINEKIO_V1_MAX_SPEED_DEG_S 600.0f

typedef enum {
    AINEKIO_V1_LEG_FR = 0,
    AINEKIO_V1_LEG_RR = 1,
    AINEKIO_V1_LEG_FL = 2,
    AINEKIO_V1_LEG_RL = 3,
} ainekio_v1_leg_t;

typedef enum {
    AINEKIO_V1_J_R1 = 0,
    AINEKIO_V1_J_R2 = 1,
    AINEKIO_V1_J_L1 = 2,
    AINEKIO_V1_J_L2 = 3,
    AINEKIO_V1_J_R4 = 4,
    AINEKIO_V1_J_R3 = 5,
    AINEKIO_V1_J_L3 = 6,
    AINEKIO_V1_J_L4 = 7,
} ainekio_v1_joint_id_t;

typedef struct {
    uint8_t id;
    const char *label;
    const char *name;
    ainekio_v1_leg_t leg;
    bool is_knee;
    uint8_t default_pca_channel;
    float min_deg;
    float max_deg;
} ainekio_v1_joint_info_t;

typedef struct {
    ainekio_v1_leg_t leg;
    const char *name;
    uint8_t hip_joint;
    uint8_t knee_joint;
    float neutral_yaw_deg;
    float hip_sign;
    float hip_in_body_mm[3];
    float knee_in_hip_mm[3];
    float foot_in_knee_mm[3];
    float foot_stand_body_mm[3];
} ainekio_v1_leg_geom_t;

extern const char ainekio_v1_geometry_id[];
extern const ainekio_v1_joint_info_t ainekio_v1_joints[AINEKIO_V1_JOINT_COUNT];
extern const ainekio_v1_leg_geom_t ainekio_v1_legs[AINEKIO_V1_LEG_COUNT];

/* Clamp model angles (deg or cd) to safe mechanical travel bounds. */
float ainekio_v1_clamp_joint_deg(uint8_t joint_id, float deg);
void ainekio_v1_clamp_angles_deg(float angles_deg[AINEKIO_V1_JOINT_COUNT]);

/* Exact 2-DOF per-leg Forward Kinematics (body frame, mm, +X fwd, +Y left, +Z up). */
void ainekio_v1_leg_fk(ainekio_v1_leg_t leg, float hip_deg, float knee_deg, float foot_body_mm[3]);

/* 2-DOF Inverse Kinematics from desired body-frame foot offset relative to standing (mm).
 * Maps (dx, dy) cleanly onto hip yaw angle and dz onto knee lift angle, clamped to limits. */
void ainekio_v1_leg_ik_offset(ainekio_v1_leg_t leg, const float offset_mm[3],
                              float *hip_deg_out, float *knee_deg_out);

/* Built-in V1 postures & analytic diagonal-trot gait (signed model degrees). */
bool ainekio_v1_posture_angles(const char *name, float out_deg[AINEKIO_V1_JOINT_COUNT]);
void ainekio_v1_walk_sample(double phase_0_1, float vx_norm, float vy_norm, float wz_norm,
                            float stride_scale, float out_deg[AINEKIO_V1_JOINT_COUNT]);

/* ============================================================================
 * Embedded 8-DOF V1 MicroDuck Neural Gait Policy (int8 row-quantized MLP)
 * Schema: "ainekio-v1-neural-gait-v2-cpg"
 * Features per 50 Hz frame (38 floats):
 *   [0..7]   measured joint positions (rad, model map-1 order)
 *   [8..15]  measured joint velocities (rad/s)
 *   [16..18] body angular rate (rad/s)
 *   [19..21] linear acceleration / 9.81 (g)
 *   [22..24] negative projected gravity in body frame
 *   [25..27] commanded twist [vx_m_s, vy_m_s, wz_rad_s]
 *   [28..35] previous normalized action [-1, 1]
 *   [36..37] gait phase oscillator [sin(2*pi*f*t), cos(2*pi*f*t)] (0 when still)
 * History: 8 causal frames @ 20 ms -> 304-float input -> 128 -> 64 -> 32 -> 8
 * Output: 8 normalized [-1, 1] joint target deltas around standing neutral,
 *         scaled by action_scale_deg[0] (hips) and action_scale_deg[1] (knees).
 * ============================================================================ */
#define AINEKIO_V1_MICRODUCK_SCHEMA "ainekio-v1-neural-gait-v2-cpg"
#define AINEKIO_V1_MICRODUCK_FEATURES 38U
#define AINEKIO_V1_MICRODUCK_SAMPLES 8U
#define AINEKIO_V1_MICRODUCK_OBS_SIZE (AINEKIO_V1_MICRODUCK_FEATURES * AINEKIO_V1_MICRODUCK_SAMPLES)
#define AINEKIO_V1_MICRODUCK_GAIT_HZ 3.0
#define AINEKIO_V1_MICRODUCK_H0 128U
#define AINEKIO_V1_MICRODUCK_H1 64U
#define AINEKIO_V1_MICRODUCK_H2 32U
#define AINEKIO_V1_MICRODUCK_ACTIONS AINEKIO_V1_JOINT_COUNT
#define AINEKIO_V1_MICRODUCK_RING_CAPACITY 16U

typedef struct {
    uint16_t h0, h1, h2;
    bool trained;
    float obs_mean[AINEKIO_V1_MICRODUCK_OBS_SIZE];
    float obs_std[AINEKIO_V1_MICRODUCK_OBS_SIZE];
    int8_t weight0_q[AINEKIO_V1_MICRODUCK_H0][AINEKIO_V1_MICRODUCK_OBS_SIZE];
    float scale0[AINEKIO_V1_MICRODUCK_H0];
    float bias0[AINEKIO_V1_MICRODUCK_H0];
    int8_t weight1_q[AINEKIO_V1_MICRODUCK_H1][AINEKIO_V1_MICRODUCK_H0];
    float scale1[AINEKIO_V1_MICRODUCK_H1];
    float bias1[AINEKIO_V1_MICRODUCK_H1];
    int8_t weight2_q[AINEKIO_V1_MICRODUCK_H2][AINEKIO_V1_MICRODUCK_H1];
    float scale2[AINEKIO_V1_MICRODUCK_H2];
    float bias2[AINEKIO_V1_MICRODUCK_H2];
    int8_t weight3_q[AINEKIO_V1_MICRODUCK_ACTIONS][AINEKIO_V1_MICRODUCK_H2];
    float scale3[AINEKIO_V1_MICRODUCK_ACTIONS];
    float bias3[AINEKIO_V1_MICRODUCK_ACTIONS];
    float action_scale_deg[2]; /* [0]=hip scale deg, [1]=knee scale deg */
} ainekio_v1_microduck_model_t;

extern const ainekio_v1_microduck_model_t ainekio_v1_microduck_default_model;

typedef struct {
    double sample_time_s[AINEKIO_V1_MICRODUCK_RING_CAPACITY];
    float samples[AINEKIO_V1_MICRODUCK_RING_CAPACITY][AINEKIO_V1_MICRODUCK_FEATURES];
    unsigned count;
    double last_time_s;
    float previous_action[AINEKIO_V1_MICRODUCK_ACTIONS];
    float scratch_features[AINEKIO_V1_MICRODUCK_FEATURES];
    float scratch_observation[AINEKIO_V1_MICRODUCK_OBS_SIZE];
    float scratch_action[AINEKIO_V1_MICRODUCK_ACTIONS];
    bool initialized;
} ainekio_v1_microduck_state_t;

void ainekio_v1_microduck_reset(ainekio_v1_microduck_state_t *state);
bool ainekio_v1_microduck_model_valid(const ainekio_v1_microduck_model_t *model);
bool ainekio_v1_microduck_features(
    const float joint_pos_deg[AINEKIO_V1_JOINT_COUNT],
    const float joint_vel_deg_s[AINEKIO_V1_JOINT_COUNT],
    const float orientation_wxyz[4],
    const float gyro_rad_s[3],
    const float accel_m_s2[3],
    const float command_twist[3],
    const float previous_action[AINEKIO_V1_MICRODUCK_ACTIONS],
    double timestamp_s,
    float features_out[AINEKIO_V1_MICRODUCK_FEATURES]);
bool ainekio_v1_microduck_observe(
    ainekio_v1_microduck_state_t *state,
    double timestamp_s,
    const float features[AINEKIO_V1_MICRODUCK_FEATURES],
    float observation_out[AINEKIO_V1_MICRODUCK_OBS_SIZE]);
bool ainekio_v1_microduck_predict(
    const ainekio_v1_microduck_model_t *model,
    const float observation[AINEKIO_V1_MICRODUCK_OBS_SIZE],
    float action_out[AINEKIO_V1_MICRODUCK_ACTIONS],
    float joint_targets_deg_out[AINEKIO_V1_JOINT_COUNT]);
bool ainekio_v1_microduck_step(
    ainekio_v1_microduck_state_t *state,
    const ainekio_v1_microduck_model_t *model,
    double timestamp_s,
    const float joint_pos_deg[AINEKIO_V1_JOINT_COUNT],
    const float joint_vel_deg_s[AINEKIO_V1_JOINT_COUNT],
    const float orientation_wxyz[4],
    const float gyro_rad_s[3],
    const float accel_m_s2[3],
    const float command_twist[3],
    float joint_targets_deg_out[AINEKIO_V1_JOINT_COUNT]);

#ifdef __cplusplus
}
#endif

#endif /* AINEKIO_V1_MODEL_H */
