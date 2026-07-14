#include <assert.h>
#include <stdio.h>

#include "ainekio/core.h"

static ainekio_command_t intent_command(uint32_t sequence, ainekio_intent_kind_t intent)
{
    ainekio_command_t command = {
        .sequence = sequence,
        .kind = AINEKIO_COMMAND_INTENT,
    };
    command.data.intent.kind = intent;
    return command;
}

static void test_initial_state_is_safe(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);

    assert(core.state == AINEKIO_STATE_ACTIVE);
    assert(core.profile == AINEKIO_PROFILE_HOME);
    assert(!core.boot_ready);
    assert(!core.servos_attached);
}

static void test_stop_detaches_until_next_movement(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);
    ainekio_core_set_boot_ready(&core, true);

    ainekio_command_t stand = intent_command(1U, AINEKIO_INTENT_STAND);
    assert(ainekio_core_accept(&core, &stand).accepted);
    assert(core.servos_attached);

    ainekio_command_t stop = {.sequence = 2U, .kind = AINEKIO_COMMAND_STOP};
    assert(ainekio_core_accept(&core, &stop).accepted);
    assert(core.stop_latched);
    assert(!core.servos_attached);

    ainekio_command_t profile = {.sequence = 3U, .kind = AINEKIO_COMMAND_PROFILE};
    profile.data.profile = AINEKIO_PROFILE_TETHER;
    assert(ainekio_core_accept(&core, &profile).accepted);
    assert(core.stop_latched);
    assert(!core.servos_attached);

    ainekio_command_t neutral = intent_command(4U, AINEKIO_INTENT_NEUTRAL);
    assert(ainekio_core_accept(&core, &neutral).accepted);
    assert(!core.stop_latched);
    assert(core.servos_attached);
}

static void test_session_boundary_detaches_servos(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);
    ainekio_core_set_boot_ready(&core, true);

    ainekio_command_t stand = intent_command(1U, AINEKIO_INTENT_STAND);
    assert(ainekio_core_accept(&core, &stand).accepted);
    assert(core.servos_attached);

    ainekio_core_begin_session(&core, 9U);
    assert(core.epoch == 9U);
    assert(!core.has_sequence);
    assert(!core.servos_attached);
    assert(core.stop_latched);
}

static void test_failsafe_detaches_servos(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);
    ainekio_core_set_boot_ready(&core, true);

    ainekio_command_t stand = intent_command(1U, AINEKIO_INTENT_STAND);
    assert(ainekio_core_accept(&core, &stand).accepted);

    ainekio_core_enter_failsafe(&core);
    assert(core.state == AINEKIO_STATE_FAILSAFE);
    assert(!core.servos_attached);
    assert(core.stop_latched);
}

static void test_sequence_and_safety_gates(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);
    ainekio_core_begin_session(&core, 7U);
    ainekio_core_set_boot_ready(&core, true);

    ainekio_command_t walk = intent_command(10U, AINEKIO_INTENT_WALK);
    assert(ainekio_core_accept(&core, &walk).accepted);
    assert(ainekio_core_accept(&core, &walk).rejection == AINEKIO_REJECT_STALE);

    ainekio_core_set_power_guard(&core, AINEKIO_POWER_MOVE_LOCKED);
    walk.sequence = 11U;
    assert(ainekio_core_accept(&core, &walk).rejection == AINEKIO_REJECT_UNSAFE);

    ainekio_command_t neutral = intent_command(12U, AINEKIO_INTENT_NEUTRAL);
    assert(ainekio_core_accept(&core, &neutral).accepted);
}

static void test_calibration_gate_and_lifecycle(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);

    ainekio_command_t servo = {.sequence = 1U, .kind = AINEKIO_COMMAND_SERVO};
    assert(ainekio_core_accept(&core, &servo).rejection == AINEKIO_REJECT_MODE);

    ainekio_command_t mode = {.sequence = 2U, .kind = AINEKIO_COMMAND_MODE};
    mode.data.mode = AINEKIO_MODE_CALIBRATE;
    assert(ainekio_core_accept(&core, &mode).accepted);

    servo.sequence = 3U;
    assert(ainekio_core_accept(&core, &servo).accepted);
    assert(ainekio_command_lifecycle(&servo) == AINEKIO_LIFECYCLE_ACK_ONLY);

    ainekio_command_t face = intent_command(4U, AINEKIO_INTENT_FACE);
    assert(ainekio_command_lifecycle(&face) == AINEKIO_LIFECYCLE_ACK_THEN_DONE);
}

static void test_sequence_can_be_claimed_without_executing_a_command(void)
{
    ainekio_core_t core;
    ainekio_core_init(&core);
    ainekio_core_begin_session(&core, 4U);

    assert(ainekio_core_claim_sequence(&core, 8U) == AINEKIO_REJECT_NONE);
    assert(core.highest_sequence == 8U);
    assert(core.state == AINEKIO_STATE_ACTIVE);
    assert(!core.servos_attached);

    ainekio_command_t stand = intent_command(8U, AINEKIO_INTENT_STAND);
    assert(ainekio_core_accept(&core, &stand).rejection == AINEKIO_REJECT_STALE);
    assert(ainekio_core_claim_sequence(&core, 0U) == AINEKIO_REJECT_MALFORMED);
}

int main(void)
{
    test_initial_state_is_safe();
    test_stop_detaches_until_next_movement();
    test_session_boundary_detaches_servos();
    test_failsafe_detaches_servos();
    test_sequence_and_safety_gates();
    test_calibration_gate_and_lifecycle();
    test_sequence_can_be_claimed_without_executing_a_command();
    puts("ainekio core tests passed");
    return 0;
}
