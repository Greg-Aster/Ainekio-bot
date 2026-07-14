#include "ainekio/config_store.h"

#include <string.h>

static bool bounded_length(const char *value, size_t capacity, size_t *length)
{
    for (size_t index = 0U; index < capacity; ++index) {
        if (value[index] == '\0') {
            *length = index;
            return true;
        }
    }
    return false;
}

static bool copy_bounded(char *destination, size_t capacity, const char *source)
{
    if (source == NULL) {
        return false;
    }
    const size_t length = strlen(source);
    if (length >= capacity) {
        return false;
    }
    memcpy(destination, source, length + 1U);
    return true;
}

static bool endpoint_valid(const char *endpoint, size_t length)
{
    return (length > 5U && strncmp(endpoint, "ws://", 5U) == 0) ||
           (length > 6U && strncmp(endpoint, "wss://", 6U) == 0);
}

static ainekio_config_slot_t inactive_slot(ainekio_config_slot_t active)
{
    return active == AINEKIO_CONFIG_SLOT_A ? AINEKIO_CONFIG_SLOT_B
                                           : AINEKIO_CONFIG_SLOT_A;
}

static ainekio_config_load_result_t load_result_for_store_error(
    ainekio_store_result_t result
)
{
    return result == AINEKIO_STORE_IO_ERROR ? AINEKIO_CONFIG_LOAD_IO_ERROR
                                            : AINEKIO_CONFIG_LOAD_CORRUPT;
}

static ainekio_store_result_t stage_record(
    ainekio_config_store_t *store,
    const ainekio_config_record_t *candidate,
    bool require_wifi
)
{
    ainekio_config_record_t staged = *candidate;
    staged.schema_version = AINEKIO_NVS_SCHEMA_VERSION;
    staged.generation = store->has_active ? store->active.generation + 1U : 1U;
    staged.complete = true;
    if (!ainekio_config_record_valid(&staged, require_wifi)) {
        return AINEKIO_STORE_CORRUPT;
    }
    const ainekio_config_slot_t slot =
        store->has_active ? inactive_slot(store->meta.active_slot) : AINEKIO_CONFIG_SLOT_A;

    ainekio_store_result_t result =
        store->port.write_record(store->port.context, slot, &staged);
    if (result != AINEKIO_STORE_OK) {
        return result;
    }

    ainekio_config_record_t verified;
    memset(&verified, 0, sizeof(verified));
    result = store->port.read_record(store->port.context, slot, &verified);
    if (result != AINEKIO_STORE_OK || memcmp(&verified, &staged, sizeof(staged)) != 0) {
        (void)store->port.erase_record(store->port.context, slot);
        return result == AINEKIO_STORE_OK ? AINEKIO_STORE_CORRUPT : result;
    }

    store->staged_slot = slot;
    store->has_staged = true;
    return AINEKIO_STORE_OK;
}

void ainekio_config_store_init(
    ainekio_config_store_t *store,
    const ainekio_config_store_port_t *port
)
{
    memset(store, 0, sizeof(*store));
    store->port = *port;
}

ainekio_config_load_result_t ainekio_config_store_load(ainekio_config_store_t *store)
{
    store->has_active = false;
    store->has_staged = false;
    memset(&store->meta, 0, sizeof(store->meta));
    memset(&store->active, 0, sizeof(store->active));

    ainekio_store_result_t result =
        store->port.read_meta(store->port.context, &store->meta);
    if (result == AINEKIO_STORE_NOT_FOUND) {
        return AINEKIO_CONFIG_LOAD_MISSING;
    }
    if (result == AINEKIO_STORE_IO_ERROR) {
        return AINEKIO_CONFIG_LOAD_IO_ERROR;
    }
    if (result != AINEKIO_STORE_OK ||
        (store->meta.active_slot != AINEKIO_CONFIG_SLOT_A &&
         store->meta.active_slot != AINEKIO_CONFIG_SLOT_B)) {
        return AINEKIO_CONFIG_LOAD_CORRUPT;
    }
    if (store->meta.schema_version > AINEKIO_NVS_SCHEMA_VERSION) {
        return AINEKIO_CONFIG_LOAD_SCHEMA_MISMATCH;
    }

    result = store->port.read_record(
        store->port.context,
        store->meta.active_slot,
        &store->active
    );
    if (result == AINEKIO_STORE_NOT_FOUND) {
        return AINEKIO_CONFIG_LOAD_CORRUPT;
    }
    if (result == AINEKIO_STORE_IO_ERROR) {
        return AINEKIO_CONFIG_LOAD_IO_ERROR;
    }
    if (result != AINEKIO_STORE_OK) {
        return AINEKIO_CONFIG_LOAD_CORRUPT;
    }

    if (store->meta.schema_version < AINEKIO_NVS_SCHEMA_VERSION) {
        if (store->active.schema_version != store->meta.schema_version) {
            return AINEKIO_CONFIG_LOAD_CORRUPT;
        }
        store->active.schema_version = AINEKIO_NVS_SCHEMA_VERSION;
        if (!ainekio_config_record_valid(&store->active, false)) {
            return AINEKIO_CONFIG_LOAD_CORRUPT;
        }
        store->has_active = true;
        result = stage_record(store, &store->active, false);
        if (result != AINEKIO_STORE_OK) {
            return load_result_for_store_error(result);
        }
        result = ainekio_config_store_commit(store);
        if (result != AINEKIO_STORE_OK) {
            return load_result_for_store_error(result);
        }
        return store->active.wifi_ssid[0] == '\0'
                   ? AINEKIO_CONFIG_LOAD_NO_WIFI
                   : AINEKIO_CONFIG_LOAD_MIGRATED;
    }
    if (!ainekio_config_record_valid(&store->active, false)) {
        return AINEKIO_CONFIG_LOAD_CORRUPT;
    }

    store->has_active = true;
    return store->active.wifi_ssid[0] == '\0' ? AINEKIO_CONFIG_LOAD_NO_WIFI
                                               : AINEKIO_CONFIG_LOAD_VALID;
}

