#pragma once

#include "esp_err.h"

esp_err_t ainekio_p4_controller_start(void);
void ainekio_p4_controller_supervise(void);
void ainekio_p4_controller_quiesce(void);
int ainekio_p4_controller_command(int argc, char **argv);
int ainekio_p4_gait_command(int argc, char **argv);
