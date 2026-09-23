#include "system.h"
#include "board.h"
#include "body.h"
#include "controller.h"
#include "network.h"
#include "storage.h"
#include "ainekio/p4_media.h"

#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs.h"

typedef struct { bool restart; } power_request_t;
static QueueHandle_t power_queue;
static SemaphoreHandle_t settings_lock;
static atomic_int profile = AINEKIO_PROFILE_HOME;
static atomic_int state = AINEKIO_STATE_IDLE;
static atomic_bool power_pending, ota_pending;
static bool ota_layout;

static void power_task(void *argument)
{
    (void)argument;
    power_request_t request;
    for (;;) {
        if (xQueueReceive(power_queue, &request, portMAX_DELAY) != pdTRUE) continue;
        /* Give the command owner an opportunity to transmit the accepted
         * result before quiesce closes its transport. */
        vTaskDelay(pdMS_TO_TICKS(250));
        ainekio_p4_controller_quiesce();
        ainekio_p4_network_suspend();
        if (request.restart) esp_restart();
        esp_deep_sleep_start();
    }
}

esp_err_t ainekio_p4_system_start(void)
{
    if (power_queue) return ESP_ERR_INVALID_STATE;
    nvs_handle_t nvs;
    esp_err_t result = nvs_open("p4_system", NVS_READWRITE, &nvs);
    if (result != ESP_OK) return result;
    uint8_t saved = AINEKIO_PROFILE_HOME;
    result = nvs_get_u8(nvs, "profile", &saved);
    nvs_close(nvs);
    if (result != ESP_OK && result != ESP_ERR_NVS_NOT_FOUND) return result;
    if (saved > AINEKIO_PROFILE_TETHER) return ESP_ERR_INVALID_STATE;
    atomic_store(&profile, saved);
    const esp_partition_t *running = esp_ota_get_running_partition();
    ota_layout = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_OTA, NULL) != NULL &&
                 esp_ota_get_next_update_partition(NULL) != NULL;
    esp_ota_img_states_t image_state;
    atomic_store(&ota_pending, running && esp_ota_get_state_partition(running, &image_state) == ESP_OK &&
                              image_state == ESP_OTA_IMG_PENDING_VERIFY);
    settings_lock = xSemaphoreCreateMutex();
    power_queue = xQueueCreate(1, sizeof(power_request_t));
    if (!settings_lock || !power_queue || xTaskCreate(power_task, "system", 4096, NULL, 3, NULL) != pdPASS) {
        if (settings_lock) vSemaphoreDelete(settings_lock);
        if (power_queue) vQueueDelete(power_queue);
        settings_lock = NULL;
        power_queue = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

ainekio_p4_system_status_t ainekio_p4_system_status(void)
{
    return (ainekio_p4_system_status_t){
        .profile = atomic_load(&profile), .state = atomic_load(&state),
        .uptime_ms = (uint64_t)esp_timer_get_time() / 1000U,
        .heap_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
        .heap_minimum = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
        .reset_reason = esp_reset_reason(), .battery_available = false,
        .ota_layout = ota_layout, .ota_pending = atomic_load(&ota_pending),
        .restart_pending = atomic_load(&power_pending),
    };
}

esp_err_t ainekio_p4_system_profile(ainekio_profile_t requested)
{
    if (requested != AINEKIO_PROFILE_HOME && requested != AINEKIO_PROFILE_TETHER) return ESP_ERR_INVALID_ARG;
    if (!settings_lock || atomic_load(&power_pending)) return ESP_ERR_INVALID_STATE;
    if (xSemaphoreTake(settings_lock, pdMS_TO_TICKS(100)) != pdTRUE) return ESP_ERR_TIMEOUT;
    if (atomic_load(&power_pending)) { xSemaphoreGive(settings_lock); return ESP_ERR_INVALID_STATE; }
    esp_err_t result = ESP_OK;
    if ((int)requested != atomic_load(&profile)) {
        ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
        nvs_handle_t nvs;
        result = nvs_open("p4_system", NVS_READWRITE, &nvs);
        if (result == ESP_OK) {
            result = nvs_set_u8(nvs, "profile", requested);
            if (result == ESP_OK) result = nvs_commit(nvs);
            nvs_close(nvs);
        }
        if (result == ESP_OK) atomic_store(&profile, requested);
    }
    xSemaphoreGive(settings_lock);
    return result;
}

static esp_err_t schedule_power(bool restart, uint32_t seconds)
{
    if (!power_queue || atomic_exchange(&power_pending, true)) return ESP_ERR_INVALID_STATE;
    ainekio_body_state_t previous_state = atomic_load(&state);
    bool storage_attempted = false, media_attempted = false, timer_prepared = false, hold_attempted = false;
    bool settings_held = false;
    esp_err_t result = ESP_OK;
    /* Admission closes immediately, but transport stays alive until every
     * fallible step has completed so the caller can return a truthful NAK. */
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    if (xSemaphoreTake(settings_lock, pdMS_TO_TICKS(100)) != pdTRUE) { result = ESP_ERR_TIMEOUT; goto failed; }
    settings_held = true;
    previous_state = atomic_load(&state);
    if (!restart) {
        /* Rev 1.3 loses GPIO hold on wake. The ordinary output owner must
         * clear retained PWM registers before the ROM/bootloader interval. */
        result = ainekio_p4_body_prepare(ainekio_pca_status(ainekio_p4_output()).generation);
        if (result != ESP_OK) goto failed;
    }
    media_attempted = true;
    result = ainekio_p4_media_suspend(true);
    if (result != ESP_OK) goto failed;
    storage_attempted = true;
    result = ainekio_p4_storage_suspend(2000);
    if (result != ESP_OK) goto failed;
    if (!restart) {
        result = esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000U);
        if (result != ESP_OK) goto failed;
        timer_prepared = true;
        hold_attempted = true;
        result = gpio_hold_en(AINEKIO_P4_PCA_OE);
        if (result != ESP_OK) goto failed;
    }
    const power_request_t request = {.restart=restart};
    if (xQueueSend(power_queue, &request, 0) != pdTRUE) { result = ESP_ERR_TIMEOUT; goto failed; }
    xSemaphoreGive(settings_lock);
    return ESP_OK;
failed:
    if (hold_attempted) (void)gpio_hold_dis(AINEKIO_P4_PCA_OE);
    if (timer_prepared) (void)esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_TIMER);
    if (storage_attempted) {
        const esp_err_t resumed = ainekio_p4_storage_resume();
        if (resumed != ESP_OK) ESP_LOGE("system", "Storage admission resume: %s", esp_err_to_name(resumed));
    }
    if (media_attempted) {
        const esp_err_t resumed = ainekio_p4_media_suspend(previous_state == AINEKIO_STATE_DOZING);
        if (resumed != ESP_OK) ESP_LOGE("system", "Media availability resume: %s", esp_err_to_name(resumed));
    }
    ESP_LOGE("system", "Power preparation rejected: %s; outputs disabled, controller remains available", esp_err_to_name(result));
    if (settings_held) xSemaphoreGive(settings_lock);
    atomic_store(&power_pending, false);
    return result;
}

