#include "storage.h"
#include "logs.h"
#include "network.h"
#include "system.h"
#include "video_avi.h"
#include "ainekio/sd_record.h"

#include <errno.h>
#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "driver/gpio.h"
#include "driver/sdmmc_host.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdmmc_cmd.h"
#include "sd_pwr_ctrl_by_on_chip_ldo.h"

#define MOUNT "/sdcard"
#define ROOT MOUNT "/ainekio"
#define LOG ROOT "/events.0.bin"
#define LOG_BYTES (1024U * 1024U)
#define LOG_COUNT 4U
#define CAPTURE_BYTES (1024U * 1024U)
#define CAPTURE_COUNT 32U
#define RECORD_BYTES 1024U

typedef enum { RETRY, CLEAR, RECORD, CAPTURE, SUSPEND, VIDEO_START, VIDEO_STOP, VIDEO_FRAME } operation_t;
typedef struct {
    operation_t operation;
    uint8_t type;
    size_t size;
    uint64_t timestamp;
    uint32_t serial;
    uint32_t suspend_generation;
    uint64_t deadline;
    uint8_t *capture;
    uint16_t width, height;
    uint8_t fps;
    uint8_t payload[RECORD_BYTES];
} request_t;

typedef struct { uint32_t serial; esp_err_t error; } completion_t;
static QueueHandle_t queue, completions;
static SemaphoreHandle_t enqueue_lock, drained, command_lock;
static uint32_t command_serial;
static uint32_t suspend_generation;
static bool suspended, capture_pending, suspend_queued, suspend_complete;
static esp_err_t suspend_result;
static portMUX_TYPE status_lock = portMUX_INITIALIZER_UNLOCKED;
static ainekio_p4_storage_status_t status = {.last_error=ESP_ERR_NOT_FOUND};
static sdmmc_card_t *card;
static sd_pwr_ctrl_handle_t power;
static FILE *log_file;
static SemaphoreHandle_t io_lock;
static FILE *download_file;
static char download_name[64];
static DIR *recording_directory;
static unsigned capture_index;
/* Includes the worker's in-flight JPEG: at most 3 * 256 KiB of PSRAM.
 * The camera's encoder buffer and transport copy retain their old ownership. */
static unsigned video_pending;
static bool video_accepting;
static ainekio_p4_video_status_t video_status;
static ainekio_avi_t video;
static uint64_t video_started, video_synced;
static char video_path[96];
static uint32_t video_session, video_sequence;
#define VIDEO_SEGMENT_BYTES (64U * 1024U * 1024U)
#define VIDEO_OLDEST_COUNT 32U
static uint64_t video_limit = VIDEO_SEGMENT_BYTES;
typedef struct { char name[64]; uint32_t sequence; } video_slot_t;
static video_slot_t video_oldest[VIDEO_OLDEST_COUNT];
static size_t video_oldest_count;
static bool recording_name(const char *name);
static void video_yield(void) { vTaskDelay(1); }

/* Refill only when the bounded oldest batch is exhausted, not per frame.
 * Filenames carry a card-wide sequence, recovered on mount without a clock or
 * a separate index file. Old firmware's equal sequences tie by filename. */
static bool video_scan(void)
{
    ainekio_p4_log_stage("storage: scan completed recording slots");
    DIR *directory = opendir(ROOT);
    if (!directory) return false;
    video_oldest_count = 0;
    unsigned visited = 0;
    bool ok = true;
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (!entry) { ok = errno == 0; break; }
        if (++visited % 32 == 0) video_yield();
        if (entry->d_type != DT_REG || !recording_name(entry->d_name)) continue;
        const unsigned long sequence = strtoul(entry->d_name + 15, NULL, 10);
        if (errno || sequence > UINT32_MAX) continue;
        if (sequence > video_sequence) video_sequence = sequence;
        if (strstr(entry->d_name, ".part")) continue;
        size_t at = 0;
        while (at < video_oldest_count &&
            (video_oldest[at].sequence < sequence ||
             (video_oldest[at].sequence == sequence && strcmp(video_oldest[at].name, entry->d_name) < 0))) ++at;
        if (at == VIDEO_OLDEST_COUNT) continue;
        if (video_oldest_count < VIDEO_OLDEST_COUNT) ++video_oldest_count;
        memmove(video_oldest + at + 1, video_oldest + at,
                (video_oldest_count - at - 1) * sizeof(video_oldest[0]));
        snprintf(video_oldest[at].name, sizeof(video_oldest[at].name), "%.63s", entry->d_name);
        video_oldest[at].sequence = sequence;
    }
    closedir(directory);
    ainekio_p4_log_stage("storage: slot scan complete");
    return ok;
}

