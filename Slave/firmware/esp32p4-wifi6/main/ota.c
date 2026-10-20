#include "idle_rest.h"
#include "ota.h"
#include "logs.h"
#include "servo_feedback.h"
#include "board.h"
#include "body.h"
#include "config.h"
#include "display.h"
#include "storage.h"
#include "system.h"
#include "ainekio/p4_media.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include "esp_app_desc.h"
#include "esp_app_format.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "esp_hosted.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"

typedef enum { NONE, PREPARING, UPLOADING, VERIFYING, STAGED, NEXT_BOOT, RESTARTING, ACCEPTED, FAILED } phase_t;
static atomic_bool busy;
static portMUX_TYPE status_lock = portMUX_INITIALIZER_UNLOCKED;
static phase_t phase;
static uint32_t received, total;
static esp_err_t last_error;
static int64_t notice_until;
/* A staged image is intentionally not bootable until explicit activation.
 * Rebooting before activation discards this in-RAM selection. */
static const esp_partition_t *staged;
static uint32_t expected;
enum { EXPECT_CAMERA=1, EXPECT_MIC=2, EXPECT_SPEAKER=4, EXPECT_DISPLAY=8, EXPECT_OUTPUT=16 };

bool ainekio_p4_ota_busy(void) { return atomic_load(&busy); }

static void status(phase_t value, esp_err_t error)
{
    taskENTER_CRITICAL(&status_lock);
    phase = value; last_error = error;
    notice_until = esp_timer_get_time() + 15000000;
    taskEXIT_CRITICAL(&status_lock);
}

static esp_err_t response(httpd_req_t *r, const char *code, const char *text)
{
    httpd_resp_set_status(r, code);
    httpd_resp_set_type(r, "application/json");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    httpd_resp_set_hdr(r, "Connection", "close");
    esp_err_t result = httpd_resp_sendstr(r, text);
    /* Discard unread upload bytes on rejection; never parse them as a request. */
    httpd_sess_trigger_close(r->handle, httpd_req_to_sockfd(r));
    return result;
}

static bool authorized(httpd_req_t *r)
{
    const ainekio_config_record_t *config = ainekio_p4_config();
    char header[sizeof(config->robot_token) + 8];
    if (!config || !config->robot_token[0] ||
        httpd_req_get_hdr_value_str(r, "Authorization", header, sizeof(header)) != ESP_OK ||
        strncmp(header, "Bearer ", 7) != 0) return false;
    const size_t length = strlen(config->robot_token);
    unsigned diff = strlen(header+7) ^ length;
    if (strlen(header+7) == length)
        for (size_t i=0; i<length; ++i) diff |= (unsigned char)header[i+7] ^ (unsigned char)config->robot_token[i];
    memset(header, 0, sizeof(header));
    return diff == 0;
}

static esp_err_t error_response(httpd_req_t *r, esp_err_t error)
{
    char body[128];
    snprintf(body, sizeof(body), "{\"error\":\"%s\"}", esp_err_to_name(error));
    return response(r, "409 Conflict", body);
}

static bool read_exact(httpd_req_t *r, void *buffer, size_t bytes)
{
    size_t done = 0;
    while (done < bytes) {
        const int n = httpd_req_recv(r, (char *)buffer + done, bytes - done);
        if (n <= 0) return false; /* Includes the configured 3-second timeout. */
        done += n;
    }
    return true;
}

static esp_err_t recording(httpd_req_t *r)
{
    if (!authorized(r)) return response(r, "401 Unauthorized", "{\"error\":\"pairing_token_required\"}");
    if (r->method == HTTP_POST) {
        char operation[6] = {0};
        if (r->content_len < 4 || r->content_len > 5 || !read_exact(r, operation, r->content_len))
            return response(r, "400 Bad Request", "{\"error\":\"use_start_or_stop\"}");
        esp_err_t result = ainekio_p4_ota_busy() ? ESP_ERR_INVALID_STATE :
            strcmp(operation, "start") == 0 ? ainekio_p4_video_start() :
            strcmp(operation, "stop") == 0 ? ainekio_p4_video_stop() : ESP_ERR_INVALID_ARG;
        if (result != ESP_OK) return error_response(r, result);
    }
    const ainekio_p4_video_status_t s = ainekio_p4_video_status();
    const ainekio_p4_storage_status_t sd = ainekio_p4_storage_status();
    char body[512];
    snprintf(body, sizeof(body), "{\"recording\":%s,\"frames\":%lu,\"dropped\":%lu,\"segments\":%lu,"
        "\"max_write_us\":%lu,\"path\":\"%s\",\"error\":\"%s\",\"mounted\":%s,\"free_bytes\":%llu,"
        "\"storage_error\":\"%s\",\"overwrite_oldest\":true,\"overwritten\":%lu}", s.recording ? "true" : "false",
        (unsigned long)s.frames, (unsigned long)s.dropped, (unsigned long)s.segments,
        (unsigned long)s.max_write_us, s.path, esp_err_to_name(s.error), sd.mounted ? "true" : "false",
        (unsigned long long)sd.free_bytes, esp_err_to_name(sd.last_error), (unsigned long)s.overwritten);
    return response(r, "200 OK", body);
}

