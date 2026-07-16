#include "ainekio/platform/audio_service.h"

#include <stdio.h>
#include <string.h>

#include "ainekio/platform/pin_map.h"
#include "ainekio/platform/wake_word_service.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define SPEAKER_PCM_LIMIT 25U
#define SPEAKER_QUEUE_LENGTH (SPEAKER_PCM_LIMIT + 1U)
#define AUDIO_NOTIFY_ASSET BIT0
#define AUDIO_NOTIFY_CANCEL BIT1
#define AUDIO_TASK_PRIORITY (configMAX_PRIORITIES - 2U)
#define AUDIO_BUS_WORDS 640U
#define VAD_THRESHOLD 900U
#define VAD_HANGOVER_FRAMES 10U
#define WAKE_SPEECH_HANGOVER_FRAMES 35U

typedef enum {
    SPEAKER_PCM = 0,
    SPEAKER_END,
} speaker_item_kind_t;

typedef struct {
    speaker_item_kind_t kind;
    uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES];
} speaker_item_t;

struct ainekio_audio_service {
    ainekio_asset_store_t *assets;
    ainekio_audio_callbacks_t callbacks;
    ainekio_wake_word_service_t *wake_word;
    i2s_chan_handle_t tx_channel;
    i2s_chan_handle_t rx_channel;
    TaskHandle_t task;
    portMUX_TYPE state_lock;
    QueueHandle_t speaker_queue;
    StaticQueue_t speaker_queue_control;
    uint8_t speaker_queue_storage[SPEAKER_QUEUE_LENGTH * sizeof(speaker_item_t)];
    int32_t bus_buffer[AUDIO_BUS_WORDS];
    uint8_t mic_payload[AINEKIO_AUDIO_PAYLOAD_BYTES];
    int16_t mic_samples[AINEKIO_AUDIO_PAYLOAD_BYTES / 2U];
    char asset_path[96];
    uint32_t tts_sequence;
    uint32_t asset_sequence;
    uint32_t asset_samples;
    uint32_t speaker_underruns;
    uint32_t microphone_drops;
    uint8_t speaker_frames_queued;
    ainekio_microphone_gate_t microphone_gate;
    uint8_t vad_hangover;
    bool tts_open;
    bool tts_ending;
    bool asset_active;
    bool microphone_enabled;
    bool vad_open;
    bool wake_latched;
    bool microphone_reset_pending;
    bool orphan_reported;
};

static const char *TAG = "ainekio_audio";
static ainekio_audio_service_t singleton;

static void pcm_to_bus(
    const uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES],
    int32_t bus[AUDIO_BUS_WORDS]
)
{
    for (size_t index = 0U; index < AINEKIO_AUDIO_PAYLOAD_BYTES / 2U; ++index) {
        const uint16_t raw = (uint16_t)payload[index * 2U] |
                             ((uint16_t)payload[index * 2U + 1U] << 8U);
        const int32_t sample = (int32_t)(int16_t)raw * INT32_C(65536);
        bus[index * 2U] = sample;
        bus[index * 2U + 1U] = sample;
    }
}

static void silence_bus(int32_t bus[AUDIO_BUS_WORDS])
{
    memset(bus, 0, AUDIO_BUS_WORDS * sizeof(bus[0]));
}

static bool write_bus(ainekio_audio_service_t *service)
{
    size_t written = 0U;
    return i2s_channel_write(
               service->tx_channel,
               service->bus_buffer,
               sizeof(service->bus_buffer),
               &written,
               25U
           ) == ESP_OK &&
           written == sizeof(service->bus_buffer);
}

static uint32_t mic_energy(const uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES])
{
    uint32_t sum = 0U;
    for (size_t index = 0U; index < AINEKIO_AUDIO_PAYLOAD_BYTES / 2U; ++index) {
        const uint16_t raw = (uint16_t)payload[index * 2U] |
                             ((uint16_t)payload[index * 2U + 1U] << 8U);
        const int32_t sample = (int16_t)raw;
        sum += (uint32_t)(sample < 0 ? -sample : sample);
    }
    return sum / (AINEKIO_AUDIO_PAYLOAD_BYTES / 2U);
}

