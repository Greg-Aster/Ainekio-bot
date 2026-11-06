"""Exercise the actual ISP profile and the saturated-white color boundary."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


class CameraPipelineTest(unittest.TestCase):
    def test_completed_buffer_clock_survives_delayed_dequeue_and_reuse(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        component = root / 'managed_components/espressif__esp_video'
        with tempfile.TemporaryDirectory(prefix='ainekio-camera-clock-') as directory:
            work = pathlib.Path(directory)
            (work / 'CMakeLists.txt').write_text(f'''
cmake_minimum_required(VERSION 3.16)
project(camera_clock_test C)
add_library(video STATIC "{component}/src/esp_video.c" "{component}/src/esp_video_ioctl.c")
function(idf_component_get_property variable component property)
    if(property STREQUAL "COMPONENT_LIB")
        set(${{variable}} video PARENT_SCOPE)
    else()
        set(${{variable}} "{component}" PARENT_SCOPE)
    endif()
endfunction()
include("{root}/cmake/idf_video_timestamp.cmake")
''')
            subprocess.run(['cmake', '-S', str(work), '-B', str(work/'build')],
                           check=True, capture_output=True)
            generated = work/'build/ainekio-idf/esp_video'

            def function(source, signature):
                start = source.index(signature)
                opening = source.index('{', start)
                depth = 1
                end = opening + 1
                while depth:
                    depth += (source[end] == '{') - (source[end] == '}')
                    end += 1
                return source[start:end]

            video = (generated/'esp_video.c').read_text()
            ioctl = (generated/'esp_video_ioctl.c').read_text()
            buffer = (component/'src/esp_video_buffer.c').read_text()
            # Compile the production queue/completion/dequeue functions and
            # generated buffer layout. Only OS synchronization is substituted.
            source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <time.h>
#include <sys/time.h>
#include <linux/videodev2.h>
#include "esp_video_buffer.h"
#define IRAM_ATTR
#define pdFALSE 0
#define portENTER_CRITICAL_SAFE(x) ((void)(x))
#define portEXIT_CRITICAL_SAFE(x) ((void)(x))
#define portYIELD_FROM_ISR() ((void)0)
struct esp_video_stream { struct esp_video_buffer *buffer; esp_video_buffer_list_t done_list; int ready_sem; };
struct esp_video { struct esp_video_stream stream; int stream_lock; uint32_t dqbuf_timeout_ticks; };
static int64_t clock_us;
static int64_t esp_timer_get_time(void) { return clock_us; }
static int xPortInIsrContext(void) { return 1; }
static void xSemaphoreGiveFromISR(int sem, BaseType_t *wake) { (void)sem; *wake = pdFALSE; }
static void xSemaphoreGive(int sem) { (void)sem; }
static struct esp_video_stream *esp_video_get_stream(struct esp_video *v, uint32_t type)
{ return type == V4L2_BUF_TYPE_VIDEO_CAPTURE ? &v->stream : NULL; }
static esp_err_t esp_video_get_buffer_info(struct esp_video *v, uint32_t type, struct esp_video_buffer_info *info)
{ if (!esp_video_get_stream(v,type)) return ESP_ERR_INVALID_ARG; *info=v->stream.buffer->info; return ESP_OK; }
'''
            source += function(buffer, 'struct esp_video_buffer_element *IRAM_ATTR esp_video_buffer_get_element_by_buffer(')
            source += function(video, 'struct esp_video_buffer_element *esp_video_get_done_element(')
            source += function(video, 'esp_err_t IRAM_ATTR esp_video_done_element(')
            source += function(video, 'esp_err_t IRAM_ATTR esp_video_done_buffer(')
            source += r'''
static esp_err_t esp_video_recv_element(struct esp_video *v,uint32_t type,uint32_t ticks,struct esp_video_buffer_element **out)
{ (void)ticks; *out=esp_video_get_done_element(v,type); return *out ? ESP_OK : ESP_ERR_TIMEOUT; }
'''
            source += function(ioctl, 'static esp_err_t esp_video_ioctl_dqbuf(')
            source += r'''
int main(void) {
    struct esp_video v={0};
    v.stream.buffer=calloc(1,sizeof(struct esp_video_buffer)+2*sizeof(struct esp_video_buffer_element));
    v.stream.buffer->info=(struct esp_video_buffer_info){.count=2,.memory_type=V4L2_MEMORY_MMAP};
    TAILQ_INIT(&v.stream.done_list);
    uint8_t pixels[2][4]={{1},{2}};
    for (unsigned i=0;i<2;++i) {
        struct esp_video_buffer_element *e=&v.stream.buffer->element[i];
        e->index=i; e->free=true; e->buffer=pixels[i]; e->video_buffer=v.stream.buffer;
        clock_us=12345678901LL+i*50000;
        assert(esp_video_done_buffer(&v,V4L2_BUF_TYPE_VIDEO_CAPTURE,pixels[i],4)==ESP_OK);
    }
    clock_us+=900000; /* Both images wait before either is dequeued. */
    for (unsigned i=0;i<2;++i) {
        struct v4l2_buffer out={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
        assert(esp_video_ioctl_dqbuf(&v,&out)==ESP_OK);
        assert(out.index==i && out.bytesused==4 && out.m.userptr==(unsigned long)pixels[i]);
        assert((int64_t)out.timestamp.tv_sec*1000000+out.timestamp.tv_usec==12345678901LL+i*50000);
        assert((out.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK)==V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC);
        assert((out.flags&V4L2_BUF_FLAG_TSTAMP_SRC_MASK)==V4L2_BUF_FLAG_TSTAMP_SRC_EOF);
    }
    clock_us+=100000;
    const int64_t reused_at=clock_us;
    assert(esp_video_done_buffer(&v,V4L2_BUF_TYPE_VIDEO_CAPTURE,pixels[0],4)==ESP_OK);
    clock_us+=500000;
    struct v4l2_buffer out={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
    assert(esp_video_ioctl_dqbuf(&v,&out)==ESP_OK && out.index==0);
    assert((int64_t)out.timestamp.tv_sec*1000000+out.timestamp.tv_usec==reused_at);
    free(v.stream.buffer);
    return 0;
}
'''
            (work/'sdkconfig.h').write_text('')
            (work/'clock.c').write_text(source)
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-I', str(work),
                            '-I', str(generated/'private_include'),
                            '-I', str(root/'tests/body_shim'), str(work/'clock.c'),
                            '-o', str(work/'clock')], check=True, capture_output=True)
            subprocess.run([str(work/'clock')], check=True, capture_output=True)

    def test_sensor_white_balance_has_no_competing_isp_owner(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        defaults = (root / "sdkconfig.defaults").read_text()
        self.assertIn("CONFIG_CAMERA_OV5647_CUSTOMIZED_IPA_JSON_CONFIGURATION_FILE=y", defaults)
        path = re.search(
            r'^CONFIG_CAMERA_OV5647_CUSTOMIZED_IPA_JSON_CONFIGURATION_FILE_PATH="([^"]+)"$',
            defaults, re.M,
        ).group(1)
        generator = root / "managed_components/espressif__esp_ipa/tools/config/esp_ipa_config.py"
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "ipa.c"
            subprocess.run([sys.executable, "-B", str(generator), "-i", str(root / path),
                            "-o", str(output), "-v", "1"], check=True, capture_output=True)
            generated = output.read_text()
        names = re.search(r's_ipa_OV5647_0_names\[\] = \{(.*?)\};', generated, re.S).group(1)
        self.assertNotIn('"esp_ipa_awb"', names)
        self.assertNotIn('.awb = &', generated)
        # Color/noise processing remains in the existing pipeline; no second
        # gain/shutter controller competes with the sensor's AEC/AGC.
        for name in ('ian', 'adn', 'aen', 'acc'):
            self.assertIn(f'"esp_ipa_{name}"', names)
        self.assertNotIn('"esp_ipa_agc"', names)

    def test_clipped_white_stays_neutral_after_sensor_white_balance(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        config = json.loads((root / 'components/ainekio_p4_media/ov5647_ipa.json').read_text())['OV5647']
        matrix = config['acc']['ccm']['table'][0]['matrix']
        def render(rgb):
            return [min(1, max(0, sum(matrix[3*r+c]*rgb[c] for c in range(3)))) for r in range(3)]
        # The old P4 path combines WB with CCM before clipping. A bright neutral
        # scene then loses green. Native WB clips before the neutral CCM instead.
        for red, blue in ((1.5, 1.5), (1.2, 2.0), (2.0, 1.2)):
            old = render([red, 1, blue])
            self.assertLess(old[1], min(old[0], old[2]))
            corrected = render([min(1, red), 1, min(1, blue)])
            for channel in corrected:
                self.assertAlmostEqual(channel, 1.0, places=4)
        # Unsaturated colors retain the same transform; this is not global
        # desaturation or a post-JPEG replacement of pink pixels.
        rgb = [0.15, 0.3, 0.2]
        gains = [1.5, 1.0, 1.8]
        self.assertEqual(render([x*g for x,g in zip(rgb,gains)]),
                         render([min(1,x*g) for x,g in zip(rgb,gains)]))


if __name__ == "__main__":
    unittest.main()
