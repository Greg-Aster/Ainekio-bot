#ifndef AINEKIO_SERVO_H
#define AINEKIO_SERVO_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/protocol.h"

#define AINEKIO_SERVO_TICK_MS 20U
#define AINEKIO_SERVO_MIN_PULSE_US 500U
#define AINEKIO_SERVO_MAX_PULSE_US 2500U

typedef struct {
    float minimum_degrees;
    float center_degrees;
    float maximum_degrees;
    bool invert;
} ainekio_servo_calibration_t;

typedef enum {
    AINEKIO_SERVO_OK = 0,
    AINEKIO_SERVO_INVALID_JOINT,
    AINEKIO_SERVO_INVALID_CALIBRATION,
    AINEKIO_SERVO_LIMIT,
} ainekio_servo_result_t;

typedef struct {
    ainekio_servo_calibration_t calibration;
    float current_degrees;
    float target_degrees;
    uint16_t remaining_ticks;
    bool attached;
} ainekio_servo_channel_t;

typedef struct {
    ainekio_servo_channel_t channels[AINEKIO_SERVO_COUNT];
} ainekio_servo_bank_t;

bool ainekio_servo_calibration_valid(const ainekio_servo_calibration_t *calibration);
ainekio_servo_result_t ainekio_servo_map_logical(
    const ainekio_servo_calibration_t *calibration,
    float logical_degrees,
    float *physical_degrees
);
uint16_t ainekio_servo_degrees_to_pulse(float physical_degrees);
void ainekio_servo_bank_init(ainekio_servo_bank_t *bank);
ainekio_servo_result_t ainekio_servo_set_calibration(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    const ainekio_servo_calibration_t *calibration
);
ainekio_servo_result_t ainekio_servo_move_logical(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    float logical_degrees,
    uint16_t duration_ms
);
ainekio_servo_result_t ainekio_servo_move_physical(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    float physical_degrees,
    uint16_t duration_ms
);
void ainekio_servo_tick(ainekio_servo_bank_t *bank);
void ainekio_servo_detach(ainekio_servo_bank_t *bank, uint8_t joint_id);
void ainekio_servo_detach_all(ainekio_servo_bank_t *bank);

#endif
