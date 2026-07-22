#ifndef AINEKIO_PLATFORM_WAKE_WORD_SERVICE_H
#define AINEKIO_PLATFORM_WAKE_WORD_SERVICE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/platform/asset_store.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ainekio_wake_word_service ainekio_wake_word_service_t;

typedef enum {
    AINEKIO_WAKE_WORD_LISTENING = 0,
    AINEKIO_WAKE_WORD_DETECTED,
    AINEKIO_WAKE_WORD_ERROR,
} ainekio_wake_word_result_t;

esp_err_t ainekio_wake_word_service_start(
    const ainekio_asset_store_t *assets,
    const char *model_id,
    ainekio_wake_word_service_t **service
);
void ainekio_wake_word_service_stop(ainekio_wake_word_service_t *service);
bool ainekio_wake_word_ready(const ainekio_wake_word_service_t *service);
const char *ainekio_wake_word_model(const ainekio_wake_word_service_t *service);
ainekio_wake_word_result_t ainekio_wake_word_process(
    ainekio_wake_word_service_t *service,
    const int16_t *samples,
    size_t sample_count
);
void ainekio_wake_word_reset(ainekio_wake_word_service_t *service);

#ifdef __cplusplus
}
#endif

#endif
