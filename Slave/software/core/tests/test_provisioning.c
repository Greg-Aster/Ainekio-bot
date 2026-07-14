#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "ainekio/config_schema.h"
#include "ainekio/provisioning.h"

static bool includes(ainekio_provision_actions_t actions, ainekio_provision_actions_t flag)
{
    return (actions & flag) == flag;
}

static void assert_nvs_name(const char *name)
{
    assert(strlen(name) > 0U);
    assert(strlen(name) <= 15U);
}

static void test_nvs_contract_is_versioned_and_bounded(void)
{
    const char *names[] = {
        AINEKIO_NVS_NAMESPACE_META,
        AINEKIO_NVS_NAMESPACE_CONFIG_A,
        AINEKIO_NVS_NAMESPACE_CONFIG_B,
        AINEKIO_NVS_NAMESPACE_CALIBRATION,
        AINEKIO_NVS_NAMESPACE_POSES,
        AINEKIO_NVS_NAMESPACE_PREFERENCES,
        AINEKIO_NVS_KEY_SCHEMA_VERSION,
        AINEKIO_NVS_KEY_ACTIVE_SLOT,
        AINEKIO_NVS_KEY_SETUP_HASH,
        AINEKIO_NVS_KEY_GENERATION,
        AINEKIO_NVS_KEY_COMPLETE,
        AINEKIO_NVS_KEY_WIFI_SSID,
        AINEKIO_NVS_KEY_WIFI_PSK,
        AINEKIO_NVS_KEY_ENDPOINT_URL,
        AINEKIO_NVS_KEY_ROBOT_ID,
        AINEKIO_NVS_KEY_ROBOT_TOKEN,
        AINEKIO_NVS_KEY_SERVO_CALIBRATION,
        AINEKIO_NVS_KEY_NAMED_POSES,
        AINEKIO_NVS_KEY_DEFAULT_PROFILE,
        AINEKIO_NVS_KEY_ADC_FACTOR,
    };
    assert(AINEKIO_NVS_SCHEMA_VERSION == 1U);
    assert(AINEKIO_CONFIG_SLOT_A != AINEKIO_CONFIG_SLOT_B);
    for (size_t index = 0U; index < sizeof(names) / sizeof(names[0]); ++index) {
        assert_nvs_name(names[index]);
    }
}

static void test_valid_boot_uses_sixty_second_window(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_VALID, 1000U);

    assert(machine.state == AINEKIO_PROVISION_STATE_CONNECTING);
    ainekio_provision_actions_t actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_CONNECTING));

    ainekio_provisioning_tick(&machine, 60999U);
    assert(machine.state == AINEKIO_PROVISION_STATE_CONNECTING);
    ainekio_provisioning_tick(&machine, 61000U);
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(machine.reason == AINEKIO_PROVISION_REASON_WIFI_TIMEOUT);
    actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_START_SETUP_AP));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_GENERATE_SETUP_SECRET));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_WIFI_UNAVAILABLE));
}

static void test_missing_and_corrupt_config_enter_automatic_setup(void)
{
    ainekio_provisioning_t missing;
    ainekio_provisioning_init(&missing, AINEKIO_CONFIG_STATUS_MISSING, 0U);
    assert(missing.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(missing.reason == AINEKIO_PROVISION_REASON_NO_CONFIG);
    assert(!missing.has_active_wifi);

    ainekio_provisioning_t corrupt;
    ainekio_provisioning_init(&corrupt, AINEKIO_CONFIG_STATUS_CORRUPT, 0U);
    assert(corrupt.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(corrupt.reason == AINEKIO_PROVISION_REASON_NVS_CORRUPT);
    assert(!corrupt.has_active_wifi);
}

static void test_automatic_setup_cycles_without_replaying_setup_cue(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_MISSING, 0U);
    (void)ainekio_provisioning_take_actions(&machine);

    ainekio_provisioning_tick(&machine, AINEKIO_SETUP_AP_ON_MS);
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_RETRY);
    ainekio_provision_actions_t actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_STOP_SETUP_AP));
    assert(!includes(actions, AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI));

    ainekio_provisioning_tick(
        &machine,
        AINEKIO_SETUP_AP_ON_MS + AINEKIO_SETUP_AP_OFF_MS
    );
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_START_SETUP_AP));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_SETUP));
    assert(!includes(actions, AINEKIO_PROVISION_ACTION_GENERATE_SETUP_SECRET));
    assert(!includes(actions, AINEKIO_PROVISION_ACTION_PLAY_SETUP_CUE));
}

static void test_manual_setup_timeout_resumes_old_config(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_VALID, 0U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_on_active_wifi_ip(&machine, 100U);
    (void)ainekio_provisioning_take_actions(&machine);

    ainekio_provisioning_request_manual(
        &machine,
        AINEKIO_PROVISION_REASON_BOOT_BUTTON,
        1000U
    );
    assert(machine.state == AINEKIO_PROVISION_STATE_MANUAL_AP);
    assert(machine.reason == AINEKIO_PROVISION_REASON_BOOT_BUTTON);
    ainekio_provisioning_tick(&machine, 1000U + AINEKIO_SETUP_AP_ON_MS);
    assert(machine.state == AINEKIO_PROVISION_STATE_CONNECTING);
    assert(machine.has_active_wifi);
    const ainekio_provision_actions_t actions =
        ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_STOP_SETUP_AP));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI));
}