static void read_microphone(ainekio_audio_service_t *service)
{
    size_t bytes = 0U;
    if (i2s_channel_read(
            service->rx_channel,
            service->bus_buffer,
            sizeof(service->bus_buffer),
            &bytes,
            0U
        ) != ESP_OK ||
        bytes != sizeof(service->bus_buffer)) {
        return;
    }
#ifdef CONFIG_AINEKIO_MIC_SLOT_RIGHT
    const size_t slot = 1U;
#else
    const size_t slot = 0U;
#endif
    for (size_t index = 0U; index < AINEKIO_AUDIO_PAYLOAD_BYTES / 2U; ++index) {
        const int16_t sample = (int16_t)(service->bus_buffer[index * 2U + slot] >> 16U);
        service->mic_samples[index] = sample;
        service->mic_payload[index * 2U] = (uint8_t)((uint16_t)sample & 0xFFU);
        service->mic_payload[index * 2U + 1U] =
            (uint8_t)(((uint16_t)sample >> 8U) & 0xFFU);
    }

    bool enabled = false;
    bool reset_pending = false;
    ainekio_microphone_gate_t gate = AINEKIO_MIC_GATE_VAD;
    taskENTER_CRITICAL(&service->state_lock);
    enabled = service->microphone_enabled;
    gate = service->microphone_gate;
    reset_pending = service->microphone_reset_pending;
    service->microphone_reset_pending = false;
    taskEXIT_CRITICAL(&service->state_lock);
    if (reset_pending) {
        if (service->vad_open && service->callbacks.gate != NULL) {
            service->callbacks.gate(service->callbacks.context, false, false);
        }
        service->vad_hangover = 0U;
        service->vad_open = false;
        service->wake_latched = false;
        ainekio_wake_word_reset(service->wake_word);
    }
    if (!enabled) {
        return;
    }
    const bool voice = mic_energy(service->mic_payload) >= VAD_THRESHOLD;
    bool wake_word = false;
    if (gate == AINEKIO_MIC_GATE_WAKE && !service->wake_latched) {
        const ainekio_wake_word_result_t wake_result = ainekio_wake_word_process(
            service->wake_word,
            service->mic_samples,
            AINEKIO_AUDIO_PAYLOAD_BYTES / 2U
        );
        if (wake_result == AINEKIO_WAKE_WORD_DETECTED) {
            service->wake_latched = true;
            service->vad_hangover = WAKE_SPEECH_HANGOVER_FRAMES;
            wake_word = true;
        } else if (wake_result == AINEKIO_WAKE_WORD_ERROR) {
            return;
        }
    } else if (gate != AINEKIO_MIC_GATE_OPEN) {
        if (voice) {
            service->vad_hangover = gate == AINEKIO_MIC_GATE_WAKE
                                        ? WAKE_SPEECH_HANGOVER_FRAMES
                                        : VAD_HANGOVER_FRAMES;
        } else if (service->vad_hangover > 0U) {
            --service->vad_hangover;
        }
    }
    const bool gate_open = gate == AINEKIO_MIC_GATE_OPEN ||
                           (gate == AINEKIO_MIC_GATE_VAD &&
                            (voice || service->vad_hangover > 0U)) ||
                           (gate == AINEKIO_MIC_GATE_WAKE &&
                            service->wake_latched &&
                            (wake_word || voice || service->vad_hangover > 0U));
    if (gate_open != service->vad_open) {
        service->vad_open = gate_open;
        if (service->callbacks.gate != NULL) {
            service->callbacks.gate(
                service->callbacks.context,
                gate_open,
                wake_word
            );
        }
    }
    if (gate_open && service->callbacks.microphone != NULL) {
        service->callbacks.microphone(
            service->callbacks.context,
            service->mic_payload
        );
    }
    if (gate == AINEKIO_MIC_GATE_WAKE && service->wake_latched && !gate_open) {
        service->wake_latched = false;
        ainekio_wake_word_reset(service->wake_word);
    }
}

static void finish_tts(ainekio_audio_service_t *service)
{
    uint32_t sequence = 0U;
    taskENTER_CRITICAL(&service->state_lock);
    sequence = service->tts_sequence;
    service->tts_sequence = 0U;
    service->tts_open = false;
    service->tts_ending = false;
    service->speaker_frames_queued = 0U;
    service->orphan_reported = false;
    taskEXIT_CRITICAL(&service->state_lock);
    if (sequence != 0U && service->callbacks.done != NULL) {
        service->callbacks.done(service->callbacks.context, sequence);
    }
}

