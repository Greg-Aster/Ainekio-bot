#pragma once

#include "ainekio/pca9685.h"
#include "ainekio/control_encode.h"
#include "esp_err.h"

/* The saved/commanded joint reference cannot be expressed by the motion model. */
enum { AINEKIO_P4_ERR_REFERENCE = 0x20000 };

/* The body task is the only I2C/PWM writer. Callers carry the generation from
 * admission, so Stop/disconnect invalidates work even while it is queued. */
esp_err_t ainekio_p4_body_start(void);
/* Re-probe/reinitialize the driver with every channel off. Never enables OE. */
esp_err_t ainekio_p4_body_prepare(uint64_t generation);
/* Cancel choreography and retain only the already energized commanded pose. */
esp_err_t ainekio_p4_body_hold(uint64_t generation);
esp_err_t ainekio_p4_body_home(uint64_t generation,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]);
esp_err_t ainekio_p4_body_move(uint64_t generation, uint8_t channel, uint16_t pulse);
void ainekio_p4_body_pulses(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]);

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
    bool moving, speed_limited, automatic_run;
    float gait_cycles_s, gait_requested_cycles_s, stride_percent, requested_stride_percent;
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
