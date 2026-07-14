#ifndef AINEKIO_SETTINGS_H
#define AINEKIO_SETTINGS_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/protocol.h"
#include "ainekio/servo.h"

#define AINEKIO_MAX_NAMED_POSES 16U

typedef struct {
    bool used;
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    uint8_t count;
    ainekio_servo_target_t targets[AINEKIO_SERVO_COUNT];
} ainekio_named_pose_t;

typedef struct {
    ainekio_named_pose_t poses[AINEKIO_MAX_NAMED_POSES];
} ainekio_pose_bank_t;

void ainekio_pose_bank_init(ainekio_pose_bank_t *bank);
bool ainekio_pose_bank_valid(const ainekio_pose_bank_t *bank);
bool ainekio_pose_bank_put(
    ainekio_pose_bank_t *bank,
    const char *name,
    const ainekio_servo_target_t *targets,
    uint8_t count
);
const ainekio_named_pose_t *ainekio_pose_bank_find(
    const ainekio_pose_bank_t *bank,
    const char *name
);
bool ainekio_servo_bank_calibration_valid(const ainekio_servo_bank_t *bank);

#endif
