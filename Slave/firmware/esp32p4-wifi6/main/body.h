#pragma once
/* Owner-requested quiet hold. The shaft band covers the observed ~112 us
 * peak-to-peak fluctuation; it applies only to extra standing feedback trim. */
#define BALANCE_SHAFT_TOLERANCE_US 120.
#define BALANCE_SETTLE_DEG .5
#define BALANCE_WAKE_DEG 1.
#define BALANCE_SETTLE_RATE_DEG_S 1.

#include "ainekio/pca9685.h"
#include "ainekio/control_encode.h"
#include "esp_err.h"

/* The saved/commanded joint reference cannot be expressed by the motion model. */
enum { AINEKIO_P4_ERR_REFERENCE = 0x20000 };

/* The body task is the only I2C/PWM writer. Callers carry the generation from
 * admission, so explicit output release invalidates queued output writes. */
esp_err_t ainekio_p4_body_start(void);
/* Connection loss preserves finite work and powered holds. The output owner
 * uses the existing Finish path for an open-ended gait from this session. */
void ainekio_p4_body_connection_lost(uint64_t connection);
/* Re-probe/reinitialize the driver with every channel off. Never enables OE. */
esp_err_t ainekio_p4_body_prepare(uint64_t generation);
/* Cancel choreography and retain only the already energized commanded pose. */
esp_err_t ainekio_p4_body_hold(uint64_t generation);
esp_err_t ainekio_p4_body_home(uint64_t generation,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]);
esp_err_t ainekio_p4_body_move(uint64_t generation, uint8_t channel, uint16_t pulse);
void ainekio_p4_body_pulses(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]);
void ainekio_p4_body_pulse_snapshot(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS],uint64_t *published_us,bool *armed);
/* Nonblocking audio cue. The existing output owner performs it while holding a
 * pose; commanded motion owns the joints until it completes. Never arms PWM. */
void ainekio_p4_body_listen(bool active);
/* Meaningful input or audio completion resets the shared one-shot rest timer. */
void ainekio_p4_body_activity(void);

typedef struct {
    uint64_t connection;
    uint32_t sequence;
    bool completed;
    /* Nonterminal no-progress evidence; execution and powered hold continue. */
    bool jam_observation;
    bool idle_request; /* Shared timer asks the Freestyle owner to rest. */
    /* 0: authored completion; 1: original target not verified; 2: measured. */
    uint8_t position_verification;
    uint16_t target_adjusted_joints; /* Existing pose fitting changed these goals. */
    ainekio_cancel_code_t reason;
    esp_err_t result;
    uint16_t stalled_joints;
    uint64_t clock_us;
} ainekio_p4_body_event_t;
/* Published only from the output owner; this describes commanded execution,
 * not measured foot contact, travel or chassis pose. */
typedef struct {
    const char *command, *activity, *phase;
    uint32_t sequence;
    uint64_t connection, started_us, sampled_us;
    float expected_up[3];
    bool expected_up_known;
} ainekio_p4_execution_t;
typedef struct {
    uint64_t connection;
    uint32_t sequence;
    bool moving, speed_limited, automatic_run, listening_feedback;
    ainekio_p4_execution_t execution;
    bool walking_feedback_active, walking_feedback_reduced;
    float walking_heading_error_rad, walking_turn_percent;
    bool balance_active, balance_reduced;
    bool balance_settled;
    bool balance_tracking_available, balance_tracking_active, balance_tracking_reduced;
    float balance_tracking_error_deg[12], balance_tracking_trim_deg[12];
    float balance_tracking_lag_rad[2];
    bool servo_feedback_waiting;
    uint16_t servo_feedback_waiting_mask;
    float stand_progress;
    bool stand_replanning;
    uint32_t stand_replans;
    uint16_t stalled_joints;
    uint64_t stall_clock_us;
    float body_roll_rad, body_pitch_rad, balance_roll_rad, balance_pitch_rad;
    /* Commanded differences from the nominal motion, not servo feedback.
     * Legs: physical front-left, front-right, rear-left, rear-right. */
    bool balance_legs_valid;
    float balance_extension_mm[4];
    float balance_joint_delta_deg[AINEKIO_BODY_JOINT_COUNT]; /* model joint order */
    float gait_cycles_s, gait_requested_cycles_s, stride_percent, requested_stride_percent;
    bool gait_valid;
    double gait_phase; /* Planned phase, never measured foot contact. */
    /* Read-only presentation of the last successful motion sample. Display
     * tasks consume this; the output owner never renders or transfers pixels. */
    const char *face_command;
    uint64_t face_elapsed_us;
    uint32_t face_revision;
    bool face_is_clip, face_entering;
    size_t face_clip;
} ainekio_p4_body_status_t;

bool ainekio_p4_body_supports(const ainekio_command_t *command);
/* Returns after validation/admission; completion is delivered separately. Walk
 * updates acknowledge only the update; the original sequence owns completion. */
esp_err_t ainekio_p4_body_execute(uint64_t generation, uint64_t connection,
    const ainekio_command_t *command);
bool ainekio_p4_body_event(ainekio_p4_body_event_t *event);
ainekio_p4_body_status_t ainekio_p4_body_status(void);
/* Latest execution snapshot at or before this device sensor timestamp. */
ainekio_p4_execution_t ainekio_p4_body_execution_at(uint64_t timestamp_us);

/* Observed maxima since boot, not deadline guarantees. No logging in the loop. */
typedef struct {
    uint32_t frames, calculation_us, frame_us, request_us, over_2ms, over_5ms;
    uint32_t stack_free_bytes;
    uint32_t queue_depth;
} ainekio_p4_body_timing_t;
ainekio_p4_body_timing_t ainekio_p4_body_timing(void);
