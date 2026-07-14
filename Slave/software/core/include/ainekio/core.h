#ifndef AINEKIO_CORE_H
#define AINEKIO_CORE_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/protocol.h"

typedef enum {
    AINEKIO_POWER_NORMAL = 0,
    AINEKIO_POWER_MOVE_LOCKED,
    AINEKIO_POWER_CUTOFF,
} ainekio_power_guard_t;

typedef enum {
    AINEKIO_REJECT_NONE = 0,
    AINEKIO_REJECT_STALE,
    AINEKIO_REJECT_MODE,
    AINEKIO_REJECT_UNSAFE,
    AINEKIO_REJECT_LIMIT,
    AINEKIO_REJECT_UNKNOWN,
    AINEKIO_REJECT_BUSY,
    AINEKIO_REJECT_PROFILE,
    AINEKIO_REJECT_ASSET_MISSING,
    AINEKIO_REJECT_MALFORMED,
} ainekio_reject_reason_t;

typedef enum {
    AINEKIO_LIFECYCLE_ACK_ONLY = 0,
    AINEKIO_LIFECYCLE_ACK_THEN_DONE,
} ainekio_lifecycle_t;

typedef struct {
    bool accepted;
    ainekio_reject_reason_t rejection;
    ainekio_lifecycle_t lifecycle;
} ainekio_decision_t;

typedef struct {
    uint32_t epoch;
    uint32_t highest_sequence;
    bool has_sequence;
    bool boot_ready;
    bool servos_attached;
    bool stop_latched;
    ainekio_body_state_t state;
    ainekio_profile_t profile;
    ainekio_mode_t mode;
    ainekio_power_guard_t power_guard;
} ainekio_core_t;

void ainekio_core_init(ainekio_core_t *core);
void ainekio_core_begin_session(ainekio_core_t *core, uint32_t epoch);
void ainekio_core_enter_failsafe(ainekio_core_t *core);
void ainekio_core_set_profile(ainekio_core_t *core, ainekio_profile_t profile);
void ainekio_core_set_mode(ainekio_core_t *core, ainekio_mode_t mode);
void ainekio_core_set_state(ainekio_core_t *core, ainekio_body_state_t state);
void ainekio_core_set_boot_ready(ainekio_core_t *core, bool ready);
void ainekio_core_set_power_guard(ainekio_core_t *core, ainekio_power_guard_t guard);
ainekio_reject_reason_t ainekio_core_claim_sequence(ainekio_core_t *core, uint32_t sequence);
ainekio_lifecycle_t ainekio_command_lifecycle(const ainekio_command_t *command);
ainekio_decision_t ainekio_core_accept(ainekio_core_t *core, const ainekio_command_t *command);

#endif
