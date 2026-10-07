#pragma once
#include <stdint.h>
#include "connection_screen.h"

ainekio_connection_network_t ainekio_p4_network_display_status(void);

int ainekio_p4_network_index(void);
uint32_t ainekio_p4_network_generation(void);
const char *ainekio_p4_network_endpoint(void);

#include <stdbool.h>
#include "esp_err.h"

esp_err_t ainekio_p4_network_start(void);
/* Persist the setup identity before PWM starts; does not open the network. */
esp_err_t ainekio_p4_network_prepare(void);
bool ainekio_p4_network_online(void);
bool ainekio_p4_network_setup_active(void);
bool ainekio_p4_network_initialized(void);
esp_err_t ainekio_p4_network_setup(void);
esp_err_t ainekio_p4_network_retry(void);
esp_err_t ainekio_p4_network_reset(void);
void ainekio_p4_network_suspend(void);
int ainekio_p4_network_command(int argc, char **argv);
