"""Run the production bounded warm-reset log recorder with SDK boundaries mocked."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'Slave/firmware/esp32p4-wifi6/main'

class ControllerLogTests(unittest.TestCase):
    def test_capture_wrap_previous_boot_and_nonblocking_panic(self):
        headers = {
            'esp_attr.h': '#define RTC_NOINIT_ATTR\n#define IRAM_ATTR\n',
            'esp_app_desc.h': '#pragma once\ntypedef struct {char version[32];} esp_app_desc_t;\nconst esp_app_desc_t *esp_app_get_description(void);\n',
            'esp_log.h': '#pragma once\n#include <stdarg.h>\ntypedef int (*vprintf_like_t)(const char *,va_list);\nvprintf_like_t esp_log_set_vprintf(vprintf_like_t);\nvoid emit(const char *,...);\n#define ESP_LOGI(tag,fmt,...) emit(fmt "\\n", ##__VA_ARGS__)\n',
            'esp_system.h': '#pragma once\ntypedef int esp_reset_reason_t;\n#define ESP_RST_POWERON 1\nesp_reset_reason_t esp_reset_reason(void);\n',
        }
        harness = r'''
#include <assert.h>
#include "logs.c"
static int reason=ESP_RST_POWERON;
static vprintf_like_t sink;
static const esp_app_desc_t app={.version="wifi-log-test"};
const esp_app_desc_t *esp_app_get_description(void){return &app;}
int esp_reset_reason(void){return reason;}
static int discard(const char *fmt,va_list ap){(void)fmt;(void)ap;return 0;}
vprintf_like_t esp_log_set_vprintf(vprintf_like_t fn){sink=fn;return discard;}
void emit(const char *fmt,...){va_list ap;va_start(ap,fmt);sink(fmt,ap);va_end(ap);}
int main(void){
 char buffer[AINEKIO_P4_LOG_SNAPSHOT_BYTES+1];
 ainekio_p4_logs_init();ainekio_p4_logs_runtime();ainekio_p4_log_stage("camera starting");
 ainekio_p4_log_panic_character('!');ainekio_p4_log_panic_character('\n');
 size_t n=ainekio_p4_logs_snapshot(buffer,sizeof(buffer));buffer[n]=0;
 assert(strstr(buffer,"camera starting") && strstr(buffer,"!\n"));
 unsigned before=retained.current_used;atomic_flag_test_and_set(&writing);
 ainekio_p4_log_panic_character('x');emit("blocked");assert(retained.current_used==before);
 assert(!ainekio_p4_logs_snapshot(buffer,sizeof(buffer)));atomic_flag_clear(&writing);
 for(unsigned i=0;i<9000;++i)ainekio_p4_log_panic_character('a');
 emit("PREVIOUS-PANIC\n");reason=4;ainekio_p4_logs_init();
 n=ainekio_p4_logs_snapshot(buffer,sizeof(buffer));buffer[n]=0;
 assert(strstr(buffer,"PREVIOUS-PANIC") && strstr(buffer,"reset reason 4"));
 assert(n<=AINEKIO_P4_LOG_SNAPSHOT_BYTES && !strstr(buffer,"camera starting"));
 assert(!ainekio_p4_logs_snapshot(buffer,20));
 reason=ESP_RST_POWERON;ainekio_p4_logs_init();
 n=ainekio_p4_logs_snapshot(buffer,sizeof(buffer));buffer[n]=0;
 assert(!strstr(buffer,"PREVIOUS-PANIC"));
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='ainekio-log-tests-') as directory:
            path=Path(directory)
            for name,text in headers.items(): (path/name).write_text(text)
            (path/'test.c').write_text(harness)
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-I',str(path),'-I',str(MAIN),str(path/'test.c'),'-o',str(path/'test')],check=True)
            subprocess.run([str(path/'test')],check=True)

if __name__ == '__main__': unittest.main()
