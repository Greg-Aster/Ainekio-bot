#include "ainekio/battery.h"

#include <math.h>
#include <string.h>

static uint8_t qualified_count(uint8_t current, bool qualifies)
{
    if (!qualifies) {
        return 0U;
    }
    return current < AINEKIO_BATTERY_QUALIFYING_SETS ? (uint8_t)(current + 1U)
                                                      : current;
}

void ainekio_battery_init(ainekio_battery_monitor_t *monitor, float calibration_factor)
{
    memset(monitor, 0, sizeof(*monitor));
    monitor->state = AINEKIO_BATTERY_NORMAL;
    monitor->calibration_factor =
        isfinite(calibration_factor) && calibration_factor > 0.0F
            ? calibration_factor
            : 1.0F;
    monitor->volts = AINEKIO_BATTERY_RECOVERY_VOLTS;
}

bool ainekio_battery_sample_due(
    const ainekio_battery_monitor_t *monitor,
    uint32_t now_ms
)
{
    return !monitor->has_sample_time ||
           (uint32_t)(now_ms - monitor->last_sample_ms) >=
               AINEKIO_BATTERY_SAMPLE_INTERVAL_MS;
}

ainekio_battery_events_t ainekio_battery_observe(
    ainekio_battery_monitor_t *monitor,
    const float *voltage_samples,
    size_t sample_count,
    uint32_t now_ms
)
{
    if (monitor == NULL || voltage_samples == NULL ||
        sample_count < AINEKIO_BATTERY_MIN_SAMPLES) {
        return AINEKIO_BATTERY_EVENT_NONE;
    }
    float sum = 0.0F;
    for (size_t index = 0U; index < sample_count; ++index) {
        if (!isfinite(voltage_samples[index]) || voltage_samples[index] < 0.0F) {
            return AINEKIO_BATTERY_EVENT_NONE;
        }
        sum += voltage_samples[index];
    }
    monitor->volts = (sum / (float)sample_count) * monitor->calibration_factor;
    monitor->last_sample_ms = now_ms;
    monitor->has_sample_time = true;

    /* A controller powered from USB can legitimately have no battery-divider
     * input. Only classify near-zero as disconnected before a plausible
     * battery has ever been observed; a later near-zero reading remains a
     * cutoff-worthy wiring or power fault. */
    if (!monitor->present_latched &&
        monitor->state != AINEKIO_BATTERY_CUTOFF) {
        if (monitor->volts <= AINEKIO_BATTERY_DISCONNECTED_MAX_VOLTS) {
            monitor->disconnected_sets = qualified_count(
                monitor->disconnected_sets,
                true
            );
            monitor->warn_sets = 0U;
            monitor->cutoff_sets = 0U;
            monitor->recovery_sets = 0U;
            if (monitor->disconnected_sets >=
                AINEKIO_BATTERY_QUALIFYING_SETS) {
                monitor->state = AINEKIO_BATTERY_DISCONNECTED;
            }
            return AINEKIO_BATTERY_EVENT_NONE;
        }
        monitor->present_latched = true;
        monitor->disconnected_sets = 0U;
        if (monitor->state == AINEKIO_BATTERY_DISCONNECTED) {
            monitor->state = AINEKIO_BATTERY_NORMAL;
        }
    }

    if (monitor->state == AINEKIO_BATTERY_CUTOFF) {
        monitor->recovery_sets = qualified_count(
            monitor->recovery_sets,
            monitor->volts >= AINEKIO_BATTERY_RECOVERY_VOLTS
        );
        if (monitor->recovery_sets >= AINEKIO_BATTERY_QUALIFYING_SETS) {
            monitor->state = AINEKIO_BATTERY_NORMAL;
            monitor->warn_sets = 0U;
            monitor->cutoff_sets = 0U;
            monitor->recovery_sets = 0U;
            monitor->disconnected_sets = 0U;
            monitor->present_latched = true;
            return AINEKIO_BATTERY_EVENT_RECOVERED;
        }
        return AINEKIO_BATTERY_EVENT_NONE;
    }

    monitor->cutoff_sets = qualified_count(
        monitor->cutoff_sets,
        monitor->volts < AINEKIO_BATTERY_CUTOFF_VOLTS
    );
    if (monitor->cutoff_sets >= AINEKIO_BATTERY_QUALIFYING_SETS) {
        monitor->state = AINEKIO_BATTERY_CUTOFF;
        monitor->warn_sets = 0U;
        monitor->recovery_sets = 0U;
        return AINEKIO_BATTERY_EVENT_CUTOFF;
    }

    monitor->warn_sets = qualified_count(
        monitor->warn_sets,
        monitor->volts < AINEKIO_BATTERY_WARN_VOLTS
    );
    if (monitor->state == AINEKIO_BATTERY_NORMAL &&
        monitor->warn_sets >= AINEKIO_BATTERY_QUALIFYING_SETS) {
        monitor->state = AINEKIO_BATTERY_WARN;
        return AINEKIO_BATTERY_EVENT_WARN;
    }
    if (monitor->state == AINEKIO_BATTERY_WARN &&
        monitor->volts >= AINEKIO_BATTERY_WARN_VOLTS) {
        monitor->state = AINEKIO_BATTERY_NORMAL;
        monitor->warn_sets = 0U;
    }
    return AINEKIO_BATTERY_EVENT_NONE;
}
