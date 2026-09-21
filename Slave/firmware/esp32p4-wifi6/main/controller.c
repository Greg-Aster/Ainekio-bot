#include "controller.h"
#include "board.h"
#include "config.h"
#include "network.h"
#include "ainekio/admission.h"
#include "ainekio/control_encode.h"
#include "ainekio/v2_motion.h"

#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

typedef struct {
    uint64_t connection, output_generation, received_us;
    ainekio_control_message_t message;
} request_t;
typedef struct {
    uint64_t connection;
    /* Full installed-command declaration plus maximally JSON-escaped bounded
     * identity/token fields. Encoding failure still closes the connection. */
    char text[2048];
} reply_t;

static portMUX_TYPE admission_lock = portMUX_INITIALIZER_UNLOCKED;
static ainekio_admission_t admission;
static QueueHandle_t requests, replies;
static atomic_bool initialized, reconnect, quiesced;
/* One WebSocket instance at a time. The link task drains/stops the old client
 * before creating another; queued results can never cross into its successor. */
static uint64_t link_generation;
static char receive_text[4097];
static size_t receive_used, frame_received;

static uint64_t now_us(void) { return esp_timer_get_time(); }
static void enter(void) { portENTER_CRITICAL(&admission_lock); }
static void leave(void) { portEXIT_CRITICAL(&admission_lock); }

static void fail_link(void)
{
    enter();
    if (admission.connected) ainekio_admission_close(&admission, admission.generation);
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    leave();
    atomic_store(&reconnect, true);
}

void ainekio_p4_controller_quiesce(void)
{
    atomic_store(&quiesced, true);
    enter();
    ainekio_admission_close(&admission, admission.generation);
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    leave();
    atomic_store(&reconnect, true);
}

static void reply(uint64_t connection, const char *text)
{
    reply_t response = {.connection=connection};
    if (strlen(text) >= sizeof(response.text)) { fail_link(); return; }
    strcpy(response.text, text);
    if (xQueueSend(replies, &response, 0) != pdTRUE) fail_link();
}

static void ack(uint64_t connection, uint32_t sequence)
{
    char text[80];
    ainekio_encode_ack(sequence, 0, text, sizeof(text));
    reply(connection, text);
}

static void nak(uint64_t connection, const ainekio_control_message_t *m, ainekio_reject_reason_t reason)
{
    static const ainekio_nak_code_t codes[] = {
        AINEKIO_NAK_UNKNOWN, AINEKIO_NAK_STALE, AINEKIO_NAK_MODE, AINEKIO_NAK_UNSAFE,
        AINEKIO_NAK_LIMIT, AINEKIO_NAK_UNKNOWN, AINEKIO_NAK_BUSY, AINEKIO_NAK_PROFILE,
        AINEKIO_NAK_ASSET_MISSING, AINEKIO_NAK_MALFORMED,
    };
    char text[180];
    uint8_t cycles;
    size_t clip_index;
    const char *detail = reason == AINEKIO_REJECT_BUSY &&
        (ainekio_v2_walk_request(&m->command, &cycles) || ainekio_v2_clip_request(&m->command, &clip_index))
        ? "motion installed; joint calibration and hardware qualification incomplete" : NULL;
    ainekio_encode_nak(m->has_sequence, m->sequence, codes[reason], detail, text, sizeof(text));
    reply(connection, text);
}

static void terminal(uint64_t connection, uint32_t sequence, bool completed)
{
    char text[96];
    if (completed) ainekio_encode_done(sequence, text, sizeof(text));
    else ainekio_encode_cancelled(sequence, AINEKIO_CANCEL_STOP, text, sizeof(text));
    reply(connection, text);
}

static void heartbeat(uint64_t connection, bool pong)
{
    char text[96];
    snprintf(text, sizeof(text), "{\"t\":\"%s\",\"clock_ms\":%" PRIu64 "}",
             pong ? "pong" : "ping", now_us() / 1000U);
    reply(connection, text);
}

