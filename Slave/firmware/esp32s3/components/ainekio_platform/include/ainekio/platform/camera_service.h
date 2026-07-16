#ifndef AINEKIO_PLATFORM_CAMERA_SERVICE_H
#define AINEKIO_PLATFORM_CAMERA_SERVICE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/protocol.h"
#include "esp_err.h"

typedef struct ainekio_camera_service ainekio_camera_service_t;

typedef struct {
    void *context;
    void (*frame)(
        void *context,
        bool snapshot,
        uint32_t sequence,
        ainekio_camera_resolution_t resolution,
        uint32_t counter,
        const uint8_t *jpeg,
        size_t length
    );
    void (*failed)(void *context, bool snapshot, uint32_t sequence);
} ainekio_camera_callbacks_t;

esp_err_t ainekio_camera_service_start(
    const ainekio_camera_callbacks_t *callbacks,
    ainekio_camera_service_t **service
);
esp_err_t ainekio_camera_configure(
    ainekio_camera_service_t *service,
    bool enabled,
    uint8_t fps,
    ainekio_camera_resolution_t resolution
);
esp_err_t ainekio_camera_snapshot(
    ainekio_camera_service_t *service,
    uint32_t sequence
);
uint32_t ainekio_camera_counter_base(
    const ainekio_camera_service_t *service
);

#endif
