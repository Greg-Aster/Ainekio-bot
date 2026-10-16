#pragma once
#include "ainekio/imu.h"
#include "esp_err.h"

typedef struct {
    float sensor_to_body[9]; /* row-major proper rotation */
    float gyro_bias_rad_s[3]; /* sensor axes, subtracted before rotation */
} ainekio_p4_imu_calibration_t;

enum { AINEKIO_GYRO_IDLE, AINEKIO_GYRO_COLLECTING, AINEKIO_GYRO_SAVED, AINEKIO_GYRO_ERROR };
enum { AINEKIO_GYRO_CALIBRATION_SAMPLES = 256 };
typedef struct {
    unsigned phase, samples;
    esp_err_t error;
    float bias_rad_s[3], deviation_rad_s[3];
} ainekio_p4_gyro_calibration_status_t;

/* With saved mounting/bias, attitude uses nominal
 * body axes. Accelerometer bias/scale remain uncalibrated. Without saved
 * calibration, identity mounting/zero bias mean unverified sensor axes.
 * The body output owner consumes snapshots for posture and walking feedback. */
typedef struct {
    bool configured, running;
    bool calibration_applied;
    ainekio_p4_imu_calibration_t calibration;
    ainekio_p4_gyro_calibration_status_t gyro_calibration;
    uint8_t identity;
    esp_err_t last_error;
    uint64_t samples, io_errors, no_data_polls, interval_max_us;
    uint32_t read_us, read_max_us;
    ainekio_imu_sample_t raw;
    ainekio_imu_observation_t attitude;
} ainekio_p4_imu_status_t;

/* Called once by app startup after media creates/prepares the shared bus. */
esp_err_t ainekio_p4_imu_start(void);
/* Copies the last result without I2C or advancing the estimator. */
ainekio_p4_imu_status_t ainekio_p4_imu_status(void);
/* Uses the existing estimator's configuration validation. Save changes only
 * the IMU NVS blob; acquisition applies it at next boot, never mid-sample. */
esp_err_t ainekio_p4_imu_calibration_load(ainekio_p4_imu_calibration_t *calibration,bool *found);
esp_err_t ainekio_p4_imu_calibration_save(const ainekio_p4_imu_calibration_t *calibration);
/* Explicit stationary measurement. No actuator action or reboot. Acquisition
 * collects raw samples, saves their mean, then applies the bias between samples
 * while preserving the mounting rotation and continuous attitude estimate. */
esp_err_t ainekio_p4_imu_calibrate_gyro(void);
