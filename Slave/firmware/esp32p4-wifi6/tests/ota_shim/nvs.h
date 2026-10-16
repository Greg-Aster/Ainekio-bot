#pragma once
#include "../config_shim/nvs.h"
#include <stdint.h>
esp_err_t nvs_get_u32(nvs_handle_t, const char *, uint32_t *);
esp_err_t nvs_set_u32(nvs_handle_t, const char *, uint32_t);
