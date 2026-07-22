#include "ainekio/platform/wake_word_service.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <new>

#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "flatbuffers/verifier.h"
#include "frontend.h"
#include "frontend_util.h"
#include "mbedtls/sha256.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_resource_variable.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {

constexpr char kManifestSchema[] = "ainekio-microwakeword-v1";
constexpr char kEngine[] = "micro_wake_word";
constexpr size_t kFeatureCount = 40U;
constexpr size_t kProbabilityWindowMaximum = 32U;
constexpr size_t kWarmupFeatureCount = 100U;
constexpr size_t kManifestMaximumBytes = 4096U;
constexpr size_t kModelMinimumBytes = 1024U;
constexpr size_t kModelMaximumBytes = 512U * 1024U;
constexpr size_t kTensorArenaMinimumBytes = 8U * 1024U;
constexpr size_t kTensorArenaMaximumBytes = 256U * 1024U;
constexpr size_t kVariableArenaBytes = 2048U;

struct Manifest {
    char model_file[65]{};
    char sha256[65]{};
    uint8_t feature_step_ms{};
    uint8_t probability_cutoff{};
    uint8_t sliding_window_size{};
    size_t tensor_arena_size{};
};

const char *const TAG = "ainekio_wake";

bool safe_leaf_filename(const char *name)
{
    if (name == nullptr) {
        return false;
    }
    const size_t length = std::strlen(name);
    if (length < 8U || length > 64U || name[0] == '.') {
        return false;
    }
    for (size_t index = 0U; index < length; ++index) {
        const char value = name[index];
        const bool safe = (value >= 'a' && value <= 'z') ||
                          (value >= 'A' && value <= 'Z') ||
                          (value >= '0' && value <= '9') || value == '_' ||
                          value == '-' || value == '.';
        if (!safe) {
            return false;
        }
    }
    return length > 7U && std::strcmp(name + length - 7U, ".tflite") == 0;
}

bool safe_model_id(const char *model_id)
{
    if (model_id == nullptr) {
        return false;
    }
    const size_t length = std::strlen(model_id);
    if (length == 0U || length > AINEKIO_WAKE_MODEL_MAX) {
        return false;
    }
    for (size_t index = 0U; index < length; ++index) {
        const char value = model_id[index];
        if (!((value >= 'a' && value <= 'z') ||
              (value >= '0' && value <= '9') || value == '_')) {
            return false;
        }
    }
    return true;
}

bool bounded_string(const cJSON *object, const char *key, size_t maximum)
{
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(value) && value->valuestring != nullptr &&
           value->valuestring[0] != '\0' &&
           std::strlen(value->valuestring) <= maximum;
}

bool exact_string(const cJSON *object, const char *key, const char *expected)
{
    return bounded_string(object, key, 64U) &&
           std::strcmp(
               cJSON_GetObjectItemCaseSensitive(object, key)->valuestring,
               expected
           ) == 0;
}

bool bounded_string_array(const cJSON *array, size_t maximum)
{
    if (!cJSON_IsArray(array) || cJSON_GetArraySize(array) == 0) {
        return false;
    }
    const int count = cJSON_GetArraySize(array);
    for (int index = 0; index < count; ++index) {
        const cJSON *value = cJSON_GetArrayItem(array, index);
        if (!cJSON_IsString(value) || value->valuestring == nullptr ||
            value->valuestring[0] == '\0' ||
            std::strlen(value->valuestring) > maximum) {
            return false;
        }
    }
    return true;
}

bool unsigned_integer(
    const cJSON *object,
    const char *key,
    size_t minimum,
    size_t maximum,
    size_t *output
)
{
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(object, key);
    if (!cJSON_IsNumber(value) || value->valuedouble < 0.0 ||
        std::floor(value->valuedouble) != value->valuedouble ||
        value->valuedouble < static_cast<double>(minimum) ||
        value->valuedouble > static_cast<double>(maximum)) {
        return false;
    }
    *output = static_cast<size_t>(value->valuedouble);
    return true;
}