static bool video_oldest_path(char *path, size_t capacity)
{
    for (unsigned pass = 0; pass < 2; ++pass) {
        for (size_t i = 0; i < video_oldest_count; ++i) {
            if (video_oldest[i].name[0] && strcmp(video_oldest[i].name, download_name)) {
                snprintf(path, capacity, ROOT "/%.63s", video_oldest[i].name);
                video_oldest[i].name[0] = 0;
                return true;
            }
        }
        if (!video_scan()) return false;
    }
    return false;
}

ainekio_p4_video_status_t ainekio_p4_video_status(void)
{
    taskENTER_CRITICAL(&status_lock);
    ainekio_p4_video_status_t copy = video_status;
    taskEXIT_CRITICAL(&status_lock);
    return copy;
}

static bool video_close(void)
{
    if (!video.file) return true;
    bool ok = !ferror(video.file) && ainekio_avi_checkpoint(&video);
    /* Discard only the unused tail of this overwritten clip, never another
     * file. Keeping stale JPEG bytes after RIFF would confuse some players. */
    if (ok) ok = ftruncate(fileno(video.file), video.bytes) == 0;
    ok = fsync(fileno(video.file)) == 0 && ok;
    ok = fclose(video.file) == 0 && ok;
    video.file = NULL;
    if (ok) {
        char final[sizeof(video_path)];
        snprintf(final, sizeof(final), "%s", video_path);
        final[strlen(final)-5] = 0; /* .part remains on any failed finalization. */
        ok = rename(video_path, final) == 0;
        if (ok) {
            taskENTER_CRITICAL(&status_lock);
            ++video_status.segments;
            snprintf(video_status.path, sizeof(video_status.path), "%s", final);
            taskEXIT_CRITICAL(&status_lock);
        }
    }
    return ok;
}

static void video_result(esp_err_t error, bool recording)
{
    xSemaphoreTake(enqueue_lock, portMAX_DELAY);
    video_accepting = recording;
    xSemaphoreGive(enqueue_lock);
    taskENTER_CRITICAL(&status_lock);
    video_status.recording = recording;
    /* Keep a storage failure visible after stop/unmount; explicit start clears it. */
    if (recording || error != ESP_OK) video_status.error = error;
    taskEXIT_CRITICAL(&status_lock);
}

static bool video_append(const request_t *r)
{
    const uint64_t chunk_bytes = 8U + r->size + (r->size & 1U);
    const uint64_t next_slot = video.file ? (r->timestamp - video_started) * video.fps / 1000U : 0;
    const uint64_t gap_bytes = next_slot > video.frames ? (next_slot - video.frames) * 8U : 0;
    if (video.file && (r->timestamp - video_started >= 60000 ||
        video.bytes + chunk_bytes + gap_bytes > video_limit ||
        video.width != r->width || video.height != r->height || video.fps != r->fps)) {
        if (!video_close()) return false;
    }
    if (!video.file) {
        uint64_t total_bytes = 0, free_bytes = 0;
        if (esp_vfs_fat_info(MOUNT, &total_bytes, &free_bytes) != ESP_OK) return false;
        /* Leave one maximum FAT directory cluster for a new long filename.
         * Existing clip data clusters are reused without truncating on open. */
        const uint64_t directory_bytes = 128U * (uint64_t)card->csd.sector_size;
        const uint64_t growth = free_bytes > directory_bytes ? free_bytes - directory_bytes : 0;
        const uint64_t first_bytes = 224U + chunk_bytes;
        char oldest[96] = {0};
        const bool reuse = free_bytes < VIDEO_SEGMENT_BYTES && video_oldest_path(oldest, sizeof(oldest));
        struct stat previous;
        if (reuse && (stat(oldest, &previous) != 0 || !S_ISREG(previous.st_mode))) return false;
        const uint64_t existing = reuse ? (uint64_t)previous.st_size : 0;
        video_limit = reuse ? existing : growth;
        if (video_limit < first_bytes && existing + growth >= first_bytes) video_limit = first_bytes;
        if (video_limit > VIDEO_SEGMENT_BYTES) video_limit = VIDEO_SEGMENT_BYTES;
        if (video_limit < first_bytes) return false;
        /* The reused clip gets the next sequence and remains visibly unfinished
         * until closed. No unlink, bulk cleanup, or formatting is involved. */
        snprintf(video_path, sizeof(video_path), ROOT "/video-%08lx-%08lu.avi.part",
                 (unsigned long)video_session, (unsigned long)++video_sequence);
        char final[sizeof(video_path)];
        snprintf(final, sizeof(final), "%s", video_path);
        final[strlen(final)-5] = 0;
        struct stat st;
        if (stat(final, &st) == 0 || errno != ENOENT) return false;
        if (stat(video_path, &st) == 0 || errno != ENOENT) return false;
        if (reuse && rename(oldest, video_path) != 0) return false;
        const int fd = open(video_path, reuse ? O_RDWR : O_CREAT | O_EXCL | O_RDWR, 0660);
        if (fd < 0) return false;
        FILE *file = fdopen(fd, "r+b");
        if (!file) { close(fd); return false; }
        if (!ainekio_avi_begin(&video, file, r->width, r->height, r->fps)) {
            fclose(file); video.file = NULL; return false;
        }
        /* Slot 0 and C6 slot 1 share IDF's transaction mutex. Yield between
         * 4 KiB writes; never submit an entire JPEG as one FATFS write. */
        video.yield = video_yield;
        video_started = video_synced = r->timestamp;
        if (reuse) { taskENTER_CRITICAL(&status_lock); ++video_status.overwritten; taskEXIT_CRITICAL(&status_lock); }
        taskENTER_CRITICAL(&status_lock);
        snprintf(video_status.path, sizeof(video_status.path), "%s", video_path);
        taskEXIT_CRITICAL(&status_lock);
    }
    /* Empty AVI chunks retain gaps caused by stills, SD backpressure and the
     * existing preview pacing. At most 900 time slots per 60-second segment. */
    const uint32_t slot = (r->timestamp - video_started) * video.fps / 1000U;
    while (video.frames < slot)
        if (!ainekio_avi_frame(&video, NULL, 0)) return false;
    if (!ainekio_avi_frame(&video, r->capture, r->size)) return false;
    if (r->timestamp - video_synced >= 1000) {
        if (!ainekio_avi_checkpoint(&video) || fsync(fileno(video.file)) != 0) return false;
        video_synced = r->timestamp;
    }
    taskENTER_CRITICAL(&status_lock); ++video_status.frames; taskEXIT_CRITICAL(&status_lock);
    return true;
}

