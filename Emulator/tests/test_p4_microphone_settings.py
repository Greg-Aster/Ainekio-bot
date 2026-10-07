"""Test the firmware's saved microphone preference across session/boot boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from .test_p4_microphone_gate import MEDIA, ROOT, function


class P4MicrophoneSettingsTests(unittest.TestCase):
    def test_saved_on_off_gate_gain_and_temporary_pauses(self):
        source = (MEDIA / "media.c").read_text()
        harness = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "ainekio/p4_media.h"
#define portMAX_DELAY 0
#define NVS_READONLY 0
#define NVS_READWRITE 1
#define ESP_CODEC_DEV_OK 0
typedef int nvs_handle_t;
static ainekio_p4_media_status_t status={.microphone_ready=true,.wake_ready=true,.wake_enabled=true};
static void *mutex=(void*)1,*codec=(void*)2,*vad=(void*)3;
static bool suspended,microphone_enabled,microphone_settings_saved;
static ainekio_microphone_gate_t microphone_gate=AINEKIO_MIC_GATE_VAD;
static uint64_t session=42;
static uint32_t microphone_epoch;
static int64_t microphone_after,microphone_sample_at=1000000;
static unsigned mutex_depth,commits,cancels,codec_gain=30;
static bool stored,fail_save,stored_gain;
static uint8_t saved[3],gain_value,pending[3],pending_gain;
static bool pending_has_gain;
static int xSemaphoreTake(void *m,unsigned t) { (void)t;assert(m==mutex && mutex_depth++==0);return 1; }
static int xSemaphoreGive(void *m) { assert(m==mutex && mutex_depth--==1);return 1; }
static int nvs_open(const char *name,int mode,nvs_handle_t *h)
{ assert(!strcmp(name,"p4_media"));*h=mode;pending_has_gain=false;return ESP_OK; }
static void nvs_close(nvs_handle_t h) { (void)h; }
static int nvs_get_u8(nvs_handle_t h,const char *key,uint8_t *v)
{ assert(h==0 && !strcmp(key,"mic_gain"));if(!stored_gain)return ESP_FAIL;*v=gain_value;return ESP_OK; }
static int nvs_get_blob(nvs_handle_t h,const char *key,void *v,size_t *size)
{ assert(h==0 && !strcmp(key,"mic_v1") && *size==3);if(!stored)return ESP_FAIL;memcpy(v,saved,3);return ESP_OK; }
static int nvs_set_blob(nvs_handle_t h,const char *key,const void *v,size_t size)
{ assert(h==1 && !strcmp(key,"mic_v1") && size==3);memcpy(pending,v,3);return ESP_OK; }
static int nvs_set_u8(nvs_handle_t h,const char *key,uint8_t v)
{ assert(h==1 && !strcmp(key,"mic_gain"));pending_gain=v;pending_has_gain=true;return ESP_OK; }
static int nvs_commit(nvs_handle_t h)
{ assert(h==1);if(fail_save)return ESP_FAIL;commits++;stored=true;memcpy(saved,pending,3);if(pending_has_gain){stored_gain=true;gain_value=pending_gain;}return ESP_OK; }
static int esp_codec_dev_set_in_gain(void *c,unsigned gain) { assert(c==codec);codec_gain=gain;return ESP_CODEC_DEV_OK; }
static int64_t esp_timer_get_time(void) { return 1000000; }
static bool p4_camera_ready(void) { return false; }
static uint32_t p4_camera_failures(void) { return 0; }
static void p4_camera_session(uint64_t s) { (void)s; }
static esp_err_t p4_camera_suspend(bool paused) { (void)paused;return ESP_OK; }
uint32_t ainekio_p4_media_audio_cancel(void) { cancels++;microphone_epoch++;return 0; }
'''
        for declaration in (
            "static void load_input_settings(",
            "ainekio_p4_media_status_t ainekio_p4_media_status(",
            "esp_err_t ainekio_p4_media_microphone(",
            "void ainekio_p4_media_disconnect(",
            "void ainekio_p4_media_session(",
            "esp_err_t ainekio_p4_media_suspend(",
        ):
            harness += function(source, declaration)
        harness += r'''
static void reboot(void)
{
    microphone_enabled=false;microphone_gate=AINEKIO_MIC_GATE_VAD;
    microphone_settings_saved=false;session=0;load_input_settings();
    assert(!ainekio_p4_media_status().microphone_listening);
    ainekio_p4_media_session(42);
}
int main(void)
{
    load_input_settings();
    assert(!microphone_enabled && !microphone_settings_saved && status.microphone_gain_db==30);
    const uint8_t gain=36;
    assert(ainekio_p4_media_microphone(true,AINEKIO_MIC_GATE_WAKE,&gain)==ESP_OK);
    assert(commits==1 && codec_gain==36);
    reboot();
    assert(microphone_enabled && microphone_gate==AINEKIO_MIC_GATE_WAKE && status.microphone_gain_db==36);
    assert(ainekio_p4_media_status().microphone_listening);
    ainekio_p4_media_disconnect();
    assert(microphone_enabled && !ainekio_p4_media_status().microphone_listening && commits==1);
    ainekio_p4_media_session(43);
    assert(ainekio_p4_media_status().microphone_listening);
    ainekio_p4_media_suspend(true);
    assert(microphone_enabled && !ainekio_p4_media_status().microphone_listening);
    ainekio_p4_media_suspend(false);
    assert(ainekio_p4_media_status().microphone_listening && commits==1);
    assert(ainekio_p4_media_microphone(true,AINEKIO_MIC_GATE_WAKE,&gain)==ESP_OK && commits==1);
    const uint8_t changed_gain=42;fail_save=true;
    assert(ainekio_p4_media_microphone(false,AINEKIO_MIC_GATE_OPEN,&changed_gain)==ESP_FAIL);
    assert(microphone_enabled && microphone_gate==AINEKIO_MIC_GATE_WAKE && codec_gain==36 && commits==1);
    fail_save=false;
    assert(ainekio_p4_media_microphone(false,AINEKIO_MIC_GATE_WAKE,NULL)==ESP_OK);
    reboot();assert(!microphone_enabled && microphone_gate==AINEKIO_MIC_GATE_WAKE);
    for(int gate=AINEKIO_MIC_GATE_OPEN;gate<=AINEKIO_MIC_GATE_WAKE;gate++) {
        assert(ainekio_p4_media_microphone(true,gate,NULL)==ESP_OK);
        reboot();assert(microphone_enabled && (int)microphone_gate==gate);
    }
    assert(mutex_depth==0 && cancels>0);
    puts("Power-cycle persistence, reconnect/sleep resume, saved off, idempotence and failed-save rollback passed.");
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-mic-settings-") as work:
            path = Path(work) / "settings.c"
            binary = Path(work) / "settings"
            path.write_text(harness)
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(path),
                "-I", str(MEDIA / "include"),
                "-I", str(ROOT / "Slave/firmware/esp32p4-wifi6/tests/body_shim"),
                "-I", str(ROOT / "Slave/software/core/include"), "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)
