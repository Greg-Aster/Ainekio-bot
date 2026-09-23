#include "media_internal.h"

#include <string.h>
#include <stdio.h>
#include <stdatomic.h>
#include "ainekio/p4_assets.h"
#include "ainekio/platform/wake_word_service.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_vad.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#define PCM_QUEUE_FRAMES 50U
#define AMP_PIN 53
#define FRAME_SAMPLES (AINEKIO_AUDIO_PAYLOAD_BYTES / sizeof(int16_t))

typedef struct {
    uint32_t generation;
    uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES];
} audio_frame_t;

static ainekio_p4_media_callbacks_t callbacks;
static i2c_master_bus_handle_t media_bus;
static i2s_chan_handle_t rx, tx;
static esp_codec_dev_handle_t codec;
static const audio_codec_data_if_t *codec_data;
static const audio_codec_ctrl_if_t *codec_control;
static const audio_codec_gpio_if_t *codec_gpio;
static const audio_codec_if_t *codec_device;
static SemaphoreHandle_t mutex;
static QueueHandle_t speaker_queue;
static ainekio_p4_media_status_t status;
static vad_handle_t vad;
static ainekio_wake_word_service_t *wake;
static SemaphoreHandle_t wake_mutex;
static FILE *asset_file;
static uint32_t asset_remaining;
static atomic_bool audio_tasks_started;
static bool suspended, microphone_enabled, ending, buffering, dma_dirty;
static ainekio_microphone_gate_t microphone_gate = AINEKIO_MIC_GATE_VAD;
static uint32_t sequence, generation;
static uint32_t microphone_epoch;
static uint64_t session, audio_session;
static int64_t last_speaker_input, microphone_after;
static esp_err_t configure_wake(bool enabled, const char *model, bool save);

static void load_wake(void)
{
    uint8_t saved[35] = {0};
    size_t size = sizeof(saved);
    nvs_handle_t handle;
    const char *model = AINEKIO_DEFAULT_WAKE_MODEL;
    bool enabled = false;
    esp_err_t result = nvs_open("p4_media", NVS_READONLY, &handle);
    if (result == ESP_OK) {
        result = nvs_get_blob(handle, "wake_v1", saved, &size);
        nvs_close(handle);
    }
    if (result == ESP_OK && size == sizeof(saved) && saved[0] == 1 && saved[1] <= 1 &&
        memchr(saved + 2, 0, sizeof(saved) - 2) && ainekio_asset_name_valid((char *)saved + 2)) {
        enabled = saved[1] != 0;
        model = (const char *)saved + 2;
    } else if (result != ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGW("p4_media", "invalid wake settings; wake disabled");
    }
    result = configure_wake(enabled, model, false);
    if (result != ESP_OK) ESP_LOGW("p4_media", "saved wake model unavailable: %s", esp_err_to_name(result));
}

static void audio_finish(esp_err_t result)
{
    uint32_t finished = sequence;
    uint64_t finished_session = audio_session;
    sequence = 0;
    status.speaker_busy = false;
    ending = false;
    buffering = false;
    if (asset_file) fclose(asset_file);
    asset_file = NULL;
    asset_remaining = 0;
    ++generation;
    gpio_set_level(AMP_PIN, 0);
    dma_dirty = true;
    microphone_after = esp_timer_get_time() + 800000;
    xQueueReset(speaker_queue);
    /* Caller releases the lock before delivering the callback. */
    xSemaphoreGive(mutex);
    if (finished && callbacks.audio_done)
        callbacks.audio_done(callbacks.context, finished_session, finished, result);
}

