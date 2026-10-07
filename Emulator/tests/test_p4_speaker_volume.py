"""Run the actual P4 persistence and final PCM-output functions with host I/O."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from .test_p4_microphone_gate import MEDIA, ROOT, function


class P4SpeakerVolumeTests(unittest.TestCase):
    def test_saved_volume_reboot_failure_and_actual_output_scaling(self):
        source = (MEDIA / "media.c").read_text()
        harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "ainekio/p4_media.h"
#define portMAX_DELAY 0
#define AMP_PIN 53
#define NVS_READONLY 0
#define NVS_READWRITE 1
typedef int nvs_handle_t;
typedef struct { uint32_t generation; uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES]; } audio_frame_t;
static ainekio_p4_media_status_t status={.speaker_ready=true,.speaker_busy=true};
static void *mutex=(void*)1,*tx=(void*)2;
static bool speaker_volume_saved,stored,fail_save;
static uint8_t saved,pending;
static uint32_t generation=9;
static unsigned commits,mutex_depth,expected_volume=100,writes;
static int16_t input[320];
static int xSemaphoreTake(void *m,unsigned t) { (void)t;assert(m==mutex && mutex_depth++==0);return 1; }
static int xSemaphoreGive(void *m) { assert(m==mutex && mutex_depth--==1);return 1; }
static int nvs_open(const char *name,int mode,nvs_handle_t *h)
{ assert(!strcmp(name,"p4_media"));*h=mode;return ESP_OK; }
static void nvs_close(nvs_handle_t h) { (void)h; }
static int nvs_get_u8(nvs_handle_t h,const char *key,uint8_t *v)
{ assert(h==0 && !strcmp(key,"spk_volume"));if(!stored)return ESP_FAIL;*v=saved;return ESP_OK; }
static int nvs_set_u8(nvs_handle_t h,const char *key,uint8_t v)
{ assert(h==1 && !strcmp(key,"spk_volume"));pending=v;return ESP_OK; }
static int nvs_commit(nvs_handle_t h)
{ assert(h==1);if(fail_save)return ESP_FAIL;commits++;stored=true;saved=pending;return ESP_OK; }
static void gpio_set_level(int pin,int value) { assert(pin==AMP_PIN && value==1); }
static void audio_finish(esp_err_t result) { (void)result;assert(!"Unexpected playback failure"); }
static esp_err_t i2s_channel_write(void *channel,const void *data,size_t size,size_t *written,unsigned timeout)
{
    assert(channel==tx && size==sizeof(input) && timeout==60 && mutex_depth==0);
    for(unsigned i=0;i<320;i++) {
        int16_t sample;memcpy(&sample,(const uint8_t*)data+i*2,2);
        assert(sample==(int16_t)((int32_t)input[i]*(int32_t)expected_volume/100));
    }
    if(expected_volume==100)assert(!memcmp(input,data,size));
    writes++;*written=size;return ESP_OK;
}
'''
        for declaration in (
            "static void load_speaker_volume(",
            "esp_err_t ainekio_p4_media_speaker_volume(",
            "static void speaker_write_frame(",
        ):
            harness += function(source, declaration)
        harness += r'''
static void reboot(void)
{ speaker_volume_saved=false;status.speaker_volume_percent=0;load_speaker_volume(); }
static void play(unsigned volume)
{
    expected_volume=volume;audio_frame_t frame={.generation=generation};
    for(unsigned i=0;i<320;i++)input[i]=(int16_t)((int)i*203-32768);
    input[0]=INT16_MIN;input[1]=INT16_MAX;input[2]=0;input[3]=-1;input[4]=1;
    memcpy(frame.pcm,input,sizeof(input));
    xSemaphoreTake(mutex,0);speaker_write_frame(&frame);
    assert(mutex_depth==0 && status.speaker_busy && generation==9);
}
int main(void)
{
    reboot();assert(status.speaker_volume_percent==100 && !speaker_volume_saved);play(100);
    for(unsigned v=0;v<=100;v++) {
        assert(ainekio_p4_media_speaker_volume(v)==ESP_OK);
        assert(status.speaker_volume_percent==v && speaker_volume_saved);
        play(v);reboot();assert(status.speaker_volume_percent==v);play(v);
        unsigned before=commits;
        assert(ainekio_p4_media_speaker_volume(v)==ESP_OK && commits==before);
    }
    fail_save=true;
    assert(ainekio_p4_media_speaker_volume(25)==ESP_FAIL);
    assert(status.speaker_volume_percent==100);play(100);reboot();play(100);
    assert(ainekio_p4_media_speaker_volume(101)==ESP_ERR_INVALID_ARG);
    assert(ainekio_p4_media_speaker_volume(255)==ESP_ERR_INVALID_ARG);
    assert(writes==205 && commits==101 && mutex_depth==0);
    puts("All 101 levels, mute, full-scale identity, persistence and failed-save behavior passed.");
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-speaker-volume-") as work:
            path = Path(work) / "volume.c"
            binary = Path(work) / "volume"
            path.write_text(harness)
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(path),
                "-I", str(MEDIA / "include"),
                "-I", str(ROOT / "Slave/firmware/esp32p4-wifi6/tests/body_shim"),
                "-I", str(ROOT / "Slave/software/core/include"), "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)
