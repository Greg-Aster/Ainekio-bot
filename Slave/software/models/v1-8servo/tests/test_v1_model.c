#include "ainekio/v1_model.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static void test_fk_standing_matches_cad(void)
{
    for (unsigned l = 0; l < AINEKIO_V1_LEG_COUNT; ++l) {
        float foot[3] = {0};
        ainekio_v1_leg_fk((ainekio_v1_leg_t)l, 0.0f, 0.0f, foot);
        const ainekio_v1_leg_geom_t *g = &ainekio_v1_legs[l];
        for (int a = 0; a < 3; ++a) {
            const float err = fabsf(foot[a] - g->foot_stand_body_mm[a]);
            assert(err < 0.02f);
        }
    }
    /* Verify +hip swings foot forward (+X) vs -hip, and +knee lifts foot upward (+Z) on ALL 4 legs! */
    for (unsigned l = 0; l < AINEKIO_V1_LEG_COUNT; ++l) {
        float f0[3], fh_fwd[3], fh_back[3], fk[3];
        ainekio_v1_leg_fk((ainekio_v1_leg_t)l, 0.0f, 0.0f, f0);
        ainekio_v1_leg_fk((ainekio_v1_leg_t)l, 15.0f, 0.0f, fh_fwd);
        ainekio_v1_leg_fk((ainekio_v1_leg_t)l, -15.0f, 0.0f, fh_back);
        ainekio_v1_leg_fk((ainekio_v1_leg_t)l, 0.0f, 45.0f, fk);
        assert(fh_fwd[0] > fh_back[0] + 2.0f);
        assert(fk[2] > f0[2] + 10.0f);
    }
}

static void test_ik_roundtrip(void)
{
    const float test_offsets[][3] = {
        { 0.0f, 0.0f, 0.0f },
        { 12.0f, 0.0f, 15.0f },
        { -10.0f, 0.0f, 25.0f },
        { 0.0f, 0.0f, 40.0f },
    };
    for (unsigned l = 0; l < AINEKIO_V1_LEG_COUNT; ++l) {
        for (size_t k = 0; k < sizeof(test_offsets) / sizeof(test_offsets[0]); ++k) {
            float h = 0.0f, kn = 0.0f;
            ainekio_v1_leg_ik_offset((ainekio_v1_leg_t)l, test_offsets[k], &h, &kn);
            float foot[3] = {0};
            ainekio_v1_leg_fk((ainekio_v1_leg_t)l, h, kn, foot);
            const float target_z = ainekio_v1_legs[l].foot_stand_body_mm[2] + test_offsets[k][2];
            assert(fabsf(foot[2] - target_z) < 0.05f);
        }
    }
}

static void test_postures_and_walk(void)
{
    const char *names[] = { "stand", "crouch", "lay_down", "sit", "bow", "stretch", "wave" };
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        float q[AINEKIO_V1_JOINT_COUNT];
        assert(ainekio_v1_posture_angles(names[i], q));
        for (uint8_t j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
            assert(q[j] >= ainekio_v1_joints[j].min_deg && q[j] <= ainekio_v1_joints[j].max_deg);
        }
    }
    for (int step = 0; step < 50; ++step) {
        float q[AINEKIO_V1_JOINT_COUNT];
        ainekio_v1_walk_sample((double)step / 50.0, 1.0f, 0.0f, 0.0f, 1.0f, q);
        for (uint8_t j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
            assert(isfinite(q[j]));
            assert(q[j] >= ainekio_v1_joints[j].min_deg && q[j] <= ainekio_v1_joints[j].max_deg);
        }
    }
}

static void test_microduck_step(void)
{
    assert(ainekio_v1_microduck_model_valid(&ainekio_v1_microduck_default_model));
    ainekio_v1_microduck_state_t st;
    ainekio_v1_microduck_reset(&st);
    const float pos[AINEKIO_V1_JOINT_COUNT] = {0};
    const float vel[AINEKIO_V1_JOINT_COUNT] = {0};
    const float quat[4] = { 1.0f, 0.0f, 0.0f, 0.0f };
    const float gyro[3] = { 0.0f, 0.0f, 0.0f };
    const float accel[3] = { 0.0f, 0.0f, 9.81f };
    const float cmd[3] = { 0.08f, 0.0f, 0.0f };
    float targets[AINEKIO_V1_JOINT_COUNT];
    for (int t = 0; t < 20; ++t) {
        assert(ainekio_v1_microduck_step(&st, &ainekio_v1_microduck_default_model,
                                         0.02 * (double)t, pos, vel, quat, gyro, accel, cmd, targets));
        for (uint8_t j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
            assert(isfinite(targets[j]));
    }
}

int main(void)
{
    test_fk_standing_matches_cad();
    test_ik_roundtrip();
    test_postures_and_walk();
    test_microduck_step();
    printf("v1_model_unit: ALL PASSED\n");
    return 0;
}
