#ifndef AINEKIO_PLATFORM_SLEEP_SERVICE_H
#define AINEKIO_PLATFORM_SLEEP_SERVICE_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

bool ainekio_sleep_battery_recheck_pending(void);
esp_err_t ainekio_sleep_battery_recovered(
    float divider_factor,
    float calibration_factor,
    float *volts,
    bool *recovered
);
void ainekio_sleep_clear_battery_recheck(void);
void ainekio_sleep_enter(uint32_t seconds, bool battery_cutoff)
    __attribute__((noreturn));

#endif
