#include "config.h"
#include "board.h"
#include "controller.h"
#include "system.h"

#include <stdio.h>
#include <math.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include "nvs.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

/* This target owns its NVS namespace. The portable configuration store still
 * owns validation, generation, staged records and commit selection. */
static ainekio_config_store_t store;
static ainekio_config_record_t boot_config;
static bool boot_configured;
static ainekio_p4_robot_settings_t boot_settings, saved_settings;
static SemaphoreHandle_t config_lock;
static ainekio_p4_calibration_t calibration;
static ainekio_p4_joint_record_t committed;
/* Independent of joint calibration. Readers never take the NVS write lock. */
static _Atomic float motion_rate = AINEKIO_MOTION_RATE_DEFAULT;
static atomic_bool motion_rate_saved;
_Static_assert(AINEKIO_BODY_JOINT_COUNT == AINEKIO_PCA_BODY_CHANNELS, "Joint/channel count mismatch");

static bool joints_valid(const ainekio_p4_joint_config_t *joints)
{
    if (!ainekio_p4_joints_valid(joints)) return false;
    const ainekio_pca9685_t *output = ainekio_p4_output();
    for (size_t i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i)
        if (!ainekio_pca_pulse_valid(output, joints[i].home_us)) return false;
    return true;
}

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
    config_lock = xSemaphoreCreateMutex();
    if (!config_lock) return ESP_ERR_NO_MEM;
    const ainekio_config_store_port_t port = {
        .read_meta=read_meta, .write_meta=write_meta, .read_record=read_record,
        .write_record=write_record, .erase_record=erase_record,
    };
    ainekio_config_store_init(&store, &port);
    const ainekio_config_load_result_t result = ainekio_config_store_load(&store);
    boot_configured = store.has_active;
    boot_config = store.active;
    saved_settings = (ainekio_p4_robot_settings_t){.version=1};
    const ainekio_store_result_t settings_result = blob("robot_settings", &saved_settings, sizeof(saved_settings), false);
    if (settings_result == AINEKIO_STORE_NOT_FOUND) {
        saved_settings = (ainekio_p4_robot_settings_t){.version=1};
        if (boot_configured) {
            strcpy(saved_settings.robot_id, boot_config.robot_id);
            strcpy(saved_settings.robot_token, boot_config.robot_token);
            strcpy(saved_settings.networks[0].ssid, boot_config.wifi_ssid);
            strcpy(saved_settings.networks[0].password, boot_config.wifi_psk);
            strcpy(saved_settings.networks[0].endpoint, boot_config.endpoint_url);
        }
    } else if (settings_result != AINEKIO_STORE_OK || !ainekio_p4_robot_settings_valid(&saved_settings)) {
        puts("Robot settings unavailable; refusing to use stale credentials.");
        return ESP_FAIL;
    }
    boot_settings = saved_settings;
    boot_configured = boot_settings.robot_id[0] && boot_settings.robot_token[0];
    if (boot_configured) {
        boot_config.schema_version = AINEKIO_NVS_SCHEMA_VERSION;
        boot_config.generation = boot_settings.revision + 1U;
        boot_config.complete = true;
        strcpy(boot_config.robot_id, boot_settings.robot_id);
        strcpy(boot_config.robot_token, boot_settings.robot_token);
        int index = ainekio_p4_network_next(&boot_settings, -1);
        const ainekio_p4_network_profile_t empty = {0};
        const ainekio_p4_network_profile_t *p = index < 0 ? &empty : &boot_settings.networks[index];
        strcpy(boot_config.wifi_ssid, p->ssid);
        strcpy(boot_config.wifi_psk, p->password);
        strcpy(boot_config.endpoint_url, p->endpoint);
        strcpy(boot_config.transport_mode, !strncmp(p->endpoint, "wss://", 6) ? "remote" : "local");
    }
    float rate = AINEKIO_MOTION_RATE_DEFAULT;
    const ainekio_store_result_t rate_result = blob("motion_rate", &rate, sizeof(rate), false);
    const bool rate_valid = rate_result == AINEKIO_STORE_OK &&
        isfinite(rate) && rate > 0.F;
    atomic_store(&motion_rate, rate_valid ? rate : AINEKIO_MOTION_RATE_DEFAULT);
    atomic_store(&motion_rate_saved, rate_valid);
    if (rate_result != AINEKIO_STORE_NOT_FOUND && !rate_valid)
        puts("Motion speed unavailable; using 2x until a setting is saved.");
    const bool defaults_valid = ainekio_p4_joint_defaults(calibration.joints);
    const ainekio_store_result_t saved = blob("joint_mapping", &committed, sizeof(committed), false);
    if (saved == AINEKIO_STORE_OK && committed.version == 1 && joints_valid(committed.joints)) {
        memcpy(calibration.joints, committed.joints, sizeof(calibration.joints));
        calibration.valid = calibration.saved = calibration.profile_confirmed = true;
    } else if (saved == AINEKIO_STORE_NOT_FOUND && defaults_valid) {
        calibration.valid = calibration.dirty = true;
        puts("No saved joint mapping. Stage and save calibration before automatic Home.");
    }
    calibration.valid = calibration.valid && joints_valid(calibration.joints);
    if (!calibration.valid) puts("Joint settings unreadable or invalid; automatic home disabled. Repair and save calibration.");
    printf("configuration load=%d; configured=%d\n", result, store.has_active);
    return result == AINEKIO_CONFIG_LOAD_IO_ERROR ? ESP_FAIL : ESP_OK;
}

