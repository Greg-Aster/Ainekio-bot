#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "ainekio/protocol.h"

/* Recording state owned by the existing microphone task. One step per 20 ms
 * PCM frame; playback/configuration/session boundaries reset this state. */
typedef struct {
    unsigned hangover;
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
        state->hangover = 150; /* Existing three-second wake acquisition window. */
    }
    bool open = gate == AINEKIO_MIC_GATE_OPEN;
    if (gate == AINEKIO_MIC_GATE_VAD || (gate == AINEKIO_MIC_GATE_WAKE && state->wake_latched)) {
        if (speech) state->hangover = silence_ms / 20;
        else if (state->hangover) --state->hangover;
        open = state->hangover > 0;
    }
    if (gate == AINEKIO_MIC_GATE_WAKE && state->wake_latched &&
        (!open || now_us >= state->wake_deadline)) {
        state->wake_latched = false;
        open = false;
    }
    return open;
}
