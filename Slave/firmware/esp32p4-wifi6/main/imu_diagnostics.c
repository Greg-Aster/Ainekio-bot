#include "imu_diagnostics.h"
#include "ainekio/p4_imu.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static void print_status(ainekio_p4_imu_status_t s)
{
    printf("imu address=0x6a WHO_AM_I=0x%02x configured=%d running=%d last_error=%s\n",
           s.identity,s.configured,s.running,esp_err_to_name(s.last_error));
    printf("imu samples=%" PRIu64 " io_errors=%" PRIu64 " no_data_polls=%" PRIu64
           " age_us=%" PRIu64 " fresh=%d read_max_us=%" PRIu32 " interval_max_us=%" PRIu64 "\n",
           s.samples,s.io_errors,s.no_data_polls,s.attitude.age_us,s.attitude.fresh,
           s.read_max_us,s.interval_max_us);
    printf("imu estimator accepted=%" PRIu64 " rejected=%" PRIu64 " gaps=%" PRIu64
           " startup=%d; frame=%s bias=%s accel_calibration=none\n",
           s.attitude.accepted_samples,s.attitude.rejected_samples,s.attitude.gap_restarts,s.attitude.startup,
           s.calibration_applied ? "body_nominal" : "sensor_unverified",
           s.calibration_applied ? "applied" : "uncalibrated");
    printf("imu active_sensor_bias_rad_s=%.8f,%.8f,%.8f\n",
           (double)s.calibration.gyro_bias_rad_s[0],(double)s.calibration.gyro_bias_rad_s[1],
           (double)s.calibration.gyro_bias_rad_s[2]);
    printf("imu %s_to_world_wxyz=%.6f,%.6f,%.6f,%.6f; heading arbitrary\n",
           s.calibration_applied ? "body" : "sensor",
           (double)s.attitude.orientation_wxyz[0],(double)s.attitude.orientation_wxyz[1],
           (double)s.attitude.orientation_wxyz[2],(double)s.attitude.orientation_wxyz[3]);
}

static int calibration_command(int argc,char **argv)
{
    ainekio_p4_imu_calibration_t calibration;
    if (argc==2) {
        bool found=false;
        const esp_err_t result=ainekio_p4_imu_calibration_load(&calibration,&found);
        printf("imu calibration stored=%d read=%s; active_applied=%d\n",
               found,esp_err_to_name(result),ainekio_p4_imu_status().calibration_applied);
        if (result!=ESP_OK) return 1;
        printf("imu stored_sensor_to_body=");
        for (unsigned i=0;i<9;++i) printf("%s%.6f",i ? "," : "",(double)calibration.sensor_to_body[i]);
        printf("\nimu stored_sensor_bias_rad_s=%.8f,%.8f,%.8f\n",
               (double)calibration.gyro_bias_rad_s[0],(double)calibration.gyro_bias_rad_s[1],
               (double)calibration.gyro_bias_rad_s[2]);
        return 0;
    }
    if (argc!=15 || strcmp(argv[2],"set")) {
        puts("imu calibration [set r00 r01 r02 r10 r11 r12 r20 r21 r22 bx by bz]");
        puts("Rotation is sensor-to-body; bias is sensor XYZ rad/s. Applies at next boot.");
        return 1;
    }
    for (unsigned i=0;i<12;++i) {
        char *end;
        const float value=strtof(argv[3+i],&end);
        if (end==argv[3+i] || *end) { puts("Invalid calibration number");return 1; }
        if (i<9) calibration.sensor_to_body[i]=value;
        else calibration.gyro_bias_rad_s[i-9]=value;
    }
    const esp_err_t result=ainekio_p4_imu_calibration_save(&calibration);
    printf("imu calibration save=%s; %s\n",esp_err_to_name(result),
           result==ESP_OK ? "applies at next boot; current acquisition unchanged" : "current acquisition unchanged");
    return result!=ESP_OK;
}

int ainekio_p4_imu_command(int argc,char **argv)
{
    if (argc>=2 && strcmp(argv[1],"calibration")==0) return calibration_command(argc,argv);
    if (argc==1 || (argc==2 && strcmp(argv[1],"probe")==0)) {
        /* Identity is the startup readback; console never touches the bus. */
        const ainekio_p4_imu_status_t status=ainekio_p4_imu_status();
        print_status(status);
        return !status.running;
    }
    const bool sample=argc==2 && strcmp(argv[1],"sample")==0;
    const bool watch=argc==2 && strcmp(argv[1],"watch")==0;
    const bool body=argc==2 && strcmp(argv[1],"body")==0;
    if (!sample && !watch && !body) { puts("imu [probe|sample|watch|body|calibration]");return 1; }
    const ainekio_p4_imu_status_t initial=ainekio_p4_imu_status();
    if (!initial.running) { print_status(initial);return 1; }
    printf("imu continuous 208Hz +/-16g +/-2000dps; snapshots up to 50Hz; frame=%s\n",
           body && initial.calibration_applied ? "body_nominal" : "sensor");
    printf("%s,read_mid_us,read_us,ax_m_s2,ay_m_s2,az_m_s2,gx_rad_s,gy_rad_s,gz_rad_s\n",
           body ? "imu_body_csv" : "imu_csv");
    uint64_t last=0;
    unsigned count=0;
    const int64_t end=esp_timer_get_time()+(watch ? 10000000 : 2000000);
    while (esp_timer_get_time()<end) {
        const ainekio_p4_imu_status_t s=ainekio_p4_imu_status();
        if (s.samples && s.samples!=last) {
            last=s.samples;
            const float *accel=body ? s.attitude.acceleration_m_s2 : s.raw.acceleration_m_s2;
            const float *gyro=body ? s.attitude.angular_rate_rad_s : s.raw.angular_rate_rad_s;
            printf("%s,%" PRIu64 ",%" PRIu32 ",%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n",
                   body ? "imu_body_csv" : "imu_csv",body ? s.attitude.timestamp_us : s.raw.timestamp_us,s.read_us,
                   (double)accel[0],(double)accel[1],(double)accel[2],
                   (double)gyro[0],(double)gyro[1],(double)gyro[2]);
            ++count;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    printf("imu capture snapshots=%u; continuous acquisition unchanged\n",count);
    print_status(ainekio_p4_imu_status());
    return 0;
}
