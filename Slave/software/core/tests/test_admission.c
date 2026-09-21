#include "ainekio/admission.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static ainekio_control_message_t decode(const char *text)
{
    ainekio_control_message_t message;
    assert(ainekio_control_decode_with_output_tests(text, strlen(text), &message) == AINEKIO_DECODE_OK);
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
    ainekio_admission_init(&a, AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_OUTPUT_TEST) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MODE), true);
    const uint64_t g = connect(&a, 1, 0);
    ainekio_control_message_t m = decode("{\"t\":\"output_test\",\"seq\":1,\"op\":\"run\",\"channel\":11,\"pulse_us\":1500,\"ms\":100,\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 1, 2, true).rejection == AINEKIO_REJECT_MODE);
    m = decode("{\"t\":\"mode\",\"seq\":2,\"name\":\"calibrate\",\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 2, 3, true).accepted);
    m = decode("{\"t\":\"servo\",\"seq\":3,\"id\":0,\"deg\":90,\"ms\":100,\"epoch\":1,\"deadline_ms\":1000}");
    assert(ainekio_admission_accept(&a, g, &m, 2, 3, true).rejection == AINEKIO_REJECT_UNKNOWN);
    assert(!ainekio_admission_check_stale(&a, 3999999));
    assert(ainekio_admission_check_stale(&a, 4000000));
    assert(!ainekio_admission_control(&a, g, 4000001));
    assert(!ainekio_admission_accept(&a, g, &m, 4000001, 4000002, true).accepted);
    const uint64_t next = connect(&a, 2, 5000000);
    /* A late heartbeat cannot win a race with the periodic supervisor. */
    assert(!ainekio_admission_control(&a, next, 9000000));
    assert(a.stale);
    assert(!ainekio_admission_control(&a, next, 9000001));
}

static void test_decoder_negotiation_and_bounds(void)
{
    const char *valid = "{\"t\":\"output_test\",\"seq\":1,\"op\":\"run\",\"channel\":11,\"pulse_us\":2000,\"ms\":2000,\"fault\":\"interrupt_arm\"}";
    ainekio_control_message_t m;
    assert(ainekio_control_decode(valid, strlen(valid), &m) != AINEKIO_DECODE_OK); /* V1 opt-out. */
    m = decode(valid);
    assert(m.command.data.output_test.channel == 11 && m.command.data.output_test.fault == 2);
    const char *invalid[] = {
        "{\"t\":\"output_test\",\"seq\":1,\"op\":\"run\",\"channel\":12,\"pulse_us\":1500,\"ms\":100}",
        "{\"t\":\"output_test\",\"seq\":1,\"op\":\"run\",\"channel\":0,\"pulse_us\":999,\"ms\":100}",
        "{\"t\":\"output_test\",\"seq\":1,\"op\":\"run\",\"channel\":0,\"pulse_us\":1500,\"ms\":2001}",
        "{\"t\":\"mode\",\"seq\":1,\"name\":\"calibrate\",\"epoch\":-1}",
        "{\"t\":\"mode\",\"seq\":1,\"name\":\"calibrate\",\"deadline_ms\":true}",
        "{\"t\":\"mode\",\"seq\":1,\"seq\":2,\"name\":\"calibrate\"}",
    };
    for (size_t i=0; i<sizeof(invalid)/sizeof(invalid[0]); ++i)
        assert(ainekio_control_decode_with_output_tests(invalid[i], strlen(invalid[i]), &m) != AINEKIO_DECODE_OK);
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
    puts("Admission: authentication, replacement, deadlines, sequencing, policy and decoder tests passed");
    return 0;
}
