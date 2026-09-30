#include "ainekio/imu.h"

#include <float.h>
#include <math.h>
#include <stddef.h>
#include <string.h>

#define GRAVITY_M_S2 9.80665F
#define RADIANS_PER_DEGREE 0.017453292519943295F

ainekio_imu_config_t ainekio_imu_default_config(void)
{
    return (ainekio_imu_config_t){
        .sample_rate_hz = 208.F, .max_gap_us = 20000, .stale_after_us = 20000,
        .gyro_range_rad_s = 2000.F * RADIANS_PER_DEGREE,
        .accel_range_m_s2 = 16.F * GRAVITY_M_S2,
        .gain = .5F, .acceleration_rejection_rad = 10.F * RADIANS_PER_DEGREE,
        .recovery_seconds = 5.F,
        .sensor_to_body = {1.F, 0.F, 0.F, 0.F, 1.F, 0.F, 0.F, 0.F, 1.F},
        .accel_scale = {1.F, 1.F, 1.F},
    };
}

static bool within(float value, float minimum, float maximum)
{
    return isfinite(value) && value >= minimum && value <= maximum;
}

static bool valid_config(const ainekio_imu_config_t *c)
{
    if (!c || !within(c->sample_rate_hz, 10.F, 2000.F) ||
        c->max_gap_us < 1000000.F / c->sample_rate_hz || c->max_gap_us > 100000 ||
        c->stale_after_us < c->max_gap_us || c->stale_after_us > 1000000 ||
        !within(c->gyro_range_rad_s, RADIANS_PER_DEGREE, 4000.F * RADIANS_PER_DEGREE) ||
        !within(c->accel_range_m_s2, GRAVITY_M_S2, 32.F * GRAVITY_M_S2) ||
        !within(c->gain, .001F, 9.9F) ||
        !within(c->acceleration_rejection_rad, RADIANS_PER_DEGREE, 90.F * RADIANS_PER_DEGREE) ||
        !within(c->recovery_seconds, .1F, 60.F)) return false;
    for (unsigned i = 0; i < 3; ++i) {
        if (!within(c->gyro_bias_rad_s[i], -c->gyro_range_rad_s, c->gyro_range_rad_s) ||
            !within(c->accel_bias_m_s2[i], -c->accel_range_m_s2, c->accel_range_m_s2) ||
            !within(c->accel_scale[i], .5F, 2.F)) return false;
    }
    const float *r = c->sensor_to_body;
    for (unsigned i = 0; i < 9; ++i)
        if (!within(r[i], -1.0001F, 1.0001F)) return false;
    for (unsigned i = 0; i < 3; ++i) {
        for (unsigned j = 0; j < 3; ++j) {
            float dot = 0.F;
            for (unsigned k = 0; k < 3; ++k) dot += r[3*i+k] * r[3*j+k];
            if (fabsf(dot - (i == j ? 1.F : 0.F)) > .0001F) return false;
        }
    }
    const float determinant = r[0]*(r[4]*r[8]-r[5]*r[7]) -
        r[1]*(r[3]*r[8]-r[5]*r[6]) + r[2]*(r[3]*r[7]-r[4]*r[6]);
    return fabsf(determinant - 1.F) <= .0001F;
}

bool ainekio_imu_init(ainekio_imu_t *imu, const ainekio_imu_config_t *config)
{
    if (!imu || !valid_config(config)) return false;
    const ainekio_imu_config_t copy = *config;
    memset(imu, 0, sizeof(*imu));
    imu->config = copy;
    FusionAhrsInitialise(&imu->ahrs);
    const FusionAhrsSettings settings = {
        .sampleRate = copy.sample_rate_hz, .convention = FusionConventionNwu,
        .gain = copy.gain, .gyroscopeRange = copy.gyro_range_rad_s / RADIANS_PER_DEGREE,
        .accelerationRejection = copy.acceleration_rejection_rad / RADIANS_PER_DEGREE,
        .magneticRejection = 0.F, .rejectionTimeout = copy.recovery_seconds,
    };
    FusionAhrsSetSettings(&imu->ahrs, &settings);
    FusionAhrsRestart(&imu->ahrs);
    imu->observation.orientation_wxyz[0] = 1.F;
    imu->observation.startup = true;
    imu->observation.age_us = UINT64_MAX;
    imu->initialized = true;
    return true;
}

static FusionVector rotate(const float r[9], const float v[3])
{
    FusionVector result = FUSION_VECTOR_ZERO;
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j) result.array[i] += r[3*i+j] * v[j];
    return result;
}

/* Initialise inclination from gravity, including an inverted start. Starting
 * at identity leaves a complementary filter at a zero-cross-product fixed
 * point when the sensor's up vector is exactly opposite the prediction. */
static FusionQuaternion inclination(FusionVector acceleration)
{
    const float roll = atan2f(acceleration.axis.y, acceleration.axis.z);
    const float pitch = atan2f(-acceleration.axis.x,
                               hypotf(acceleration.axis.y, acceleration.axis.z));
    const float cr = cosf(roll*.5F), sr = sinf(roll*.5F);
    const float cp = cosf(pitch*.5F), sp = sinf(pitch*.5F);
    return (FusionQuaternion){.array={cr*cp, sr*cp, cr*sp, -sr*sp}};
}

