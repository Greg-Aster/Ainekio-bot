#include "joint_calibration.h"
#include "ainekio/v2_limits.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static ainekio_v2_frame_t home_frame(void)
{
    ainekio_v2_frame_t frame = {0};
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) frame.position[i] = (float[]){0,117,-4041}[i%3];
    return frame;
}

static void assert_off(const uint16_t *pulses)
{
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) assert(pulses[i] == 0);
}

static void test_defaults_home_and_full_nominal_span(void)
{
    ainekio_v2_frame_t frame = home_frame();
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    uint16_t pulses[AINEKIO_BODY_JOINT_COUNT];
    assert(ainekio_p4_joint_defaults(joints));
    assert(ainekio_p4_joints_valid(joints));
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    for (size_t i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        assert(joints[i].home_cd == (int32_t)frame.position[i]);
        assert(pulses[i] == 1300);
    }
    frame.position[8] += 14400;
    frame.position[11] -= 9000;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[8] == 2900 && pulses[11] == 300);
    frame.position[11] -= 100;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[11] == 289); /* No servo travel cap. */
}

static void test_mapping_direction_channels_and_disabled_joint(void)
{
    ainekio_v2_frame_t frame = home_frame();
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    uint16_t pulses[AINEKIO_BODY_JOINT_COUNT];
    assert(ainekio_p4_joint_defaults(joints));
    joints[0].channel = 11;
    joints[11].channel = 0;
    joints[0].home_us = 1495;
    joints[0].home_cd = -1000;
    joints[0].us_per_degree = 10;
    frame.position[0] = 2900;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[11] == 1885 && pulses[0] == 1300);
    joints[0].invert = 1;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[11] == 1105);
    joints[11].channel = -1;
    frame.position[11] = NAN;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[0] == 0 && pulses[11] == 1105);
    frame.position[8] = INFINITY;
    assert(!ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert_off(pulses);
}

static void test_original_library_leg_extremes(void)
{
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    uint16_t pulses[AINEKIO_BODY_JOINT_COUNT];
    assert(ainekio_p4_joint_defaults(joints));
    /* Independent recorded extrema from Pushup/Point/Bow, not a combined pose.
     * Mapping must retain the original reach after the horns are re-indexed. */
    const float minimum_cd[3] = {0, -7902.3025f, -12811.3331f};
    const float maximum_cd[3] = {0, 13537.1044f, 10129.4998f};
    for (unsigned end = 0; end < 2; ++end) {
        ainekio_v2_frame_t frame = home_frame();
        for (unsigned leg = 0; leg < 4; ++leg)
            for (unsigned j = 1; j < 3; ++j)
                frame.position[leg*3+j] = end ? maximum_cd[j] : minimum_cd[j];
        assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
        for (unsigned leg = 0; leg < 4; ++leg) {
            assert(pulses[leg*3+1] == (end ? 2791 : 409));
            assert(pulses[leg*3+2] == (end ? 2874 : 326));
        }
    }
}

static void test_invalid_mapping_cannot_produce_partial_output(void)
{
    ainekio_v2_frame_t rest = home_frame();
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    uint16_t pulses[AINEKIO_BODY_JOINT_COUNT];
    const float bad[] = {0, -1, 100.1f, INFINITY, NAN};
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); ++i) {
        assert(ainekio_p4_joint_defaults(joints));
        joints[11].us_per_degree = bad[i];
        memset(pulses, 0xaa, sizeof(pulses));
        assert(!ainekio_p4_joint_map_frame(joints, &rest, pulses));
        assert_off(pulses);
    }
    assert(ainekio_p4_joint_defaults(joints));
    joints[8].home_cd = 36001;
    assert(!ainekio_p4_joints_valid(joints));
    joints[8].home_cd = -36001;
    assert(!ainekio_p4_joints_valid(joints));
    assert(!ainekio_p4_joint_map_frame(NULL, &rest, pulses));
    assert_off(pulses);
    assert(!ainekio_p4_joint_map_frame(joints, NULL, pulses));
    assert_off(pulses);
}

static void test_pulse_conversion(void)
{
    ainekio_v2_frame_t frame = home_frame();
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    uint16_t pulses[AINEKIO_BODY_JOINT_COUNT];
    assert(ainekio_p4_joint_defaults(joints));
    joints[0].us_per_degree = 10;
    joints[0].home_us = 1600;
    frame.position[0] += 15000;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses) && pulses[0] == 3100);
    frame.position[0] = -13000;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses) && pulses[0] == 300);
    frame.position[0] = 13000;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses) && pulses[0] == 2900);
    joints[0].invert = 1;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses) && pulses[0] == 300);
    frame.position[0] = 16000; /* Zero is output-off, not an enabled servo pulse. */
    assert(!ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert_off(pulses);
    frame.position[0] = -700000;
    assert(!ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert_off(pulses);
    joints[0].home_us = 0;
    assert(!ainekio_p4_joints_valid(joints));
}

static void test_commanded_reference_round_trip(void)
{
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    ainekio_v2_frame_t frame = home_frame(), restored;
    uint16_t pulses[AINEKIO_BODY_JOINT_COUNT];
    assert(ainekio_p4_joint_defaults(joints));
    frame.position[0] = 3000;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(ainekio_p4_joint_unmap_frame(joints, pulses, &restored));
    assert(fabs(restored.position[0] - frame.position[0]) < 5);
    pulses[0] = 0;
    assert(!ainekio_p4_joint_unmap_frame(joints, pulses, &restored));
}

static void test_manual_pulse_reference_is_literal(void)
{
    ainekio_p4_joint_config_t joints[12];assert(ainekio_p4_joint_defaults(joints));
    ainekio_v2_frame_t commanded=home_frame(),reference;uint16_t pulses[12];
    commanded.position[0]=-5500;
    assert(ainekio_p4_joint_map_frame(joints,&commanded,pulses));
    assert(ainekio_p4_joint_unmap_frame(joints,pulses,&reference));
    /* Manual PWM is interpreted literally; no polygon search invents a pose.
     * Automatic frames retain -5500 exactly in the body output owner. */
    assert(reference.position[0]!=commanded.position[0]);
    assert(fabs(reference.position[0]-100.*((double)pulses[0]-joints[0].home_us)/joints[0].us_per_degree)<.001);
}

int main(void)
{
    test_manual_pulse_reference_is_literal();
    test_defaults_home_and_full_nominal_span();
    test_original_library_leg_extremes();
    test_mapping_direction_channels_and_disabled_joint();
    test_invalid_mapping_cannot_produce_partial_output();
    test_pulse_conversion();
    test_commanded_reference_round_trip();
    puts("Joint mapping and calibration passed");
    return 0;
}
