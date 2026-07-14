#include "ainekio/platform/sd_service.h"

#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "ainekio/platform/pin_map.h"
#include "driver/sdmmc_host.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdmmc_cmd.h"

#define SD_MOUNT_POINT "/sdcard"
#define SD_LOG_DIRECTORY SD_MOUNT_POINT "/logs"
#define SD_CAPTURE_DIRECTORY SD_MOUNT_POINT "/captures"
#define SD_ACTIVE_LOG SD_LOG_DIRECTORY "/events.0.bin"
#define SD_COMMAND_QUEUE_LENGTH 4U
#define SD_LOG_SEGMENT_BYTES (4U * 1024U * 1024U)
#define SD_LOG_SEGMENTS 4U
#define SD_SYNC_BYTES (32U * 1024U)
#define SD_SYNC_INTERVAL_US INT64_C(5000000)
#define SD_SWEEP_INTERVAL_US INT64_C(86400000000)
#define SD_CAPTURE_RETENTION_SECONDS (7 * 24 * 60 * 60)
#define SD_CAPTURE_RETENTION_BYTES (UINT64_C(200) * 1024U * 1024U)
#define SD_REFORMAT_CONFIRMATION_US INT64_C(60000000)
#define SD_TASK_PRIORITY 2U

_Static_assert(
    AINEKIO_SD_APPEND_MAX_BYTES <= AINEKIO_SD_RECORD_MAX_PAYLOAD,
    "SD command payload exceeds the portable record limit"
);

typedef enum {
    SD_COMMAND_RETRY = 0,
    SD_COMMAND_APPEND,
    SD_COMMAND_CLEAR,
    SD_COMMAND_REFORMAT,
} sd_command_kind_t;

typedef struct {
    sd_command_kind_t kind;
    uint8_t record_type;
    uint32_t payload_length;
    uint64_t timestamp_ms;
    uint8_t payload[AINEKIO_SD_APPEND_MAX_BYTES];
} sd_command_t;

struct ainekio_sd_service {
    ainekio_sd_callbacks_t callbacks;
    sdmmc_card_t *card;
    FILE *log_file;
    QueueHandle_t queue;
    StaticQueue_t queue_control;
    uint8_t queue_storage[SD_COMMAND_QUEUE_LENGTH * sizeof(sd_command_t)];
    TaskHandle_t task;
    portMUX_TYPE state_lock;
    size_t unsynced_bytes;
    int64_t last_sync_us;
    int64_t last_sweep_us;
    uint32_t reformat_confirmation;
    int64_t reformat_deadline_us;
    bool mounted;
};

static const char *TAG = "ainekio_sd";
static ainekio_sd_service_t singleton;

static void report_state(
    ainekio_sd_service_t *service,
    ainekio_sd_state_t state
)
{
    taskENTER_CRITICAL(&service->state_lock);
    service->mounted = state == AINEKIO_SD_MOUNTED;
    taskEXIT_CRITICAL(&service->state_lock);
    if (service->callbacks.state != NULL) {
        service->callbacks.state(service->callbacks.context, state);
    }
}

static bool make_directory(const char *path)
{
    return mkdir(path, 0770) == 0 || errno == EEXIST;
}

static void close_log(ainekio_sd_service_t *service)
{
    if (service->log_file != NULL) {
        (void)fflush(service->log_file);
        (void)fsync(fileno(service->log_file));
        (void)fclose(service->log_file);
        service->log_file = NULL;
    }
    service->unsynced_bytes = 0U;
}

static void unmount_card(ainekio_sd_service_t *service)
{
    close_log(service);
    if (service->card != NULL) {
        (void)esp_vfs_fat_sdcard_unmount(SD_MOUNT_POINT, service->card);
        service->card = NULL;
    }
}

