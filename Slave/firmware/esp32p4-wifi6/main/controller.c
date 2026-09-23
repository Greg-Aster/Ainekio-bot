#include "controller.h"
#include "board.h"
#include "config.h"
#include "ainekio/v2_limits.h"
#include "network.h"
#include "body.h"
#include "system.h"
#include "storage.h"
#include "ainekio/p4_media.h"
#include "ainekio/binary_codec.h"
#include "ainekio/admission.h"
#include "ainekio/control_encode.h"
#include "ainekio/v2_motion.h"
#include "ainekio/v2_walk.h"

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
#include "esp_wifi.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

typedef struct {
    uint64_t connection, output_generation, received_us;
    bool admitted_stop;
    ainekio_control_message_t message;
} request_t;
typedef struct {
    uint64_t connection;
    char *text;
} reply_t;
typedef struct {
    uint64_t connection;
    uint32_t sequence;
    char text[192];
} media_event_t;
typedef struct {
    uint64_t connection;
    uint8_t *bytes;
    size_t length;
    uint32_t done_sequence;
    char metadata[192];
} packet_t;

static portMUX_TYPE admission_lock = portMUX_INITIALIZER_UNLOCKED;
static ainekio_admission_t admission;
static QueueHandle_t requests, replies;
static QueueHandle_t audio_packets, camera_packets, media_events;
/* Only this command's completion waits for its ACK/NAK to enter replies.
 * Media streaming and unrelated completions never wait for command execution. */
static atomic_uint pending_sequence;
static atomic_uint microphone_counter, microphone_tx_drops, camera_tx_drops;
static atomic_uint stopped_sequence;
static atomic_uchar camera_fps;
static atomic_bool initialized, reconnect, quiesced;
/* One WebSocket instance at a time. The link task drains/stops the old client
 * before creating another; queued results can never cross into its successor. */
static uint64_t link_generation;
static char receive_text[4097];
static size_t receive_used, frame_received;
static uint8_t receive_opcode;

static void cancel_audio(uint64_t connection, ainekio_cancel_code_t code);
static void telemetry(uint64_t connection);

static uint64_t now_us(void) { return esp_timer_get_time(); }
static void enter(void) { portENTER_CRITICAL(&admission_lock); }
static void leave(void) { portEXIT_CRITICAL(&admission_lock); }

static void fail_link(void)
{
    enter();
    const bool had_controller = admission.authenticated;
    if (admission.connected) ainekio_admission_close(&admission, admission.generation);
    if (had_controller) ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
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
    reply_t response = {.connection=connection, .text=strdup(text)};
    if (!response.text) { fail_link(); return; }
    if (xQueueSend(replies, &response, 0) != pdTRUE) {
        free(response.text);
        fail_link();
    }
}

static void nak(uint64_t connection, const ainekio_control_message_t *m, ainekio_reject_reason_t reason)
{
    static const ainekio_nak_code_t codes[] = {
        AINEKIO_NAK_UNKNOWN, AINEKIO_NAK_STALE, AINEKIO_NAK_MODE, AINEKIO_NAK_UNSAFE,
        AINEKIO_NAK_LIMIT, AINEKIO_NAK_UNKNOWN, AINEKIO_NAK_BUSY, AINEKIO_NAK_PROFILE,
        AINEKIO_NAK_ASSET_MISSING, AINEKIO_NAK_MALFORMED,
    };
    char text[180];
    const char *detail = reason == AINEKIO_REJECT_LIMIT ?
        "Command parameters are outside their supported range" :
        reason == AINEKIO_REJECT_BUSY ? "Body is busy, asleep, or its outputs are unavailable" : NULL;
    ainekio_encode_nak(m->has_sequence, m->sequence, codes[reason], detail, text, sizeof(text));
    reply(connection, text);
}

static void execution_failed(uint64_t connection, uint32_t sequence, esp_err_t error)
{
    const ainekio_p4_system_status_t system = ainekio_p4_system_status();
    const ainekio_pca_status_t output = ainekio_pca_status(ainekio_p4_output());
    const ainekio_nak_code_t code = error == ESP_ERR_INVALID_ARG || error == AINEKIO_P4_ERR_REFERENCE ? AINEKIO_NAK_LIMIT :
        error == ESP_ERR_NOT_FOUND ? AINEKIO_NAK_ASSET_MISSING : AINEKIO_NAK_BUSY;
    const char *detail = error == AINEKIO_P4_ERR_REFERENCE ? "Commanded pose cannot close the leg linkage" :
        error == ESP_ERR_INVALID_ARG ? "Motion mapping failed or pulse exceeds PWM timer capacity" :
        error == ESP_ERR_NOT_FOUND ? "Requested asset is unavailable" :
        output.fault == AINEKIO_PCA_FAULT_IO ? "Servo controller I2C transfer failed" :
        output.fault == AINEKIO_PCA_FAULT_DEADLINE ? "Servo controller I2C transfer missed its deadline" :
        output.fault == AINEKIO_PCA_FAULT_PROGRESS ? "Servo frame update missed its deadline" :
        error == ESP_ERR_TIMEOUT ? "Command or motion update missed its deadline" :
        system.restart_pending ? "Restart is pending" :
        system.state == AINEKIO_STATE_DOZING || system.state == AINEKIO_STATE_DEEP_SLEEP ? "Body is asleep; select Idle before moving" :
        error == ESP_ERR_NO_MEM ? "Body lacks memory or command queue space" :
        output.fault ? "Motion stopped after execution failed" :
        "Command could not execute; read body status and retry";
    char text[192];
    ainekio_encode_nak(true, sequence, code, detail, text, sizeof(text));
    reply(connection, text);
}

