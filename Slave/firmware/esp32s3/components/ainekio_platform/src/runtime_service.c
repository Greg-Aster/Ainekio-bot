#include "ainekio/platform/runtime_service.h"

#include <string.h>

#include "ainekio/assets.h"
#include "ainekio/binary_codec.h"
#include "ainekio/control_codec.h"
#include "ainekio/control_encode.h"
#include "ainekio/platform/motion_service.h"
#include "ainekio/platform/nvs_adapter.h"
#include "ainekio/platform/audio_service.h"
#include "ainekio/platform/camera_service.h"
#include "ainekio/platform/display_service.h"
#include "ainekio/platform/sd_service.h"
#include "ainekio/platform/telemetry_service.h"
#include "ainekio/platform/sleep_service.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#define COMMAND_QUEUE_LENGTH 32U
#define STOP_QUEUE_LENGTH 8U
#define INTERNAL_QUEUE_LENGTH 8U
#define TX_QUEUE_LENGTH 32U
#define FAST_TX_QUEUE_LENGTH 8U
#define MIC_QUEUE_LENGTH 10U
#define CAMERA_QUEUE_LENGTH 2U
#define RX_TEXT_BYTES (AINEKIO_CONTROL_MAX_BYTES + 1U)
#define TX_TEXT_BYTES 1536U
#define WRITE_TIMEOUT_MS 100U
#define CONTROL_PING_US INT64_C(2000000)
#define CONTROL_FAILSAFE_US INT64_C(3000000)
#define ACTIVE_IDLE_US INT64_C(60000000)
#define CALIBRATION_IDLE_US INT64_C(600000000)
#define SUPERVISOR_ONLINE BIT0
#define SUPERVISOR_DISCONNECTED BIT1
#define SUPERVISOR_FORCE_CLOSE BIT2

typedef enum {
    TX_HELLO = 0,
    TX_ACK,
    TX_NAK,
    TX_DONE,
    TX_CANCELLED,
    TX_STATUS,
    TX_EVENT,
    TX_CAMERA_META,
    TX_PING,
    TX_PONG,
    TX_CLOSE,
} tx_kind_t;

typedef enum {
    TX_MESSAGE_NONE = 0,
    TX_MESSAGE_CAPABILITY_UNAVAILABLE,
    TX_MESSAGE_NVS_WRITE_FAILED,
    TX_MESSAGE_WAKE_MODEL_UNAVAILABLE,
} tx_message_t;

typedef struct {
    uint32_t session_serial;
    tx_kind_t kind;
    union {
        struct {
            uint32_t sequence;
            uint32_t sleep_seconds;
        } ack;
        struct {
            bool has_sequence;
            uint32_t sequence;
            ainekio_nak_code_t code;
            tx_message_t message;
        } nak;
        uint32_t sequence;
        struct {
            uint32_t sequence;
            ainekio_cancel_code_t code;
        } cancelled;
        ainekio_status_t status;
        ainekio_event_t event;
        struct {
            ainekio_camera_resolution_t resolution;
            uint8_t fps;
            uint32_t counter_base;
        } camera_meta;
        struct {
            uint16_t code;
            uint32_t sleep_seconds;
            bool battery_cutoff;
        } close;
    } data;
} tx_item_t;

typedef enum {
    RX_COMMAND = 0,
    RX_UNKNOWN_INTENT,
} rx_command_kind_t;

typedef struct {
    uint32_t session_serial;
    rx_command_kind_t kind;
    uint32_t sequence;
    ainekio_command_t command;
} rx_command_item_t;

typedef struct {
    uint32_t session_serial;
    ainekio_command_t command;
    uint32_t cancelled_sequence;
    uint32_t cancelled_audio_sequence;
} stop_item_t;

typedef enum {
    INTERNAL_WELCOME = 0,
    INTERNAL_FAILSAFE,
} internal_kind_t;

typedef struct {
    internal_kind_t kind;
    uint32_t session_serial;
    uint32_t epoch;
    ainekio_profile_t profile;
} internal_item_t;

typedef struct {
    float volts;
    ainekio_battery_state_t state;
    ainekio_battery_events_t events;
} battery_item_t;

typedef struct {
    ainekio_sd_state_t state;
} sd_item_t;

typedef struct {
    uint32_t session_serial;
    uint8_t bytes[AINEKIO_BINARY_HEADER_BYTES + AINEKIO_AUDIO_PAYLOAD_BYTES];
    size_t length;
} mic_tx_item_t;

typedef struct {
    uint32_t session_serial;
    bool snapshot;
    uint32_t sequence;
    ainekio_camera_resolution_t resolution;
    uint32_t counter;
    uint8_t *bytes;
    size_t length;
} camera_tx_item_t;

struct ainekio_runtime {
    ainekio_core_t *core;
    ainekio_servo_bank_t *servos;
    ainekio_pose_bank_t *poses;
    ainekio_mcpwm_adapter_t *mcpwm;
    ainekio_asset_store_t *assets;
    ainekio_provisioning_service_t *provisioning;
    char firmware_version[33];

    ainekio_motion_service_t motion;
    ainekio_audio_service_t *audio;
    ainekio_camera_service_t *camera;
    ainekio_display_service_t *display;
    ainekio_telemetry_service_t *telemetry;
    ainekio_sd_service_t *sd;
    esp_websocket_client_handle_t client;
    SemaphoreHandle_t client_lock;
    StaticSemaphore_t client_lock_storage;
    portMUX_TYPE state_lock;
    ainekio_config_record_t active_config;
    char client_endpoint[AINEKIO_ENDPOINT_URL_BYTES];
    bool has_config;
    bool connected;
    bool authenticated;
    bool failsafe_signalled;
    bool ping_pending;
    bool boot_event_pending;
    bool brownout_recovered_pending;
    bool littlefs_failure_pending;
    bool sd_failure_pending;
    bool sd_corrupt_pending;
    bool ota_validation_checked;
    uint8_t display_state;
    uint32_t config_generation;
    uint32_t session_serial;
    int64_t last_rx_control_us;
    int64_t last_tx_control_us;

    char rx_text[RX_TEXT_BYTES];
    size_t rx_text_expected;
    bool rx_text_discard;
    uint8_t rx_binary[AINEKIO_BINARY_HEADER_BYTES + AINEKIO_AUDIO_PAYLOAD_BYTES];
    size_t rx_binary_expected;
    bool rx_binary_discard;

    QueueHandle_t command_queue;
    QueueHandle_t stop_queue;
    QueueHandle_t internal_queue;
    QueueHandle_t tx_queue;
    QueueHandle_t fast_tx_queue;
    QueueHandle_t mic_queue;
    QueueHandle_t camera_queue;
    QueueHandle_t battery_queue;
    QueueHandle_t sd_queue;
    StaticQueue_t command_queue_control;
    StaticQueue_t stop_queue_control;
    StaticQueue_t internal_queue_control;
    StaticQueue_t tx_queue_control;
    StaticQueue_t fast_tx_queue_control;
    StaticQueue_t mic_queue_control;
    StaticQueue_t battery_queue_control;
    StaticQueue_t sd_queue_control;
    uint8_t command_queue_storage[COMMAND_QUEUE_LENGTH * sizeof(rx_command_item_t)];
    uint8_t stop_queue_storage[STOP_QUEUE_LENGTH * sizeof(stop_item_t)];
    uint8_t internal_queue_storage[INTERNAL_QUEUE_LENGTH * sizeof(internal_item_t)];
    uint8_t tx_queue_storage[TX_QUEUE_LENGTH * sizeof(tx_item_t)];
    uint8_t fast_tx_queue_storage[FAST_TX_QUEUE_LENGTH * sizeof(tx_item_t)];
    uint8_t mic_queue_storage[MIC_QUEUE_LENGTH * sizeof(mic_tx_item_t)];
    uint8_t battery_queue_storage[sizeof(battery_item_t)];
    uint8_t sd_queue_storage[sizeof(sd_item_t)];
    uint32_t microphone_counter;

    TaskHandle_t supervisor_task;
    TaskHandle_t tx_task;
    TaskHandle_t dispatcher_task;
    int64_t last_intent_us;
    int64_t calibration_activity_us;
    int64_t next_status_us;
    float battery_voltage;
    bool sd_available;
    uint32_t camera_drops;
    uint32_t speaker_underruns;
    uint32_t microphone_drops;
    ainekio_battery_events_t battery_events_pending;
    bool camera_enabled;
    bool camera_stream_applied;
    uint8_t camera_fps;
    uint8_t camera_applied_fps;
    ainekio_camera_resolution_t camera_resolution;
    ainekio_camera_resolution_t camera_applied_resolution;
    bool microphone_enabled;
    ainekio_microphone_gate_t microphone_gate;
    bool wake_enabled;
    bool wake_ready;
    char wake_model[AINEKIO_WAKE_MODEL_MAX + 1U];
};

static const char *TAG = "ainekio_runtime";
static ainekio_runtime_t singleton;

static int64_t now_us(void)
{
    return esp_timer_get_time();
}

static ainekio_status_t runtime_status(
    const ainekio_runtime_t *runtime,
    int8_t rssi,
    ainekio_body_state_t state,
    uint32_t uptime_seconds
)
{
    const bool wake_ready = runtime->wake_ready &&
                            ainekio_audio_wake_ready(runtime->audio);
    ainekio_status_t status = {
        .battery_voltage = runtime->battery_voltage,
        .rssi = rssi,
        .state = state,
        .uptime_seconds = uptime_seconds,
        .free_heap = esp_get_free_heap_size(),
        .sd_available = runtime->sd_available,
        .camera_drops = runtime->camera_drops,
        .speaker_underruns = runtime->speaker_underruns,
        .microphone_drops = runtime->microphone_drops,
        .wake_enabled = runtime->wake_enabled,
        .wake_ready = wake_ready,
    };
    (void)strcpy(status.wake_model, runtime->wake_model);
    return status;
}

static bool wake_model_known(const char *model)
{
    return strcmp(model, AINEKIO_DEFAULT_WAKE_MODEL) == 0;
}

static uint32_t current_serial(ainekio_runtime_t *runtime)
{
    taskENTER_CRITICAL(&runtime->state_lock);
    const uint32_t serial = runtime->session_serial;
    taskEXIT_CRITICAL(&runtime->state_lock);
    return serial;
}

static bool session_matches(
    ainekio_runtime_t *runtime,
    uint32_t serial,
    bool require_authenticated
)
{
    taskENTER_CRITICAL(&runtime->state_lock);
    const bool matches = runtime->connected && runtime->session_serial == serial &&
                         (!require_authenticated || runtime->authenticated);
    taskEXIT_CRITICAL(&runtime->state_lock);
    return matches;
}

static uint32_t cancel_audio(ainekio_runtime_t *runtime)
{
    if (runtime->audio == NULL) {
        return 0U;
    }
    const uint32_t sequence = ainekio_audio_cancel(runtime->audio);
    if (sequence != 0U) {
        ainekio_display_end_talk(runtime->display);
    }
    return sequence;
}

