#include "ainekio/platform/asset_store.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "cJSON.h"
#include "esp_littlefs.h"
#include "esp_log.h"

#define INDEX_JSON_MAX_BYTES 16384U

static const char *TAG = "ainekio_assets";
static const char *const joint_labels[AINEKIO_SERVO_COUNT] = {
    "R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4",
};

static bool integer_in_range(const cJSON *value, int minimum, int maximum)
{
    return cJSON_IsNumber(value) && value->valuedouble == (double)value->valueint &&
           value->valueint >= minimum && value->valueint <= maximum;
}

static bool copy_string(const cJSON *value, char *output, size_t output_size)
{
    if (!cJSON_IsString(value) || value->valuestring == NULL) {
        return false;
    }
    const size_t length = strlen(value->valuestring);
    if (length == 0U || length >= output_size) {
        return false;
    }
    memcpy(output, value->valuestring, length + 1U);
    return true;
}

static bool relative_path_valid(const char *path)
{
    return path != NULL && path[0] != '\0' && path[0] != '/' &&
           strstr(path, "..") == NULL && strchr(path, '\\') == NULL;
}

static bool make_path(const char *relative, char *output, size_t output_size)
{
    if (!relative_path_valid(relative)) {
        return false;
    }
    const int written = snprintf(
        output,
        output_size,
        "%s/%s",
        AINEKIO_ASSET_MOUNT_PATH,
        relative
    );
    return written > 0 && (size_t)written < output_size;
}

static bool file_size_is(const char *relative, uint32_t expected)
{
    char path[96];
    struct stat status;
    return make_path(relative, path, sizeof(path)) && stat(path, &status) == 0 &&
           status.st_size >= 0 && (uint32_t)status.st_size == expected;
}

