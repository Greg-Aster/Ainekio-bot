#include "ainekio/v2_microduck.h"
#include <math.h>
#include <string.h>

static float elu(float x)
{
    return x >= 0.f ? x : expm1f(x);
}

void ainekio_v2_microduck_reset(ainekio_v2_microduck_state_t *state)
{
    if (!state) return;
    memset(state, 0, sizeof(*state));
}

bool ainekio_v2_microduck_quantize_row(const float *weights, unsigned count,
    int8_t *quantized_out, float *scale_out)
{
    if (!weights || !count || !quantized_out || !scale_out) return false;
    float max_abs = 0.f;
    for (unsigned i = 0; i < count; ++i) {
        if (!isfinite(weights[i])) return false;
        const float a = fabsf(weights[i]);
        if (a > max_abs) max_abs = a;
    }
    if (max_abs == 0.f) {
        *scale_out = 1.f;
        memset(quantized_out, 0, count);
        return true;
    }
    const float scale = max_abs / 127.f;
    *scale_out = scale;
    for (unsigned i = 0; i < count; ++i) {
        int q = (int)lroundf(weights[i] / scale);
        if (q < -127) q = -127;
        else if (q > 127) q = 127;
        quantized_out[i] = (int8_t)q;
    }
    return true;
}

static bool resolve_dims(const ainekio_v2_microduck_model_t *model,
    unsigned *d0, unsigned *d1, unsigned *d2)
{
    if (!model) return false;
    *d0 = model->h0 ? model->h0 : AINEKIO_V2_MICRODUCK_H0;
    *d1 = model->h1 ? model->h1 : AINEKIO_V2_MICRODUCK_H1;
    *d2 = model->h2 ? model->h2 : AINEKIO_V2_MICRODUCK_H2;
    return *d0 >= 1 && *d0 <= AINEKIO_V2_MICRODUCK_H0 &&
           *d1 >= 1 && *d1 <= AINEKIO_V2_MICRODUCK_H1 &&
           *d2 >= 1 && *d2 <= AINEKIO_V2_MICRODUCK_H2;
}

bool ainekio_v2_microduck_model_valid(const ainekio_v2_microduck_model_t *model)
{
    unsigned d0, d1, d2;
    if (!resolve_dims(model, &d0, &d1, &d2)) return false;
    for (unsigned a = 0; a < 3; ++a)
        if (!isfinite(model->action_scale_mm[a]) || model->action_scale_mm[a] <= 0.f) return false;
    for (unsigned i = 0; i < AINEKIO_V2_MICRODUCK_OBS_SIZE; ++i)
        if (!isfinite(model->obs_mean[i]) || !isfinite(model->obs_std[i]) || model->obs_std[i] <= 0.f) return false;
    for (unsigned j = 0; j < d0; ++j)
        if (!isfinite(model->bias0[j]) || !isfinite(model->scale0[j]) || model->scale0[j] < 0.f) return false;
    for (unsigned j = 0; j < d1; ++j)
        if (!isfinite(model->bias1[j]) || !isfinite(model->scale1[j]) || model->scale1[j] < 0.f) return false;
    for (unsigned j = 0; j < d2; ++j)
        if (!isfinite(model->bias2[j]) || !isfinite(model->scale2[j]) || model->scale2[j] < 0.f) return false;
    for (unsigned j = 0; j < AINEKIO_V2_MICRODUCK_ACTIONS; ++j)
        if (!isfinite(model->bias3[j]) || !isfinite(model->scale3[j]) || model->scale3[j] < 0.f) return false;
    return true;
}

bool ainekio_v2_microduck_features(const ainekio_v2_frame_t *measured,
    const float orientation_wxyz[4], const float gyro_rad_s[3],
    const float accel_m_s2[3], const float command_twist[3],
    const float previous_action[AINEKIO_V2_MICRODUCK_ACTIONS],
    float features_out[AINEKIO_V2_MICRODUCK_FEATURES])
{
    if (!measured || !orientation_wxyz || !gyro_rad_s || !accel_m_s2 ||
        !command_twist || !previous_action || !features_out) return false;
    const double cd_to_rad = 3.14159265358979323846 / 18000.0;
    for (unsigned j = 0; j < 12; ++j) {
        if (!isfinite(measured->position[j]) || !isfinite(measured->velocity[j]) ||
            !isfinite(previous_action[j]) || fabsf(previous_action[j]) > 1.000001f) return false;
        features_out[j] = (float)((double)measured->position[j] * cd_to_rad);
        features_out[12 + j] = (float)((double)measured->velocity[j] * cd_to_rad);
        features_out[36 + j] = previous_action[j];
    }
    for (unsigned i = 0; i < 4; ++i)
        if (!isfinite(orientation_wxyz[i])) return false;
    for (unsigned a = 0; a < 3; ++a) {
        if (!isfinite(gyro_rad_s[a]) || !isfinite(accel_m_s2[a]) || !isfinite(command_twist[a])) return false;
        features_out[24 + a] = gyro_rad_s[a];
        features_out[27 + a] = (float)((double)accel_m_s2[a] / 9.81);
        features_out[33 + a] = command_twist[a];
    }
    const double w = orientation_wxyz[0], x = orientation_wxyz[1];
    const double y = orientation_wxyz[2], z = orientation_wxyz[3];
    features_out[30] = (float)(-2.0 * (x * z - w * y));
    features_out[31] = (float)(-2.0 * (y * z + w * x));
    features_out[32] = (float)(1.0 - 2.0 * (w * w + z * z));
    return true;
}

