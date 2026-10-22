#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Diagnostic event journal only: no actuator, admission or timing decisions.
 * Output time is software publication, not the PCA9685's physical PWM edge. */
enum { AINEKIO_TRACE_OUTPUT=1, AINEKIO_TRACE_SAMPLE=2, AINEKIO_TRACE_TRACKING=3 };
typedef struct {
    uint64_t time_us;
    unsigned kind;
    union {
        struct { uint16_t pulses[12]; bool armed; } output;
        struct {
            uint64_t sampled_us[4];
            uint16_t nominal_pulses[12];
            double phase[4];
            float target[4][3], measured[4][3], correction[4][3];
            float stride;
            uint32_t signature, command_sequence;
            unsigned valid_mask;
            bool eligible;
            bool support_known[4], grounded[4]; /* planned, never measured contact */
            /* Exact inputs available at this output decision, not reconstructed
             * with future sensor samples during training. Units in v2_learning.h. */
            uint32_t policy_signature;
            uint32_t gait_signature,profile_signature;
            uint64_t policy_imu_us;
            double policy_phase;
            float policy_input[4][8],policy_correction[4][3];
            float policy_command[4];
            bool policy_usable,policy_eligible;
            unsigned gait_mode;
            char model_id[65];
            float model_amount;
            float cycles_s, requested_rate;
            float reference_twist[3]; /* planned vx/vy m/s and yaw rad/s, not odometry */
            bool model_active;
        } tracking;
        struct {
            uint64_t sampled_us[16], imu_us;
            uint16_t raw[16], spread[16], valid_mask;
            float filtered[16], velocity[16];
            float q[4], gyro[3], accel[3];
            uint32_t revision, scan, scan_us, command_sequence;
            int error;
            bool imu_available, imu_fresh, imu_startup, imu_recovering;
            bool imu_calibrated;
            bool walking, entering;
            double phase;
            float stride_percent, cycles_s;
        } sample;
    };
} ainekio_gait_trace_event_t;
typedef struct {
    ainekio_gait_trace_event_t *events;
    size_t capacity;
    uint64_t latest;
} ainekio_gait_trace_ring_t;
/* Callers serialize access; read does not consume records. */
void ainekio_gait_trace_push(ainekio_gait_trace_ring_t *ring,const ainekio_gait_trace_event_t *event);
uint64_t ainekio_gait_trace_oldest(const ainekio_gait_trace_ring_t *ring);
bool ainekio_gait_trace_read(const ainekio_gait_trace_ring_t *ring,uint64_t sequence,ainekio_gait_trace_event_t *event);
