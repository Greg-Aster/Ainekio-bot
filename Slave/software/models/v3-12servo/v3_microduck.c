#include "ainekio/v3_model.h"
#include <math.h>
#include <string.h>

static float elu(float x)
{
    return x >= 0.f ? x : expm1f(x);
}

void ainekio_v3_microduck_reset(ainekio_v3_microduck_state_t *state)
{
    if (!state) return;
    memset(state, 0, sizeof(*state));
}

static bool resolve_dims(const ainekio_v3_microduck_model_t *model,
                         unsigned *d0, unsigned *d1, unsigned *d2)
{
    if (!model) return false;
    *d0 = model->h0 ? model->h0 : AINEKIO_V3_MICRODUCK_H0;
    *d1 = model->h1 ? model->h1 : AINEKIO_V3_MICRODUCK_H1;
    *d2 = model->h2 ? model->h2 : AINEKIO_V3_MICRODUCK_H2;
    return *d0 >= 1 && *d0 <= AINEKIO_V3_MICRODUCK_H0 &&
           *d1 >= 1 && *d1 <= AINEKIO_V3_MICRODUCK_H1 &&
           *d2 >= 1 && *d2 <= AINEKIO_V3_MICRODUCK_H2;
}

bool ainekio_v3_microduck_model_valid(const ainekio_v3_microduck_model_t *model)
{
    unsigned d0, d1, d2;
    if (!resolve_dims(model, &d0, &d1, &d2)) return false;
    for (unsigned a = 0; a < 3; ++a)
        if (!isfinite(model->action_scale_mm[a]) || model->action_scale_mm[a] <= 0.f) return false;
    for (unsigned i = 0; i < AINEKIO_V3_MICRODUCK_OBS_SIZE; ++i)
        if (!isfinite(model->obs_mean[i]) || !isfinite(model->obs_std[i]) || model->obs_std[i] <= 0.f) return false;
    for (unsigned j = 0; j < d0; ++j)
        if (!isfinite(model->bias0[j]) || !isfinite(model->scale0[j]) || model->scale0[j] < 0.f) return false;
    for (unsigned j = 0; j < d1; ++j)
        if (!isfinite(model->bias1[j]) || !isfinite(model->scale1[j]) || model->scale1[j] < 0.f) return false;
    for (unsigned j = 0; j < d2; ++j)
        if (!isfinite(model->bias2[j]) || !isfinite(model->scale2[j]) || model->scale2[j] < 0.f) return false;
    for (unsigned j = 0; j < AINEKIO_V3_MICRODUCK_ACTIONS; ++j)
        if (!isfinite(model->bias3[j]) || !isfinite(model->scale3[j]) || model->scale3[j] < 0.f) return false;
    return true;
}

static double v3_gait_hz(const float command_twist[3])
{
    const double lin = hypot((double)command_twist[0], (double)command_twist[1]);
    const double eff = lin / 0.38 + 0.45 * fabs((double)command_twist[2]) / 1.30;
    const double u = eff < 0.0 ? 0.0 : (eff > 1.0 ? 1.0 : eff);
    return AINEKIO_V3_MICRODUCK_GAIT_HZ_MIN
         + (AINEKIO_V3_MICRODUCK_GAIT_HZ_MAX - AINEKIO_V3_MICRODUCK_GAIT_HZ_MIN) * u;
}