bool ainekio_v2_microduck_observe(ainekio_v2_microduck_state_t *state,
    double timestamp_s, const float features[AINEKIO_V2_MICRODUCK_FEATURES],
    float observation_out[AINEKIO_V2_MICRODUCK_OBS_SIZE])
{
    if (!state || !features || !observation_out || !isfinite(timestamp_s) || timestamp_s < 0.0)
        return false;
    for (unsigned i = 0; i < AINEKIO_V2_MICRODUCK_FEATURES; ++i)
        if (!isfinite(features[i])) return false;
    if (!state->initialized || timestamp_s < state->last_time_s) {
        state->count = 0;
        state->initialized = true;
    }
    state->last_time_s = timestamp_s;
    if (state->count > 0 && state->sample_time_s[state->count - 1] == timestamp_s) {
        memcpy(state->samples[state->count - 1], features, sizeof(float) * AINEKIO_V2_MICRODUCK_FEATURES);
    } else {
        if (state->count == AINEKIO_V2_MICRODUCK_RING_CAPACITY) {
            memmove(&state->sample_time_s[0], &state->sample_time_s[1],
                sizeof(double) * (AINEKIO_V2_MICRODUCK_RING_CAPACITY - 1));
            memmove(&state->samples[0], &state->samples[1],
                sizeof(state->samples[0]) * (AINEKIO_V2_MICRODUCK_RING_CAPACITY - 1));
            --state->count;
        }
        state->sample_time_s[state->count] = timestamp_s;
        memcpy(state->samples[state->count], features, sizeof(float) * AINEKIO_V2_MICRODUCK_FEATURES);
        ++state->count;
    }
    while (state->count > 1 &&
           state->sample_time_s[1] < timestamp_s - (double)AINEKIO_V2_MICRODUCK_SAMPLES * 0.02) {
        memmove(&state->sample_time_s[0], &state->sample_time_s[1],
            sizeof(double) * (state->count - 1));
        memmove(&state->samples[0], &state->samples[1],
            sizeof(state->samples[0]) * (state->count - 1));
        --state->count;
    }
    for (unsigned index = 0; index < AINEKIO_V2_MICRODUCK_SAMPLES; ++index) {
        const double target_s = timestamp_s - (double)index * 0.02 + 1e-9;
        float *dest = &observation_out[index * AINEKIO_V2_MICRODUCK_FEATURES];
        int matched = -1;
        for (int s = (int)state->count - 1; s >= 0; --s) {
            if (state->sample_time_s[s] <= target_s) {
                matched = s;
                break;
            }
        }
        if (matched >= 0)
            memcpy(dest, state->samples[matched], sizeof(float) * AINEKIO_V2_MICRODUCK_FEATURES);
        else
            memset(dest, 0, sizeof(float) * AINEKIO_V2_MICRODUCK_FEATURES);
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
    if (max_abs <= 1e-12f) {
        memset(dst, 0, sizeof(int16_t) * n);
        *scale_out = 0.f;
        return;
    }
    const float scale = max_abs / 20480.f;
    const float inv_scale = 20480.f / max_abs;
    for (unsigned i = 0; i < n; ++i) {
        const float q = src[i] * inv_scale;
        dst[i] = (int16_t)(q >= 0.f ? (int32_t)(q + 0.5f) : (int32_t)(q - 0.5f));
    }
    *scale_out = scale;
}

static inline int32_t dot_i8_i16(const int8_t * restrict w, const int16_t * restrict x, unsigned n)
{
    int32_t acc0 = 0, acc1 = 0, acc2 = 0, acc3 = 0;
    unsigned i = 0;
    for (; i + 8 <= n; i += 8) {
        acc0 += (int32_t)w[i + 0] * (int32_t)x[i + 0] + (int32_t)w[i + 1] * (int32_t)x[i + 1];
        acc1 += (int32_t)w[i + 2] * (int32_t)x[i + 2] + (int32_t)w[i + 3] * (int32_t)x[i + 3];
        acc2 += (int32_t)w[i + 4] * (int32_t)x[i + 4] + (int32_t)w[i + 5] * (int32_t)x[i + 5];
        acc3 += (int32_t)w[i + 6] * (int32_t)x[i + 6] + (int32_t)w[i + 7] * (int32_t)x[i + 7];
    }
    int32_t acc = (acc0 + acc1) + (acc2 + acc3);
    for (; i < n; ++i) acc += (int32_t)w[i] * (int32_t)x[i];
    return acc;
}

bool ainekio_v2_microduck_predict(const ainekio_v2_microduck_model_t *model,
    const float observation[AINEKIO_V2_MICRODUCK_OBS_SIZE],
    float action_out[AINEKIO_V2_MICRODUCK_ACTIONS],
    float feet_mm_out[4][3])
{
    unsigned d0, d1, d2;
    if (!resolve_dims(model, &d0, &d1, &d2) || !observation || !action_out || !feet_mm_out)
        return false;
    static float norm[AINEKIO_V2_MICRODUCK_OBS_SIZE];
    static float h0[AINEKIO_V2_MICRODUCK_H0];
    static float h1[AINEKIO_V2_MICRODUCK_H1];
    static float h2[AINEKIO_V2_MICRODUCK_H2];
    static int16_t q_in[AINEKIO_V2_MICRODUCK_OBS_SIZE];
    for (unsigned i = 0; i < AINEKIO_V2_MICRODUCK_OBS_SIZE; ++i) {
        if (!isfinite(observation[i]) || !isfinite(model->obs_mean[i]) ||
            !isfinite(model->obs_std[i]) || model->obs_std[i] <= 0.f) return false;
        norm[i] = (observation[i] - model->obs_mean[i]) / model->obs_std[i];
    }
    for (unsigned a = 0; a < 3; ++a)
        if (!isfinite(model->action_scale_mm[a]) || model->action_scale_mm[a] <= 0.f) return false;

    float in_scale = 0.f;
    quantize_activations(norm, AINEKIO_V2_MICRODUCK_OBS_SIZE, q_in, &in_scale);
    for (unsigned j = 0; j < d0; ++j) {
        if (!isfinite(model->bias0[j]) || !isfinite(model->scale0[j]) || model->scale0[j] < 0.f) return false;
        const int32_t acc = dot_i8_i16(model->weight0_q[j], q_in, AINEKIO_V2_MICRODUCK_OBS_SIZE);
        h0[j] = elu(model->bias0[j] + (float)acc * (model->scale0[j] * in_scale));
    }
    quantize_activations(h0, d0, q_in, &in_scale);
    for (unsigned j = 0; j < d1; ++j) {
        if (!isfinite(model->bias1[j]) || !isfinite(model->scale1[j]) || model->scale1[j] < 0.f) return false;
        const int32_t acc = dot_i8_i16(model->weight1_q[j], q_in, d0);
        h1[j] = elu(model->bias1[j] + (float)acc * (model->scale1[j] * in_scale));
    }
    quantize_activations(h1, d1, q_in, &in_scale);
    for (unsigned j = 0; j < d2; ++j) {
        if (!isfinite(model->bias2[j]) || !isfinite(model->scale2[j]) || model->scale2[j] < 0.f) return false;
        const int32_t acc = dot_i8_i16(model->weight2_q[j], q_in, d1);
        h2[j] = elu(model->bias2[j] + (float)acc * (model->scale2[j] * in_scale));
    }
    quantize_activations(h2, d2, q_in, &in_scale);
    for (unsigned j = 0; j < AINEKIO_V2_MICRODUCK_ACTIONS; ++j) {
        if (!isfinite(model->bias3[j]) || !isfinite(model->scale3[j]) || model->scale3[j] < 0.f) return false;
        const int32_t acc = dot_i8_i16(model->weight3_q[j], q_in, d2);
        const float sum = model->bias3[j] + (float)acc * (model->scale3[j] * in_scale);
        if (!isfinite(sum)) return false;
        const float act = fmaxf(-1.f, fminf(1.f, tanhf(sum)));
        action_out[j] = act;
        feet_mm_out[j / 3][j % 3] = act * model->action_scale_mm[j % 3];
    }
    return true;
}

bool ainekio_v2_microduck_step(ainekio_v2_microduck_state_t *state,
    const ainekio_v2_microduck_model_t *model, double timestamp_s,
    const ainekio_v2_frame_t *measured, const float orientation_wxyz[4],
    const float gyro_rad_s[3], const float accel_m_s2[3],
    const float command_twist[3], float feet_mm_out[4][3])
{
    if (!state || !model || !feet_mm_out) return false;
    if (!ainekio_v2_microduck_features(measured, orientation_wxyz, gyro_rad_s,
            accel_m_s2, command_twist, state->previous_action, state->scratch_features) ||
        !ainekio_v2_microduck_observe(state, timestamp_s, state->scratch_features,
            state->scratch_observation) ||
        !ainekio_v2_microduck_predict(model, state->scratch_observation,
            state->scratch_action, feet_mm_out))
        return false;
    memcpy(state->previous_action, state->scratch_action, sizeof(state->previous_action));
    return true;
}
