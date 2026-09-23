#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "ainekio/assets.h"
#include "esp_err.h"

#define AINEKIO_P4_ASSET_ROOT "/assets"
typedef struct {
    char name[AINEKIO_ASSET_NAME_MAX + 1];
    char path[96];
    uint32_t samples;
} ainekio_p4_audio_asset_t;

typedef struct { bool mounted; uint8_t audio; uint16_t unavailable; } ainekio_p4_assets_status_t;

/* Call once before media startup. Missing partition/files are reported, never
 * formatted and never gate servo startup. Published indexes are immutable. */
esp_err_t ainekio_p4_assets_init(void);
ainekio_p4_assets_status_t ainekio_p4_assets_status(void);
const ainekio_p4_audio_asset_t *ainekio_p4_assets_audio(const char *name);