static bool recover_log_tail(FILE *file, bool *tail_truncated)
{
    *tail_truncated = false;
    if (fseek(file, 0L, SEEK_SET) != 0) {
        return false;
    }
    long valid_end = 0L;
    uint8_t header_bytes[AINEKIO_SD_RECORD_HEADER_BYTES];
    uint8_t payload_buffer[256];
    while (true) {
        const size_t header_read = fread(
            header_bytes,
            1U,
            sizeof(header_bytes),
            file
        );
        if (header_read == 0U && feof(file)) {
            break;
        }
        ainekio_sd_record_header_t header;
        if (header_read != sizeof(header_bytes) ||
            !ainekio_sd_record_decode_header(header_bytes, &header)) {
            *tail_truncated = true;
            break;
        }
        uint32_t crc_state = ainekio_sd_crc32_begin();
        crc_state = ainekio_sd_crc32_update(
            crc_state,
            &header_bytes[4],
            16U
        );
        uint32_t remaining = header.payload_length;
        bool payload_complete = true;
        while (remaining > 0U) {
            const size_t chunk = remaining < sizeof(payload_buffer)
                                     ? remaining
                                     : sizeof(payload_buffer);
            if (fread(payload_buffer, 1U, chunk, file) != chunk) {
                *tail_truncated = true;
                remaining = 0U;
                payload_complete = false;
                break;
            }
            crc_state = ainekio_sd_crc32_update(crc_state, payload_buffer, chunk);
            remaining -= (uint32_t)chunk;
        }
        if (!payload_complete ||
            ainekio_sd_crc32_finish(crc_state) != header.crc32) {
            *tail_truncated = true;
            break;
        }
        valid_end = ftell(file);
        if (valid_end < 0L) {
            return false;
        }
    }
    clearerr(file);
    if (*tail_truncated && ftruncate(fileno(file), valid_end) != 0) {
        return false;
    }
    return fseek(file, 0L, SEEK_END) == 0;
}

static bool open_log(ainekio_sd_service_t *service)
{
    service->log_file = fopen(SD_ACTIVE_LOG, "a+b");
    if (service->log_file == NULL) {
        return false;
    }
    bool truncated = false;
    if (!recover_log_tail(service->log_file, &truncated)) {
        close_log(service);
        return false;
    }
    if (truncated) {
        ESP_LOGW(TAG, "torn log tail removed at mount");
    }
    service->last_sync_us = esp_timer_get_time();
    return true;
}

static bool initialize_filesystem(ainekio_sd_service_t *service)
{
    return make_directory(SD_LOG_DIRECTORY) &&
           make_directory(SD_CAPTURE_DIRECTORY) && open_log(service);
}

static esp_err_t mount_card(
    ainekio_sd_service_t *service,
    bool format_if_mount_failed
)
{
    if (ainekio_sd_available(service)) {
        return ESP_OK;
    }
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.flags = SDMMC_HOST_FLAG_1BIT | SDMMC_HOST_FLAG_DEINIT_ARG;
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width = 1U;
    slot.clk = AINEKIO_PIN_SD_CLK;
    slot.cmd = AINEKIO_PIN_SD_CMD;
    slot.d0 = AINEKIO_PIN_SD_DAT0;
    slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
    const esp_vfs_fat_mount_config_t mount = {
        .format_if_mount_failed = format_if_mount_failed,
        .max_files = 6,
        .allocation_unit_size = 16U * 1024U,
    };
    esp_err_t result = esp_vfs_fat_sdmmc_mount(
        SD_MOUNT_POINT,
        &host,
        &slot,
        &mount,
        &service->card
    );
    if (result != ESP_OK) {
        service->card = NULL;
        report_state(
            service,
            result == ESP_FAIL ? AINEKIO_SD_CORRUPT
                               : AINEKIO_SD_UNAVAILABLE
        );
        return result;
    }
    if (!initialize_filesystem(service)) {
        unmount_card(service);
        report_state(service, AINEKIO_SD_UNAVAILABLE);
        return ESP_FAIL;
    }
    service->last_sweep_us = esp_timer_get_time();
    report_state(service, AINEKIO_SD_MOUNTED);
    return ESP_OK;
}

static bool sync_log(ainekio_sd_service_t *service)
{
    if (service->log_file == NULL || service->unsynced_bytes == 0U) {
        return true;
    }
    if (fflush(service->log_file) != 0 ||
        fsync(fileno(service->log_file)) != 0) {
        return false;
    }
    service->unsynced_bytes = 0U;
    service->last_sync_us = esp_timer_get_time();
    return true;
}

