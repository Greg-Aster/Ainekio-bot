#include "ainekio/core.h"

static bool command_is_calibration_only(ainekio_command_kind_t kind)
{
    return kind == AINEKIO_COMMAND_SERVO || kind == AINEKIO_COMMAND_LIMITS ||
           kind == AINEKIO_COMMAND_POSE_SAVE || kind == AINEKIO_COMMAND_CALIBRATION_SAVE;
}

static bool command_is_movement(const ainekio_command_t *command)
{
    return command->kind == AINEKIO_COMMAND_INTENT &&
           ainekio_intent_is_movement(command->data.intent.kind);
}

static ainekio_decision_t rejected(ainekio_reject_reason_t reason)
{
    ainekio_decision_t decision = {
        .accepted = false,
        .rejection = reason,
        .lifecycle = AINEKIO_LIFECYCLE_ACK_ONLY,
    };
    return decision;
}

void ainekio_core_init(ainekio_core_t *core)
{
    *core = (ainekio_core_t){
        .state = AINEKIO_STATE_ACTIVE,
        .profile = AINEKIO_PROFILE_HOME,
        .mode = AINEKIO_MODE_NORMAL,
        .power_guard = AINEKIO_POWER_NORMAL,
    };
}

void ainekio_core_begin_session(ainekio_core_t *core, uint32_t epoch)
{
    core->epoch = epoch;
    core->highest_sequence = 0U;
    core->has_sequence = false;
    core->state = AINEKIO_STATE_ACTIVE;
    core->mode = AINEKIO_MODE_NORMAL;
    core->servos_attached = false;
    core->stop_latched = true;
}

void ainekio_core_enter_failsafe(ainekio_core_t *core)
{
    core->state = AINEKIO_STATE_FAILSAFE;
    core->servos_attached = false;
    core->stop_latched = true;
}

void ainekio_core_set_profile(ainekio_core_t *core, ainekio_profile_t profile)
{
    core->profile = profile;
}

void ainekio_core_set_mode(ainekio_core_t *core, ainekio_mode_t mode)
{
    core->mode = mode;
}

void ainekio_core_set_state(ainekio_core_t *core, ainekio_body_state_t state)
{
    core->state = state;
}

void ainekio_core_set_boot_ready(ainekio_core_t *core, bool ready)
{
    core->boot_ready = ready;
    if (!ready) {
        core->servos_attached = false;
    }
}

void ainekio_core_set_power_guard(ainekio_core_t *core, ainekio_power_guard_t guard)
{
    const ainekio_power_guard_t previous = core->power_guard;
    core->power_guard = guard;
    if (guard == AINEKIO_POWER_CUTOFF) {
        core->servos_attached = false;
        core->stop_latched = true;
        core->state = AINEKIO_STATE_DEEP_SLEEP;
    } else if (guard == AINEKIO_POWER_NORMAL && previous == AINEKIO_POWER_CUTOFF) {
        core->state = AINEKIO_STATE_ACTIVE;
    }
}

ainekio_reject_reason_t ainekio_core_claim_sequence(ainekio_core_t *core, uint32_t sequence)
{
    if (sequence == 0U || sequence > AINEKIO_MAX_SEQUENCE) {
        return AINEKIO_REJECT_MALFORMED;
    }
    if (core->has_sequence && sequence <= core->highest_sequence) {
        return AINEKIO_REJECT_STALE;
    }

    core->highest_sequence = sequence;
    core->has_sequence = true;
    return AINEKIO_REJECT_NONE;
}

ainekio_lifecycle_t ainekio_command_lifecycle(const ainekio_command_t *command)
{
    if (command->kind == AINEKIO_COMMAND_INTENT || command->kind == AINEKIO_COMMAND_SNAPSHOT) {
        return AINEKIO_LIFECYCLE_ACK_THEN_DONE;
    }
    if (command->kind == AINEKIO_COMMAND_TTS && command->data.tts_operation == AINEKIO_TTS_START) {
        return AINEKIO_LIFECYCLE_ACK_THEN_DONE;
    }
    if (command->kind == AINEKIO_COMMAND_STATE &&
        command->data.state.request == AINEKIO_STATE_REQUEST_SLEEP) {
        return AINEKIO_LIFECYCLE_ACK_THEN_DONE;
    }
    return AINEKIO_LIFECYCLE_ACK_ONLY;
}

ainekio_decision_t ainekio_core_accept(ainekio_core_t *core, const ainekio_command_t *command)
{
    const bool is_stop = command->kind == AINEKIO_COMMAND_STOP;
    const bool is_movement = command_is_movement(command);

    if (is_stop) {
        core->servos_attached = false;
        core->stop_latched = true;
    }

    const ainekio_reject_reason_t sequence_rejection =
        ainekio_core_claim_sequence(core, command->sequence);
    if (sequence_rejection != AINEKIO_REJECT_NONE) {
        return rejected(sequence_rejection);
    }

    if (core->state == AINEKIO_STATE_DEEP_SLEEP) {
        return rejected(AINEKIO_REJECT_BUSY);
    }
    if (is_stop) {
        return (ainekio_decision_t){true, AINEKIO_REJECT_NONE, AINEKIO_LIFECYCLE_ACK_ONLY};
    }
    if (command_is_calibration_only(command->kind) && core->mode != AINEKIO_MODE_CALIBRATE) {
        return rejected(AINEKIO_REJECT_MODE);
    }
    if (is_movement && !core->boot_ready) {
        return rejected(AINEKIO_REJECT_BUSY);
    }
    if (is_movement && core->power_guard != AINEKIO_POWER_NORMAL &&
        command->data.intent.kind != AINEKIO_INTENT_NEUTRAL) {
        return rejected(AINEKIO_REJECT_UNSAFE);
    }
    if (core->profile == AINEKIO_PROFILE_TETHER &&
        command->kind == AINEKIO_COMMAND_CAMERA && command->data.camera.enabled) {
        return rejected(AINEKIO_REJECT_PROFILE);
    }
    if (core->profile == AINEKIO_PROFILE_TETHER &&
        command->kind == AINEKIO_COMMAND_MICROPHONE &&
        command->data.microphone.enabled &&
        command->data.microphone.gate == AINEKIO_MIC_GATE_OPEN) {
        return rejected(AINEKIO_REJECT_PROFILE);
    }

    if (is_movement) {
        core->servos_attached = true;
        core->stop_latched = false;
    }
    if (command->kind == AINEKIO_COMMAND_MODE) {
        ainekio_core_set_mode(core, command->data.mode);
    } else if (command->kind == AINEKIO_COMMAND_PROFILE) {
        core->profile = command->data.profile;
    } else if (command->kind == AINEKIO_COMMAND_STATE) {
        if (command->data.state.request == AINEKIO_STATE_REQUEST_IDLE) {
            ainekio_core_set_state(core, AINEKIO_STATE_IDLE);
        } else if (command->data.state.request == AINEKIO_STATE_REQUEST_DOZE) {
            ainekio_core_set_state(core, AINEKIO_STATE_DOZING);
        } else {
            ainekio_core_set_state(core, AINEKIO_STATE_DEEP_SLEEP);
            core->servos_attached = false;
        }
    } else if (command->kind == AINEKIO_COMMAND_INTENT ||
               command->kind == AINEKIO_COMMAND_SNAPSHOT) {
        ainekio_core_set_state(core, AINEKIO_STATE_ACTIVE);
    }

    return (ainekio_decision_t){
        .accepted = true,
        .rejection = AINEKIO_REJECT_NONE,
        .lifecycle = ainekio_command_lifecycle(command),
    };
}
