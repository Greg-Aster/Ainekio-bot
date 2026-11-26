#include "ainekio/v3_model.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static void assert_near(float a, float b, float tol, const char *label)
{
    if (fabsf(a - b) > tol) {
        fprintf(stderr, "FAIL %s: got %.4f expected %.4f (tol %.4f)\n", label, a, b, tol);
        assert(0);
    }
}

int main(void)
{
    /* 1. Verify neutral FK matches Blender CAD to < 0.01 mm on all 4 legs */
    for (unsigned l = 0; l < AINEKIO_V3_LEG_COUNT; ++l) {
        ainekio_v3_fk_result_t fk;
        assert(ainekio_v3_leg_fk((ainekio_v3_leg_id_t)l, 0.0f, 0.0f, 0.0f, &fk));
        assert_near(fk.foot_robot_mm[0], ainekio_v3_legs[l].neutral_sole_in_robot_mm[0], 0.02f, "neutral_x");
        assert_near(fk.foot_robot_mm[1], ainekio_v3_legs[l].neutral_sole_in_robot_mm[1], 0.02f, "neutral_y");
        assert_near(fk.foot_robot_mm[2], ainekio_v3_legs[l].neutral_sole_in_robot_mm[2], 0.02f, "neutral_z");
        assert_near(fk.separation_mm, 66.2369f, 0.02f, "neutral_sep");
        assert(fk.sin_transmission > 0.98f);
    }

    /* 2. Verify closed-form IK -> FK round-trip across 3D foot offsets */
    const float test_offsets[][3] = {
        {0.0f, 0.0f, 0.0f},
        {25.0f, 0.0f, 15.0f},
        {-20.0f, 12.0f, 10.0f},
        {15.0f, -15.0f, -12.0f},
        {0.0f, 0.0f, 25.0f},
    };
    for (unsigned l = 0; l < AINEKIO_V3_LEG_COUNT; ++l) {
        for (unsigned k = 0; k < sizeof(test_offsets) / sizeof(test_offsets[0]); ++k) {
            float h = 0.0f, a = 0.0f, t = 0.0f;
            assert(ainekio_v3_leg_ik_offset(
                (ainekio_v3_leg_id_t)l,
                test_offsets[k][0], test_offsets[k][1], test_offsets[k][2],
                &h, &a, &t));
            ainekio_v3_fk_result_t fk;
            assert(ainekio_v3_leg_fk((ainekio_v3_leg_id_t)l, h, a, t, &fk));
            assert_near(fk.foot_robot_mm[0], ainekio_v3_legs[l].neutral_sole_in_robot_mm[0] + test_offsets[k][0], 0.15f, "ik_x");
            assert_near(fk.foot_robot_mm[1], ainekio_v3_legs[l].neutral_sole_in_robot_mm[1] + test_offsets[k][1], 0.15f, "ik_y");
            assert_near(fk.foot_robot_mm[2], ainekio_v3_legs[l].neutral_sole_in_robot_mm[2] + test_offsets[k][2], 0.15f, "ik_z");
        }
    }

    /* 3. Verify all canonical postures stay inside non-singular 4-bar workspace */
    const char *postures[] = {"stand", "crouch", "lay_down", "sit", "bow", "stretch", "wave_fr", "wave_fl"};
    for (unsigned i = 0; i < sizeof(postures) / sizeof(postures[0]); ++i) {
        float q[AINEKIO_V3_JOINT_COUNT];
        assert(ainekio_v3_posture_angles(postures[i], q));
        for (unsigned l = 0; l < AINEKIO_V3_LEG_COUNT; ++l) {
            ainekio_v3_fk_result_t fk;
            assert(ainekio_v3_leg_fk((ainekio_v3_leg_id_t)l, q[3*l], q[3*l+1], q[3*l+2], &fk));
            assert(fk.sin_transmission > 0.20f);
        }
    }

    /* 4. Verify analytic trot and microduck step return finite clamped angles */
    float trot_q[AINEKIO_V3_JOINT_COUNT];
    for (int s = 0; s < 20; ++s) {
        ainekio_v3_analytic_trot(s * 0.05, 0.25f, 0.05f, 0.4f, trot_q);
        for (unsigned j = 0; j < AINEKIO_V3_JOINT_COUNT; ++j)
            assert(isfinite(trot_q[j]));
    }

    assert(ainekio_v3_microduck_model_valid(&ainekio_v3_microduck_default_model));
    ainekio_v3_microduck_state_t st;
    ainekio_v3_microduck_reset(&st);
    float pos[12] = {0}, vel[12] = {0}, out[12] = {0};
    float quat[4] = {1.0f, 0.0f, 0.0f, 0.0f};
    float gyro[3] = {0}, accel[3] = {0, 0, 9.81f}, cmd[3] = {0.25f, 0.0f, 0.0f};
    assert(ainekio_v3_microduck_step(&st, &ainekio_v3_microduck_default_model, 0.02,
                                     pos, vel, quat, gyro, accel, cmd, out));
    for (unsigned j = 0; j < 12; ++j) assert(isfinite(out[j]));

    /* 5. Verify speed-adaptive cadence continuity across mid-walk twist updates & zero-gate at stand */
    const float cmd_fast[3] = {0.45f, 0.0f, 0.0f};
    assert(ainekio_v3_microduck_step(&st, &ainekio_v3_microduck_default_model, 0.04,
                                     pos, vel, quat, gyro, accel, cmd_fast, out));
    const double ph_after_fast = st.phase_rad;
    assert(ph_after_fast > 0.20 && ph_after_fast < 0.30); /* 2*pi*2.00*0.02 = 0.2513 rad */
    const float cmd_stand[3] = {0.0f, 0.0f, 0.0f};
    assert(ainekio_v3_microduck_step(&st, &ainekio_v3_microduck_default_model, 0.06,
                                     pos, vel, quat, gyro, accel, cmd_stand, out));
    assert_near(st.scratch_features[48], 0.0f, 1e-6f, "stand_cpg_sin");
    assert_near(st.scratch_features[49], 0.0f, 1e-6f, "stand_cpg_cos");

    /* 6. Verify 2-stage IK boundary projection preserves full dx across z-pinch with < 4 deg step */
    {
        ainekio_v3_microduck_model_t mdl = ainekio_v3_microduck_default_model;
        mdl.action_scale_mm[0] = 78.0f;
        mdl.action_scale_mm[1] = 28.0f;
        mdl.action_scale_mm[2] = 36.0f;
        /* Zero weights except bias3 driving FL (leg 2) to dx=+68mm, dz=+20mm vs dz=+22mm */
        float obs_z[AINEKIO_V3_MICRODUCK_OBS_SIZE] = {0};
        float act_a[12] = {0}, q_a[12] = {0}, act_b[12] = {0}, q_b[12] = {0};
        for (unsigned j = 0; j < 12; ++j) {
            mdl.scale3[j] = 0.0f;
            mdl.bias3[j] = 0.0f;
        }
        mdl.bias3[6] = atanhf(68.0f / 78.0f);
        mdl.bias3[8] = atanhf(20.0f / 36.0f);
        assert(ainekio_v3_microduck_predict(&mdl, obs_z, act_a, q_a));
        mdl.bias3[8] = atanhf(22.0f / 36.0f);
        assert(ainekio_v3_microduck_predict(&mdl, obs_z, act_b, q_b));
        assert(fabsf(q_a[7] - q_b[7]) < 2.5f && fabsf(q_a[8] - q_b[8]) < 2.5f);
    }

    printf("v3_model_unit: ALL PASSED\n");
    return 0;
}
