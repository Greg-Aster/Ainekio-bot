#include "ainekio/platform/provisioning_service.h"

#include <stdio.h>
#include <string.h>

#include "ainekio/platform/pin_map.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"

#define SERVICE_PERIOD_MS 100U
#define BOOT_HOLD_MS 5000U
#define RETRY_INITIAL_MS 1000U
#define RETRY_MAX_MS 30000U
#define REQUEST_MANUAL BIT0
#define REQUEST_NETWORK_RESET BIT1
#define REQUEST_GATEWAY_AUTH_FAILED BIT2

static const char *TAG = "ainekio_provision";

static uint32_t service_now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static bool includes(ainekio_provision_actions_t actions, ainekio_provision_actions_t flag)
{
    return (actions & flag) != 0U;
}

static void schedule_retry(ainekio_provisioning_service_t *service, uint32_t now)
{
    service->retry_delay_ms = service->retry_delay_ms == 0U
                                  ? RETRY_INITIAL_MS
                                  : service->retry_delay_ms * 2U;
    if (service->retry_delay_ms > RETRY_MAX_MS) {
        service->retry_delay_ms = RETRY_MAX_MS;
    }
    service->retry_at_ms = now + service->retry_delay_ms;
}

static void connect_active(ainekio_provisioning_service_t *service, uint32_t now)
{
    if (!service->config_store->has_active ||
        service->config_store->active.wifi_ssid[0] == '\0') {
        return;
    }
    const esp_err_t result = ainekio_wifi_connect(
        service->wifi,
        service->config_store->active.wifi_ssid,
        service->config_store->active.wifi_psk
    );
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "saved network association request failed: %s", esp_err_to_name(result));
    }
    schedule_retry(service, now);
}

static void connect_staged(ainekio_provisioning_service_t *service, uint32_t now)
{
    const esp_err_t result = ainekio_wifi_connect(
        service->wifi,
        service->staged_ssid,
        service->staged_psk
    );
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "staged network association request failed: %s", esp_err_to_name(result));
    }
    schedule_retry(service, now);
}

static void show_status(
    ainekio_provisioning_service_t *service,
    ainekio_provision_display_t status,
    const char *secret
)
{
    const esp_err_t result = service->io.display == NULL
                                 ? ESP_ERR_NOT_SUPPORTED
                                 : service->io.display(service->io.context, status, secret);
    if (status == AINEKIO_PROVISION_DISPLAY_SETUP && result != ESP_OK &&
        secret != NULL && !service->serial_secret_printed) {
        printf("Ainekio setup network: %s\nAinekio setup secret: %s\n",
               AINEKIO_SETUP_SSID,
               secret);
        service->serial_secret_printed = true;
    }
}

static void play_cue(
    ainekio_provisioning_service_t *service,
    ainekio_provision_cue_t cue
)
{
    if (service->io.cue != NULL) {
        (void)service->io.cue(service->io.context, cue);
    }
}

static void process_candidate(ainekio_provisioning_service_t *service, uint32_t now)
{
    ainekio_portal_candidate_t candidate;
    if (!ainekio_provisioning_portal_take_candidate(service->portal, &candidate, 0U)) {
        return;
    }
    const ainekio_store_result_t staged = candidate.network_only
                                              ? ainekio_config_store_stage_network(
                                                    service->config_store,
                                                    candidate.record.wifi_ssid,
                                                    candidate.record.wifi_psk
                                                )
                                              : ainekio_config_store_stage_initial(
                                                    service->config_store,
                                                    &candidate.record
                                                );
    if (staged == AINEKIO_STORE_OK &&
        ainekio_provisioning_begin_staged_validation(service->machine, now)) {
        memcpy(service->staged_ssid, candidate.record.wifi_ssid,
               sizeof(service->staged_ssid));
        memcpy(service->staged_psk, candidate.record.wifi_psk,
               sizeof(service->staged_psk));
    } else if (staged == AINEKIO_STORE_OK) {
        (void)ainekio_config_store_discard(service->config_store);
    }
    memset(&candidate, 0, sizeof(candidate));
}

static void process_boot_button(ainekio_provisioning_service_t *service, uint32_t now)
{
    const bool pressed = gpio_get_level(AINEKIO_PIN_BOOT) == 0;
    if (!pressed) {
        service->boot_press_active = false;
        service->boot_press_triggered = false;
        return;
    }
    if (!service->boot_press_active) {
        service->boot_press_active = true;
        service->boot_pressed_at_ms = now;
        return;
    }
    if (!service->boot_press_triggered &&
        (uint32_t)(now - service->boot_pressed_at_ms) >= BOOT_HOLD_MS) {
        service->boot_press_triggered = true;
        ainekio_provisioning_request_manual(
            service->machine,
            AINEKIO_PROVISION_REASON_BOOT_BUTTON,
            now
        );
    }
}

