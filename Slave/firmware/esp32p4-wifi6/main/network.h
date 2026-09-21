#pragma once

#include <stdbool.h>
#include "esp_err.h"

esp_err_t ainekio_p4_network_start(void);
bool ainekio_p4_network_online(void);
int ainekio_p4_network_command(int argc, char **argv);
