#include "ainekio/provisioning.h"

#include <string.h>

static bool elapsed(uint64_t now_ms, uint64_t started_ms, uint64_t duration_ms)
{
    return now_ms - started_ms >= duration_ms;
}

static void start_setup_ap(ainekio_provisioning_t *machine)
{
    if (!machine->setup_ap_running) {
        machine->setup_ap_running = true;
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_START_SETUP_AP;
    }
}

static void stop_setup_ap(ainekio_provisioning_t *machine)
{
    if (machine->setup_ap_running) {
        machine->setup_ap_running = false;
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_STOP_SETUP_AP;
    }
}

static bool reason_shows_unavailable(ainekio_provision_reason_t reason)
{
    return reason == AINEKIO_PROVISION_REASON_NO_CONFIG ||
           reason == AINEKIO_PROVISION_REASON_NVS_CORRUPT ||
           reason == AINEKIO_PROVISION_REASON_WIFI_TIMEOUT ||
           reason == AINEKIO_PROVISION_REASON_NETWORK_RESET;
}

static void discard_staged_if_present(ainekio_provisioning_t *machine)
{
    if (machine->has_staged_config) {
        machine->has_staged_config = false;
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG;
    }
}

static void enter_connecting(ainekio_provisioning_t *machine, uint64_t now_ms)
{
    stop_setup_ap(machine);
    machine->state = AINEKIO_PROVISION_STATE_CONNECTING;
    machine->reason = AINEKIO_PROVISION_REASON_NONE;
    machine->session = AINEKIO_PROVISION_SESSION_NONE;
    machine->state_started_ms = now_ms;
    machine->has_staged_config = false;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI |
                                AINEKIO_PROVISION_ACTION_SHOW_CONNECTING;
}

static void enter_setup_session(
    ainekio_provisioning_t *machine,
    ainekio_provision_session_t requested_session,
    ainekio_provision_reason_t reason,
    uint64_t now_ms
)
{
    discard_staged_if_present(machine);
    machine->session = requested_session;
    if (!machine->has_active_wifi) {
        machine->session = AINEKIO_PROVISION_SESSION_AUTOMATIC;
    }
    machine->state = machine->session == AINEKIO_PROVISION_SESSION_MANUAL
                         ? AINEKIO_PROVISION_STATE_MANUAL_AP
                         : AINEKIO_PROVISION_STATE_AUTOMATIC_AP;
    machine->reason = reason;
    machine->state_started_ms = now_ms;
    machine->session_started_ms = now_ms;
    start_setup_ap(machine);
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_LOAD_SETUP_KEY |
                                AINEKIO_PROVISION_ACTION_SHOW_SETUP |
                                AINEKIO_PROVISION_ACTION_PLAY_SETUP_CUE;
    if (machine->has_active_wifi) {
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI;
    }
    if (reason_shows_unavailable(reason)) {
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_WIFI_UNAVAILABLE;
    }
}

static void enter_automatic_retry(ainekio_provisioning_t *machine, uint64_t now_ms)
{
    stop_setup_ap(machine);
    machine->state = AINEKIO_PROVISION_STATE_AUTOMATIC_RETRY;
    machine->state_started_ms = now_ms;
    if (machine->has_active_wifi) {
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI |
                                    AINEKIO_PROVISION_ACTION_SHOW_CONNECTING;
    } else {
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_WIFI_UNAVAILABLE;
    }
}

static void resume_setup_after_staged_failure(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    machine->has_staged_config = false;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG;
    if (machine->session == AINEKIO_PROVISION_SESSION_MANUAL &&
        machine->has_active_wifi) {
        machine->state = AINEKIO_PROVISION_STATE_MANUAL_AP;
    } else {
        machine->session = AINEKIO_PROVISION_SESSION_AUTOMATIC;
        machine->state = AINEKIO_PROVISION_STATE_AUTOMATIC_AP;
    }
    machine->state_started_ms = now_ms;
    start_setup_ap(machine);
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_SETUP;
    if (machine->has_active_wifi) {
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI;
    }
}

