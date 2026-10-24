#pragma once

#include <stdbool.h>
#include "esp_err.h"
#include "connection_screen.h"

ainekio_connection_gateway_t ainekio_p4_controller_display_status(void);

esp_err_t ainekio_p4_controller_start(void);
esp_err_t ainekio_p4_controller_media_start(void);
void ainekio_p4_controller_supervise(void);
/* Retire the transport session without releasing powered body outputs. */
void ainekio_p4_controller_connection_lost(void);
bool ainekio_p4_controller_transport_active(void);
void ainekio_p4_controller_quiesce(void);
int ainekio_p4_controller_command(int argc, char **argv);
int ainekio_p4_home_command(int argc, char **argv);
int ainekio_p4_gait_command(int argc, char **argv);