static void hello(uint64_t connection)
{
    const ainekio_config_record_t *config = ainekio_p4_config();
    char text[sizeof(((reply_t *)0)->text)];
    if (!ainekio_encode_hello(esp_app_get_description()->version, config->robot_id, config->robot_token, false, text, sizeof(text))) {
        fail_link(); return;
    }
    cJSON *message = cJSON_Parse(text);
    if (!message) { fail_link(); return; }
    const char *features[] = {"command_deadline_v1", "output_test_v1", "body_capabilities_v1", "body_commands_v1"};
    cJSON_DeleteItemFromObject(message, "features");
    cJSON_AddItemToObject(message, "features", cJSON_CreateStringArray(features, 4));
    cJSON_AddStringToObject(message, "model", "v2-12servo");
    cJSON_AddNumberToObject(message, "clock_ms", now_us() / 1000U);
    cJSON *caps = cJSON_AddObjectToObject(message, "capabilities");
    if (caps) {
        const char *commands[] = {"walk", "stop"};
        cJSON *installed = cJSON_CreateStringArray(commands, 2);
        cJSON_AddItemToObject(caps, "commands", installed);
        for (size_t i = 0; installed && i < ainekio_v2_clip_count; ++i)
            cJSON_AddItemToArray(installed, cJSON_CreateString(ainekio_v2_clips[i].command));
        /* Installed geometric assets are distinct from executable body motions.
         * No measured V2 calibration, qualified entry/stop or electrical proof
         * exists yet. Never infer readiness from having twelve sample columns. */
        cJSON_AddBoolToObject(caps, "motion", false);
        cJSON_AddBoolToObject(caps, "camera", false);
        cJSON_AddBoolToObject(caps, "microphone", false);
        cJSON_AddBoolToObject(caps, "speaker", false);
    }
    if (caps && cJSON_PrintPreallocated(message, text, sizeof(text), false)) reply(connection, text);
    else fail_link();
    cJSON_Delete(message);
}

static void received(void)
{
    if (atomic_load(&quiesced)) return;
    request_t request = {.connection=link_generation, .received_us=now_us()};
    if (ainekio_control_decode_with_output_tests(receive_text, receive_used, &request.message) != AINEKIO_DECODE_OK) {
        fail_link(); return;
    }
    ainekio_control_message_t *m = &request.message;
    enter();
    if (m->kind == AINEKIO_MESSAGE_WELCOME) {
        const bool valid = ainekio_admission_welcome(&admission, request.connection,
            m->data.welcome.epoch, m->data.welcome.profile, m->data.welcome.deadline_supported, now_us());
        leave();
        if (!valid) fail_link();
        else ESP_LOGI("controller", "Selected controller authenticated epoch=%" PRIu32, m->data.welcome.epoch);
        return;
    }
    if (!ainekio_admission_control(&admission, request.connection, now_us())) { leave(); fail_link(); return; }
    if (m->has_command && m->command.kind == AINEKIO_COMMAND_STOP) {
        /* Preserve core STOP semantics: current authenticated stops disable even
         * when duplicated. Expiry never delays this separate gate operation. */
        if (m->has_epoch && m->epoch == admission.core.epoch)
            ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
        const ainekio_decision_t decision = ainekio_admission_accept(&admission,
            request.connection, m, request.received_us, now_us(), true);
        leave();
        if (decision.accepted) ack(request.connection, m->sequence);
        else nak(request.connection, m, decision.rejection);
        return;
    }
    request.output_generation = ainekio_pca_status(ainekio_p4_output()).generation;
    leave();
    if (m->kind == AINEKIO_MESSAGE_PING) heartbeat(request.connection, true);
    else if (m->kind == AINEKIO_MESSAGE_PONG) return;
    else if (m->has_command) {
        if (xQueueSend(requests, &request, 0) != pdTRUE) fail_link();
    } else fail_link();
}

