#pragma once
#include "../body_shim/esp_err.h"
#define ESP_ERR_NOT_FOUND 0x105
#define ESP_ERR_INVALID_SIZE 0x104
const char *esp_err_to_name(esp_err_t error);