static void heartbeat(uint64_t connection, bool pong)
{
    char text[96];
    snprintf(text, sizeof(text), "{\"t\":\"%s\",\"clock_ms\":%" PRIu64 "}",
             pong ? "pong" : "ping", now_us() / 1000U);
    reply(connection, text);
}

static ainekio_capabilities_t capabilities(const ainekio_p4_media_status_t *media,
    const ainekio_p4_calibration_t *calibration, const char **commands)
{
    const char *base[] = {"stop", "say", "stand", "neutral", "walk", "backward", "left", "right", "crawl", "run"};
    size_t count = sizeof(base)/sizeof(base[0]);
    memcpy(commands, base, sizeof(base));
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i) {
        bool duplicate = false;
        for (size_t j = 0; j < count; ++j)
            if (strcmp(commands[j], ainekio_v2_clips[i].command) == 0) duplicate = true;
        if (!duplicate) commands[count++] = ainekio_v2_clips[i].command;
    }
    return (ainekio_capabilities_t){.commands=commands, .command_count=count,
        .motion=calibration->valid && calibration->profile_confirmed && atomic_load(&initialized), .camera=media->camera_ready,
        .microphone=media->microphone_ready, .speaker=media->speaker_ready, .wake=media->wake_ready,
        .profile=true, .power=true, .storage=true,
        .motion_reason=!calibration->valid ? "Joint calibration is invalid." : !calibration->profile_confirmed ? "Review and Save joint calibration for the current servo profile." : NULL,
        .display_reason="Display hardware selection and implementation are deferred.",
        .camera_reason=media->camera_ready ? NULL : "OV5647 camera is not ready.",
        .microphone_reason=media->microphone_ready ? NULL : "Onboard audio input is not ready.",
        .speaker_reason=media->speaker_ready ? NULL : "Onboard audio output is not ready."};
}

static void hello(uint64_t connection)
{
    const ainekio_config_record_t *config = ainekio_p4_config();
    const ainekio_p4_media_status_t media = ainekio_p4_media_status();
    const ainekio_p4_calibration_t calibration = ainekio_p4_calibration();
    const char *commands[10 + ainekio_v2_clip_count];
    const ainekio_capabilities_t caps = capabilities(&media, &calibration, commands);
    const char *features[] = {"command_deadline_v1", "body_capabilities_v1", "body_commands_v1", "body_calibration_v2", "storage_control_v1", "walk_controls_v2", "run_gait_v1"};
    const ainekio_hello_t message = {.firmware=esp_app_get_description()->version,
        .robot_id=config->robot_id, .auth_token=config->robot_token,
        .features=features, .feature_count=sizeof(features)/sizeof(features[0]),
        .model="v2-12servo", .clock_ms=now_us()/1000U, .capabilities=&caps};
    char text[4096];
    if (ainekio_encode_hello(&message, text, sizeof(text))) reply(connection, text);
    else fail_link();
}

static void received(void)
{
    if (atomic_load(&quiesced)) return;
    request_t request = {.connection=link_generation, .received_us=now_us()};
    if (ainekio_control_decode_for_body(receive_text, receive_used, &request.message) != AINEKIO_DECODE_OK) {
        fail_link(); return;
    }
    ainekio_control_message_t *m = &request.message;
    enter();
    if (m->kind == AINEKIO_MESSAGE_WELCOME) {
        const bool valid = ainekio_admission_welcome(&admission, request.connection,
            m->data.welcome.epoch, m->data.welcome.profile, m->data.welcome.deadline_supported, now_us());
        leave();
        if (!valid) fail_link();
        else {
            atomic_store(&stopped_sequence, 0);
            ainekio_p4_media_session(request.connection);
            if (ainekio_p4_system_profile(m->data.welcome.profile) != ESP_OK ||
                ainekio_p4_system_authenticated() != ESP_OK) { fail_link(); return; }
            telemetry(request.connection);
            ESP_LOGI("controller", "Selected controller authenticated epoch=%" PRIu32, m->data.welcome.epoch);
        }
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
        if (decision.accepted) {
            atomic_store(&stopped_sequence, m->sequence);
            /* Motor OE is already high. Serialize remaining cancellation after
             * any command admitted just before STOP, then acknowledge it. */
            request.admitted_stop = true;
            if (xQueueSend(requests, &request, 0) != pdTRUE) fail_link();
        } else nak(request.connection, m, decision.rejection);
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
        receive_opcode = 0;
        enter();
        if (atomic_load(&quiesced)) { leave(); fail_link(); return; }
        link_generation = ainekio_admission_open(&admission);
        leave();
        hello(link_generation);
    } else if (id == WEBSOCKET_EVENT_DISCONNECTED || id == WEBSOCKET_EVENT_ERROR) {
        enter();
        const bool had_controller = admission.authenticated;
        ainekio_admission_close(&admission, link_generation);
        if (had_controller) ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
        leave();
        atomic_store(&reconnect, true);
    } else if (id == WEBSOCKET_EVENT_DATA) {
        const esp_websocket_event_data_t *data = event_data;
        if (data->op_code >= 8) return; /* WebSocket control frames belong to IDF. */
        if (data->payload_offset == 0) {
            if ((data->op_code != 0 && receive_opcode != 0) ||
                (data->op_code == 0 && receive_opcode == 0) || data->op_code > 2) { fail_link(); return; }
            if (data->op_code != 0) receive_opcode = data->op_code;
            frame_received = 0;
        }
        if (data->data_len < 0 || data->payload_len < 0 || data->payload_offset < 0 ||
            (size_t)data->payload_offset != frame_received ||
            data->data_len > data->payload_len - data->payload_offset ||
            receive_used + (size_t)data->data_len >= sizeof(receive_text) ||
            (receive_opcode == 2 && receive_used + (size_t)data->data_len >
             AINEKIO_BINARY_HEADER_BYTES + AINEKIO_AUDIO_PAYLOAD_BYTES)) { fail_link(); return; }
        memcpy(receive_text + receive_used, data->data_ptr, data->data_len);
        receive_used += data->data_len;
        frame_received += data->data_len;
        if (data->fin && frame_received == (size_t)data->payload_len) {
            receive_text[receive_used] = '\0';
            if (receive_opcode == 1) received();
            else {
                enter();
                const bool current = ainekio_admission_control(&admission, link_generation, now_us());
                leave();
                ainekio_binary_frame_t frame;
                if (!current || ainekio_binary_decode((uint8_t *)receive_text, receive_used, &frame) != AINEKIO_BINARY_OK ||
                    frame.type != AINEKIO_FRAME_SPEAKER_PCM) fail_link();
                else if (ainekio_p4_media_tts_push(frame.payload) != ESP_OK)
                    cancel_audio(link_generation, AINEKIO_CANCEL_OVERFLOW);
            }
            receive_used = frame_received = 0;
            receive_opcode = 0;
        }
    }
}

