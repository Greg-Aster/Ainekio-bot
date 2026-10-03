#include "joint_calibration.h"
#include "ainekio/v2_limits.h"
#include "ainekio/v2_walk.h"

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
        assert(pulses[i] == ainekio_v2_pulse_reference(i));
    }
    frame.position[8] += 14400;
    frame.position[11] -= 3600;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[8] == 2323 && pulses[11] == 323);
    frame.position[11] -= 100;
    assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
    assert(pulses[11] == 312); /* Literal mapping; no servo travel cap. */
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
    assert(pulses[11] == 1885 && pulses[0] == 723);
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
    const float minimum_cd[3] = {0, -3999.f, -5327.f};
    const float maximum_cd[3] = {0, 18533.f, 13936.f};
    for (unsigned end = 0; end < 2; ++end) {
        ainekio_v2_frame_t frame = home_frame();
        for (unsigned leg = 0; leg < 4; ++leg)
            for (unsigned j = 1; j < 3; ++j)
                frame.position[leg*3+j] = end ? maximum_cd[j] : minimum_cd[j];
        assert(ainekio_p4_joint_map_frame(joints, &frame, pulses));
        for (unsigned leg = 0; leg < 4; ++leg) {
            assert(pulses[leg*3+1] == (end ? 2902 : 399));
            assert(pulses[leg*3+2] == (end ? 2720 : 580));
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

static void test_recommended_mounting_home_matches_inversion(void)
{
    ainekio_p4_joint_config_t direct[12], mirrored[12];
    assert(ainekio_p4_joint_defaults(direct));
    memcpy(mirrored, direct, sizeof(mirrored));
    assert(ainekio_v2_pulse_midpoint()==1650.);
    const uint16_t expected_direct[3] = {1650,856,723};
    const uint16_t expected_mirrored[3] = {1650,2444,2577};
    for (unsigned i=0; i<12; ++i) {
        assert(ainekio_p4_joint_recommended_home(i, false) == expected_direct[i%3]);
        mirrored[i].invert = 1;
        mirrored[i].home_us = ainekio_p4_joint_recommended_home(i, true);
        assert(mirrored[i].home_us == expected_mirrored[i%3]);
    }
    /* The same modeled poses must be complementary pulses for mirrored
     * servos. This tests the recommendation through the production mapper. */
    const float poses[][3] = {{0,117,-4041},{0,-3999,-5327},{0,18533,13936}};
    for (unsigned pose=0; pose<3; ++pose) {
        ainekio_v2_frame_t frame=home_frame();
        uint16_t a[12],b[12];
        for (unsigned i=0; i<12; ++i) frame.position[i]=poses[pose][i%3];
        assert(ainekio_p4_joint_map_frame(direct,&frame,a));
        assert(ainekio_p4_joint_map_frame(mirrored,&frame,b));
        for (unsigned i=0; i<12; ++i) assert(a[i]+b[i]==3300);
    }
}

static void test_walk_400us_endpoint(void)
{
    /* Owner's saved calibration, not the electrical defaults. Exercise the
     * production command -> planner -> mapper path, including speed updates. */
    const uint16_t home[12]={1600,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
    ainekio_p4_joint_config_t joints[12];
    assert(ainekio_p4_joint_defaults(joints));
    for(unsigned i=0;i<12;i++) {joints[i].home_us=home[i];joints[i].invert=(i/3)%2==0;}
    assert(ainekio_v2_joint_speed_set(1000.F));
    for(unsigned dir=0;dir<4;dir++)for(unsigned mode=0;mode<3;mode++) {
        ainekio_v2_walk_state_t state={0};
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;
        c.data.intent.data.walk.gait=AINEKIO_GAIT_WALK;
        c.data.intent.data.walk.controls=mode;
        c.data.intent.data.walk.speed_percent=100;
        c.data.intent.data.walk.stride_percent=100;
        c.data.intent.data.walk.motion_rate=3;
        assert(ainekio_v2_walk_accept(&state,&c,0));
        unsigned low=65535,high=0;
        for(uint64_t now=0;now<=40000000&&!state.complete;now+=10000) {
            assert(ainekio_v2_walk_tick(&state,now));
            uint16_t pulses[12];assert(ainekio_p4_joint_map_frame(joints,&state.pose.frame,pulses));
            for(unsigned i=0;i<12;i++) {
                if(pulses[i]<400||pulses[i]>2900)fprintf(stderr,"Walk envelope dir=%u mode=%u us=%llu joint=%u pulse=%u phase=%g\n",dir,mode,(unsigned long long)now,i,pulses[i],state.phase);
                assert(pulses[i]>=400&&pulses[i]<=2900);
                if(pulses[i]<low)low=pulses[i];
                if(pulses[i]>high)high=pulses[i];
            }
            if(now==6000000||now==10000000||now==14000000||now==18000000||now==22000000) {
                c.sequence++;c.data.intent.data.walk.update_sequence=1;
                c.data.intent.data.walk.controls=1;
                c.data.intent.data.walk.speed_percent=now==22000000?0:now==6000000?20:now==10000000?40:now==14000000?70:100;
                assert(ainekio_v2_walk_accept(&state,&c,now));
            }
        }
        assert(state.complete);
        if(dir==AINEKIO_WALK_FORWARD)assert(low<=420&&high>=2880);
    }
    /* Finish can begin anywhere in the cycle. Check its committed foot
     * landings as well as the steady stroke at all supported tick intervals. */
    const unsigned intervals[]={10000,20000,40000};
    for(unsigned interval=0;interval<3;interval++)for(unsigned stop=0;stop<32;stop++) {
        ainekio_v2_walk_state_t state={0};
        ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        c.data.intent.kind=AINEKIO_INTENT_WALK;
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
        assert(ainekio_v2_walk_accept(&state,&c,0));
        for(uint64_t now=intervals[interval];now<40000000&&!state.complete;now+=intervals[interval]) {
            assert(ainekio_v2_walk_tick(&state,now));
            uint16_t pulses[12];assert(ainekio_p4_joint_map_frame(joints,&state.pose.frame,pulses));
            for(unsigned i=0;i<12;i++)assert(pulses[i]>=400&&pulses[i]<=2900);
            if(!state.stopping&&state.phase>=7.+stop/32.) {
                c.sequence=2;c.data.intent.data.walk.update_sequence=1;
                c.data.intent.data.walk.speed_percent=0;
                assert(ainekio_v2_walk_accept(&state,&c,now));
            }
        }
        assert(state.complete);
    }
    assert(ainekio_v2_joint_speed_set((float)ainekio_v2_joint_speed_default()));
}

int main(void)
{
    test_walk_400us_endpoint();
    test_recommended_mounting_home_matches_inversion();
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