esp_err_t ainekio_p4_system_restart(void) { return schedule_power(true, 0); }

esp_err_t ainekio_p4_system_state(ainekio_state_request_t requested, uint32_t seconds)
{
    if (atomic_load(&power_pending)) return ESP_ERR_INVALID_STATE;
    if (requested == AINEKIO_STATE_REQUEST_SLEEP) {
        if (seconds == 0 || seconds > 86400U) return ESP_ERR_INVALID_ARG;
        esp_err_t result = schedule_power(false, seconds);
        if (result == ESP_OK) atomic_store(&state, AINEKIO_STATE_DEEP_SLEEP);
        return result;
    }
    if (requested != AINEKIO_STATE_REQUEST_IDLE && requested != AINEKIO_STATE_REQUEST_DOZE)
        return ESP_ERR_INVALID_ARG;
    if (!settings_lock) return ESP_ERR_INVALID_STATE;
    if (xSemaphoreTake(settings_lock, pdMS_TO_TICKS(100)) != pdTRUE) return ESP_ERR_TIMEOUT;
    if (atomic_load(&power_pending)) { xSemaphoreGive(settings_lock); return ESP_ERR_INVALID_STATE; }
    const bool dozing = requested == AINEKIO_STATE_REQUEST_DOZE;
    const ainekio_body_state_t previous = atomic_load(&state);
    /* Close body admission before changing the output generation. */
    if (dozing) atomic_store(&state, AINEKIO_STATE_DOZING);
    if (dozing) ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    esp_err_t result = ainekio_p4_media_suspend(dozing);
    atomic_store(&state, result == ESP_OK ? (dozing ? AINEKIO_STATE_DOZING : AINEKIO_STATE_IDLE) : previous);
    xSemaphoreGive(settings_lock);
    return result;
}

