#include "ainekio/assets.h"

#include <string.h>

#define MOTION_SCHEMA_VERSION 1U
#define MOTION_FLAG_RETURN_POSE 0x01U

typedef struct {
    const uint8_t *bytes;
    size_t length;
    size_t offset;
} asset_reader_t;

static uint16_t read_u16_at(const uint8_t *bytes)
{
    return (uint16_t)bytes[0] | (uint16_t)((uint16_t)bytes[1] << 8U);
}

static uint32_t read_u32_at(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8U) |
           ((uint32_t)bytes[2] << 16U) | ((uint32_t)bytes[3] << 24U);
}

static bool reader_take(asset_reader_t *reader, void *output, size_t count)
{
    if (count > reader->length - reader->offset) {
        return false;
    }
    if (output != NULL) {
        memcpy(output, reader->bytes + reader->offset, count);
    }
    reader->offset += count;
    return true;
}

static bool reader_u8(asset_reader_t *reader, uint8_t *value)
{
    return reader_take(reader, value, sizeof(*value));
}

static bool reader_u16(asset_reader_t *reader, uint16_t *value)
{
    uint8_t bytes[2];
    if (!reader_take(reader, bytes, sizeof(bytes))) {
        return false;
    }
    *value = read_u16_at(bytes);
    return true;
}

static uint32_t crc32(const uint8_t *bytes, size_t length)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    for (size_t index = 0U; index < length; ++index) {
        crc ^= bytes[index];
        for (uint8_t bit = 0U; bit < 8U; ++bit) {
            const uint32_t mask = (uint32_t)-(int32_t)(crc & 1U);
            crc = (crc >> 1U) ^ (UINT32_C(0xEDB88320) & mask);
        }
    }
    return ~crc;
}

bool ainekio_asset_name_valid(const char *name)
{
    if (name == NULL || name[0] == '\0') {
        return false;
    }
    size_t length = 0U;
    while (name[length] != '\0') {
        const char value = name[length];
        if (!((value >= 'a' && value <= 'z') || (value >= '0' && value <= '9') ||
              value == '_') ||
            ++length > AINEKIO_ASSET_NAME_MAX) {
            return false;
        }
    }
    return true;
}

static bool reader_name(asset_reader_t *reader, uint8_t length, char *name)
{
    if (length == 0U || length > AINEKIO_ASSET_NAME_MAX ||
        !reader_take(reader, name, length)) {
        return false;
    }
    name[length] = '\0';
    return ainekio_asset_name_valid(name);
}