bool ainekio_v3_microduck_features(
    const float joint_pos_deg[AINEKIO_V3_JOINT_COUNT],
    const float joint_vel_deg_s[AINEKIO_V3_JOINT_COUNT],
    const float orientation_wxyz[4],
    const float gyro_rad_s[3],
    const float accel_m_s2[3],
    const float command_twist[3],
    const float previous_action[AINEKIO_V3_MICRODUCK_ACTIONS],
    double timestamp_s,
    float features_out[AINEKIO_V3_MICRODUCK_FEATURES])
{
    if (!joint_pos_deg || !joint_vel_deg_s || !orientation_wxyz || !gyro_rad_s ||
        !accel_m_s2 || !command_twist || !previous_action || !features_out || !isfinite(timestamp_s))
        return false;
    const double deg_to_rad = 3.14159265358979323846 / 180.0;
    for (unsigned j = 0; j < AINEKIO_V3_JOINT_COUNT; ++j) {
        if (!isfinite(joint_pos_deg[j]) || !isfinite(joint_vel_deg_s[j]) ||
            !isfinite(previous_action[j]) || fabsf(previous_action[j]) > 1.000001f)
            return false;
        features_out[j] = (float)((double)joint_pos_deg[j] * deg_to_rad);
        features_out[12 + j] = (float)((double)joint_vel_deg_s[j] * deg_to_rad);
        features_out[36 + j] = previous_action[j];
    }
    for (unsigned i = 0; i < 4; ++i)
        if (!isfinite(orientation_wxyz[i])) return false;
    for (unsigned a = 0; a < 3; ++a) {
        if (!isfinite(gyro_rad_s[a]) || !isfinite(accel_m_s2[a]) || !isfinite(command_twist[a]))
            return false;
        features_out[24 + a] = gyro_rad_s[a];
        features_out[27 + a] = (float)((double)accel_m_s2[a] / 9.81);
        features_out[33 + a] = command_twist[a];
    }
    const double w = orientation_wxyz[0], x = orientation_wxyz[1];
    const double y = orientation_wxyz[2], z = orientation_wxyz[3];
    features_out[30] = (float)(-2.0 * (x * z - w * y));
    features_out[31] = (float)(-2.0 * (y * z + w * x));
    features_out[32] = (float)(1.0 - 2.0 * (w * w + z * z));

    const double cmd_mag = hypot((double)command_twist[0], (double)command_twist[1])
                         + 0.18 * fabs((double)command_twist[2]);
    if (cmd_mag > 0.02) {
        const double ph = 2.0 * 3.14159265358979323846 * v3_gait_hz(command_twist) * timestamp_s;
        features_out[48] = (float)sin(ph);
        features_out[49] = (float)cos(ph);
    } else {
        features_out[48] = 0.0f;
        features_out[49] = 0.0f;
    }
    return true;
}

bool ainekio_v3_microduck_observe(
    ainekio_v3_microduck_state_t *state,
    double timestamp_s,
    const float features[AINEKIO_V3_MICRODUCK_FEATURES],
    float observation_out[AINEKIO_V3_MICRODUCK_OBS_SIZE])
{
    if (!state || !features || !observation_out || !isfinite(timestamp_s) || timestamp_s < 0.0)
        return false;
    for (unsigned i = 0; i < AINEKIO_V3_MICRODUCK_FEATURES; ++i)
        if (!isfinite(features[i])) return false;
    if (!state->initialized || timestamp_s < state->last_time_s) {
        state->count = 0;
        state->initialized = true;
    }
    state->last_time_s = timestamp_s;
    if (state->count > 0 && state->sample_time_s[state->count - 1] == timestamp_s) {
        memcpy(state->samples[state->count - 1], features, sizeof(float) * AINEKIO_V3_MICRODUCK_FEATURES);
    } else {
        if (state->count == AINEKIO_V3_MICRODUCK_RING_CAPACITY) {
            memmove(&state->sample_time_s[0], &state->sample_time_s[1],
                    sizeof(double) * (AINEKIO_V3_MICRODUCK_RING_CAPACITY - 1));
            memmove(&state->samples[0], &state->samples[1],
                    sizeof(state->samples[0]) * (AINEKIO_V3_MICRODUCK_RING_CAPACITY - 1));
            --state->count;
        }
        state->sample_time_s[state->count] = timestamp_s;
        memcpy(state->samples[state->count], features, sizeof(float) * AINEKIO_V3_MICRODUCK_FEATURES);
        ++state->count;
    }
    while (state->count > 1 &&
           state->sample_time_s[1] < timestamp_s - (double)AINEKIO_V3_MICRODUCK_SAMPLES * 0.02) {
        memmove(&state->sample_time_s[0], &state->sample_time_s[1], sizeof(double) * (state->count - 1));
        memmove(&state->samples[0], &state->samples[1], sizeof(state->samples[0]) * (state->count - 1));
        --state->count;
    }
    for (unsigned index = 0; index < AINEKIO_V3_MICRODUCK_SAMPLES; ++index) {
        const double target_s = timestamp_s - (double)index * 0.02 + 1e-9;
        float *dest = &observation_out[index * AINEKIO_V3_MICRODUCK_FEATURES];
        int matched = -1;
        for (int s = (int)state->count - 1; s >= 0; --s) {
            if (state->sample_time_s[s] <= target_s) {
                matched = s;
                break;
            }
        }
        if (matched >= 0)
            memcpy(dest, state->samples[matched], sizeof(float) * AINEKIO_V3_MICRODUCK_FEATURES);
        else
            memset(dest, 0, sizeof(float) * AINEKIO_V3_MICRODUCK_FEATURES);
    }
    return true;
}

