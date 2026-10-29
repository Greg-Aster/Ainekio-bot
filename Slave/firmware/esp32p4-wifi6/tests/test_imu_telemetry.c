#include "imu_telemetry.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cJSON.h"
#include <math.h>
int main(void) {
    const ainekio_imu_observation_t sample = {.timestamp_us=123456, .age_us=2000,
        .accepted_samples=1000, .rejected_samples=2, .gap_restarts=3,
        .available=true, .fresh=true, .orientation_wxyz={1,0,0,0},
        .acceleration_m_s2={0,0,9.80665f}, .angular_rate_rad_s={1,2,3}};
    ainekio_p4_imu_status_t sensor={.attitude=sample,.calibration_applied=true,
        .io_errors=2,.no_data_polls=4};
    char text[2048];
    assert(ainekio_imu_telemetry(&sensor,9,NULL,NULL,NULL,text,sizeof(text)));
    assert(strstr(text,"\"face_token\":\"\""));
    assert(strstr(text,"\"frame\":\"body_nominal\""));
    assert(strstr(text,"\"angular_rate_rad_s\":[1,2,3]"));
    assert(strstr(text,"\"timestamp_us\":123456"));
    assert(strstr(text,"\"accepted_samples\":1000,\"rejected_samples\":2,\"gap_restarts\":3"));
    assert(strstr(text,"\"io_errors\":2,\"no_data_polls\":4"));
    assert(!strstr(text,"gap_status_us"));
    puts(text);
    sensor.calibration_applied=false;
    assert(ainekio_imu_telemetry(&sensor,9,NULL,NULL,NULL,text,sizeof(text)));
    assert(strstr(text,"sensor_unverified"));
    assert(!ainekio_imu_telemetry(&sensor,9,NULL,NULL,NULL,text,4));
    sensor.attitude.timestamp_us=sensor.attitude.age_us=UINT64_MAX;
    sensor.attitude.accepted_samples=sensor.attitude.rejected_samples=sensor.attitude.gap_restarts=UINT64_MAX;
    sensor.io_errors=sensor.no_data_polls=UINT64_MAX;
    const ainekio_p4_execution_t motion={.command="crab_right",.activity="locomotion",
        .phase="entry",.sequence=UINT32_MAX,.connection=UINT64_MAX,.started_us=UINT64_MAX,.sampled_us=UINT64_MAX,
        .expected_up={0,.5f,.8660254f},.expected_up_known=true,
        .host_nominal=true,.nominal_sample=UINT32_MAX};
    char token[AINEKIO_ASSET_NAME_MAX+1U];
    memset(token,'a',sizeof token-1);token[sizeof token-1]='\0';
    memcpy(token,"be_",3);
    assert(ainekio_imu_telemetry(&sensor,UINT32_MAX,&motion,token,NULL,text,sizeof(text)));
    assert(strstr(text,"\"face_token\":\"be_"));
    assert(strstr(text,"\"io_errors\":18446744073709551615"));
    assert(strstr(text,"\"motion\":{\"command\":\"crab_right\""));
    assert(strstr(text,"\"sequence\":4294967295"));
    assert(strstr(text,"\"expected_up\":[0,0.5,"));
    puts(text);
    /* Combined event: per-joint timestamps, null missing feedback and a
     * commanded zero angle remain distinct. Exercise the actual JSON parser. */
    ainekio_p4_feedback_observation_t feedback={.device_us=UINT64_MAX,
        .scan=UINT32_MAX,.revision=UINT32_MAX,.scan_us=20000,.enabled=true,
        .usable_mask=4094,.commanded_mask=4095,.stalled_joints=4,
        .health={.calibrated=4095,.unavailable=1}};
    for(unsigned j=0;j<12;j++) {
        feedback.sampled_us[j]=INT64_MAX-100*j;
        feedback.measured.position[j]=(j%2?-1:1)*35999.9f;
        feedback.measured.velocity[j]=(j%2?-1:1)*54545.45f;
        feedback.commanded.position[j]=j?12345.6f:0;
    }
    char combined[5120];
    const size_t bytes=ainekio_imu_telemetry(&sensor,UINT32_MAX,&motion,token,&feedback,combined,sizeof combined);
    assert(bytes && bytes==strlen(combined));
    cJSON *message=cJSON_Parse(combined);assert(message);
    cJSON *data=cJSON_GetObjectItemCaseSensitive(message,"data");assert(data);
    cJSON *execution=cJSON_GetObjectItemCaseSensitive(data,"motion");assert(execution);
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(execution,"walk_source")->valuestring,"host"));
    assert(cJSON_GetObjectItemCaseSensitive(execution,"nominal_sample")->valuedouble==UINT32_MAX);
    cJSON *joints=cJSON_GetObjectItemCaseSensitive(data,"joint_feedback");assert(joints);
    cJSON *angles=cJSON_GetObjectItemCaseSensitive(joints,"filtered_model_deg");
    cJSON *commands=cJSON_GetObjectItemCaseSensitive(joints,"commanded_model_deg");
    assert(cJSON_GetArraySize(angles)==12 && cJSON_GetArraySize(commands)==12);
    assert(cJSON_IsNull(cJSON_GetArrayItem(angles,0)));
    assert(cJSON_GetArrayItem(commands,0)->valuedouble==0);
    assert(fabs(cJSON_GetArrayItem(angles,1)->valuedouble+359.999)<.001);
    assert(cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(joints,"sampled_us"))==12);
    cJSON_Delete(message);
    assert(!ainekio_imu_telemetry(&sensor,UINT32_MAX,&motion,token,&feedback,combined,bytes));
    assert(ainekio_imu_telemetry(&sensor,UINT32_MAX,&motion,token,&feedback,combined,bytes+1)==bytes);
    printf("Combined IMU/joint worst-width fixture: %zu bytes, %zu bytes/s at 50Hz; snapshot workspace %zu bytes\n",
        bytes,bytes*50,sizeof(ainekio_p4_feedback_snapshot_t)+sizeof feedback);
    return 0;
}
