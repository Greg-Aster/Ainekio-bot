#include "ainekio/settings.h"

#include <math.h>
#include <string.h>

#include "ainekio/assets.h"

void ainekio_pose_bank_init(ainekio_pose_bank_t *bank)
{
    memset(bank, 0, sizeof(*bank));
}

static bool pose_valid(const ainekio_named_pose_t *pose)
{
    if (!pose->used) {
        return pose->name[0] == '\0' && pose->count == 0U;
    }
    if (!ainekio_asset_name_valid(pose->name) || pose->count < 1U ||
        pose->count > AINEKIO_SERVO_COUNT) {
        return false;
    }
    uint8_t seen = 0U;
    for (uint8_t index = 0U; index < pose->count; ++index) {
        const ainekio_servo_target_t *target = &pose->targets[index];
        if (target->id >= AINEKIO_SERVO_COUNT || !isfinite(target->degrees) ||
            target->degrees < 0.0F || target->degrees > 180.0F ||
            (seen & (uint8_t)(1U << target->id)) != 0U) {
            return false;
        }
        seen |= (uint8_t)(1U << target->id);
    }
    return true;
}

bool ainekio_pose_bank_valid(const ainekio_pose_bank_t *bank)
{
    if (bank == NULL) {
        return false;
    }
    for (uint8_t index = 0U; index < AINEKIO_MAX_NAMED_POSES; ++index) {
        if (!pose_valid(&bank->poses[index])) {
            return false;
        }
        if (!bank->poses[index].used) {
            continue;
        }
        for (uint8_t other = (uint8_t)(index + 1U); other < AINEKIO_MAX_NAMED_POSES;
             ++other) {
            if (bank->poses[other].used &&
                strcmp(bank->poses[index].name, bank->poses[other].name) == 0) {
                return false;
            }
        }
    }
    return true;
}

bool ainekio_pose_bank_put(
    ainekio_pose_bank_t *bank,
    const char *name,
    const ainekio_servo_target_t *targets,
    uint8_t count
)
{
    if (bank == NULL || !ainekio_asset_name_valid(name) || targets == NULL ||
        count < 1U || count > AINEKIO_SERVO_COUNT) {
        return false;
    }
    int slot = -1;
    for (uint8_t index = 0U; index < AINEKIO_MAX_NAMED_POSES; ++index) {
        if (bank->poses[index].used && strcmp(bank->poses[index].name, name) == 0) {
            slot = index;
            break;
        }
        if (!bank->poses[index].used && slot < 0) {
            slot = index;
        }
    }
    if (slot < 0) {
        return false;
    }
    ainekio_named_pose_t candidate = {.used = true, .count = count};
    const size_t name_length = strlen(name);
    memcpy(candidate.name, name, name_length + 1U);
    memcpy(candidate.targets, targets, count * sizeof(targets[0]));
    if (!pose_valid(&candidate)) {
        return false;
    }
    bank->poses[slot] = candidate;
    return true;
}

const ainekio_named_pose_t *ainekio_pose_bank_find(
    const ainekio_pose_bank_t *bank,
    const char *name
)
{
    if (bank == NULL || name == NULL) {
        return NULL;
    }
    for (uint8_t index = 0U; index < AINEKIO_MAX_NAMED_POSES; ++index) {
        if (bank->poses[index].used && strcmp(bank->poses[index].name, name) == 0) {
            return &bank->poses[index];
        }
    }
    return NULL;
}

bool ainekio_servo_bank_calibration_valid(const ainekio_servo_bank_t *bank)
{
    if (bank == NULL) {
        return false;
    }
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        if (!ainekio_servo_calibration_valid(&bank->channels[index].calibration)) {
            return false;
        }
    }
    return true;
}