static void signal_failsafe(ainekio_runtime_t *runtime)
{
    bool first = false;
    uint32_t serial = 0U;
    taskENTER_CRITICAL(&runtime->state_lock);
    if (!runtime->failsafe_signalled) {
        runtime->failsafe_signalled = true;
        first = true;
        serial = runtime->session_serial;
    }
    runtime->authenticated = false;
    taskEXIT_CRITICAL(&runtime->state_lock);
    if (!first) {
        return;
    }
    if (runtime->camera != NULL) {
        (void)ainekio_camera_configure(
            runtime->camera,
            false,
            runtime->camera_fps,
            runtime->camera_resolution
        );
        runtime->camera_stream_applied = false;
    }
    ainekio_motion_service_request_failsafe(&runtime->motion);
    (void)cancel_audio(runtime);
    const internal_item_t item = {
        .kind = INTERNAL_FAILSAFE,
        .session_serial = serial,
    };
    (void)xQueueSend(runtime->internal_queue, &item, 0U);
}

static void force_disconnect(ainekio_runtime_t *runtime)
{
    signal_failsafe(runtime);
    if (runtime->supervisor_task != NULL) {
        (void)xTaskNotify(runtime->supervisor_task, SUPERVISOR_FORCE_CLOSE, eSetBits);
    }
}

static bool enqueue_tx(
    ainekio_runtime_t *runtime,
    const tx_item_t *item,
    bool fast
)
{
    QueueHandle_t queue = fast ? runtime->fast_tx_queue : runtime->tx_queue;
    if (xQueueSend(queue, item, 0U) == pdTRUE) {
        return true;
    }
    ESP_LOGE(TAG, "%s control queue overflow", fast ? "fast" : "normal");
    force_disconnect(runtime);
    return false;
}

static tx_item_t tx_base(ainekio_runtime_t *runtime, tx_kind_t kind)
{
    return (tx_item_t){
        .session_serial = current_serial(runtime),
        .kind = kind,
    };
}

static bool queue_ack(
    ainekio_runtime_t *runtime,
    uint32_t sequence,
    uint32_t sleep_seconds,
    bool fast
)
{
    tx_item_t item = tx_base(runtime, TX_ACK);
    item.data.ack.sequence = sequence;
    item.data.ack.sleep_seconds = sleep_seconds;
    return enqueue_tx(runtime, &item, fast);
}

static bool queue_nak(
    ainekio_runtime_t *runtime,
    bool has_sequence,
    uint32_t sequence,
    ainekio_nak_code_t code,
    tx_message_t message,
    bool fast
)
{
    tx_item_t item = tx_base(runtime, TX_NAK);
    item.data.nak.has_sequence = has_sequence;
    item.data.nak.sequence = sequence;
    item.data.nak.code = code;
    item.data.nak.message = message;
    return enqueue_tx(runtime, &item, fast);
}

static void queue_event(ainekio_runtime_t *runtime, ainekio_event_t event)
{
    if (!session_matches(runtime, current_serial(runtime), true)) {
        return;
    }
    tx_item_t item = tx_base(runtime, TX_EVENT);
    item.data.event = event;
    (void)enqueue_tx(runtime, &item, false);
}

static ainekio_nak_code_t rejection_code(ainekio_reject_reason_t rejection)
{
    switch (rejection) {
    case AINEKIO_REJECT_STALE:
        return AINEKIO_NAK_STALE;
    case AINEKIO_REJECT_MODE:
        return AINEKIO_NAK_MODE;
    case AINEKIO_REJECT_UNSAFE:
        return AINEKIO_NAK_UNSAFE;
    case AINEKIO_REJECT_LIMIT:
        return AINEKIO_NAK_LIMIT;
    case AINEKIO_REJECT_UNKNOWN:
        return AINEKIO_NAK_UNKNOWN;
    case AINEKIO_REJECT_PROFILE:
        return AINEKIO_NAK_PROFILE;
    case AINEKIO_REJECT_ASSET_MISSING:
        return AINEKIO_NAK_ASSET_MISSING;
    case AINEKIO_REJECT_MALFORMED:
        return AINEKIO_NAK_MALFORMED;
    case AINEKIO_REJECT_BUSY:
    case AINEKIO_REJECT_NONE:
    default:
        return AINEKIO_NAK_BUSY;
    }
}

static const char *tx_message_text(tx_message_t message)
{
    switch (message) {
    case TX_MESSAGE_CAPABILITY_UNAVAILABLE:
        return "capability unavailable";
    case TX_MESSAGE_NVS_WRITE_FAILED:
        return "nvs write failed";
    case TX_MESSAGE_WAKE_MODEL_UNAVAILABLE:
        return "wake model unavailable";
    case TX_MESSAGE_NONE:
    default:
        return NULL;
    }
}

static size_t encode_tx(
    ainekio_runtime_t *runtime,
    const tx_item_t *item,
    char *output,
    size_t capacity
)
{
    switch (item->kind) {
    case TX_HELLO: {
        ainekio_config_record_t config;
        taskENTER_CRITICAL(&runtime->state_lock);
        config = runtime->active_config;
        taskEXIT_CRITICAL(&runtime->state_lock);
        return ainekio_encode_hello(
            runtime->firmware_version,
            config.robot_id,
            config.robot_token,
            output,
            capacity
        );
    }
    case TX_ACK:
        return ainekio_encode_ack(
            item->data.ack.sequence,
            item->data.ack.sleep_seconds,
            output,
            capacity
        );
    case TX_NAK:
        return ainekio_encode_nak(
            item->data.nak.has_sequence,
            item->data.nak.sequence,
            item->data.nak.code,
            tx_message_text(item->data.nak.message),
            output,
            capacity
        );
    case TX_DONE:
        return ainekio_encode_done(item->data.sequence, output, capacity);
    case TX_CANCELLED:
        return ainekio_encode_cancelled(
            item->data.cancelled.sequence,
            item->data.cancelled.code,
            output,
            capacity
        );
    case TX_STATUS:
        return ainekio_encode_status(&item->data.status, output, capacity);
    case TX_EVENT:
        return ainekio_encode_event(item->data.event, output, capacity);
    case TX_CAMERA_META:
        return ainekio_encode_camera_meta(
            item->data.camera_meta.resolution,
            item->data.camera_meta.fps,
            item->data.camera_meta.counter_base,
            output,
            capacity
        );
    case TX_PING:
        return ainekio_encode_ping(false, output, capacity);
    case TX_PONG:
        return ainekio_encode_ping(true, output, capacity);
    case TX_CLOSE:
    default:
        return 0U;
    }
}

static void send_tx_item(ainekio_runtime_t *runtime, const tx_item_t *item)
{
    if (!session_matches(runtime, item->session_serial, false)) {
        return;
    }
    if (xSemaphoreTake(runtime->client_lock, pdMS_TO_TICKS(WRITE_TIMEOUT_MS)) !=
        pdTRUE) {
        force_disconnect(runtime);
        return;
    }
    esp_websocket_client_handle_t client = runtime->client;
    if (client == NULL || !esp_websocket_client_is_connected(client)) {
        (void)xSemaphoreGive(runtime->client_lock);
        return;
    }

    if (item->kind == TX_CLOSE) {
        const esp_err_t result = esp_websocket_client_close_with_code(
            client,
            item->data.close.code,
            NULL,
            0,
            pdMS_TO_TICKS(WRITE_TIMEOUT_MS)
        );
        (void)xSemaphoreGive(runtime->client_lock);
        if (result != ESP_OK) {
            force_disconnect(runtime);
        }
        return;
    }

    char output[TX_TEXT_BYTES];
    const size_t length = encode_tx(runtime, item, output, sizeof(output));
    int sent = -1;
    if (length > 0U) {
        sent = esp_websocket_client_send_text(
            client,
            output,
            (int)length,
            pdMS_TO_TICKS(WRITE_TIMEOUT_MS)
        );
    }
    (void)xSemaphoreGive(runtime->client_lock);
    if (length == 0U || sent != (int)length) {
        ESP_LOGE(TAG, "bounded control write failed kind=%u", (unsigned int)item->kind);
        force_disconnect(runtime);
        return;
    }
    taskENTER_CRITICAL(&runtime->state_lock);
    runtime->last_tx_control_us = now_us();
    if (item->kind == TX_PING) {
        runtime->ping_pending = false;
    }
    taskEXIT_CRITICAL(&runtime->state_lock);
}

static bool send_binary(
    ainekio_runtime_t *runtime,
    uint32_t session_serial,
    const uint8_t *bytes,
    size_t length
)
{
    if (!session_matches(runtime, session_serial, true)) {
        return false;
    }
    if (xSemaphoreTake(runtime->client_lock, pdMS_TO_TICKS(WRITE_TIMEOUT_MS)) !=
        pdTRUE) {
        force_disconnect(runtime);
        return false;
    }
    esp_websocket_client_handle_t client = runtime->client;
    const int sent = client != NULL && esp_websocket_client_is_connected(client)
                         ? esp_websocket_client_send_bin(
                               client,
                               (const char *)bytes,
                               (int)length,
                               pdMS_TO_TICKS(WRITE_TIMEOUT_MS)
                           )
                         : -1;
    (void)xSemaphoreGive(runtime->client_lock);
    if (sent != (int)length) {
        force_disconnect(runtime);
        return false;
    }
    return true;
}

static void tx_task(void *argument)
{
    ainekio_runtime_t *runtime = argument;
    while (true) {
        tx_item_t item;
        if (xQueueReceive(runtime->fast_tx_queue, &item, 0U) == pdTRUE) {
            send_tx_item(runtime, &item);
            if (item.kind == TX_CLOSE && item.data.close.sleep_seconds > 0U) {
                vTaskDelay(pdMS_TO_TICKS(20U));
                ainekio_sleep_enter(
                    item.data.close.sleep_seconds,
                    item.data.close.battery_cutoff
                );
            }
            continue;
        }
        if (xQueueReceive(runtime->tx_queue, &item, pdMS_TO_TICKS(5U)) == pdTRUE) {
            send_tx_item(runtime, &item);
            if (item.kind == TX_CLOSE && item.data.close.sleep_seconds > 0U) {
                vTaskDelay(pdMS_TO_TICKS(20U));
                ainekio_sleep_enter(
                    item.data.close.sleep_seconds,
                    item.data.close.battery_cutoff
                );
            }
            continue;
        }
        mic_tx_item_t microphone;
        if (xQueueReceive(runtime->mic_queue, &microphone, 0U) == pdTRUE &&
            session_matches(runtime, microphone.session_serial, true)) {
            (void)send_binary(
                runtime,
                microphone.session_serial,
                microphone.bytes,
                microphone.length
            );
            continue;
        }
        camera_tx_item_t camera;
        if (xQueueReceive(runtime->camera_queue, &camera, 0U) == pdTRUE) {
            if (session_matches(runtime, camera.session_serial, true)) {
                if (camera.snapshot) {
                    tx_item_t meta = tx_base(runtime, TX_CAMERA_META);
                    meta.data.camera_meta.resolution = camera.resolution;
                    meta.data.camera_meta.fps = 0U;
                    meta.data.camera_meta.counter_base = camera.counter;
                    send_tx_item(runtime, &meta);
                }
                const bool sent = send_binary(
                    runtime,
                    camera.session_serial,
                    camera.bytes,
                    camera.length
                );
                if (sent && camera.snapshot) {
                    tx_item_t done = tx_base(runtime, TX_DONE);
                    done.data.sequence = camera.sequence;
                    send_tx_item(runtime, &done);
                }
            }
            heap_caps_free(camera.bytes);
        }
    }
}

