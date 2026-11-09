#ifndef AINEKIO_V2_MICRODUCK_H
#define AINEKIO_V2_MICRODUCK_H

#include "ainekio/v2_motion.h"
#include <stdbool.h>
#include <stdint.h>

#define AINEKIO_V2_MICRODUCK_SCHEMA "ainekio-neural-gait-v7-proprio"
#define AINEKIO_V2_MICRODUCK_FEATURES 48
#define AINEKIO_V2_MICRODUCK_SAMPLES 15
#define AINEKIO_V2_MICRODUCK_OBS_SIZE (AINEKIO_V2_MICRODUCK_FEATURES * AINEKIO_V2_MICRODUCK_SAMPLES)
#define AINEKIO_V2_MICRODUCK_H0 512
#define AINEKIO_V2_MICRODUCK_H1 256
#define AINEKIO_V2_MICRODUCK_H2 128
#define AINEKIO_V2_MICRODUCK_ACTIONS 12
#define AINEKIO_V2_MICRODUCK_RING_CAPACITY 16

/* Exported MicroDuck ONNX policy weights (obs_normalizer + 3-layer ELU MLP +
 * Tanh output + body-axis foot action scales in millimetres).
 * Weights use symmetric per-row int8 quantization (int8_t weight * float
 * row_scale) so the 534,016 weights fit in ~548 KB on the ESP32-P4 and fit
 * inside the 4 MB OTA partition while retaining <0.1 mm action accuracy. */
typedef struct {
    uint16_t h0, h1, h2;
    float obs_mean[AINEKIO_V2_MICRODUCK_OBS_SIZE];
    float obs_std[AINEKIO_V2_MICRODUCK_OBS_SIZE];
    int8_t weight0_q[AINEKIO_V2_MICRODUCK_H0][AINEKIO_V2_MICRODUCK_OBS_SIZE];
    float scale0[AINEKIO_V2_MICRODUCK_H0];
    float bias0[AINEKIO_V2_MICRODUCK_H0];
    int8_t weight1_q[AINEKIO_V2_MICRODUCK_H1][AINEKIO_V2_MICRODUCK_H0];
    float scale1[AINEKIO_V2_MICRODUCK_H1];
    float bias1[AINEKIO_V2_MICRODUCK_H1];
    int8_t weight2_q[AINEKIO_V2_MICRODUCK_H2][AINEKIO_V2_MICRODUCK_H1];
    float scale2[AINEKIO_V2_MICRODUCK_H2];
    float bias2[AINEKIO_V2_MICRODUCK_H2];
    int8_t weight3_q[AINEKIO_V2_MICRODUCK_ACTIONS][AINEKIO_V2_MICRODUCK_H2];
    float scale3[AINEKIO_V2_MICRODUCK_ACTIONS];
    float bias3[AINEKIO_V2_MICRODUCK_ACTIONS];
    float action_scale_mm[3];
} ainekio_v2_microduck_model_t;

extern const ainekio_v2_microduck_model_t ainekio_v2_microduck_default_model;

/* Per-walk 15-frame proprioceptive history, previous normalized action, and
 * working scratch buffers (kept in state/BSS rather than task stack). */
typedef struct {
    double sample_time_s[AINEKIO_V2_MICRODUCK_RING_CAPACITY];
    float samples[AINEKIO_V2_MICRODUCK_RING_CAPACITY][AINEKIO_V2_MICRODUCK_FEATURES];
    unsigned count;
    double last_time_s;
    float previous_action[AINEKIO_V2_MICRODUCK_ACTIONS];
    float scratch_features[AINEKIO_V2_MICRODUCK_FEATURES];
    float scratch_observation[AINEKIO_V2_MICRODUCK_OBS_SIZE];
    float scratch_action[AINEKIO_V2_MICRODUCK_ACTIONS];
    bool initialized;
} ainekio_v2_microduck_state_t;

void ainekio_v2_microduck_reset(ainekio_v2_microduck_state_t *state);

bool ainekio_v2_microduck_quantize_row(const float *weights, unsigned count,
    int8_t *quantized_out, float *scale_out);

bool ainekio_v2_microduck_model_valid(const ainekio_v2_microduck_model_t *model);

/* Assemble one 48-float proprioceptive snapshot matching ainekio-neural-gait-v7-proprio:
 * [0..11]  joint positions (rad, from measured centidegrees)
 * [12..23] joint velocities (rad/s, from measured centidegrees/s)
 * [24..26] body angular rate (rad/s)
 * [27..29] linear acceleration / 9.81 (g)
 * [30..32] negative projected gravity in body frame from orientation_wxyz
 * [33..35] commanded twist [vx_m_s, vy_m_s, wz_rad_s]
 * [36..47] previous normalized action [-1, 1] */
bool ainekio_v2_microduck_features(const ainekio_v2_frame_t *measured,
    const float orientation_wxyz[4], const float gyro_rad_s[3],
    const float accel_m_s2[3], const float command_twist[3],
    const float previous_action[AINEKIO_V2_MICRODUCK_ACTIONS],
    float features_out[AINEKIO_V2_MICRODUCK_FEATURES]);

/* Record a timestamped 48-float snapshot and project the 15-frame (720-float)
 * causal history at 20 ms intervals matching ObservationHistory.project(). */
bool ainekio_v2_microduck_observe(ainekio_v2_microduck_state_t *state,
    double timestamp_s, const float features[AINEKIO_V2_MICRODUCK_FEATURES],
    float observation_out[AINEKIO_V2_MICRODUCK_OBS_SIZE]);

/* Evaluate the normalized 720->512->256->128->12 ELU/Tanh MLP and scale to
 * body-coordinate foot offsets (mm) in physical model leg order. */
bool ainekio_v2_microduck_predict(const ainekio_v2_microduck_model_t *model,
    const float observation[AINEKIO_V2_MICRODUCK_OBS_SIZE],
    float action_out[AINEKIO_V2_MICRODUCK_ACTIONS],
    float feet_mm_out[4][3]);

/* End-to-end 50 Hz step: assemble features, update 15-frame history, run MLP,
 * update state->previous_action, and output feet_mm_out[4][3]. */
bool ainekio_v2_microduck_step(ainekio_v2_microduck_state_t *state,
    const ainekio_v2_microduck_model_t *model, double timestamp_s,
    const ainekio_v2_frame_t *measured, const float orientation_wxyz[4],
    const float gyro_rad_s[3], const float accel_m_s2[3],
    const float command_twist[3], float feet_mm_out[4][3]);

#endif
