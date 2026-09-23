#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "ainekio/protocol.h"
#include "esp_err.h"

typedef struct {
    ainekio_profile_t profile;
    ainekio_body_state_t state;
    uint64_t uptime_ms;
    uint32_t heap_free;
    uint32_t heap_minimum;
    int reset_reason;
    bool battery_available;
    bool ota_layout;
    bool ota_pending;
    bool restart_pending;
} ainekio_p4_system_status_t;

esp_err_t ainekio_p4_system_start(void);
ainekio_p4_system_status_t ainekio_p4_system_status(void);
esp_err_t ainekio_p4_system_profile(ainekio_profile_t profile);
/* IDLE resumes media availability but never arms outputs. DOZE disables
 * outputs/media; SLEEP prepares synchronously, then powers down after ACK grace.
 * Failed preparation leaves the controller connected and outputs disabled. */
esp_err_t ainekio_p4_system_state(ainekio_state_request_t state, uint32_t seconds);
/* Called only after a validated gateway welcome. Factory images are a no-op. */
esp_err_t ainekio_p4_system_authenticated(void);
/* Persist first, then prepare synchronously. ESP_OK gives callers 250 ms to
 * send a reply before restart; a failure leaves the controller connected. */
esp_err_t ainekio_p4_system_restart(void);
int ainekio_p4_system_command(int argc, char **argv);