static esp_err_t firmware_status(httpd_req_t *r)
{
    if (!authorized(r)) return response(r, "401 Unauthorized", "{\"error\":\"pairing_token_required\"}");
    static const char *names[] = {"idle", "preparing", "uploading", "verifying", "staged", "next_boot", "restarting", "accepted", "failed"};
    taskENTER_CRITICAL(&status_lock);
    const phase_t p = phase;
    const uint32_t count = received, size = total;
    const esp_err_t error = last_error;
    taskEXIT_CRITICAL(&status_lock);
    const esp_partition_t *running = esp_ota_get_running_partition(), *boot = esp_ota_get_boot_partition();
    const ainekio_p4_system_status_t s = ainekio_p4_system_status();
    char body[384];
    snprintf(body, sizeof(body), "{\"state\":\"%s\",\"received\":%lu,\"size\":%lu,\"running\":\"%s\","
        "\"boot\":\"%s\",\"ota_layout\":%s,\"pending_verify\":%s,\"error\":\"%s\",\"version\":\"%s\"}", names[p],
        (unsigned long)count, (unsigned long)size, running ? running->label : "", boot ? boot->label : "",
        s.ota_layout ? "true" : "false", s.ota_pending ? "true" : "false", esp_err_to_name(error),
        esp_app_get_description()->version);
    return response(r, "200 OK", body);
}

