#include "ainekio/admission.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static ainekio_control_message_t decode(const char *text)
{
    ainekio_control_message_t message;
    assert(ainekio_control_decode_for_body(text, strlen(text), &message) == AINEKIO_DECODE_OK);
    return message;
}

static uint64_t connect(ainekio_admission_t *a, uint32_t epoch, uint64_t now)
{
    uint64_t generation = ainekio_admission_open(a);
    assert(ainekio_admission_welcome(a, generation, epoch, AINEKIO_PROFILE_HOME, true, now));
    return generation;
}

static void test_authentication_and_replacement(void)
{
    ainekio_admission_t a;
    ainekio_admission_init(&a, UINT32_MAX, true);
    ainekio_control_message_t m = decode("{\"t\":\"mode\",\"name\":\"calibrate\",\"seq\":1,\"epoch\":1,\"deadline_ms\":900}");
    uint64_t first = ainekio_admission_open(&a);
    assert(!ainekio_admission_accept(&a, first, &m, 100, 200, true).accepted);
    assert(!ainekio_admission_welcome(&a, first, 1, AINEKIO_PROFILE_HOME, false, 100));
    assert(ainekio_admission_welcome(&a, first, 1, AINEKIO_PROFILE_HOME, true, 100));
    assert(!ainekio_admission_welcome(&a, first, 1, AINEKIO_PROFILE_HOME, true, 100));
    assert(ainekio_admission_accept(&a, first, &m, 100, 200, true).accepted);
    ainekio_admission_close(&a, first);
    /* Another host may restart its own epoch counter. Local connection identity
     * still rejects old work, even when its epoch and sequence look current. */
    uint64_t next = connect(&a, 1, 300);
    assert(next != first && a.core.mode == AINEKIO_MODE_NORMAL);
    ainekio_admission_close(&a, first); /* Late disconnect cannot close successor. */
    assert(a.connected);
    assert(!ainekio_admission_accept(&a, first, &m, 100, 400, true).accepted);
    assert(ainekio_admission_accept(&a, next, &m, 300, 400, true).accepted);
}

static void test_deadline_queue_sequence_and_stop(void)
{
    ainekio_admission_t a;
    ainekio_admission_init(&a, UINT32_MAX, true);
    const uint64_t g = connect(&a, 9, 0);
    ainekio_control_message_t m = decode("{\"t\":\"mode\",\"name\":\"calibrate\",\"seq\":1,\"epoch\":9,\"deadline_ms\":20}");
    assert(ainekio_admission_accept(&a, g, &m, 1000, 19999, true).accepted);
    m.sequence = m.command.sequence = 2;
    assert(ainekio_admission_accept(&a, g, &m, 1000, 20000, true).rejection == AINEKIO_REJECT_STALE);
    m.deadline_ms = 99999;
    assert(!ainekio_admission_accept(&a, g, &m, 1000, 20001, true).accepted); /* Consumed expired seq. */
    m.sequence = m.command.sequence = 3;
    assert(!ainekio_admission_accept(&a, g, &m, 1, 1000001, true).accepted);
    m.sequence = m.command.sequence = 4;
    m.has_deadline = false;
    assert(!ainekio_admission_accept(&a, g, &m, 1, 20000, true).accepted);
    m = decode("{\"t\":\"stop\",\"seq\":5,\"detach\":true,\"epoch\":9,\"deadline_ms\":0}");
    assert(ainekio_admission_accept(&a, g, &m, 0, 3000000, true).accepted);
    assert(a.core.stop_latched && !a.core.servos_attached);
    m.epoch = 8;
    assert(!ainekio_admission_accept(&a, g, &m, 0, 3000001, true).accepted);
}

