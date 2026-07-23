#ifndef AINEKIO_CONFIG_STORE_H
#define AINEKIO_CONFIG_STORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/config_schema.h"

#define AINEKIO_WIFI_SSID_BYTES 33U
#define AINEKIO_WIFI_PSK_BYTES 65U
#define AINEKIO_TRANSPORT_MODE_BYTES 8U
#define AINEKIO_ENDPOINT_URL_BYTES 256U
#define AINEKIO_ROBOT_ID_BYTES 65U
#define AINEKIO_ROBOT_TOKEN_BYTES 129U

typedef struct {
    uint32_t schema_version;
    uint32_t generation;
    bool complete;
    char wifi_ssid[AINEKIO_WIFI_SSID_BYTES];
    char wifi_psk[AINEKIO_WIFI_PSK_BYTES];
    char transport_mode[AINEKIO_TRANSPORT_MODE_BYTES];
    char endpoint_url[AINEKIO_ENDPOINT_URL_BYTES];
    char robot_id[AINEKIO_ROBOT_ID_BYTES];
    char robot_token[AINEKIO_ROBOT_TOKEN_BYTES];
} ainekio_config_record_t;

typedef struct {
    uint32_t schema_version;
    ainekio_config_slot_t active_slot;
} ainekio_config_meta_t;

typedef enum {
    AINEKIO_STORE_OK = 0,
    AINEKIO_STORE_NOT_FOUND,
    AINEKIO_STORE_CORRUPT,
    AINEKIO_STORE_IO_ERROR,
} ainekio_store_result_t;

typedef struct {
    void *context;
    ainekio_store_result_t (*read_meta)(void *context, ainekio_config_meta_t *meta);
    ainekio_store_result_t (*write_meta)(void *context, const ainekio_config_meta_t *meta);
    ainekio_store_result_t (*read_record)(
        void *context,
        ainekio_config_slot_t slot,
        ainekio_config_record_t *record
    );
    ainekio_store_result_t (*write_record)(
        void *context,
        ainekio_config_slot_t slot,
        const ainekio_config_record_t *record
    );
    ainekio_store_result_t (*erase_record)(void *context, ainekio_config_slot_t slot);
} ainekio_config_store_port_t;

typedef enum {
    AINEKIO_CONFIG_LOAD_VALID = 0,
    AINEKIO_CONFIG_LOAD_MIGRATED,
    AINEKIO_CONFIG_LOAD_NO_WIFI,
    AINEKIO_CONFIG_LOAD_MISSING,
    AINEKIO_CONFIG_LOAD_CORRUPT,
    AINEKIO_CONFIG_LOAD_SCHEMA_MISMATCH,
    AINEKIO_CONFIG_LOAD_IO_ERROR,
} ainekio_config_load_result_t;

typedef struct {
    ainekio_config_store_port_t port;
    ainekio_config_meta_t meta;
    ainekio_config_record_t active;
    ainekio_config_slot_t staged_slot;
    bool has_active;
    bool has_staged;
} ainekio_config_store_t;

void ainekio_config_store_init(
    ainekio_config_store_t *store,
    const ainekio_config_store_port_t *port
);
ainekio_config_load_result_t ainekio_config_store_load(ainekio_config_store_t *store);
bool ainekio_config_record_valid(const ainekio_config_record_t *record, bool require_wifi);
ainekio_store_result_t ainekio_config_store_stage_initial(
    ainekio_config_store_t *store,
    const ainekio_config_record_t *candidate
);
ainekio_store_result_t ainekio_config_store_stage_network(
    ainekio_config_store_t *store,
    const char *ssid,
    const char *psk
);
ainekio_store_result_t ainekio_config_store_stage_network_reset(
    ainekio_config_store_t *store
);
ainekio_store_result_t ainekio_config_store_commit(ainekio_config_store_t *store);
ainekio_store_result_t ainekio_config_store_discard(ainekio_config_store_t *store);

#endif