ainekio_imu_result_t ainekio_imu_update(ainekio_imu_t *imu,
                                      const ainekio_imu_sample_t *sample)
{
    if (!imu || !imu->initialized) return AINEKIO_IMU_REJECTED;
    ainekio_imu_observation_t *o = &imu->observation;
    if (!sample || (o->available && sample->timestamp_us <= o->timestamp_us)) {
        ++o->rejected_samples;
        return AINEKIO_IMU_REJECTED;
    }
    const ainekio_imu_config_t *c = &imu->config;
    float acceleration[3], angular_rate[3];
    for (unsigned i = 0; i < 3; ++i) {
        if (!within(sample->acceleration_m_s2[i], -c->accel_range_m_s2, c->accel_range_m_s2) ||
            !within(sample->angular_rate_rad_s[i], -c->gyro_range_rad_s, c->gyro_range_rad_s)) {
            ++o->rejected_samples;
            return AINEKIO_IMU_REJECTED;
        }
        acceleration[i] = (sample->acceleration_m_s2[i] - c->accel_bias_m_s2[i]) * c->accel_scale[i];
        angular_rate[i] = sample->angular_rate_rad_s[i] - c->gyro_bias_rad_s[i];
    }
    const FusionVector accel = rotate(c->sensor_to_body, acceleration);
    const FusionVector gyro = rotate(c->sensor_to_body, angular_rate);
    const bool gap = o->available && sample->timestamp_us - o->timestamp_us > c->max_gap_us;
    FusionAhrs filter = imu->ahrs;
    bool gravity_initialized = imu->gravity_initialized;
    float period = 0.F;
    if (gap) {
        FusionAhrsRestart(&filter);
        gravity_initialized = false;
    } else if (o->available) {
        period = (float)(sample->timestamp_us - o->timestamp_us) / 1000000.F;
    }
    FusionVector accel_g = FusionVectorScale(accel, 1.F / GRAVITY_M_S2);
    if (FusionVectorNormSquared(accel_g) < FLT_MIN) accel_g = FUSION_VECTOR_ZERO;
    if (!gravity_initialized && !FusionVectorIsZero(accel_g)) {
        FusionAhrsSetQuaternion(&filter, inclination(accel_g));
        gravity_initialized = true;
    }
    /* The first sample establishes time; it must not invent a gyro interval.
     * A gap similarly establishes a new origin. No missed samples are replayed. */
    if (period > 0.F) {
        /* With no gravity observation at startup, convergence cannot be earned
         * merely by waiting. Keep startup explicit until acceleration returns. */
        if (FusionAhrsGetFlags(&filter).startup && FusionVectorIsZero(accel_g)) {
            FusionAhrsRestart(&filter);
            gravity_initialized = false;
        }
        FusionAhrsSetSamplePeriod(&filter, period);
        FusionAhrsUpdateNoMagnetometer(&filter,
            FusionVectorScale(gyro, 1.F / RADIANS_PER_DEGREE), accel_g);
    }
    const FusionQuaternion q = FusionAhrsGetQuaternion(&filter);
    for (unsigned i = 0; i < 4; ++i) {
        if (!isfinite(q.array[i])) {
            ++o->rejected_samples;
            return AINEKIO_IMU_REJECTED;
        }
    }
    imu->ahrs = filter;
    imu->gravity_initialized = gravity_initialized;
    if (gap) ++o->gap_restarts;
    const FusionAhrsFlags flags = FusionAhrsGetFlags(&filter);
    const FusionAhrsInternalStates internal = FusionAhrsGetInternalStates(&filter);
    memcpy(o->orientation_wxyz, q.array, sizeof(o->orientation_wxyz));
    memcpy(o->acceleration_m_s2, accel.array, sizeof(o->acceleration_m_s2));
    memcpy(o->angular_rate_rad_s, gyro.array, sizeof(o->angular_rate_rad_s));
    o->timestamp_us = sample->timestamp_us;
    o->available = true;
    o->fresh = true;
    o->age_us = 0;
    o->startup = flags.startup;
    o->gyro_recovery = flags.overrangeRecovery;
    o->accelerometer_ignored = period == 0.F || internal.accelerometerIgnored;
    o->acceleration_recovery = flags.accelerationRecovery;
    ++o->accepted_samples;
    return gap ? AINEKIO_IMU_RESTARTED : AINEKIO_IMU_ACCEPTED;
}

bool ainekio_imu_observe(const ainekio_imu_t *imu, uint64_t now_us,
                         ainekio_imu_observation_t *observation)
{
    if (!observation) return false;
    *observation = (ainekio_imu_observation_t){.age_us = UINT64_MAX};
    if (!imu || !imu->initialized) return false;
    *observation = imu->observation;
    observation->fresh = false;
    observation->age_us = UINT64_MAX;
    if (observation->available && now_us >= observation->timestamp_us) {
        observation->age_us = now_us - observation->timestamp_us;
        observation->fresh = observation->age_us <= imu->config.stale_after_us;
    }
    return observation->available;
}