static void test_target_policy_and_fault_liveness(void)
{
    ainekio_admission_t a;
    ainekio_admission_init(&a, AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_BODY_CALIBRATION) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MODE), true);
    const uint64_t g = connect(&a, 1, 0);
    ainekio_control_message_t m = decode("{\"t\":\"calibration\",\"seq\":1,\"op\":\"move\",\"id\":11,\"pulse_us\":1500,\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).rejection == AINEKIO_REJECT_MODE);
    m = decode("{\"t\":\"mode\",\"seq\":2,\"name\":\"calibrate\",\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 2, 3, true).accepted);
    m = decode("{\"t\":\"servo\",\"seq\":3,\"id\":0,\"deg\":90,\"ms\":100,\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 2, 3, true).rejection == AINEKIO_REJECT_UNKNOWN);
    assert(!ainekio_admission_check_stale(&a, 3999999));
    assert(ainekio_admission_check_stale(&a, 4000000));
    assert(a.connected && a.authenticated && a.generation == g);
    assert(a.core.state == AINEKIO_STATE_FAILSAFE && a.core.stop_latched);
    assert(!ainekio_admission_accept(&a, g, &m, 4000001, 4000002, true).accepted);
    assert(ainekio_admission_control(&a, g, 4000003));
    assert(!a.stale && a.core.stop_latched && a.core.state == AINEKIO_STATE_FAILSAFE);
    assert(a.core.epoch == 1 && a.core.highest_sequence == 3);
    m = decode("{\"t\":\"calibration\",\"seq\":4,\"op\":\"get\",\"epoch\":1,\"deadline_ms\":5000}");
    assert(ainekio_admission_accept(&a, g, &m, 4000003, 4000004, true).accepted);
    assert(a.core.stop_latched); /* Readback and heartbeats do not resume motion. */
    const uint64_t next = connect(&a, 2, 5000000);
    /* A late frame still detects the timeout if it beats the supervisor. */
    assert(!ainekio_admission_control(&a, next, 9000000));
    assert(a.stale);
    assert(a.connected && a.authenticated && a.generation == next && a.core.stop_latched);
    assert(ainekio_admission_control(&a, next, 9000001));
    assert(!a.stale && a.core.stop_latched);
    assert(!ainekio_admission_control(&a, g, 9000002)); /* Superseded source stays fenced. */
}

static void test_decoder_negotiation_and_bounds(void)
{
    const char *valid = "{\"t\":\"calibration\",\"seq\":1,\"op\":\"set\",\"id\":11,\"channel\":11,\"home_us\":1505,\"invert\":true}";
    ainekio_control_message_t m;
    assert(ainekio_control_decode(valid, strlen(valid), &m) != AINEKIO_DECODE_OK); /* V1 opt-out. */
    m = decode(valid);
    assert(m.command.data.calibration.id == 11 && m.command.data.calibration.invert);
    assert(m.command.data.calibration.home_us == 1505);
    assert(!m.command.data.calibration.has_mapping);
    m = decode("{\"t\":\"calibration\",\"seq\":1,\"op\":\"set\",\"id\":11,\"channel\":11,\"home_us\":1505,\"invert\":true,\"home_cd\":-8352,\"us_per_degree\":11.111111}");
    assert(m.command.data.calibration.has_mapping);
    assert(m.command.data.calibration.home_cd == -8352);
    assert(m.command.data.calibration.us_per_degree > 11.11f && m.command.data.calibration.us_per_degree < 11.12f);
    /* Transport widths do not prescribe servo travel. The body owns hardware validation. */
    const unsigned pulses[] = {1, 499, 2501, 3000, UINT16_MAX};
    for (size_t i = 0; i < sizeof(pulses) / sizeof(pulses[0]); ++i) {
        char json[128];
        snprintf(json, sizeof(json), "{\"t\":\"calibration\",\"seq\":1,\"op\":\"move\",\"id\":11,\"pulse_us\":%u}", pulses[i]);
        m = decode(json);
        assert(m.command.data.calibration.pulse_us == pulses[i]);
        assert(ainekio_control_decode(json, strlen(json), &m) != AINEKIO_DECODE_OK); /* V1 remains opt-out. */
    }
    m = decode("{\"t\":\"calibration\",\"seq\":1,\"op\":\"set\",\"id\":11,\"channel\":11,\"home_us\":3000,\"invert\":false}");
    assert(m.command.data.calibration.home_us == 3000);
    const char *invalid[] = {
        "{\"t\":\"calibration\",\"seq\":1,\"op\":\"move\",\"id\":12,\"pulse_us\":1500}",
        "{\"t\":\"calibration\",\"seq\":1,\"op\":\"move\",\"id\":0,\"pulse_us\":0}",
        "{\"t\":\"calibration\",\"seq\":1,\"op\":\"move\",\"id\":0,\"pulse_us\":65536}",
        "{\"t\":\"calibration\",\"seq\":1,\"op\":\"get\",\"id\":1}",
        "{\"t\":\"calibration\",\"seq\":1,\"op\":\"set\",\"id\":11,\"channel\":11,\"home_us\":0,\"invert\":true}",
        "{\"t\":\"calibration\",\"seq\":1,\"op\":\"set\",\"id\":11,\"channel\":11,\"home_us\":65536,\"invert\":true}",
        "{\"t\":\"mode\",\"seq\":1,\"name\":\"calibrate\",\"epoch\":-1}",
        "{\"t\":\"mode\",\"seq\":1,\"name\":\"calibrate\",\"deadline_ms\":true}",
        "{\"t\":\"mode\",\"seq\":1,\"seq\":2,\"name\":\"calibrate\"}",
    };
    for (size_t i=0; i<sizeof(invalid)/sizeof(invalid[0]); ++i)
        assert(ainekio_control_decode_for_body(invalid[i], strlen(invalid[i]), &m) != AINEKIO_DECODE_OK);
}

static void test_calibration_read_and_power_gates(void)
{
    ainekio_admission_t a;
    ainekio_admission_init(&a, UINT32_MAX, true);
    const uint64_t g = connect(&a, 1, 0);
    ainekio_control_message_t m = decode("{\"t\":\"calibration\",\"seq\":1,\"op\":\"get\",\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).accepted);
    m = decode("{\"t\":\"calibration\",\"seq\":2,\"op\":\"move\",\"id\":11,\"pulse_us\":1505,\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).rejection == AINEKIO_REJECT_MODE);
    ainekio_core_set_mode(&a.core, AINEKIO_MODE_CALIBRATE);
    m.sequence = m.command.sequence = 3;
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).rejection == AINEKIO_REJECT_BUSY);
    ainekio_core_set_boot_ready(&a.core, true);
    m.sequence = m.command.sequence = 4;
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).accepted);
    ainekio_core_set_power_guard(&a.core, AINEKIO_POWER_MOVE_LOCKED);
    m.sequence = m.command.sequence = 5;
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).rejection == AINEKIO_REJECT_UNSAFE);
    m = decode("{\"t\":\"calibration\",\"seq\":6,\"op\":\"home\",\"epoch\":1,\"deadline_ms\":1000}");
    assert(m.command.data.calibration.id == -1);
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).rejection == AINEKIO_REJECT_UNSAFE);
}

