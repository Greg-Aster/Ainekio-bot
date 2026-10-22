#include "imu_telemetry.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    const ainekio_imu_observation_t sample = {.timestamp_us=123456, .age_us=2000,
        .accepted_samples=1000, .rejected_samples=2, .gap_restarts=3,
        .available=true, .fresh=true, .orientation_wxyz={1,0,0,0},
        .acceleration_m_s2={0,0,9.80665f}, .angular_rate_rad_s={1,2,3}};
    ainekio_p4_imu_status_t sensor={.attitude=sample,.calibration_applied=true,
        .io_errors=2,.no_data_polls=4};
    char text[2048];
    assert(ainekio_imu_telemetry(&sensor,9,NULL,NULL,text,sizeof(text)));
    assert(strstr(text,"\"face_token\":\"\""));
    assert(strstr(text,"\"frame\":\"body_nominal\""));
    assert(strstr(text,"\"angular_rate_rad_s\":[1,2,3]"));
    assert(strstr(text,"\"timestamp_us\":123456"));
    assert(strstr(text,"\"accepted_samples\":1000,\"rejected_samples\":2,\"gap_restarts\":3"));
    assert(strstr(text,"\"io_errors\":2,\"no_data_polls\":4"));
    assert(!strstr(text,"gap_status_us"));
    puts(text);
    sensor.calibration_applied=false;
    assert(ainekio_imu_telemetry(&sensor,9,NULL,NULL,text,sizeof(text)));
    assert(strstr(text,"sensor_unverified"));
    assert(!ainekio_imu_telemetry(&sensor,9,NULL,NULL,text,4));
    sensor.attitude.timestamp_us=sensor.attitude.age_us=UINT64_MAX;
    sensor.attitude.accepted_samples=sensor.attitude.rejected_samples=sensor.attitude.gap_restarts=UINT64_MAX;
    sensor.io_errors=sensor.no_data_polls=UINT64_MAX;
    const ainekio_p4_execution_t motion={.command="crab_right",.activity="locomotion",
        .phase="entry",.sequence=UINT32_MAX,.connection=UINT64_MAX,.started_us=UINT64_MAX,.sampled_us=UINT64_MAX,
        .expected_up={0,.5f,.8660254f},.expected_up_known=true};
    char token[AINEKIO_ASSET_NAME_MAX+1U];
    memset(token,'a',sizeof token-1);token[sizeof token-1]='\0';
    memcpy(token,"be_",3);
    assert(ainekio_imu_telemetry(&sensor,UINT32_MAX,&motion,token,text,sizeof(text)));
    assert(strstr(text,"\"face_token\":\"be_"));
    assert(strstr(text,"\"io_errors\":18446744073709551615"));
    assert(strstr(text,"\"motion\":{\"command\":\"crab_right\""));
    assert(strstr(text,"\"sequence\":4294967295"));
    assert(strstr(text,"\"expected_up\":[0,0.5,"));
    puts(text);
    return 0;
}
