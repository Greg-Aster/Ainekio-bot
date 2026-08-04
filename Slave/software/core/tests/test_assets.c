#include "ainekio/assets.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef AINEKIO_TEST_ASSET_ROOT
#error "AINEKIO_TEST_ASSET_ROOT is required"
#endif

static uint8_t *read_asset(const char *name, size_t *length)
{
    char path[512];
    const int written = snprintf(
        path,
        sizeof(path),
        "%s/motions/%s.amot",
        AINEKIO_TEST_ASSET_ROOT,
        name
    );
    assert(written > 0 && (size_t)written < sizeof(path));
    FILE *file = fopen(path, "rb");
    assert(file != NULL);
    assert(fseek(file, 0L, SEEK_END) == 0);
    const long file_length = ftell(file);
    assert(file_length > 0L);
    rewind(file);
    uint8_t *bytes = malloc((size_t)file_length);
    assert(bytes != NULL);
    assert(fread(bytes, 1U, (size_t)file_length, file) == (size_t)file_length);
    assert(fclose(file) == 0);
    *length = (size_t)file_length;
    return bytes;
}

static void test_all_seed_assets_decode_and_fit_default_calibration(void)
{
    static const char *const names[] = {
        "rest", "stand", "wave", "dance", "swim", "point", "pushup",
        "bow", "cute", "freaky", "worm", "shake", "shrug", "dead",
        "crab", "walk_forward", "walk_backward", "turn_left", "turn_right",
        "sit", "nod", "celebrate", "stretch", "macarena", "salsa", "surprised",
        "sad", "curious", "turn_left_45", "turn_right_45", "turn_left_90",
        "turn_right_90", "turn_left_180", "turn_right_180", "walk_slow",
        "run",
    };
    ainekio_servo_bank_t servos;
    ainekio_servo_bank_init(&servos);
    for (size_t index = 0U; index < sizeof(names) / sizeof(names[0]); ++index) {
        size_t length = 0U;
        uint8_t *bytes = read_asset(names[index], &length);
        ainekio_motion_asset_t *asset = malloc(sizeof(*asset));
        assert(asset != NULL);
        assert(ainekio_motion_asset_decode(bytes, length, asset) == AINEKIO_ASSET_OK);
        assert(strcmp(asset->name, names[index]) == 0);
        assert(ainekio_motion_asset_check_limits(asset, &servos) == AINEKIO_ASSET_OK);
        free(asset);
        free(bytes);
    }
}

static void test_corruption_truncation_and_trailing_data_are_rejected(void)
{
    size_t length = 0U;
    uint8_t *bytes = read_asset("wave", &length);
    ainekio_motion_asset_t *asset = malloc(sizeof(*asset));
    assert(asset != NULL);
    assert(ainekio_motion_asset_decode(bytes, length - 1U, asset) == AINEKIO_ASSET_TRUNCATED);
    bytes[length - 1U] ^= 0x80U;
    assert(ainekio_motion_asset_decode(bytes, length, asset) == AINEKIO_ASSET_CHECKSUM);
    bytes[length - 1U] ^= 0x80U;
    uint8_t *extended = realloc(bytes, length + 1U);
    assert(extended != NULL);
    extended[length] = 0U;
    assert(ainekio_motion_asset_decode(extended, length + 1U, asset) == AINEKIO_ASSET_MALFORMED);
    free(asset);
    free(extended);
}

static void test_sesame_walk_is_one_bounded_gait_cycle(void)
{
    size_t length = 0U;
    uint8_t *bytes = read_asset("walk_forward", &length);
    ainekio_motion_asset_t *asset = malloc(sizeof(*asset));
    assert(asset != NULL);
    assert(ainekio_motion_asset_decode(bytes, length, asset) == AINEKIO_ASSET_OK);
    assert(asset->sequential_servo_timing);
    assert(asset->return_pose[0] == '\0');
    assert(asset->frame_count == 32U);

    uint32_t duration_ms = 0U;
    for (uint16_t index = 0U; index < asset->frame_count; ++index) {
        duration_ms += asset->frames[index].duration_ms;
    }
    assert(duration_ms == 4940U);
    free(asset);
    free(bytes);

    bytes = read_asset("walk_backward", &length);
    asset = malloc(sizeof(*asset));
    assert(asset != NULL);
    assert(ainekio_motion_asset_decode(bytes, length, asset) == AINEKIO_ASSET_OK);
    assert(asset->frame_count == 31U);
    duration_ms = 0U;
    for (uint16_t index = 0U; index < asset->frame_count; ++index) {
        duration_ms += asset->frames[index].duration_ms;
    }
    assert(duration_ms == 4760U);
    free(asset);
    free(bytes);
}