void ainekio_provisioning_init(
    ainekio_provisioning_t *machine,
    ainekio_config_status_t config_status,
    uint64_t now_ms
)
{
    memset(machine, 0, sizeof(*machine));
    machine->has_active_wifi = config_status == AINEKIO_CONFIG_STATUS_VALID ||
                               config_status == AINEKIO_CONFIG_STATUS_MIGRATED;
    if (machine->has_active_wifi) {
        enter_connecting(machine, now_ms);
        return;
    }

    const ainekio_provision_reason_t reason =
        config_status == AINEKIO_CONFIG_STATUS_CORRUPT
            ? AINEKIO_PROVISION_REASON_NVS_CORRUPT
            : AINEKIO_PROVISION_REASON_NO_CONFIG;
    enter_setup_session(machine, AINEKIO_PROVISION_SESSION_AUTOMATIC, reason, now_ms);
}

void ainekio_provisioning_tick(ainekio_provisioning_t *machine, uint64_t now_ms)
{
    switch (machine->state) {
        case AINEKIO_PROVISION_STATE_CONNECTING:
            if (elapsed(now_ms, machine->state_started_ms, AINEKIO_WIFI_CONNECT_TIMEOUT_MS)) {
                enter_setup_session(
                    machine,
                    AINEKIO_PROVISION_SESSION_AUTOMATIC,
                    AINEKIO_PROVISION_REASON_WIFI_TIMEOUT,
                    now_ms
                );
            }
            break;
        case AINEKIO_PROVISION_STATE_MANUAL_AP:
            if (elapsed(now_ms, machine->session_started_ms, AINEKIO_SETUP_AP_ON_MS)) {
                if (machine->has_active_wifi) {
                    enter_connecting(machine, now_ms);
                } else {
                    machine->session = AINEKIO_PROVISION_SESSION_AUTOMATIC;
                    enter_automatic_retry(machine, now_ms);
                }
            }
            break;
        case AINEKIO_PROVISION_STATE_AUTOMATIC_AP:
            if (elapsed(now_ms, machine->state_started_ms, AINEKIO_SETUP_AP_ON_MS)) {
                enter_automatic_retry(machine, now_ms);
            }
            break;
        case AINEKIO_PROVISION_STATE_AUTOMATIC_RETRY:
            if (elapsed(now_ms, machine->state_started_ms, AINEKIO_SETUP_AP_OFF_MS)) {
                machine->state = AINEKIO_PROVISION_STATE_AUTOMATIC_AP;
                machine->state_started_ms = now_ms;
                start_setup_ap(machine);
                machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_SETUP;
            }
            break;
        case AINEKIO_PROVISION_STATE_VALIDATING_STAGED:
            if (elapsed(now_ms, machine->state_started_ms, AINEKIO_WIFI_CONNECT_TIMEOUT_MS)) {
                resume_setup_after_staged_failure(machine, now_ms);
            }
            break;
        case AINEKIO_PROVISION_STATE_ONLINE:
        case AINEKIO_PROVISION_STATE_COMMITTING_STAGED:
            break;
    }
}

void ainekio_provisioning_on_wifi_lost(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    if (machine->state == AINEKIO_PROVISION_STATE_ONLINE && machine->has_active_wifi) {
        enter_connecting(machine, now_ms);
    }
}

void ainekio_provisioning_on_active_wifi_ip(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    if (!machine->has_active_wifi ||
        (machine->state != AINEKIO_PROVISION_STATE_CONNECTING &&
         machine->state != AINEKIO_PROVISION_STATE_AUTOMATIC_AP &&
         machine->state != AINEKIO_PROVISION_STATE_AUTOMATIC_RETRY)) {
        return;
    }

    stop_setup_ap(machine);
    machine->state = AINEKIO_PROVISION_STATE_ONLINE;
    machine->reason = AINEKIO_PROVISION_REASON_NONE;
    machine->session = AINEKIO_PROVISION_SESSION_NONE;
    machine->state_started_ms = now_ms;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_CONNECTED |
                                AINEKIO_PROVISION_ACTION_PLAY_CONNECTED_CUE;
}

