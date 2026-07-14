#ifndef AINEKIO_PLATFORM_TELEMETRY_SERVICE_H
#define AINEKIO_PLATFORM_TELEMETRY_SERVICE_H

#include "ainekio/battery.h"
#include "ainekio/platform/battery_adc.h"
#include "ainekio/platform/motion_service.h"
#include "esp_err.h"

typedef struct ainekio_telemetry_service ainekio_telemetry_service_t;

typedef void (*ainekio_battery_observation_fn)(
    void *context,
    float volts,
    ainekio_battery_state_t state,
    ainekio_battery_events_t events
);

typedef struct {
    void *context;
    ainekio_battery_observation_fn battery;
} ainekio_telemetry_callbacks_t;

esp_err_t ainekio_telemetry_service_start(
    float divider_factor,
    float calibration_factor,
    ainekio_motion_service_t *motion,
    const ainekio_telemetry_callbacks_t *callbacks,
    ainekio_telemetry_service_t **service
);

#endif
