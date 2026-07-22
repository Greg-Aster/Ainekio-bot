#ifndef AINEKIO_BATTERY_H
#define AINEKIO_BATTERY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_BATTERY_MIN_SAMPLES 16U
#define AINEKIO_BATTERY_WARN_VOLTS 7.0F
#define AINEKIO_BATTERY_CUTOFF_VOLTS 6.8F
#define AINEKIO_BATTERY_RECOVERY_VOLTS 7.2F
#define AINEKIO_BATTERY_DISCONNECTED_MAX_VOLTS 0.25F
#define AINEKIO_BATTERY_QUALIFYING_SETS 3U
#define AINEKIO_BATTERY_SAMPLE_INTERVAL_MS UINT32_C(5000)

typedef enum {
    AINEKIO_BATTERY_NORMAL = 0,
    AINEKIO_BATTERY_WARN,
    AINEKIO_BATTERY_CUTOFF,
    AINEKIO_BATTERY_DISCONNECTED,
} ainekio_battery_state_t;

typedef uint32_t ainekio_battery_events_t;
enum {
    AINEKIO_BATTERY_EVENT_NONE = 0U,
    AINEKIO_BATTERY_EVENT_WARN = 1U << 0,
    AINEKIO_BATTERY_EVENT_CUTOFF = 1U << 1,
    AINEKIO_BATTERY_EVENT_RECOVERED = 1U << 2,
};

typedef struct {
    ainekio_battery_state_t state;
    float calibration_factor;
    float volts;
    uint8_t warn_sets;
    uint8_t cutoff_sets;
    uint8_t recovery_sets;
    uint8_t disconnected_sets;
    uint32_t last_sample_ms;
    bool has_sample_time;
    bool present_latched;
} ainekio_battery_monitor_t;

void ainekio_battery_init(ainekio_battery_monitor_t *monitor, float calibration_factor);
bool ainekio_battery_sample_due(
    const ainekio_battery_monitor_t *monitor,
    uint32_t now_ms
);
ainekio_battery_events_t ainekio_battery_observe(
    ainekio_battery_monitor_t *monitor,
    const float *voltage_samples,
    size_t sample_count,
    uint32_t now_ms
);

#endif