static void motion_done(void *context, uint32_t sequence)
{
    ainekio_runtime_t *runtime = context;
    tx_item_t item = tx_base(runtime, TX_DONE);
    item.data.sequence = sequence;
    (void)enqueue_tx(runtime, &item, false);
}

static void motion_failed(void *context, uint32_t sequence)
{
    ainekio_runtime_t *runtime = context;
    tx_item_t item = tx_base(runtime, TX_CANCELLED);
    item.data.cancelled.sequence = sequence;
    item.data.cancelled.code = AINEKIO_CANCEL_OVERFLOW;
    (void)enqueue_tx(runtime, &item, false);
}

static void motion_face(
    void *context,
    const char *name,
    ainekio_face_mode_t mode
)
{
    ainekio_runtime_t *runtime = context;
    (void)ainekio_display_show_face(
        runtime->display,
        name,
        mode,
        true,
        true
    );
}

static void audio_done(void *context, uint32_t sequence)
{
    ainekio_runtime_t *runtime = context;
    ainekio_display_end_talk(runtime->display);
    motion_done(context, sequence);
}

static void audio_failed(void *context, uint32_t sequence, bool overflow)
{
    ainekio_runtime_t *runtime = context;
    ainekio_display_end_talk(runtime->display);
    if (overflow) {
        queue_event(runtime, AINEKIO_EVENT_TTS_OVERFLOW);
    }
    tx_item_t item = tx_base(runtime, TX_CANCELLED);
    item.data.cancelled.sequence = sequence;
    item.data.cancelled.code = AINEKIO_CANCEL_OVERFLOW;
    (void)enqueue_tx(runtime, &item, false);
}

static void audio_microphone(
    void *context,
    const uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES]
)
{
    ainekio_runtime_t *runtime = context;
    if (!session_matches(runtime, current_serial(runtime), true)) {
        return;
    }
    mic_tx_item_t item = {.session_serial = current_serial(runtime)};
    if (ainekio_binary_encode(
            AINEKIO_FRAME_MIC_PCM,
            runtime->microphone_counter++,
            payload,
            AINEKIO_AUDIO_PAYLOAD_BYTES,
            item.bytes,
            sizeof(item.bytes),
            &item.length
        ) != AINEKIO_BINARY_OK) {
        return;
    }
    if (xQueueSend(runtime->mic_queue, &item, 0U) == pdTRUE) {
        return;
    }
    mic_tx_item_t discarded;
    (void)xQueueReceive(runtime->mic_queue, &discarded, 0U);
    ++runtime->microphone_drops;
    if (xQueueSend(runtime->mic_queue, &item, 0U) != pdTRUE) {
        ++runtime->microphone_drops;
    }
}

static void audio_gate(void *context, bool open, bool wake_word)
{
    ainekio_runtime_t *runtime = context;
    queue_event(
        runtime,
        open ? AINEKIO_EVENT_VAD_OPEN : AINEKIO_EVENT_VAD_CLOSE
    );
    if (wake_word) {
        queue_event(runtime, AINEKIO_EVENT_WAKE_WORD);
    }
}

static void count_camera_drop(ainekio_runtime_t *runtime)
{
    taskENTER_CRITICAL(&runtime->state_lock);
    ++runtime->camera_drops;
    taskEXIT_CRITICAL(&runtime->state_lock);
}

static void cancel_snapshot(ainekio_runtime_t *runtime, uint32_t sequence)
{
    if (sequence == 0U) {
        return;
    }
    tx_item_t item = tx_base(runtime, TX_CANCELLED);
    item.data.cancelled.sequence = sequence;
    item.data.cancelled.code = AINEKIO_CANCEL_OVERFLOW;
    (void)enqueue_tx(runtime, &item, false);
}

static void camera_frame(
    void *context,
    bool snapshot,
    uint32_t sequence,
    ainekio_camera_resolution_t resolution,
    uint32_t counter,
    const uint8_t *jpeg,
    size_t length
)
{
    ainekio_runtime_t *runtime = context;
    const uint32_t serial = current_serial(runtime);
    if (!session_matches(runtime, serial, true)) {
        return;
    }
    const size_t capacity = AINEKIO_BINARY_HEADER_BYTES + length;
    uint8_t *bytes = heap_caps_malloc(
        capacity,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
    );
    size_t encoded_length = 0U;
    if (bytes == NULL ||
        ainekio_binary_encode(
            AINEKIO_FRAME_CAMERA_JPEG,
            counter,
            jpeg,
            length,
            bytes,
            capacity,
            &encoded_length
        ) != AINEKIO_BINARY_OK) {
        heap_caps_free(bytes);
        count_camera_drop(runtime);
        if (snapshot) {
            cancel_snapshot(runtime, sequence);
        }
        return;
    }
    const camera_tx_item_t item = {
        .session_serial = serial,
        .snapshot = snapshot,
        .sequence = sequence,
        .resolution = resolution,
        .counter = counter,
        .bytes = bytes,
        .length = encoded_length,
    };
    if (xQueueSend(runtime->camera_queue, &item, 0U) == pdTRUE) {
        return;
    }

    camera_tx_item_t discarded;
    if (xQueueReceive(runtime->camera_queue, &discarded, 0U) == pdTRUE) {
        heap_caps_free(discarded.bytes);
        count_camera_drop(runtime);
        if (discarded.snapshot) {
            cancel_snapshot(runtime, discarded.sequence);
        }
    }
    if (xQueueSend(runtime->camera_queue, &item, 0U) != pdTRUE) {
        heap_caps_free(bytes);
        count_camera_drop(runtime);
        if (snapshot) {
            cancel_snapshot(runtime, sequence);
        }
    }
}

static void camera_failed(void *context, bool snapshot, uint32_t sequence)
{
    ainekio_runtime_t *runtime = context;
    count_camera_drop(runtime);
    if (snapshot && session_matches(runtime, current_serial(runtime), true)) {
        cancel_snapshot(runtime, sequence);
    }
}

static esp_err_t sync_camera_stream(ainekio_runtime_t *runtime)
{
    if (runtime->camera == NULL) {
        runtime->camera_stream_applied = false;
        return ESP_OK;
    }
    const bool wanted = runtime->camera_enabled && runtime->camera_fps > 0U &&
                        runtime->core->state == AINEKIO_STATE_ACTIVE &&
                        runtime->core->profile == AINEKIO_PROFILE_HOME;
    if (runtime->camera_stream_applied == wanted &&
        (!wanted ||
         (runtime->camera_applied_fps == runtime->camera_fps &&
          runtime->camera_applied_resolution == runtime->camera_resolution))) {
        return ESP_OK;
    }
    const esp_err_t result = ainekio_camera_configure(
        runtime->camera,
        wanted,
        runtime->camera_fps,
        runtime->camera_resolution
    );
    if (result == ESP_OK) {
        runtime->camera_stream_applied = wanted;
        runtime->camera_applied_fps = runtime->camera_fps;
        runtime->camera_applied_resolution = runtime->camera_resolution;
    }
    return result;
}

static void battery_observation(
    void *context,
    float volts,
    ainekio_battery_state_t state,
    ainekio_battery_events_t events
)
{
    ainekio_runtime_t *runtime = context;
    if ((events & AINEKIO_BATTERY_EVENT_CUTOFF) != 0U) {
        (void)ainekio_motion_service_request_stop(&runtime->motion);
        (void)cancel_audio(runtime);
    }
    const battery_item_t item = {
        .volts = volts,
        .state = state,
        .events = events,
    };
    (void)xQueueOverwrite(runtime->battery_queue, &item);
}

static void sd_state_changed(void *context, ainekio_sd_state_t state)
{
    ainekio_runtime_t *runtime = context;
    const sd_item_t item = {.state = state};
    (void)xQueueOverwrite(runtime->sd_queue, &item);
}

static void claim_and_nak(
    ainekio_runtime_t *runtime,
    uint32_t sequence,
    ainekio_nak_code_t desired,
    tx_message_t message
)
{
    const ainekio_reject_reason_t claimed =
        ainekio_core_claim_sequence(runtime->core, sequence);
    (void)queue_nak(
        runtime,
        true,
        sequence,
        claimed == AINEKIO_REJECT_NONE ? desired : rejection_code(claimed),
        claimed == AINEKIO_REJECT_NONE ? message : TX_MESSAGE_NONE,
        false
    );
}

static bool movement_job(
    const ainekio_command_t *command,
    ainekio_motion_job_t *job
)
{
    const ainekio_intent_t *intent = &command->data.intent;
    *job = (ainekio_motion_job_t){
        .sequence = command->sequence,
        .repetitions = 1U,
    };
    switch (intent->kind) {
    case AINEKIO_INTENT_SIT:
        job->kind = AINEKIO_MOTION_JOB_ASSET;
        (void)strcpy(job->name, "rest");
        return true;
    case AINEKIO_INTENT_STAND:
        job->kind = AINEKIO_MOTION_JOB_STAND;
        return true;
    case AINEKIO_INTENT_NEUTRAL:
        job->kind = AINEKIO_MOTION_JOB_NEUTRAL;
        return true;
    case AINEKIO_INTENT_WALK: {
        static const char *const names[] = {
            "walk_forward", "walk_backward", "turn_left", "turn_right",
        };
        job->kind = AINEKIO_MOTION_JOB_ASSET;
        job->repetitions = intent->data.walk.steps;
        (void)strcpy(job->name, names[intent->data.walk.direction]);
        return true;
    }
    case AINEKIO_INTENT_EMOTE:
        job->kind = AINEKIO_MOTION_JOB_ASSET;
        (void)strcpy(job->name, intent->data.asset);
        return true;
    default:
        return false;
    }
}

static void dispatch_movement(
    ainekio_runtime_t *runtime,
    const ainekio_command_t *command
)
{
    if (command->data.intent.kind == AINEKIO_INTENT_LOOK) {
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_BUSY,
            TX_MESSAGE_CAPABILITY_UNAVAILABLE
        );
        return;
    }
    ainekio_motion_job_t job;
    if (!movement_job(command, &job)) {
        claim_and_nak(runtime, command->sequence, AINEKIO_NAK_UNKNOWN, TX_MESSAGE_NONE);
        return;
    }
    const ainekio_motion_submit_result_t prepared =
        ainekio_motion_service_prepare(&runtime->motion, &job);
    if (prepared != AINEKIO_MOTION_SUBMIT_OK) {
        if (prepared == AINEKIO_MOTION_SUBMIT_ASSET_MISSING) {
            queue_event(runtime, AINEKIO_EVENT_ASSET_MISSING);
            claim_and_nak(
                runtime,
                command->sequence,
                AINEKIO_NAK_ASSET_MISSING,
                TX_MESSAGE_NONE
            );
        } else if (prepared == AINEKIO_MOTION_SUBMIT_LIMIT) {
            claim_and_nak(runtime, command->sequence, AINEKIO_NAK_LIMIT, TX_MESSAGE_NONE);
        } else {
            claim_and_nak(runtime, command->sequence, AINEKIO_NAK_BUSY, TX_MESSAGE_NONE);
        }
        return;
    }

    const ainekio_decision_t decision = ainekio_core_accept(runtime->core, command);
    if (!decision.accepted) {
        ainekio_motion_service_abort(&runtime->motion, command->sequence);
        (void)queue_nak(
            runtime,
            true,
            command->sequence,
            rejection_code(decision.rejection),
            TX_MESSAGE_NONE,
            false
        );
        return;
    }
    if (!queue_ack(runtime, command->sequence, 0U, false)) {
        ainekio_motion_service_abort(&runtime->motion, command->sequence);
        return;
    }
    runtime->last_intent_us = now_us();
    const ainekio_motion_submit_result_t committed =
        ainekio_motion_service_commit(&runtime->motion, command->sequence);
    if (committed != AINEKIO_MOTION_SUBMIT_OK &&
        committed != AINEKIO_MOTION_SUBMIT_PREEMPTED) {
        motion_failed(runtime, command->sequence);
    }
}