float ainekio_p4_motion_rate(void) { return atomic_load(&motion_rate); }
bool ainekio_p4_motion_rate_saved(void) { return atomic_load(&motion_rate_saved); }
esp_err_t ainekio_p4_motion_rate_save(float rate)
{
    if (!isfinite(rate) || rate <= 0.F) return ESP_ERR_INVALID_ARG;
    if (ainekio_pca_status(ainekio_p4_output()).armed) return ESP_ERR_INVALID_STATE;
    const ainekio_store_result_t result = blob("motion_rate", &rate, sizeof(rate), true);
    if (result != AINEKIO_STORE_OK) return ESP_FAIL;
    atomic_store(&motion_rate, rate);
    atomic_store(&motion_rate_saved, true);
    return ESP_OK;
}

const ainekio_config_record_t *ainekio_p4_config(void)
{
    return boot_configured ? &boot_config : NULL;
}

ainekio_p4_calibration_t ainekio_p4_calibration(void)
{
    xSemaphoreTake(config_lock, portMAX_DELAY);
    const ainekio_p4_calibration_t result = calibration;
    xSemaphoreGive(config_lock);
    return result;
}

bool ainekio_p4_home_pulses(uint16_t pulses[AINEKIO_BODY_JOINT_COUNT])
{
    if (!pulses) return false;
    const ainekio_p4_calibration_t state = ainekio_p4_calibration();
    memset(pulses, 0, sizeof(uint16_t) * AINEKIO_BODY_JOINT_COUNT);
    if (!state.valid) return false;
    for (size_t i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i)
        if (state.joints[i].channel >= 0) pulses[state.joints[i].channel] = state.joints[i].home_us;
    return true;
}

bool ainekio_p4_frame_pulses(const ainekio_v2_frame_t *frame,
                           uint16_t pulses[AINEKIO_BODY_JOINT_COUNT])
{
    if (!pulses) return false;
    const ainekio_p4_calibration_t state = ainekio_p4_calibration();
    if (!state.valid || !state.profile_confirmed) { memset(pulses, 0, sizeof(uint16_t) * AINEKIO_BODY_JOINT_COUNT); return false; }
    if (!ainekio_p4_joint_map_frame(state.joints, frame, pulses)) return false;
    for (size_t i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i) {
        if (pulses[i] && !ainekio_pca_pulse_valid(ainekio_p4_output(), pulses[i])) {
            memset(pulses, 0, sizeof(uint16_t) * AINEKIO_BODY_JOINT_COUNT);
            return false;
        }
    }
    return true;
}

