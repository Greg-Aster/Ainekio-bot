#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "ainekio/protocol.h"

/* Recording state owned by the existing microphone task. Only the configured
 * silence pause and wake maximum end recording. Capture boundaries reset it. */
typedef struct {
    int64_t silence_deadline;
    bool wake_latched;
    int64_t wake_deadline;
} p4_speech_gate_t;

static inline bool p4_speech_gate_step(p4_speech_gate_t *state,
    ainekio_microphone_gate_t gate, bool detected, bool speech,
    uint16_t silence_ms, uint16_t max_recording_ms, int64_t now_us)
{
    if (detected) {
        state->wake_latched = true;
        state->wake_deadline = now_us + (int64_t)max_recording_ms * 1000;
        state->silence_deadline = 0;
    }
    bool open = gate == AINEKIO_MIC_GATE_OPEN;
    if (gate == AINEKIO_MIC_GATE_VAD || (gate == AINEKIO_MIC_GATE_WAKE && state->wake_latched)) {
        if (speech) state->silence_deadline = now_us + (int64_t)silence_ms * 1000;
        open = (gate == AINEKIO_MIC_GATE_WAKE && !state->silence_deadline) ||
            now_us < state->silence_deadline;
    }
    if (gate == AINEKIO_MIC_GATE_WAKE && state->wake_latched &&
        (!open || now_us >= state->wake_deadline)) {
        state->wake_latched = false;
        open = false;
    }
    return open;
}