static esp_err_t controller_logs(httpd_req_t *r)
{
    if (!authorized(r)) return response(r, "401 Unauthorized", "{\"error\":\"pairing_token_required\"}");
    char *snapshot = malloc(AINEKIO_P4_LOG_SNAPSHOT_BYTES);
    if (!snapshot) return error_response(r, ESP_ERR_NO_MEM);
    const size_t size = ainekio_p4_logs_snapshot(snapshot, AINEKIO_P4_LOG_SNAPSHOT_BYTES);
    if (!size) { free(snapshot); return error_response(r, ESP_ERR_INVALID_STATE); }
    httpd_resp_set_type(r, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    esp_err_t result = ESP_OK;
    for (size_t offset=0; offset<size && result==ESP_OK; offset+=4096)
        result = httpd_resp_send_chunk(r, snapshot+offset, size-offset < 4096 ? size-offset : 4096);
    free(snapshot);
    return result == ESP_OK ? httpd_resp_send_chunk(r, NULL, 0) : ESP_FAIL;
}

static esp_err_t recordings(httpd_req_t *r)
{
    if (!authorized(r)) return response(r, "401 Unauthorized", "{\"error\":\"pairing_token_required\"}");
    char query[96], name[64];
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    esp_err_t result;
    if (httpd_req_get_url_query_len(r)) {
        if (httpd_req_get_url_query_str(r, query, sizeof(query)) != ESP_OK ||
            httpd_query_key_value(query, "name", name, sizeof(name)) != ESP_OK)
            return error_response(r, ESP_ERR_INVALID_ARG);
        uint64_t remaining = 0;
        result = ainekio_p4_recording_read_open(name, &remaining);
        if (result != ESP_OK) return error_response(r, result);
        char *buffer = malloc(4096);
        if (!buffer) { ainekio_p4_recording_read_close(); return error_response(r, ESP_ERR_NO_MEM); }
        char disposition[96], length[24];
        snprintf(disposition, sizeof(disposition), "attachment; filename=\"%s\"", name);
        snprintf(length, sizeof(length), "%llu", (unsigned long long)remaining);
        httpd_resp_set_type(r, "video/x-msvideo");
        httpd_resp_set_hdr(r, "Content-Disposition", disposition);
        httpd_resp_set_hdr(r, "X-Recording-Bytes", length);
        while (remaining && result == ESP_OK) {
            size_t count = 0;
            result = ainekio_p4_recording_read(buffer, remaining < 4096 ? remaining : 4096, &count);
            if (result != ESP_OK || !count) { result = ESP_FAIL; break; }
            result = httpd_resp_send_chunk(r, buffer, count);
            remaining -= count;
            vTaskDelay(1);
        }
        free(buffer);
        ainekio_p4_recording_read_close();
    } else {
        result = ainekio_p4_recording_list_open();
        if (result != ESP_OK) return error_response(r, result);
        httpd_resp_set_type(r, "application/json");
        result = httpd_resp_send_chunk(r, "{\"files\":[", HTTPD_RESP_USE_STRLEN);
        bool done = false, first = true;
        while (result == ESP_OK && !done) {
            ainekio_p4_recording_file_t file;
            result = ainekio_p4_recording_list_next(&file, &done);
            if (result == ESP_OK && file.name[0]) {
                char item[160];
                snprintf(item, sizeof(item), "%s{\"name\":\"%s\",\"bytes\":%llu,\"complete\":%s}",
                    first ? "" : ",", file.name, (unsigned long long)file.bytes, file.complete ? "true" : "false");
                result = httpd_resp_send_chunk(r, item, HTTPD_RESP_USE_STRLEN);
                first = false;
            }
            vTaskDelay(1);
        }
        ainekio_p4_recording_read_close();
        if (result == ESP_OK) result = httpd_resp_send_chunk(r, "]}", HTTPD_RESP_USE_STRLEN);
    }
    /* An interrupted read must not terminate a truncated download as success. */
    return result == ESP_OK ? httpd_resp_send_chunk(r, NULL, 0) : ESP_FAIL;
}

static uint32_t ready_devices(void)
{
    const ainekio_p4_media_status_t m = ainekio_p4_media_status();
    const ainekio_pca_status_t output = ainekio_pca_status(ainekio_p4_output());
    /* OTA authentication deliberately latches outputs off. That clears the
     * driver's ready flag without undoing a successful boot-time bus probe. */
    const bool output_ready = output.ready || (ainekio_p4_output_initialized() &&
        output.fault == AINEKIO_PCA_FAULT_EMERGENCY);
    return (m.camera_ready ? EXPECT_CAMERA : 0) | (m.microphone_ready ? EXPECT_MIC : 0) |
        (m.speaker_ready ? EXPECT_SPEAKER : 0) | (ainekio_p4_display_ready() ? EXPECT_DISPLAY : 0) |
        (output_ready ? EXPECT_OUTPUT : 0);
}

static esp_err_t upload(httpd_req_t *r)
{
    if (!authorized(r)) return response(r, "401 Unauthorized", "{\"error\":\"pairing_token_required\"}");
    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *target = esp_ota_get_next_update_partition(NULL);
    const esp_partition_t *boot = esp_ota_get_boot_partition();
    if (!ainekio_p4_system_status().ota_layout || !target || !running || target->address == running->address ||
        !boot || boot->address != running->address || ainekio_p4_system_status().restart_pending)
        return error_response(r, ESP_ERR_INVALID_STATE);
    enum { PREFIX = sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t) + sizeof(esp_app_desc_t) };
    if (r->content_len < PREFIX || r->content_len > target->size) return error_response(r, ESP_ERR_INVALID_SIZE);
    uint8_t *buffer = malloc(4096);
    if (!buffer) return error_response(r, ESP_ERR_NO_MEM);
    esp_err_t result = ESP_OK;
    esp_ota_handle_t handle = 0;
    bool open = false;
    if (!read_exact(r, buffer, PREFIX)) { free(buffer); return error_response(r, ESP_ERR_TIMEOUT); }
    esp_image_header_t image;
    esp_app_desc_t desc;
    memcpy(&image, buffer, sizeof(image));
    memcpy(&desc, buffer + sizeof(image) + sizeof(esp_image_segment_header_t), sizeof(desc));
    if (image.magic != ESP_IMAGE_HEADER_MAGIC || image.chip_id != ESP_CHIP_ID_ESP32P4 ||
        desc.magic_word != ESP_APP_DESC_MAGIC_WORD ||
        memcmp(desc.project_name, esp_app_get_description()->project_name, sizeof(desc.project_name)) != 0) {
        free(buffer); return error_response(r, ESP_ERR_INVALID_ARG);
    }
    if (atomic_exchange(&busy, true)) { free(buffer); return error_response(r, ESP_ERR_INVALID_STATE); }
    if (ainekio_p4_system_status().restart_pending) {
        atomic_store(&busy, false); free(buffer); return error_response(r, ESP_ERR_INVALID_STATE);
    }
    staged = NULL;
    expected = ready_devices();
    taskENTER_CRITICAL(&status_lock); received = 0; total = r->content_len; taskEXIT_CRITICAL(&status_lock);
    status(PREPARING, ESP_OK);
    result = ainekio_p4_system_state(AINEKIO_STATE_REQUEST_DOZE, 0);
    if (result != ESP_OK) goto done;
    result = ainekio_p4_video_stop();
    if (result != ESP_OK) goto done;
    /* Sequential mode erases sectors as they are written; no full-slot erase
     * and no watchdog relaxation. Yield between bounded 4 KiB writes. */
    result = esp_ota_begin(target, OTA_WITH_SEQUENTIAL_WRITES, &handle);
    if (result != ESP_OK) goto done;
    open = true;
    status(UPLOADING, ESP_OK);
    size_t count = PREFIX, done_bytes = 0;
    for (;;) {
        result = esp_ota_write(handle, buffer, count);
        if (result != ESP_OK) goto done;
        done_bytes += count;
        taskENTER_CRITICAL(&status_lock); received = done_bytes; taskEXIT_CRITICAL(&status_lock);
        vTaskDelay(1);
        if (done_bytes == r->content_len) break;
        count = r->content_len - done_bytes;
        if (count > 4096) count = 4096;
        if (!read_exact(r, buffer, count)) { result = ESP_ERR_TIMEOUT; goto done; }
    }
    status(VERIFYING, ESP_OK);
    result = esp_ota_end(handle); /* IDF validates image hash, chip and silicon revision. */
    open = false;
    if (result == ESP_OK) { staged = target; status(STAGED, ESP_OK); }
done:
    if (open) esp_ota_abort(handle);
    free(buffer);
    atomic_store(&busy, false);
    if (result != ESP_OK) { status(FAILED, result); return error_response(r, result); }
    return response(r, "200 OK", "{\"state\":\"staged\",\"activation\":\"required\",\"body\":\"doze\"}");
}

