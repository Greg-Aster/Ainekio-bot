#include "imu_telemetry.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    const ainekio_imu_observation_t sample = {.timestamp_us=123456, .age_us=2000,
        .available=true, .fresh=true, .orientation_wxyz={1,0,0,0},
        .acceleration_m_s2={0,0,9.80665f}, .angular_rate_rad_s={1,2,3}};
    char text[1024];
    assert(ainekio_imu_telemetry(&sample,true,9,text,sizeof(text)));
    assert(strstr(text,"\"frame\":\"body_nominal\""));
    assert(strstr(text,"\"angular_rate_rad_s\":[1,2,3]"));
    assert(strstr(text,"\"timestamp_us\":123456"));
    puts(text);
    assert(ainekio_imu_telemetry(&sample,false,9,text,sizeof(text)));
    assert(strstr(text,"sensor_unverified"));
    assert(!ainekio_imu_telemetry(&sample,true,9,text,4));
    return 0;
}
