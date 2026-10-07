"""Exercise speaker DMA handoff while receive/cancel callbacks run concurrently."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from .test_p4_microphone_gate import MEDIA, ROOT, function


class P4SpeakerHandoffTests(unittest.TestCase):
    def test_receive_and_cancel_during_dma_write(self):
        source = (MEDIA / "media.c").read_text()
        harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "ainekio/p4_media.h"
#define AMP_PIN 53
#define portMAX_DELAY 0
#define pdTRUE 1
typedef struct { uint32_t generation; uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES]; } audio_frame_t;
static ainekio_p4_media_callbacks_t callbacks;
static ainekio_p4_media_status_t status = {.speaker_ready=true,.speaker_volume_percent=100};
static void *mutex=(void*)1, *speaker_queue=(void*)2, *tx=(void*)3;
static bool suspended, ending, buffering, dma_dirty;
static uint32_t generation, sequence, asset_remaining, microphone_epoch;
static uint64_t session=42, audio_session;
static int64_t microphone_after, last_speaker_input;
static FILE *asset_file;
static unsigned mutex_depth, mode, queued, completions, amp;
static uint32_t completed_sequence;
static int xSemaphoreTake(void *m,unsigned timeout) { (void)timeout;assert(m==mutex && mutex_depth++==0);return 1; }
static int xSemaphoreGive(void *m) { assert(m==mutex && mutex_depth--==1);return 1; }
static void xQueueReset(void *q) { assert(q==speaker_queue);queued=0; }
static int xQueueSend(void *q,const audio_frame_t *f,unsigned timeout)
{ assert(q==speaker_queue && f->generation==generation && timeout==0);queued++;return pdTRUE; }
static void gpio_set_level(int pin,int value) { assert(pin==AMP_PIN);amp=value; }
static int64_t esp_timer_get_time(void) { return 1000000; }
static esp_err_t i2s_channel_write(void *,const void *,size_t,size_t *,unsigned);
'''
        for declaration in (
            "static void audio_finish(",
            "static void speaker_write_frame(",
            "esp_err_t ainekio_p4_media_tts_start(",
            "esp_err_t ainekio_p4_media_tts_push(",
            "uint32_t ainekio_p4_media_audio_cancel(",
        ):
            harness += function(source, declaration)
        harness += r'''
static esp_err_t i2s_channel_write(void *channel,const void *data,size_t size,size_t *written,unsigned timeout)
{
    assert(channel==tx && size==640 && timeout==60);
    assert(mutex_depth==0); /* WebSocket receive must not wait on speaker DMA. */
    if(mode==0)assert(ainekio_p4_media_tts_push(data)==ESP_OK);
    if(mode==1) {
        assert(ainekio_p4_media_audio_cancel()==11 && amp==0 && dma_dirty);
        assert(ainekio_p4_media_tts_start(22)==ESP_OK);
        assert(amp==0); /* New playback may not unmute old DMA. */
    }
    *written=mode ? 0 : size;
    return mode ? ESP_ERR_TIMEOUT : ESP_OK;
}
static void done(void *context,uint64_t s,uint32_t id,esp_err_t result)
{
    (void)context;assert(mutex_depth==0 && s==42 && result==ESP_ERR_TIMEOUT);
    assert(!status.speaker_busy && amp==0 && dma_dirty);
    completions++;completed_sequence=id;
}
int main(void)
{
    callbacks.audio_done=done;
    assert(ainekio_p4_media_tts_start(11)==ESP_OK);
    audio_frame_t frame={.generation=generation};
    xSemaphoreTake(mutex,0);speaker_write_frame(&frame);
    assert(mutex_depth==0 && queued==1 && completions==0 && sequence==11);
    mode=1;
    xSemaphoreTake(mutex,0);speaker_write_frame(&frame);
    assert(mutex_depth==0 && completions==0 && sequence==22 && status.speaker_busy);
    assert(generation!=frame.generation && amp==0);
    mode=2;frame.generation=generation;
    xSemaphoreTake(mutex,0);speaker_write_frame(&frame);
    assert(mutex_depth==0 && completions==1 && completed_sequence==22);
    puts("Concurrent receive, cancellation, replacement and current-generation failure passed.");
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-speaker-handoff-") as work:
            path = Path(work) / "speaker.c"
            binary = Path(work) / "speaker"
            path.write_text(harness)
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(path),
                "-I", str(MEDIA / "include"),
                "-I", str(ROOT / "Slave/firmware/esp32p4-wifi6/tests/body_shim"),
                "-I", str(ROOT / "Slave/software/core/include"), "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)
