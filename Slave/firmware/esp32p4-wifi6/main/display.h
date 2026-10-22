#pragma once
#include <stdbool.h>
#include "esp_err.h"
#include "ainekio/protocol.h"

/* One display task owns SPI and all panel calls. Never writes body outputs. */
esp_err_t ainekio_p4_display_start(void);
bool ainekio_p4_display_ready(void);
const char *ainekio_p4_display_face(void);
/* Active selection identity, including while a temporary overlay covers it. */
void ainekio_p4_display_token(uint64_t at_ms, char token[AINEKIO_ASSET_NAME_MAX + 1U]);
esp_err_t ainekio_p4_display_expression(const char *name);
esp_err_t ainekio_p4_display_select(const ainekio_face_selection_t *request);
void ainekio_p4_display_restore(void);
int ainekio_p4_display_command(int argc,char **argv);
