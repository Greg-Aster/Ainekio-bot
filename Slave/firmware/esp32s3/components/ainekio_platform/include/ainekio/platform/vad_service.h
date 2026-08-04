#ifndef AINEKIO_PLATFORM_VAD_SERVICE_H
#define AINEKIO_PLATFORM_VAD_SERVICE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct ainekio_vad_service ainekio_vad_service_t;

typedef enum {
    AINEKIO_VAD_PENDING = 0,
    AINEKIO_VAD_SILENCE,
    AINEKIO_VAD_SPEECH,
    AINEKIO_VAD_ERROR,
} ainekio_vad_result_t;

esp_err_t ainekio_vad_service_start(ainekio_vad_service_t **service);
void ainekio_vad_service_stop(ainekio_vad_service_t *service);
bool ainekio_vad_ready(const ainekio_vad_service_t *service);
void ainekio_vad_reset(ainekio_vad_service_t *service);
ainekio_vad_result_t ainekio_vad_process(
    ainekio_vad_service_t *service,
    const int16_t *samples,
    size_t sample_count
);

#endif