esp_err_t ainekio_p4_system_authenticated(void)
{
    if (!atomic_load(&ota_pending)) return ESP_OK;
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    esp_err_t result = esp_ota_mark_app_valid_cancel_rollback();
    if (result == ESP_OK) atomic_store(&ota_pending, false);
    return result;
}

int ainekio_p4_system_command(int argc, char **argv)
{
    if (argc > 1 && atomic_load(&power_pending)) return 1;
    esp_err_t result = ESP_OK;
    if (argc == 2 && strcmp(argv[1], "restart") == 0) result = ainekio_p4_system_restart();
    else if (argc == 2 && strcmp(argv[1], "idle") == 0) result = ainekio_p4_system_state(AINEKIO_STATE_REQUEST_IDLE, 0);
    else if (argc == 2 && strcmp(argv[1], "doze") == 0) result = ainekio_p4_system_state(AINEKIO_STATE_REQUEST_DOZE, 0);
    else if (argc == 3 && strcmp(argv[1], "sleep") == 0) {
        char *end;
        unsigned long seconds = strtoul(argv[2], &end, 10);
        if (!argv[2][0] || *end || seconds > 86400U) return 1;
        result = ainekio_p4_system_state(AINEKIO_STATE_REQUEST_SLEEP, seconds);
    } else if (argc == 3 && strcmp(argv[1], "profile") == 0) {
        if (strcmp(argv[2], "home") == 0) result = ainekio_p4_system_profile(AINEKIO_PROFILE_HOME);
        else if (strcmp(argv[2], "tether") == 0) result = ainekio_p4_system_profile(AINEKIO_PROFILE_TETHER);
        else return 1;
    } else if (argc == 3 && strcmp(argv[1], "storage") == 0) {
        if (strcmp(argv[2], "retry") == 0) result = ainekio_p4_storage_retry();
        else if (strcmp(argv[2], "clear") == 0) result = ainekio_p4_storage_clear();
        else return 1;
    } else if (argc != 1) return 1;
    const ainekio_p4_system_status_t status = ainekio_p4_system_status();
    const ainekio_p4_storage_status_t sd = ainekio_p4_storage_status();
    printf("system profile=%s state=%d uptime_ms=%" PRIu64 " heap=%" PRIu32 " battery=unavailable ota=%d pending=%d\n",
           status.profile == AINEKIO_PROFILE_HOME ? "home" : "tether", status.state, status.uptime_ms,
           status.heap_free, status.ota_layout, status.ota_pending);
    printf("storage mounted=%d free=%" PRIu64 " dropped=%" PRIu32 " error=%s\n",
           sd.mounted, sd.free_bytes, sd.dropped_records, esp_err_to_name(sd.last_error));
    return result == ESP_OK ? 0 : 1;
}