bool ainekio_config_record_valid(const ainekio_config_record_t *record, bool require_wifi)
{
    if (record == NULL || record->schema_version != AINEKIO_NVS_SCHEMA_VERSION ||
        !record->complete || record->generation == 0U) {
        return false;
    }

    size_t ssid_length;
    size_t psk_length;
    size_t endpoint_length;
    size_t robot_id_length;
    size_t token_length;
    if (!bounded_length(record->wifi_ssid, sizeof(record->wifi_ssid), &ssid_length) ||
        !bounded_length(record->wifi_psk, sizeof(record->wifi_psk), &psk_length) ||
        !bounded_length(record->endpoint_url, sizeof(record->endpoint_url), &endpoint_length) ||
        !bounded_length(record->robot_id, sizeof(record->robot_id), &robot_id_length) ||
        !bounded_length(record->robot_token, sizeof(record->robot_token), &token_length)) {
        return false;
    }
    const bool has_wifi = ssid_length > 0U;
    if (require_wifi && !has_wifi) {
        return false;
    }
    if ((!has_wifi && psk_length != 0U) ||
        (has_wifi && (psk_length < 8U || psk_length > 64U))) {
        return false;
    }
    return endpoint_valid(record->endpoint_url, endpoint_length) &&
           robot_id_length > 0U && token_length > 0U;
}

ainekio_store_result_t ainekio_config_store_stage_initial(
    ainekio_config_store_t *store,
    const ainekio_config_record_t *candidate
)
{
    return stage_record(store, candidate, true);
}

ainekio_store_result_t ainekio_config_store_stage_network(
    ainekio_config_store_t *store,
    const char *ssid,
    const char *psk
)
{
    if (!store->has_active) {
        return AINEKIO_STORE_NOT_FOUND;
    }
    ainekio_config_record_t candidate = store->active;
    if (!copy_bounded(candidate.wifi_ssid, sizeof(candidate.wifi_ssid), ssid) ||
        !copy_bounded(candidate.wifi_psk, sizeof(candidate.wifi_psk), psk)) {
        return AINEKIO_STORE_CORRUPT;
    }
    return stage_record(store, &candidate, true);
}

ainekio_store_result_t ainekio_config_store_stage_network_reset(
    ainekio_config_store_t *store
)
{
    if (!store->has_active) {
        return AINEKIO_STORE_NOT_FOUND;
    }
    ainekio_config_record_t candidate = store->active;
    candidate.wifi_ssid[0] = '\0';
    candidate.wifi_psk[0] = '\0';
    return stage_record(store, &candidate, false);
}

ainekio_store_result_t ainekio_config_store_commit(ainekio_config_store_t *store)
{
    if (!store->has_staged) {
        return AINEKIO_STORE_NOT_FOUND;
    }
    ainekio_config_record_t staged;
    memset(&staged, 0, sizeof(staged));
    ainekio_store_result_t result = store->port.read_record(
        store->port.context,
        store->staged_slot,
        &staged
    );
    if (result != AINEKIO_STORE_OK ||
        !ainekio_config_record_valid(&staged, false)) {
        return result == AINEKIO_STORE_OK ? AINEKIO_STORE_CORRUPT : result;
    }

    const ainekio_config_meta_t next_meta = {
        .schema_version = AINEKIO_NVS_SCHEMA_VERSION,
        .active_slot = store->staged_slot,
    };
    result = store->port.write_meta(store->port.context, &next_meta);
    if (result != AINEKIO_STORE_OK) {
        return result;
    }
    store->meta = next_meta;
    store->active = staged;
    store->has_active = true;
    store->has_staged = false;
    store->staged_slot = AINEKIO_CONFIG_SLOT_NONE;
    return AINEKIO_STORE_OK;
}

ainekio_store_result_t ainekio_config_store_discard(ainekio_config_store_t *store)
{
    if (!store->has_staged) {
        return AINEKIO_STORE_OK;
    }
    const ainekio_store_result_t result =
        store->port.erase_record(store->port.context, store->staged_slot);
    if (result == AINEKIO_STORE_OK || result == AINEKIO_STORE_NOT_FOUND) {
        store->has_staged = false;
        store->staged_slot = AINEKIO_CONFIG_SLOT_NONE;
        return AINEKIO_STORE_OK;
    }
    return result;
}