static void websocket_event(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    (void)arg; (void)base;
    if (id == WEBSOCKET_EVENT_CONNECTED) {
        receive_used = frame_received = 0;
        enter();
        if (atomic_load(&quiesced)) { leave(); fail_link(); return; }
        link_generation = ainekio_admission_open(&admission);
        leave();
        hello(link_generation);
    } else if (id == WEBSOCKET_EVENT_DISCONNECTED || id == WEBSOCKET_EVENT_ERROR) {
        enter();
        ainekio_admission_close(&admission, link_generation);
        ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
        leave();
        atomic_store(&reconnect, true);
    } else if (id == WEBSOCKET_EVENT_DATA) {
        const esp_websocket_event_data_t *data = event_data;
        if (data->op_code >= 8) return; /* WebSocket control frames belong to IDF. */
        if (data->payload_offset == 0) {
            if ((data->op_code == 1 && receive_used != 0) ||
                (data->op_code == 0 && receive_used == 0) || data->op_code > 1) { fail_link(); return; }
            frame_received = 0;
        }
        if (data->data_len < 0 || data->payload_len < 0 || data->payload_offset < 0 ||
            (size_t)data->payload_offset != frame_received ||
            data->data_len > data->payload_len - data->payload_offset ||
            receive_used + (size_t)data->data_len >= sizeof(receive_text)) { fail_link(); return; }
        memcpy(receive_text + receive_used, data->data_ptr, data->data_len);
        receive_used += data->data_len;
        frame_received += data->data_len;
        if (data->fin && frame_received == (size_t)data->payload_len) {
            receive_text[receive_used] = '\0';
            received();
            receive_used = frame_received = 0;
        }
    }
}

static void link_task(void *arg)
{
    (void)arg;
    const ainekio_config_record_t *config = ainekio_p4_config();
    for (;;) {
        if (!config || atomic_load(&quiesced) || !ainekio_p4_network_online()) { vTaskDelay(pdMS_TO_TICKS(100)); continue; }
        atomic_store(&reconnect, false);
        const esp_websocket_client_config_t options = {
            .uri=config->endpoint_url, .disable_auto_reconnect=true,
            .task_prio=5, .task_stack=16384, .buffer_size=1024,
            .network_timeout_ms=1000, .crt_bundle_attach=esp_crt_bundle_attach,
        };
        esp_websocket_client_handle_t client = esp_websocket_client_init(&options);
        if (!client) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        esp_err_t error = esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, websocket_event, NULL);
        if (error == ESP_OK) error = esp_websocket_client_start(client);
        uint64_t last_ping = now_us();
        while (error == ESP_OK && !atomic_load(&reconnect) && ainekio_p4_network_online()) {
            reply_t message;
            if (xQueueReceive(replies, &message, pdMS_TO_TICKS(20)) == pdTRUE) {
                enter();
                const bool current = admission.connected && admission.generation == message.connection;
                leave();
                if (current && esp_websocket_client_send_text(client, message.text, strlen(message.text), pdMS_TO_TICKS(100)) < 0)
                    fail_link();
            }
            if (now_us() - last_ping >= UINT64_C(1000000)) {
                enter();
                const bool authenticated = admission.authenticated;
                const uint64_t generation = admission.generation;
                leave();
                if (authenticated) heartbeat(generation, false);
                last_ping = now_us();
            }
        }
        fail_link();
        enter();
        ainekio_admission_close(&admission, link_generation);
        leave();
        esp_websocket_client_stop(client);
        esp_websocket_client_destroy(client);
        vTaskDelay(pdMS_TO_TICKS(1000)); /* Retry only the explicitly selected host. */
    }
}

void ainekio_p4_controller_supervise(void)
{
    if (!atomic_load(&initialized)) return;
    enter();
    const bool stale = ainekio_admission_check_stale(&admission, now_us());
    leave();
    if (stale) fail_link();
}