bool sha256_string(const char *value)
{
    if (value == nullptr || std::strlen(value) != 64U) {
        return false;
    }
    for (size_t index = 0U; index < 64U; ++index) {
        const char digit = value[index];
        if (!((digit >= '0' && digit <= '9') || (digit >= 'a' && digit <= 'f'))) {
            return false;
        }
    }
    return true;
}

void *aligned_memory(size_t bytes, uint32_t preferred_caps, uint32_t fallback_caps);

esp_err_t read_manifest(const char *path, const char *model_id, Manifest *manifest)
{
    FILE *file = std::fopen(path, "rb");
    if (file == nullptr) {
        return ESP_ERR_NOT_FOUND;
    }
    char *bytes = static_cast<char *>(aligned_memory(
        kManifestMaximumBytes + 1U,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT,
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    ));
    if (bytes == nullptr) {
        std::fclose(file);
        return ESP_ERR_NO_MEM;
    }
    const size_t count = std::fread(bytes, 1U, kManifestMaximumBytes + 1U, file);
    const bool io_error = std::ferror(file) != 0;
    std::fclose(file);
    if (io_error) {
        heap_caps_free(bytes);
        return ESP_FAIL;
    }
    if (count == 0U || count > kManifestMaximumBytes) {
        heap_caps_free(bytes);
        return ESP_ERR_INVALID_SIZE;
    }
    bytes[count] = '\0';
    cJSON *root = cJSON_ParseWithLength(bytes, count);
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        heap_caps_free(bytes);
        return ESP_ERR_INVALID_RESPONSE;
    }

    const cJSON *micro = cJSON_GetObjectItemCaseSensitive(root, "micro");
    const cJSON *languages = cJSON_GetObjectItemCaseSensitive(root, "trained_languages");
    const cJSON *model = cJSON_GetObjectItemCaseSensitive(root, "model");
    const cJSON *digest = cJSON_GetObjectItemCaseSensitive(root, "sha256");
    const cJSON *cutoff = cJSON_IsObject(micro)
                              ? cJSON_GetObjectItemCaseSensitive(
                                    micro,
                                    "probability_cutoff"
                                )
                              : nullptr;
    size_t feature_step = 0U;
    size_t sliding_window = 0U;
    size_t tensor_arena = 0U;
    const bool valid = exact_string(root, "schema", kManifestSchema) &&
                       exact_string(root, "engine", kEngine) &&
                       exact_string(root, "id", model_id) &&
                       bounded_string(root, "wake_word", 64U) &&
                       bounded_string(root, "author", 128U) &&
                       bounded_string(root, "license", 128U) &&
                       bounded_string(root, "training_revision", 128U) &&
                       bounded_string_array(languages, 16U) &&
                       cJSON_IsString(model) && safe_leaf_filename(model->valuestring) &&
                       cJSON_IsString(digest) && sha256_string(digest->valuestring) &&
                       cJSON_IsObject(micro) && cJSON_IsNumber(cutoff) &&
                       cutoff->valuedouble >= (1.0 / 255.0) &&
                       cutoff->valuedouble <= 1.0 &&
                       unsigned_integer(
                           micro,
                           "feature_step_size",
                           10U,
                           30U,
                           &feature_step
                       ) &&
                       (feature_step == 10U || feature_step == 20U ||
                        feature_step == 30U) &&
                       unsigned_integer(
                           micro,
                           "sliding_window_size",
                           1U,
                           kProbabilityWindowMaximum,
                           &sliding_window
                       ) &&
                       unsigned_integer(
                           micro,
                           "tensor_arena_size",
                           kTensorArenaMinimumBytes,
                           kTensorArenaMaximumBytes,
                           &tensor_arena
                       );
    if (valid) {
        std::strcpy(manifest->model_file, model->valuestring);
        std::strcpy(manifest->sha256, digest->valuestring);
        manifest->feature_step_ms = static_cast<uint8_t>(feature_step);
        manifest->probability_cutoff = static_cast<uint8_t>(
            std::lround(cutoff->valuedouble * 255.0)
        );
        manifest->sliding_window_size = static_cast<uint8_t>(sliding_window);
        manifest->tensor_arena_size = tensor_arena;
    }
    cJSON_Delete(root);
    heap_caps_free(bytes);
    return valid ? ESP_OK : ESP_ERR_INVALID_RESPONSE;
}