static esp_err_t activate(httpd_req_t *r)
{
    if (!authorized(r)) return response(r, "401 Unauthorized", "{\"error\":\"pairing_token_required\"}");
    char operation[10] = {0};
    if (r->content_len < 7 || r->content_len > 9 || !read_exact(r, operation, r->content_len) ||
        (strcmp(operation, "restart") && strcmp(operation, "next_boot")))
        return response(r, "400 Bad Request", "{\"error\":\"use_restart_or_next_boot\"}");
    if (!staged || atomic_exchange(&busy, true)) return error_response(r, ESP_ERR_INVALID_STATE);
    if (ainekio_p4_system_status().restart_pending) {
        atomic_store(&busy, false); return error_response(r, ESP_ERR_INVALID_STATE);
    }
    status(PREPARING, ESP_OK);
    esp_err_t result = ainekio_p4_system_state(AINEKIO_STATE_REQUEST_DOZE, 0);
    if (result == ESP_OK) result = ainekio_p4_video_stop();
    nvs_handle_t nvs;
    if (result == ESP_OK) {
        result = nvs_open("p4_ota", NVS_READWRITE, &nvs);
        if (result == ESP_OK) {
            result = nvs_set_u32(nvs, "expected", expected);
            if (result == ESP_OK) result = nvs_commit(nvs);
            nvs_close(nvs);
        }
    }
    if (result == ESP_OK) result = esp_ota_set_boot_partition(staged);
    atomic_store(&busy, false);
    if (result == ESP_OK) {
        status(NEXT_BOOT, ESP_OK);
        if (!strcmp(operation, "restart")) {
            status(RESTARTING, ESP_OK);
            result = ainekio_p4_system_restart();
        }
    }
    if (result != ESP_OK) { status(FAILED, result); return error_response(r, result); }
    return response(r, "200 OK", "{\"state\":\"selected_for_next_boot\"}");
}