static void set_error(esp_err_t error)
{
    taskENTER_CRITICAL(&status_lock);
    status.last_error = error;
    taskEXIT_CRITICAL(&status_lock);
}

ainekio_p4_storage_status_t ainekio_p4_storage_status(void)
{
    taskENTER_CRITICAL(&status_lock);
    ainekio_p4_storage_status_t copy = status;
    taskEXIT_CRITICAL(&status_lock);
    return copy;
}

static void refresh_space(void)
{
    uint64_t total = 0, free = 0;
    if (card) (void)esp_vfs_fat_info(MOUNT, &total, &free);
    taskENTER_CRITICAL(&status_lock);
    status.total_bytes = total;
    status.free_bytes = free;
    taskEXIT_CRITICAL(&status_lock);
}

static bool close_log(void)
{
    if (!log_file) return true;
    bool ok = fflush(log_file) == 0;
    ok = fsync(fileno(log_file)) == 0 && ok;
    ok = fclose(log_file) == 0 && ok;
    log_file = NULL;
    return ok;
}

static esp_err_t unmount(void)
{
    if (download_file) { fclose(download_file); download_file = NULL; }
    download_name[0] = 0;
    if (recording_directory) { closedir(recording_directory); recording_directory = NULL; }
    const bool video_ok = video_close();
    video_result(video_ok ? ESP_OK : ESP_FAIL, false);
    esp_err_t result = close_log() && video_ok ? ESP_OK : ESP_FAIL;
    if (card) {
        esp_err_t unmounted = esp_vfs_fat_sdcard_unmount(MOUNT, card);
        if (unmounted != ESP_OK) result = unmounted;
        else card = NULL;
    }
    if (!card && power) { (void)sd_pwr_ctrl_del_on_chip_ldo(power); power = NULL; }
    taskENTER_CRITICAL(&status_lock);
    status.mounted = card != NULL;
    taskEXIT_CRITICAL(&status_lock);
    return result;
}

/* The portable record CRC lets a torn final write be removed without losing
 * older records. Scan at most one bounded log segment, never arbitrary files. */
