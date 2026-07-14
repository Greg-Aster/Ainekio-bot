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

int main(void)
{
    test_all_seed_assets_decode_and_fit_default_calibration();
    test_corruption_truncation_and_trailing_data_are_rejected();
    test_fallbacks_are_bounded();
    puts("asset tests passed");
    return 0;
}