static void test_storage_extension(void)
{
    const char *json = "{\"t\":\"storage\",\"op\":\"retry\",\"seq\":1,\"epoch\":1,\"deadline_ms\":1000}";
    ainekio_control_message_t m;
    assert(ainekio_control_decode(json, strlen(json), &m) == AINEKIO_DECODE_VALUE);
    m = decode(json);
    assert(m.command.kind == AINEKIO_COMMAND_STORAGE);
    assert(m.command.data.storage_operation == AINEKIO_STORAGE_RETRY);
    ainekio_admission_t a;
    ainekio_admission_init(&a, AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STORAGE), true);
    const uint64_t generation = connect(&a, 1, 0);
    assert(ainekio_admission_accept(&a, generation, &m, 1, 2, true).accepted);
    const char *invalid = "{\"t\":\"storage\",\"op\":\"format\",\"seq\":1}";
    assert(ainekio_control_decode_for_body(invalid, strlen(invalid), &m) != AINEKIO_DECODE_OK);
}

static void test_model_policy_preserves_session_and_sequence(void)
{
    ainekio_admission_t a;
    ainekio_admission_init(&a, UINT32_MAX, true);
    const uint64_t generation = connect(&a, 7, 0);
    ainekio_control_message_t m = decode("{\"t\":\"intent\",\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":3,\"seq\":1,\"epoch\":7,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, generation, &m, 1, 2, false).rejection == AINEKIO_REJECT_UNKNOWN);
    assert(ainekio_admission_accept(&a, generation, &m, 1, 2, true).rejection == AINEKIO_REJECT_STALE);
    m.sequence = m.command.sequence = 2;
    /* Installed geometry never establishes actuator readiness. */
    assert(ainekio_admission_accept(&a, generation, &m, 1, 2, true).rejection == AINEKIO_REJECT_BUSY);
    ainekio_core_set_boot_ready(&a.core,true);
    m.sequence = m.command.sequence = 3;
    assert(ainekio_admission_accept(&a, generation, &m, 1, 2, true).accepted);
    ainekio_admission_close(&a,generation);
    assert(ainekio_admission_accept(&a, generation, &m, 1, 2, false).rejection == AINEKIO_REJECT_STALE);
}

int main(void)
{
    test_authentication_and_replacement();
    test_deadline_queue_sequence_and_stop();
    test_target_policy_and_fault_liveness();
    test_decoder_negotiation_and_bounds();
    test_model_policy_preserves_session_and_sequence();
    test_calibration_read_and_power_gates();
    test_storage_extension();
    puts("Admission: authentication, replacement, deadlines, sequencing, policy and decoder tests passed");
    return 0;
}
