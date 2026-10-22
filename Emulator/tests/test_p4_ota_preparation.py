"""Test the production profile confirmation used by WELCOME during OTA."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class OTAProfileTests(unittest.TestCase):
    def test_accepting_firmware_does_not_release_standing_outputs(self):
        source = (ROOT / "Slave/firmware/esp32p4-wifi6/main/system.c").read_text()
        start = source.index("esp_err_t ainekio_p4_system_authenticated(")
        function = source[start:source.index("\n}", start) + 2]
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdatomic.h>
typedef int esp_err_t;
enum { ESP_OK, FAILED, AINEKIO_PCA_FAULT_EMERGENCY };
static atomic_bool ota_pending;
static bool armed = true;
static int check_result, mark_result;
static unsigned checked, marked, accepted;
void *ainekio_p4_output(void) { return &armed; }
void ainekio_pca_emergency_disable(void *p, int fault)
{ (void)p; (void)fault; armed = false; }
void ainekio_p4_logs_runtime(void) {}
int ainekio_p4_ota_startup_check(void) { ++checked; return check_result; }
int esp_ota_mark_app_valid_cancel_rollback(void) { ++marked; return mark_result; }
void ainekio_p4_ota_accepted(void) { ++accepted; }
''' + function + r'''
int main(void)
{
    ota_pending = true;
    assert(ainekio_p4_system_authenticated() == ESP_OK);
    assert(armed && !ota_pending && checked == 1 && marked == 1 && accepted == 1);
    assert(ainekio_p4_system_authenticated() == ESP_OK);
    assert(armed && checked == 1 && marked == 1 && accepted == 1);
    ota_pending = true; check_result = FAILED;
    assert(ainekio_p4_system_authenticated() == FAILED);
    assert(armed && ota_pending && checked == 2 && marked == 1 && accepted == 1);
    check_result = ESP_OK; mark_result = FAILED;
    assert(ainekio_p4_system_authenticated() == FAILED);
    assert(armed && ota_pending && checked == 3 && marked == 2 && accepted == 1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-ota-standing-") as directory:
            path = Path(directory)
            (path / "accept.c").write_text(harness)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(path / "accept.c"), "-o", str(path / "accept")], check=True)
            subprocess.run([str(path / "accept")], check=True)

    def test_reconnect_can_confirm_profile_without_changing_it_during_upload(self):
        source = (ROOT / "Slave/firmware/esp32p4-wifi6/main/system.c").read_text()
        start = source.index("esp_err_t ainekio_p4_system_profile(")
        function = source[start:source.index("\n}", start) + 2]
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <string.h>
typedef int esp_err_t, nvs_handle_t;
typedef enum { AINEKIO_PROFILE_HOME, AINEKIO_PROFILE_TETHER } ainekio_profile_t;
enum { ESP_OK, ESP_ERR_INVALID_STATE, ESP_ERR_INVALID_ARG, ESP_ERR_TIMEOUT };
#define pdTRUE 1
#define pdMS_TO_TICKS(n) (n)
#define NVS_READWRITE 1
#define AINEKIO_PCA_FAULT_EMERGENCY 1
static atomic_int profile;
static atomic_bool power_pending;
static int settings_lock = 1;
static bool ota_busy, start_ota_on_lock, lock_held;
static unsigned disables, writes;
static bool ainekio_p4_ota_busy(void) { return ota_busy; }
static int xSemaphoreTake(int lock, unsigned ticks)
{
    assert(lock == 1 && ticks == 100 && !lock_held);
    lock_held = true;
    if (start_ota_on_lock) ota_busy = true;
    return pdTRUE;
}
static void xSemaphoreGive(int lock) { assert(lock == 1 && lock_held); lock_held = false; }
static void *ainekio_p4_output(void) { return (void *)1; }
static void ainekio_pca_emergency_disable(void *output, int fault)
{ assert(output == (void *)1 && fault == 1); ++disables; }
static int nvs_open(const char *space, int mode, nvs_handle_t *handle)
{ assert(!strcmp(space,"p4_system") && mode == 1); *handle = 1; return ESP_OK; }
static int nvs_set_u8(nvs_handle_t handle, const char *key, int value)
{ assert(handle == 1 && !strcmp(key,"profile") && value == 1); ++writes; return ESP_OK; }
static int nvs_commit(nvs_handle_t handle) { assert(handle == 1); return ESP_OK; }
static void nvs_close(nvs_handle_t handle) { assert(handle == 1); }
''' + function + r'''
int main(void)
{
    profile = AINEKIO_PROFILE_HOME;
    ota_busy = true;
    assert(ainekio_p4_system_profile(AINEKIO_PROFILE_HOME) == ESP_OK);
    assert(!disables && !writes && !lock_held);
    assert(ainekio_p4_system_profile(AINEKIO_PROFILE_TETHER) == ESP_ERR_INVALID_STATE);
    assert(!disables && !writes && profile == AINEKIO_PROFILE_HOME && !lock_held);
    /* OTA starting during mutex acquisition must still prevent a change. */
    ota_busy = false; start_ota_on_lock = true;
    assert(ainekio_p4_system_profile(AINEKIO_PROFILE_TETHER) == ESP_ERR_INVALID_STATE);
    assert(!disables && !writes && !lock_held);
    start_ota_on_lock = false; ota_busy = false;
    assert(ainekio_p4_system_profile(AINEKIO_PROFILE_TETHER) == ESP_OK);
    assert(disables == 1 && writes == 1 && profile == AINEKIO_PROFILE_TETHER && !lock_held);
    ota_busy = true;
    assert(ainekio_p4_system_profile(AINEKIO_PROFILE_TETHER) == ESP_OK);
    assert(disables == 1 && writes == 1 && !lock_held);
    power_pending = true;
    assert(ainekio_p4_system_profile(AINEKIO_PROFILE_TETHER) == ESP_ERR_INVALID_STATE);
    assert(ainekio_p4_system_profile(99) == ESP_ERR_INVALID_ARG);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-ota-profile-") as directory:
            path = Path(directory)
            (path / "profile.c").write_text(harness)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(path / "profile.c"), "-o", str(path / "profile")], check=True)
            subprocess.run([str(path / "profile")], check=True)