static cJSON *read_json(const char *relative)
{
    char path[96];
    if (!make_path(relative, path, sizeof(path))) {
        return NULL;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL || fseek(file, 0L, SEEK_END) != 0) {
        if (file != NULL) {
            fclose(file);
        }
        return NULL;
    }
    const long length = ftell(file);
    if (length <= 0L || length > (long)INDEX_JSON_MAX_BYTES ||
        fseek(file, 0L, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    char *bytes = malloc((size_t)length + 1U);
    if (bytes == NULL) {
        fclose(file);
        return NULL;
    }
    const size_t read = fread(bytes, 1U, (size_t)length, file);
    fclose(file);
    if (read != (size_t)length) {
        free(bytes);
        return NULL;
    }
    bytes[length] = '\0';
    cJSON *document = cJSON_ParseWithLength(bytes, (size_t)length);
    free(bytes);
    return document;
}

static bool joint_map_valid(const cJSON *root)
{
    const cJSON *map = cJSON_GetObjectItemCaseSensitive(root, "joint_map");
    const cJSON *version = cJSON_GetObjectItemCaseSensitive(map, "version");
    const cJSON *joints = cJSON_GetObjectItemCaseSensitive(map, "joints");
    if (!cJSON_IsObject(map) || !integer_in_range(
            version,
            AINEKIO_JOINT_MAP_VERSION,
            AINEKIO_JOINT_MAP_VERSION
        ) ||
        !cJSON_IsArray(joints) || cJSON_GetArraySize(joints) != AINEKIO_SERVO_COUNT) {
        return false;
    }
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        const cJSON *joint = cJSON_GetArrayItem(joints, index);
        const cJSON *id = cJSON_GetObjectItemCaseSensitive(joint, "id");
        const cJSON *label = cJSON_GetObjectItemCaseSensitive(joint, "label");
        if (!cJSON_IsObject(joint) || !integer_in_range(id, index, index) ||
            !cJSON_IsString(label) || label->valuestring == NULL ||
            strcmp(label->valuestring, joint_labels[index]) != 0) {
            return false;
        }
    }
    return true;
}

static bool name_duplicate_motion(
    const ainekio_asset_store_t *store,
    const char *name
)
{
    for (uint8_t index = 0U; index < store->motion_count; ++index) {
        if (strcmp(store->motions[index].name, name) == 0) {
            return true;
        }
    }
    return false;
}

static esp_err_t read_motion_file(
    ainekio_asset_store_t *store,
    const ainekio_motion_index_entry_t *entry,
    ainekio_motion_asset_t *asset
)
{
    char path[96];
    if (entry->bytes == 0U || entry->bytes > sizeof(store->io_buffer) ||
        !make_path(entry->path, path, sizeof(path))) {
        return ESP_ERR_INVALID_SIZE;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return ESP_ERR_NOT_FOUND;
    }
    const size_t read = fread(store->io_buffer, 1U, entry->bytes, file);
    const int trailing = fgetc(file);
    fclose(file);
    if (read != entry->bytes || trailing != EOF) {
        return ESP_ERR_INVALID_SIZE;
    }
    const ainekio_asset_result_t decoded =
        ainekio_motion_asset_decode(store->io_buffer, entry->bytes, asset);
    if (decoded != AINEKIO_ASSET_OK || strcmp(asset->name, entry->name) != 0) {
        return ESP_ERR_INVALID_RESPONSE;
    }
    return ainekio_motion_asset_check_limits(asset, store->servos) == AINEKIO_ASSET_OK
               ? ESP_OK
               : ESP_ERR_INVALID_ARG;
}

static esp_err_t load_motion_index(ainekio_asset_store_t *store)
{
    cJSON *root = read_json("motions-bin-v1.json");
    const cJSON *schema = cJSON_GetObjectItemCaseSensitive(root, "schema_version");
    const cJSON *assets = cJSON_GetObjectItemCaseSensitive(root, "assets");
    if (!cJSON_IsObject(root) || !integer_in_range(schema, 1, 1) ||
        !joint_map_valid(root) || !cJSON_IsArray(assets) ||
        cJSON_GetArraySize(assets) < 1 ||
        cJSON_GetArraySize(assets) > AINEKIO_ASSET_MAX_MOTIONS) {
        cJSON_Delete(root);
        return ESP_ERR_INVALID_RESPONSE;
    }
    cJSON *item = NULL;
    cJSON_ArrayForEach(item, assets) {
        ainekio_motion_index_entry_t *entry = &store->motions[store->motion_count];
        const cJSON *name = cJSON_GetObjectItemCaseSensitive(item, "name");
        const cJSON *path = cJSON_GetObjectItemCaseSensitive(item, "path");
        const cJSON *bytes = cJSON_GetObjectItemCaseSensitive(item, "bytes");
        if (!cJSON_IsObject(item) || !copy_string(name, entry->name, sizeof(entry->name)) ||
            !ainekio_asset_name_valid(entry->name) ||
            name_duplicate_motion(store, entry->name) ||
            !copy_string(path, entry->path, sizeof(entry->path)) ||
            !relative_path_valid(entry->path) ||
            !integer_in_range(bytes, AINEKIO_MOTION_BINARY_HEADER_BYTES,
                              AINEKIO_MOTION_MAX_FILE_BYTES)) {
            cJSON_Delete(root);
            return ESP_ERR_INVALID_RESPONSE;
        }
        char expected_path[65];
        const int written = snprintf(
            expected_path,
            sizeof(expected_path),
            "motions/%s.amot",
            entry->name
        );
        if (written <= 0 || (size_t)written >= sizeof(expected_path) ||
            strcmp(entry->path, expected_path) != 0) {
            cJSON_Delete(root);
            return ESP_ERR_INVALID_RESPONSE;
        }
        entry->bytes = (uint32_t)bytes->valueint;
        ++store->motion_count;
    }
    cJSON_Delete(root);

    ainekio_motion_asset_t *scratch = malloc(sizeof(*scratch));
    if (scratch == NULL) {
        return ESP_ERR_NO_MEM;
    }
    for (uint8_t index = 0U; index < store->motion_count; ++index) {
        ainekio_motion_index_entry_t *entry = &store->motions[index];
        entry->available = file_size_is(entry->path, entry->bytes) &&
                           read_motion_file(store, entry, scratch) == ESP_OK;
        if (!entry->available) {
            ++store->unavailable_count;
            ESP_LOGW(TAG, "motion asset unavailable: %s", entry->name);
        }
    }
    free(scratch);
    return ESP_OK;
}

static bool name_duplicate_face(const ainekio_asset_store_t *store, const char *name)
{
    for (uint8_t index = 0U; index < store->face_count; ++index) {
        if (strcmp(store->faces[index].name, name) == 0) {
            return true;
        }
    }
    return false;
}

static bool parse_face_mode(const cJSON *value, ainekio_face_mode_t *mode)
{
    if (!cJSON_IsString(value) || value->valuestring == NULL) {
        return false;
    }
    if (strcmp(value->valuestring, "once") == 0) {
        *mode = AINEKIO_FACE_MODE_ONCE;
    } else if (strcmp(value->valuestring, "loop") == 0) {
        *mode = AINEKIO_FACE_MODE_LOOP;
    } else if (strcmp(value->valuestring, "boomerang") == 0) {
        *mode = AINEKIO_FACE_MODE_BOOMERANG;
    } else {
        return false;
    }
    return true;
}

static esp_err_t load_face_index(ainekio_asset_store_t *store)
{
    cJSON *root = read_json("faces-v1.json");
    const cJSON *schema = cJSON_GetObjectItemCaseSensitive(root, "schema_version");
    const cJSON *faces = cJSON_GetObjectItemCaseSensitive(root, "faces");
    if (!cJSON_IsObject(root) || !integer_in_range(schema, 1, 1) ||
        !cJSON_IsArray(faces) || cJSON_GetArraySize(faces) < 1 ||
        cJSON_GetArraySize(faces) > AINEKIO_ASSET_MAX_FACES) {
        cJSON_Delete(root);
        return ESP_ERR_INVALID_RESPONSE;
    }
    cJSON *item = NULL;
    cJSON_ArrayForEach(item, faces) {
        ainekio_face_index_entry_t *entry = &store->faces[store->face_count];
        const cJSON *name = cJSON_GetObjectItemCaseSensitive(item, "name");
        const cJSON *width = cJSON_GetObjectItemCaseSensitive(item, "width");
        const cJSON *height = cJSON_GetObjectItemCaseSensitive(item, "height");
        const cJSON *fps = cJSON_GetObjectItemCaseSensitive(item, "fps");
        const cJSON *mode = cJSON_GetObjectItemCaseSensitive(item, "mode");
        const cJSON *frames = cJSON_GetObjectItemCaseSensitive(item, "frames");
        const int frame_count = cJSON_IsArray(frames) ? cJSON_GetArraySize(frames) : 0;
        if (!cJSON_IsObject(item) || !copy_string(name, entry->name, sizeof(entry->name)) ||
            !ainekio_asset_name_valid(entry->name) || name_duplicate_face(store, entry->name) ||
            !integer_in_range(width, 128, 128) || !integer_in_range(height, 64, 64) ||
            !integer_in_range(fps, 1, 30) || frame_count < 1 ||
            frame_count > AINEKIO_ASSET_MAX_FACE_FRAMES ||
            !parse_face_mode(mode, &entry->mode)) {
            cJSON_Delete(root);
            return ESP_ERR_INVALID_RESPONSE;
        }
        entry->fps = (uint8_t)fps->valueint;
        entry->frame_count = (uint8_t)frame_count;
        entry->available = true;
        for (int frame_index = 0; frame_index < frame_count; ++frame_index) {
            const cJSON *frame = cJSON_GetArrayItem(frames, frame_index);
            if (!copy_string(
                    frame,
                    entry->frame_paths[frame_index],
                    sizeof(entry->frame_paths[frame_index])
                ) ||
                !relative_path_valid(entry->frame_paths[frame_index]) ||
                !file_size_is(entry->frame_paths[frame_index], AINEKIO_FACE_FRAME_BYTES)) {
                entry->available = false;
            }
        }
        if (!entry->available) {
            ++store->unavailable_count;
            ESP_LOGW(TAG, "face asset unavailable: %s", entry->name);
        }
        ++store->face_count;
    }
    cJSON_Delete(root);
    return ESP_OK;
}

static bool name_duplicate_audio(const ainekio_asset_store_t *store, const char *name)
{
    for (uint8_t index = 0U; index < store->audio_count; ++index) {
        if (strcmp(store->audio[index].name, name) == 0) {
            return true;
        }
    }
    return false;
}

static esp_err_t load_audio_index(ainekio_asset_store_t *store)
{
    cJSON *root = read_json("audio-v1.json");
    const cJSON *schema = cJSON_GetObjectItemCaseSensitive(root, "schema_version");
    const cJSON *rate = cJSON_GetObjectItemCaseSensitive(root, "sample_rate");
    const cJSON *format = cJSON_GetObjectItemCaseSensitive(root, "format");
    const cJSON *assets = cJSON_GetObjectItemCaseSensitive(root, "assets");
    if (!cJSON_IsObject(root) || !integer_in_range(schema, 1, 1) ||
        !integer_in_range(rate, 16000, 16000) || !cJSON_IsString(format) ||
        format->valuestring == NULL || strcmp(format->valuestring, "s16le-mono") != 0 ||
        !cJSON_IsArray(assets) || cJSON_GetArraySize(assets) > AINEKIO_ASSET_MAX_AUDIO) {
        cJSON_Delete(root);
        return ESP_ERR_INVALID_RESPONSE;
    }
    cJSON *item = NULL;
    cJSON_ArrayForEach(item, assets) {
        ainekio_audio_index_entry_t *entry = &store->audio[store->audio_count];
        const cJSON *name = cJSON_GetObjectItemCaseSensitive(item, "name");
        const cJSON *path = cJSON_GetObjectItemCaseSensitive(item, "path");
        const cJSON *samples = cJSON_GetObjectItemCaseSensitive(item, "samples");
        if (!cJSON_IsObject(item) || !copy_string(name, entry->name, sizeof(entry->name)) ||
            !ainekio_asset_name_valid(entry->name) || name_duplicate_audio(store, entry->name) ||
            !copy_string(path, entry->path, sizeof(entry->path)) ||
            !relative_path_valid(entry->path) || !integer_in_range(samples, 1, 16000 * 30)) {
            cJSON_Delete(root);
            return ESP_ERR_INVALID_RESPONSE;
        }
        entry->samples = (uint32_t)samples->valueint;
        entry->available = file_size_is(entry->path, entry->samples * 2U);
        if (!entry->available) {
            ++store->unavailable_count;
            ESP_LOGW(TAG, "audio asset unavailable: %s", entry->name);
        }
        ++store->audio_count;
    }
    cJSON_Delete(root);
    return ESP_OK;
}

esp_err_t ainekio_asset_store_init(
    ainekio_asset_store_t *store,
    ainekio_servo_bank_t *servos
)
{
    if (store == NULL || servos == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(store, 0, sizeof(*store));
    store->servos = servos;
    store->lock = xSemaphoreCreateMutexStatic(&store->lock_storage);
    const esp_vfs_littlefs_conf_t configuration = {
        .base_path = AINEKIO_ASSET_MOUNT_PATH,
        .partition_label = "littlefs",
        .format_if_mount_failed = false,
        .read_only = true,
        .dont_mount = false,
        .grow_on_mount = false,
    };
    esp_err_t result = esp_vfs_littlefs_register(&configuration);
    if (result != ESP_OK) {
        return result;
    }
    store->mounted = true;
    result = load_motion_index(store);
    if (result == ESP_OK) {
        result = load_face_index(store);
    }
    if (result == ESP_OK) {
        result = load_audio_index(store);
    }
    if (result != ESP_OK) {
        (void)esp_vfs_littlefs_unregister("littlefs");
        store->mounted = false;
        return result;
    }
    return ESP_OK;
}

esp_err_t ainekio_asset_store_load_motion(
    ainekio_asset_store_t *store,
    const char *name,
    ainekio_motion_asset_t *asset
)
{
    if (store == NULL || !store->mounted || !ainekio_asset_name_valid(name) ||
        asset == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const ainekio_motion_index_entry_t *entry = NULL;
    for (uint8_t index = 0U; index < store->motion_count; ++index) {
        if (strcmp(store->motions[index].name, name) == 0) {
            entry = &store->motions[index];
            break;
        }
    }
    if (entry == NULL || !entry->available) {
        return ESP_ERR_NOT_FOUND;
    }
    if (xSemaphoreTake(store->lock, pdMS_TO_TICKS(1000U)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    const esp_err_t result = read_motion_file(store, entry, asset);
    (void)xSemaphoreGive(store->lock);
    return result;
}

const ainekio_motion_index_entry_t *ainekio_asset_store_motion(
    const ainekio_asset_store_t *store,
    const char *name
)
{
    if (store == NULL || name == NULL) {
        return NULL;
    }
    for (uint8_t index = 0U; index < store->motion_count; ++index) {
        if (store->motions[index].available &&
            strcmp(store->motions[index].name, name) == 0) {
            return &store->motions[index];
        }
    }
    return NULL;
}

const ainekio_face_index_entry_t *ainekio_asset_store_face(
    const ainekio_asset_store_t *store,
    const char *name
)
{
    if (store == NULL || name == NULL) {
        return NULL;
    }
    for (uint8_t index = 0U; index < store->face_count; ++index) {
        if (store->faces[index].available && strcmp(store->faces[index].name, name) == 0) {
            return &store->faces[index];
        }
    }
    return NULL;
}

esp_err_t ainekio_asset_store_read_face_frame(
    ainekio_asset_store_t *store,
    const ainekio_face_index_entry_t *face,
    uint8_t frame_index,
    uint8_t output[AINEKIO_FACE_FRAME_BYTES]
)
{
    if (store == NULL || face == NULL || !face->available ||
        frame_index >= face->frame_count || output == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    char path[96];
    if (!make_path(face->frame_paths[frame_index], path, sizeof(path))) {
        return ESP_ERR_INVALID_ARG;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return ESP_ERR_NOT_FOUND;
    }
    const size_t read = fread(output, 1U, AINEKIO_FACE_FRAME_BYTES, file);
    const int trailing = fgetc(file);
    fclose(file);
    return read == AINEKIO_FACE_FRAME_BYTES && trailing == EOF ? ESP_OK
                                                               : ESP_ERR_INVALID_SIZE;
}

const ainekio_audio_index_entry_t *ainekio_asset_store_audio(
    const ainekio_asset_store_t *store,
    const char *name
)
{
    if (store == NULL || name == NULL) {
        return NULL;
    }
    for (uint8_t index = 0U; index < store->audio_count; ++index) {
        if (store->audio[index].available && strcmp(store->audio[index].name, name) == 0) {
            return &store->audio[index];
        }
    }
    return NULL;
}

esp_err_t ainekio_asset_store_audio_path(
    const ainekio_audio_index_entry_t *audio,
    char *output,
    size_t output_size
)
{
    return audio != NULL && audio->available && make_path(audio->path, output, output_size)
               ? ESP_OK
               : ESP_ERR_INVALID_ARG;
}