static void test_staged_config_commits_only_after_station_ip(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_MISSING, 0U);
    (void)ainekio_provisioning_take_actions(&machine);

    assert(ainekio_provisioning_begin_staged_validation(&machine, 100U));
    assert(machine.state == AINEKIO_PROVISION_STATE_VALIDATING_STAGED);
    ainekio_provision_actions_t actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_CONNECT_STAGED_WIFI));
    assert(!includes(actions, AINEKIO_PROVISION_ACTION_COMMIT_STAGED_CONFIG));

    ainekio_provisioning_on_staged_wifi_ip(&machine, 200U);
    assert(machine.state == AINEKIO_PROVISION_STATE_COMMITTING_STAGED);
    actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_COMMIT_STAGED_CONFIG));

    ainekio_provisioning_on_staged_commit_result(&machine, true, 300U);
    assert(machine.state == AINEKIO_PROVISION_STATE_ONLINE);
    assert(machine.has_active_wifi);
    assert(!machine.has_staged_config);
    actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_STOP_SETUP_AP));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_CONNECTED));
}

static void test_staged_timeout_and_commit_failure_preserve_old_config(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_VALID, 0U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_on_active_wifi_ip(&machine, 1U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_request_manual(
        &machine,
        AINEKIO_PROVISION_REASON_DASHBOARD_REQUEST,
        100U
    );
    (void)ainekio_provisioning_take_actions(&machine);

    assert(ainekio_provisioning_begin_staged_validation(&machine, 200U));
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_tick(&machine, 200U + AINEKIO_WIFI_CONNECT_TIMEOUT_MS);
    assert(machine.state == AINEKIO_PROVISION_STATE_MANUAL_AP);
    assert(machine.has_active_wifi);
    ainekio_provision_actions_t actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG));

    assert(ainekio_provisioning_begin_staged_validation(&machine, 70000U));
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_on_staged_wifi_ip(&machine, 70100U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_on_staged_commit_result(&machine, false, 70200U);
    assert(machine.state == AINEKIO_PROVISION_STATE_MANUAL_AP);
    assert(machine.has_active_wifi);
    actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG));
}

static void test_network_reset_clears_only_wifi_state(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_VALID, 0U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_on_active_wifi_ip(&machine, 1U);
    (void)ainekio_provisioning_take_actions(&machine);

    ainekio_provisioning_request_network_reset(&machine, 10U);
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(machine.reason == AINEKIO_PROVISION_REASON_NETWORK_RESET);
    assert(!machine.has_active_wifi);
    const ainekio_provision_actions_t actions =
        ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_CLEAR_ACTIVE_WIFI));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_GENERATE_SETUP_SECRET));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_SETUP));
}

static void test_network_reset_discards_an_incomplete_stage(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_MISSING, 0U);
    (void)ainekio_provisioning_take_actions(&machine);
    assert(ainekio_provisioning_begin_staged_validation(&machine, 100U));
    (void)ainekio_provisioning_take_actions(&machine);

    ainekio_provisioning_request_network_reset(&machine, 200U);
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(!machine.has_staged_config);
    const ainekio_provision_actions_t actions =
        ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_CLEAR_ACTIVE_WIFI));
}

static void test_saved_network_return_and_gateway_failure_are_distinct(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_VALID, 0U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_tick(&machine, AINEKIO_WIFI_CONNECT_TIMEOUT_MS);
    (void)ainekio_provisioning_take_actions(&machine);

    ainekio_provisioning_on_gateway_failure(&machine);
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(ainekio_provisioning_take_actions(&machine) == AINEKIO_PROVISION_ACTION_NONE);

    ainekio_provisioning_on_active_wifi_ip(&machine, 61000U);
    assert(machine.state == AINEKIO_PROVISION_STATE_ONLINE);
    ainekio_provision_actions_t actions =
        ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_STOP_SETUP_AP));
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_CONNECTED));

    ainekio_provisioning_on_gateway_auth_failure(&machine);
    assert(machine.state == AINEKIO_PROVISION_STATE_ONLINE);
    assert(machine.has_active_wifi);
    actions = ainekio_provisioning_take_actions(&machine);
    assert(includes(actions, AINEKIO_PROVISION_ACTION_SHOW_GATEWAY_AUTH_FAILED));
}

static void test_wifi_loss_restarts_the_same_connection_window(void)
{
    ainekio_provisioning_t machine;
    ainekio_provisioning_init(&machine, AINEKIO_CONFIG_STATUS_MIGRATED, 0U);
    (void)ainekio_provisioning_take_actions(&machine);
    ainekio_provisioning_on_active_wifi_ip(&machine, 1U);
    (void)ainekio_provisioning_take_actions(&machine);

    ainekio_provisioning_on_wifi_lost(&machine, 100U);
    assert(machine.state == AINEKIO_PROVISION_STATE_CONNECTING);
    ainekio_provisioning_tick(&machine, 100U + AINEKIO_WIFI_CONNECT_TIMEOUT_MS);
    assert(machine.state == AINEKIO_PROVISION_STATE_AUTOMATIC_AP);
    assert(machine.reason == AINEKIO_PROVISION_REASON_WIFI_TIMEOUT);
}

int main(void)
{
    test_nvs_contract_is_versioned_and_bounded();
    test_valid_boot_uses_sixty_second_window();
    test_missing_and_corrupt_config_enter_automatic_setup();
    test_automatic_setup_cycles_without_replaying_setup_cue();
    test_manual_setup_timeout_resumes_old_config();
    test_staged_config_commits_only_after_station_ip();
    test_staged_timeout_and_commit_failure_preserve_old_config();
    test_network_reset_clears_only_wifi_state();
    test_network_reset_discards_an_incomplete_stage();
    test_saved_network_return_and_gateway_failure_are_distinct();
    test_wifi_loss_restarts_the_same_connection_window();
    puts("ainekio provisioning tests passed");
    return 0;
}