static void media_event(uint64_t connection, uint32_t sequence, const char *text)
{
    media_event_t event = {.connection=connection, .sequence=sequence};
    if (strlen(text) >= sizeof(event.text)) { fail_link(); return; }
    strcpy(event.text, text);
    if (xQueueSend(media_events, &event, 0) != pdTRUE) fail_link();
}

static void microphone(void *context, uint64_t session, const uint8_t *pcm)
{
    (void)context;
    packet_t packet = {.connection=session};
    packet.length = AINEKIO_BINARY_HEADER_BYTES + AINEKIO_AUDIO_PAYLOAD_BYTES;
    packet.bytes = malloc(packet.length);
    if (!packet.bytes) { atomic_fetch_add(&microphone_tx_drops, 1); return; }
    size_t length;
    if (ainekio_binary_encode(AINEKIO_FRAME_MIC_PCM, atomic_fetch_add(&microphone_counter, 1),
        pcm, AINEKIO_AUDIO_PAYLOAD_BYTES, packet.bytes, packet.length, &length) != AINEKIO_BINARY_OK ||
        xQueueSend(audio_packets, &packet, 0) != pdTRUE) {
        free(packet.bytes);
        atomic_fetch_add(&microphone_tx_drops, 1);
    }
}

static void audio_done(void *context, uint64_t session, uint32_t sequence, esp_err_t result)
{
    (void)context;
    char text[192];
    if (result == ESP_OK) ainekio_encode_done(sequence, text, sizeof(text));
    else ainekio_encode_nak(true, sequence, AINEKIO_NAK_BUSY, "audio playback failed", text, sizeof(text));
    media_event(session, sequence, text);
}

static void gate_event(void *context, uint64_t session, bool open, bool wake_word)
{
    (void)context;
    char text[128];
    ainekio_encode_event(wake_word ? AINEKIO_EVENT_WAKE_WORD :
        open ? AINEKIO_EVENT_VAD_OPEN : AINEKIO_EVENT_VAD_CLOSE, false, 0, text, sizeof(text));
    media_event(session, 0, text);
}

static void camera_failed(void *context, uint64_t session, ainekio_camera_origin_t origin,
                          uint32_t origin_id, esp_err_t result)
{
    (void)context; (void)result;
    if (origin == AINEKIO_CAMERA_ORIGIN_REQUEST) {
        char text[192];
        ainekio_encode_nak(true, origin_id, AINEKIO_NAK_BUSY, "camera capture or transmit queue failed", text, sizeof(text));
        media_event(session, origin_id, text);
    }
}

