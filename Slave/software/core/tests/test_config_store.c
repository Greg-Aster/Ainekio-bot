#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "ainekio/config_store.h"

typedef struct {
    ainekio_config_meta_t meta;
    ainekio_config_record_t records[2];
    bool has_meta;
    bool has_record[2];
    bool fail_record_write;
    bool corrupt_readback;
    bool fail_meta_write;
} memory_store_t;

static size_t slot_index(ainekio_config_slot_t slot)
{
    assert(slot == AINEKIO_CONFIG_SLOT_A || slot == AINEKIO_CONFIG_SLOT_B);
    return slot == AINEKIO_CONFIG_SLOT_A ? 0U : 1U;
}

static ainekio_store_result_t read_meta(void *context, ainekio_config_meta_t *meta)
{
    memory_store_t *memory = context;
    if (!memory->has_meta) {
        return AINEKIO_STORE_NOT_FOUND;
    }
    *meta = memory->meta;
    return AINEKIO_STORE_OK;
}

static ainekio_store_result_t write_meta(
    void *context,
    const ainekio_config_meta_t *meta
)
{
    memory_store_t *memory = context;
    if (memory->fail_meta_write) {
        return AINEKIO_STORE_IO_ERROR;
    }
    memory->meta = *meta;
    memory->has_meta = true;
    return AINEKIO_STORE_OK;
}

static ainekio_store_result_t read_record(
    void *context,
    ainekio_config_slot_t slot,
    ainekio_config_record_t *record
)
{
    memory_store_t *memory = context;
    const size_t index = slot_index(slot);
    if (!memory->has_record[index]) {
        return AINEKIO_STORE_NOT_FOUND;
    }
    *record = memory->records[index];
    if (memory->corrupt_readback) {
        record->complete = false;
    }
    return AINEKIO_STORE_OK;
}

static ainekio_store_result_t write_record(
    void *context,
    ainekio_config_slot_t slot,
    const ainekio_config_record_t *record
)
{
    memory_store_t *memory = context;
    if (memory->fail_record_write) {
        return AINEKIO_STORE_IO_ERROR;
    }
    const size_t index = slot_index(slot);
    memory->records[index] = *record;
    memory->has_record[index] = true;
    return AINEKIO_STORE_OK;
}

static ainekio_store_result_t erase_record(void *context, ainekio_config_slot_t slot)
{
    memory_store_t *memory = context;
    memory->has_record[slot_index(slot)] = false;
    return AINEKIO_STORE_OK;
}

static ainekio_config_store_port_t port(memory_store_t *memory)
{
    return (ainekio_config_store_port_t){
        .context = memory,
        .read_meta = read_meta,
        .write_meta = write_meta,
        .read_record = read_record,
        .write_record = write_record,
        .erase_record = erase_record,
    };
}

static ainekio_config_record_t initial_record(void)
{
    ainekio_config_record_t record = {
        .schema_version = AINEKIO_NVS_SCHEMA_VERSION,
        .generation = 1U,
        .complete = true,
    };
    (void)strcpy(record.wifi_ssid, "first-network");
    (void)strcpy(record.wifi_psk, "first-password");
    (void)strcpy(record.endpoint_url, "ws://192.168.1.2:8790/robot");
    (void)strcpy(record.robot_id, "ainekio-01");
    (void)strcpy(record.robot_token, "secret-token");
    return record;
}

static void test_initial_commit_and_reload(void)
{
    memory_store_t memory = {0};
    const ainekio_config_store_port_t storage_port = port(&memory);
    ainekio_config_store_t store;
    ainekio_config_store_init(&store, &storage_port);
    assert(ainekio_config_store_load(&store) == AINEKIO_CONFIG_LOAD_MISSING);

    const ainekio_config_record_t record = initial_record();
    assert(ainekio_config_store_stage_initial(&store, &record) == AINEKIO_STORE_OK);
    assert(!store.has_active);
    assert(ainekio_config_store_commit(&store) == AINEKIO_STORE_OK);
    assert(store.meta.active_slot == AINEKIO_CONFIG_SLOT_A);

    ainekio_config_store_t reloaded;
    ainekio_config_store_init(&reloaded, &storage_port);
    assert(ainekio_config_store_load(&reloaded) == AINEKIO_CONFIG_LOAD_VALID);
    assert(strcmp(reloaded.active.wifi_ssid, "first-network") == 0);
    assert(strcmp(reloaded.active.robot_token, "secret-token") == 0);
}

