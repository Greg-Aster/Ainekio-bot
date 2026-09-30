#ifndef AINEKIO_IMU_H
#define AINEKIO_IMU_H

#include "FusionAhrs.h"
#include <stdbool.h>
#include <stdint.h>

/* Acquisition timestamps are monotonic microseconds from one sensor session,
 * never network arrival time or retimed gait time. Accelerometer values are
 * specific force (include gravity at rest), in sensor axes. */
typedef struct {
    uint64_t timestamp_us;
    float acceleration_m_s2[3];
    float angular_rate_rad_s[3];
} ainekio_imu_sample_t;

typedef struct {
    float sample_rate_hz;
    uint32_t max_gap_us;
    uint32_t stale_after_us;
    float gyro_range_rad_s;
    float accel_range_m_s2;
    float gain;
    float acceleration_rejection_rad;
    float recovery_seconds;
    /* Proper rotation, row-major: sensor axes -> body x forward, y left, z up.
     * Defaults are identity for bench/replay use, NOT a mounting calibration. */
    float sensor_to_body[9];
    float gyro_bias_rad_s[3];
    float accel_bias_m_s2[3];
    float accel_scale[3];
} ainekio_imu_config_t;

typedef struct {
    uint64_t timestamp_us;
    uint64_t age_us; /* UINT64_MAX when absent or now precedes acquisition. */
    uint64_t accepted_samples;
    uint64_t rejected_samples;
    uint64_t gap_restarts;
    float acceleration_m_s2[3]; /* Calibrated body axes; still includes gravity. */
    float angular_rate_rad_s[3]; /* Calibrated body axes. */
    /* w,x,y,z; rotates body vectors to a local z-up world. Yaw is arbitrary
     * at startup and drifts: this six-axis estimate has no heading reference. */
    float orientation_wxyz[4];
    bool available;
    bool fresh;
    bool startup;
    bool gyro_recovery;
    bool accelerometer_ignored;
    bool acceleration_recovery;
} ainekio_imu_observation_t;

/* Caller-owned, fixed storage; fields are private implementation state.
 * A single owner updates/reads it. Firmware must synchronize snapshot copies
 * itself; this library owns no task, bus, allocation, transport or actuator. */
typedef struct {
    ainekio_imu_config_t config;
    FusionAhrs ahrs;
    ainekio_imu_observation_t observation;
    bool initialized;
    bool gravity_initialized;
} ainekio_imu_t;

typedef enum {
    AINEKIO_IMU_REJECTED,
    AINEKIO_IMU_ACCEPTED,
    AINEKIO_IMU_RESTARTED
} ainekio_imu_result_t;

ainekio_imu_config_t ainekio_imu_default_config(void);
/* Invalid configuration leaves an existing estimator unchanged. */
bool ainekio_imu_init(ainekio_imu_t *imu, const ainekio_imu_config_t *config);
/* Invalid/duplicate/out-of-order samples only increment rejected_samples.
 * A long gap restarts convergence without integrating across the missing time.
 * Reinitialize explicitly when the acquisition clock/session is replaced. */
ainekio_imu_result_t ainekio_imu_update(ainekio_imu_t *imu,
                                      const ainekio_imu_sample_t *sample);
/* Returns whether a sample exists, even when stale. Reading never advances
 * the estimator. Freshness and recovery flags are observations, not proof of
 * calibration, physical posture, foot contact, or permission to move. */
bool ainekio_imu_observe(const ainekio_imu_t *imu, uint64_t now_us,
                         ainekio_imu_observation_t *observation);

#endif