static bool calibration_limits_valid(const ainekio_command_t *command)
{
    const ainekio_servo_calibration_t calibration = {
        .minimum_degrees = command->data.limits.minimum,
        .center_degrees = command->data.limits.center,
        .maximum_degrees = command->data.limits.maximum,
        .invert = command->data.limits.invert,
    };
    return ainekio_servo_calibration_valid(&calibration);
}

static void dispatch_command(
    ainekio_runtime_t *runtime,
    const rx_command_item_t *item
)
{
    if (!session_matches(runtime, item->session_serial, true)) {
        return;
    }
    if (item->kind == RX_UNKNOWN_INTENT) {
        claim_and_nak(runtime, item->sequence, AINEKIO_NAK_UNKNOWN, TX_MESSAGE_NONE);
        return;
    }
    const ainekio_command_t *command = &item->command;
    if (command->kind == AINEKIO_COMMAND_INTENT &&
        ainekio_intent_is_movement(command->data.intent.kind)) {
        dispatch_movement(runtime, command);
        return;
    }
    if (command->kind == AINEKIO_COMMAND_SNAPSHOT) {
        if (runtime->camera == NULL) {
            claim_and_nak(
                runtime,
                command->sequence,
                AINEKIO_NAK_BUSY,
                TX_MESSAGE_CAPABILITY_UNAVAILABLE
            );
            return;
        }
        const ainekio_decision_t decision =
            ainekio_core_accept(runtime->core, command);
        if (!decision.accepted) {
            (void)queue_nak(
                runtime,
                true,
                command->sequence,
                rejection_code(decision.rejection),
                TX_MESSAGE_NONE,
                false
            );
            return;
        }
        if (ainekio_camera_snapshot(runtime->camera, command->sequence) != ESP_OK) {
            (void)queue_nak(
                runtime,
                true,
                command->sequence,
                AINEKIO_NAK_BUSY,
                TX_MESSAGE_NONE,
                false
            );
            return;
        }
        (void)queue_ack(runtime, command->sequence, 0U, false);
        runtime->last_intent_us = now_us();
        (void)sync_camera_stream(runtime);
        return;
    }
    if (command->kind == AINEKIO_COMMAND_CAMERA &&
        command->data.camera.enabled && runtime->camera == NULL) {
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_BUSY,
            TX_MESSAGE_CAPABILITY_UNAVAILABLE
        );
        return;
    }
    if (command->kind == AINEKIO_COMMAND_WAKE_CONFIG &&
        (!wake_model_known(command->data.wake.model) ||
         (command->data.wake.enabled &&
          !ainekio_audio_wake_ready(runtime->audio)))) {
        claim_and_nak(
            runtime,
            command->sequence,
            !wake_model_known(command->data.wake.model)
                ? AINEKIO_NAK_ASSET_MISSING
                : AINEKIO_NAK_BUSY,
            TX_MESSAGE_WAKE_MODEL_UNAVAILABLE
        );
        return;
    }
    if (command->kind == AINEKIO_COMMAND_MICROPHONE &&
        command->data.microphone.enabled &&
        command->data.microphone.gate == AINEKIO_MIC_GATE_WAKE &&
        (!runtime->wake_enabled ||
         !ainekio_audio_wake_ready(runtime->audio))) {
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_BUSY,
            TX_MESSAGE_WAKE_MODEL_UNAVAILABLE
        );
        return;
    }
    if (command->kind == AINEKIO_COMMAND_CAMERA &&
        command->data.camera.enabled &&
        runtime->core->profile == AINEKIO_PROFILE_HOME &&
        command->data.camera.fps > 10U) {
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_PROFILE,
            TX_MESSAGE_NONE
        );
        return;
    }
    const bool needs_audio = command->kind == AINEKIO_COMMAND_TTS ||
                             command->kind == AINEKIO_COMMAND_MICROPHONE ||
                             (command->kind == AINEKIO_COMMAND_INTENT &&
                              command->data.intent.kind == AINEKIO_INTENT_SAY);
    if (needs_audio && runtime->audio == NULL) {
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_BUSY,
            TX_MESSAGE_CAPABILITY_UNAVAILABLE
        );
        return;
    }
    if (command->kind == AINEKIO_COMMAND_INTENT &&
        command->data.intent.kind == AINEKIO_INTENT_FACE &&
        ainekio_asset_store_face(runtime->assets, command->data.intent.data.asset) == NULL) {
        queue_event(runtime, AINEKIO_EVENT_ASSET_MISSING);
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_ASSET_MISSING,
            TX_MESSAGE_NONE
        );
        return;
    }
    if (command->kind == AINEKIO_COMMAND_INTENT &&
        command->data.intent.kind == AINEKIO_INTENT_SAY &&
        ainekio_asset_store_audio(runtime->assets, command->data.intent.data.asset) ==
            NULL) {
        queue_event(runtime, AINEKIO_EVENT_ASSET_MISSING);
        claim_and_nak(
            runtime,
            command->sequence,
            AINEKIO_NAK_ASSET_MISSING,
            TX_MESSAGE_NONE
        );
        return;
    }
    if (command->kind == AINEKIO_COMMAND_LIMITS && !calibration_limits_valid(command)) {
        claim_and_nak(runtime, command->sequence, AINEKIO_NAK_LIMIT, TX_MESSAGE_NONE);
        return;
    }
    if (command->kind == AINEKIO_COMMAND_MODE &&
        command->data.mode == AINEKIO_MODE_CALIBRATE &&
        ainekio_motion_service_busy(&runtime->motion)) {
        claim_and_nak(runtime, command->sequence, AINEKIO_NAK_BUSY, TX_MESSAGE_NONE);
        return;
    }
    if (command->kind == AINEKIO_COMMAND_STATE &&
        command->data.state.request == AINEKIO_STATE_REQUEST_SLEEP &&
        (ainekio_motion_service_busy(&runtime->motion) ||
         ainekio_audio_busy(runtime->audio))) {
        claim_and_nak(runtime, command->sequence, AINEKIO_NAK_BUSY, TX_MESSAGE_NONE);
        return;
    }
    if (command->kind == AINEKIO_COMMAND_SERVO) {
        float physical = 0.0F;
        if (command->data.servo.id >= AINEKIO_SERVO_COUNT ||
            ainekio_motion_service_busy(&runtime->motion) ||
            ainekio_servo_map_logical(
                &runtime->servos->channels[command->data.servo.id].calibration,
                command->data.servo.degrees,
                &physical
            ) != AINEKIO_SERVO_OK) {
            claim_and_nak(
                runtime,
                command->sequence,
                command->data.servo.id >= AINEKIO_SERVO_COUNT ||
                        !ainekio_motion_service_busy(&runtime->motion)
                    ? AINEKIO_NAK_LIMIT
                    : AINEKIO_NAK_BUSY,
                TX_MESSAGE_NONE
            );
            return;
        }
    }

    const ainekio_profile_t prior_profile = runtime->core->profile;
    const ainekio_decision_t decision = ainekio_core_accept(runtime->core, command);
    if (!decision.accepted) {
        (void)queue_nak(
            runtime,
            true,
            command->sequence,
            rejection_code(decision.rejection),
            TX_MESSAGE_NONE,
            false
        );
        return;
    }

    if (command->kind == AINEKIO_COMMAND_STATE &&
        command->data.state.request == AINEKIO_STATE_REQUEST_SLEEP) {
        (void)ainekio_motion_service_request_stop(&runtime->motion);
        (void)cancel_audio(runtime);
        if (!queue_ack(
                runtime,
                command->sequence,
                command->data.state.sleep_seconds,
                false
            )) {
            return;
        }
        wifi_ap_record_t access_point;
        const int8_t rssi = esp_wifi_sta_get_ap_info(&access_point) == ESP_OK
                                ? access_point.rssi
                                : -127;
        tx_item_t status = tx_base(runtime, TX_STATUS);
        status.data.status = runtime_status(
            runtime,
            rssi,
            AINEKIO_STATE_DEEP_SLEEP,
            (uint32_t)(now_us() / INT64_C(1000000))
        );
        tx_item_t done = tx_base(runtime, TX_DONE);
        done.data.sequence = command->sequence;
        tx_item_t close = tx_base(runtime, TX_CLOSE);
        close.data.close.code = 1000U;
        close.data.close.sleep_seconds = command->data.state.sleep_seconds;
        close.data.close.battery_cutoff = false;
        (void)enqueue_tx(runtime, &status, false);
        (void)enqueue_tx(runtime, &done, false);
        (void)enqueue_tx(runtime, &close, false);
        return;
    }

    esp_err_t persistence = ESP_OK;
    uint32_t cancelled_audio_sequence = 0U;
    bool audio_overflow = false;
    if (command->kind == AINEKIO_COMMAND_PROFILE) {
        persistence = ainekio_nvs_adapter_save_profile(command->data.profile);
        if (persistence != ESP_OK) {
            ainekio_core_set_profile(runtime->core, prior_profile);
        }
    } else if (command->kind == AINEKIO_COMMAND_WAKE_CONFIG) {
        persistence = ainekio_nvs_adapter_save_wake_preferences(
            command->data.wake.enabled,
            command->data.wake.model
        );
        if (persistence == ESP_OK) {
            runtime->wake_enabled = command->data.wake.enabled;
            (void)strcpy(runtime->wake_model, command->data.wake.model);
            if (!runtime->wake_enabled && runtime->microphone_enabled &&
                runtime->microphone_gate == AINEKIO_MIC_GATE_WAKE) {
                runtime->microphone_enabled = false;
                ainekio_audio_set_microphone(
                    runtime->audio,
                    false,
                    AINEKIO_MIC_GATE_WAKE
                );
            }
        }
    } else if (command->kind == AINEKIO_COMMAND_LIMITS) {
        const ainekio_servo_calibration_t calibration = {
            .minimum_degrees = command->data.limits.minimum,
            .center_degrees = command->data.limits.center,
            .maximum_degrees = command->data.limits.maximum,
            .invert = command->data.limits.invert,
        };
        if (ainekio_servo_set_calibration(
                runtime->servos,
                command->data.limits.id,
                &calibration
            ) != AINEKIO_SERVO_OK) {
            persistence = ESP_ERR_INVALID_ARG;
        }
        runtime->calibration_activity_us = now_us();
    } else if (command->kind == AINEKIO_COMMAND_SERVO) {
        const ainekio_motion_submit_result_t result =
            ainekio_motion_service_calibrate_servo(
                &runtime->motion,
                command->data.servo.id,
                command->data.servo.degrees,
                command->data.servo.duration_ms
            );
        if (result != AINEKIO_MOTION_SUBMIT_OK) {
            persistence = result == AINEKIO_MOTION_SUBMIT_LIMIT
                              ? ESP_ERR_INVALID_ARG
                              : ESP_ERR_INVALID_STATE;
        }
        runtime->calibration_activity_us = now_us();
    } else if (command->kind == AINEKIO_COMMAND_POSE_SAVE) {
        if (!ainekio_pose_bank_put(
                runtime->poses,
                command->data.pose.name,
                command->data.pose.targets,
                command->data.pose.count
            )) {
            persistence = ESP_ERR_INVALID_ARG;
        }
        runtime->calibration_activity_us = now_us();
    } else if (command->kind == AINEKIO_COMMAND_CALIBRATION_SAVE) {
        persistence = ainekio_nvs_adapter_save_calibration(runtime->servos);
        if (persistence == ESP_OK) {
            persistence = ainekio_nvs_adapter_save_poses(runtime->poses);
        }
        runtime->calibration_activity_us = now_us();
    } else if (command->kind == AINEKIO_COMMAND_MODE) {
        runtime->calibration_activity_us = command->data.mode == AINEKIO_MODE_CALIBRATE
                                               ? now_us()
                                               : 0;
        if (command->data.mode == AINEKIO_MODE_NORMAL) {
            (void)ainekio_motion_service_request_stop(&runtime->motion);
        }
    } else if (command->kind == AINEKIO_COMMAND_CAMERA) {
        const bool prior_enabled = runtime->camera_enabled;
        const uint8_t prior_fps = runtime->camera_fps;
        const ainekio_camera_resolution_t prior_resolution =
            runtime->camera_resolution;
        runtime->camera_enabled = command->data.camera.enabled;
        runtime->camera_fps = command->data.camera.fps;
        runtime->camera_resolution = command->data.camera.resolution;
        persistence = sync_camera_stream(runtime);
        if (persistence != ESP_OK) {
            runtime->camera_enabled = prior_enabled;
            runtime->camera_fps = prior_fps;
            runtime->camera_resolution = prior_resolution;
        }
    } else if (command->kind == AINEKIO_COMMAND_MICROPHONE) {
        runtime->microphone_enabled = command->data.microphone.enabled;
        runtime->microphone_gate = command->data.microphone.gate;
        ainekio_audio_set_microphone(
            runtime->audio,
            command->data.microphone.enabled,
            command->data.microphone.gate
        );
    } else if (command->kind == AINEKIO_COMMAND_TTS) {
        ainekio_audio_result_t audio_result = AINEKIO_AUDIO_OK;
        if (command->data.tts_operation == AINEKIO_TTS_START) {
            audio_result = ainekio_audio_tts_start(
                runtime->audio,
                command->sequence
            );
            if (audio_result == AINEKIO_AUDIO_OK) {
                ainekio_display_begin_talk(runtime->display);
            }
        } else if (command->data.tts_operation == AINEKIO_TTS_END) {
            audio_result = ainekio_audio_tts_end(runtime->audio);
            if (audio_result == AINEKIO_AUDIO_OVERFLOW) {
                cancelled_audio_sequence = cancel_audio(runtime);
                audio_overflow = true;
                audio_result = AINEKIO_AUDIO_OK;
            }
        } else {
            cancelled_audio_sequence = cancel_audio(runtime);
        }
        if (audio_result != AINEKIO_AUDIO_OK) {
            persistence = audio_result == AINEKIO_AUDIO_ORPHAN
                              ? ESP_ERR_INVALID_STATE
                              : ESP_ERR_NOT_FINISHED;
        }
    } else if (command->kind == AINEKIO_COMMAND_INTENT &&
               command->data.intent.kind == AINEKIO_INTENT_SAY) {
        const ainekio_audio_result_t audio_result = ainekio_audio_say(
            runtime->audio,
            command->sequence,
            command->data.intent.data.asset
        );
        if (audio_result != AINEKIO_AUDIO_OK) {
            persistence = audio_result == AINEKIO_AUDIO_ASSET_MISSING
                              ? ESP_ERR_NOT_FOUND
                              : ESP_ERR_INVALID_STATE;
        } else {
            ainekio_display_begin_talk(runtime->display);
        }
    } else if (command->kind == AINEKIO_COMMAND_INTENT &&
               command->data.intent.kind == AINEKIO_INTENT_FACE &&
               runtime->display != NULL) {
        persistence = ainekio_display_show_face(
            runtime->display,
            command->data.intent.data.asset,
            AINEKIO_FACE_MODE_ONCE,
            false,
            true
        );
    }

    if (persistence != ESP_OK) {
        (void)queue_nak(
            runtime,
            true,
            command->sequence,
            persistence == ESP_ERR_INVALID_ARG
                ? AINEKIO_NAK_LIMIT
                : (persistence == ESP_ERR_NOT_FOUND ? AINEKIO_NAK_ASSET_MISSING
                                                    : AINEKIO_NAK_BUSY),
            (command->kind == AINEKIO_COMMAND_PROFILE ||
             command->kind == AINEKIO_COMMAND_WAKE_CONFIG ||
             command->kind == AINEKIO_COMMAND_CALIBRATION_SAVE)
                ? TX_MESSAGE_NVS_WRITE_FAILED
                : TX_MESSAGE_NONE,
            false
        );
        return;
    }
    (void)queue_ack(runtime, command->sequence, 0U, false);
    if (command->kind == AINEKIO_COMMAND_CAMERA) {
        tx_item_t meta = tx_base(runtime, TX_CAMERA_META);
        meta.data.camera_meta.resolution = command->data.camera.resolution;
        meta.data.camera_meta.fps = command->data.camera.enabled
                                        ? command->data.camera.fps
                                        : 0U;
        meta.data.camera_meta.counter_base =
            ainekio_camera_counter_base(runtime->camera);
        (void)enqueue_tx(runtime, &meta, false);
    }
    if (audio_overflow) {
        queue_event(runtime, AINEKIO_EVENT_TTS_OVERFLOW);
    }
    if (cancelled_audio_sequence != 0U) {
        tx_item_t cancelled = tx_base(runtime, TX_CANCELLED);
        cancelled.data.cancelled.sequence = cancelled_audio_sequence;
        cancelled.data.cancelled.code = audio_overflow ? AINEKIO_CANCEL_OVERFLOW
                                                       : AINEKIO_CANCEL_STOP;
        (void)enqueue_tx(runtime, &cancelled, false);
    }
    const bool audio_completes_later =
        (command->kind == AINEKIO_COMMAND_TTS &&
         command->data.tts_operation == AINEKIO_TTS_START) ||
        (command->kind == AINEKIO_COMMAND_INTENT &&
         command->data.intent.kind == AINEKIO_INTENT_SAY);
    if (decision.lifecycle == AINEKIO_LIFECYCLE_ACK_THEN_DONE &&
        !audio_completes_later) {
        tx_item_t done = tx_base(runtime, TX_DONE);
        done.data.sequence = command->sequence;
        (void)enqueue_tx(runtime, &done, false);
        runtime->last_intent_us = now_us();
    }
}

