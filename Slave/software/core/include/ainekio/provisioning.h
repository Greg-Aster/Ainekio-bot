#ifndef AINEKIO_PROVISIONING_H
#define AINEKIO_PROVISIONING_H

#include <stdbool.h>
#include <stdint.h>

#define AINEKIO_WIFI_CONNECT_TIMEOUT_MS UINT64_C(60000)
#define AINEKIO_SETUP_AP_ON_MS UINT64_C(600000)
#define AINEKIO_SETUP_AP_OFF_MS UINT64_C(60000)

typedef enum {
    AINEKIO_CONFIG_STATUS_VALID = 0,
    AINEKIO_CONFIG_STATUS_MIGRATED,
    AINEKIO_CONFIG_STATUS_MISSING,
    AINEKIO_CONFIG_STATUS_CORRUPT,
} ainekio_config_status_t;

typedef enum {
    AINEKIO_PROVISION_STATE_CONNECTING = 0,
    AINEKIO_PROVISION_STATE_ONLINE,
    AINEKIO_PROVISION_STATE_MANUAL_AP,
    AINEKIO_PROVISION_STATE_AUTOMATIC_AP,
    AINEKIO_PROVISION_STATE_AUTOMATIC_RETRY,
    AINEKIO_PROVISION_STATE_VALIDATING_STAGED,
    AINEKIO_PROVISION_STATE_COMMITTING_STAGED,
} ainekio_provision_state_t;

typedef enum {
    AINEKIO_PROVISION_REASON_NONE = 0,
    AINEKIO_PROVISION_REASON_NO_CONFIG,
    AINEKIO_PROVISION_REASON_NVS_CORRUPT,
    AINEKIO_PROVISION_REASON_WIFI_TIMEOUT,
    AINEKIO_PROVISION_REASON_DASHBOARD_REQUEST,
    AINEKIO_PROVISION_REASON_BOOT_BUTTON,
    AINEKIO_PROVISION_REASON_NETWORK_RESET,
} ainekio_provision_reason_t;

typedef enum {
    AINEKIO_PROVISION_SESSION_NONE = 0,
    AINEKIO_PROVISION_SESSION_MANUAL,
    AINEKIO_PROVISION_SESSION_AUTOMATIC,
} ainekio_provision_session_t;

typedef uint32_t ainekio_provision_actions_t;

enum {
    AINEKIO_PROVISION_ACTION_NONE = 0U,
    AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI = 1U << 0,
    AINEKIO_PROVISION_ACTION_START_SETUP_AP = 1U << 1,
    AINEKIO_PROVISION_ACTION_STOP_SETUP_AP = 1U << 2,
    AINEKIO_PROVISION_ACTION_CONNECT_STAGED_WIFI = 1U << 3,
    AINEKIO_PROVISION_ACTION_COMMIT_STAGED_CONFIG = 1U << 4,
    AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG = 1U << 5,
    AINEKIO_PROVISION_ACTION_CLEAR_ACTIVE_WIFI = 1U << 6,
    AINEKIO_PROVISION_ACTION_GENERATE_SETUP_SECRET = 1U << 7,
    AINEKIO_PROVISION_ACTION_SHOW_CONNECTING = 1U << 8,
    AINEKIO_PROVISION_ACTION_SHOW_WIFI_UNAVAILABLE = 1U << 9,
    AINEKIO_PROVISION_ACTION_SHOW_SETUP = 1U << 10,
    AINEKIO_PROVISION_ACTION_SHOW_CONNECTED = 1U << 11,
    AINEKIO_PROVISION_ACTION_PLAY_SETUP_CUE = 1U << 12,
    AINEKIO_PROVISION_ACTION_PLAY_CONNECTED_CUE = 1U << 13,
    AINEKIO_PROVISION_ACTION_SHOW_GATEWAY_AUTH_FAILED = 1U << 14,
};

typedef struct {
    ainekio_provision_state_t state;
    ainekio_provision_reason_t reason;
    ainekio_provision_session_t session;
    uint64_t state_started_ms;
    uint64_t session_started_ms;
    ainekio_provision_actions_t pending_actions;
    bool has_active_wifi;
    bool setup_ap_running;
    bool has_staged_config;
} ainekio_provisioning_t;

void ainekio_provisioning_init(
    ainekio_provisioning_t *machine,
    ainekio_config_status_t config_status,
    uint64_t now_ms
);
void ainekio_provisioning_tick(ainekio_provisioning_t *machine, uint64_t now_ms);
void ainekio_provisioning_on_wifi_lost(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
);
void ainekio_provisioning_on_active_wifi_ip(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
);
void ainekio_provisioning_request_manual(
    ainekio_provisioning_t *machine,
    ainekio_provision_reason_t reason,
    uint64_t now_ms
);
void ainekio_provisioning_request_network_reset(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
);

/* Call only after the submitted replacement has been staged successfully. */
bool ainekio_provisioning_begin_staged_validation(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
);
void ainekio_provisioning_on_staged_wifi_ip(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
);
void ainekio_provisioning_on_staged_validation_failure(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
);
void ainekio_provisioning_on_staged_commit_result(
    ainekio_provisioning_t *machine,
    bool committed,
    uint64_t now_ms
);

/* Gateway transport failure intentionally has no provisioning transition. */
void ainekio_provisioning_on_gateway_failure(ainekio_provisioning_t *machine);
void ainekio_provisioning_on_gateway_auth_failure(
    ainekio_provisioning_t *machine
);

ainekio_provision_actions_t ainekio_provisioning_take_actions(
    ainekio_provisioning_t *machine
);

#endif
