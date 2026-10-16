#include "imu_telemetry.h"
#include <inttypes.h>
#include <stdio.h>
size_t ainekio_imu_telemetry(const ainekio_imu_observation_t *s, bool calibrated,
    uint32_t boot_id, char *text, size_t capacity)
{
    int n = snprintf(text, capacity,
        "{\"t\":\"event\",\"name\":\"imu\",\"data\":{\"boot_id\":%" PRIu32
        ",\"timestamp_us\":%" PRIu64 ",\"age_us\":%" PRIu64
        ",\"available\":%s,\"fresh\":%s,\"startup\":%s,\"calibration_applied\":%s,"
        "\"gyro_recovery\":%s,\"acceleration_recovery\":%s,\"accelerometer_ignored\":%s,"
        "\"frame\":\"%s\",\"orientation_wxyz\":[%.9g,%.9g,%.9g,%.9g],"
        "\"acceleration_m_s2\":[%.9g,%.9g,%.9g],\"angular_rate_rad_s\":[%.9g,%.9g,%.9g]}}",
        boot_id, s->timestamp_us, s->age_us, s->available?"true":"false", s->fresh?"true":"false",
        s->startup?"true":"false", calibrated?"true":"false", s->gyro_recovery?"true":"false",
        s->acceleration_recovery?"true":"false", s->accelerometer_ignored?"true":"false",
        calibrated?"body_nominal":"sensor_unverified",
        (double)s->orientation_wxyz[0], (double)s->orientation_wxyz[1],
        (double)s->orientation_wxyz[2], (double)s->orientation_wxyz[3],
        (double)s->acceleration_m_s2[0], (double)s->acceleration_m_s2[1], (double)s->acceleration_m_s2[2],
        (double)s->angular_rate_rad_s[0], (double)s->angular_rate_rad_s[1], (double)s->angular_rate_rad_s[2]);
    return n > 0 && (size_t)n < capacity ? (size_t)n : 0;
}
