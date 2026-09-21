#include "config.h"
#include "board.h"
#include "controller.h"

#include <stdio.h>
#include <string.h>
#include "nvs.h"
#include "esp_system.h"

/* This target owns its NVS namespace. The portable configuration store still
 * owns validation, generation, staged records and commit selection. */
static ainekio_config_store_t store;
static ainekio_config_record_t boot_config;
static bool boot_configured;

static ainekio_store_result_t blob(const char *key, void *data, size_t size, bool write)
{
    nvs_handle_t nvs;
    esp_err_t result = nvs_open("p4_config", write ? NVS_READWRITE : NVS_READONLY, &nvs);
    if (result == ESP_OK) {
        size_t actual = size;
        result = write ? nvs_set_blob(nvs, key, data, size) : nvs_get_blob(nvs, key, data, &actual);
        if (write && result == ESP_OK) result = nvs_commit(nvs);
        if (!write && result == ESP_OK && actual != size) result = ESP_ERR_NVS_INVALID_LENGTH;
        nvs_close(nvs);
    }
    if (result == ESP_OK) return AINEKIO_STORE_OK;
    if (result == ESP_ERR_NVS_NOT_FOUND) return AINEKIO_STORE_NOT_FOUND;
    if (result == ESP_ERR_NVS_INVALID_LENGTH || result == ESP_ERR_NVS_TYPE_MISMATCH)
        return AINEKIO_STORE_CORRUPT;
    return AINEKIO_STORE_IO_ERROR;
}
static const char *slot_key(ainekio_config_slot_t slot)
{
    return slot == AINEKIO_CONFIG_SLOT_A ? "slot_a" : "slot_b";
}
static ainekio_store_result_t read_meta(void *p, ainekio_config_meta_t *m)
{ (void)p; return blob("meta", m, sizeof(*m), false); }
static ainekio_store_result_t write_meta(void *p, const ainekio_config_meta_t *m)
{ (void)p; return blob("meta", (void *)m, sizeof(*m), true); }
static ainekio_store_result_t read_record(void *p, ainekio_config_slot_t s, ainekio_config_record_t *r)
{ (void)p; return blob(slot_key(s), r, sizeof(*r), false); }
static ainekio_store_result_t write_record(void *p, ainekio_config_slot_t s, const ainekio_config_record_t *r)
{ (void)p; return blob(slot_key(s), (void *)r, sizeof(*r), true); }
static ainekio_store_result_t erase_record(void *p, ainekio_config_slot_t slot)
{
    (void)p;
    nvs_handle_t nvs;
    esp_err_t result = nvs_open("p4_config", NVS_READWRITE, &nvs);
    if (result != ESP_OK) return AINEKIO_STORE_IO_ERROR;
    result = nvs_erase_key(nvs, slot_key(slot));
    if (result == ESP_ERR_NVS_NOT_FOUND) result = ESP_OK;
    if (result == ESP_OK) result = nvs_commit(nvs);
    nvs_close(nvs);
    return result == ESP_OK ? AINEKIO_STORE_OK : AINEKIO_STORE_IO_ERROR;
}

esp_err_t ainekio_p4_config_init(void)
{
    const ainekio_config_store_port_t port = {
        .read_meta=read_meta, .write_meta=write_meta, .read_record=read_record,
        .write_record=write_record, .erase_record=erase_record,
    };
    ainekio_config_store_init(&store, &port);
    const ainekio_config_load_result_t result = ainekio_config_store_load(&store);
    boot_configured = store.has_active;
    boot_config = store.active;
    printf("configuration load=%d; configured=%d\n", result, store.has_active);
    return result == AINEKIO_CONFIG_LOAD_IO_ERROR ? ESP_FAIL : ESP_OK;
}

const ainekio_config_record_t *ainekio_p4_config(void)
{
    return boot_configured ? &boot_config : NULL;
}

static bool copy(char *target, size_t capacity, const char *source)
{
    if (strlen(source) >= capacity) return false;
    strcpy(target, source);
    return true;
}

int ainekio_p4_config_command(int argc, char **argv)
{
    ainekio_config_record_t candidate = store.has_active ? store.active : (ainekio_config_record_t){0};
    candidate.schema_version = AINEKIO_NVS_SCHEMA_VERSION;
    candidate.complete = true;
    candidate.generation = 1; /* The store assigns the next committed generation. */
    if (argc == 3 && strcmp(argv[1], "controller") == 0 && store.has_active) {
        if (!copy(candidate.endpoint_url, sizeof(candidate.endpoint_url), argv[2])) return 1;
    } else if (argc == 6) {
        if (!copy(candidate.wifi_ssid, sizeof(candidate.wifi_ssid), argv[1]) ||
            !copy(candidate.wifi_psk, sizeof(candidate.wifi_psk), argv[2]) ||
            !copy(candidate.endpoint_url, sizeof(candidate.endpoint_url), argv[3]) ||
            !copy(candidate.robot_id, sizeof(candidate.robot_id), argv[4]) ||
            !copy(candidate.robot_token, sizeof(candidate.robot_token), argv[5])) return 1;
    } else {
        puts("config <ssid> <psk> <ws(s)://host:port/robot> <robot-id> <token>\n"
             "config controller <ws(s)://host:port/robot> (retains credentials)\n"
             "Successful configuration commits then restarts DISARMED. Use a private serial terminal.");
        return 1;
    }
    strcpy(candidate.transport_mode, strncmp(candidate.endpoint_url, "wss://", 6) == 0
           ? AINEKIO_TRANSPORT_REMOTE : AINEKIO_TRANSPORT_LOCAL);
    const size_t length = strlen(candidate.endpoint_url);
    if (length < 6 || strcmp(candidate.endpoint_url + length - 6, "/robot") != 0 ||
        !ainekio_config_record_valid(&candidate, true)) {
        puts("Invalid configuration; nothing committed.");
        return 1;
    }
    ainekio_p4_controller_quiesce();
    if (ainekio_config_store_stage_initial(&store, &candidate) != AINEKIO_STORE_OK ||
        ainekio_config_store_commit(&store) != AINEKIO_STORE_OK) {
        puts("Configuration commit failed; outputs remain disabled.");
        return 1;
    }
    esp_restart();
    return 0;
}
