#include "ainekio/audio_endpoint.h"

#include <stddef.h>
#include <string.h>

void ainekio_audio_endpoint_init(ainekio_audio_endpoint_t *endpoint)
{
    if (endpoint != NULL) {
        memset(endpoint, 0, sizeof(*endpoint));
    }
}

void ainekio_audio_endpoint_begin(ainekio_audio_endpoint_t *endpoint)
{
    if (endpoint == NULL) {
        return;
    }
    endpoint->active_frames = 0U;
    endpoint->active = true;
}

ainekio_audio_endpoint_result_t ainekio_audio_endpoint_update(
    ainekio_audio_endpoint_t *endpoint,
    ainekio_audio_activity_t activity
)
{
    if (endpoint == NULL || !endpoint->active) {
        return AINEKIO_AUDIO_ENDPOINT_SILENCE;
    }
    if (endpoint->active_frames < UINT16_MAX) {
        ++endpoint->active_frames;
    }
    if (endpoint->active_frames >= AINEKIO_WAKE_ENDPOINT_MAX_FRAMES) {
        endpoint->active = false;
        return AINEKIO_AUDIO_ENDPOINT_MAXIMUM;
    }
    if (endpoint->active_frames >= AINEKIO_WAKE_ENDPOINT_MIN_FRAMES &&
        activity == AINEKIO_AUDIO_ACTIVITY_SILENCE) {
        endpoint->active = false;
        return AINEKIO_AUDIO_ENDPOINT_SILENCE;
    }
    return AINEKIO_AUDIO_ENDPOINT_ACTIVE;
}

void ainekio_audio_endpoint_cancel(ainekio_audio_endpoint_t *endpoint)
{
    if (endpoint == NULL) {
        return;
    }
    endpoint->active_frames = 0U;
    endpoint->active = false;
}