static void camera_frame(void *context, uint64_t session, ainekio_camera_origin_t origin,
                         uint32_t origin_id, ainekio_camera_resolution_t resolution,
                         uint32_t counter, const uint8_t *jpeg, size_t length)
{
    (void)context;
    if (length > AINEKIO_MAX_JPEG_BYTES) { camera_failed(NULL, session, origin, origin_id, ESP_ERR_INVALID_SIZE); return; }
    packet_t packet = {.connection=session, .length=length+AINEKIO_BINARY_HEADER_BYTES,
        .done_sequence=origin == AINEKIO_CAMERA_ORIGIN_REQUEST ? origin_id : 0};
    packet.bytes = heap_caps_malloc(packet.length, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    size_t encoded;
    if (!packet.bytes || !ainekio_encode_camera_meta(resolution, atomic_load(&camera_fps), counter,
        origin, origin_id, packet.metadata, sizeof(packet.metadata)) ||
        ainekio_binary_encode(AINEKIO_FRAME_CAMERA_JPEG, counter, jpeg, length,
            packet.bytes, packet.length, &encoded) != AINEKIO_BINARY_OK ||
        xQueueSend(camera_packets, &packet, 0) != pdTRUE) {
        free(packet.bytes);
        atomic_fetch_add(&camera_tx_drops, 1);
        camera_failed(NULL, session, origin, origin_id, ESP_ERR_NO_MEM);
    }
    if (origin != AINEKIO_CAMERA_ORIGIN_NONE) ainekio_p4_storage_capture(jpeg, length);
}

esp_err_t ainekio_p4_controller_media_start(void)
{
    const ainekio_p4_media_callbacks_t callbacks = {.microphone=microphone, .audio_done=audio_done,
        .gate=gate_event, .camera_frame=camera_frame, .camera_failed=camera_failed};
    return ainekio_p4_media_start(&callbacks);
}

static void telemetry(uint64_t connection)
{
    const ainekio_p4_media_status_t media = ainekio_p4_media_status();
    const ainekio_p4_system_status_t system = ainekio_p4_system_status();
    const ainekio_p4_calibration_t calibration = ainekio_p4_calibration();
    const ainekio_pca_status_t output = ainekio_pca_status(ainekio_p4_output());
    wifi_ap_record_t ap = {0};
    esp_wifi_sta_get_ap_info(&ap);
    enter();
    const ainekio_mode_t mode = admission.core.mode;
    const ainekio_body_state_t state = system.state == AINEKIO_STATE_DOZING ||
        system.state == AINEKIO_STATE_DEEP_SLEEP ? system.state : admission.core.state;
    leave();
    ainekio_status_t status = {.rssi=ap.rssi, .state=state, .uptime_seconds=system.uptime_ms/1000U,
        .free_heap=system.heap_free, .sd_available=ainekio_p4_storage_status().mounted,
        .camera_ready=media.camera_ready, .camera_drops=media.camera_failures+atomic_load(&camera_tx_drops),
        .speaker_underruns=media.speaker_underruns,
        .microphone_drops=media.microphone_drops+atomic_load(&microphone_tx_drops),
        .wake_enabled=media.wake_enabled, .wake_ready=media.wake_ready};
    memcpy(status.wake_model, media.wake_model, sizeof(status.wake_model));
    if (!status.wake_model[0]) strcpy(status.wake_model, AINEKIO_DEFAULT_WAKE_MODEL);
    const char *commands[10 + ainekio_v2_clip_count];
    const ainekio_capabilities_t caps = capabilities(&media, &calibration, commands);
    ainekio_body_status_fields_t body = {.mode=mode, .output_ready=output.ready,
        .output_armed=output.armed, .output_fault=output.fault,
        .calibration_dirty=calibration.dirty, .calibration_saved=calibration.saved,
        .power_monitor_ready=system.battery_available, .microphone_ready=media.microphone_ready,
        .speaker_ready=media.speaker_ready, .capabilities=&caps};
    status.body = &body;
    char text[4096];
    if (!ainekio_encode_status(&status, text, sizeof(text))) { fail_link(); return; }
    reply(connection, text);
    if (status.uptime_seconds % 5U == 0U) {
        /* Store changing measurements, not the repeated command catalog. */
        body.capabilities = NULL;
        const size_t length = ainekio_encode_status(&status, text, sizeof(text));
        if (length) ainekio_p4_storage_record(1, text, length);
    }
}

static bool current_connection(uint64_t generation)
{
    enter();
    const bool current = admission.connected && admission.generation == generation;
    leave();
    return current;
}

static void send_packet(esp_websocket_client_handle_t client, packet_t *packet)
{
    if (current_connection(packet->connection) &&
        (!packet->done_sequence || packet->done_sequence > atomic_load(&stopped_sequence))) {
        const size_t metadata_length = strlen(packet->metadata);
        const bool metadata_ok = metadata_length == 0 ||
            esp_websocket_client_send_text(client, packet->metadata, metadata_length, pdMS_TO_TICKS(100)) == (int)metadata_length;
        if (!metadata_ok || !current_connection(packet->connection) ||
            esp_websocket_client_send_bin(client, (const char *)packet->bytes, packet->length, pdMS_TO_TICKS(250)) != (int)packet->length)
            fail_link();
        else if (packet->done_sequence) {
            char text[80];
            ainekio_encode_done(packet->done_sequence, text, sizeof(text));
            reply(packet->connection, text);
        }
    }
    free(packet->bytes);
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
        uint64_t last_ping = now_us(), last_status = now_us();
        ainekio_p4_body_event_t event = {0};
        bool have_body_event = false;
        while (error == ESP_OK && !atomic_load(&reconnect) && ainekio_p4_network_online()) {
            reply_t message;
            if (xQueueReceive(replies, &message, pdMS_TO_TICKS(20)) == pdTRUE) {
                enter();
                const bool current = admission.connected && admission.generation == message.connection;
                leave();
                if (current && esp_websocket_client_send_text(client, message.text, strlen(message.text), pdMS_TO_TICKS(100)) != (int)strlen(message.text))
                    fail_link();
                free(message.text);
            }
            if (!have_body_event) have_body_event = ainekio_p4_body_event(&event);
            if (have_body_event && event.sequence != atomic_load(&pending_sequence)) {
                if (current_connection(event.connection)) {
                    char result[192];
                    const bool stopped = event.sequence <= atomic_load(&stopped_sequence);
                    if (stopped)
                        ainekio_encode_cancelled(event.sequence, AINEKIO_CANCEL_STOP, result, sizeof(result));
                    else if (event.result != ESP_OK)
                        execution_failed(event.connection, event.sequence, event.result);
                    else if (event.completed)
                        ainekio_encode_done(event.sequence, result, sizeof(result));
                    else ainekio_encode_cancelled(event.sequence, event.reason, result, sizeof(result));
                    if (stopped || event.result == ESP_OK) reply(event.connection, result);
                }
                have_body_event = false;
            }
            media_event_t media;
            if (xQueuePeek(media_events, &media, 0) == pdTRUE &&
                (!media.sequence || media.sequence != atomic_load(&pending_sequence))) {
                xQueueReceive(media_events, &media, 0);
                if (current_connection(media.connection)) reply(media.connection, media.text);
            }
            packet_t packet;
            if (xQueueReceive(audio_packets, &packet, 0) == pdTRUE) send_packet(client, &packet);
            if (xQueuePeek(camera_packets, &packet, 0) == pdTRUE &&
                (!packet.done_sequence || (packet.done_sequence != atomic_load(&pending_sequence) &&
                                          uxQueueMessagesWaiting(replies) == 0))) {
                xQueueReceive(camera_packets, &packet, 0);
                send_packet(client, &packet);
            }
            /* The gateway requires a clock observation younger than one second.
             * Leave margin for scheduling and network delay within that window. */
            if (now_us() - last_ping >= UINT64_C(250000)) {
                enter();
                const bool authenticated = admission.authenticated;
                const uint64_t generation = admission.generation;
                leave();
                if (authenticated) {
                    heartbeat(generation, false);
                    const uint64_t interval = ainekio_p4_system_status().profile == AINEKIO_PROFILE_TETHER ?
                        UINT64_C(30000000) : UINT64_C(5000000);
                    if (now_us() - last_status >= interval) { telemetry(generation); last_status=now_us(); }
                }
                last_ping = now_us();
            }
        }
        fail_link();
        enter();
        ainekio_admission_close(&admission, link_generation);
        leave();
        ainekio_p4_media_disconnect();
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

static void calibration_status(const request_t *request)
{
    const ainekio_p4_calibration_t state = ainekio_p4_calibration();
    const ainekio_pca_status_t output = ainekio_pca_status(ainekio_p4_output());
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    ainekio_p4_body_pulses(pulses);
    cJSON *message = cJSON_CreateObject();
    if (!message) { fail_link(); return; }
    cJSON_AddStringToObject(message, "t", "calibration_status");
    cJSON_AddNumberToObject(message, "seq", request->message.sequence);
    cJSON_AddBoolToObject(message, "dirty", state.dirty);
    cJSON_AddBoolToObject(message, "saved", state.saved);
    cJSON_AddBoolToObject(message, "profile_confirmed", state.profile_confirmed);
    cJSON_AddStringToObject(message, "servo_profile_id", ainekio_v2_servo_profile_id());
    cJSON_AddNumberToObject(message, "recommended_reference_us", ainekio_v2_pulse_reference());
    cJSON_AddNumberToObject(message, "provisional_us_per_degree", ainekio_v2_us_per_degree());
    cJSON_AddBoolToObject(message, "shaft_travel_measured", false);
    cJSON_AddBoolToObject(message, "ready", state.valid && output.ready);
    uint16_t pulse_min, pulse_max;
    if (ainekio_pca_pulse_bounds(ainekio_p4_output(), &pulse_min, &pulse_max)) {
        cJSON_AddNumberToObject(message, "pulse_min_us", pulse_min);
        cJSON_AddNumberToObject(message, "pulse_max_us", pulse_max);
    }
    cJSON *joints = cJSON_AddArrayToObject(message, "joints");
    for (size_t i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i) {
        const ainekio_p4_joint_config_t *joint = &state.joints[i];
        cJSON *entry = cJSON_CreateObject();
        if (!entry || !joints) { cJSON_Delete(entry); cJSON_Delete(message); fail_link(); return; }
        cJSON_AddItemToArray(joints, entry);
        cJSON_AddNumberToObject(entry, "id", i);
        cJSON_AddNumberToObject(entry, "channel", joint->channel);
        cJSON_AddNumberToObject(entry, "home_us", joint->home_us);
        cJSON_AddBoolToObject(entry, "invert", joint->invert);
        cJSON_AddNumberToObject(entry, "home_cd", joint->home_cd);
        cJSON_AddNumberToObject(entry, "recommended_home_cd", 100.*ainekio_v2_center_degrees(i));
        cJSON_AddNumberToObject(entry, "us_per_degree", joint->us_per_degree);
        cJSON_AddNumberToObject(entry, "pulse_us", joint->channel < 0 ? 0 : pulses[joint->channel]);
    }
    char text[4096];
    if (cJSON_PrintPreallocated(message, text, sizeof(text), false)) reply(request->connection, text);
    else fail_link();
    cJSON_Delete(message);
}

static void storage_status(const request_t *request)
{
    const ainekio_p4_storage_status_t status = ainekio_p4_storage_status();
    cJSON *message = cJSON_CreateObject();
    if (!message) { fail_link(); return; }
    cJSON_AddStringToObject(message, "t", "storage_status");
    cJSON_AddNumberToObject(message, "seq", request->message.sequence);
    cJSON_AddBoolToObject(message, "available", true);
    cJSON_AddBoolToObject(message, "mounted", status.mounted);
    cJSON_AddBoolToObject(message, "busy", status.busy);
    cJSON_AddNumberToObject(message, "total_bytes", status.total_bytes);
    cJSON_AddNumberToObject(message, "free_bytes", status.free_bytes > status.total_bytes ? status.total_bytes : status.free_bytes);
    cJSON_AddNumberToObject(message, "dropped_records", status.dropped_records);
    cJSON_AddStringToObject(message, "error", status.last_error == ESP_OK ? "" : esp_err_to_name(status.last_error));
    char text[768];
    if (cJSON_PrintPreallocated(message, text, sizeof(text), false)) reply(request->connection, text);
    else fail_link();
    cJSON_Delete(message);
}

static esp_err_t calibrate(const request_t *request)
{
    const ainekio_command_t *command = &request->message.command;
    const typeof(command->data.calibration) *c = &command->data.calibration;
    if (c->operation == AINEKIO_CALIBRATION_GET) return ESP_OK;
    if (c->operation == AINEKIO_CALIBRATION_SAVE) {
        ainekio_pca_disarm(ainekio_p4_output());
        return ainekio_p4_calibration_save();
    }
    if (c->operation == AINEKIO_CALIBRATION_SET) {
        const ainekio_p4_calibration_t current = ainekio_p4_calibration();
        if (c->id < 0 || c->id >= AINEKIO_BODY_JOINT_COUNT) return ESP_ERR_INVALID_ARG;
        ainekio_p4_joint_config_t joint = current.joints[c->id];
        joint.channel = c->channel;
        joint.home_us = c->home_us;
        joint.invert = c->invert;
        if (c->has_mapping) { joint.home_cd = c->home_cd; joint.us_per_degree = c->us_per_degree; }
        /* Changing the channel map invalidates every queued pulse frame. */
        ainekio_pca_disarm(ainekio_p4_output());
        return ainekio_p4_calibration_stage(c->id, &joint);
    }
    const ainekio_p4_calibration_t state = ainekio_p4_calibration();
    if (!state.valid) return ESP_ERR_INVALID_STATE;
    if (c->operation == AINEKIO_CALIBRATION_HOME && c->id < 0) {
        uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
        if (!ainekio_p4_home_pulses(pulses)) return ESP_ERR_INVALID_STATE;
        return ainekio_p4_body_home(request->output_generation, pulses);
    }
    if (c->id < 0 || c->id >= AINEKIO_BODY_JOINT_COUNT) return ESP_ERR_INVALID_ARG;
    const ainekio_p4_joint_config_t *joint = &state.joints[c->id];
    if (joint->channel < 0) return ESP_ERR_INVALID_STATE;
    const uint16_t pulse = c->operation == AINEKIO_CALIBRATION_HOME ? joint->home_us : c->pulse_us;
    /* Manual and generated pulses use the same driver timer capacity. */
    return ainekio_p4_body_move(request->output_generation, joint->channel, pulse);
}

static void done(uint64_t connection, uint32_t sequence)
{
    char text[80];
    ainekio_encode_done(sequence, text, sizeof(text));
    reply(connection, text);
}

static void cancel_audio(uint64_t connection, ainekio_cancel_code_t code)
{
    const uint32_t sequence = ainekio_p4_media_audio_cancel();
    if (sequence) {
        char text[100];
        ainekio_encode_cancelled(sequence, code, text, sizeof(text));
        reply(connection, text);
    }
}

static esp_err_t apply(const request_t *request)
{
    const ainekio_command_t *command = &request->message.command;
    if (command->kind != AINEKIO_COMMAND_STOP && ainekio_p4_system_status().restart_pending)
        return ESP_ERR_INVALID_STATE;
    switch (command->kind) {
    case AINEKIO_COMMAND_STOP:
        cancel_audio(request->connection, AINEKIO_CANCEL_STOP);
        ainekio_p4_media_cancel_snapshots();
        return ESP_OK;
    case AINEKIO_COMMAND_BODY_CALIBRATION: return calibrate(request);
    case AINEKIO_COMMAND_STORAGE:
        if (command->data.storage_operation == AINEKIO_STORAGE_RETRY) return ainekio_p4_storage_retry();
        if (command->data.storage_operation == AINEKIO_STORAGE_CLEAR) return ainekio_p4_storage_clear();
        return ESP_OK;
    case AINEKIO_COMMAND_WAKE_CONFIG:
        ainekio_pca_disarm(ainekio_p4_output());
        return ainekio_p4_media_wake_configure(command->data.wake.enabled, command->data.wake.model);
    case AINEKIO_COMMAND_INTENT:
        if (command->data.intent.kind == AINEKIO_INTENT_SAY)
            return ainekio_p4_media_say(command->sequence, command->data.intent.data.asset);
        return ainekio_p4_body_execute(request->output_generation, request->connection, command);
    case AINEKIO_COMMAND_MODE:
        if (command->data.mode == AINEKIO_MODE_CALIBRATE) {
            ainekio_pca_disarm(ainekio_p4_output());
            return ainekio_p4_body_prepare(ainekio_pca_status(ainekio_p4_output()).generation);
        }
        return ainekio_p4_body_hold(request->output_generation);
    case AINEKIO_COMMAND_PROFILE:
        return ainekio_p4_system_profile(command->data.profile);
    case AINEKIO_COMMAND_STATE:
        if (command->data.state.request != AINEKIO_STATE_REQUEST_IDLE)
            cancel_audio(request->connection, AINEKIO_CANCEL_STOP);
        {
            const esp_err_t result = ainekio_p4_system_state(command->data.state.request, command->data.state.sleep_seconds);
            return result;
        }
    case AINEKIO_COMMAND_MICROPHONE:
        return ainekio_p4_media_microphone(command->data.microphone.enabled, command->data.microphone.gate);
    case AINEKIO_COMMAND_CAMERA:
        {
            esp_err_t result = ainekio_p4_media_camera_configure(command->data.camera.enabled,
                command->data.camera.fps, command->data.camera.resolution);
            if (result == ESP_OK) atomic_store(&camera_fps, command->data.camera.enabled ? command->data.camera.fps : 0);
            return result;
        }
    case AINEKIO_COMMAND_SNAPSHOT:
        return ainekio_p4_media_snapshot(AINEKIO_CAMERA_ORIGIN_REQUEST, command->sequence);
    case AINEKIO_COMMAND_TTS:
        if (command->data.tts_operation == AINEKIO_TTS_START)
            return ainekio_p4_media_tts_start(command->sequence);
        if (command->data.tts_operation == AINEKIO_TTS_END) return ainekio_p4_media_tts_end();
        cancel_audio(request->connection, AINEKIO_CANCEL_STOP);
        return ESP_OK;
    default: return ESP_ERR_NOT_SUPPORTED;
    }
}

static void control_task(void *arg)
{
    (void)arg;
    request_t request;
    for (;;) {
        if (xQueueReceive(requests, &request, portMAX_DELAY) != pdTRUE) continue;
        atomic_store(&pending_sequence, request.message.command.sequence);
        const ainekio_command_t *command = &request.message.command;
        const ainekio_p4_system_status_t system = ainekio_p4_system_status();
        enter();
        ainekio_core_set_profile(&admission.core, system.profile);
        if (system.state == AINEKIO_STATE_DOZING || system.state == AINEKIO_STATE_DEEP_SLEEP)
            ainekio_core_set_state(&admission.core, system.state);
        const ainekio_profile_t previous_profile = admission.core.profile;
        const ainekio_body_state_t previous_state = admission.core.state;
        const ainekio_mode_t previous_mode = admission.core.mode;
        const bool model_supported = command->kind != AINEKIO_COMMAND_MOTION_PLAN &&
            (command->kind != AINEKIO_COMMAND_INTENT || command->data.intent.kind == AINEKIO_INTENT_SAY ||
             ainekio_p4_body_supports(command));
        ainekio_core_set_boot_ready(&admission.core, true);
        const bool current = admission.connected && admission.authenticated && admission.generation == request.connection;
        const ainekio_decision_t decision = request.admitted_stop ?
            (ainekio_decision_t){.accepted=current, .rejection=AINEKIO_REJECT_STALE} :
            ainekio_admission_accept(&admission, request.connection,
                &request.message, request.received_us, now_us(), model_supported);
        leave();
        if (!decision.accepted) nak(request.connection, &request.message, decision.rejection);
        else {
            const esp_err_t result = atomic_load(&quiesced) ? ESP_ERR_INVALID_STATE : apply(&request);
            if (result != ESP_OK) {
                enter();
                if (admission.generation == request.connection) {
                    if (command->kind == AINEKIO_COMMAND_PROFILE) admission.core.profile = previous_profile;
                    admission.core.state = previous_state;
                    if (command->kind == AINEKIO_COMMAND_MODE) admission.core.mode = previous_mode;
                }
                leave();
                execution_failed(request.connection, request.message.sequence, result);
            } else {
                char text[80];
                ainekio_encode_ack(command->sequence,
                    command->kind == AINEKIO_COMMAND_STATE ? command->data.state.sleep_seconds : 0, text, sizeof(text));
                reply(request.connection, text);
                if (command->kind == AINEKIO_COMMAND_BODY_CALIBRATION) calibration_status(&request);
                if (command->kind == AINEKIO_COMMAND_STORAGE) storage_status(&request);
                if (command->kind == AINEKIO_COMMAND_STATE && command->data.state.request == AINEKIO_STATE_REQUEST_SLEEP)
                    done(request.connection, command->sequence);
            }
        }
        atomic_store(&pending_sequence, 0);
    }
}

esp_err_t ainekio_p4_controller_start(void)
{
    const uint32_t allowed = AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_INTENT) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STOP) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MODE) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_BODY_CALIBRATION) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_PROFILE) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STATE) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_CAMERA) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_SNAPSHOT) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MICROPHONE) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_TTS) | AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_WAKE_CONFIG) |
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STORAGE);
    ainekio_admission_init(&admission, allowed, true);
    requests = xQueueCreate(8, sizeof(request_t));
    replies = xQueueCreate(16, sizeof(reply_t));
    audio_packets = xQueueCreate(8, sizeof(packet_t));
    camera_packets = xQueueCreate(2, sizeof(packet_t));
    media_events = xQueueCreate(8, sizeof(media_event_t));
    if (!requests || !replies || !audio_packets || !camera_packets || !media_events) return ESP_ERR_NO_MEM;
    ESP_ERROR_CHECK(ainekio_p4_body_start());
    atomic_store(&initialized, true);
    if (xTaskCreate(control_task, "body_control", 12288, NULL, 5, NULL) != pdPASS ||
        xTaskCreate(link_task, "controller", 14336, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    return ESP_OK;
}

int ainekio_p4_home_command(int argc, char **argv)
{
    (void)argv;
    if (argc != 1 || !atomic_load(&initialized) || atomic_load(&quiesced)) return 1;
    const uint64_t generation = ainekio_pca_status(ainekio_p4_output()).generation;
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    if (!ainekio_p4_home_pulses(pulses)) return 1;
    const esp_err_t result = ainekio_p4_body_home(generation, pulses);
    printf("home: %s\n", esp_err_to_name(result));
    return result == ESP_OK ? 0 : 1;
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
    const ainekio_p4_media_status_t media = ainekio_p4_media_status();
    printf("motion=%d display=deferred camera=%d microphone=%d speaker=%d wake=%d\n",
           ainekio_p4_calibration().valid && atomic_load(&initialized),
           media.camera_ready, media.microphone_ready, media.speaker_ready, media.wake_ready);
    printf("installed walk=%s joints=%u hardware_qualified=%d; use gait for geometric diagnostics\n",
           ainekio_v2_walk_id, AINEKIO_V2_JOINT_COUNT, ainekio_v2_walk_hardware_qualified);
    const ainekio_p4_body_timing_t timing=ainekio_p4_body_timing();
    printf("motion timing frames=%" PRIu32 " max_calculation_us=%" PRIu32 " max_frame_us=%" PRIu32
           " max_request_us=%" PRIu32 " over_2ms=%" PRIu32 " over_5ms=%" PRIu32
           " body_stack_free_bytes=%" PRIu32 "\n",timing.frames,timing.calculation_us,timing.frame_us,
           timing.request_us,timing.over_2ms,timing.over_5ms,timing.stack_free_bytes);
    printf("internal_heap_free=%u internal_heap_minimum=%u\n",
           (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
           (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
    for (size_t i = 0; i < ainekio_v2_clip_count; ++i)
        printf("installed %s duration_ms=%" PRIu64 " heading_deg=%d hardware_qualified=%d\n",
               ainekio_v2_clips[i].command, ainekio_v2_clips[i].duration_us / 1000U,
               ainekio_v2_clips[i].heading_degrees, ainekio_v2_clips[i].hardware_qualified);
    return 0;
}

int ainekio_p4_gait_command(int argc, char **argv)
{
    const bool walk = (argc == 4 || argc == 5 || argc == 6) && (strcmp(argv[1], "walk") == 0 || strcmp(argv[1], "run") == 0);
    if (!walk && argc != 3) {
        puts("gait walk|run <steps 1..10> <elapsed-ms> [speed-percent 0..200 | stride-percent rate]\n"
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
    if (errno || *end || end == time_arg || time_arg[0] == '-' || elapsed > (walk ? 120000UL : 60400UL)) return 1;
    ainekio_v2_frame_t frame;
    if (walk) {
        ainekio_command_t request = {.kind=AINEKIO_COMMAND_INTENT, .sequence=1};
        request.data.intent.kind=AINEKIO_INTENT_WALK;
        request.data.intent.data.walk.steps=(uint8_t)steps;
        request.data.intent.data.walk.gait=strcmp(argv[1], "run")==0?AINEKIO_GAIT_RUN:AINEKIO_GAIT_WALK;
        if (argc >= 5) {
            errno = 0; double first = strtod(argv[4], &end);
            if (errno || *end || end == argv[4]) return 1;
            if (argc == 5) { request.data.intent.data.walk.controls=1; request.data.intent.data.walk.speed_percent=first; }
            else {
                errno = 0; double rate = strtod(argv[5], &end);
                if (errno || *end || end == argv[5] || first < 1.) return 1;
                request.data.intent.data.walk.controls=2; request.data.intent.data.walk.stride_percent=first; request.data.intent.data.walk.motion_rate=rate;
            }
        }
        ainekio_v2_walk_state_t state={0};
        const uint64_t begin_at = now_us();
        if (!ainekio_v2_walk_accept(&state, &request, 0)) return 1;
        const uint64_t begin_us = now_us() - begin_at;
        uint64_t maximum_tick_us = 0, previous_tick_us = 0, maximum_finish_gap_us = 0;
        unsigned samples = 0, over_interval = 0;
        unsigned long sampled_ms = 0;
        bool solver_ok = true;
        for (unsigned long ms = 0; ms < elapsed && !state.complete;) {
            ms += elapsed - ms < 20 ? elapsed - ms : 20;
            const uint64_t tick_at = now_us();
            solver_ok = ainekio_v2_walk_tick(&state, (uint64_t)ms*1000U);
            const uint64_t tick_us = now_us() - tick_at;
            if (tick_us > maximum_tick_us) maximum_tick_us = tick_us;
            if (tick_us > UINT64_C(20000)) ++over_interval;
            /* Estimate ideal scheduled completion spacing; this excludes PWM I/O.
               The output task's real 40 ms write-progress guard is unchanged. */
            if (samples) {
                const uint64_t start_gap_us = previous_tick_us > UINT64_C(20000) ?
                                              previous_tick_us : UINT64_C(20000);
                const uint64_t finish_gap_us = start_gap_us + tick_us - previous_tick_us;
                if (finish_gap_us > maximum_finish_gap_us) maximum_finish_gap_us = finish_gap_us;
            }
            previous_tick_us = tick_us;
            sampled_ms = ms;
            ++samples;
            if (!solver_ok) break;
            vTaskDelay(1); /* Offline evaluation must still yield to networking and the watchdog. */
        }
        frame = state.pose.frame;
        printf("walk timing: begin_us=%" PRIu64 " max_tick_us=%" PRIu64
               " samples=%u over_20ms=%u max_ideal_finish_gap_us=%" PRIu64
               " sampled_ms=%lu complete=%d solver_ok=%d sample_interval_us=20000 no_PWM=1\n",
               begin_us, maximum_tick_us, samples, over_interval, maximum_finish_gap_us,
               sampled_ms, state.complete, solver_ok);
        if (!solver_ok) return 1;
        printf("%s steps=%lu stride=%.3f rate=%.3f run_blend=%.3f phase=%d cycle=%u hardware_ready=0 geometry=%s\n",
               argv[1], steps, state.target.stride_percent, state.target.motion_rate, state.pose.run_blend, frame.phase, frame.cycle, ainekio_v2_walk_geometry_id);
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
