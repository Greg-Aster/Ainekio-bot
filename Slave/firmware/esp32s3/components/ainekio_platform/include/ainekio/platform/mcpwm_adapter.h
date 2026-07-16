#ifndef AINEKIO_PLATFORM_MCPWM_ADAPTER_H
#define AINEKIO_PLATFORM_MCPWM_ADAPTER_H

#include <stdbool.h>

#include "ainekio/servo.h"
#include "driver/mcpwm_prelude.h"
#include "esp_err.h"

typedef struct {
    mcpwm_timer_handle_t timers[2];
    mcpwm_oper_handle_t operators[4];
    mcpwm_cmpr_handle_t comparators[AINEKIO_SERVO_COUNT];
    mcpwm_gen_handle_t generators[AINEKIO_SERVO_COUNT];
    bool output_enabled[AINEKIO_SERVO_COUNT];
    bool initialized;
} ainekio_mcpwm_adapter_t;

esp_err_t ainekio_mcpwm_adapter_init(ainekio_mcpwm_adapter_t *adapter);
esp_err_t ainekio_mcpwm_adapter_enable_all(
    ainekio_mcpwm_adapter_t *adapter,
    ainekio_servo_bank_t *bank,
    uint16_t stagger_ms
);
esp_err_t ainekio_mcpwm_adapter_sync(
    ainekio_mcpwm_adapter_t *adapter,
    ainekio_servo_bank_t *bank
);
esp_err_t ainekio_mcpwm_adapter_detach(
    ainekio_mcpwm_adapter_t *adapter,
    uint8_t joint_id
);
esp_err_t ainekio_mcpwm_adapter_detach_all(ainekio_mcpwm_adapter_t *adapter);

#endif
