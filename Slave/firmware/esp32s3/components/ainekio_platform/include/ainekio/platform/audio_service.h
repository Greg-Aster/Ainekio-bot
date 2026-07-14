#ifndef AINEKIO_PLATFORM_AUDIO_SERVICE_H
#define AINEKIO_PLATFORM_AUDIO_SERVICE_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/binary_codec.h"
#include "ainekio/platform/asset_store.h"
#include "ainekio/protocol.h"
#include "esp_err.h"

typedef struct ainekio_audio_service ainekio_audio_service_t;

typedef enum {
    AINEKIO_AUDIO_OK = 0,
    AINEKIO_AUDIO_BUSY,
    AINEKIO_AUDIO_ORPHAN,
    AINEKIO_AUDIO_OVERFLOW,
    AINEKIO_AUDIO_ASSET_MISSING,
    AINEKIO_AUDIO_IO_ERROR,
} ainekio_audio_result_t;

typedef void (*ainekio_audio_done_fn)(void *context, uint32_t sequence);
typedef void (*ainekio_audio_failed_fn)(
    void *context,
    uint32_t sequence,
    bool overflow
);
typedef void (*ainekio_audio_mic_fn)(
    void *context,
    const uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES]
);
typedef void (*ainekio_audio_gate_fn)(
    void *context,
    bool open,
    bool wake_word
);

typedef struct {
    void *context;
    ainekio_audio_done_fn done;
    ainekio_audio_failed_fn failed;
    ainekio_audio_mic_fn microphone;
    ainekio_audio_gate_fn gate;
} ainekio_audio_callbacks_t;

esp_err_t ainekio_audio_service_start(
    ainekio_asset_store_t *assets,
    const ainekio_audio_callbacks_t *callbacks,
    ainekio_audio_service_t **service
);
ainekio_audio_result_t ainekio_audio_tts_start(
    ainekio_audio_service_t *service,
    uint32_t sequence
);
ainekio_audio_result_t ainekio_audio_tts_end(ainekio_audio_service_t *service);
uint32_t ainekio_audio_cancel(ainekio_audio_service_t *service);
bool ainekio_audio_busy(const ainekio_audio_service_t *service);
ainekio_audio_result_t ainekio_audio_push_speaker(
    ainekio_audio_service_t *service,
    const uint8_t payload[AINEKIO_AUDIO_PAYLOAD_BYTES]
);
ainekio_audio_result_t ainekio_audio_say(
    ainekio_audio_service_t *service,
    uint32_t sequence,
    const char *asset_name
);
ainekio_audio_result_t ainekio_audio_play_cue(
    ainekio_audio_service_t *service,
    const char *asset_name
);
void ainekio_audio_set_microphone(
    ainekio_audio_service_t *service,
    bool enabled,
    ainekio_microphone_gate_t gate
);
uint32_t ainekio_audio_speaker_underruns(const ainekio_audio_service_t *service);
uint32_t ainekio_audio_microphone_drops(const ainekio_audio_service_t *service);

#endif
