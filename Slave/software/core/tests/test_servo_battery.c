#include <assert.h>
#include <stdio.h>

#include "ainekio/battery.h"
#include "ainekio/servo.h"

static bool close_enough(float actual, float expected)
{
    const float difference = actual > expected ? actual - expected : expected - actual;
    return difference < 0.001F;
}

static void fill_samples(float *samples, float value)
{
    for (size_t index = 0U; index < AINEKIO_BATTERY_MIN_SAMPLES; ++index) {
        samples[index] = value;
    }
}

static void test_servo_mapping_and_interpolation(void)
{
    ainekio_servo_bank_t bank;
    ainekio_servo_bank_init(&bank);
    const ainekio_servo_calibration_t calibration = {
        .minimum_degrees = 20.0F,
        .center_degrees = 95.0F,
        .maximum_degrees = 160.0F,
        .invert = true,
    };
    assert(ainekio_servo_set_calibration(&bank, AINEKIO_JOINT_R1, &calibration) ==
           AINEKIO_SERVO_OK);

    float physical = 0.0F;
    assert(ainekio_servo_map_logical(&calibration, 90.0F, &physical) ==
           AINEKIO_SERVO_OK);
    assert(close_enough(physical, 95.0F));
    assert(ainekio_servo_map_logical(&calibration, 45.0F, &physical) ==
           AINEKIO_SERVO_OK);
    assert(close_enough(physical, 140.0F));
    assert(ainekio_servo_map_logical(&calibration, 10.0F, &physical) ==
           AINEKIO_SERVO_LIMIT);

    assert(ainekio_servo_move_logical(&bank, AINEKIO_JOINT_R1, 45.0F, 100U) ==
           AINEKIO_SERVO_OK);
    assert(bank.channels[AINEKIO_JOINT_R1].attached);
    assert(bank.channels[AINEKIO_JOINT_R1].remaining_ticks == 5U);
    ainekio_servo_tick(&bank);
    assert(close_enough(bank.channels[AINEKIO_JOINT_R1].current_degrees, 104.0F));
    for (unsigned int tick = 0U; tick < 4U; ++tick) {
        ainekio_servo_tick(&bank);
    }
    assert(close_enough(bank.channels[AINEKIO_JOINT_R1].current_degrees, 140.0F));
    assert(ainekio_servo_degrees_to_pulse(0.0F) == 500U);
    assert(ainekio_servo_degrees_to_pulse(90.0F) == 1500U);
    assert(ainekio_servo_degrees_to_pulse(180.0F) == 2500U);

    ainekio_servo_detach_all(&bank);
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        assert(!bank.channels[joint_id].attached);
    }
}

static void test_battery_debounce_recovery_and_quiet_window(void)
{
    ainekio_battery_monitor_t monitor;
    ainekio_battery_init(&monitor, 1.0F);
    float samples[AINEKIO_BATTERY_MIN_SAMPLES];

    assert(ainekio_battery_sample_due(&monitor, 0U));
    fill_samples(samples, 6.95F);
    assert(ainekio_battery_observe(&monitor, samples, 15U, 0U) ==
           AINEKIO_BATTERY_EVENT_NONE);
    for (uint32_t reading = 0U; reading < 2U; ++reading) {
        assert(ainekio_battery_observe(&monitor, samples, 16U, reading * 5000U) ==
               AINEKIO_BATTERY_EVENT_NONE);
    }
    assert(ainekio_battery_observe(&monitor, samples, 16U, 10000U) ==
           AINEKIO_BATTERY_EVENT_WARN);
    assert(monitor.state == AINEKIO_BATTERY_WARN);
    assert(!ainekio_battery_sample_due(&monitor, 14999U));
    assert(ainekio_battery_sample_due(&monitor, 15000U));

    fill_samples(samples, 6.7F);
    for (uint32_t reading = 0U; reading < 2U; ++reading) {
        assert(ainekio_battery_observe(&monitor, samples, 16U, 15000U + reading) ==
               AINEKIO_BATTERY_EVENT_NONE);
    }
    assert(ainekio_battery_observe(&monitor, samples, 16U, 15002U) ==
           AINEKIO_BATTERY_EVENT_CUTOFF);
    assert(monitor.state == AINEKIO_BATTERY_CUTOFF);

    fill_samples(samples, 7.21F);
    for (uint32_t reading = 0U; reading < 2U; ++reading) {
        assert(ainekio_battery_observe(&monitor, samples, 16U, 20000U + reading) ==
               AINEKIO_BATTERY_EVENT_NONE);
    }
    assert(ainekio_battery_observe(&monitor, samples, 16U, 20002U) ==
           AINEKIO_BATTERY_EVENT_RECOVERED);
    assert(monitor.state == AINEKIO_BATTERY_NORMAL);
}

static void test_startup_disconnected_battery_and_presence_latch(void)
{
    ainekio_battery_monitor_t monitor;
    ainekio_battery_init(&monitor, 1.0F);
    float samples[AINEKIO_BATTERY_MIN_SAMPLES];

    fill_samples(samples, 0.0F);
    for (uint32_t reading = 0U;
         reading < AINEKIO_BATTERY_QUALIFYING_SETS - 1U;
         ++reading) {
        assert(ainekio_battery_observe(&monitor, samples, 16U, reading * 5000U) ==
               AINEKIO_BATTERY_EVENT_NONE);
        assert(monitor.state == AINEKIO_BATTERY_NORMAL);
    }
    assert(ainekio_battery_observe(&monitor, samples, 16U, 10000U) ==
           AINEKIO_BATTERY_EVENT_NONE);
    assert(monitor.state == AINEKIO_BATTERY_DISCONNECTED);
    assert(!monitor.present_latched);

    fill_samples(samples, 7.4F);
    assert(ainekio_battery_observe(&monitor, samples, 16U, 15000U) ==
           AINEKIO_BATTERY_EVENT_NONE);
    assert(monitor.state == AINEKIO_BATTERY_NORMAL);
    assert(monitor.present_latched);

    fill_samples(samples, 0.0F);
    for (uint32_t reading = 0U;
         reading < AINEKIO_BATTERY_QUALIFYING_SETS - 1U;
         ++reading) {
        assert(ainekio_battery_observe(
                   &monitor,
                   samples,
                   16U,
                   20000U + reading * 5000U
               ) == AINEKIO_BATTERY_EVENT_NONE);
        assert(monitor.state == AINEKIO_BATTERY_NORMAL);
    }
    assert(ainekio_battery_observe(&monitor, samples, 16U, 30000U) ==
           AINEKIO_BATTERY_EVENT_CUTOFF);
    assert(monitor.state == AINEKIO_BATTERY_CUTOFF);
}

int main(void)
{
    test_servo_mapping_and_interpolation();
    test_battery_debounce_recovery_and_quiet_window();
    test_startup_disconnected_battery_and_presence_latch();
    puts("ainekio servo and battery tests passed");
    return 0;
}