static void process_link_state(ainekio_provisioning_service_t *service, uint32_t now)
{
    const bool has_ip = ainekio_wifi_has_ip(service->wifi);
    if (has_ip && !service->previous_ip) {
        service->retry_delay_ms = 0U;
        if (service->machine->state == AINEKIO_PROVISION_STATE_VALIDATING_STAGED) {
            ainekio_provisioning_on_staged_wifi_ip(service->machine, now);
        } else {
            ainekio_provisioning_on_active_wifi_ip(service->machine, now);
            if (service->io.online != NULL && service->config_store->has_active) {
                (void)service->io.online(
                    service->io.context,
                    &service->config_store->active
                );
            }
        }
    } else if (!has_ip && service->previous_ip &&
               service->machine->state == AINEKIO_PROVISION_STATE_ONLINE) {
        ainekio_provisioning_on_wifi_lost(service->machine, now);
    }
    service->previous_ip = has_ip;
}

static void process_retry(ainekio_provisioning_service_t *service, uint32_t now)
{
    if (ainekio_wifi_has_ip(service->wifi) || service->retry_at_ms == 0U ||
        (int32_t)(now - service->retry_at_ms) < 0) {
        return;
    }
    if (service->machine->state == AINEKIO_PROVISION_STATE_VALIDATING_STAGED) {
        connect_staged(service, now);
    } else if (service->machine->has_active_wifi &&
               service->machine->state != AINEKIO_PROVISION_STATE_MANUAL_AP) {
        connect_active(service, now);
    }
}

static void process_actions(
    ainekio_provisioning_service_t *service,
    ainekio_provision_actions_t actions,
    uint32_t now
)
{
    if (includes(actions, AINEKIO_PROVISION_ACTION_CLEAR_ACTIVE_WIFI)) {
        const bool cleared =
            ainekio_config_store_stage_network_reset(service->config_store) ==
                AINEKIO_STORE_OK &&
            ainekio_config_store_commit(service->config_store) == AINEKIO_STORE_OK;
        if (!cleared) {
            ESP_LOGE(TAG, "network-only reset could not be committed");
        }
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_DISCARD_STAGED_CONFIG)) {
        (void)ainekio_config_store_discard(service->config_store);
        memset(service->staged_ssid, 0, sizeof(service->staged_ssid));
        memset(service->staged_psk, 0, sizeof(service->staged_psk));
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_GENERATE_SETUP_SECRET)) {
        memset(service->setup_secret, 0, sizeof(service->setup_secret));
        service->serial_secret_printed = false;
        const esp_err_t result = ainekio_provisioning_portal_generate_secret(
            service->portal,
            service->setup_secret
        );
        if (result != ESP_OK) {
            ESP_LOGE(TAG, "setup secret generation failed: %s", esp_err_to_name(result));
        }
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_START_SETUP_AP) &&
        service->setup_secret[0] != '\0') {
        const esp_err_t wifi_result =
            ainekio_wifi_start_setup(service->wifi, service->setup_secret);
        const esp_err_t portal_result = wifi_result == ESP_OK
                                            ? ainekio_provisioning_portal_start(
                                                  service->portal,
                                                  service->config_store->has_active
                                              )
                                            : wifi_result;
        if (portal_result != ESP_OK) {
            ESP_LOGE(TAG, "setup service start failed: %s", esp_err_to_name(portal_result));
        }
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_STOP_SETUP_AP)) {
        (void)ainekio_wifi_stop_setup(service->wifi);
        if (service->machine->state == AINEKIO_PROVISION_STATE_AUTOMATIC_RETRY) {
            (void)ainekio_provisioning_portal_suspend(service->portal);
        } else {
            (void)ainekio_provisioning_portal_stop(service->portal);
            memset(service->setup_secret, 0, sizeof(service->setup_secret));
        }
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_CONNECT_ACTIVE_WIFI)) {
        connect_active(service, now);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_CONNECT_STAGED_WIFI)) {
        connect_staged(service, now);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_COMMIT_STAGED_CONFIG)) {
        const bool committed =
            ainekio_config_store_commit(service->config_store) == AINEKIO_STORE_OK;
        ainekio_provisioning_on_staged_commit_result(service->machine, committed, now);
        if (committed) {
            memset(service->staged_ssid, 0, sizeof(service->staged_ssid));
            memset(service->staged_psk, 0, sizeof(service->staged_psk));
            if (service->io.online != NULL && service->config_store->has_active) {
                (void)service->io.online(
                    service->io.context,
                    &service->config_store->active
                );
            }
        }
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_SHOW_CONNECTING)) {
        show_status(service, AINEKIO_PROVISION_DISPLAY_CONNECTING, NULL);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_SHOW_WIFI_UNAVAILABLE)) {
        show_status(service, AINEKIO_PROVISION_DISPLAY_UNAVAILABLE, NULL);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_SHOW_SETUP)) {
        show_status(service, AINEKIO_PROVISION_DISPLAY_SETUP, service->setup_secret);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_SHOW_CONNECTED)) {
        show_status(service, AINEKIO_PROVISION_DISPLAY_CONNECTED, NULL);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_SHOW_GATEWAY_AUTH_FAILED)) {
        show_status(service, AINEKIO_PROVISION_DISPLAY_GATEWAY_AUTH_FAILED, NULL);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_PLAY_SETUP_CUE)) {
        play_cue(service, AINEKIO_PROVISION_CUE_SETUP);
    }
    if (includes(actions, AINEKIO_PROVISION_ACTION_PLAY_CONNECTED_CUE)) {
        play_cue(service, AINEKIO_PROVISION_CUE_CONNECTED);
    }
}

