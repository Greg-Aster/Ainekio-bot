#include "ainekio/platform/vad_service.h"

#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_vadn_iface.h"
#include "esp_vadn_models.h"
#include "model_path.h"

#define AINEKIO_VAD_SAMPLE_RATE_HZ 16000
#define AINEKIO_VAD_CHANNELS 1
#define AINEKIO_VAD_MIN_SPEECH_MS 128
#define AINEKIO_VAD_MIN_SILENCE_MS 1000
#define AINEKIO_VAD_MAX_CHUNK_SAMPLES 2048U

struct ainekio_vad_service {
    srmodel_list_t *models;
    const esp_vadn_iface_t *interface;
    model_iface_data_t *model;
    int16_t *buffer;
    size_t chunk_samples;
    size_t buffered_samples;
};

static const char *TAG = "ainekio_vad";
static ainekio_vad_service_t singleton;

static void release_service(ainekio_vad_service_t *service)
{
    if (service == NULL) {
        return;
    }
    if (service->model != NULL && service->interface != NULL) {
        service->interface->destroy(service->model);
    }
    service->model = NULL;
    service->interface = NULL;
    heap_caps_free(service->buffer);
    service->buffer = NULL;
    if (service->models != NULL) {
        esp_srmodel_deinit(service->models);
    }
    service->models = NULL;
    service->chunk_samples = 0U;
    service->buffered_samples = 0U;
}

esp_err_t ainekio_vad_service_start(ainekio_vad_service_t **service_output)
{
    if (service_output == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *service_output = NULL;
    ainekio_vad_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));

    const size_t internal_before = heap_caps_get_free_size(
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    );
    const size_t psram_before = heap_caps_get_free_size(
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
    );

    service->models = esp_srmodel_init("model");
    if (service->models == NULL) {
        ESP_LOGE(TAG, "model partition unavailable");
        return ESP_ERR_NOT_FOUND;
    }
    char *model_name = esp_srmodel_filter(
        service->models,
        ESP_VADN_PREFIX,
        NULL
    );
    if (model_name == NULL) {
        ESP_LOGE(TAG, "VADNet model unavailable in model partition");
        release_service(service);
        return ESP_ERR_NOT_FOUND;
    }
    service->interface = esp_vadn_handle_from_name(model_name);
    if (service->interface == NULL) {
        ESP_LOGE(TAG, "VADNet interface unavailable for %s", model_name);
        release_service(service);
        return ESP_ERR_NOT_SUPPORTED;
    }
    service->model = service->interface->create(
        model_name,
        VAD_MODE_1,
        AINEKIO_VAD_CHANNELS,
        AINEKIO_VAD_MIN_SPEECH_MS,
        AINEKIO_VAD_MIN_SILENCE_MS
    );
    if (service->model == NULL) {
        ESP_LOGE(TAG, "VADNet model creation failed for %s", model_name);
        release_service(service);
        return ESP_ERR_NO_MEM;
    }

    const int sample_rate = service->interface->get_samp_rate(service->model);
    const int channels = service->interface->get_channel_num(service->model);
    const int chunk_samples = service->interface->get_samp_chunksize(
        service->model
    );
    if (sample_rate != AINEKIO_VAD_SAMPLE_RATE_HZ ||
        channels != AINEKIO_VAD_CHANNELS || chunk_samples <= 0 ||
        (size_t)chunk_samples > AINEKIO_VAD_MAX_CHUNK_SAMPLES) {
        ESP_LOGE(
            TAG,
            "unsupported VADNet input rate=%d channels=%d chunk=%d",
            sample_rate,
            channels,
            chunk_samples
        );
        release_service(service);
        return ESP_ERR_NOT_SUPPORTED;
    }
    service->chunk_samples = (size_t)chunk_samples;
    service->buffer = heap_caps_calloc(
        service->chunk_samples,
        sizeof(service->buffer[0]),
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    );
    if (service->buffer == NULL) {
        release_service(service);
        return ESP_ERR_NO_MEM;
    }

    const size_t internal_after = heap_caps_get_free_size(
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    );
    const size_t psram_after = heap_caps_get_free_size(
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
    );
    ESP_LOGI(
        TAG,
        "ready model=%s rate=%d chunk=%u mode=%d speech_ms=%d silence_ms=%d "
        "internal_delta=%u psram_delta=%u",
        model_name,
        sample_rate,
        (unsigned int)service->chunk_samples,
        (int)VAD_MODE_1,
        AINEKIO_VAD_MIN_SPEECH_MS,
        AINEKIO_VAD_MIN_SILENCE_MS,
        (unsigned int)(internal_before > internal_after
                           ? internal_before - internal_after
                           : 0U),
        (unsigned int)(psram_before > psram_after
                           ? psram_before - psram_after
                           : 0U)
    );
    *service_output = service;
    return ESP_OK;
}

void ainekio_vad_service_stop(ainekio_vad_service_t *service)
{
    release_service(service);
}

bool ainekio_vad_ready(const ainekio_vad_service_t *service)
{
    return service != NULL && service->interface != NULL &&
           service->model != NULL && service->buffer != NULL &&
           service->chunk_samples > 0U;
}

void ainekio_vad_reset(ainekio_vad_service_t *service)
{
    if (!ainekio_vad_ready(service)) {
        return;
    }
    service->interface->clean(service->model);
    service->buffered_samples = 0U;
}

ainekio_vad_result_t ainekio_vad_process(
    ainekio_vad_service_t *service,
    const int16_t *samples,
    size_t sample_count
)
{
    if (!ainekio_vad_ready(service) || samples == NULL || sample_count == 0U) {
        return AINEKIO_VAD_ERROR;
    }

    ainekio_vad_result_t result = AINEKIO_VAD_PENDING;
    while (sample_count > 0U) {
        const size_t remaining = service->chunk_samples -
                                 service->buffered_samples;
        const size_t copied = sample_count < remaining ? sample_count : remaining;
        memcpy(
            &service->buffer[service->buffered_samples],
            samples,
            copied * sizeof(samples[0])
        );
        service->buffered_samples += copied;
        samples += copied;
        sample_count -= copied;

        if (service->buffered_samples == service->chunk_samples) {
            const vad_state_t state = service->interface->detect(
                service->model,
                service->buffer
            );
            service->buffered_samples = 0U;
            result = state == VAD_SPEECH ? AINEKIO_VAD_SPEECH
                                         : AINEKIO_VAD_SILENCE;
        }
    }
    return result;
}