static void test_network_replacement_commits_only_after_meta_switch(void)
{
    memory_store_t memory = {0};
    const ainekio_config_store_port_t storage_port = port(&memory);
    ainekio_config_store_t store;
    ainekio_config_store_init(&store, &storage_port);
    const ainekio_config_record_t record = initial_record();
    assert(ainekio_config_store_stage_initial(&store, &record) == AINEKIO_STORE_OK);
    assert(ainekio_config_store_commit(&store) == AINEKIO_STORE_OK);

    assert(ainekio_config_store_stage_network(
               &store,
               "second-network",
               "second-password"
           ) == AINEKIO_STORE_OK);
    assert(store.meta.active_slot == AINEKIO_CONFIG_SLOT_A);
    assert(strcmp(store.active.wifi_ssid, "first-network") == 0);

    memory.fail_meta_write = true;
    assert(ainekio_config_store_commit(&store) == AINEKIO_STORE_IO_ERROR);
    assert(store.meta.active_slot == AINEKIO_CONFIG_SLOT_A);
    assert(strcmp(store.active.wifi_ssid, "first-network") == 0);

    memory.fail_meta_write = false;
    assert(ainekio_config_store_commit(&store) == AINEKIO_STORE_OK);
    assert(store.meta.active_slot == AINEKIO_CONFIG_SLOT_B);
    assert(strcmp(store.active.wifi_ssid, "second-network") == 0);
    assert(strcmp(store.active.robot_token, "secret-token") == 0);
}

static void test_failed_stage_and_network_reset_preserve_non_wifi_values(void)
{
    memory_store_t memory = {0};
    const ainekio_config_store_port_t storage_port = port(&memory);
    ainekio_config_store_t store;
    ainekio_config_store_init(&store, &storage_port);
    const ainekio_config_record_t record = initial_record();
    assert(ainekio_config_store_stage_initial(&store, &record) == AINEKIO_STORE_OK);
    assert(ainekio_config_store_commit(&store) == AINEKIO_STORE_OK);

    memory.corrupt_readback = true;
    assert(ainekio_config_store_stage_network(
               &store,
               "bad-network",
               "bad-password"
           ) == AINEKIO_STORE_CORRUPT);
    assert(strcmp(store.active.wifi_ssid, "first-network") == 0);
    memory.corrupt_readback = false;

    assert(ainekio_config_store_stage_network_reset(&store) == AINEKIO_STORE_OK);
    assert(ainekio_config_store_commit(&store) == AINEKIO_STORE_OK);
    assert(store.active.wifi_ssid[0] == '\0');
    assert(store.active.wifi_psk[0] == '\0');
    assert(strcmp(store.active.endpoint_url, record.endpoint_url) == 0);
    assert(strcmp(store.active.robot_id, record.robot_id) == 0);
    assert(strcmp(store.active.robot_token, record.robot_token) == 0);

    ainekio_config_store_t reloaded;
    ainekio_config_store_init(&reloaded, &storage_port);
    assert(ainekio_config_store_load(&reloaded) == AINEKIO_CONFIG_LOAD_NO_WIFI);
}

static void test_bounds_and_corrupt_metadata_fail_closed(void)
{
    memory_store_t memory = {0};
    const ainekio_config_store_port_t storage_port = port(&memory);
    ainekio_config_store_t store;
    ainekio_config_store_init(&store, &storage_port);
    ainekio_config_record_t record = initial_record();
    memset(record.wifi_ssid, 'x', sizeof(record.wifi_ssid));
    assert(!ainekio_config_record_valid(&record, true));
    assert(ainekio_config_store_stage_initial(&store, &record) == AINEKIO_STORE_CORRUPT);

    memory.has_meta = true;
    memory.meta.schema_version = 99U;
    memory.meta.active_slot = AINEKIO_CONFIG_SLOT_A;
    assert(
        ainekio_config_store_load(&store) ==
        AINEKIO_CONFIG_LOAD_SCHEMA_MISMATCH
    );
    assert(memory.meta.schema_version == 99U);
}

static void test_legacy_schema_migrates_without_losing_wifi(void)
{
    memory_store_t memory = {0};
    memory.has_meta = true;
    memory.meta.schema_version = 0U;
    memory.meta.active_slot = AINEKIO_CONFIG_SLOT_A;
    memory.has_record[0] = true;
    memory.records[0] = initial_record();
    memory.records[0].schema_version = 0U;
    const ainekio_config_store_port_t storage_port = port(&memory);
    ainekio_config_store_t store;
    ainekio_config_store_init(&store, &storage_port);

    assert(ainekio_config_store_load(&store) == AINEKIO_CONFIG_LOAD_MIGRATED);
    assert(store.meta.schema_version == AINEKIO_NVS_SCHEMA_VERSION);
    assert(store.meta.active_slot == AINEKIO_CONFIG_SLOT_B);
    assert(strcmp(store.active.wifi_ssid, "first-network") == 0);
    assert(strcmp(store.active.wifi_psk, "first-password") == 0);
    assert(strcmp(store.active.robot_token, "secret-token") == 0);
}

int main(void)
{
    test_initial_commit_and_reload();
    test_network_replacement_commits_only_after_meta_switch();
    test_failed_stage_and_network_reset_preserve_non_wifi_values();
    test_bounds_and_corrupt_metadata_fail_closed();
    test_legacy_schema_migrates_without_losing_wifi();
    puts("ainekio config store tests passed");
    return 0;
}
