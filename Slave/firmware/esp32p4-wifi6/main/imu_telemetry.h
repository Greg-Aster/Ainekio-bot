#pragma once
#include "ainekio/imu.h"
#include <stddef.h>
size_t ainekio_imu_telemetry(const ainekio_imu_observation_t *s, bool calibrated,
    uint32_t boot_id, char *text, size_t capacity);