static void dispatch_stop(ainekio_runtime_t *runtime, const stop_item_t *item)
{
    if (!session_matches(runtime, item->session_serial, true)) {
        return;
    }
    const ainekio_decision_t decision =
        ainekio_core_accept(runtime->core, &item->command);
    if (decision.accepted) {
        (void)queue_ack(runtime, item->command.sequence, 0U, true);
    } else {
        (void)queue_nak(
            runtime,
            true,
            item->command.sequence,
            rejection_code(decision.rejection),
            TX_MESSAGE_NONE,
            true
        );
    }
    if (item->cancelled_sequence != 0U) {
        tx_item_t cancelled = tx_base(runtime, TX_CANCELLED);
        cancelled.data.cancelled.sequence = item->cancelled_sequence;
        cancelled.data.cancelled.code = AINEKIO_CANCEL_STOP;
        (void)enqueue_tx(runtime, &cancelled, true);
    }
    if (item->cancelled_audio_sequence != 0U) {
        tx_item_t cancelled = tx_base(runtime, TX_CANCELLED);
        cancelled.data.cancelled.sequence = item->cancelled_audio_sequence;
        cancelled.data.cancelled.code = AINEKIO_CANCEL_STOP;
        (void)enqueue_tx(runtime, &cancelled, true);
    }
}

static void dispatch_internal(
    ainekio_runtime_t *runtime,
    const internal_item_t *item
)
{
    if (item->kind == INTERNAL_FAILSAFE) {
        ainekio_core_enter_failsafe(runtime->core);
        return;
    }
    if (!session_matches(runtime, item->session_serial, false)) {
        return;
    }
    ainekio_core_begin_session(runtime->core, item->epoch);
    ainekio_core_set_profile(runtime->core, item->profile);
    taskENTER_CRITICAL(&runtime->state_lock);
    runtime->authenticated = true;
    taskEXIT_CRITICAL(&runtime->state_lock);
    runtime->last_intent_us = now_us();
    runtime->next_status_us = now_us();
    if (!runtime->ota_validation_checked) {
        const esp_err_t ota_result = esp_ota_mark_app_valid_cancel_rollback();
        if (ota_result == ESP_OK ||
            ota_result == ESP_ERR_OTA_ROLLBACK_INVALID_STATE) {
            runtime->ota_validation_checked = true;
            if (ota_result == ESP_OK) {
                ESP_LOGI(TAG, "pending OTA image accepted after gateway authentication");
            }
        } else {
            ESP_LOGE(
                TAG,
                "pending OTA image could not be accepted: %s",
                esp_err_to_name(ota_result)
            );
        }
    }
    if (runtime->boot_event_pending) {
        runtime->boot_event_pending = false;
        queue_event(runtime, AINEKIO_EVENT_BOOT);
    }
    if (runtime->brownout_recovered_pending) {
        runtime->brownout_recovered_pending = false;
        queue_event(runtime, AINEKIO_EVENT_BROWNOUT_RECOVERED);
    }
    if (runtime->littlefs_failure_pending) {
        runtime->littlefs_failure_pending = false;
        queue_event(runtime, AINEKIO_EVENT_LITTLEFS_FAIL);
    }
    if (runtime->sd_corrupt_pending) {
        runtime->sd_corrupt_pending = false;
        runtime->sd_failure_pending = false;
        queue_event(runtime, AINEKIO_EVENT_SD_CORRUPT);
    } else if (runtime->sd_failure_pending) {
        runtime->sd_failure_pending = false;
        queue_event(runtime, AINEKIO_EVENT_SD_FAIL);
    }
}