ainekio_asset_result_t ainekio_motion_asset_decode(
    const uint8_t *bytes,
    size_t length,
    ainekio_motion_asset_t *asset
)
{
    if (bytes == NULL || asset == NULL || length < AINEKIO_MOTION_BINARY_HEADER_BYTES) {
        return AINEKIO_ASSET_TRUNCATED;
    }
    if (memcmp(bytes, "AMOT", 4U) != 0 || bytes[4] != MOTION_SCHEMA_VERSION ||
        bytes[5] != AINEKIO_JOINT_MAP_VERSION) {
        return AINEKIO_ASSET_VERSION;
    }
    const uint8_t repeat_count = bytes[6];
    const uint8_t flags = bytes[7];
    const uint16_t frame_count = read_u16_at(bytes + 8U);
    const uint16_t cue_count = read_u16_at(bytes + 10U);
    const uint8_t name_length = bytes[12];
    const uint8_t return_length = bytes[13];
    const uint16_t reserved = read_u16_at(bytes + 14U);
    const uint32_t payload_length = read_u32_at(bytes + 16U);
    const uint32_t expected_crc = read_u32_at(bytes + 20U);
    if (payload_length != length - AINEKIO_MOTION_BINARY_HEADER_BYTES) {
        return payload_length > length - AINEKIO_MOTION_BINARY_HEADER_BYTES
                   ? AINEKIO_ASSET_TRUNCATED
                   : AINEKIO_ASSET_MALFORMED;
    }
    if (crc32(bytes + AINEKIO_MOTION_BINARY_HEADER_BYTES, payload_length) !=
        expected_crc) {
        return AINEKIO_ASSET_CHECKSUM;
    }
    if ((flags & (uint8_t)~MOTION_FLAG_RETURN_POSE) != 0U || reserved != 0U ||
        repeat_count < 1U || repeat_count > 16U || frame_count < 1U ||
        frame_count > AINEKIO_MOTION_MAX_FRAMES ||
        (uint32_t)frame_count * repeat_count > AINEKIO_MOTION_MAX_EXPANDED_FRAMES ||
        cue_count > AINEKIO_MOTION_MAX_FACE_CUES ||
        ((flags & MOTION_FLAG_RETURN_POSE) == 0U) != (return_length == 0U)) {
        return AINEKIO_ASSET_MALFORMED;
    }

    memset(asset, 0, sizeof(*asset));
    asset->frame_count = frame_count;
    asset->repeat_count = repeat_count;
    asset->face_cue_count = (uint8_t)cue_count;
    asset_reader_t reader = {
        .bytes = bytes + AINEKIO_MOTION_BINARY_HEADER_BYTES,
        .length = payload_length,
    };
    if (!reader_name(&reader, name_length, asset->name)) {
        return AINEKIO_ASSET_MALFORMED;
    }
    if (return_length > 0U &&
        !reader_name(&reader, return_length, asset->return_pose)) {
        return AINEKIO_ASSET_MALFORMED;
    }
    for (uint16_t index = 0U; index < cue_count; ++index) {
        ainekio_motion_face_cue_t *cue = &asset->face_cues[index];
        uint8_t mode = 0U;
        uint8_t cue_name_length = 0U;
        if (!reader_u16(&reader, &cue->frame_index) ||
            !reader_u8(&reader, &mode) ||
            !reader_u8(&reader, &cue_name_length) ||
            cue->frame_index >= frame_count || mode > AINEKIO_FACE_MODE_BOOMERANG ||
            !reader_name(&reader, cue_name_length, cue->name)) {
            return AINEKIO_ASSET_MALFORMED;
        }
        cue->mode = (ainekio_face_mode_t)mode;
    }
    for (uint16_t frame_index = 0U; frame_index < frame_count; ++frame_index) {
        ainekio_motion_frame_t *frame = &asset->frames[frame_index];
        if (!reader_u16(&reader, &frame->duration_ms) ||
            !reader_u8(&reader, &frame->target_count) ||
            frame->duration_ms < 20U || frame->duration_ms > 5000U ||
            frame->target_count < 1U || frame->target_count > AINEKIO_SERVO_COUNT) {
            return AINEKIO_ASSET_MALFORMED;
        }
        uint8_t seen = 0U;
        for (uint8_t target_index = 0U; target_index < frame->target_count;
             ++target_index) {
            ainekio_motion_target_t *target = &frame->targets[target_index];
            if (!reader_u8(&reader, &target->joint_id) ||
                !reader_u16(&reader, &target->centidegrees) ||
                target->joint_id >= AINEKIO_SERVO_COUNT ||
                target->centidegrees > 18000U ||
                (seen & (uint8_t)(1U << target->joint_id)) != 0U) {
                return AINEKIO_ASSET_MALFORMED;
            }
            seen |= (uint8_t)(1U << target->joint_id);
        }
    }
    return reader.offset == reader.length ? AINEKIO_ASSET_OK : AINEKIO_ASSET_MALFORMED;
}

ainekio_asset_result_t ainekio_motion_asset_check_limits(
    const ainekio_motion_asset_t *asset,
    const ainekio_servo_bank_t *servos
)
{
    if (asset == NULL || servos == NULL || !ainekio_asset_name_valid(asset->name)) {
        return AINEKIO_ASSET_MALFORMED;
    }
    for (uint16_t frame_index = 0U; frame_index < asset->frame_count; ++frame_index) {
        const ainekio_motion_frame_t *frame = &asset->frames[frame_index];
        for (uint8_t index = 0U; index < frame->target_count; ++index) {
            const ainekio_motion_target_t *target = &frame->targets[index];
            float physical = 0.0F;
            if (target->joint_id >= AINEKIO_SERVO_COUNT ||
                ainekio_servo_map_logical(
                    &servos->channels[target->joint_id].calibration,
                    (float)target->centidegrees / 100.0F,
                    &physical
                ) != AINEKIO_SERVO_OK) {
                return AINEKIO_ASSET_LIMIT;
            }
        }
    }
    return AINEKIO_ASSET_OK;
}

void ainekio_motion_asset_fallback(
    ainekio_fallback_motion_t fallback,
    ainekio_motion_asset_t *asset
)
{
    static const uint16_t neutral[AINEKIO_SERVO_COUNT] = {
        9000U, 9000U, 9000U, 9000U, 9000U, 9000U, 9000U, 9000U,
    };
    static const uint16_t stand[AINEKIO_SERVO_COUNT] = {
        13500U, 4500U, 4500U, 13500U, 0U, 18000U, 0U, 18000U,
    };
    memset(asset, 0, sizeof(*asset));
    const bool is_stand = fallback == AINEKIO_FALLBACK_STAND;
    memcpy(asset->name, is_stand ? "stand" : "neutral", is_stand ? 6U : 8U);
    asset->frame_count = 1U;
    asset->repeat_count = 1U;
    asset->frames[0].duration_ms = 300U;
    asset->frames[0].target_count = AINEKIO_SERVO_COUNT;
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        asset->frames[0].targets[index].joint_id = index;
        asset->frames[0].targets[index].centidegrees = is_stand ? stand[index] : neutral[index];
    }
}
