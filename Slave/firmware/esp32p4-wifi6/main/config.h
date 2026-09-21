#pragma once

#include "ainekio/config_store.h"
#include "esp_err.h"

esp_err_t ainekio_p4_config_init(void);
const ainekio_config_record_t *ainekio_p4_config(void);
int ainekio_p4_config_command(int argc, char **argv);
