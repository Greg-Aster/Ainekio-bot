#pragma once
#include <stdbool.h>
#include "esp_err.h"
#include "esp_http_server.h"
#include "connection_screen.h"

bool ainekio_p4_ota_busy(void);
esp_err_t ainekio_p4_maintenance_register(httpd_handle_t server);
/* Called at the existing authenticated startup acceptance point. */
esp_err_t ainekio_p4_ota_startup_check(void);
void ainekio_p4_ota_accepted(void);
/* Overlay only; display task remains the sole panel owner. */
bool ainekio_p4_ota_page(ainekio_connection_page_t *page);