static void speaker_task(void *unused)
{
    (void)unused;
    while (!atomic_load(&audio_tasks_started)) vTaskDelay(1);
    audio_frame_t frame;
    for (;;) {
        xSemaphoreTake(mutex, portMAX_DELAY);
        if (!status.speaker_busy || suspended) {
            xSemaphoreGive(mutex);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (dma_dirty) {
            /* Disable and overwrite every DMA buffer before another generation
             * can unmute. Cancellation itself only mutes and invalidates work. */
            static const uint8_t silence[4 * AINEKIO_AUDIO_PAYLOAD_BYTES] = {0};
            size_t loaded = 0;
            esp_err_t reset_result = i2s_channel_disable(tx);
            if (reset_result == ESP_OK)
                reset_result = i2s_channel_preload_data(tx, silence, sizeof(silence), &loaded);
            if (reset_result == ESP_OK && loaded == sizeof(silence)) reset_result = i2s_channel_enable(tx);
            else if (reset_result == ESP_OK) reset_result = ESP_FAIL;
            if (reset_result != ESP_OK) {
                status.speaker_ready = false;
                audio_finish(reset_result);
                continue;
            }
            dma_dirty = false;
        }
        if (asset_file) {
            const size_t amount = asset_remaining < sizeof(frame.pcm) ? asset_remaining : sizeof(frame.pcm);
            memset(frame.pcm, 0, sizeof(frame.pcm));
            if (fread(frame.pcm, 1, amount, asset_file) != amount) {
                audio_finish(ESP_FAIL);
                continue;
            }
            asset_remaining -= amount;
            if (!asset_remaining) {
                fclose(asset_file);
                asset_file = NULL;
                ending = true;
            }
            gpio_set_level(AMP_PIN, 1);
            size_t written = 0;
            esp_err_t write_result = i2s_channel_write(tx, frame.pcm, sizeof(frame.pcm), &written, 60);
            if (write_result != ESP_OK || written != sizeof(frame.pcm)) {
                audio_finish(write_result == ESP_OK ? ESP_FAIL : write_result);
                continue;
            }
            xSemaphoreGive(mutex);
            continue;
        }
        const UBaseType_t queued = uxQueueMessagesWaiting(speaker_queue);
        if (buffering && (queued >= 4 || ending)) buffering = false;
        if (buffering || !queued) {
            if (ending && !queued) {
                /* Driver DMA retains at most four 20 ms buffers. */
                const uint32_t finishing_generation = generation;
                xSemaphoreGive(mutex);
                vTaskDelay(pdMS_TO_TICKS(80));
                xSemaphoreTake(mutex, portMAX_DELAY);
                if (status.speaker_busy && generation == finishing_generation)
                    audio_finish(ESP_OK);
                else xSemaphoreGive(mutex);
                continue;
            }
            if (esp_timer_get_time() - last_speaker_input > 1000000) {
                ++status.speaker_underruns;
                audio_finish(ESP_ERR_TIMEOUT);
                continue;
            }
            xSemaphoreGive(mutex);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (xQueueReceive(speaker_queue, &frame, 0) != pdTRUE ||
            frame.generation != generation) {
            xSemaphoreGive(mutex);
            continue;
        }
        gpio_set_level(AMP_PIN, 1);
        size_t written = 0;
        esp_err_t result = i2s_channel_write(tx, frame.pcm, sizeof(frame.pcm), &written, 60);
        if (result != ESP_OK || written != sizeof(frame.pcm)) {
            audio_finish(result == ESP_OK ? ESP_FAIL : result);
            continue;
        }
        xSemaphoreGive(mutex);
    }
}

static void microphone_task(void *unused)
{
    (void)unused;
    while (!atomic_load(&audio_tasks_started)) vTaskDelay(1);
    int16_t pcm[FRAME_SAMPLES];
    uint8_t pre_roll[5][AINEKIO_AUDIO_PAYLOAD_BYTES];
    size_t pre_count = 0, pre_next = 0;
    bool was_open = false;
    unsigned hangover = 0;
    uint64_t previous_session = 0;
    uint32_t previous_epoch = 0;
    bool wake_latched = false;
    int64_t wake_deadline = 0;
    for (;;) {
        xSemaphoreTake(mutex, portMAX_DELAY);
        const uint64_t capture_session = session;
        xSemaphoreGive(mutex);
        size_t received = 0;
        esp_err_t result = i2s_channel_read(rx, pcm, sizeof(pcm), &received, 40);
        if (result != ESP_OK || received != sizeof(pcm)) {
            xSemaphoreTake(mutex, portMAX_DELAY);
            ++status.microphone_drops;
            xSemaphoreGive(mutex);
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        xSemaphoreTake(mutex, portMAX_DELAY);
        const bool enabled = microphone_enabled && !suspended && !status.speaker_busy &&
                             esp_timer_get_time() >= microphone_after;
        const ainekio_microphone_gate_t gate = microphone_gate;
        const uint64_t frame_session = session;
        const bool wake_enabled = status.wake_enabled;
        const uint32_t current_epoch = microphone_epoch;
        xSemaphoreGive(mutex);
        if (!enabled || !frame_session || capture_session != frame_session ||
            previous_session != frame_session || previous_epoch != current_epoch) {
            const bool reset_gate = was_open || wake_latched || previous_session != frame_session ||
                                    previous_epoch != current_epoch;
            if (was_open && frame_session && previous_session == frame_session && callbacks.gate)
                callbacks.gate(callbacks.context, frame_session, false, false);
            pre_count = pre_next = 0;
            was_open = false;
            hangover = 0;
            wake_latched = false;
            previous_session = frame_session;
            previous_epoch = current_epoch;
            if (reset_gate) {
                xSemaphoreTake(wake_mutex, portMAX_DELAY);
                if (wake) ainekio_wake_word_reset(wake);
                xSemaphoreGive(wake_mutex);
            }
            continue;
        }
        bool open = gate == AINEKIO_MIC_GATE_OPEN;
        bool detected = false;
        if (gate == AINEKIO_MIC_GATE_WAKE && !wake_enabled) { wake_latched = false; hangover = 0; }
        if (gate == AINEKIO_MIC_GATE_WAKE && wake_enabled && !wake_latched) {
            xSemaphoreTake(wake_mutex, portMAX_DELAY);
            const ainekio_wake_word_result_t wake_result = wake
                ? ainekio_wake_word_process(wake, pcm, FRAME_SAMPLES) : AINEKIO_WAKE_WORD_ERROR;
            detected = wake_result == AINEKIO_WAKE_WORD_DETECTED;
            xSemaphoreGive(wake_mutex);
            if (wake_result == AINEKIO_WAKE_WORD_ERROR) {
                xSemaphoreTake(mutex, portMAX_DELAY);
                status.wake_ready = status.wake_enabled = false;
                xSemaphoreGive(mutex);
            }
            if (detected) {
                wake_latched = true;
                wake_deadline = esp_timer_get_time() + 15000000;
                hangover = 150;
            }
        }
        if ((gate == AINEKIO_MIC_GATE_VAD || (gate == AINEKIO_MIC_GATE_WAKE && wake_latched)) && vad) {
            if (vad_process(vad, pcm, 16000, 20) == VAD_SPEECH) hangover = 50;
            else if (hangover) --hangover;
            open = hangover > 0;
        }
        if (gate == AINEKIO_MIC_GATE_WAKE && wake_latched &&
            (!open || esp_timer_get_time() >= wake_deadline)) {
            wake_latched = false;
            open = false;
            xSemaphoreTake(wake_mutex, portMAX_DELAY);
            if (wake) ainekio_wake_word_reset(wake);
            xSemaphoreGive(wake_mutex);
        }
        if (open != was_open && callbacks.gate)
            callbacks.gate(callbacks.context, frame_session, open, detected);
        if (open && callbacks.microphone) {
            if (!was_open) {
                for (size_t i = 0; i < pre_count; ++i) {
                    const size_t index = (pre_next + 5 - pre_count + i) % 5;
                    callbacks.microphone(callbacks.context, frame_session, pre_roll[index]);
                }
                pre_count = 0;
            }
            callbacks.microphone(callbacks.context, frame_session, (const uint8_t *)pcm);
        } else {
            memcpy(pre_roll[pre_next], pcm, sizeof(pcm));
            pre_next = (pre_next + 1) % 5;
            if (pre_count < 5) ++pre_count;
        }
        was_open = open;
    }
}

static esp_err_t audio_start(void)
{
    const gpio_config_t amp = {.pin_bit_mask = UINT64_C(1) << AMP_PIN, .mode = GPIO_MODE_OUTPUT};
    gpio_set_level(AMP_PIN, 0);
    esp_err_t result = gpio_config(&amp);
    if (result != ESP_OK) return result;
    if (i2c_master_probe(media_bus, 0x18, 30) != ESP_OK) return ESP_ERR_NOT_FOUND;
    i2s_chan_config_t channels = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channels.dma_desc_num = 4;
    channels.dma_frame_num = FRAME_SAMPLES;
    channels.auto_clear = true;
    result = i2s_new_channel(&channels, &tx, &rx);
    if (result != ESP_OK) return result;
    i2s_std_config_t config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {.mclk = 13, .bclk = 12, .ws = 10, .dout = 9, .din = 11},
    };
    result = i2s_channel_init_std_mode(tx, &config);
    if (result == ESP_OK) result = i2s_channel_init_std_mode(rx, &config);
    if (result != ESP_OK) return result;
    audio_codec_i2s_cfg_t data_config = {.port = I2S_NUM_0, .rx_handle = rx, .tx_handle = tx};
    audio_codec_i2c_cfg_t control_config = {.port = I2C_NUM_0, .addr = ES8311_CODEC_DEFAULT_ADDR,
                                           .bus_handle = media_bus};
    codec_data = audio_codec_new_i2s_data(&data_config);
    codec_control = audio_codec_new_i2c_ctrl(&control_config);
    codec_gpio = audio_codec_new_gpio();
    if (!codec_data || !codec_control || !codec_gpio) return ESP_ERR_NO_MEM;
    es8311_codec_cfg_t chip = {.ctrl_if = codec_control, .gpio_if = codec_gpio,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_BOTH, .pa_pin = -1, .use_mclk = true,
        .hw_gain = {.pa_voltage = 5.0f, .codec_dac_voltage = 3.3f}};
    codec_device = es8311_codec_new(&chip);
    if (!codec_device) return ESP_FAIL;
    esp_codec_dev_cfg_t dev = {.dev_type = ESP_CODEC_DEV_TYPE_IN_OUT, .codec_if = codec_device, .data_if = codec_data};
    codec = esp_codec_dev_new(&dev);
    if (!codec) return ESP_ERR_NO_MEM;
    esp_codec_dev_sample_info_t sample = {.sample_rate = 16000, .channel = 1,
        .channel_mask = ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0), .bits_per_sample = 16};
    if (esp_codec_dev_open(codec, &sample) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    if (esp_codec_dev_set_out_vol(codec, 55) != ESP_CODEC_DEV_OK ||
        esp_codec_dev_set_in_gain(codec, 30.0f) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    vad = vad_create(VAD_MODE_3);
    status.vad_ready = vad != NULL;
    TaskHandle_t speaker_handle = NULL;
    if (xTaskCreate(speaker_task, "p4_speaker", 4096, NULL, 3, &speaker_handle) != pdPASS)
        return ESP_ERR_NO_MEM;
    if (xTaskCreate(microphone_task, "p4_mic", 6144, NULL, 3, NULL) != pdPASS) {
        vTaskDelete(speaker_handle);
        return ESP_ERR_NO_MEM;
    }
    status.microphone_ready = status.speaker_ready = true;
    atomic_store(&audio_tasks_started, true);
    return ESP_OK;
}

static void audio_cleanup(void)
{
    gpio_set_level(AMP_PIN, 0);
    if (codec) { esp_codec_dev_close(codec); esp_codec_dev_delete(codec); codec = NULL; }
    if (codec_device) { audio_codec_delete_codec_if(codec_device); codec_device = NULL; }
    if (codec_data) { audio_codec_delete_data_if(codec_data); codec_data = NULL; }
    if (codec_control) { audio_codec_delete_ctrl_if(codec_control); codec_control = NULL; }
    if (codec_gpio) { audio_codec_delete_gpio_if(codec_gpio); codec_gpio = NULL; }
    if (rx) { (void)i2s_channel_disable(rx); i2s_del_channel(rx); rx = NULL; }
    if (tx) { (void)i2s_channel_disable(tx); i2s_del_channel(tx); tx = NULL; }
    if (vad) { vad_destroy(vad); vad = NULL; }
    status.vad_ready = status.microphone_ready = status.speaker_ready = false;
}

esp_err_t ainekio_p4_media_start(const ainekio_p4_media_callbacks_t *configuration)
{
    if (!configuration) return ESP_ERR_INVALID_ARG;
    if (mutex) return ESP_ERR_INVALID_STATE;
    snprintf(status.wake_model, sizeof(status.wake_model), "%s", AINEKIO_DEFAULT_WAKE_MODEL);
    callbacks = *configuration;
    mutex = xSemaphoreCreateMutex();
    wake_mutex = xSemaphoreCreateMutex();
    speaker_queue = xQueueCreate(PCM_QUEUE_FRAMES, sizeof(audio_frame_t));
    if (!mutex || !wake_mutex || !speaker_queue) {
        if (mutex) vSemaphoreDelete(mutex);
        if (wake_mutex) vSemaphoreDelete(wake_mutex);
        if (speaker_queue) vQueueDelete(speaker_queue);
        mutex = wake_mutex = NULL;
        speaker_queue = NULL;
        return ESP_ERR_NO_MEM;
    }
    const i2c_master_bus_config_t bus = {.i2c_port = I2C_NUM_0, .sda_io_num = 7,
        .scl_io_num = 8, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true};
    esp_err_t result = i2c_new_master_bus(&bus, &media_bus);
    if (result != ESP_OK) {
        vSemaphoreDelete(mutex);
        vSemaphoreDelete(wake_mutex);
        vQueueDelete(speaker_queue);
        mutex = wake_mutex = NULL;
        speaker_queue = NULL;
        return result;
    }
    result = audio_start();
    if (result != ESP_OK) audio_cleanup();
    ESP_LOGI("p4_media", "ES8311 audio: %s", esp_err_to_name(result));
    load_wake();
    result = p4_camera_start(media_bus, &callbacks);
    ESP_LOGI("p4_media", "OV5647 camera task: %s", esp_err_to_name(result));
    return ESP_OK;
}

ainekio_p4_media_status_t ainekio_p4_media_status(void)
{
    ainekio_p4_media_status_t result = {.wake_model = AINEKIO_DEFAULT_WAKE_MODEL};
    if (!mutex) return result;
    xSemaphoreTake(mutex, portMAX_DELAY);
    result = status;
    xSemaphoreGive(mutex);
    result.camera_ready = p4_camera_ready();
    result.camera_failures = p4_camera_failures();
    return result;
}

esp_err_t ainekio_p4_media_microphone(bool enabled, ainekio_microphone_gate_t gate)
{
    if (!mutex) return ESP_ERR_INVALID_STATE;
    if (gate < AINEKIO_MIC_GATE_OPEN || gate > AINEKIO_MIC_GATE_WAKE) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(mutex, portMAX_DELAY);
    esp_err_t result = !status.microphone_ready || suspended || !session ? ESP_ERR_INVALID_STATE : ESP_OK;
    if (enabled && ((gate == AINEKIO_MIC_GATE_WAKE && (!status.wake_ready || !status.wake_enabled)) ||
                    (gate != AINEKIO_MIC_GATE_OPEN && !vad)))
        result = ESP_ERR_NOT_SUPPORTED;
    if (result == ESP_OK) {
        microphone_enabled = enabled;
        microphone_gate = gate;
        ++microphone_epoch;
    }
    xSemaphoreGive(mutex);
    return result;
}

esp_err_t ainekio_p4_media_tts_start(uint32_t id)
{
    if (!id) return ESP_ERR_INVALID_ARG;
    if (!mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(mutex, portMAX_DELAY);
    esp_err_t result = (!status.speaker_ready || suspended || status.speaker_busy || !session) ? ESP_ERR_INVALID_STATE : ESP_OK;
    if (result == ESP_OK) {
        xQueueReset(speaker_queue);
        sequence = id;
        audio_session = session;
        ++generation;
        status.speaker_busy = true;
        ending = false;
        buffering = true;
        last_speaker_input = esp_timer_get_time();
    }
    xSemaphoreGive(mutex);
    return result;
}

esp_err_t ainekio_p4_media_say(uint32_t id, const char *name)
{
    if (!name || !id) return ESP_ERR_INVALID_ARG;
    const ainekio_p4_audio_asset_t *asset = ainekio_p4_assets_audio(name);
    if (!asset) return ESP_ERR_NOT_FOUND;
    if (!mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(mutex, portMAX_DELAY);
    esp_err_t result = (!status.speaker_ready || suspended || status.speaker_busy || !session)
        ? ESP_ERR_INVALID_STATE : ESP_OK;
    if (result == ESP_OK) {
        asset_file = fopen(asset->path, "rb");
        if (!asset_file) result = ESP_FAIL;
        else {
            asset_remaining = asset->samples * sizeof(int16_t);
            sequence = id;
            audio_session = session;
            ++generation;
            status.speaker_busy = true;
            ending = buffering = false;
            last_speaker_input = esp_timer_get_time();
            xQueueReset(speaker_queue);
        }
    }
    xSemaphoreGive(mutex);
    return result;
}

static esp_err_t configure_wake(bool enabled, const char *model, bool save)
{
    if (!model || !ainekio_asset_name_valid(model) || strlen(model) > 32) return ESP_ERR_INVALID_ARG;
    if (!mutex || !wake_mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(wake_mutex, portMAX_DELAY);
    esp_err_t result = ESP_OK;
    if (!wake || !ainekio_wake_word_ready(wake) || strcmp(ainekio_wake_word_model(wake), model)) {
        if (wake) ainekio_wake_word_service_stop(wake);
        wake = NULL;
        if (!ainekio_p4_assets_status().mounted) result = ESP_ERR_NOT_FOUND;
        else result = ainekio_wake_word_service_start(AINEKIO_P4_ASSET_ROOT, model, &wake);
    }
    if (wake) ainekio_wake_word_reset(wake);
    if (result == ESP_OK && save) {
        uint8_t stored[35] = {1, enabled ? 1 : 0};
        memcpy(stored + 2, model, strlen(model) + 1);
        nvs_handle_t handle;
        result = nvs_open("p4_media", NVS_READWRITE, &handle);
        if (result == ESP_OK) {
            result = nvs_set_blob(handle, "wake_v1", stored, sizeof(stored));
            if (result == ESP_OK) result = nvs_commit(handle);
            nvs_close(handle);
        }
    }
    xSemaphoreTake(mutex, portMAX_DELAY);
    status.wake_ready = status.microphone_ready && status.vad_ready && wake && ainekio_wake_word_ready(wake);
    status.wake_enabled = enabled && status.wake_ready && result == ESP_OK;
    ++microphone_epoch;
    snprintf(status.wake_model, sizeof(status.wake_model), "%s", model);
    xSemaphoreGive(mutex);
    xSemaphoreGive(wake_mutex);
    return result;
}

esp_err_t ainekio_p4_media_wake_configure(bool enabled, const char *model)
{
    return configure_wake(enabled, model, true);
}

esp_err_t ainekio_p4_media_tts_push(const uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES])
{
    if (!pcm) return ESP_ERR_INVALID_ARG;
    if (!mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (!status.speaker_busy || ending || suspended || asset_file) {
        xSemaphoreGive(mutex);
        return ESP_ERR_INVALID_STATE;
    }
    audio_frame_t frame = {.generation = generation};
    memcpy(frame.pcm, pcm, sizeof(frame.pcm));
    if (xQueueSend(speaker_queue, &frame, 0) != pdTRUE) {
        audio_finish(ESP_ERR_NO_MEM);
        return ESP_ERR_NO_MEM;
    }
    last_speaker_input = esp_timer_get_time();
    xSemaphoreGive(mutex);
    return ESP_OK;
}

esp_err_t ainekio_p4_media_tts_end(void)
{
    if (!mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(mutex, portMAX_DELAY);
    const esp_err_t result = status.speaker_busy && !ending && !asset_file ? ESP_OK : ESP_ERR_INVALID_STATE;
    if (result == ESP_OK) ending = true;
    xSemaphoreGive(mutex);
    return result;
}

uint32_t ainekio_p4_media_audio_cancel(void)
{
    if (!mutex) return 0;
    gpio_set_level(AMP_PIN, 0);
    xSemaphoreTake(mutex, portMAX_DELAY);
    gpio_set_level(AMP_PIN, 0);
    dma_dirty = true;
    const uint32_t cancelled = sequence;
    sequence = 0;
    status.speaker_busy = false;
    ending = buffering = false;
    if (asset_file) fclose(asset_file);
    asset_file = NULL;
    asset_remaining = 0;
    ++generation;
    xQueueReset(speaker_queue);
    microphone_after = esp_timer_get_time() + 800000;
    xSemaphoreGive(mutex);
    return cancelled;
}

void ainekio_p4_media_disconnect(void)
{
    ainekio_p4_media_audio_cancel();
    if (mutex) {
        xSemaphoreTake(mutex, portMAX_DELAY);
        microphone_enabled = false;
        session = 0;
        xSemaphoreGive(mutex);
    }
    p4_camera_session(0);
}

void ainekio_p4_media_session(uint64_t next_session)
{
    ainekio_p4_media_disconnect();
    if (mutex) {
        xSemaphoreTake(mutex, portMAX_DELAY);
        session = next_session;
        xSemaphoreGive(mutex);
    }
    p4_camera_session(next_session);
}

esp_err_t ainekio_p4_media_suspend(bool paused)
{
    if (!mutex) return ESP_OK;
    if (paused) ainekio_p4_media_audio_cancel();
    xSemaphoreTake(mutex, portMAX_DELAY);
    suspended = paused;
    if (paused) microphone_enabled = false;
    xSemaphoreGive(mutex);
    return p4_camera_suspend(paused);
}