static void output_task(void *arg)
{
    (void)arg;
    const esp_task_wdt_config_t config = {.timeout_ms=100, .idle_core_mask=0, .trigger_panic=true};
    esp_err_t error = esp_task_wdt_reconfigure(&config);
    if (error == ESP_ERR_INVALID_STATE) error = esp_task_wdt_init(&config);
    ESP_ERROR_CHECK(error);
    esp_task_wdt_user_handle_t watchdog;
    ESP_ERROR_CHECK(esp_task_wdt_add_user("body progress", &watchdog));
    ainekio_pca9685_t *output = ainekio_p4_output();
    bool active = false;
    uint64_t connection=0, output_generation=0, end_us=0, next_frame=0;
    uint32_t sequence=0;
    uint16_t pulses[12] = {0};
    for (;;) {
        const uint64_t now = now_us();
        ainekio_pca_status_t status = ainekio_pca_status(output);
        if (active && (!status.armed || status.generation != output_generation)) {
            terminal(connection, sequence, false);
            active = false;
        }
        if (active && now >= end_us) {
            ainekio_pca_disarm(output);
            terminal(connection, sequence, true);
            active = false;
        }
        if (active && now >= next_frame) {
            if (ainekio_pca_write_frame(output, output_generation, pulses) == AINEKIO_PCA_OK)
                ESP_ERROR_CHECK(esp_task_wdt_reset_user(watchdog));
            /* Never execute a burst of overdue frames. The independent 40 ms
             * progress fault invalidates the run before any resumption. */
            next_frame = now_us() + UINT64_C(20000);
        }
        request_t request;
        if (xQueueReceive(requests, &request, 0) == pdTRUE) {
            ainekio_command_t *command = &request.message.command;
            uint8_t cycles;
            size_t clip_index;
            const bool supported = command->kind != AINEKIO_COMMAND_INTENT ||
                ainekio_v2_walk_request(command, &cycles) || ainekio_v2_clip_request(command, &clip_index);
            enter();
            ainekio_decision_t decision = ainekio_admission_accept(&admission, request.connection,
                &request.message, request.received_us, now_us(), supported);
            leave();
            if (!decision.accepted) nak(request.connection, &request.message, decision.rejection);
            else if (command->kind == AINEKIO_COMMAND_MODE) {
                if (command->data.mode == AINEKIO_MODE_NORMAL) ainekio_pca_disarm(output);
                ack(request.connection, command->sequence);
            } else if (command->kind == AINEKIO_COMMAND_OUTPUT_TEST) {
                if (active) { nak(request.connection, &request.message, AINEKIO_REJECT_BUSY); continue; }
                if (command->data.output_test.recover) {
                    const ainekio_pca_result_t result = ainekio_pca_recover(output, request.output_generation);
                    if (result == AINEKIO_PCA_OK) ack(request.connection, command->sequence);
                    else nak(request.connection, &request.message, AINEKIO_REJECT_UNSAFE);
                } else {
                    memset(pulses, 0, sizeof(pulses));
                    pulses[command->data.output_test.channel] = command->data.output_test.pulse_us;
                    ainekio_p4_interrupt_arm(command->data.output_test.fault == 2);
                    const ainekio_pca_result_t result = ainekio_pca_arm(output, request.output_generation, pulses);
                    ainekio_p4_interrupt_arm(false);
                    if (result != AINEKIO_PCA_OK) nak(request.connection, &request.message, AINEKIO_REJECT_UNSAFE);
                    else {
                        active = true;
                        sequence = command->sequence;
                        connection = request.connection;
                        output_generation = request.output_generation;
                        end_us = now_us() + (uint64_t)command->data.output_test.duration_ms * 1000U;
                        next_frame = now_us() + UINT64_C(20000);
                        ack(connection, sequence);
                        ESP_ERROR_CHECK(esp_task_wdt_reset_user(watchdog));
                        if (command->data.output_test.fault == 1) vTaskDelay(pdMS_TO_TICKS(200));
                        if (command->data.output_test.fault == 3) { vTaskDelay(pdMS_TO_TICKS(20)); esp_restart(); }
                    }
                }
            } else {
                /* No calibrated actuator executor is bound yet. Never turn
                 * an installed geometric asset into a successful no-op. */
                nak(request.connection, &request.message, AINEKIO_REJECT_UNSAFE);
            }
        }
        status = ainekio_pca_status(output);
        if (!status.armed && !status.in_flight) ESP_ERROR_CHECK(esp_task_wdt_reset_user(watchdog));
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

esp_err_t ainekio_p4_controller_start(void)
{
    ainekio_admission_init(&admission, AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_INTENT) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STOP) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MODE) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_OUTPUT_TEST), true);
    requests = xQueueCreate(8, sizeof(request_t));
    replies = xQueueCreate(16, sizeof(reply_t));
    if (!requests || !replies) return ESP_ERR_NO_MEM;
    atomic_store(&initialized, true);
    if (xTaskCreatePinnedToCore(output_task, "body_output", 6144, NULL, 10, NULL, 1) != pdPASS ||
        xTaskCreate(link_task, "controller", 6144, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    return ESP_OK;
}

int ainekio_p4_controller_command(int argc, char **argv)
{
    (void)argc; (void)argv;
    enter();
    const uint64_t generation = admission.generation;
    const uint32_t epoch = admission.core.epoch;
    const bool connected = admission.connected, authenticated = admission.authenticated;
    leave();
    const ainekio_config_record_t *config = ainekio_p4_config();
    printf("controller configured=%d connected=%d authenticated=%d generation=%" PRIu64 " epoch=%" PRIu32 "\n",
           config != NULL, connected, authenticated, generation, epoch);
    puts("motion=unavailable camera=unavailable microphone=unavailable speaker=unavailable");
    printf("installed walk=%s joints=%u hardware_qualified=%d; use gait for geometric diagnostics\n",
           ainekio_v2_walk_id, AINEKIO_V2_JOINT_COUNT, ainekio_v2_walk_hardware_qualified);
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i)
        printf("installed %s duration_ms=%" PRIu64 " heading_deg=%d hardware_qualified=%d\n",
               ainekio_v2_clips[i].command, ainekio_v2_clips[i].duration_us / 1000U,
               ainekio_v2_clips[i].heading_degrees, ainekio_v2_clips[i].hardware_qualified);
    return 0;
}

