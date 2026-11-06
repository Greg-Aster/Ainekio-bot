#include "joint_calibration.h"
#include "ainekio/v2_limits.h"
#include "ainekio/v2_walk.h"
#include "ainekio/v2_learning.h"

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

static void test_installed_walk_mapping(void)
{
    /* Photo-derived reindexed crank profile, not device calibration proof. Exercise the
     * production command -> planner -> mapper path, including speed updates. */
    const uint16_t home[12]={1600,2444,2800,1670,856,500,1670,2444,2800,1760,856,500};
    ainekio_p4_joint_config_t joints[12];
    assert(ainekio_p4_joint_defaults(joints));
    for(unsigned i=0;i<12;i++) {joints[i].home_us=home[i];joints[i].invert=i%3==0?(i==3||i==6):(i/3)%2==0;}
    for(unsigned i=2;i<12;i+=3)joints[i].home_cd=-11768;
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
        /* Every requested pose must fit the reindexed mapping, including
         * updates and Finish. Full-stroke endpoints have a separate test. */
        assert(low<high);
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
            for(unsigned i=0;i<12;i++){
                if(pulses[i]<400||pulses[i]>2900)fprintf(stderr,"Finish mapping interval=%u stop=%u time=%llu phase=%g joint=%u pulse=%u\n",intervals[interval],stop,(unsigned long long)now,state.phase,i,pulses[i]);
                assert(pulses[i]>=400&&pulses[i]<=2900);
            }
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


static void test_installed_mechanical_travel(void)
{
    const unsigned home[12]={1760,2750,2870,1650,415,440,1650,2740,2800,1700,560,500};
    const unsigned invert[12]={0,1,1,1,0,0,1,1,1,0,0,0};
    ainekio_p4_joint_config_t joints[12];assert(ainekio_p4_joint_defaults(joints));
    for(unsigned j=0;j<12;j++) {
        joints[j].home_us=home[j];joints[j].invert=invert[j];
        joints[j].home_cd=j%3==0?0:j%3==1?-3087:-11768;
    }
    /* Shoulder range is explicitly unknown and excluded, even at >2800 us.
     * Role follows the joint, not its assigned output socket. */
    joints[0].home_us=3100;joints[0].channel=1;joints[1].channel=0;
    ainekio_p4_joint_config_t original[12];memcpy(original,joints,sizeof joints);
    unsigned changed=0,unchanged=0;
    for(unsigned direction=0;direction<4;direction++)for(unsigned mode=0;mode<3;mode++) {
        ainekio_command_t cmd={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};
        cmd.data.intent.kind=AINEKIO_INTENT_WALK;
        cmd.data.intent.data.walk.direction=direction;cmd.data.intent.data.walk.gait=mode;
        cmd.data.intent.data.walk.controls=2;cmd.data.intent.data.walk.stride_percent=100;
        cmd.data.intent.data.walk.motion_rate=2;cmd.data.intent.data.walk.steps=4;
        ainekio_v2_walk_state_t walk={0};assert(ainekio_v2_walk_accept(&walk,&cmd,0));
        for(uint64_t now=20000;!walk.complete&&now<30000000;now+=20000) {
            assert(ainekio_v2_walk_tick(&walk,now));
            ainekio_v2_frame_t frame=walk.pose.frame;bool fits=ainekio_p4_joint_frame_in_travel(joints,&frame);
            assert(ainekio_p4_joint_fit_frame(joints,&frame));
            assert(ainekio_p4_joint_frame_in_travel(joints,&frame));
            if(!memcmp(&frame,&walk.pose.frame,sizeof frame))unchanged++;else changed++;
            if(fits)assert(!memcmp(&frame,&walk.pose.frame,sizeof frame));
            for(unsigned j=0;j<12;j+=3)assert(frame.position[j]==walk.pose.frame.position[j]);
            float point[4][3];assert(ainekio_v2_feet_forward(&frame,point)==15);
        }
        assert(walk.complete);
    }
    assert(changed&&unchanged);assert(!memcmp(original,joints,sizeof joints));
    /* Every authored clip sample still closes with the installed calibration. */
    for(size_t clip=0;clip<ainekio_v2_clip_count;clip++)for(uint64_t t=0;t<=ainekio_v2_clips[clip].duration_us;t+=20000) {
        ainekio_v2_frame_t frame;assert(ainekio_v2_clip_sample(clip,t,&frame));
        assert(ainekio_p4_joint_fit_frame(joints,&frame));assert(ainekio_p4_joint_frame_in_travel(joints,&frame));
    }
}

static bool recorded_frame_valid(const ainekio_v2_frame_t *frame,void *context)
{ return ainekio_p4_joint_frame_in_travel(context,frame); }
static bool recorded_frame_project(ainekio_v2_frame_t *frame,void *context)
{ return ainekio_p4_joint_fit_frame(context,frame); }

static void test_recorded_host_target_preserves_linkage_through_full_rate_ramp(void)
{
    /* Physical Walk2908, 20261104-141328-b9541835: last written sample615
     * followed by accepted target616. The front-left intermediate joint chord
     * cannot close even though its endpoints and PWM mapping are valid. */
    const uint16_t home[12]={1760,2750,2870,1650,415,440,1650,2740,2750,1700,560,575};
    const uint8_t invert[12]={0,1,1,1,0,0,1,1,1,0,0,0};
    const uint16_t previous_us[12]={1887,2116,1587,1729,1449,1778,1734,1927,1799,1651,1059,1286};
    const float desired[4][3]={
        {-4.571684897F,14.378000498F,11.056041420F},
        {19.888297319F,18.247160912F,-16.286560893F},
        {26.945784688F,11.335481405F,-14.387429953F},
        {22.631487250F,-5.139428973F,1.989708468F}};
    ainekio_p4_joint_config_t mapping[12];ainekio_v2_frame_t initial,reference={0};
    for(unsigned j=0;j<12;j++) {
        mapping[j]=(ainekio_p4_joint_config_t){.channel=j,.invert=invert[j],.home_us=home[j],
            .home_cd=j%3==0?0:j%3==1?-3087:-11768,.us_per_degree=11.11111068725586F};
        reference.position[j]=(float[]){0,346,-2163}[j%3];
    }
    /* Physical imitation input row27, 20261105-075415-c2eafb4e, actor3000:
     * a 0.163-degree carrier boundary error used to halve the entire stride.
     * Nominal targets reuse calibrated Cartesian projection, while legacy
     * residual corrections retain their original scalar-fit contract. */
    const float boundary[4][3]={
        {-19.919277F,-1.966776F,4.405593F},
        {-45.183193F,-2.048863F,4.303583F},
        {-.117400F,-2.034141F,3.718738F},
        {-38.735844F,-1.963999F,6.155737F}};
    ainekio_v2_frame_t residual,unbounded;
    float residual_applied[4][3],residual_fit[4];
    assert(ainekio_v2_feet_offset(&reference,boundary,&unbounded));
    assert(!recorded_frame_valid(&unbounded,mapping));
    assert(ainekio_v2_learning_offsets_apply(boundary,&reference,recorded_frame_valid,
        mapping,&residual,residual_applied,residual_fit)==.5F);
    assert(residual_fit[1]==.5F);
    ainekio_v2_walk_pose_t projected;double projected_anchors[4][3];
    float projected_applied[4][3],projected_fit[4],origin[4][3],feet[4][3];
    assert(ainekio_v2_nominal_foot_pose(&reference,boundary,recorded_frame_valid,
        recorded_frame_project,mapping,&projected,projected_anchors,projected_applied,projected_fit));
    assert(recorded_frame_valid(&projected.frame,mapping));
    assert(ainekio_v2_feet_forward(&reference,origin)==15);
    assert(ainekio_v2_feet_forward(&projected.frame,feet)==15);
    for(unsigned leg=0;leg<4;leg++) {
        assert(projected_fit[leg]==1.F);
        double error=0.;
        for(unsigned axis=0;axis<3;axis++) {
            double actual=feet[leg][axis]-origin[leg][axis];
            assert(fabs(projected_applied[leg][axis]-actual)<.0001);
            error+=pow(actual-boundary[leg][axis],2);
            if(leg!=1)assert(fabs(actual-boundary[leg][axis])<.0001);
        }
        assert(sqrt(error)<.11); /* 0.098mm correction, not a 22.6mm lost stroke. */
    }
    assert(projected_applied[1][0]<-45.F);
    /* Small steps across that calibrated endpoint remain small in foot space. */
    float previous_foot[3]={0};
    for(unsigned step=0;step<=20;step++) {
        ainekio_v2_frame_t requested=projected.frame;
        requested.position[4]+=-40.F+4.F*step;
        float desired_nearby[4][3];assert(ainekio_v2_feet_forward(&requested,feet)==15);
        for(unsigned leg=0;leg<4;leg++)for(unsigned axis=0;axis<3;axis++)
            desired_nearby[leg][axis]=feet[leg][axis]-origin[leg][axis];
        ainekio_v2_walk_pose_t resolved;
        assert(ainekio_v2_nominal_foot_pose(&reference,(const float (*)[3])desired_nearby,
            recorded_frame_valid,recorded_frame_project,mapping,&resolved,projected_anchors,
            projected_applied,projected_fit));
        assert(recorded_frame_valid(&resolved.frame,mapping));
        for(unsigned axis=0;axis<3;axis++) {
            if(step)assert(fabs(projected_applied[1][axis]-previous_foot[axis])<.1);
            previous_foot[axis]=projected_applied[1][axis];
        }
    }
    assert(ainekio_p4_joint_unmap_frame(mapping,previous_us,&initial));
    ainekio_v2_walk_pose_t pose;double anchors[4][3];float applied[4][3],fit[4];
    assert(ainekio_v2_nominal_foot_pose(&reference,desired,recorded_frame_valid,recorded_frame_project,mapping,&pose,anchors,applied,fit));
    for(unsigned l=0;l<4;l++)assert(fit[l]==1.F);
    assert(ainekio_v2_limits_frame(&initial)&&ainekio_v2_limits_frame(&pose.frame));
    double remaining=0.;for(unsigned j=0;j<12;j++)remaining=fmax(remaining,fabs(pose.frame.position[j]-initial.position[j]));
    ainekio_v2_frame_t chord=initial;
    for(unsigned j=0;j<12;j++)chord.position[j]+=(float)(4000./remaining*(pose.frame.position[j]-initial.position[j]));
    assert(!ainekio_v2_limits_frame(&chord));
    uint16_t pulses[12];assert(ainekio_p4_joint_map_frame(mapping,&chord,pulses));
    for(unsigned j=0;j<12;j++)assert(pulses[j]>=500&&pulses[j]<=2800);
    const double speeds[]={60./.11,2000.},intervals[]={.01,.02,.025,.04};
    for(unsigned speed=0;speed<2;speed++)for(unsigned interval=0;interval<4;interval++) {
        ainekio_v2_frame_t from=initial;
        bool arrived=false;
        for(unsigned step=0;step<1000&&!arrived;step++) {
            ainekio_v2_frame_t next;
            assert(ainekio_p4_joint_ramp_frame(&from,pose.frame.position,speeds[speed]*100.,intervals[interval],&next));
            assert(ainekio_v2_limits_frame(&next));
            assert(ainekio_p4_joint_frame_in_travel(mapping,&next));
            double travelled=0.;arrived=true;
            for(unsigned j=0;j<12;j++) {
                travelled=fmax(travelled,fabs(next.position[j]-from.position[j]));
                if(next.position[j]!=pose.frame.position[j])arrived=false;
            }
            const double budget=speeds[speed]*100.*intervals[interval];
            assert(travelled<=budget+.01);
            if(!arrived)assert(fabs(travelled-budget)<.02); /* Uses the configured rate, no hidden multiplier. */
            from=next;
        }
        assert(arrived);
        /* A replacement target uses the current geometry immediately. */
        ainekio_v2_frame_t reversed;
        assert(ainekio_p4_joint_ramp_frame(&from,initial.position,speeds[speed]*100.,intervals[interval],&reversed));
        assert(ainekio_v2_limits_frame(&reversed));
        assert(ainekio_p4_joint_frame_in_travel(mapping,&reversed));
    }
}

int main(void)
{
    test_recorded_host_target_preserves_linkage_through_full_rate_ramp();
    test_installed_mechanical_travel();
    test_installed_walk_mapping();
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