esp_err_t ainekio_p4_ota_startup_check(void)
{
    status(VERIFYING, ESP_OK);
    uint32_t required = 0;
    nvs_handle_t nvs;
    esp_err_t result = nvs_open("p4_ota", NVS_READONLY, &nvs);
    if (result == ESP_OK) {
        result = nvs_get_u32(nvs, "expected", &required);
        nvs_close(nvs);
    }
    if (result != ESP_OK) { status(FAILED, result); return result; }
    esp_hosted_coprocessor_fwver_t version = {0};
    result = esp_hosted_get_coprocessor_fwversion(&version);
    const ainekio_pca_status_t output = ainekio_pca_status(ainekio_p4_output());
    const uint32_t ready = ready_devices();
    const uint32_t stack = ainekio_p4_body_timing().stack_free_bytes;
    /* Preserve the startup decision and expose its inputs for USB and Wi-Fi
     * diagnosis before runtime log capture is enabled by acceptance. */
    char detail[192];
    snprintf(detail, sizeof(detail),
        "OTA startup required=0x%lx ready=0x%lx body_stack=%lu C6=%s version=%u.%u.%u output_fault=%d",
        (unsigned long)required, (unsigned long)ready, (unsigned long)stack,
        esp_err_to_name(result), (unsigned)version.major1, (unsigned)version.minor1,
        (unsigned)version.patch1, (int)output.fault);
    ainekio_p4_log_stage(detail);
    puts(detail);
    if (result == ESP_OK && ((ready & required) != required ||
        !stack || !version.major1 ||
        output.fault == AINEKIO_PCA_FAULT_IO || output.fault == AINEKIO_PCA_FAULT_DEADLINE ||
        output.fault == AINEKIO_PCA_FAULT_PROGRESS)) result = ESP_ERR_INVALID_STATE;
    if (result != ESP_OK) status(FAILED, result);
    return result;
}

void ainekio_p4_ota_accepted(void) { status(ACCEPTED, ESP_OK); }

bool ainekio_p4_ota_page(ainekio_connection_page_t *page)
{
    taskENTER_CRITICAL(&status_lock);
    phase_t p = phase;
    const uint32_t count = received, size = total;
    const bool expired = esp_timer_get_time() > notice_until;
    taskEXIT_CRITICAL(&status_lock);
    if (p == NONE && ainekio_p4_system_status().ota_pending) p = VERIFYING;
    if (p == NONE || ((p == ACCEPTED || p == FAILED) && expired)) return false;
    memset(page, 0, sizeof(*page));
    page->pages = 1;
    snprintf(page->heading, sizeof(page->heading), "Firmware update");
    const char *message = p == PREPARING ? "Preparing / Doze" : p == UPLOADING ? "Writing flash" :
        p == VERIFYING ? "Checking firmware" : p == STAGED ? "Upload verified" :
        p == NEXT_BOOT ? "Ready for next boot" : p == RESTARTING ? "Restarting..." :
        p == ACCEPTED ? "Update accepted" : "Update failed";
    snprintf(page->lines[0], sizeof(page->lines[0]), "%s", message);
    if (p == UPLOADING) snprintf(page->lines[1], sizeof(page->lines[1]), "%lu%%", (unsigned long)(size ? (uint64_t)count*100/size : 0));
    if (p == STAGED) snprintf(page->lines[1], sizeof(page->lines[1]), "Choose activation");
    if (p == FAILED) snprintf(page->lines[1], sizeof(page->lines[1]), "Check update status");
    if (p == PREPARING || p == UPLOADING || p == VERIFYING)
        snprintf(page->footer, sizeof(page->footer), "Keep power connected");
    return true;
}

static esp_err_t idle_rest(httpd_req_t *r)
{
    if(!authorized(r))return response(r,"401 Unauthorized","{\"error\":\"pairing_token_required\"}");
    return ainekio_p4_idle_rest_http(r);
}

static esp_err_t servo_feedback(httpd_req_t *r)
{
    if(!authorized(r))return response(r,"401 Unauthorized","{\"error\":\"pairing_token_required\"}");
    return ainekio_p4_feedback_http(r);
}

esp_err_t ainekio_p4_maintenance_register(httpd_handle_t server)
{
    const httpd_uri_t endpoints[] = {
        {.uri="/api/idle-rest", .method=HTTP_GET, .handler=idle_rest},
        {.uri="/api/idle-rest", .method=HTTP_POST, .handler=idle_rest},
        {.uri="/api/servo-feedback", .method=HTTP_GET, .handler=servo_feedback},
        {.uri="/api/servo-feedback", .method=HTTP_POST, .handler=servo_feedback},
        {.uri="/api/logs", .method=HTTP_GET, .handler=controller_logs},
        {.uri="/api/recording", .method=HTTP_GET, .handler=recording},
        {.uri="/api/recording", .method=HTTP_POST, .handler=recording},
        {.uri="/api/recordings", .method=HTTP_GET, .handler=recordings},
        {.uri="/api/firmware", .method=HTTP_GET, .handler=firmware_status},
        {.uri="/api/firmware", .method=HTTP_POST, .handler=upload},
        {.uri="/api/firmware/activate", .method=HTTP_POST, .handler=activate},
    };
    for (size_t i=0; i<sizeof(endpoints)/sizeof(endpoints[0]); ++i) {
        esp_err_t result = httpd_register_uri_handler(server, &endpoints[i]);
        if (result != ESP_OK) return result;
    }
    return ESP_OK;
}