static void provisioning_task(void *argument)
{
    ainekio_provisioning_service_t *service = argument;
    while (true) {
        const uint32_t now = service_now_ms();
        uint32_t requests = 0U;
        (void)xTaskNotifyWait(0U, UINT32_MAX, &requests, 0U);
        if ((requests & REQUEST_MANUAL) != 0U) {
            ainekio_provisioning_request_manual(
                service->machine,
                AINEKIO_PROVISION_REASON_DASHBOARD_REQUEST,
                now
            );
        }
        if ((requests & REQUEST_NETWORK_RESET) != 0U) {
            ainekio_provisioning_request_network_reset(service->machine, now);
        }
        if ((requests & REQUEST_GATEWAY_AUTH_FAILED) != 0U) {
            ainekio_provisioning_on_gateway_auth_failure(service->machine);
        }
        process_boot_button(service, now);
        process_candidate(service, now);
        process_link_state(service, now);
        ainekio_provisioning_tick(service->machine, now);
        process_actions(service, ainekio_provisioning_take_actions(service->machine), now);
        process_retry(service, now);
        vTaskDelay(pdMS_TO_TICKS(SERVICE_PERIOD_MS));
    }
}

esp_err_t ainekio_provisioning_service_start(
    ainekio_provisioning_service_t *service,
    ainekio_provisioning_t *machine,
    ainekio_config_store_t *config_store,
    ainekio_wifi_adapter_t *wifi,
    ainekio_provisioning_portal_t *portal,
    const ainekio_provision_io_t *io
)
{
    if (service == NULL || machine == NULL || config_store == NULL || wifi == NULL ||
        portal == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(service, 0, sizeof(*service));
    service->machine = machine;
    service->config_store = config_store;
    service->wifi = wifi;
    service->portal = portal;
    if (io != NULL) {
        service->io = *io;
    }
    const gpio_config_t boot_config = {
        .pin_bit_mask = UINT64_C(1) << AINEKIO_PIN_BOOT,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    const esp_err_t gpio_result = gpio_config(&boot_config);
    if (gpio_result != ESP_OK) {
        return gpio_result;
    }
    if (xTaskCreatePinnedToCore(
            provisioning_task,
            "provision",
            4096U,
            service,
            3U,
            &service->task,
            0
        ) != pdPASS) {
        service->task = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

void ainekio_provisioning_service_request_manual(
    ainekio_provisioning_service_t *service
)
{
    if (service != NULL && service->task != NULL) {
        (void)xTaskNotify(service->task, REQUEST_MANUAL, eSetBits);
    }
}

void ainekio_provisioning_service_request_network_reset(
    ainekio_provisioning_service_t *service
)
{
    if (service != NULL && service->task != NULL) {
        (void)xTaskNotify(service->task, REQUEST_NETWORK_RESET, eSetBits);
    }
}

void ainekio_provisioning_service_request_gateway_auth_failure(
    ainekio_provisioning_service_t *service
)
{
    if (service != NULL && service->task != NULL) {
        (void)xTaskNotify(service->task, REQUEST_GATEWAY_AUTH_FAILED, eSetBits);
    }
}