static bool open_log(void)
{
    log_file = fopen(LOG, "a+b");
    if (!log_file || fseek(log_file, 0, SEEK_SET) != 0) return false;
    long valid = 0;
    for (;;) {
        uint8_t encoded[AINEKIO_SD_RECORD_HEADER_BYTES], bytes[256];
        size_t n = fread(encoded, 1, sizeof(encoded), log_file);
        if (!n && feof(log_file)) break;
        ainekio_sd_record_header_t header;
        if (n != sizeof(encoded) || !ainekio_sd_record_decode_header(encoded, &header) ||
            header.payload_length > RECORD_BYTES ||
            (uint64_t)valid + sizeof(encoded) + header.payload_length > LOG_BYTES) break;
        uint32_t crc = ainekio_sd_crc32_update(ainekio_sd_crc32_begin(), encoded + 4, 16);
        size_t left = header.payload_length;
        bool good = true;
        while (left) {
            size_t count = left < sizeof(bytes) ? left : sizeof(bytes);
            if (fread(bytes, 1, count, log_file) != count) { good = false; break; }
            crc = ainekio_sd_crc32_update(crc, bytes, count);
            left -= count;
        }
        if (!good || ainekio_sd_crc32_finish(crc) != header.crc32) break;
        valid = ftell(log_file);
        if (valid < 0) return false;
    }
    if (ferror(log_file)) return false;
    clearerr(log_file);
    return ftruncate(fileno(log_file), valid) == 0 && fseek(log_file, 0, SEEK_END) == 0;
}

static esp_err_t mount(void)
{
    if (card) return ESP_OK;
    if (!ainekio_p4_network_initialized()) return ESP_ERR_INVALID_STATE;
    const sd_pwr_ctrl_ldo_config_t ldo = {.ldo_chan_id=4};
    esp_err_t result = sd_pwr_ctrl_new_on_chip_ldo(&ldo, &power);
    if (result != ESP_OK) return result;
    /* Board schematic: Q1 SI2301 P-channel gate on GPIO45; LOW enables TF VDD.
     * GPIO39..44 I/O supply is LDO4, managed by the SDMMC power controller. */
    gpio_set_level(45, 0);
    const gpio_config_t gate = {.pin_bit_mask=UINT64_C(1)<<45, .mode=GPIO_MODE_OUTPUT};
    result = gpio_config(&gate);
    if (result != ESP_OK) goto failed;
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.slot = 0;
    host.flags = SDMMC_HOST_FLAG_4BIT | SDMMC_HOST_FLAG_DEINIT_ARG;
    host.max_freq_khz = SDMMC_FREQ_DEFAULT;
    host.pwr_ctrl_handle = power;
    host.deinit_p = sdmmc_host_deinit_slot;
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width = 4; slot.clk = 43; slot.cmd = 44;
    slot.d0 = 39; slot.d1 = 40; slot.d2 = 41; slot.d3 = 42;
    slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
    const esp_vfs_fat_mount_config_t config = {.format_if_mount_failed=false, .max_files=4,
                                             .allocation_unit_size=16U*1024U};
    result = esp_vfs_fat_sdmmc_mount(MOUNT, &host, &slot, &config, &card);
    if (result != ESP_OK) goto failed;
    if ((mkdir(ROOT, 0770) != 0 && errno != EEXIST) || !open_log() || !video_scan()) { result = ESP_FAIL; goto failed; }
    taskENTER_CRITICAL(&status_lock);
    status.mounted = true;
    taskEXIT_CRITICAL(&status_lock);
    refresh_space();
    return ESP_OK;
failed:
    (void)unmount();
    return result;
}

static bool rotate(void)
{
    if (!close_log()) return false;
    for (unsigned i=LOG_COUNT-1; i>0; --i) {
        char source[64], destination[64];
        snprintf(source, sizeof(source), ROOT "/events.%u.bin", i-1);
        snprintf(destination, sizeof(destination), ROOT "/events.%u.bin", i);
        if (unlink(destination) != 0 && errno != ENOENT) return false;
        if (rename(source, destination) != 0 && errno != ENOENT) return false;
    }
    return open_log();
}

static bool append(const request_t *request)
{
    if (!log_file) return false;
    long current = ftell(log_file);
    if (current < 0 || ((uint64_t)current + AINEKIO_SD_RECORD_HEADER_BYTES + request->size > LOG_BYTES && !rotate()))
        return false;
    ainekio_sd_record_header_t header = {.type=request->type, .payload_length=request->size,
        .timestamp_ms=request->timestamp, .crc32=ainekio_sd_record_crc(request->type, request->size,
                                                                   request->timestamp, request->payload)};
    uint8_t encoded[AINEKIO_SD_RECORD_HEADER_BYTES];
    return ainekio_sd_record_encode_header(encoded, &header) &&
        fwrite(encoded, 1, sizeof(encoded), log_file) == sizeof(encoded) &&
        fwrite(request->payload, 1, request->size, log_file) == request->size &&
        fflush(log_file) == 0 && fsync(fileno(log_file)) == 0;
}

