#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#include "ainekio/core.h"

typedef struct {
    ainekio_core_t core;
} ainekio_emulator_core_t;

ainekio_emulator_core_t *ainekio_emulator_core_create(void)
{
    ainekio_emulator_core_t *emulator = calloc(1U, sizeof(*emulator));
    if (emulator != NULL) {
        ainekio_core_init(&emulator->core);
    }
    return emulator;
}

void ainekio_emulator_core_destroy(ainekio_emulator_core_t *emulator)
{
    free(emulator);
}

void ainekio_emulator_core_begin_session(ainekio_emulator_core_t *emulator,
                                         uint32_t epoch,
                                         int profile)
{
    ainekio_core_begin_session(&emulator->core, epoch);
    ainekio_core_set_profile(&emulator->core, (ainekio_profile_t)profile);
    ainekio_core_set_boot_ready(&emulator->core, true);
}

void ainekio_emulator_core_enter_failsafe(ainekio_emulator_core_t *emulator)
{
    ainekio_core_enter_failsafe(&emulator->core);
}

int ainekio_emulator_core_claim_sequence(ainekio_emulator_core_t *emulator, uint32_t sequence)
{
    return (int)ainekio_core_claim_sequence(&emulator->core, sequence);
}

int ainekio_emulator_core_accept(ainekio_emulator_core_t *emulator,
                                 uint32_t sequence,
                                 int command_kind,
                                 int command_value,
                                 int *rejection,
                                 int *lifecycle)
{
    ainekio_command_t command = {
        .sequence = sequence,
        .kind = (ainekio_command_kind_t)command_kind,
    };

    switch (command.kind) {
    case AINEKIO_COMMAND_INTENT:
        command.data.intent.kind = (ainekio_intent_kind_t)command_value;
        break;
    case AINEKIO_COMMAND_TTS:
        command.data.tts_operation = (ainekio_tts_operation_t)command_value;
        break;
    case AINEKIO_COMMAND_PROFILE:
        command.data.profile = (ainekio_profile_t)command_value;
        break;
    case AINEKIO_COMMAND_STATE:
        command.data.state.request = (ainekio_state_request_t)command_value;
        break;
    case AINEKIO_COMMAND_MODE:
        command.data.mode = (ainekio_mode_t)command_value;
        break;
    default:
        break;
    }

    const ainekio_decision_t decision = ainekio_core_accept(&emulator->core, &command);
    *rejection = (int)decision.rejection;
    *lifecycle = (int)decision.lifecycle;
    return decision.accepted ? 1 : 0;
}

int ainekio_emulator_core_state(const ainekio_emulator_core_t *emulator)
{
    return (int)emulator->core.state;
}

int ainekio_emulator_core_profile(const ainekio_emulator_core_t *emulator)
{
    return (int)emulator->core.profile;
}

int ainekio_emulator_core_servos_attached(const ainekio_emulator_core_t *emulator)
{
    return emulator->core.servos_attached ? 1 : 0;
}
