#ifndef AINEKIO_AUDIO_ENDPOINT_H
#define AINEKIO_AUDIO_ENDPOINT_H

#include <stdbool.h>
#include <stdint.h>

#define AINEKIO_WAKE_ENDPOINT_MIN_FRAMES 50U
#define AINEKIO_WAKE_ENDPOINT_MAX_FRAMES 750U

typedef enum {
    AINEKIO_AUDIO_ACTIVITY_PENDING = 0,
    AINEKIO_AUDIO_ACTIVITY_SILENCE,
    AINEKIO_AUDIO_ACTIVITY_SPEECH,
} ainekio_audio_activity_t;

typedef enum {
    AINEKIO_AUDIO_ENDPOINT_ACTIVE = 0,
    AINEKIO_AUDIO_ENDPOINT_SILENCE,
    AINEKIO_AUDIO_ENDPOINT_MAXIMUM,
} ainekio_audio_endpoint_result_t;

typedef struct {
    uint16_t active_frames;
    bool active;
} ainekio_audio_endpoint_t;

void ainekio_audio_endpoint_init(ainekio_audio_endpoint_t *endpoint);
void ainekio_audio_endpoint_begin(ainekio_audio_endpoint_t *endpoint);
ainekio_audio_endpoint_result_t ainekio_audio_endpoint_update(
    ainekio_audio_endpoint_t *endpoint,
    ainekio_audio_activity_t activity
);
void ainekio_audio_endpoint_cancel(ainekio_audio_endpoint_t *endpoint);

#endif
