#include "ainekio/p4_assets.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "cJSON.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "esp_partition.h"

#define MAX_AUDIO 16U
#define MAX_INDEX_BYTES 16384U

static ainekio_p4_audio_asset_t audio[MAX_AUDIO];
static ainekio_p4_assets_status_t status;
static bool initialized;

static bool number(const cJSON *value, unsigned minimum, unsigned maximum)
{
    return cJSON_IsNumber(value) && value->valuedouble >= minimum && value->valuedouble <= maximum &&
           value->valuedouble == value->valueint;
}

static bool named(const cJSON *value, char output[AINEKIO_ASSET_NAME_MAX+1])
{
    if (!cJSON_IsString(value) || !value->valuestring || !ainekio_asset_name_valid(value->valuestring)) return false;
    snprintf(output, AINEKIO_ASSET_NAME_MAX+1, "%s", value->valuestring);
    return true;
}

static bool exact_size(const char *path, uint32_t bytes)
{
    struct stat info;
    return stat(path, &info) == 0 && S_ISREG(info.st_mode) && info.st_size >= 0 && (uint64_t)info.st_size == bytes;
}

static cJSON *index_json(const char *path)
{
    FILE *file = fopen(path, "rb");
    if (!file) return NULL;
    if (fseek(file, 0, SEEK_END) != 0) { fclose(file); return NULL; }
    long size = ftell(file);
    if (size <= 0 || size > MAX_INDEX_BYTES || fseek(file, 0, SEEK_SET) != 0) { fclose(file); return NULL; }
    char *bytes = malloc(size+1);
    if (!bytes) { fclose(file); return NULL; }
    size_t received = fread(bytes, 1, size, file);
    int extra = fgetc(file);
    fclose(file);
    bytes[size] = 0;
    cJSON *root = received == (size_t)size && extra == EOF && !memchr(bytes, 0, size)
        ? cJSON_ParseWithLengthOpts(bytes, size+1, NULL, true) : NULL;
    free(bytes);
    return root;
}

static void load_audio(void)
{
    cJSON *root = index_json(AINEKIO_P4_ASSET_ROOT "/audio-v1.json");
    cJSON *items = cJSON_GetObjectItemCaseSensitive(root, "assets");
    const char *format = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(root, "format"));
    if (!number(cJSON_GetObjectItemCaseSensitive(root, "schema_version"), 1, 1) ||
        !number(cJSON_GetObjectItemCaseSensitive(root, "sample_rate"), 16000, 16000) ||
        !format || strcmp(format, "s16le-mono") || !cJSON_IsArray(items) || cJSON_GetArraySize(items) > MAX_AUDIO) {
        ++status.unavailable; cJSON_Delete(root); return;
    }
    cJSON *item;
    cJSON_ArrayForEach(item, items) {
        ainekio_p4_audio_asset_t entry = {0};
        cJSON *samples = cJSON_GetObjectItemCaseSensitive(item, "samples");
        const char *path = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(item, "path"));
        bool valid = named(cJSON_GetObjectItemCaseSensitive(item, "name"), entry.name) &&
            !ainekio_p4_assets_audio(entry.name) && number(samples, 1, 16000U*30U);
        if (valid) {
            char expected[64];
            snprintf(expected, sizeof(expected), "audio/%s.pcm", entry.name);
            snprintf(entry.path, sizeof(entry.path), AINEKIO_P4_ASSET_ROOT "/%s", expected);
            entry.samples = samples->valueint;
            valid = path && !strcmp(path, expected) && exact_size(entry.path, entry.samples*2U);
        }
        if (valid) audio[status.audio++] = entry;
        else ++status.unavailable;
    }
    cJSON_Delete(root);
}

esp_err_t ainekio_p4_assets_init(void)
{
    if (initialized) return ESP_ERR_INVALID_STATE;
    initialized = true;
    if (!esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "littlefs"))
        return ESP_ERR_NOT_FOUND;
    const esp_vfs_littlefs_conf_t config = {.base_path=AINEKIO_P4_ASSET_ROOT, .partition_label="littlefs",
                                          .format_if_mount_failed=false, .read_only=true, .dont_mount=false};
    esp_err_t result = esp_vfs_littlefs_register(&config);
    if (result != ESP_OK) return result;
    status.mounted = true;
    load_audio();
    ESP_LOGI("assets", "audio=%u unavailable=%u", status.audio, status.unavailable);
    return ESP_OK;
}

ainekio_p4_assets_status_t ainekio_p4_assets_status(void) { return status; }

const ainekio_p4_audio_asset_t *ainekio_p4_assets_audio(const char *name)
{
    if (!name) return NULL;
    for (unsigned i=0; i<status.audio; ++i) if (!strcmp(audio[i].name, name)) return &audio[i];
    return NULL;
}
