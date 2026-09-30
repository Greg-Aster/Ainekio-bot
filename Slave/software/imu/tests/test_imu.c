#include "ainekio/imu.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define G 9.80665F
#define RAD 0.017453292519943295F

static void near(float actual, float expected, float tolerance)
{
    if (!isfinite(actual) || fabsf(actual - expected) > tolerance) {
        fprintf(stderr, "actual=%g expected=%g tolerance=%g\n", actual, expected, tolerance);
        assert(false);
    }
}

static void settle(ainekio_imu_t *imu, ainekio_imu_sample_t *sample)
{
    for (unsigned i = 0; i < 1200; ++i) {
        sample->timestamp_us += 4808;
        assert(ainekio_imu_update(imu, sample) == AINEKIO_IMU_ACCEPTED);
    }
    ainekio_imu_observation_t o;
    assert(ainekio_imu_observe(imu, sample->timestamp_us, &o));
    assert(o.fresh && !o.startup && !o.gyro_recovery);
}

static ainekio_imu_t initialized(void)
{
    ainekio_imu_t imu;
    const ainekio_imu_config_t c = ainekio_imu_default_config();
    assert(ainekio_imu_init(&imu, &c));
    return imu;
}

static void test_configuration(void)
{
    ainekio_imu_t imu = initialized();
    const ainekio_imu_t before = imu;
    ainekio_imu_config_t c = ainekio_imu_default_config();
    c.sensor_to_body[0] = -1.F; /* Reflection is not a physical rotation. */
    assert(!ainekio_imu_init(&imu, &c));
    assert(memcmp(&imu, &before, sizeof(imu)) == 0);
    c = ainekio_imu_default_config(); c.sensor_to_body[1] = .1F;
    assert(!ainekio_imu_init(&imu, &c));
    c = ainekio_imu_default_config(); c.sample_rate_hz = NAN;
    assert(!ainekio_imu_init(&imu, &c));
    c = ainekio_imu_default_config(); c.max_gap_us = 1;
    assert(!ainekio_imu_init(&imu, &c));
    c = ainekio_imu_default_config(); c.accel_scale[2] = INFINITY;
    assert(!ainekio_imu_init(&imu, &c));
    assert(!ainekio_imu_init(NULL, &c));
    assert(!ainekio_imu_init(&imu, NULL));
}

static void test_orientation_and_mount(void)
{
    /* Analytical gravity observation for +30 degree roll, -20 degree pitch.
     * Check the world-up vector in body axes, independent of unobservable yaw. */
    const float roll = 30.F * RAD, pitch = -20.F * RAD;
    const float up[3] = {-sinf(pitch), sinf(roll)*cosf(pitch), cosf(roll)*cosf(pitch)};
    ainekio_imu_t imu = initialized();
    ainekio_imu_config_t c = ainekio_imu_default_config();
    const float rotation[9] = {0.F,-1.F,0.F, 0.F,0.F,-1.F, 1.F,0.F,0.F};
    memcpy(c.sensor_to_body, rotation, sizeof(rotation));
    c.gyro_bias_rad_s[0] = .02F;
    c.accel_bias_m_s2[1] = .15F;
    c.accel_scale[2] = 1.02F;
    assert(ainekio_imu_init(&imu, &c));
    ainekio_imu_sample_t sample = {0};
    for (unsigned j = 0; j < 3; ++j) {
        float a = 0.F;
        for (unsigned i = 0; i < 3; ++i) a += rotation[3*i+j]*up[i]*G;
        sample.acceleration_m_s2[j] = a/c.accel_scale[j] + c.accel_bias_m_s2[j];
        sample.angular_rate_rad_s[j] = c.gyro_bias_rad_s[j];
    }
    settle(&imu, &sample);
    ainekio_imu_observation_t o;
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    const float *q = o.orientation_wxyz;
    const float estimated_up[3] = {2.F*(q[1]*q[3]-q[0]*q[2]),
        2.F*(q[2]*q[3]+q[0]*q[1]), 1.F-2.F*(q[1]*q[1]+q[2]*q[2])};
    for (unsigned i = 0; i < 3; ++i) {
        near(estimated_up[i], up[i], .001F);
        near(o.acceleration_m_s2[i], up[i]*G, .0001F);
        near(o.angular_rate_rad_s[i], 0.F, .000001F);
    }
}

static void test_elapsed_time_rotation(void)
{
    ainekio_imu_t imu = initialized();
    ainekio_imu_sample_t sample = {.acceleration_m_s2={0.F,0.F,G}};
    settle(&imu, &sample);
    sample.angular_rate_rad_s[2] = 30.F*RAD;
    uint64_t elapsed = 0;
    for (unsigned i = 0; i < 208; ++i) {
        const uint64_t dt = i % 2 ? 5208 : 4408;
        elapsed += dt;
        sample.timestamp_us += dt;
        assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    }
    ainekio_imu_observation_t o;
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    const float *q = o.orientation_wxyz;
    const float yaw = atan2f(2.F*(q[0]*q[3]+q[1]*q[2]),1.F-2.F*(q[2]*q[2]+q[3]*q[3]));
    near(yaw, 30.F*RAD*(float)elapsed/1000000.F, .0001F);
    const ainekio_imu_t before = imu;
    for (unsigned i = 0; i < 100; ++i)
        assert(ainekio_imu_observe(&imu, sample.timestamp_us+i, &o));
    assert(memcmp(&before, &imu, sizeof(imu)) == 0);
}