static void dispatch_battery(
    ainekio_runtime_t *runtime,
    const battery_item_t *item
)
{
    runtime->battery_voltage = item->volts;
    ainekio_core_set_power_guard(
        runtime->core,
        item->state == AINEKIO_BATTERY_NORMAL
            ? AINEKIO_POWER_NORMAL
            : (item->state == AINEKIO_BATTERY_WARN
                   ? AINEKIO_POWER_MOVE_LOCKED
                   : AINEKIO_POWER_CUTOFF)
    );
    runtime->battery_events_pending |= item->events;
    if ((runtime->battery_events_pending & AINEKIO_BATTERY_EVENT_CUTOFF) != 0U) {
        ainekio_core_set_state(runtime->core, AINEKIO_STATE_DEEP_SLEEP);
        runtime->battery_events_pending &= ~AINEKIO_BATTERY_EVENT_CUTOFF;
        if (!session_matches(runtime, current_serial(runtime), true)) {
            ainekio_sleep_enter(30U * 60U, true);
        }
        tx_item_t event = tx_base(runtime, TX_EVENT);
        event.data.event = AINEKIO_EVENT_BATTERY_CUTOFF;
        wifi_ap_record_t access_point;
        const int8_t rssi = esp_wifi_sta_get_ap_info(&access_point) == ESP_OK
                                ? access_point.rssi
                                : -127;
        tx_item_t status = tx_base(runtime, TX_STATUS);
        status.data.status = runtime_status(
            runtime,
            rssi,
            AINEKIO_STATE_DEEP_SLEEP,
            (uint32_t)(now_us() / INT64_C(1000000))
        );
        tx_item_t close = tx_base(runtime, TX_CLOSE);
        close.data.close.code = 1000U;
        close.data.close.sleep_seconds = 30U * 60U;
        close.data.close.battery_cutoff = true;
        (void)enqueue_tx(runtime, &event, true);
        (void)enqueue_tx(runtime, &status, true);
        (void)enqueue_tx(runtime, &close, true);
        return;
    }
    if (!session_matches(runtime, current_serial(runtime), true)) {
        return;
    }
    if ((runtime->battery_events_pending & AINEKIO_BATTERY_EVENT_WARN) != 0U) {
        queue_event(runtime, AINEKIO_EVENT_BATTERY_WARN);
    }
    if ((runtime->battery_events_pending & AINEKIO_BATTERY_EVENT_CUTOFF) != 0U) {
        queue_event(runtime, AINEKIO_EVENT_BATTERY_CUTOFF);
    }
    if ((runtime->battery_events_pending & AINEKIO_BATTERY_EVENT_RECOVERED) != 0U) {
        queue_event(runtime, AINEKIO_EVENT_BROWNOUT_RECOVERED);
    }
    runtime->battery_events_pending = AINEKIO_BATTERY_EVENT_NONE;
}

static void dispatch_sd(ainekio_runtime_t *runtime, const sd_item_t *item)
{
    runtime->sd_available = item->state == AINEKIO_SD_MOUNTED;
    if (item->state == AINEKIO_SD_MOUNTED) {
        return;
    }
    const bool authenticated =
        session_matches(runtime, current_serial(runtime), true);
    if (item->state == AINEKIO_SD_CORRUPT) {
        if (authenticated) {
            queue_event(runtime, AINEKIO_EVENT_SD_CORRUPT);
        } else {
            runtime->sd_corrupt_pending = true;
        }
    } else if (authenticated) {
        queue_event(runtime, AINEKIO_EVENT_SD_FAIL);
    } else {
        runtime->sd_failure_pending = true;
    }
}

static void dispatcher_tick(ainekio_runtime_t *runtime)
{
    const int64_t now = now_us();
    if (runtime->core->state == AINEKIO_STATE_ACTIVE &&
        now - runtime->last_intent_us >= ACTIVE_IDLE_US) {
        ainekio_core_set_state(runtime->core, AINEKIO_STATE_IDLE);
    }
    if (runtime->core->mode == AINEKIO_MODE_CALIBRATE &&
        runtime->calibration_activity_us > 0 &&
        now - runtime->calibration_activity_us >= CALIBRATION_IDLE_US) {
        ainekio_core_set_mode(runtime->core, AINEKIO_MODE_NORMAL);
        runtime->calibration_activity_us = 0;
        (void)ainekio_motion_service_request_stop(&runtime->motion);
    }
    if (runtime->display_state != (uint8_t)runtime->core->state) {
        runtime->display_state = (uint8_t)runtime->core->state;
        ainekio_display_set_idle(
            runtime->display,
            runtime->core->state == AINEKIO_STATE_IDLE
        );
    }
    (void)sync_camera_stream(runtime);
    if (!session_matches(runtime, current_serial(runtime), true) ||
        now < runtime->next_status_us) {
        return;
    }
    if (runtime->audio != NULL) {
        runtime->speaker_underruns =
            ainekio_audio_speaker_underruns(runtime->audio);
    }
    wifi_ap_record_t access_point;
    const int8_t rssi = esp_wifi_sta_get_ap_info(&access_point) == ESP_OK
                            ? access_point.rssi
                            : -127;
    tx_item_t status = tx_base(runtime, TX_STATUS);
    status.data.status = runtime_status(
        runtime,
        rssi,
        runtime->core->state,
        (uint32_t)(now / INT64_C(1000000))
    );
    (void)enqueue_tx(runtime, &status, false);
    const bool slow = runtime->core->profile == AINEKIO_PROFILE_TETHER ||
                      runtime->core->state == AINEKIO_STATE_DOZING;
    runtime->next_status_us = now + (slow ? INT64_C(30000000) : INT64_C(5000000));
}

static void dispatcher_task(void *argument)
{
    ainekio_runtime_t *runtime = argument;
    while (true) {
        sd_item_t sd;
        if (xQueueReceive(runtime->sd_queue, &sd, 0U) == pdTRUE) {
            dispatch_sd(runtime, &sd);
            continue;
        }
        battery_item_t battery;
        if (xQueueReceive(runtime->battery_queue, &battery, 0U) == pdTRUE) {
            dispatch_battery(runtime, &battery);
            continue;
        }
        stop_item_t stop;
        if (xQueueReceive(runtime->stop_queue, &stop, 0U) == pdTRUE) {
            dispatch_stop(runtime, &stop);
            continue;
        }
        internal_item_t internal;
        if (xQueueReceive(runtime->internal_queue, &internal, 0U) == pdTRUE) {
            dispatch_internal(runtime, &internal);
            continue;
        }
        rx_command_item_t command;
        if (xQueueReceive(runtime->command_queue, &command, pdMS_TO_TICKS(20U)) ==
            pdTRUE) {
            dispatch_command(runtime, &command);
        }
        dispatcher_tick(runtime);
    }
}

static void handle_decoded_control(
    ainekio_runtime_t *runtime,
    const ainekio_control_message_t *message,
    ainekio_decode_result_t result,
    uint32_t serial
)
{
    if (result == AINEKIO_DECODE_UNKNOWN && message->has_sequence) {
        if (!session_matches(runtime, serial, true)) {
            force_disconnect(runtime);
            return;
        }
        const rx_command_item_t item = {
            .session_serial = serial,
            .kind = RX_UNKNOWN_INTENT,
            .sequence = message->sequence,
        };
        if (xQueueSend(runtime->command_queue, &item, 0U) != pdTRUE) {
            force_disconnect(runtime);
        }
        return;
    }
    if (result != AINEKIO_DECODE_OK) {
        (void)queue_nak(
            runtime,
            message->has_sequence,
            message->sequence,
            AINEKIO_NAK_MALFORMED,
            TX_MESSAGE_NONE,
            false
        );
        return;
    }
    if (message->kind == AINEKIO_MESSAGE_PING) {
        tx_item_t pong = tx_base(runtime, TX_PONG);
        (void)enqueue_tx(runtime, &pong, true);
        return;
    }
    if (message->kind == AINEKIO_MESSAGE_PONG) {
        return;
    }
    if (message->kind == AINEKIO_MESSAGE_ERROR) {
        tx_item_t close = tx_base(runtime, TX_CLOSE);
        close.data.close.code =
            message->data.session_error == AINEKIO_SESSION_ERROR_AUTH ? 4001U
                                                                      : 4002U;
        if (message->data.session_error == AINEKIO_SESSION_ERROR_AUTH) {
            ainekio_provisioning_service_request_gateway_auth_failure(
                runtime->provisioning
            );
        }
        (void)enqueue_tx(runtime, &close, true);
        return;
    }
    if (message->kind == AINEKIO_MESSAGE_WELCOME) {
        if (session_matches(runtime, serial, true)) {
            force_disconnect(runtime);
            return;
        }
        const internal_item_t item = {
            .kind = INTERNAL_WELCOME,
            .session_serial = serial,
            .epoch = message->data.welcome.epoch,
            .profile = message->data.welcome.profile,
        };
        if (xQueueSend(runtime->internal_queue, &item, 0U) != pdTRUE) {
            force_disconnect(runtime);
        }
        return;
    }
    if (!session_matches(runtime, serial, true) || !message->has_command) {
        force_disconnect(runtime);
        return;
    }
    if (message->command.kind == AINEKIO_COMMAND_STOP) {
        const stop_item_t stop = {
            .session_serial = serial,
            .command = message->command,
            .cancelled_sequence =
                ainekio_motion_service_request_stop(&runtime->motion),
            .cancelled_audio_sequence = cancel_audio(runtime),
        };
        if (xQueueSend(runtime->stop_queue, &stop, 0U) != pdTRUE) {
            force_disconnect(runtime);
        }
        return;
    }
    const rx_command_item_t item = {
        .session_serial = serial,
        .kind = RX_COMMAND,
        .sequence = message->sequence,
        .command = message->command,
    };
    if (xQueueSend(runtime->command_queue, &item, 0U) != pdTRUE) {
        force_disconnect(runtime);
    }
}

static void handle_text_chunk(
    ainekio_runtime_t *runtime,
    const esp_websocket_event_data_t *data
)
{
    if (data->payload_offset == 0) {
        runtime->rx_text_expected = data->payload_len > 0
                                        ? (size_t)data->payload_len
                                        : 0U;
        runtime->rx_text_discard = data->payload_len <= 0 ||
                                   data->payload_len > (int)AINEKIO_CONTROL_MAX_BYTES ||
                                   !data->fin;
    }
    if (runtime->rx_text_discard || data->payload_offset < 0 || data->data_len < 0 ||
        (size_t)data->payload_offset + (size_t)data->data_len >
            runtime->rx_text_expected) {
        if (data->payload_offset + data->data_len >= data->payload_len) {
            (void)queue_nak(
                runtime,
                false,
                0U,
                AINEKIO_NAK_MALFORMED,
                TX_MESSAGE_NONE,
                false
            );
        }
        return;
    }
    memcpy(
        runtime->rx_text + (size_t)data->payload_offset,
        data->data_ptr,
        (size_t)data->data_len
    );
    if ((size_t)data->payload_offset + (size_t)data->data_len !=
        runtime->rx_text_expected) {
        return;
    }
    runtime->rx_text[runtime->rx_text_expected] = '\0';
    taskENTER_CRITICAL(&runtime->state_lock);
    runtime->last_rx_control_us = now_us();
    const uint32_t serial = runtime->session_serial;
    taskEXIT_CRITICAL(&runtime->state_lock);
    ainekio_control_message_t message;
    const ainekio_decode_result_t result = ainekio_control_decode(
        runtime->rx_text,
        runtime->rx_text_expected,
        &message
    );
    handle_decoded_control(runtime, &message, result, serial);
}