static void fail_io(ainekio_sd_service_t *service)
{
    ESP_LOGE(TAG, "SD I/O failed; storage features disabled");
    unmount_card(service);
    report_state(service, AINEKIO_SD_UNAVAILABLE);
}

static bool rotate_log(ainekio_sd_service_t *service)
{
    if (!sync_log(service)) {
        return false;
    }
    close_log(service);
    char older[96];
    char newer[96];
    for (int index = (int)SD_LOG_SEGMENTS - 1; index > 0; --index) {
        (void)snprintf(
            older,
            sizeof(older),
            SD_LOG_DIRECTORY "/events.%d.bin",
            index
        );
        (void)snprintf(
            newer,
            sizeof(newer),
            SD_LOG_DIRECTORY "/events.%d.bin",
            index - 1
        );
        if (index == (int)SD_LOG_SEGMENTS - 1) {
            (void)unlink(older);
        }
        (void)rename(newer, older);
    }
    return open_log(service);
}

static bool append_record(
    ainekio_sd_service_t *service,
    const sd_command_t *command
)
{
    if (mount_card(service, false) != ESP_OK) {
        return false;
    }
    if (fseek(service->log_file, 0L, SEEK_END) != 0) {
        return false;
    }
    const long current_size = ftell(service->log_file);
    const size_t record_size =
        AINEKIO_SD_RECORD_HEADER_BYTES + command->payload_length;
    if (current_size < 0L ||
        ((uint64_t)current_size + record_size > SD_LOG_SEGMENT_BYTES &&
         !rotate_log(service))) {
        return false;
    }
    const ainekio_sd_record_header_t header = {
        .type = command->record_type,
        .payload_length = command->payload_length,
        .timestamp_ms = command->timestamp_ms,
        .crc32 = ainekio_sd_record_crc(
            command->record_type,
            command->payload_length,
            command->timestamp_ms,
            command->payload
        ),
    };
    uint8_t encoded[AINEKIO_SD_RECORD_HEADER_BYTES];
    if (!ainekio_sd_record_encode_header(encoded, &header) ||
        fwrite(encoded, 1U, sizeof(encoded), service->log_file) !=
            sizeof(encoded) ||
        (command->payload_length != 0U &&
         fwrite(
             command->payload,
             1U,
             command->payload_length,
             service->log_file
         ) != command->payload_length)) {
        return false;
    }
    service->unsynced_bytes += record_size;
    return service->unsynced_bytes < SD_SYNC_BYTES || sync_log(service);
}