static void test_fallbacks_are_bounded(void)
{
    ainekio_motion_asset_t *asset = malloc(sizeof(*asset));
    assert(asset != NULL);
    ainekio_motion_asset_fallback(AINEKIO_FALLBACK_NEUTRAL, asset);
    assert(strcmp(asset->name, "neutral") == 0);
    assert(asset->frame_count == 1U);
    assert(asset->frames[0].target_count == AINEKIO_SERVO_COUNT);
    ainekio_motion_asset_fallback(AINEKIO_FALLBACK_STAND, asset);
    assert(strcmp(asset->name, "stand") == 0);
    assert(asset->frames[0].targets[0].centidegrees == 13500U);
    free(asset);
}

static void test_feedback_frames_are_small_and_pose_relative(void)
{
    static const uint16_t base[AINEKIO_SERVO_COUNT] = {
        13500U, 4500U, 4500U, 13500U, 0U, 18000U, 0U, 18000U,
    };
    ainekio_motion_frame_t frame;

    assert(ainekio_motion_feedback_frame(
        AINEKIO_MOTION_FEEDBACK_LISTEN,
        true,
        base,
        &frame
    ));
    assert(frame.duration_ms == 300U);
    assert(frame.target_count == AINEKIO_SERVO_COUNT);
    assert(frame.targets[AINEKIO_JOINT_R1].centidegrees == 13500U);
    assert(frame.targets[AINEKIO_JOINT_L1].centidegrees == 4500U);
    assert(frame.targets[AINEKIO_JOINT_R2].centidegrees == 5100U);
    assert(frame.targets[AINEKIO_JOINT_L2].centidegrees == 12900U);
    assert(frame.targets[AINEKIO_JOINT_R4].centidegrees == 600U);
    assert(frame.targets[AINEKIO_JOINT_L4].centidegrees == 17400U);

    assert(ainekio_motion_feedback_frame(
        AINEKIO_MOTION_FEEDBACK_TALK,
        true,
        base,
        &frame
    ));
    assert(frame.duration_ms == 420U);
    assert(frame.targets[AINEKIO_JOINT_R1].centidegrees == 13300U);
    assert(frame.targets[AINEKIO_JOINT_R2].centidegrees == 4700U);
    assert(frame.targets[AINEKIO_JOINT_R3].centidegrees == 17700U);
    assert(frame.targets[AINEKIO_JOINT_R4].centidegrees == 300U);
    assert(frame.targets[AINEKIO_JOINT_L3].centidegrees == 300U);
    assert(frame.targets[AINEKIO_JOINT_L4].centidegrees == 17700U);

    assert(ainekio_motion_feedback_frame(
        AINEKIO_MOTION_FEEDBACK_TALK,
        false,
        base,
        &frame
    ));
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        assert(frame.targets[index].joint_id == index);
        assert(frame.targets[index].centidegrees == base[index]);
    }

    static const uint16_t neutral[AINEKIO_SERVO_COUNT] = {
        9000U, 9000U, 9000U, 9000U, 9000U, 9000U, 9000U, 9000U,
    };
    assert(ainekio_motion_feedback_frame(
        AINEKIO_MOTION_FEEDBACK_LISTEN,
        true,
        neutral,
        &frame
    ));
    assert(frame.targets[AINEKIO_JOINT_R2].centidegrees == 9600U);
    assert(frame.targets[AINEKIO_JOINT_L2].centidegrees == 8400U);
    assert(frame.targets[AINEKIO_JOINT_R4].centidegrees == 9600U);
    assert(frame.targets[AINEKIO_JOINT_L4].centidegrees == 8400U);

    uint16_t invalid[AINEKIO_SERVO_COUNT];
    memcpy(invalid, base, sizeof(invalid));
    invalid[AINEKIO_JOINT_R1] = 18001U;
    assert(!ainekio_motion_feedback_frame(
        AINEKIO_MOTION_FEEDBACK_LISTEN,
        true,
        invalid,
        &frame
    ));
}

int main(void)
{
    test_all_seed_assets_decode_and_fit_default_calibration();
    test_corruption_truncation_and_trailing_data_are_rejected();
    test_sesame_walk_is_one_bounded_gait_cycle();
    test_fallbacks_are_bounded();
    test_feedback_frames_are_small_and_pose_relative();
    puts("asset tests passed");
    return 0;
}
