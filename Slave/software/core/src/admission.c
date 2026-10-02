#include "ainekio/admission.h"

static ainekio_decision_t reject(ainekio_reject_reason_t reason)
{
    return (ainekio_decision_t){false, reason, AINEKIO_LIFECYCLE_ACK_ONLY};
}

void ainekio_admission_init(ainekio_admission_t *a, uint32_t commands, bool deadline)
{
    *a = (ainekio_admission_t){.allowed_commands=commands, .require_deadline=deadline};
    ainekio_core_init(&a->core);
}

uint64_t ainekio_admission_open(ainekio_admission_t *a)
{
    ++a->generation;
    a->connected = true;
    a->authenticated = false;
    a->stale = false;
    ainekio_core_enter_failsafe(&a->core);
    return a->generation;
}

void ainekio_admission_close(ainekio_admission_t *a, uint64_t generation)
{
    if (generation != a->generation) return;
    a->connected = false;
    a->authenticated = false;
    a->stale = true;
    ++a->generation;
    ainekio_core_enter_failsafe(&a->core);
}

bool ainekio_admission_welcome(ainekio_admission_t *a, uint64_t generation,
    uint32_t epoch, ainekio_profile_t profile, bool deadline_supported, uint64_t now_us)
{
    if (generation != a->generation || !a->connected || a->authenticated ||
        (a->require_deadline && !deadline_supported) ||
        (profile != AINEKIO_PROFILE_HOME && profile != AINEKIO_PROFILE_TETHER)) return false;
    ainekio_core_begin_session(&a->core, epoch);
    ainekio_core_set_profile(&a->core, profile);
    a->authenticated = true;
    a->stale = false;
    a->last_control_us = now_us;
    return true;
}

bool ainekio_admission_control(ainekio_admission_t *a, uint64_t generation, uint64_t now_us)
{
    if (generation != a->generation || !a->connected || !a->authenticated) return false;
    /* Silence stops execution, not the authenticated transport. If this frame
     * detects the timeout, let the caller disable outputs before accepting a
     * subsequent fresh frame. Recovery never clears the core's stop latch. */
    if (ainekio_admission_check_stale(a, now_us)) return false;
    a->last_control_us = now_us;
    a->stale = false;
    return true;
}

bool ainekio_admission_check_stale(ainekio_admission_t *a, uint64_t now_us)
{
    if (!a->authenticated || a->stale || now_us - a->last_control_us < AINEKIO_ADMISSION_STALE_US)
        return false;
    a->stale = true;
    ainekio_core_enter_failsafe(&a->core);
    return true;
}

ainekio_decision_t ainekio_admission_accept(ainekio_admission_t *a,
    uint64_t generation, const ainekio_control_message_t *m,
    uint64_t received_us, uint64_t now_us, bool model_supported)
{
    if (generation != a->generation || !a->connected || !a->authenticated || a->stale)
        return reject(AINEKIO_REJECT_STALE);
    if (now_us - a->last_control_us >= AINEKIO_ADMISSION_STALE_US)
        return reject(AINEKIO_REJECT_STALE);
    if (!m || !m->has_command || !m->has_sequence ||
        m->command.sequence != m->sequence || m->command.kind < AINEKIO_COMMAND_INTENT ||
        m->command.kind > AINEKIO_COMMAND_ROBOT_SETTINGS)
        return reject(AINEKIO_REJECT_MALFORMED);
    if (a->require_deadline && (!m->has_epoch || m->epoch != a->core.epoch))
        return reject(AINEKIO_REJECT_STALE);
    const bool stop = m->command.kind == AINEKIO_COMMAND_STOP;
    if (!stop && (now_us < received_us ||
        now_us - received_us >= AINEKIO_ADMISSION_MAX_QUEUE_US ||
        (a->require_deadline && !m->has_deadline) ||
        (m->has_deadline && now_us / 1000U >= m->deadline_ms))) {
        const ainekio_reject_reason_t sequence = ainekio_core_claim_sequence(&a->core, m->sequence);
        return reject(sequence == AINEKIO_REJECT_NONE ? AINEKIO_REJECT_STALE : sequence);
    }
    /* Model-specific semantic support is checked after session/deadline
     * validation, and consumes the sequence just like an unsupported kind. */
    if ((!model_supported && !stop) ||
        (a->allowed_commands & AINEKIO_COMMAND_MASK(m->command.kind)) == 0U) {
        const ainekio_reject_reason_t sequence = ainekio_core_claim_sequence(&a->core, m->sequence);
        return reject(sequence == AINEKIO_REJECT_NONE ? AINEKIO_REJECT_UNKNOWN : sequence);
    }
    return ainekio_core_accept(&a->core, &m->command);
}