static void play_asset(ainekio_audio_service_t *service)
{
    char path[sizeof(service->asset_path)];
    uint32_t expected_samples = 0U;
    uint32_t sequence = 0U;
    taskENTER_CRITICAL(&service->state_lock);
    (void)strcpy(path, service->asset_path);
    expected_samples = service->asset_samples;
    sequence = service->asset_sequence;
    taskEXIT_CRITICAL(&service->state_lock);
    FILE *file = fopen(path, "rb");
    bool failed = file == NULL;
    uint32_t played_samples = 0U;
    while (!failed && played_samples < expected_samples) {
        uint32_t notifications = 0U;
        (void)xTaskNotifyWait(0U, AUDIO_NOTIFY_CANCEL, &notifications, 0U);
        if ((notifications & AUDIO_NOTIFY_CANCEL) != 0U) {
            break;
        }
        uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES] = {0};
        const size_t remaining_bytes =
            (size_t)(expected_samples - played_samples) * 2U;
        const size_t wanted = remaining_bytes < sizeof(pcm) ? remaining_bytes
                                                            : sizeof(pcm);
        const size_t read = fread(pcm, 1U, wanted, file);
        if (read != wanted) {
            failed = true;
            break;
        }
        pcm_to_bus(pcm, service->bus_buffer);
        failed = !write_bus(service);
        read_microphone(service);
        played_samples += (uint32_t)(wanted / 2U);
    }
    if (file != NULL) {
        fclose(file);
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool still_active = service->asset_active &&
                              service->asset_sequence == sequence;
    if (still_active) {
        service->asset_active = false;
        service->asset_sequence = 0U;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (still_active && !failed && sequence != 0U &&
        service->callbacks.done != NULL) {
        service->callbacks.done(service->callbacks.context, sequence);
    } else if (still_active && failed && sequence != 0U &&
               service->callbacks.failed != NULL) {
        service->callbacks.failed(service->callbacks.context, sequence, false);
    }
}

static void audio_task(void *argument)
{
    ainekio_audio_service_t *service = argument;
    while (true) {
        uint32_t notifications = 0U;
        (void)xTaskNotifyWait(0U, AUDIO_NOTIFY_ASSET, &notifications, 0U);
        if ((notifications & AUDIO_NOTIFY_ASSET) != 0U) {
            play_asset(service);
            continue;
        }

        speaker_item_t item;
        const bool has_item =
            xQueueReceive(service->speaker_queue, &item, 0U) == pdTRUE;
        if (has_item && item.kind == SPEAKER_END) {
            finish_tts(service);
            silence_bus(service->bus_buffer);
        } else if (has_item) {
            taskENTER_CRITICAL(&service->state_lock);
            if (service->speaker_frames_queued > 0U) {
                --service->speaker_frames_queued;
            }
            taskEXIT_CRITICAL(&service->state_lock);
            pcm_to_bus(item.payload, service->bus_buffer);
        } else {
            bool tts_open = false;
            taskENTER_CRITICAL(&service->state_lock);
            tts_open = service->tts_open;
            taskEXIT_CRITICAL(&service->state_lock);
            if (tts_open) {
                ++service->speaker_underruns;
            }
            silence_bus(service->bus_buffer);
        }
        if (!write_bus(service)) {
            ESP_LOGW(TAG, "speaker DMA write failed");
        }
        read_microphone(service);
    }
}

static esp_err_t initialize_i2s(ainekio_audio_service_t *service)
{
    i2s_chan_config_t channel_config =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel_config.dma_desc_num = 8U;
    channel_config.dma_frame_num = 320U;
    esp_err_t result = i2s_new_channel(
        &channel_config,
        &service->tx_channel,
        &service->rx_channel
    );
    if (result != ESP_OK) {
        return result;
    }
    const i2s_std_config_t standard_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000U),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT,
            I2S_SLOT_MODE_STEREO
        ),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = AINEKIO_PIN_I2S_BCLK,
            .ws = AINEKIO_PIN_I2S_WS,
            .dout = AINEKIO_PIN_I2S_AMP_DOUT,
            .din = AINEKIO_PIN_I2S_MIC_DIN,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    result = i2s_channel_init_std_mode(service->tx_channel, &standard_config);
    if (result == ESP_OK) {
        result = i2s_channel_init_std_mode(service->rx_channel, &standard_config);
    }
    if (result == ESP_OK) {
        result = i2s_channel_enable(service->tx_channel);
    }
    if (result == ESP_OK) {
        result = i2s_channel_enable(service->rx_channel);
    }
    return result;
}

