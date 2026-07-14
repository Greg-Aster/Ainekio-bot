#ifndef AINEKIO_PLATFORM_DISPLAY_SERVICE_H
#define AINEKIO_PLATFORM_DISPLAY_SERVICE_H

#include <stdbool.h>

#include "ainekio/assets.h"
#include "ainekio/platform/asset_store.h"
#include "esp_err.h"

typedef struct ainekio_display_service ainekio_display_service_t;

esp_err_t ainekio_display_service_start(
    ainekio_asset_store_t *assets,
    ainekio_display_service_t **service
);
esp_err_t ainekio_display_show_face(
    ainekio_display_service_t *service,
    const char *name,
    ainekio_face_mode_t mode,
    bool override_mode,
    bool remember
);
esp_err_t ainekio_display_show_status(
    ainekio_display_service_t *service,
    const char *line_1,
    const char *line_2,
    const char *line_3,
    const char *line_4
);
void ainekio_display_begin_talk(ainekio_display_service_t *service);
void ainekio_display_end_talk(ainekio_display_service_t *service);
void ainekio_display_set_idle(ainekio_display_service_t *service, bool idle);

#endif