static void handle_binary_chunk(
    ainekio_runtime_t *runtime,
    const esp_websocket_event_data_t *data
)
{
    if (data->payload_offset == 0) {
        runtime->rx_binary_expected = data->payload_len > 0
                                          ? (size_t)data->payload_len
                                          : 0U;
        runtime->rx_binary_discard = runtime->audio == NULL || !data->fin ||
                                     data->payload_len <= 0 ||
                                     data->payload_len > (int)sizeof(runtime->rx_binary);
        if (!runtime->rx_binary_discard && data->data_len > 0 &&
            (uint8_t)data->data_ptr[0] != AINEKIO_FRAME_SPEAKER_PCM) {
            runtime->rx_binary_discard = true;
        }
    }
    if (runtime->rx_binary_discard || data->payload_offset < 0 ||
        data->data_len < 0 ||
        (size_t)data->payload_offset + (size_t)data->data_len >
            runtime->rx_binary_expected) {
        return;
    }
    memcpy(
        runtime->rx_binary + (size_t)data->payload_offset,
        data->data_ptr,
        (size_t)data->data_len
    );
    if ((size_t)data->payload_offset + (size_t)data->data_len !=
        runtime->rx_binary_expected) {
        return;
    }
    ainekio_binary_frame_t frame;
    if (ainekio_binary_decode(
            runtime->rx_binary,
            runtime->rx_binary_expected,
            &frame
        ) != AINEKIO_BINARY_OK ||
        frame.type != AINEKIO_FRAME_SPEAKER_PCM) {
        return;
    }
    const ainekio_audio_result_t result =
        ainekio_audio_push_speaker(runtime->audio, frame.payload);
    if (result == AINEKIO_AUDIO_ORPHAN) {
        queue_event(runtime, AINEKIO_EVENT_TTS_ORPHAN);
    } else if (result == AINEKIO_AUDIO_OVERFLOW) {
        const uint32_t cancelled = cancel_audio(runtime);
        queue_event(runtime, AINEKIO_EVENT_TTS_OVERFLOW);
        if (cancelled != 0U) {
            tx_item_t item = tx_base(runtime, TX_CANCELLED);
            item.data.cancelled.sequence = cancelled;
            item.data.cancelled.code = AINEKIO_CANCEL_OVERFLOW;
            (void)enqueue_tx(runtime, &item, false);
        }
    }
}

static void websocket_event(
    void *handler_argument,
    esp_event_base_t event_base,
    int32_t event_id,
    void *event_data
)
{
    (void)event_base;
    ainekio_runtime_t *runtime = handler_argument;
    esp_websocket_event_data_t *data = event_data;
    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        taskENTER_CRITICAL(&runtime->state_lock);
        ++runtime->session_serial;
        if (runtime->session_serial == 0U) {
            ++runtime->session_serial;
        }
        runtime->connected = true;
        runtime->authenticated = false;
        runtime->failsafe_signalled = false;
        runtime->ping_pending = false;
        runtime->last_rx_control_us = now_us();
        runtime->last_tx_control_us = runtime->last_rx_control_us;
        const uint32_t serial = runtime->session_serial;
        taskEXIT_CRITICAL(&runtime->state_lock);
        const tx_item_t hello = {
            .session_serial = serial,
            .kind = TX_HELLO,
        };
        (void)enqueue_tx(runtime, &hello, true);
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DATA && data != NULL) {
        if (data->op_code == 0x01U) {
            handle_text_chunk(runtime, data);
        } else if (data->op_code == 0x02U) {
            handle_binary_chunk(runtime, data);
        } else if (data->op_code == 0x00U) {
            force_disconnect(runtime);
        }
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DISCONNECTED ||
        event_id == WEBSOCKET_EVENT_CLOSED) {
        taskENTER_CRITICAL(&runtime->state_lock);
        runtime->connected = false;
        runtime->authenticated = false;
        runtime->ping_pending = false;
        taskEXIT_CRITICAL(&runtime->state_lock);
        signal_failsafe(runtime);
        if (runtime->supervisor_task != NULL) {
            (void)xTaskNotify(
                runtime->supervisor_task,
                SUPERVISOR_DISCONNECTED,
                eSetBits
            );
        }
    }
}

static void flush_session_queues(ainekio_runtime_t *runtime)
{
    (void)xQueueReset(runtime->command_queue);
    (void)xQueueReset(runtime->stop_queue);
    (void)xQueueReset(runtime->internal_queue);
    (void)xQueueReset(runtime->tx_queue);
    (void)xQueueReset(runtime->fast_tx_queue);
    (void)xQueueReset(runtime->mic_queue);
    camera_tx_item_t camera;
    while (xQueueReceive(runtime->camera_queue, &camera, 0U) == pdTRUE) {
        heap_caps_free(camera.bytes);
    }
    (void)xQueueReset(runtime->camera_queue);
}

static void destroy_client(ainekio_runtime_t *runtime)
{
    if (xSemaphoreTake(runtime->client_lock, pdMS_TO_TICKS(1000U)) != pdTRUE) {
        return;
    }
    esp_websocket_client_handle_t client = runtime->client;
    runtime->client = NULL;
    if (client != NULL) {
        (void)esp_websocket_client_stop(client);
        (void)esp_websocket_client_destroy(client);
    }
    (void)xSemaphoreGive(runtime->client_lock);
}

static esp_err_t create_client(ainekio_runtime_t *runtime)
{
    taskENTER_CRITICAL(&runtime->state_lock);
    (void)strcpy(runtime->client_endpoint, runtime->active_config.endpoint_url);
    taskEXIT_CRITICAL(&runtime->state_lock);
    const bool secure = strncmp(runtime->client_endpoint, "wss://", 6U) == 0;
    const esp_websocket_client_config_t config = {
        .uri = runtime->client_endpoint,
        .disable_auto_reconnect = true,
        .enable_close_reconnect = false,
        .user_context = runtime,
        .task_core_id_set = true,
        .task_core_id = 0,
        .task_prio = 10,
        .task_name = "ws_rx",
        .task_stack = 6144,
        .buffer_size = AINEKIO_CONTROL_MAX_BYTES,
        .crt_bundle_attach = secure ? esp_crt_bundle_attach : NULL,
        .keep_alive_enable = true,
        .keep_alive_idle = 5,
        .keep_alive_interval = 5,
        .keep_alive_count = 3,
        .network_timeout_ms = WRITE_TIMEOUT_MS,
        .ping_interval_sec = 10U,
    };
    esp_websocket_client_handle_t client = esp_websocket_client_init(&config);
    if (client == NULL) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t result = esp_websocket_register_events(
        client,
        WEBSOCKET_EVENT_ANY,
        websocket_event,
        runtime
    );
    if (result == ESP_OK) {
        if (xSemaphoreTake(runtime->client_lock, pdMS_TO_TICKS(1000U)) != pdTRUE) {
            result = ESP_ERR_TIMEOUT;
        } else {
            runtime->client = client;
            (void)xSemaphoreGive(runtime->client_lock);
        }
    }
    if (result == ESP_OK) {
        result = esp_websocket_client_start(client);
    }
    if (result != ESP_OK) {
        if (runtime->client == client) {
            runtime->client = NULL;
        }
        (void)esp_websocket_client_destroy(client);
    }
    return result;
}

static uint32_t jittered_delay(uint32_t base_ms)
{
    const uint32_t span = base_ms / 5U;
    if (span == 0U) {
        return base_ms;
    }
    const uint32_t width = span * 2U + 1U;
    return base_ms - span + esp_random() % width;
}

static void supervisor_liveness(ainekio_runtime_t *runtime)
{
    const int64_t now = now_us();
    bool connected = false;
    bool authenticated = false;
    bool ping = false;
    bool failsafe = false;
    uint32_t serial = 0U;
    taskENTER_CRITICAL(&runtime->state_lock);
    connected = runtime->connected;
    authenticated = runtime->authenticated;
    serial = runtime->session_serial;
    if (connected && now - runtime->last_rx_control_us >= CONTROL_FAILSAFE_US) {
        failsafe = true;
    } else if (authenticated && !runtime->ping_pending &&
               now - runtime->last_tx_control_us >= CONTROL_PING_US) {
        runtime->ping_pending = true;
        ping = true;
    }
    taskEXIT_CRITICAL(&runtime->state_lock);
    if (failsafe) {
        force_disconnect(runtime);
    } else if (ping) {
        const tx_item_t item = {
            .session_serial = serial,
            .kind = TX_PING,
        };
        if (!enqueue_tx(runtime, &item, true)) {
            taskENTER_CRITICAL(&runtime->state_lock);
            runtime->ping_pending = false;
            taskEXIT_CRITICAL(&runtime->state_lock);
        }
    }
}

static void supervisor_task(void *argument)
{
    ainekio_runtime_t *runtime = argument;
    uint32_t backoff_ms = 1000U;
    int64_t attempt_at_us = 0;
    uint32_t seen_generation = 0U;
    while (true) {
        uint32_t notifications = 0U;
        (void)xTaskNotifyWait(
            0U,
            UINT32_MAX,
            &notifications,
            pdMS_TO_TICKS(50U)
        );
        supervisor_liveness(runtime);

        taskENTER_CRITICAL(&runtime->state_lock);
        const bool has_config = runtime->has_config;
        const uint32_t generation = runtime->config_generation;
        const bool connected = runtime->connected;
        taskEXIT_CRITICAL(&runtime->state_lock);

        if ((notifications & (SUPERVISOR_FORCE_CLOSE | SUPERVISOR_DISCONNECTED)) != 0U) {
            destroy_client(runtime);
            flush_session_queues(runtime);
            attempt_at_us = now_us() + (int64_t)jittered_delay(backoff_ms) * 1000;
            backoff_ms = backoff_ms < 30000U ? backoff_ms * 2U : 30000U;
            if (backoff_ms > 30000U) {
                backoff_ms = 30000U;
            }
        }
        if ((notifications & SUPERVISOR_ONLINE) != 0U ||
            generation != seen_generation) {
            destroy_client(runtime);
            flush_session_queues(runtime);
            seen_generation = generation;
            backoff_ms = 1000U;
            attempt_at_us = 0;
        }
        if (has_config && !connected && runtime->client == NULL &&
            now_us() >= attempt_at_us) {
            const esp_err_t result = create_client(runtime);
            if (result != ESP_OK) {
                ESP_LOGW(TAG, "gateway connection start failed: %s", esp_err_to_name(result));
                attempt_at_us =
                    now_us() + (int64_t)jittered_delay(backoff_ms) * 1000;
                backoff_ms = backoff_ms < 30000U ? backoff_ms * 2U : 30000U;
                if (backoff_ms > 30000U) {
                    backoff_ms = 30000U;
                }
            }
        }
    }
}