static void quantize_activations(const float *src, unsigned n, int16_t *dst, float *scale_out)
{
    float max_abs = 0.f;
    for (unsigned i = 0; i < n; ++i) {
        const float a = fabsf(src[i]);
        if (a > max_abs) max_abs = a;
    }
    if (max_abs < 1e-12f) {
        *scale_out = 0.f;
        memset(dst, 0, n * sizeof(int16_t));
        return;
    }
    const float inv = 32767.f / max_abs;
    *scale_out = max_abs / 32767.f;
    for (unsigned i = 0; i < n; ++i) {
        int q = (int)lroundf(src[i] * inv);
        if (q < -32767) q = -32767;
        else if (q > 32767) q = 32767;
        dst[i] = (int16_t)q;
    }
}

static int32_t dot_i8_i16(const int8_t *w, const int16_t *x, unsigned n)
{
    int32_t acc = 0;
    for (unsigned i = 0; i < n; ++i)
        acc += (int32_t)w[i] * (int32_t)x[i];
    return acc;
}

bool ainekio_v3_microduck_predict(
    const ainekio_v3_microduck_model_t *model,
    const float observation[AINEKIO_V3_MICRODUCK_OBS_SIZE],
    float action_out[AINEKIO_V3_MICRODUCK_ACTIONS],
    float joint_targets_deg_out[AINEKIO_V3_JOINT_COUNT])
{
    unsigned d0, d1, d2;
    if (!model || !observation || !action_out || !joint_targets_deg_out ||
        !resolve_dims(model, &d0, &d1, &d2))
        return false;

    float norm_obs[AINEKIO_V3_MICRODUCK_OBS_SIZE];
    int16_t x0_q[AINEKIO_V3_MICRODUCK_OBS_SIZE];
    float x0_s = 0.f;
    for (unsigned i = 0; i < AINEKIO_V3_MICRODUCK_OBS_SIZE; ++i) {
        if (!isfinite(observation[i])) return false;
        norm_obs[i] = (observation[i] - model->obs_mean[i]) / model->obs_std[i];
    }
    quantize_activations(norm_obs, AINEKIO_V3_MICRODUCK_OBS_SIZE, x0_q, &x0_s);

    float h0[AINEKIO_V3_MICRODUCK_H0];
    int16_t h0_q[AINEKIO_V3_MICRODUCK_H0];
    float h0_s = 0.f;
    for (unsigned r = 0; r < d0; ++r) {
        const float v = (float)dot_i8_i16(model->weight0_q[r], x0_q, AINEKIO_V3_MICRODUCK_OBS_SIZE)
                        * (model->scale0[r] * x0_s) + model->bias0[r];
        h0[r] = elu(v);
    }
    quantize_activations(h0, d0, h0_q, &h0_s);

    float h1[AINEKIO_V3_MICRODUCK_H1];
    int16_t h1_q[AINEKIO_V3_MICRODUCK_H1];
    float h1_s = 0.f;
    for (unsigned r = 0; r < d1; ++r) {
        const float v = (float)dot_i8_i16(model->weight1_q[r], h0_q, d0)
                        * (model->scale1[r] * h0_s) + model->bias1[r];
        h1[r] = elu(v);
    }
    quantize_activations(h1, d1, h1_q, &h1_s);

    float h2[AINEKIO_V3_MICRODUCK_H2];
    int16_t h2_q[AINEKIO_V3_MICRODUCK_H2];
    float h2_s = 0.f;
    for (unsigned r = 0; r < d2; ++r) {
        const float v = (float)dot_i8_i16(model->weight2_q[r], h1_q, d1)
                        * (model->scale2[r] * h1_s) + model->bias2[r];
        h2[r] = elu(v);
    }
    quantize_activations(h2, d2, h2_q, &h2_s);

    for (unsigned j = 0; j < AINEKIO_V3_MICRODUCK_ACTIONS; ++j) {
        const float raw = (float)dot_i8_i16(model->weight3_q[j], h2_q, d2)
                          * (model->scale3[j] * h2_s) + model->bias3[j];
        const float a = tanhf(raw);
        if (!isfinite(a)) return false;
        action_out[j] = a;
    }

    for (unsigned l = 0; l < AINEKIO_V3_LEG_COUNT; ++l) {
        const float dx = action_out[3U * l + 0U] * model->action_scale_mm[0];
        const float dy = action_out[3U * l + 1U] * model->action_scale_mm[1];
        const float dz = action_out[3U * l + 2U] * model->action_scale_mm[2];
        float h_deg = 0.0f, alpha_deg = 0.0f, theta_deg = 0.0f;
        if (!ainekio_v3_leg_ik_offset((ainekio_v3_leg_id_t)l,
                                      dx, dy, dz,
                                      &h_deg, &alpha_deg, &theta_deg)) {
            const float z_ref = dz < 0.0f ? 0.0f : (dz > 14.0f ? 14.0f : dz);
            float rh = 0.0f, ra = 0.0f, rt = 0.0f;
            if (ainekio_v3_leg_ik_offset((ainekio_v3_leg_id_t)l,
                                         dx, dy, z_ref,
                                         &rh, &ra, &rt)) {
                /* Stage 1: preserve 100% of horizontal stride (dx, dy), bisect z from z_ref -> dz */
                float lo = 0.0f, hi = 1.0f;
                h_deg = rh; alpha_deg = ra; theta_deg = rt;
                for (unsigned k = 0; k < 6U; ++k) {
                    const float mid = 0.5f * (lo + hi);
                    const float zm = z_ref + (dz - z_ref) * mid;
                    float th = 0.0f, ta = 0.0f, tt = 0.0f;
                    if (ainekio_v3_leg_ik_offset((ainekio_v3_leg_id_t)l,
                                                 dx, dy, zm,
                                                 &th, &ta, &tt)) {
                        lo = mid;
                        h_deg = th; alpha_deg = ta; theta_deg = tt;
                    } else {
                        hi = mid;
                    }
                }
            } else {
                /* Stage 2: radial bisection from neutral (0, 0, 0) -> (dx, dy, dz) */
                float lo = 0.0f, hi = 1.0f;
                h_deg = 0.0f; alpha_deg = 0.0f; theta_deg = 0.0f;
                for (unsigned k = 0; k < 7U; ++k) {
                    const float mid = 0.5f * (lo + hi);
                    float th = 0.0f, ta = 0.0f, tt = 0.0f;
                    if (ainekio_v3_leg_ik_offset((ainekio_v3_leg_id_t)l,
                                                 dx * mid, dy * mid, dz * mid,
                                                 &th, &ta, &tt)) {
                        lo = mid;
                        h_deg = th; alpha_deg = ta; theta_deg = tt;
                    } else {
                        hi = mid;
                    }
                }
            }
        }
        joint_targets_deg_out[3U * l + 0U] = ainekio_v3_clamp_joint_deg((uint8_t)(3U * l + 0U), h_deg);
        joint_targets_deg_out[3U * l + 1U] = ainekio_v3_clamp_joint_deg((uint8_t)(3U * l + 1U), alpha_deg);
        joint_targets_deg_out[3U * l + 2U] = ainekio_v3_clamp_joint_deg((uint8_t)(3U * l + 2U), theta_deg);
    }
    return true;
}

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
    float joint_targets_deg_out[AINEKIO_V3_JOINT_COUNT])
{
    if (!state || !model || !joint_targets_deg_out) return false;
    const double prev_t = state->initialized ? state->last_time_s : timestamp_s;
    if (!ainekio_v3_microduck_features(joint_pos_deg, joint_vel_deg_s, orientation_wxyz,
                                       gyro_rad_s, accel_m_s2, command_twist,
                                       state->previous_action, timestamp_s, state->scratch_features))
        return false;
    const double cmd_mag = hypot((double)command_twist[0], (double)command_twist[1])
                         + 0.18 * fabs((double)command_twist[2]);
    if (!state->initialized || timestamp_s < prev_t) {
        state->phase_rad = 0.0;
    } else if (cmd_mag > 0.02) {
        double dt = timestamp_s - prev_t;
        if (dt > 0.1) dt = 0.1;
        state->phase_rad = fmod(state->phase_rad + 2.0 * 3.14159265358979323846 * v3_gait_hz(command_twist) * dt,
                                2.0 * 3.14159265358979323846);
    }
    if (cmd_mag > 0.02) {
        state->scratch_features[48] = (float)sin(state->phase_rad);
        state->scratch_features[49] = (float)cos(state->phase_rad);
    } else {
        state->scratch_features[48] = 0.0f;
        state->scratch_features[49] = 0.0f;
    }
    if (!ainekio_v3_microduck_observe(state, timestamp_s, state->scratch_features,
                                      state->scratch_observation))
        return false;
    if (!ainekio_v3_microduck_predict(model, state->scratch_observation,
                                      state->scratch_action, joint_targets_deg_out))
        return false;
    memcpy(state->previous_action, state->scratch_action, sizeof(state->previous_action));
    return true;
}