static bool capture(const request_t *request)
{
    char destination[64];
    snprintf(destination, sizeof(destination), ROOT "/capture.%02u.jpg", capture_index);
    FILE *file = fopen(ROOT "/capture.tmp", "wb");
    if (!file) return false;
    bool ok = fwrite(request->capture, 1, request->size, file) == request->size;
    ok = fflush(file) == 0 && ok;
    ok = fsync(fileno(file)) == 0 && ok;
    ok = fclose(file) == 0 && ok;
    if (ok && unlink(destination) != 0 && errno != ENOENT) ok = false;
    if (ok) ok = rename(ROOT "/capture.tmp", destination) == 0;
    if (!ok) (void)unlink(ROOT "/capture.tmp");
    else capture_index = (capture_index + 1) % CAPTURE_COUNT;
    return ok;
}

static bool clear(void)
{
    if (!close_log()) return false;
    char path[64];
    for (unsigned i=0; i<LOG_COUNT; ++i) {
        snprintf(path, sizeof(path), ROOT "/events.%u.bin", i);
        if (unlink(path) != 0 && errno != ENOENT) return false;
    }
    for (unsigned i=0; i<CAPTURE_COUNT; ++i) {
        snprintf(path, sizeof(path), ROOT "/capture.%02u.jpg", i);
        if (unlink(path) != 0 && errno != ENOENT) return false;
    }
    if (unlink(ROOT "/capture.tmp") != 0 && errno != ENOENT) return false;
    return open_log();
}

static void storage_task(void *argument)
{
    (void)argument;
    xSemaphoreTake(io_lock, portMAX_DELAY);
    esp_err_t result = mount();
    xSemaphoreGive(io_lock);
    set_error(result);
    if (result != ESP_OK) ESP_LOGW("storage", "Removable storage unavailable: %s", esp_err_to_name(result));
    request_t request;
    for (;;) {
        if (xQueueReceive(queue, &request, portMAX_DELAY) != pdTRUE) continue;
        xSemaphoreTake(io_lock, portMAX_DELAY);
        const int64_t write_started = esp_timer_get_time();
        taskENTER_CRITICAL(&status_lock); status.busy = true; taskEXIT_CRITICAL(&status_lock);
        const bool expired = request.serial && (uint64_t)esp_timer_get_time() >= request.deadline;
        if (expired) result = ESP_ERR_TIMEOUT;
        else if (request.operation == SUSPEND) {
            xSemaphoreTake(enqueue_lock, portMAX_DELAY);
            const bool current = suspended && request.suspend_generation == suspend_generation;
            xSemaphoreGive(enqueue_lock);
            result = current ? unmount() : ESP_OK;
        }
        else if (request.operation == RETRY) result = mount();
        else if (request.operation == VIDEO_STOP) {
            result = video_close() ? ESP_OK : ESP_FAIL;
            video_result(result, false);
        }
        else if (!card) result = ESP_ERR_INVALID_STATE;
        else if (request.operation == VIDEO_START) {
            result = ESP_OK;
            video_result(ESP_OK, true);
        }
        else if (request.operation == VIDEO_FRAME) result = video_append(&request) ? ESP_OK : ESP_FAIL;
        else if (request.operation == RECORD) result = append(&request) ? ESP_OK : ESP_FAIL;
        else if (request.operation == CAPTURE) result = capture(&request) ? ESP_OK : ESP_FAIL;
        else result = clear() ? ESP_OK : ESP_FAIL;
        if (request.capture) {
            free(request.capture);
            xSemaphoreTake(enqueue_lock, portMAX_DELAY);
            if (request.operation == VIDEO_FRAME) --video_pending;
            else capture_pending = false;
            xSemaphoreGive(enqueue_lock);
        }
        if (!expired && result != ESP_OK && card) (void)unmount();
        if (request.operation == VIDEO_FRAME) {
            const uint32_t elapsed = esp_timer_get_time() - write_started;
            taskENTER_CRITICAL(&status_lock);
            if (elapsed > video_status.max_write_us) video_status.max_write_us = elapsed;
            if (result != ESP_OK) video_status.error = result;
            taskEXIT_CRITICAL(&status_lock);
        }
        set_error(result);
        if (request.operation != VIDEO_FRAME || request.timestamp == video_synced) refresh_space();
        xSemaphoreGive(io_lock);
        taskENTER_CRITICAL(&status_lock); status.busy = false; taskEXIT_CRITICAL(&status_lock);
        if (request.serial) {
            const completion_t completion = {.serial=request.serial, .error=result};
            xQueueOverwrite(completions, &completion);
        }
        if (request.operation == SUSPEND) {
            xSemaphoreTake(enqueue_lock, portMAX_DELAY);
            const bool current = suspended && request.suspend_generation == suspend_generation;
            if (current) {
                suspend_result = result;
                suspend_complete = true;
                suspend_queued = false;
            }
            xSemaphoreGive(enqueue_lock);
            if (current) xSemaphoreGive(drained);
        }
    }
}

