#pragma once
#include "ainekio/p4_imu.h"
#include "body.h"
#include <stddef.h>
size_t ainekio_imu_telemetry(const ainekio_p4_imu_status_t *sensor,
    uint32_t boot_id, const ainekio_p4_execution_t *motion, const char *face_token,
    char *text, size_t capacity);