esp_err_t ainekio_p4_calibration_stage(uint8_t id, const ainekio_p4_joint_config_t *joint)
{
    if (id >= AINEKIO_BODY_JOINT_COUNT || !joint) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(config_lock, portMAX_DELAY);
    ainekio_p4_calibration_t candidate = calibration;
    candidate.joints[id] = *joint;
    esp_err_t result = ESP_ERR_INVALID_ARG;
    if (joints_valid(candidate.joints)) {
        candidate.valid = true;
        candidate.saved = committed.version == 1 &&
            memcmp(candidate.joints, committed.joints, sizeof(committed.joints)) == 0;
        candidate.dirty = !candidate.saved;
        calibration = candidate;
        result = ESP_OK;
    }
    xSemaphoreGive(config_lock);
    return result;
}

esp_err_t ainekio_p4_calibration_save(void)
{
    xSemaphoreTake(config_lock, portMAX_DELAY);
    if (!calibration.valid) { xSemaphoreGive(config_lock); return ESP_ERR_INVALID_STATE; }
    ainekio_p4_joint_record_t candidate = {.version=1};
    memcpy(candidate.joints, calibration.joints, sizeof(candidate.joints));
    const ainekio_store_result_t saved = blob("joint_mapping", &candidate, sizeof(candidate), true);
    if (saved == AINEKIO_STORE_OK) {
        committed = candidate;
        calibration.saved = calibration.profile_confirmed = true;
        calibration.dirty = false;
    }
    xSemaphoreGive(config_lock);
    return saved == AINEKIO_STORE_OK ? ESP_OK : ESP_FAIL;
}

static int configure_home(int argc, char **argv)
{
    if (argc == 2) {
        const ainekio_p4_calibration_t state = ainekio_p4_calibration();
        uint16_t home_pulses[AINEKIO_PCA_BODY_CHANNELS];
        ainekio_p4_home_pulses(home_pulses);
        printf("home settings valid=%d saved=%d dirty=%d; 0 means disabled\n", state.valid, state.saved, state.dirty);
        for (size_t i=0; i<AINEKIO_PCA_BODY_CHANNELS; ++i)
            printf("channel=%u home_us=%u\n", (unsigned)i, home_pulses[i]);
        return 0;
    }
    if (argc != 4) {
        puts("config home [channel 0..11] [pulse-us | off]\n"
             "Updates the saved home and restarts. Connect or move plugs only with power off.");
        return 1;
    }
    char *end;
    const unsigned long channel = strtoul(argv[2], &end, 10);
    if (!argv[2][0] || *end || channel >= AINEKIO_PCA_BODY_CHANNELS) return 1;
    unsigned long pulse = 0;
    if (strcmp(argv[3], "off") != 0) {
        pulse = strtoul(argv[3], &end, 10);
        if (!argv[3][0] || *end || pulse > UINT16_MAX ||
            !ainekio_pca_pulse_valid(ainekio_p4_output(), (uint16_t)pulse)) return 1;
    }
    ainekio_p4_calibration_t state = ainekio_p4_calibration();
    size_t id = channel;
    for (size_t i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i)
        if (state.joints[i].channel == (int)channel) { id=i; break; }
    ainekio_p4_joint_config_t candidate = state.joints[id];
    candidate.channel = pulse ? (int8_t)channel : -1;
    if (pulse) candidate.home_us = pulse;
    if (ainekio_p4_calibration_stage(id, &candidate) != ESP_OK) return 1;
    ainekio_pca_disarm(ainekio_p4_output());
    if (ainekio_p4_calibration_save() != ESP_OK) {
        puts("Home settings commit failed; outputs remain disabled.");
        return 1;
    }
    if (ainekio_p4_system_restart() != ESP_OK) {
        puts("Home settings saved, but restart preparation failed; outputs remain disabled.");
        return 1;
    }
    return 0;
}

static bool copy(char *target, size_t capacity, const char *source)
{
    if (strlen(source) >= capacity) return false;
    strcpy(target, source);
    return true;
}

const ainekio_p4_robot_settings_t *ainekio_p4_boot_settings(void) { return &boot_settings; }
ainekio_p4_robot_settings_t ainekio_p4_saved_settings(void)
{
    xSemaphoreTake(config_lock, portMAX_DELAY);
    ainekio_p4_robot_settings_t result = saved_settings;
    xSemaphoreGive(config_lock);
    return result;
}

/* Caller holds config_lock and has disabled outputs. NVS replaces one blob
 * atomically, including identity, credentials and every network profile. */