esp_err_t ainekio_p4_storage_start(void)
{
    if (queue) return ESP_ERR_INVALID_STATE;
    video_session = esp_random();
    enqueue_lock = xSemaphoreCreateMutex();
    drained = xSemaphoreCreateBinary();
    queue = xQueueCreate(4, sizeof(request_t));
    completions = xQueueCreate(1, sizeof(completion_t));
    command_lock = xSemaphoreCreateMutex();
    io_lock = xSemaphoreCreateMutex();
    if (!queue || !enqueue_lock || !drained || !completions || !command_lock || !io_lock ||
        xTaskCreate(storage_task, "storage", 6144, NULL, 2, NULL) != pdPASS) {
        if (queue) vQueueDelete(queue);
        if (enqueue_lock) vSemaphoreDelete(enqueue_lock);
        if (drained) vSemaphoreDelete(drained);
        if (completions) vQueueDelete(completions);
        if (command_lock) vSemaphoreDelete(command_lock);
        if (io_lock) vSemaphoreDelete(io_lock);
        io_lock = NULL;
        queue = NULL; enqueue_lock = NULL; drained = NULL; completions = NULL; command_lock = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

static esp_err_t enqueue(request_t *request)
{
    if (!queue || xSemaphoreTake(enqueue_lock, 0) != pdTRUE) return ESP_ERR_INVALID_STATE;
    esp_err_t result = ESP_ERR_INVALID_STATE;
    if (request->operation == RETRY && !ainekio_p4_system_status().restart_pending) {
        ++suspend_generation;
        suspended = false;
        suspend_queued = false;
        suspend_complete = false;
        (void)xSemaphoreTake(drained, 0);
    }
    if (!suspended) result = xQueueSend(queue, request, 0) == pdTRUE ? ESP_OK : ESP_ERR_TIMEOUT;
    if (result == ESP_OK && request->operation == VIDEO_STOP) video_accepting = false;
    xSemaphoreGive(enqueue_lock);
    return result;
}

static esp_err_t command(operation_t operation)
{
    if (!command_lock || xSemaphoreTake(command_lock, 0) != pdTRUE) return ESP_ERR_INVALID_STATE;
    completion_t completion;
    while (xQueueReceive(completions, &completion, 0) == pdTRUE) { }
    request_t request = {.operation=operation, .serial=++command_serial,
        .deadline=(uint64_t)esp_timer_get_time()+UINT64_C(4000000)};
    esp_err_t result = enqueue(&request);
    if (result == ESP_OK) {
        result = ESP_ERR_TIMEOUT;
        const TickType_t start = xTaskGetTickCount(), budget = pdMS_TO_TICKS(4000);
        TickType_t elapsed = 0;
        while (elapsed < budget && xQueueReceive(completions, &completion, budget-elapsed) == pdTRUE) {
            if (completion.serial == request.serial) { result=completion.error; break; }
            elapsed = xTaskGetTickCount() - start;
        }
    }
    xSemaphoreGive(command_lock);
    return result;
}

esp_err_t ainekio_p4_storage_retry(void)
{
    if (ainekio_p4_system_status().restart_pending) return ESP_ERR_INVALID_STATE;
    return command(RETRY);
}
esp_err_t ainekio_p4_storage_clear(void) { return command(CLEAR); }

esp_err_t ainekio_p4_video_start(void) { return command(VIDEO_START); }
esp_err_t ainekio_p4_video_stop(void) { return queue ? command(VIDEO_STOP) : ESP_OK; }

static bool recording_name(const char *name)
{
    /* Only this recorder's flat namespace; never interpret a request as a path. */
    if (!name || strlen(name) >= 64 || strncmp(name, "video-", 6)) return false;
    const char *p = name + 6;
    for (unsigned i=0; i<8; ++i) if (!isxdigit((unsigned char)*p++)) return false;
    if (*p++ != '-') return false;
    unsigned digits = 0;
    while (isdigit((unsigned char)*p)) { ++digits; ++p; }
    return digits >= 8 && digits <= 10 && (!strcmp(p, ".avi") || !strcmp(p, ".avi.part"));
}

static esp_err_t read_lock(void)
{
    if (!io_lock) return ESP_ERR_INVALID_STATE;
    return xSemaphoreTake(io_lock, pdMS_TO_TICKS(4000)) == pdTRUE ? ESP_OK : ESP_ERR_TIMEOUT;
}

esp_err_t ainekio_p4_recording_list_open(void)
{
    esp_err_t result = read_lock();
    if (result != ESP_OK) return result;
    if (recording_directory) closedir(recording_directory);
    recording_directory = card ? opendir(ROOT) : NULL;
    result = recording_directory ? ESP_OK : ESP_ERR_INVALID_STATE;
    xSemaphoreGive(io_lock);
    return result;
}

esp_err_t ainekio_p4_recording_list_next(ainekio_p4_recording_file_t *file, bool *done)
{
    esp_err_t result = read_lock();
    if (result != ESP_OK) return result;
    memset(file, 0, sizeof(*file));
    *done = false;
    if (!recording_directory) result = ESP_ERR_INVALID_STATE;
    else {
        errno = 0;
        struct dirent *entry = readdir(recording_directory);
        if (!entry) { *done = true; result = errno ? ESP_FAIL : ESP_OK; }
        else if (recording_name(entry->d_name)) {
            char path[96]; struct stat st;
            snprintf(path, sizeof(path), ROOT "/%.63s", entry->d_name);
            if (stat(path, &st) == 0 && S_ISREG(st.st_mode)) {
                snprintf(file->name, sizeof(file->name), "%.63s", entry->d_name);
                file->bytes = st.st_size;
                file->complete = !strstr(entry->d_name, ".part");
            }
        }
    }
    xSemaphoreGive(io_lock);
    return result;
}

esp_err_t ainekio_p4_recording_read_open(const char *name, uint64_t *bytes)
{
    if (!recording_name(name)) return ESP_ERR_INVALID_ARG;
    esp_err_t result = read_lock();
    if (result != ESP_OK) return result;
    if (download_file) { fclose(download_file); download_file = NULL; }
    download_name[0] = 0;
    char path[96]; struct stat st;
    snprintf(path, sizeof(path), ROOT "/%s", name);
    if (!card) result = ESP_ERR_INVALID_STATE;
    else if (stat(path, &st) || !S_ISREG(st.st_mode)) result = ESP_ERR_NOT_FOUND;
    else {
        download_file = fopen(path, "rb");
        result = download_file ? ESP_OK : ESP_FAIL;
        if (download_file) {
            *bytes = st.st_size;
            snprintf(download_name, sizeof(download_name), "%s", name);
            char *partial = strstr(download_name, ".part");
            if (partial) *partial = 0;
        }
    }
    xSemaphoreGive(io_lock);
    return result;
}

esp_err_t ainekio_p4_recording_read(void *buffer, size_t capacity, size_t *bytes)
{
    esp_err_t result = read_lock();
    if (result != ESP_OK) return result;
    *bytes = 0;
    if (!download_file) result = ESP_ERR_INVALID_STATE;
    else { *bytes = fread(buffer, 1, capacity, download_file); if (ferror(download_file)) result = ESP_FAIL; }
    xSemaphoreGive(io_lock);
    return result;
}

void ainekio_p4_recording_read_close(void)
{
    if (read_lock() != ESP_OK) return;
    if (download_file) { fclose(download_file); download_file = NULL; }
    download_name[0] = 0;
    if (recording_directory) { closedir(recording_directory); recording_directory = NULL; }
    xSemaphoreGive(io_lock);
}

void ainekio_p4_video_frame(const void *jpeg, size_t size, unsigned width, unsigned height, unsigned fps)
{
    if (!queue || !jpeg || size < 4 || size > 256U * 1024U || !fps || fps > 15) return;
    if (xSemaphoreTake(enqueue_lock, 0) != pdTRUE) {
        taskENTER_CRITICAL(&status_lock);
        if (video_status.recording) ++video_status.dropped;
        taskEXIT_CRITICAL(&status_lock);
        return;
    }
    if (video_accepting && !suspended) {
        request_t request = {.operation=VIDEO_FRAME, .size=size, .width=width, .height=height,
            .fps=fps, .timestamp=(uint64_t)esp_timer_get_time()/1000U};
        if (video_pending < 3) request.capture = heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (request.capture) memcpy(request.capture, jpeg, size);
        if (request.capture && xQueueSend(queue, &request, 0) == pdTRUE) ++video_pending;
        else {
            free(request.capture);
            taskENTER_CRITICAL(&status_lock); ++video_status.dropped; taskEXIT_CRITICAL(&status_lock);
        }
    }
    xSemaphoreGive(enqueue_lock);
}

esp_err_t ainekio_p4_storage_record(uint8_t type, const void *payload, size_t size)
{
    if ((!payload && size) || size > RECORD_BYTES) return ESP_ERR_INVALID_SIZE;
    if (!ainekio_p4_storage_status().mounted) return ESP_ERR_INVALID_STATE;
    request_t request = {.operation=RECORD, .type=type, .size=size,
                         .timestamp=(uint64_t)esp_timer_get_time()/1000U};
    if (size) memcpy(request.payload, payload, size);
    esp_err_t result = enqueue(&request);
    if (result != ESP_OK) {
        taskENTER_CRITICAL(&status_lock); ++status.dropped_records; taskEXIT_CRITICAL(&status_lock);
    }
    return result;
}

esp_err_t ainekio_p4_storage_capture(const void *jpeg, size_t size)
{
    if (!jpeg || size < 4 || size > CAPTURE_BYTES) return ESP_ERR_INVALID_SIZE;
    const uint8_t *bytes = jpeg;
    if (bytes[0] != 0xff || bytes[1] != 0xd8 || bytes[size-2] != 0xff || bytes[size-1] != 0xd9)
        return ESP_ERR_INVALID_ARG;
    if (!queue || !ainekio_p4_storage_status().mounted || xSemaphoreTake(enqueue_lock, 0) != pdTRUE)
        return ESP_ERR_INVALID_STATE;
    esp_err_t result = ESP_ERR_INVALID_STATE;
    if (!suspended && !capture_pending) {
        request_t request = {.operation=CAPTURE, .size=size};
        request.capture = heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!request.capture) result = ESP_ERR_NO_MEM;
        else {
            memcpy(request.capture, jpeg, size);
            if (xQueueSend(queue, &request, 0) == pdTRUE) { capture_pending = true; result = ESP_OK; }
            else { free(request.capture); result = ESP_ERR_TIMEOUT; }
        }
    }
    xSemaphoreGive(enqueue_lock);
    return result;
}

esp_err_t ainekio_p4_storage_suspend(uint32_t timeout_ms)
{
    if (!queue) return ESP_OK;
    TickType_t budget = pdMS_TO_TICKS(timeout_ms), start = xTaskGetTickCount();
    if (xSemaphoreTake(enqueue_lock, budget) != pdTRUE) return ESP_ERR_TIMEOUT;
    if (suspend_complete && suspend_result == ESP_OK) {
        xSemaphoreGive(enqueue_lock);
        return ESP_OK;
    }
    suspended = true;
    video_accepting = false;
    const bool send_request = !suspend_queued;
    if (send_request) {
        ++suspend_generation;
        suspend_queued = true;
        suspend_complete = false;
        (void)xSemaphoreTake(drained, 0);
    }
    const uint32_t generation = suspend_generation;
    xSemaphoreGive(enqueue_lock);
    request_t request = {.operation=SUSPEND, .suspend_generation=generation};
    TickType_t elapsed = xTaskGetTickCount() - start;
    if (send_request && (elapsed >= budget || xQueueSend(queue, &request, budget-elapsed) != pdTRUE)) {
        xSemaphoreTake(enqueue_lock, portMAX_DELAY);
        if (suspend_generation == generation) suspend_queued = false;
        xSemaphoreGive(enqueue_lock);
        return ESP_ERR_TIMEOUT;
    }
    elapsed = xTaskGetTickCount() - start;
    if (elapsed < budget) (void)xSemaphoreTake(drained, budget-elapsed);
    xSemaphoreTake(enqueue_lock, portMAX_DELAY);
    esp_err_t result = suspend_generation == generation && suspend_complete ? suspend_result : ESP_ERR_TIMEOUT;
    xSemaphoreGive(enqueue_lock);
    return result;
}

esp_err_t ainekio_p4_storage_resume(void)
{
    if (!queue) return ESP_OK;
    if (xSemaphoreTake(enqueue_lock, pdMS_TO_TICKS(100)) != pdTRUE) return ESP_ERR_TIMEOUT;
    /* A late worker result from the cancelled handoff cannot complete a later
     * sleep request. Worker I/O itself remains serialized through its queue. */
    ++suspend_generation;
    suspended = false;
    suspend_queued = false;
    suspend_complete = false;
    (void)xSemaphoreTake(drained, 0);
    xSemaphoreGive(enqueue_lock);
    return ESP_OK;
}
