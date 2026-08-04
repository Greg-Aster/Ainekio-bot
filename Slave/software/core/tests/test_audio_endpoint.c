#include <assert.h>
#include <stdio.h>

#include "ainekio/audio_endpoint.h"

static void test_classifier_silence_respects_minimum_capture(void)
{
    ainekio_audio_endpoint_t endpoint;
    ainekio_audio_endpoint_init(&endpoint);
    ainekio_audio_endpoint_begin(&endpoint);

    for (unsigned int frame = 0U;
         frame < AINEKIO_WAKE_ENDPOINT_MIN_FRAMES - 1U;
         ++frame) {
        assert(ainekio_audio_endpoint_update(
                   &endpoint,
                   AINEKIO_AUDIO_ACTIVITY_SILENCE
               ) == AINEKIO_AUDIO_ENDPOINT_ACTIVE);
    }
    assert(ainekio_audio_endpoint_update(
               &endpoint,
               AINEKIO_AUDIO_ACTIVITY_SILENCE
           ) == AINEKIO_AUDIO_ENDPOINT_SILENCE);
}

static void test_pending_and_speech_keep_capture_open(void)
{
    ainekio_audio_endpoint_t endpoint;
    ainekio_audio_endpoint_init(&endpoint);
    ainekio_audio_endpoint_begin(&endpoint);

    for (unsigned int frame = 0U; frame < 200U; ++frame) {
        const ainekio_audio_activity_t activity =
            frame % 2U == 0U ? AINEKIO_AUDIO_ACTIVITY_PENDING
                             : AINEKIO_AUDIO_ACTIVITY_SPEECH;
        assert(ainekio_audio_endpoint_update(&endpoint, activity) ==
               AINEKIO_AUDIO_ENDPOINT_ACTIVE);
    }
    assert(ainekio_audio_endpoint_update(
               &endpoint,
               AINEKIO_AUDIO_ACTIVITY_SILENCE
           ) == AINEKIO_AUDIO_ENDPOINT_SILENCE);
}

static void test_maximum_capture_is_absolute(void)
{
    ainekio_audio_endpoint_t endpoint;
    ainekio_audio_endpoint_init(&endpoint);
    ainekio_audio_endpoint_begin(&endpoint);

    for (unsigned int frame = 0U;
         frame < AINEKIO_WAKE_ENDPOINT_MAX_FRAMES - 1U;
         ++frame) {
        assert(ainekio_audio_endpoint_update(
                   &endpoint,
                   AINEKIO_AUDIO_ACTIVITY_SPEECH
               ) == AINEKIO_AUDIO_ENDPOINT_ACTIVE);
    }
    assert(ainekio_audio_endpoint_update(
               &endpoint,
               AINEKIO_AUDIO_ACTIVITY_SPEECH
           ) == AINEKIO_AUDIO_ENDPOINT_MAXIMUM);
}

static void test_cancel_requires_a_new_begin(void)
{
    ainekio_audio_endpoint_t endpoint;
    ainekio_audio_endpoint_init(&endpoint);
    ainekio_audio_endpoint_begin(&endpoint);
    ainekio_audio_endpoint_cancel(&endpoint);

    assert(ainekio_audio_endpoint_update(
               &endpoint,
               AINEKIO_AUDIO_ACTIVITY_SPEECH
           ) == AINEKIO_AUDIO_ENDPOINT_SILENCE);
}

int main(void)
{
    test_classifier_silence_respects_minimum_capture();
    test_pending_and_speech_keep_capture_open();
    test_maximum_capture_is_absolute();
    test_cancel_requires_a_new_begin();
    puts("ainekio audio endpoint tests passed");
    return 0;
}
