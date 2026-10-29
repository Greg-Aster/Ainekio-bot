#include "imu_telemetry.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdarg.h>
/* Append to the existing message workspace, without a second large JSON
 * buffer or heap allocations. A truncated message is never returned. */
static bool append(char *text,size_t capacity,size_t *used,const char *format,...)
{
    if(*used>=capacity)return false;
    va_list args;va_start(args,format);
    int n=vsnprintf(text+*used,capacity-*used,format,args);va_end(args);
    if(n<0 || (size_t)n>=capacity-*used)return false;
    *used+=(size_t)n;return true;
}
size_t ainekio_imu_telemetry(const ainekio_p4_imu_status_t *sensor,
    uint32_t boot_id, const ainekio_p4_execution_t *motion, const char *face_token,
    const ainekio_p4_feedback_observation_t *feedback,char *text,size_t capacity)
{
    const ainekio_imu_observation_t *s=&sensor->attitude;
    const bool calibrated=sensor->calibration_applied;
    char execution[480]="";
    if(motion) {
        char up[96]="null";
        if(motion->expected_up_known)
            snprintf(up,sizeof up,"[%.9g,%.9g,%.9g]",(double)motion->expected_up[0],
                (double)motion->expected_up[1],(double)motion->expected_up[2]);
        snprintf(execution,sizeof execution,
            ",\"motion\":{\"command\":\"%s\",\"activity\":\"%s\",\"phase\":\"%s\","
            "\"sequence\":%" PRIu32 ",\"connection\":%" PRIu64 ",\"started_us\":%" PRIu64 ",\"sampled_us\":%" PRIu64
            ",\"expected_up\":%s,\"walk_source\":\"%s\",\"nominal_sample\":%" PRIu32 "}",motion->command?motion->command:"",
            motion->activity?motion->activity:"idle",motion->phase?motion->phase:"off",
            motion->sequence,motion->connection,motion->started_us,motion->sampled_us,up,
            motion->host_nominal?"host":"native",motion->nominal_sample);
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
    if(n<=0 || (size_t)n>=capacity)return 0;
    if(!feedback)return (size_t)n;
    size_t used=(size_t)n-2; /* Extend data, retaining the existing event. */
    const ainekio_p4_feedback_health_t *h=&feedback->health;
    if(!append(text,capacity,&used,",\"joint_feedback\":{\"map\":2,\"device_us\":%" PRIu64
        ",\"scan\":%" PRIu32 ",\"scan_us\":%" PRIu32 ",\"revision\":%" PRIu32
        ",\"enabled\":%s,\"usable_mask\":%u,\"commanded_mask\":%u,\"stalled_joints\":%u,"
        "\"calibrated_mask\":%u,\"unavailable_mask\":%u,\"clipped_mask\":%u,"
        "\"below_calibration_mask\":%u,\"above_calibration_mask\":%u,\"sampled_us\":[",
        feedback->device_us,feedback->scan,feedback->scan_us,feedback->revision,
        feedback->enabled?"true":"false",feedback->usable_mask,feedback->commanded_mask,
        feedback->stalled_joints,h->calibrated,h->unavailable,h->clipped,
        h->below_calibration,h->above_calibration))return 0;
    for(unsigned j=0;j<12;j++)
        if(!append(text,capacity,&used,"%s%" PRId64,j?",":"",feedback->sampled_us[j]))return 0;
    const char *names[]={"filtered_model_deg","velocity_deg_s","commanded_model_deg"};
    const float *columns[]={feedback->measured.position,feedback->measured.velocity,
        feedback->commanded.position};
    for(unsigned c=0;c<3;c++) {
        if(!append(text,capacity,&used,"],\"%s\":[",names[c]))return 0;
        for(unsigned j=0;j<12;j++) {
            const bool present=(c==2?feedback->commanded_mask:feedback->usable_mask)&(1U<<j);
            if(!append(text,capacity,&used,"%s",j?",":""))return 0;
            if(present) {if(!append(text,capacity,&used,"%.6g",columns[c][j]/100.))return 0;}
            else if(!append(text,capacity,&used,"null"))return 0;
        }
    }
    return append(text,capacity,&used,"]}}}")?used:0;
}