void ainekio_provisioning_request_manual(
    ainekio_provisioning_t *machine,
    ainekio_provision_reason_t reason,
    uint64_t now_ms
)
{
    if (reason != AINEKIO_PROVISION_REASON_BOOT_BUTTON) {
        reason = AINEKIO_PROVISION_REASON_DASHBOARD_REQUEST;
    }
    enter_setup_session(machine, AINEKIO_PROVISION_SESSION_MANUAL, reason, now_ms);
}

void ainekio_provisioning_request_network_reset(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    machine->has_active_wifi = false;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_CLEAR_ACTIVE_WIFI;
    enter_setup_session(
        machine,
        AINEKIO_PROVISION_SESSION_AUTOMATIC,
        AINEKIO_PROVISION_REASON_NETWORK_RESET,
        now_ms
    );
}

bool ainekio_provisioning_begin_staged_validation(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    if (!machine->setup_ap_running ||
        (machine->state != AINEKIO_PROVISION_STATE_MANUAL_AP &&
         machine->state != AINEKIO_PROVISION_STATE_AUTOMATIC_AP)) {
        return false;
    }
    machine->state = AINEKIO_PROVISION_STATE_VALIDATING_STAGED;
    machine->state_started_ms = now_ms;
    machine->has_staged_config = true;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_CONNECT_STAGED_WIFI;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_CONNECTING;
    return true;
}

void ainekio_provisioning_on_staged_wifi_ip(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    if (machine->state != AINEKIO_PROVISION_STATE_VALIDATING_STAGED ||
        !machine->has_staged_config) {
        return;
    }
    machine->state = AINEKIO_PROVISION_STATE_COMMITTING_STAGED;
    machine->state_started_ms = now_ms;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_COMMIT_STAGED_CONFIG;
}

void ainekio_provisioning_on_staged_validation_failure(
    ainekio_provisioning_t *machine,
    uint64_t now_ms
)
{
    if (machine->state == AINEKIO_PROVISION_STATE_VALIDATING_STAGED) {
        resume_setup_after_staged_failure(machine, now_ms);
    }
}

void ainekio_provisioning_on_staged_commit_result(
    ainekio_provisioning_t *machine,
    bool committed,
    uint64_t now_ms
)
{
    if (machine->state != AINEKIO_PROVISION_STATE_COMMITTING_STAGED) {
        return;
    }
    if (!committed) {
        resume_setup_after_staged_failure(machine, now_ms);
        return;
    }

    machine->has_active_wifi = true;
    machine->has_staged_config = false;
    stop_setup_ap(machine);
    machine->state = AINEKIO_PROVISION_STATE_ONLINE;
    machine->reason = AINEKIO_PROVISION_REASON_NONE;
    machine->session = AINEKIO_PROVISION_SESSION_NONE;
    machine->state_started_ms = now_ms;
    machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_CONNECTED |
                                AINEKIO_PROVISION_ACTION_PLAY_CONNECTED_CUE;
}

void ainekio_provisioning_on_gateway_failure(ainekio_provisioning_t *machine)
{
    (void)machine;
}

void ainekio_provisioning_on_gateway_auth_failure(
    ainekio_provisioning_t *machine
)
{
    if (machine->state == AINEKIO_PROVISION_STATE_ONLINE) {
        machine->pending_actions |= AINEKIO_PROVISION_ACTION_SHOW_GATEWAY_AUTH_FAILED;
    }
}

ainekio_provision_actions_t ainekio_provisioning_take_actions(
    ainekio_provisioning_t *machine
)
{
    const ainekio_provision_actions_t actions = machine->pending_actions;
    machine->pending_actions = AINEKIO_PROVISION_ACTION_NONE;
    return actions;
}