esp_err_t ainekio_audio_service_start(
    ainekio_asset_store_t *assets,
    const char *wake_model,
    const ainekio_audio_callbacks_t *callbacks,
    ainekio_audio_service_t **service_output
)
{
    if (assets == NULL || wake_model == NULL || service_output == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_audio_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));
    service->assets = assets;
    service->state_lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    service->microphone_gate = AINEKIO_MIC_GATE_VAD;
    if (callbacks != NULL) {
        service->callbacks = *callbacks;
    }
    const esp_err_t wake_result = ainekio_wake_word_service_start(
        assets,
        wake_model,
        &service->wake_word
    );
    if (wake_result != ESP_OK) {
        service->wake_word = NULL;
        ESP_LOGW(
            TAG,
            "wake model %s unavailable: %s",
            wake_model,
            esp_err_to_name(wake_result)
        );
    }
    service->speaker_queue = xQueueCreateStatic(
        SPEAKER_QUEUE_LENGTH,
        sizeof(speaker_item_t),
        service->speaker_queue_storage,
        &service->speaker_queue_control
    );
    if (service->speaker_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t result = initialize_i2s(service);
    if (result != ESP_OK) {
        return result;
    }
    if (xTaskCreatePinnedToCore(
            audio_task,
            "audio",
            6144U,
            service,
            AUDIO_TASK_PRIORITY,
            &service->task,
            1
        ) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    *service_output = service;
    return ESP_OK;
}

ainekio_audio_result_t ainekio_audio_tts_start(
    ainekio_audio_service_t *service,
    uint32_t sequence
)
{
    if (service == NULL || sequence == 0U) {
        return AINEKIO_AUDIO_IO_ERROR;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool busy = service->tts_open || service->asset_active;
    if (!busy) {
        service->tts_open = true;
        service->tts_ending = false;
        service->speaker_frames_queued = 0U;
        service->tts_sequence = sequence;
        service->orphan_reported = false;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    return busy ? AINEKIO_AUDIO_BUSY : AINEKIO_AUDIO_OK;
}

ainekio_audio_result_t ainekio_audio_tts_end(ainekio_audio_service_t *service)
{
    if (service == NULL) {
        return AINEKIO_AUDIO_IO_ERROR;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool open = service->tts_open && !service->tts_ending;
    if (open) {
        service->tts_ending = true;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (!open) {
        return AINEKIO_AUDIO_ORPHAN;
    }
    const speaker_item_t item = {.kind = SPEAKER_END};
    if (xQueueSend(service->speaker_queue, &item, 0U) == pdTRUE) {
        return AINEKIO_AUDIO_OK;
    }
    taskENTER_CRITICAL(&service->state_lock);
    service->tts_ending = false;
    taskEXIT_CRITICAL(&service->state_lock);
    return AINEKIO_AUDIO_OVERFLOW;
}

uint32_t ainekio_audio_cancel(ainekio_audio_service_t *service)
{
    if (service == NULL) {
        return 0U;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const uint32_t sequence = service->tts_open ? service->tts_sequence
                                                : service->asset_sequence;
    service->tts_open = false;
    service->tts_ending = false;
    service->speaker_frames_queued = 0U;
    service->tts_sequence = 0U;
    service->asset_active = false;
    service->asset_sequence = 0U;
    service->orphan_reported = false;
    taskEXIT_CRITICAL(&service->state_lock);
    (void)xQueueReset(service->speaker_queue);
    if (service->task != NULL) {
        (void)xTaskNotify(service->task, AUDIO_NOTIFY_CANCEL, eSetBits);
    }
    return sequence;
}

bool ainekio_audio_busy(const ainekio_audio_service_t *service)
{
    if (service == NULL) {
        return false;
    }
    ainekio_audio_service_t *mutable_service =
        (ainekio_audio_service_t *)service;
    taskENTER_CRITICAL(&mutable_service->state_lock);
    const bool busy = mutable_service->tts_open || mutable_service->asset_active;
    taskEXIT_CRITICAL(&mutable_service->state_lock);
    return busy;
}

ainekio_audio_result_t ainekio_audio_push_speaker(
    ainekio_audio_service_t *service,
    const uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES]
)
{
    if (service == NULL || payload == NULL) {
        return AINEKIO_AUDIO_IO_ERROR;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool open = service->tts_open && !service->tts_ending;
    const bool capacity = service->speaker_frames_queued < SPEAKER_PCM_LIMIT;
    const bool first_orphan = !service->orphan_reported;
    if (!open) {
        service->orphan_reported = true;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (!open) {
        return first_orphan ? AINEKIO_AUDIO_ORPHAN : AINEKIO_AUDIO_OK;
    }
    if (!capacity) {
        return AINEKIO_AUDIO_OVERFLOW;
    }
    speaker_item_t item = {.kind = SPEAKER_PCM};
    memcpy(item.payload, payload, sizeof(item.payload));
    if (xQueueSend(service->speaker_queue, &item, 0U) == pdTRUE) {
        taskENTER_CRITICAL(&service->state_lock);
        ++service->speaker_frames_queued;
        taskEXIT_CRITICAL(&service->state_lock);
        return AINEKIO_AUDIO_OK;
    }
    return AINEKIO_AUDIO_OVERFLOW;
}

static ainekio_audio_result_t play_named_asset(
    ainekio_audio_service_t *service,
    uint32_t sequence,
    const char *asset_name
)
{
    if (service == NULL || asset_name == NULL) {
        return AINEKIO_AUDIO_IO_ERROR;
    }
    const ainekio_audio_index_entry_t *asset =
        ainekio_asset_store_audio(service->assets, asset_name);
    if (asset == NULL) {
        return AINEKIO_AUDIO_ASSET_MISSING;
    }
    char path[sizeof(service->asset_path)];
    if (ainekio_asset_store_audio_path(asset, path, sizeof(path)) != ESP_OK) {
        return AINEKIO_AUDIO_ASSET_MISSING;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool busy = service->tts_open || service->asset_active;
    if (!busy) {
        service->asset_active = true;
        service->asset_sequence = sequence;
        service->asset_samples = asset->samples;
        (void)strcpy(service->asset_path, path);
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (busy) {
        return AINEKIO_AUDIO_BUSY;
    }
    (void)xTaskNotify(service->task, AUDIO_NOTIFY_ASSET, eSetBits);
    return AINEKIO_AUDIO_OK;
}

ainekio_audio_result_t ainekio_audio_say(
    ainekio_audio_service_t *service,
    uint32_t sequence,
    const char *asset_name
)
{
    if (sequence == 0U) {
        return AINEKIO_AUDIO_IO_ERROR;
    }
    return play_named_asset(service, sequence, asset_name);
}

ainekio_audio_result_t ainekio_audio_play_cue(
    ainekio_audio_service_t *service,
    const char *asset_name
)
{
    return play_named_asset(service, 0U, asset_name);
}

void ainekio_audio_set_microphone(
    ainekio_audio_service_t *service,
    bool enabled,
    ainekio_microphone_gate_t gate
)
{
    if (service == NULL || gate > AINEKIO_MIC_GATE_WAKE) {
        return;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool changed = service->microphone_enabled != enabled ||
                         service->microphone_gate != gate;
    service->microphone_enabled = enabled;
    service->microphone_gate = gate;
    if (changed) {
        service->microphone_reset_pending = true;
    }
    taskEXIT_CRITICAL(&service->state_lock);
}

bool ainekio_audio_wake_ready(const ainekio_audio_service_t *service)
{
    return service != NULL && ainekio_wake_word_ready(service->wake_word);
}

bool ainekio_audio_wake_model_available(
    const ainekio_audio_service_t *service,
    const char *model
)
{
    const char *installed = service == NULL
                                ? NULL
                                : ainekio_wake_word_model(service->wake_word);
    return installed != NULL && model != NULL && strcmp(installed, model) == 0;
}

uint32_t ainekio_audio_speaker_underruns(const ainekio_audio_service_t *service)
{
    return service == NULL ? 0U : service->speaker_underruns;
}

uint32_t ainekio_audio_microphone_drops(const ainekio_audio_service_t *service)
{
    return service == NULL ? 0U : service->microphone_drops;
}
