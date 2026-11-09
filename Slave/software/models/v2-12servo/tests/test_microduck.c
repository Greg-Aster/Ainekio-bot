#include "ainekio/v2_microduck.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool near(float a, float b, float tol)
{
    return fabsf(a - b) <= tol;
}

int main(void)
{
    ainekio_v2_frame_t measured = {0};
    for (unsigned j = 0; j < 12; ++j) {
        measured.position[j] = 1800.f * (float)(j + 1); /* 18 deg * (j+1) */
        measured.velocity[j] = -900.f * (float)(j + 1); /* -9 deg/s * (j+1) */
    }
    const float q_upright[4] = {1.f, 0.f, 0.f, 0.f};
    const float gyro[3] = {0.1f, -0.2f, 0.3f};
    const float accel[3] = {0.f, 0.f, 9.81f};
    const float cmd[3] = {0.15f, -0.04f, 0.5f};
    float prev[12] = {0};
    for (unsigned j = 0; j < 12; ++j) prev[j] = 0.05f * (float)j;

    float feat[AINEKIO_V2_MICRODUCK_FEATURES];
    assert(ainekio_v2_microduck_features(&measured, q_upright, gyro, accel, cmd, prev, feat));
    const float pi = 3.14159265358979323846f;
    for (unsigned j = 0; j < 12; ++j) {
        assert(near(feat[j], 0.1f * pi * (float)(j + 1), 1e-6f));
        assert(near(feat[12 + j], -0.05f * pi * (float)(j + 1), 1e-6f));
        assert(near(feat[36 + j], prev[j], 1e-6f));
    }
    assert(near(feat[24], 0.1f, 1e-6f) && near(feat[25], -0.2f, 1e-6f) && near(feat[26], 0.3f, 1e-6f));
    assert(near(feat[27], 0.f, 1e-6f) && near(feat[28], 0.f, 1e-6f) && near(feat[29], 1.f, 1e-6f));
    /* Upright quaternion [1,0,0,0]: gravity=[0,0,1], -gravity=[0,0,-1]. */
    assert(near(feat[30], 0.f, 1e-6f) && near(feat[31], 0.f, 1e-6f) && near(feat[32], -1.f, 1e-6f));
    assert(near(feat[33], 0.15f, 1e-6f) && near(feat[34], -0.04f, 1e-6f) && near(feat[35], 0.5f, 1e-6f));

    /* Reject out-of-range previous actions or nonfinite inputs. */
    prev[0] = 1.1f;
    assert(!ainekio_v2_microduck_features(&measured, q_upright, gyro, accel, cmd, prev, feat));
    prev[0] = 0.f;

    /* Verify causal 15-frame history projection at 20 ms intervals. */
    ainekio_v2_microduck_state_t state;
    ainekio_v2_microduck_reset(&state);
    float obs[AINEKIO_V2_MICRODUCK_OBS_SIZE];
    for (unsigned step = 0; step < 20; ++step) {
        for (unsigned i = 0; i < AINEKIO_V2_MICRODUCK_FEATURES; ++i)
            feat[i] = (float)(step + 1) * 100.f + (float)i;
        assert(ainekio_v2_microduck_observe(&state, (double)step * 0.02, feat, obs));
        for (unsigned k = 0; k < AINEKIO_V2_MICRODUCK_SAMPLES; ++k) {
            const float *row = &obs[k * AINEKIO_V2_MICRODUCK_FEATURES];
            if (k <= step) {
                const float expected_base = (float)(step - k + 1) * 100.f;
                assert(near(row[0], expected_base, 1e-5f));
                assert(near(row[47], expected_base + 47.f, 1e-5f));
            } else {
                assert(near(row[0], 0.f, 1e-6f) && near(row[47], 0.f, 1e-6f));
            }
        }
    }

    /* Verify int8 quantized MLP forward pass, ELU nonlinearity, Tanh output and foot scaling. */
    ainekio_v2_microduck_model_t *model = calloc(1, sizeof(*model));
    assert(model);
    model->h0 = 128;
    model->h1 = 64;
    model->h2 = 32;
    for (unsigned i = 0; i < AINEKIO_V2_MICRODUCK_OBS_SIZE; ++i) {
        model->obs_mean[i] = 0.f;
        model->obs_std[i] = 1.f;
    }
    model->action_scale_mm[0] = 25.f;
    model->action_scale_mm[1] = 15.f;
    model->action_scale_mm[2] = 20.f;
    for (unsigned j = 0; j < model->h0; ++j) model->scale0[j] = 1.f;
    for (unsigned j = 0; j < model->h1; ++j) model->scale1[j] = 1.f;
    for (unsigned j = 0; j < model->h2; ++j) model->scale2[j] = 1.f;
    for (unsigned j = 0; j < AINEKIO_V2_MICRODUCK_ACTIONS; ++j) model->scale3[j] = 1.f;

    float row0[AINEKIO_V2_MICRODUCK_OBS_SIZE] = {0};
    row0[33] = 1.f; /* command vx_m_s -> h0[0] */
    assert(ainekio_v2_microduck_quantize_row(row0, AINEKIO_V2_MICRODUCK_OBS_SIZE, model->weight0_q[0], &model->scale0[0]));
    model->bias0[1] = -1.f; /* negative bias tests ELU(x) = expm1(x) */

    float row1[AINEKIO_V2_MICRODUCK_H0] = {0};
    row1[0] = 2.f;
    row1[1] = 1.f;
    assert(ainekio_v2_microduck_quantize_row(row1, model->h0, model->weight1_q[0], &model->scale1[0]));

    float row2[AINEKIO_V2_MICRODUCK_H1] = {0};
    row2[0] = 0.5f;
    assert(ainekio_v2_microduck_quantize_row(row2, model->h1, model->weight2_q[0], &model->scale2[0]));

    for (unsigned j = 0; j < AINEKIO_V2_MICRODUCK_ACTIONS; ++j) {
        float row3[AINEKIO_V2_MICRODUCK_H2] = {0};
        row3[0] = (j % 2 == 0) ? 1.f : -1.f;
        assert(ainekio_v2_microduck_quantize_row(row3, model->h2, model->weight3_q[j], &model->scale3[j]));
    }
    assert(ainekio_v2_microduck_model_valid(model));

    ainekio_v2_microduck_reset(&state);
    memset(&measured, 0, sizeof(measured));
    float feet_mm[4][3] = {{0}};
    assert(ainekio_v2_microduck_step(&state, model, 0.0, &measured, q_upright, gyro, accel, cmd, feet_mm));
    const float expected_h0_0 = cmd[0] * (float)model->weight0_q[0][33] * model->scale0[0];
    const float expected_h0_1 = expm1f(-1.f);
    const float sum_h1_0 = ((float)model->weight1_q[0][0] * expected_h0_0 + (float)model->weight1_q[0][1] * expected_h0_1) * model->scale1[0];
    const float expected_h1_0 = sum_h1_0 >= 0.f ? sum_h1_0 : expm1f(sum_h1_0);
    const float sum_h2_0 = (float)model->weight2_q[0][0] * expected_h1_0 * model->scale2[0];
    const float expected_h2_0 = sum_h2_0 >= 0.f ? sum_h2_0 : expm1f(sum_h2_0);
    const float expected_act0 = tanhf(expected_h2_0);
    assert(near(state.previous_action[0], expected_act0, 1e-4f));
    assert(near(state.previous_action[1], -expected_act0, 1e-4f));
    assert(near(feet_mm[0][0], expected_act0 * 25.f, 1e-3f));
    assert(near(feet_mm[0][1], -expected_act0 * 15.f, 1e-3f));
    assert(near(feet_mm[0][2], expected_act0 * 20.f, 1e-3f));

    /* Verify embedded default trained MicroDuck policy on standing/walking inputs. */
    assert(ainekio_v2_microduck_model_valid(&ainekio_v2_microduck_default_model));
    ainekio_v2_microduck_reset(&state);
    for (unsigned step = 0; step < 25; ++step) {
        assert(ainekio_v2_microduck_step(&state, &ainekio_v2_microduck_default_model,
            (double)step * 0.02, &measured, q_upright, gyro, accel, cmd, feet_mm));
        for (unsigned leg = 0; leg < 4; ++leg) {
            for (unsigned axis = 0; axis < 3; ++axis) {
                assert(isfinite(feet_mm[leg][axis]) &&
                       fabsf(feet_mm[leg][axis]) <= ainekio_v2_microduck_default_model.action_scale_mm[axis] + 1e-3f);
            }
        }
    }

    free(model);
    puts("MicroDuck v7 proprioceptive feature assembly, causal 15-frame ring buffer, int8 MLP inference, and embedded default policy passed.");
    return 0;
}