int ainekio_p4_gait_command(int argc, char **argv)
{
    const bool walk = argc == 4 && strcmp(argv[1], "walk") == 0;
    if (!walk && argc != 3) {
        puts("gait walk <steps 1..10> <elapsed-ms>\n"
             "gait <installed-command> <elapsed-ms>; list names with controller\n"
             "Samples installed CAD motion only; never drives PWM or reports movement completion.");
        return 1;
    }
    char *end;
    unsigned long steps = 0;
    if (walk) {
        errno = 0;
        steps = strtoul(argv[2], &end, 10);
        if (errno || *end || end == argv[2] || steps < 1 || steps > 10) return 1;
    }
    const char *time_arg = argv[walk ? 3 : 2];
    errno = 0;
    const unsigned long elapsed = strtoul(time_arg, &end, 10);
    if (errno || *end || end == time_arg || time_arg[0] == '-' || elapsed > 60400) return 1;
    ainekio_v2_frame_t frame;
    if (walk) {
        if (!ainekio_v2_walk_sample(steps, (uint64_t)elapsed*1000U, &frame)) return 1;
        printf("walk steps=%lu duration_ms=%" PRIu64 " phase=%d cycle=%u hardware_ready=0\n",
               steps, ainekio_v2_walk_duration_us(steps)/1000U, frame.phase, frame.cycle);
    } else {
        size_t index;
        if (!ainekio_v2_clip_find(argv[1], &index) ||
            !ainekio_v2_clip_sample(index, (uint64_t)elapsed*1000U, &frame)) return 1;
        printf("%s duration_ms=%" PRIu64 " phase=%d heading_deg=%d hardware_ready=0\n",
               ainekio_v2_clips[index].command, ainekio_v2_clips[index].duration_us / 1000U,
               frame.phase, ainekio_v2_clips[index].heading_degrees);
    }
    for (size_t j=0; j<AINEKIO_V2_JOINT_COUNT; ++j)
        printf("%s CAD_cdeg=%.5f cdeg_s=%.5f cdeg_s2=%.5f\n",ainekio_v2_joints[j].name,
               (double)frame.position[j],(double)frame.velocity[j],(double)frame.acceleration[j]);
    return 0;
}
