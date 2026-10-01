#pragma once
#include "esp_err.h"
#include <stdint.h>
typedef void *i2c_master_bus_handle_t;
esp_err_t i2c_master_probe(i2c_master_bus_handle_t bus, uint16_t address, int timeout_ms);
