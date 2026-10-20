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
 * admission, so Stop/disconnect invalidates work even while it is queued. */
esp_err_t ainekio_p4_body_start(void);
/* Asynchronous startup choreography; calibration Home is separate. */
esp_err_t ainekio_p4_body_startup(uint64_t generation);
/* Re-probe/reinitialize the driver with every channel off. Never enables OE. */
esp_err_t ainekio_p4_body_prepare(uint64_t generation);
/* Cancel choreography and retain only the already energized commanded pose. */
esp_err_t ainekio_p4_body_hold(uint64_t generation);
esp_err_t ainekio_p4_body_home(uint64_t generation,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]);
esp_err_t ainekio_p4_body_move(uint64_t generation, uint8_t channel, uint16_t pulse);
void ainekio_p4_body_pulses(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]);
/* Nonblocking audio cue. The existing output owner performs it while holding a
 * pose; commanded motion owns the joints until it completes. Never arms PWM. */
void ainekio_p4_body_listen(bool active);
/* Meaningful input or audio completion resets the shared one-shot rest timer. */
void ainekio_p4_body_activity(void);


typedef struct {
    uint64_t connection;
    uint32_t sequence;
    bool completed;
    ainekio_cancel_code_t reason;
    esp_err_t result;
} ainekio_p4_body_event_t;
typedef struct {
    uint64_t connection;
    uint32_t sequence;
    bool moving, speed_limited, automatic_run, listening_feedback;
    bool balance_active, balance_reduced;
    bool balance_settled;
    bool balance_tracking_available, balance_tracking_active, balance_tracking_reduced;
    float balance_tracking_error_deg[12], balance_tracking_trim_deg[12];
    float balance_tracking_lag_rad[2];
    bool servo_feedback_waiting;
    uint16_t servo_feedback_waiting_mask;
    float stand_progress;
    float body_roll_rad, body_pitch_rad, balance_roll_rad, balance_pitch_rad;
    /* Commanded differences from the nominal motion, not servo feedback.
     * Legs: physical front-left, front-right, rear-left, rear-right. */
    bool balance_legs_valid;
    float balance_extension_mm[4];
    float balance_joint_delta_deg[AINEKIO_BODY_JOINT_COUNT]; /* model joint order */
    float gait_cycles_s, gait_requested_cycles_s, stride_percent, requested_stride_percent;
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

/* Observed maxima since boot, not deadline guarantees. No logging in the loop. */
typedef struct {
    uint32_t frames, calculation_us, frame_us, request_us, over_2ms, over_5ms;
    uint32_t stack_free_bytes;
    uint32_t queue_depth;
} ainekio_p4_body_timing_t;
ainekio_p4_body_timing_t ainekio_p4_body_timing(void);
