#ifndef AINEKIO_P4_MEDIA_H
#define AINEKIO_P4_MEDIA_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "ainekio/protocol.h"
#include "ainekio/binary_codec.h"

typedef struct {
    void *context;
    /* Callbacks run on media tasks. Copy data before returning; do not block. */
    void (*microphone)(void *context, uint64_t session, const uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES]);
    void (*audio_done)(void *context, uint64_t session, uint32_t sequence, esp_err_t result);
    void (*gate)(void *context, uint64_t session, bool open, bool wake_word);
    void (*camera_frame)(void *context, uint64_t session, ainekio_camera_origin_t origin,
                         uint32_t origin_id, ainekio_camera_resolution_t resolution,
                         uint32_t counter, const uint8_t *jpeg, size_t length);
    void (*camera_failed)(void *context, uint64_t session, ainekio_camera_origin_t origin,
                          uint32_t origin_id, esp_err_t result);
} ainekio_p4_media_callbacks_t;

typedef struct {
    bool microphone_ready, speaker_ready, camera_ready, display_ready;
    bool vad_ready, wake_ready, speaker_busy;
    bool wake_enabled;
    char wake_model[33];
    uint32_t microphone_drops, speaker_underruns, camera_failures;
} ainekio_p4_media_status_t;

/* Start after the body controller. Missing peripherals are reported individually;
 * no media initialization is allowed to gate the servo owner's startup. */
esp_err_t ainekio_p4_media_start(const ainekio_p4_media_callbacks_t *callbacks);
ainekio_p4_media_status_t ainekio_p4_media_status(void);
void ainekio_p4_media_session(uint64_t session);
esp_err_t ainekio_p4_media_wake_configure(bool enabled, const char *model);
esp_err_t ainekio_p4_media_microphone(bool enabled, ainekio_microphone_gate_t gate);
esp_err_t ainekio_p4_media_tts_start(uint32_t sequence);
esp_err_t ainekio_p4_media_say(uint32_t sequence, const char *asset_name);
esp_err_t ainekio_p4_media_tts_push(const uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES]);
esp_err_t ainekio_p4_media_tts_end(void);
uint32_t ainekio_p4_media_audio_cancel(void);
esp_err_t ainekio_p4_media_camera_configure(bool enabled, uint8_t fps,
                                           ainekio_camera_resolution_t resolution);
esp_err_t ainekio_p4_media_snapshot(ainekio_camera_origin_t origin, uint32_t origin_id);
void ainekio_p4_media_cancel_snapshots(void);
/* Cancel queued snapshots, streaming and audio on connection loss. */
void ainekio_p4_media_disconnect(void);
esp_err_t ainekio_p4_media_suspend(bool suspended);
#endif