void digest_hex(const uint8_t digest[32], char output[65])
{
    static constexpr char hex[] = "0123456789abcdef";
    for (size_t index = 0U; index < 32U; ++index) {
        output[index * 2U] = hex[digest[index] >> 4U];
        output[index * 2U + 1U] = hex[digest[index] & 0x0FU];
    }
    output[64] = '\0';
}

void *aligned_memory(size_t bytes, uint32_t preferred_caps, uint32_t fallback_caps)
{
    void *memory = nullptr;
    if ((preferred_caps & MALLOC_CAP_SPIRAM) == 0U || esp_psram_is_initialized()) {
        memory = heap_caps_aligned_alloc(16U, bytes, preferred_caps);
    }
    return memory != nullptr
               ? memory
               : heap_caps_aligned_alloc(16U, bytes, fallback_caps);
}

}  // namespace

struct ainekio_wake_word_service {
    char model_id[AINEKIO_WAKE_MODEL_MAX + 1U]{};
    Manifest manifest{};
    uint8_t *model_bytes{};
    size_t model_size{};
    uint8_t *tensor_arena{};
    size_t tensor_arena_size{};
    uint8_t *variable_arena{};
    tflite::MicroAllocator *variable_allocator{};
    tflite::MicroResourceVariables *resource_variables{};
    const tflite::Model *model{};
    tflite::MicroMutableOpResolver<20> op_resolver{};
    tflite::MicroInterpreter *interpreter{};
    FrontendConfig frontend_config{};
    FrontendState frontend_state{};
    uint8_t recent_probabilities[kProbabilityWindowMaximum]{};
    size_t probability_index{};
    size_t feature_count{};
    uint8_t stride_index{};
    bool frontend_ready{};
    bool ready{};
};