static void clear_directory(const char *path)
{
    DIR *directory = opendir(path);
    if (directory == NULL) {
        return;
    }
    struct dirent *entry = NULL;
    char child[192];
    while ((entry = readdir(directory)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 ||
            strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        const int written = snprintf(
            child,
            sizeof(child),
            "%s/%s",
            path,
            entry->d_name
        );
        if (written > 0 && (size_t)written < sizeof(child)) {
            (void)unlink(child);
        }
    }
    (void)closedir(directory);
}

static bool clear_storage(ainekio_sd_service_t *service)
{
    if (mount_card(service, false) != ESP_OK) {
        return false;
    }
    close_log(service);
    clear_directory(SD_LOG_DIRECTORY);
    clear_directory(SD_CAPTURE_DIRECTORY);
    return open_log(service);
}

static uint64_t sweep_capture_age(const char *path, time_t now)
{
    DIR *directory = opendir(path);
    if (directory == NULL) {
        return 0U;
    }
    uint64_t total = 0U;
    struct dirent *entry = NULL;
    char child[192];
    while ((entry = readdir(directory)) != NULL) {
        if (entry->d_name[0] == '.') {
            continue;
        }
        const int written = snprintf(
            child,
            sizeof(child),
            "%s/%s",
            path,
            entry->d_name
        );
        struct stat info;
        if (written <= 0 || (size_t)written >= sizeof(child) ||
            stat(child, &info) != 0 || !S_ISREG(info.st_mode)) {
            continue;
        }
        const bool clock_valid = now >= (time_t)1577836800;
        if (clock_valid && info.st_mtime > 0 &&
            now - info.st_mtime > SD_CAPTURE_RETENTION_SECONDS) {
            (void)unlink(child);
        } else if (info.st_size > 0) {
            total += (uint64_t)info.st_size;
        }
    }
    (void)closedir(directory);
    return total;
}

static bool remove_oldest_capture(const char *path, uint64_t *removed_bytes)
{
    DIR *directory = opendir(path);
    if (directory == NULL) {
        return false;
    }
    time_t oldest_time = 0;
    off_t oldest_size = 0;
    char oldest_path[192] = {0};
    struct dirent *entry = NULL;
    char child[192];
    while ((entry = readdir(directory)) != NULL) {
        if (entry->d_name[0] == '.') {
            continue;
        }
        const int written = snprintf(
            child,
            sizeof(child),
            "%s/%s",
            path,
            entry->d_name
        );
        struct stat info;
        if (written <= 0 || (size_t)written >= sizeof(child) ||
            stat(child, &info) != 0 || !S_ISREG(info.st_mode)) {
            continue;
        }
        if (oldest_path[0] == '\0' || info.st_mtime < oldest_time) {
            (void)strcpy(oldest_path, child);
            oldest_time = info.st_mtime;
            oldest_size = info.st_size;
        }
    }
    (void)closedir(directory);
    if (oldest_path[0] == '\0' || unlink(oldest_path) != 0) {
        return false;
    }
    *removed_bytes = oldest_size > 0 ? (uint64_t)oldest_size : 0U;
    return true;
}

static void enforce_retention(ainekio_sd_service_t *service)
{
    if (!ainekio_sd_available(service)) {
        return;
    }
    const time_t now = time(NULL);
    uint64_t total = sweep_capture_age(SD_CAPTURE_DIRECTORY, now);
    while (total > SD_CAPTURE_RETENTION_BYTES) {
        uint64_t removed = 0U;
        if (!remove_oldest_capture(SD_CAPTURE_DIRECTORY, &removed)) {
            break;
        }
        total = removed >= total ? 0U : total - removed;
    }
    service->last_sweep_us = esp_timer_get_time();
}

static bool reformat_card(ainekio_sd_service_t *service)
{
    if (mount_card(service, true) != ESP_OK) {
        return false;
    }
    close_log(service);
    if (esp_vfs_fat_sdcard_format(SD_MOUNT_POINT, service->card) != ESP_OK ||
        !initialize_filesystem(service)) {
        return false;
    }
    enforce_retention(service);
    report_state(service, AINEKIO_SD_MOUNTED);
    return true;
}

static void service_tick(ainekio_sd_service_t *service)
{
    if (!ainekio_sd_available(service)) {
        return;
    }
    const int64_t now = esp_timer_get_time();
    if (service->unsynced_bytes != 0U &&
        now - service->last_sync_us >= SD_SYNC_INTERVAL_US &&
        !sync_log(service)) {
        fail_io(service);
        return;
    }
    if (now - service->last_sweep_us >= SD_SWEEP_INTERVAL_US) {
        enforce_retention(service);
    }
}

static void sd_task(void *argument)
{
    ainekio_sd_service_t *service = argument;
    (void)mount_card(service, false);
    enforce_retention(service);
    while (true) {
        sd_command_t command;
        if (xQueueReceive(service->queue, &command, pdMS_TO_TICKS(1000U)) ==
            pdTRUE) {
            bool ok = true;
            switch (command.kind) {
            case SD_COMMAND_RETRY:
                ok = mount_card(service, false) == ESP_OK;
                if (ok) {
                    enforce_retention(service);
                }
                break;
            case SD_COMMAND_APPEND:
                ok = append_record(service, &command);
                break;
            case SD_COMMAND_CLEAR:
                ok = clear_storage(service);
                break;
            case SD_COMMAND_REFORMAT:
                ok = reformat_card(service);
                break;
            default:
                ok = false;
                break;
            }
            if (!ok && ainekio_sd_available(service)) {
                fail_io(service);
            }
        }
        service_tick(service);
    }
}

static esp_err_t enqueue_command(
    ainekio_sd_service_t *service,
    const sd_command_t *command
)
{
    if (service == NULL || command == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    return xQueueSend(service->queue, command, 0U) == pdTRUE
               ? ESP_OK
               : ESP_ERR_TIMEOUT;
}

esp_err_t ainekio_sd_service_start(
    const ainekio_sd_callbacks_t *callbacks,
    ainekio_sd_service_t **service_output
)
{
    if (service_output == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_sd_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));
    service->state_lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    if (callbacks != NULL) {
        service->callbacks = *callbacks;
    }
    service->queue = xQueueCreateStatic(
        SD_COMMAND_QUEUE_LENGTH,
        sizeof(sd_command_t),
        service->queue_storage,
        &service->queue_control
    );
    if (service->queue == NULL ||
        xTaskCreatePinnedToCore(
            sd_task,
            "sd",
            6144U,
            service,
            SD_TASK_PRIORITY,
            &service->task,
            0
        ) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    *service_output = service;
    return ESP_OK;
}

bool ainekio_sd_available(const ainekio_sd_service_t *service)
{
    if (service == NULL) {
        return false;
    }
    ainekio_sd_service_t *mutable_service = (ainekio_sd_service_t *)service;
    taskENTER_CRITICAL(&mutable_service->state_lock);
    const bool mounted = mutable_service->mounted;
    taskEXIT_CRITICAL(&mutable_service->state_lock);
    return mounted;
}

esp_err_t ainekio_sd_request_retry(ainekio_sd_service_t *service)
{
    const sd_command_t command = {.kind = SD_COMMAND_RETRY};
    return enqueue_command(service, &command);
}

esp_err_t ainekio_sd_append(
    ainekio_sd_service_t *service,
    uint8_t record_type,
    uint64_t timestamp_ms,
    const void *payload,
    size_t payload_length
)
{
    if (payload_length > AINEKIO_SD_APPEND_MAX_BYTES ||
        (payload == NULL && payload_length != 0U)) {
        return ESP_ERR_INVALID_ARG;
    }
    sd_command_t command = {
        .kind = SD_COMMAND_APPEND,
        .record_type = record_type,
        .payload_length = (uint32_t)payload_length,
        .timestamp_ms = timestamp_ms,
    };
    if (payload_length != 0U) {
        memcpy(command.payload, payload, payload_length);
    }
    return enqueue_command(service, &command);
}

esp_err_t ainekio_sd_request_clear(ainekio_sd_service_t *service)
{
    const sd_command_t command = {.kind = SD_COMMAND_CLEAR};
    return enqueue_command(service, &command);
}

esp_err_t ainekio_sd_prepare_reformat(
    ainekio_sd_service_t *service,
    uint32_t *confirmation
)
{
    if (service == NULL || confirmation == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    uint32_t value = esp_random();
    if (value == 0U) {
        value = 1U;
    }
    const int64_t deadline_us =
        esp_timer_get_time() + SD_REFORMAT_CONFIRMATION_US;
    taskENTER_CRITICAL(&service->state_lock);
    service->reformat_confirmation = value;
    service->reformat_deadline_us = deadline_us;
    taskEXIT_CRITICAL(&service->state_lock);
    *confirmation = value;
    return ESP_OK;
}

esp_err_t ainekio_sd_confirm_reformat(
    ainekio_sd_service_t *service,
    uint32_t confirmation
)
{
    if (service == NULL || confirmation == 0U) {
        return ESP_ERR_INVALID_ARG;
    }
    const int64_t now = esp_timer_get_time();
    taskENTER_CRITICAL(&service->state_lock);
    const bool valid = confirmation == service->reformat_confirmation &&
                       now <= service->reformat_deadline_us;
    service->reformat_confirmation = 0U;
    service->reformat_deadline_us = 0;
    taskEXIT_CRITICAL(&service->state_lock);
    if (!valid) {
        return ESP_ERR_INVALID_STATE;
    }
    const sd_command_t command = {.kind = SD_COMMAND_REFORMAT};
    return enqueue_command(service, &command);
}