static esp_err_t commit_settings(const ainekio_p4_robot_settings_t *candidate)
{
    if (!ainekio_p4_robot_settings_valid(candidate)) return ESP_ERR_INVALID_ARG;
    if (blob("robot_settings", (void *)candidate, sizeof(*candidate), true) != AINEKIO_STORE_OK) return ESP_FAIL;
    saved_settings = *candidate;
    return ESP_OK;
}

esp_err_t ainekio_p4_settings_change(const ainekio_robot_settings_command_t *command)
{
    if (ainekio_p4_system_status().restart_pending || ainekio_pca_status(ainekio_p4_output()).armed) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(config_lock, portMAX_DELAY);
    ainekio_p4_robot_settings_t candidate = saved_settings;
    esp_err_t result = ESP_ERR_INVALID_ARG;
    if (command->operation == AINEKIO_SETTINGS_APPLY) {
        result = command->revision == saved_settings.revision ? ainekio_p4_system_restart() : ESP_ERR_INVALID_STATE;
    } else if (ainekio_p4_robot_settings_update(&candidate, command)) result = commit_settings(&candidate);
    memset(&candidate, 0, sizeof(candidate));
    xSemaphoreGive(config_lock);
    return result;
}

esp_err_t ainekio_p4_config_save_record(const ainekio_config_record_t *record)
{
    if (ainekio_p4_system_status().restart_pending) return ESP_ERR_INVALID_STATE;
    if (!record || !ainekio_config_record_valid(record, true)) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(config_lock, portMAX_DELAY);
    ainekio_p4_robot_settings_t candidate = saved_settings;
    strcpy(candidate.robot_id, record->robot_id);
    strcpy(candidate.robot_token, record->robot_token);
    int index = 0;
    for (unsigned i=0; i<AINEKIO_NETWORK_SLOTS; ++i)
        if (!strcmp(candidate.networks[i].ssid, record->wifi_ssid)) { index = i; break; }
    strcpy(candidate.networks[index].ssid, record->wifi_ssid);
    strcpy(candidate.networks[index].password, record->wifi_psk);
    strcpy(candidate.networks[index].endpoint, record->endpoint_url);
    for (unsigned i=0; i<AINEKIO_NETWORK_SLOTS; ++i)
        if (!strcmp(candidate.networks[i].ssid, record->wifi_ssid))
            strcpy(candidate.networks[i].password, record->wifi_psk);
    ++candidate.revision;
    esp_err_t result = commit_settings(&candidate);
    memset(&candidate, 0, sizeof(candidate));
    xSemaphoreGive(config_lock);
    return result;
}

esp_err_t ainekio_p4_config_reset_network(void)
{
    if (ainekio_p4_system_status().restart_pending) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(config_lock, portMAX_DELAY);
    ainekio_p4_robot_settings_t candidate = saved_settings;
    memset(candidate.networks, 0, sizeof(candidate.networks));
    ++candidate.revision;
    esp_err_t result = commit_settings(&candidate);
    memset(&candidate, 0, sizeof(candidate));
    xSemaphoreGive(config_lock);
    return result;
}

int ainekio_p4_config_command(int argc, char **argv)
{
    if (ainekio_p4_system_status().restart_pending) return 1;
    if (argc >= 2 && strcmp(argv[1], "home") == 0) return configure_home(argc, argv);
    ainekio_config_record_t candidate = boot_configured ? boot_config : (ainekio_config_record_t){0};
    candidate.schema_version = AINEKIO_NVS_SCHEMA_VERSION;
    candidate.complete = true;
    candidate.generation = 1; /* The store assigns the next committed generation. */
    if (argc == 3 && strcmp(argv[1], "controller") == 0 && boot_configured) {
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
             "config home [channel 0..11] [pulse-us | off]\n"
             "Successful configuration commits then restarts at the saved home. Use a private serial terminal.");
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
    ainekio_pca_disarm(ainekio_p4_output());
    if (ainekio_p4_config_save_record(&candidate) != ESP_OK) {
        puts("Configuration commit failed; outputs remain disabled.");
        return 1;
    }
    if (ainekio_p4_system_restart() != ESP_OK) {
        puts("Configuration saved, but restart preparation failed; outputs remain disabled.");
        return 1;
    }
    return 0;
}
