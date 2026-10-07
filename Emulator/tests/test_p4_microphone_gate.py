"""Exercise the actual P4 microphone loop across speaker/inference races."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media"


def function(source, declaration):
    start = source.index(declaration)
    return source[start:source.index("\n}", start) + 2]


class P4MicrophoneGateTests(unittest.TestCase):
    def test_playback_discards_inflight_detection_history_and_preroll(self):
        source = (MEDIA / "media.c").read_text()
        harness = r'''
#include <assert.h>
#include <setjmp.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "ainekio/p4_media.h"
#include "ainekio/platform/wake_word_service.h"
#define FRAME_SAMPLES 320
#define AMP_PIN 53
#define portMAX_DELAY 0
#define pdMS_TO_TICKS(x) (x)
#define VAD_SPEECH 1
static ainekio_p4_media_callbacks_t callbacks;
static ainekio_p4_media_status_t status = {.microphone_ready=true,.speaker_ready=true,.wake_enabled=true};
static void *mutex=(void*)1, *wake_mutex=(void*)2, *speaker_queue=(void*)3, *rx=(void*)4, *vad=(void*)5;
static ainekio_wake_word_service_t *wake=(ainekio_wake_word_service_t*)6;
static bool microphone_enabled=true, suspended, ending, buffering, dma_dirty;
static ainekio_microphone_gate_t microphone_gate=AINEKIO_MIC_GATE_WAKE;
static uint32_t microphone_epoch=1, generation, sequence, asset_remaining;
static uint64_t session=42, audio_session;
static int64_t microphone_after, last_speaker_input, clock_us, microphone_sample_at;
static FILE *asset_file;
static atomic_bool audio_tasks_started=true;
static unsigned input_frame, resets, wake_frames, opens, closes, pcm_frames, mutex_depth;
static jmp_buf finished;
static int xSemaphoreTake(void *m,unsigned timeout) { (void)timeout;if(m==mutex)assert(mutex_depth++==0);return 1; }
static int xSemaphoreGive(void *m) { if(m==mutex)assert(mutex_depth--==1);return 1; }
static void xQueueReset(void *q) { assert(q==speaker_queue); }
static void gpio_set_level(int pin,int value) { assert(pin==AMP_PIN);(void)value; }
static int64_t esp_timer_get_time(void) { return clock_us; }
static void vTaskDelay(unsigned ms) { clock_us+=ms*1000; }
'''
        harness += function(source, "static void audio_finish(")
        harness += function(source, "esp_err_t ainekio_p4_media_tts_start(")
        harness += r'''
void ainekio_wake_word_reset(ainekio_wake_word_service_t *w) { assert(w==wake);resets++; }
ainekio_wake_word_result_t ainekio_wake_word_process(ainekio_wake_word_service_t *w,const int16_t *pcm,size_t n)
{
    assert(w==wake && pcm && n==320);
    assert(!status.speaker_busy && clock_us>=microphone_after);
    assert(input_frame<4 || input_frame>=49);wake_frames++;
    if(input_frame==3) {
        /* Playback starts while a previous wake inference is still running. */
        assert(ainekio_p4_media_tts_start(1)==ESP_OK);
        return AINEKIO_WAKE_WORD_DETECTED;
    }
    if(input_frame==50) {
        assert(resets>=3); /* Initial session, playback start, playback end. */
        return AINEKIO_WAKE_WORD_DETECTED;
    }
    return AINEKIO_WAKE_WORD_LISTENING;
}
static int vad_process(void *v,const int16_t *pcm,int rate,int ms)
{ assert(v==vad && pcm && rate==16000 && ms==20);return 0; }
static int i2s_channel_read(void *channel,void *out,size_t size,size_t *received,unsigned timeout)
{
    assert(channel==rx && size==640 && timeout==40 && mutex_depth==0);
    input_frame++;clock_us+=20000;
    if(input_frame==60)longjmp(finished,1);
    if(input_frame==9) {
        xSemaphoreTake(mutex,0);audio_finish(ESP_OK);
        assert(microphone_after==clock_us+800000);
    }
    if(input_frame==53)assert(ainekio_p4_media_tts_start(2)==ESP_OK);
    int16_t *pcm=out;
    for(unsigned i=0;i<320;i++)pcm[i]=(int16_t)input_frame;
    *received=size;return ESP_OK;
}
static void gate(void *context,uint64_t id,bool open,bool detected)
{
    (void)context;assert(id==42);
    if(open) {
        assert(input_frame==50 && detected && mutex_depth==1);
        assert(status.utterance_open && !status.speaker_busy);opens++;
    } else {
        assert(input_frame==53 && !detected && !status.utterance_open);closes++;
    }
}
static void pcm(void *context,uint64_t id,const uint8_t *bytes)
{
    (void)context;assert(id==42 && mutex_depth==1);
    assert(!status.speaker_busy && clock_us>=microphone_after);
    int16_t sample;memcpy(&sample,bytes,sizeof sample);
    assert(sample>=49 && sample<=52); /* No playback/cooldown pre-roll leaked. */
    pcm_frames++;
}
'''
        harness += function(source, "static void microphone_task(")
        harness += r'''
int main(void)
{
    callbacks.gate=gate;callbacks.microphone=pcm;
    if(!setjmp(finished))microphone_task(NULL);
    assert(mutex_depth==0 && opens==1 && closes==1 && pcm_frames==4);
    assert(wake_frames==4 && resets>=4 && !status.utterance_open);
    puts("In-flight wake, playback, cooldown, fresh resume, pre-roll and recording close passed.");
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-mic-gate-") as work:
            path = Path(work) / "gate.c"
            binary = Path(work) / "gate"
            path.write_text(harness)
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(path), "-lm",
                "-I", str(MEDIA / "include"),
                "-I", str(ROOT / "Slave/firmware/esp32p4-wifi6/tests/body_shim"),
                "-I", str(ROOT / "Slave/firmware/components/ainekio_wake/include"),
                "-I", str(ROOT / "Slave/software/core/include"), "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)
