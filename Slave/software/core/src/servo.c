#include "ainekio/servo.h"

#include <math.h>
#include <string.h>

static bool degrees_valid(float value)
{
    return isfinite(value) && value >= 0.0F && value <= 180.0F;
}

static uint16_t duration_ticks(uint16_t duration_ms)
{
    if (duration_ms == 0U) {
        return 1U;
    }
    return (uint16_t)((duration_ms + AINEKIO_SERVO_TICK_MS - 1U) /
                      AINEKIO_SERVO_TICK_MS);
}

bool ainekio_servo_calibration_valid(const ainekio_servo_calibration_t *calibration)
{
    return calibration != NULL && degrees_valid(calibration->minimum_degrees) &&
           degrees_valid(calibration->center_degrees) &&
           degrees_valid(calibration->maximum_degrees) &&
           calibration->minimum_degrees <= calibration->center_degrees &&
           calibration->center_degrees <= calibration->maximum_degrees &&
           calibration->minimum_degrees < calibration->maximum_degrees;
}

ainekio_servo_result_t ainekio_servo_map_logical(
    const ainekio_servo_calibration_t *calibration,
    float logical_degrees,
    float *physical_degrees
)
{
    if (!ainekio_servo_calibration_valid(calibration) || physical_degrees == NULL) {
        return AINEKIO_SERVO_INVALID_CALIBRATION;
    }
    if (!degrees_valid(logical_degrees)) {
        return AINEKIO_SERVO_LIMIT;
    }
    const float direction = calibration->invert ? -1.0F : 1.0F;
    const float mapped = calibration->center_degrees +
                         direction * (logical_degrees - 90.0F);
    if (!isfinite(mapped) || mapped < calibration->minimum_degrees ||
        mapped > calibration->maximum_degrees) {
        return AINEKIO_SERVO_LIMIT;
    }
    *physical_degrees = mapped;
    return AINEKIO_SERVO_OK;
}

uint16_t ainekio_servo_degrees_to_pulse(float physical_degrees)
{
    if (!isfinite(physical_degrees) || physical_degrees <= 0.0F) {
        return AINEKIO_SERVO_MIN_PULSE_US;
    }
    if (physical_degrees >= 180.0F) {
        return AINEKIO_SERVO_MAX_PULSE_US;
    }
    const float span = (float)(AINEKIO_SERVO_MAX_PULSE_US -
                               AINEKIO_SERVO_MIN_PULSE_US);
    return (uint16_t)((float)AINEKIO_SERVO_MIN_PULSE_US +
                      (physical_degrees / 180.0F) * span + 0.5F);
}

void ainekio_servo_bank_init(ainekio_servo_bank_t *bank)
{
    memset(bank, 0, sizeof(*bank));
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        bank->channels[joint_id].calibration = (ainekio_servo_calibration_t){
            .minimum_degrees = 0.0F,
            .center_degrees = 90.0F,
            .maximum_degrees = 180.0F,
            .invert = false,
        };
        bank->channels[joint_id].current_degrees = 90.0F;
        bank->channels[joint_id].target_degrees = 90.0F;
    }
}

ainekio_servo_result_t ainekio_servo_set_calibration(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    const ainekio_servo_calibration_t *calibration
)
{
    if (joint_id >= AINEKIO_SERVO_COUNT) {
        return AINEKIO_SERVO_INVALID_JOINT;
    }
    if (!ainekio_servo_calibration_valid(calibration)) {
        return AINEKIO_SERVO_INVALID_CALIBRATION;
    }
    bank->channels[joint_id].calibration = *calibration;
    bank->channels[joint_id].current_degrees = calibration->center_degrees;
    bank->channels[joint_id].target_degrees = calibration->center_degrees;
    bank->channels[joint_id].remaining_ticks = 0U;
    bank->channels[joint_id].attached = false;
    return AINEKIO_SERVO_OK;
}

static ainekio_servo_result_t move_physical(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    float physical_degrees,
    uint16_t duration_ms
)
{
    if (joint_id >= AINEKIO_SERVO_COUNT) {
        return AINEKIO_SERVO_INVALID_JOINT;
    }
    ainekio_servo_channel_t *channel = &bank->channels[joint_id];
    if (!degrees_valid(physical_degrees) ||
        physical_degrees < channel->calibration.minimum_degrees ||
        physical_degrees > channel->calibration.maximum_degrees) {
        return AINEKIO_SERVO_LIMIT;
    }
    channel->target_degrees = physical_degrees;
    channel->remaining_ticks = duration_ticks(duration_ms);
    channel->attached = true;
    return AINEKIO_SERVO_OK;
}

ainekio_servo_result_t ainekio_servo_move_logical(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    float logical_degrees,
    uint16_t duration_ms
)
{
    if (joint_id >= AINEKIO_SERVO_COUNT) {
        return AINEKIO_SERVO_INVALID_JOINT;
    }
    float physical_degrees = 0.0F;
    const ainekio_servo_result_t result = ainekio_servo_map_logical(
        &bank->channels[joint_id].calibration,
        logical_degrees,
        &physical_degrees
    );
    return result == AINEKIO_SERVO_OK
               ? move_physical(bank, joint_id, physical_degrees, duration_ms)
               : result;
}

ainekio_servo_result_t ainekio_servo_move_physical(
    ainekio_servo_bank_t *bank,
    uint8_t joint_id,
    float physical_degrees,
    uint16_t duration_ms
)
{
    return move_physical(bank, joint_id, physical_degrees, duration_ms);
}

void ainekio_servo_tick(ainekio_servo_bank_t *bank)
{
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        ainekio_servo_channel_t *channel = &bank->channels[joint_id];
        if (!channel->attached || channel->remaining_ticks == 0U) {
            continue;
        }
        if (channel->remaining_ticks == 1U) {
            channel->current_degrees = channel->target_degrees;
        } else {
            channel->current_degrees +=
                (channel->target_degrees - channel->current_degrees) /
                (float)channel->remaining_ticks;
        }
        --channel->remaining_ticks;
    }
}

void ainekio_servo_detach(ainekio_servo_bank_t *bank, uint8_t joint_id)
{
    if (joint_id >= AINEKIO_SERVO_COUNT) {
        return;
    }
    bank->channels[joint_id].attached = false;
    bank->channels[joint_id].remaining_ticks = 0U;
}

void ainekio_servo_detach_all(ainekio_servo_bank_t *bank)
{
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        ainekio_servo_detach(bank, joint_id);
    }
}