static void test_invalid_and_stale(void)
{
    ainekio_imu_t imu = initialized();
    ainekio_imu_observation_t o;
    assert(!ainekio_imu_observe(&imu, 0, &o));
    assert(!o.available && !o.fresh && o.age_us == UINT64_MAX);
    ainekio_imu_sample_t sample = {.timestamp_us=100, .acceleration_m_s2={0.F,0.F,G}};
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    const FusionAhrs before = imu.ahrs;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_REJECTED);
    sample.timestamp_us = 99;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_REJECTED);
    sample.timestamp_us = 5000; sample.angular_rate_rad_s[0] = NAN;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_REJECTED);
    sample.angular_rate_rad_s[0] = 0; sample.acceleration_m_s2[2] = INFINITY;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_REJECTED);
    sample.acceleration_m_s2[2] = 1000.F;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_REJECTED);
    assert(memcmp(&before, &imu.ahrs, sizeof(before)) == 0);
    assert(ainekio_imu_observe(&imu, 20100, &o));
    assert(o.fresh && o.accepted_samples == 1 && o.rejected_samples == 5);
    assert(ainekio_imu_observe(&imu, 20101, &o));
    assert(!o.fresh && o.timestamp_us == 100);
    assert(ainekio_imu_observe(&imu, 99, &o));
    assert(!o.fresh && o.age_us == UINT64_MAX);
    assert(!ainekio_imu_observe(&imu, 100, NULL));
}

static void test_gap_and_session_reset(void)
{
    ainekio_imu_t imu = initialized();
    ainekio_imu_sample_t sample = {.acceleration_m_s2={0.F,0.F,G}};
    settle(&imu, &sample);
    sample.timestamp_us += 100000;
    sample.angular_rate_rad_s[2] = 90.F*RAD;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_RESTARTED);
    ainekio_imu_observation_t o;
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    assert(o.startup && o.gap_restarts == 1);
    near(o.orientation_wxyz[0], 1.F, .000001F);
    near(o.orientation_wxyz[3], 0.F, .000001F); /* No integration over missing time. */
    assert(ainekio_imu_init(&imu, &imu.config));
    sample.timestamp_us = 0;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    assert(ainekio_imu_observe(&imu, 0, &o));
    assert(o.accepted_samples == 1 && o.gap_restarts == 0 && o.startup);
    near(o.orientation_wxyz[3], 0.F, .000001F);
}

static void test_disturbance_flags(void)
{
    ainekio_imu_t imu = initialized();
    ainekio_imu_sample_t sample = {.acceleration_m_s2={0.F,0.F,G}};
    settle(&imu, &sample);
    sample.acceleration_m_s2[0] = G;
    sample.timestamp_us += 4808;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    ainekio_imu_observation_t o;
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    assert(o.accelerometer_ignored && !o.startup);
    near(o.orientation_wxyz[2], 0.F, .000001F);
    sample.acceleration_m_s2[0] = 0;
    sample.angular_rate_rad_s[0] = 1990.F*RAD;
    sample.timestamp_us += 4808;
    assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    assert(o.gyro_recovery && o.startup);
    imu = initialized();
    sample = (ainekio_imu_sample_t){0};
    for (unsigned i = 0; i < 1000; ++i) {
        sample.timestamp_us += 4808;
        assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    }
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    assert(o.startup && o.accelerometer_ignored);
}

static void test_inverted_and_near_zero(void)
{
    ainekio_imu_t imu = initialized();
    ainekio_imu_sample_t sample = {.acceleration_m_s2={0.F,0.F,1.e-30F}};
    for (unsigned i = 0; i < 1000; ++i) {
        sample.timestamp_us += 4808;
        assert(ainekio_imu_update(&imu, &sample) == AINEKIO_IMU_ACCEPTED);
    }
    ainekio_imu_observation_t o;
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    assert(o.startup && o.accelerometer_ignored);
    sample.acceleration_m_s2[2] = -G;
    settle(&imu, &sample);
    assert(ainekio_imu_observe(&imu, sample.timestamp_us, &o));
    /* Inverted inclination: roll +/-180, yaw remains unreferenced. */
    near(fabsf(o.orientation_wxyz[1]), 1.F, .00001F);
    near(o.orientation_wxyz[0], 0.F, .00001F);
}

int main(void)
{
    test_configuration();
    test_orientation_and_mount();
    test_elapsed_time_rotation();
    test_invalid_and_stale();
    test_gap_and_session_reset();
    test_disturbance_flags();
    test_inverted_and_near_zero();
    printf("IMU estimation: seven scenarios passed; fixed state=%zu bytes\n", sizeof(ainekio_imu_t));
    return 0;
}
