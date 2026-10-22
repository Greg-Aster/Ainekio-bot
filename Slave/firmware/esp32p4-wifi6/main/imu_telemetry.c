#include "imu_telemetry.h"
#include <inttypes.h>
#include <stdio.h>
size_t ainekio_imu_telemetry(const ainekio_p4_imu_status_t *sensor,
    uint32_t boot_id, const ainekio_p4_execution_t *motion, const char *face_token,
    char *text, size_t capacity)
{
    const ainekio_imu_observation_t *s=&sensor->attitude;
    const bool calibrated=sensor->calibration_applied;
    char execution[384]="";
    if(motion) {
        char up[96]="null";
        if(motion->expected_up_known)
            snprintf(up,sizeof up,"[%.9g,%.9g,%.9g]",(double)motion->expected_up[0],
                (double)motion->expected_up[1],(double)motion->expected_up[2]);
        snprintf(execution,sizeof execution,
            ",\"motion\":{\"command\":\"%s\",\"activity\":\"%s\",\"phase\":\"%s\","
            "\"sequence\":%" PRIu32 ",\"connection\":%" PRIu64 ",\"started_us\":%" PRIu64 ",\"sampled_us\":%" PRIu64
            ",\"expected_up\":%s}",motion->command?motion->command:"",
            motion->activity?motion->activity:"idle",motion->phase?motion->phase:"off",
            motion->sequence,motion->connection,motion->started_us,motion->sampled_us,up);
    }
    int n = snprintf(text, capacity,
        "{\"t\":\"event\",\"name\":\"imu\",\"data\":{\"boot_id\":%" PRIu32
        ",\"timestamp_us\":%" PRIu64 ",\"age_us\":%" PRIu64
        ",\"accepted_samples\":%" PRIu64 ",\"rejected_samples\":%" PRIu64 ",\"gap_restarts\":%" PRIu64
        ",\"available\":%s,\"fresh\":%s,\"startup\":%s,\"calibration_applied\":%s,"
        "\"gyro_recovery\":%s,\"acceleration_recovery\":%s,\"accelerometer_ignored\":%s,"
        "\"frame\":\"%s\",\"orientation_wxyz\":[%.9g,%.9g,%.9g,%.9g],"
        "\"acceleration_m_s2\":[%.9g,%.9g,%.9g],\"angular_rate_rad_s\":[%.9g,%.9g,%.9g],"
        "\"acquisition\":{\"io_errors\":%" PRIu64 ",\"no_data_polls\":%" PRIu64
        "}%s,\"face_token\":\"%s\"}}",
        boot_id, s->timestamp_us, s->age_us, s->accepted_samples, s->rejected_samples, s->gap_restarts,
        s->available?"true":"false", s->fresh?"true":"false",
        s->startup?"true":"false", calibrated?"true":"false", s->gyro_recovery?"true":"false",
        s->acceleration_recovery?"true":"false", s->accelerometer_ignored?"true":"false",
        calibrated?"body_nominal":"sensor_unverified",
        (double)s->orientation_wxyz[0], (double)s->orientation_wxyz[1],
        (double)s->orientation_wxyz[2], (double)s->orientation_wxyz[3],
        (double)s->acceleration_m_s2[0], (double)s->acceleration_m_s2[1], (double)s->acceleration_m_s2[2],
        (double)s->angular_rate_rad_s[0], (double)s->angular_rate_rad_s[1], (double)s->angular_rate_rad_s[2],
        sensor->io_errors,sensor->no_data_polls,execution,face_token?face_token:"");
    return n > 0 && (size_t)n < capacity ? (size_t)n : 0;
}