namespace {

ainekio_wake_word_service singleton;

void release_service(ainekio_wake_word_service_t *service)
{
    service->ready = false;
    if (service->interpreter != nullptr) {
        delete service->interpreter;
        service->interpreter = nullptr;
    }
    if (service->frontend_ready) {
        FrontendFreeStateContents(&service->frontend_state);
        service->frontend_ready = false;
    }
    heap_caps_free(service->variable_arena);
    service->variable_arena = nullptr;
    service->variable_allocator = nullptr;
    service->resource_variables = nullptr;
    heap_caps_free(service->tensor_arena);
    service->tensor_arena = nullptr;
    heap_caps_free(service->model_bytes);
    service->model_bytes = nullptr;
    service->model_size = 0U;
}

bool register_operations(tflite::MicroMutableOpResolver<20> *resolver)
{
    return resolver->AddCallOnce() == kTfLiteOk &&
           resolver->AddVarHandle() == kTfLiteOk &&
           resolver->AddReshape() == kTfLiteOk &&
           resolver->AddReadVariable() == kTfLiteOk &&
           resolver->AddStridedSlice() == kTfLiteOk &&
           resolver->AddConcatenation() == kTfLiteOk &&
           resolver->AddAssignVariable() == kTfLiteOk &&
           resolver->AddConv2D() == kTfLiteOk && resolver->AddMul() == kTfLiteOk &&
           resolver->AddAdd() == kTfLiteOk && resolver->AddMean() == kTfLiteOk &&
           resolver->AddFullyConnected() == kTfLiteOk &&
           resolver->AddLogistic() == kTfLiteOk &&
           resolver->AddQuantize() == kTfLiteOk &&
           resolver->AddDepthwiseConv2D() == kTfLiteOk &&
           resolver->AddAveragePool2D() == kTfLiteOk &&
           resolver->AddMaxPool2D() == kTfLiteOk && resolver->AddPad() == kTfLiteOk &&
           resolver->AddPack() == kTfLiteOk && resolver->AddSplitV() == kTfLiteOk;
}

esp_err_t load_model_file(ainekio_wake_word_service_t *service, const char *path)
{
    FILE *file = std::fopen(path, "rb");
    if (file == nullptr) {
        return ESP_ERR_NOT_FOUND;
    }
    if (std::fseek(file, 0L, SEEK_END) != 0) {
        std::fclose(file);
        return ESP_FAIL;
    }
    const long length = std::ftell(file);
    if (length < static_cast<long>(kModelMinimumBytes) ||
        length > static_cast<long>(kModelMaximumBytes) ||
        std::fseek(file, 0L, SEEK_SET) != 0) {
        std::fclose(file);
        return ESP_ERR_INVALID_SIZE;
    }
    service->model_size = static_cast<size_t>(length);
    service->model_bytes = static_cast<uint8_t *>(aligned_memory(
        service->model_size,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT,
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    ));
    if (service->model_bytes == nullptr) {
        std::fclose(file);
        return ESP_ERR_NO_MEM;
    }
    const size_t count = std::fread(
        service->model_bytes,
        1U,
        service->model_size,
        file
    );
    const bool io_error = std::ferror(file) != 0;
    std::fclose(file);
    if (io_error || count != service->model_size) {
        return ESP_FAIL;
    }

    uint8_t digest[32]{};
    char actual_digest[65]{};
    if (mbedtls_sha256(service->model_bytes, service->model_size, digest, 0) != 0) {
        return ESP_FAIL;
    }
    digest_hex(digest, actual_digest);
    if (std::strcmp(actual_digest, service->manifest.sha256) != 0) {
        return ESP_ERR_INVALID_CRC;
    }
    flatbuffers::Verifier verifier(service->model_bytes, service->model_size);
    if (!tflite::VerifyModelBuffer(verifier)) {
        return ESP_ERR_INVALID_RESPONSE;
    }
    service->model = tflite::GetModel(service->model_bytes);
    return service->model->version() == TFLITE_SCHEMA_VERSION
               ? ESP_OK
               : ESP_ERR_NOT_SUPPORTED;
}

esp_err_t initialize_interpreter(ainekio_wake_word_service_t *service)
{
    if (!register_operations(&service->op_resolver)) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    service->variable_arena = static_cast<uint8_t *>(aligned_memory(
        kVariableArenaBytes,
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
    ));
    if (service->variable_arena == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    service->variable_allocator = tflite::MicroAllocator::Create(
        service->variable_arena,
        kVariableArenaBytes
    );
    if (service->variable_allocator == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    service->resource_variables = tflite::MicroResourceVariables::Create(
        service->variable_allocator,
        20
    );
    if (service->resource_variables == nullptr) {
        return ESP_ERR_NO_MEM;
    }

    service->tensor_arena_size = service->manifest.tensor_arena_size * 2U;
    service->tensor_arena = static_cast<uint8_t *>(aligned_memory(
        service->tensor_arena_size,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT,
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT
    ));
    if (service->tensor_arena == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    service->interpreter = new (std::nothrow) tflite::MicroInterpreter(
        service->model,
        service->op_resolver,
        service->tensor_arena,
        service->tensor_arena_size,
        service->resource_variables
    );
    if (service->interpreter == nullptr) {
        return ESP_ERR_NO_MEM;
    }
    if (service->interpreter->AllocateTensors() != kTfLiteOk) {
        return ESP_ERR_NO_MEM;
    }

    TfLiteTensor *input = service->interpreter->input(0U);
    TfLiteTensor *output = service->interpreter->output(0U);
    const bool input_valid = input != nullptr && input->type == kTfLiteInt8 &&
                             input->dims != nullptr && input->dims->size == 3 &&
                             input->dims->data[0] == 1 && input->dims->data[1] > 0 &&
                             input->dims->data[1] <= 32 &&
                             input->dims->data[2] == static_cast<int>(kFeatureCount) &&
                             input->params.scale > 0.0F;
    const bool output_valid = output != nullptr && output->type == kTfLiteUInt8 &&
                              output->dims != nullptr && output->dims->size == 2 &&
                              output->dims->data[0] == 1 && output->dims->data[1] == 1 &&
                              output->params.scale > 0.0F;
    return input_valid && output_valid ? ESP_OK : ESP_ERR_NOT_SUPPORTED;
}

esp_err_t initialize_frontend(ainekio_wake_word_service_t *service)
{
    FrontendFillConfigWithDefaults(&service->frontend_config);
    service->frontend_config.window.size_ms = 30U;
    service->frontend_config.window.step_size_ms = service->manifest.feature_step_ms;
    service->frontend_config.filterbank.num_channels = kFeatureCount;
    service->frontend_config.filterbank.lower_band_limit = 125.0F;
    service->frontend_config.filterbank.upper_band_limit = 7500.0F;
    service->frontend_config.noise_reduction.smoothing_bits = 10U;
    service->frontend_config.noise_reduction.even_smoothing = 0.025F;
    service->frontend_config.noise_reduction.odd_smoothing = 0.06F;
    service->frontend_config.noise_reduction.min_signal_remaining = 0.05F;
    service->frontend_config.pcan_gain_control.enable_pcan = 1;
    service->frontend_config.pcan_gain_control.strength = 0.95F;
    service->frontend_config.pcan_gain_control.offset = 80.0F;
    service->frontend_config.pcan_gain_control.gain_bits = 21U;
    service->frontend_config.log_scale.enable_log = 1;
    service->frontend_config.log_scale.scale_shift = 6U;
    if (!FrontendPopulateState(
            &service->frontend_config,
            &service->frontend_state,
            16000
        )) {
        return ESP_ERR_NO_MEM;
    }
    service->frontend_ready = true;
    return ESP_OK;
}

uint8_t quantized_probability(const TfLiteTensor *output)
{
    float probability =
        (static_cast<int32_t>(output->data.uint8[0]) - output->params.zero_point) *
        output->params.scale;
    probability = std::max(0.0F, std::min(1.0F, probability));
    return static_cast<uint8_t>(std::lround(probability * 255.0F));
}

bool probability_detected(const ainekio_wake_word_service_t *service)
{
    if (service->feature_count < kWarmupFeatureCount) {
        return false;
    }
    uint32_t sum = 0U;
    for (size_t index = 0U; index < service->manifest.sliding_window_size; ++index) {
        sum += service->recent_probabilities[index];
    }
    return sum > static_cast<uint32_t>(service->manifest.probability_cutoff) *
                     service->manifest.sliding_window_size;
}

ainekio_wake_word_result_t infer_feature(
    ainekio_wake_word_service_t *service,
    const FrontendOutput &features
)
{
    if (features.size != kFeatureCount) {
        return AINEKIO_WAKE_WORD_ERROR;
    }
    TfLiteTensor *input = service->interpreter->input(0U);
    const size_t stride = static_cast<size_t>(input->dims->data[1]);
    int8_t *destination = input->data.int8 + service->stride_index * kFeatureCount;
    for (size_t index = 0U; index < kFeatureCount; ++index) {
        const float real_feature = static_cast<float>(features.values[index]) / 25.6F;
        int32_t quantized = static_cast<int32_t>(
            std::lround(real_feature / input->params.scale)
        ) + input->params.zero_point;
        quantized = std::max<int32_t>(INT8_MIN, std::min<int32_t>(INT8_MAX, quantized));
        destination[index] = static_cast<int8_t>(quantized);
    }
    ++service->stride_index;
    ++service->feature_count;
    if (service->stride_index < stride) {
        return AINEKIO_WAKE_WORD_LISTENING;
    }
    service->stride_index = 0U;
    if (service->interpreter->Invoke() != kTfLiteOk) {
        service->ready = false;
        return AINEKIO_WAKE_WORD_ERROR;
    }
    TfLiteTensor *output = service->interpreter->output(0U);
    service->recent_probabilities[service->probability_index] =
        quantized_probability(output);
    service->probability_index =
        (service->probability_index + 1U) % service->manifest.sliding_window_size;
    return probability_detected(service) ? AINEKIO_WAKE_WORD_DETECTED
                                         : AINEKIO_WAKE_WORD_LISTENING;
}

}  // namespace

extern "C" esp_err_t ainekio_wake_word_service_start(
    const ainekio_asset_store_t *assets,
    const char *model_id,
    ainekio_wake_word_service_t **service_output
)
{
    if (assets == nullptr || model_id == nullptr || service_output == nullptr ||
        !assets->mounted || !safe_model_id(model_id)) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_wake_word_service_t *service = &singleton;
    if (service->model_bytes != nullptr || service->interpreter != nullptr) {
        return ESP_ERR_INVALID_STATE;
    }
    std::strcpy(service->model_id, model_id);

    char manifest_path[128]{};
    if (std::snprintf(
            manifest_path,
            sizeof(manifest_path),
            "%s/wake/%s/manifest.json",
            AINEKIO_ASSET_MOUNT_PATH,
            model_id
        ) >= static_cast<int>(sizeof(manifest_path))) {
        return ESP_ERR_INVALID_SIZE;
    }
    esp_err_t result = read_manifest(manifest_path, model_id, &service->manifest);
    if (result != ESP_OK) {
        return result;
    }

    char model_path[128]{};
    if (std::snprintf(
            model_path,
            sizeof(model_path),
            "%s/wake/%s/%s",
            AINEKIO_ASSET_MOUNT_PATH,
            model_id,
            service->manifest.model_file
        ) >= static_cast<int>(sizeof(model_path))) {
        return ESP_ERR_INVALID_SIZE;
    }
    result = load_model_file(service, model_path);
    if (result == ESP_OK) {
        result = initialize_interpreter(service);
    }
    if (result == ESP_OK) {
        result = initialize_frontend(service);
    }
    if (result != ESP_OK) {
        release_service(service);
        return result;
    }
    service->ready = true;
    *service_output = service;
    ESP_LOGI(
        TAG,
        "model=%s bytes=%u arena=%u cutoff=%u window=%u step_ms=%u ready=true",
        service->model_id,
        static_cast<unsigned int>(service->model_size),
        static_cast<unsigned int>(service->tensor_arena_size),
        static_cast<unsigned int>(service->manifest.probability_cutoff),
        static_cast<unsigned int>(service->manifest.sliding_window_size),
        static_cast<unsigned int>(service->manifest.feature_step_ms)
    );
    return ESP_OK;
}

extern "C" void ainekio_wake_word_service_stop(
    ainekio_wake_word_service_t *service
)
{
    if (service != nullptr) {
        release_service(service);
    }
}

extern "C" bool ainekio_wake_word_ready(
    const ainekio_wake_word_service_t *service
)
{
    return service != nullptr && service->ready;
}

extern "C" const char *ainekio_wake_word_model(
    const ainekio_wake_word_service_t *service
)
{
    return ainekio_wake_word_ready(service) ? service->model_id : nullptr;
}

extern "C" ainekio_wake_word_result_t ainekio_wake_word_process(
    ainekio_wake_word_service_t *service,
    const int16_t *samples,
    size_t sample_count
)
{
    if (!ainekio_wake_word_ready(service) || samples == nullptr || sample_count == 0U) {
        return AINEKIO_WAKE_WORD_ERROR;
    }
    size_t offset = 0U;
    while (offset < sample_count) {
        size_t processed = 0U;
        const FrontendOutput output = FrontendProcessSamples(
            &service->frontend_state,
            samples + offset,
            sample_count - offset,
            &processed
        );
        if (processed == 0U || processed > sample_count - offset) {
            service->ready = false;
            return AINEKIO_WAKE_WORD_ERROR;
        }
        offset += processed;
        if (output.size == 0U) {
            continue;
        }
        const ainekio_wake_word_result_t result = infer_feature(service, output);
        if (result != AINEKIO_WAKE_WORD_LISTENING) {
            return result;
        }
    }
    return AINEKIO_WAKE_WORD_LISTENING;
}

extern "C" void ainekio_wake_word_reset(ainekio_wake_word_service_t *service)
{
    if (!ainekio_wake_word_ready(service)) {
        return;
    }
    std::memset(
        service->recent_probabilities,
        0,
        sizeof(service->recent_probabilities)
    );
    service->probability_index = 0U;
    service->feature_count = 0U;
    service->stride_index = 0U;
    FrontendReset(&service->frontend_state);
    if (service->interpreter->Reset() != kTfLiteOk) {
        service->ready = false;
        ESP_LOGE(TAG, "model=%s reset failed", service->model_id);
    }
}