static bool initialize_queues(ainekio_runtime_t *runtime)
{
    runtime->command_queue = xQueueCreateStatic(
        COMMAND_QUEUE_LENGTH,
        sizeof(rx_command_item_t),
        runtime->command_queue_storage,
        &runtime->command_queue_control
    );
    runtime->stop_queue = xQueueCreateStatic(
        STOP_QUEUE_LENGTH,
        sizeof(stop_item_t),
        runtime->stop_queue_storage,
        &runtime->stop_queue_control
    );
    runtime->internal_queue = xQueueCreateStatic(
        INTERNAL_QUEUE_LENGTH,
        sizeof(internal_item_t),
        runtime->internal_queue_storage,
        &runtime->internal_queue_control
    );
    runtime->tx_queue = xQueueCreateStatic(
        TX_QUEUE_LENGTH,
        sizeof(tx_item_t),
        runtime->tx_queue_storage,
        &runtime->tx_queue_control
    );
    runtime->fast_tx_queue = xQueueCreateStatic(
        FAST_TX_QUEUE_LENGTH,
        sizeof(tx_item_t),
        runtime->fast_tx_queue_storage,
        &runtime->fast_tx_queue_control
    );
    runtime->mic_queue = xQueueCreateStatic(
        MIC_QUEUE_LENGTH,
        sizeof(mic_tx_item_t),
        runtime->mic_queue_storage,
        &runtime->mic_queue_control
    );
    runtime->camera_queue = xQueueCreate(
        CAMERA_QUEUE_LENGTH,
        sizeof(camera_tx_item_t)
    );
    runtime->battery_queue = xQueueCreateStatic(
        1U,
        sizeof(battery_item_t),
        runtime->battery_queue_storage,
        &runtime->battery_queue_control
    );
    runtime->sd_queue = xQueueCreateStatic(
        1U,
        sizeof(sd_item_t),
        runtime->sd_queue_storage,
        &runtime->sd_queue_control
    );
    return runtime->command_queue != NULL && runtime->stop_queue != NULL &&
           runtime->internal_queue != NULL && runtime->tx_queue != NULL &&
           runtime->fast_tx_queue != NULL && runtime->mic_queue != NULL &&
           runtime->camera_queue != NULL && runtime->battery_queue != NULL &&
           runtime->sd_queue != NULL;
}

esp_err_t ainekio_runtime_start(
    const ainekio_runtime_dependencies_t *dependencies,
    ainekio_runtime_t **runtime_output
)
{
    if (dependencies == NULL || runtime_output == NULL || dependencies->core == NULL ||
        dependencies->servos == NULL || dependencies->poses == NULL ||
        dependencies->mcpwm == NULL || dependencies->assets == NULL ||
        dependencies->provisioning == NULL || dependencies->firmware_version == NULL ||
        dependencies->wake_model == NULL ||
        strlen(dependencies->firmware_version) > 32U ||
        !ainekio_asset_name_valid(dependencies->wake_model)) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_runtime_t *runtime = &singleton;
    memset(runtime, 0, sizeof(*runtime));
    runtime->core = dependencies->core;
    runtime->servos = dependencies->servos;
    runtime->poses = dependencies->poses;
    runtime->mcpwm = dependencies->mcpwm;
    runtime->assets = dependencies->assets;
    runtime->provisioning = dependencies->provisioning;
    runtime->boot_event_pending = dependencies->boot_event_pending;
    runtime->brownout_recovered_pending =
        dependencies->brownout_recovered_pending;
    runtime->littlefs_failure_pending = dependencies->littlefs_failure_pending;
    runtime->wake_enabled = dependencies->wake_enabled;
    runtime->wake_ready = false;
    (void)strcpy(runtime->wake_model, dependencies->wake_model);
    runtime->display_state = UINT8_MAX;
    runtime->state_lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    (void)strcpy(runtime->firmware_version, dependencies->firmware_version);
    runtime->client_lock = xSemaphoreCreateMutexStatic(&runtime->client_lock_storage);
    if (runtime->client_lock == NULL || !initialize_queues(runtime)) {
        return ESP_ERR_NO_MEM;
    }

    const ainekio_motion_callbacks_t callbacks = {
        .context = runtime,
        .done = motion_done,
        .failed = motion_failed,
        .face = motion_face,
    };
    esp_err_t result = ainekio_motion_service_start(
        &runtime->motion,
        runtime->servos,
        runtime->poses,
        runtime->mcpwm,
        runtime->assets,
        &callbacks
    );
    if (result != ESP_OK) {
        return result;
    }
    const esp_err_t display_result = ainekio_display_service_start(
        runtime->assets,
        &runtime->display
    );
    if (display_result != ESP_OK) {
        runtime->display = NULL;
        ESP_LOGW(TAG, "display service unavailable: %s", esp_err_to_name(display_result));
    }
    const ainekio_camera_callbacks_t camera_callbacks = {
        .context = runtime,
        .frame = camera_frame,
        .failed = camera_failed,
    };
    const esp_err_t camera_result = ainekio_camera_service_start(
        &camera_callbacks,
        &runtime->camera
    );
    if (camera_result != ESP_OK) {
        runtime->camera = NULL;
        ESP_LOGW(TAG, "camera service unavailable: %s", esp_err_to_name(camera_result));
    }
    if (xTaskCreatePinnedToCore(
            tx_task,
            "ws_tx",
            4096U,
            runtime,
            9U,
            &runtime->tx_task,
            0
        ) != pdPASS ||
        xTaskCreatePinnedToCore(
            dispatcher_task,
            "dispatcher",
            6144U,
            runtime,
            8U,
            &runtime->dispatcher_task,
            0
        ) != pdPASS ||
        xTaskCreatePinnedToCore(
            supervisor_task,
            "ws_supervisor",
            4096U,
            runtime,
            7U,
            &runtime->supervisor_task,
            0
        ) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    const ainekio_sd_callbacks_t sd_callbacks = {
        .context = runtime,
        .state = sd_state_changed,
    };
    const esp_err_t sd_result = ainekio_sd_service_start(
        &sd_callbacks,
        &runtime->sd
    );
    if (sd_result != ESP_OK) {
        runtime->sd = NULL;
        runtime->sd_failure_pending = true;
        ESP_LOGW(TAG, "SD service unavailable: %s", esp_err_to_name(sd_result));
    }
    if (dependencies->battery_divider_factor > 0.0F) {
        const ainekio_telemetry_callbacks_t telemetry_callbacks = {
            .context = runtime,
            .battery = battery_observation,
        };
        const esp_err_t telemetry_result = ainekio_telemetry_service_start(
            dependencies->battery_divider_factor,
            dependencies->battery_adc_factor,
            &runtime->motion,
            &telemetry_callbacks,
            &runtime->telemetry
        );
        if (telemetry_result != ESP_OK) {
            runtime->telemetry = NULL;
            ESP_LOGW(
                TAG,
                "telemetry service unavailable: %s",
                esp_err_to_name(telemetry_result)
            );
        }
    }
    const ainekio_audio_callbacks_t audio_callbacks = {
        .context = runtime,
        .done = audio_done,
        .failed = audio_failed,
        .microphone = audio_microphone,
        .gate = audio_gate,
    };
    const esp_err_t audio_result = ainekio_audio_service_start(
        runtime->assets,
        runtime->wake_model,
        &audio_callbacks,
        &runtime->audio
    );
    if (audio_result != ESP_OK) {
        runtime->audio = NULL;
        ESP_LOGW(TAG, "audio service unavailable: %s", esp_err_to_name(audio_result));
    }
    runtime->wake_ready = ainekio_audio_wake_ready(runtime->audio);
    *runtime_output = runtime;
    return ESP_OK;
}

esp_err_t ainekio_runtime_network_online(
    ainekio_runtime_t *runtime,
    const ainekio_config_record_t *active_config
)
{
    if (runtime == NULL || active_config == NULL ||
        !ainekio_config_record_valid(active_config, true)) {
        return ESP_ERR_INVALID_ARG;
    }
    taskENTER_CRITICAL(&runtime->state_lock);
    runtime->active_config = *active_config;
    runtime->has_config = true;
    ++runtime->config_generation;
    if (runtime->config_generation == 0U) {
        ++runtime->config_generation;
    }
    taskEXIT_CRITICAL(&runtime->state_lock);
    if (runtime->supervisor_task == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    (void)xTaskNotify(runtime->supervisor_task, SUPERVISOR_ONLINE, eSetBits);
    return ESP_OK;
}

bool ainekio_runtime_audio_ready(const ainekio_runtime_t *runtime)
{
    return runtime != NULL && runtime->audio != NULL;
}

bool ainekio_runtime_camera_ready(const ainekio_runtime_t *runtime)
{
    return runtime != NULL && runtime->camera != NULL;
}

bool ainekio_runtime_display_ready(const ainekio_runtime_t *runtime)
{
    return runtime != NULL && runtime->display != NULL;
}

bool ainekio_runtime_telemetry_ready(const ainekio_runtime_t *runtime)
{
    return runtime != NULL && runtime->telemetry != NULL;
}

bool ainekio_runtime_sd_ready(const ainekio_runtime_t *runtime)
{
    return runtime != NULL && runtime->sd != NULL;
}

bool ainekio_runtime_sd_mounted(const ainekio_runtime_t *runtime)
{
    return runtime != NULL && ainekio_sd_available(runtime->sd);
}

esp_err_t ainekio_runtime_provision_display(
    ainekio_runtime_t *runtime,
    ainekio_provision_display_t status,
    const char *setup_secret
)
{
    if (runtime == NULL || runtime->display == NULL) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    switch (status) {
    case AINEKIO_PROVISION_DISPLAY_CONNECTING:
        return ainekio_display_show_status(
            runtime->display,
            "CONNECTING TO WIFI",
            NULL,
            NULL,
            NULL
        );
    case AINEKIO_PROVISION_DISPLAY_UNAVAILABLE:
        return ainekio_display_show_status(
            runtime->display,
            "WIFI UNAVAILABLE",
            NULL,
            NULL,
            NULL
        );
    case AINEKIO_PROVISION_DISPLAY_SETUP:
        return ainekio_display_show_status(
            runtime->display,
            "AINEKIO-SETUP",
            "SETUP SECRET",
            setup_secret,
            NULL
        );
    case AINEKIO_PROVISION_DISPLAY_CONNECTED:
        return ainekio_display_show_status(
            runtime->display,
            "WIFI CONNECTED",
            NULL,
            NULL,
            NULL
        );
    case AINEKIO_PROVISION_DISPLAY_GATEWAY_AUTH_FAILED:
        return ainekio_display_show_status(
            runtime->display,
            "GATEWAY AUTH FAILED",
            "CHECK ROBOT TOKEN",
            NULL,
            NULL
        );
    default:
        return ESP_ERR_INVALID_ARG;
    }
}

esp_err_t ainekio_runtime_provision_cue(
    ainekio_runtime_t *runtime,
    ainekio_provision_cue_t cue
)
{
    if (runtime == NULL || runtime->audio == NULL) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    const char *asset = cue == AINEKIO_PROVISION_CUE_SETUP
                            ? "setup_required"
                            : (cue == AINEKIO_PROVISION_CUE_CONNECTED
                                   ? "wifi_connected"
                                   : NULL);
    if (asset == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const ainekio_audio_result_t result =
        ainekio_audio_play_cue(runtime->audio, asset);
    return result == AINEKIO_AUDIO_OK
               ? ESP_OK
               : (result == AINEKIO_AUDIO_ASSET_MISSING ? ESP_ERR_NOT_FOUND
                                                        : ESP_ERR_INVALID_STATE);
}
