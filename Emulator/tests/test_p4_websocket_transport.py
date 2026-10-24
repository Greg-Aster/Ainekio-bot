"""Exercise the exact project-built IDF frame writer with partial TCP writes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / 'Slave/firmware/esp32p4-wifi6'


class WebSocketWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='ainekio-ws-write-')
        cls.addClassCleanup(cls.workspace.cleanup)
        root = Path(cls.workspace.name)
        sdk = Path(os.environ.get('IDF_PATH', '/home/greggles/esp/esp-idf-v5.5.4'))
        transport = sdk / 'components/tcp_transport'
        (root / 'CMakeLists.txt').write_text(f'''
cmake_minimum_required(VERSION 3.16)
project(ws_write_test C)
add_library(transport STATIC "{transport}/transport_ws.c")
function(idf_component_get_property variable component property)
    if(property STREQUAL "COMPONENT_LIB")
        set(${{variable}} transport PARENT_SCOPE)
    else()
        set(${{variable}} "{transport}" PARENT_SCOPE)
    endif()
endfunction()
include("{FIRMWARE}/cmake/idf_websocket_write.cmake")
''')
        subprocess.run(['cmake', '-S', str(root), '-B', str(root/'build')],
                       check=True, capture_output=True)
        source = (root/'build/ainekio-idf/transport_ws.c').read_text()
        start = source.index('extern bool ainekio_p4_controller_transport_active(')
        end = source.index('\nint esp_transport_ws_send_raw', start)
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
typedef void *esp_transport_handle_t;
typedef struct { void *parent; } transport_ws_t;
static transport_ws_t ws;
static unsigned calls, wire_size;
static unsigned char wire[8192];
static const char *mode;
bool ainekio_p4_controller_transport_active(void) {
    return strcmp(mode,"cancel") || calls < 3;
}
#define MAX_WEBSOCKET_HEADER_SIZE 14
#define WS_SIZE16 126
#define WS_SIZE64 127
#define ESP_LOGE(...)
#define ESP_LOGD(...)
static void *esp_transport_get_context_data(void *p) {return &ws;}
static int esp_transport_poll_write(void *p,int ms) {return 1;}
static ssize_t getrandom(void *p,size_t n,unsigned flags) {memset(p,0x55,n);return n;}
static int esp_transport_write(void *p,const char *b,int n,int ms) {
    ++calls;
    assert(ms == 2000);
    if (!strcmp(mode,"zero") && calls==3) return 0;
    if (!strcmp(mode,"cancel")) return 0;
    if (!strcmp(mode,"again") && calls==3) {errno=EAGAIN;return -1;}
    if (!strcmp(mode,"interrupted") && calls==3) {errno=EINTR;return -1;}
    if (!strcmp(mode,"error") && calls==3) {errno=ECONNRESET;return -1;}
    if (!strcmp(mode,"header_error") && calls==2) {errno=EPIPE;return -1;}
    unsigned sent = n;
    if (!strcmp(mode,"header") || !strcmp(mode,"header_error")) {
        if(sent>3)sent=3;
    } else if(strcmp(mode,"whole") && calls>1 && sent>17)sent=17;
    memcpy(wire+wire_size,b,sent);wire_size+=sent;return sent;
}
'''
        harness += source[start:end]
        harness += r'''
int main(int argc,char **argv) {
    mode=argv[1];
    char payload[4096];
    for(unsigned i=0;i<sizeof(payload);++i)payload[i]=(char)(i%251);
    int n=!strcmp(mode,"empty")?0:sizeof(payload);
    int result=_ws_write(NULL,n?0x82:0x89,0x80,payload,n,2000);
    for(unsigned i=0;i<sizeof(payload);++i)assert((unsigned char)payload[i]==i%251);
    printf("%d %u\n",result,calls);
    for(unsigned i=0;i<wire_size;++i)printf("%02x",wire[i]);
    puts("");return 0;
}
'''
        (root/'writer.c').write_text(harness)
        cls.binary = root/'writer'
        subprocess.run(['cc', '-o', str(cls.binary), str(root/'writer.c')], check=True, capture_output=True)

    def result(self, mode):
        header, data = subprocess.check_output([str(self.binary), mode], text=True).splitlines()
        result, calls = map(int, header.split())
        return result, calls, bytes.fromhex(data)

    def test_short_header_and_payload_keep_one_complete_frame(self):
        for mode in ('whole', 'header', 'payload', 'zero', 'again', 'interrupted'):
            with self.subTest(mode=mode):
                result, calls, wire = self.result(mode)
                self.assertEqual(result, 4096)
                self.assertEqual(wire[:4], bytes([0x82, 0xfe, 0x10, 0]))
                self.assertEqual(len(wire), 4104)
                mask=wire[4:8]
                decoded=bytes(value ^ mask[i%4] for i,value in enumerate(wire[8:]))
                self.assertEqual(decoded, bytes(i%251 for i in range(4096)))
                self.assertGreater(calls, 1 if mode=='whole' else 2)

    def test_retired_connection_or_error_never_reports_a_partial_frame_as_success(self):
        for mode in ('cancel', 'error', 'header_error'):
            with self.subTest(mode=mode):
                result, calls, wire = self.result(mode)
                self.assertEqual(result, -1)
                self.assertEqual(calls, 2 if mode=='header_error' else 3)

    def test_empty_control_frame_is_still_sent(self):
        result, calls, wire=self.result('empty')
        self.assertEqual(result,0)
        self.assertEqual(calls,1)
        self.assertEqual(wire,bytes([0x89,0x80,0x55,0x55,0x55,0x55]))
