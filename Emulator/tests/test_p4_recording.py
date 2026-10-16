"""Exercise the production recording producer without camera/SD hardware."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Slave/firmware/esp32p4-wifi6/main/storage.c"


class RecordingQueueTests(unittest.TestCase):
    def test_copy_ownership_bounded_queue_and_nonblocking_backpressure(self):
        source = SOURCE.read_text()
        operations = re.search(r"typedef enum \{[^}]*\} operation_t;", source).group()
        request = re.search(r"typedef struct \{[^}]*\} request_t;", source).group()
        start = source.index("void ainekio_p4_video_frame(")
        producer = source[start:source.index("\n}", start) + 2]
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define pdTRUE 1
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define RECORD_BYTES 1024U
#define taskENTER_CRITICAL(p) ((void)(p))
#define taskEXIT_CRITICAL(p) ((void)(p))
''' + operations + request + r'''
static void *queue=(void *)1, *enqueue_lock=(void *)2;
static int status_lock;
static bool video_accepting, suspended, lock_busy, queue_full;
static unsigned video_pending, allocated, queued;
static struct { bool recording; unsigned dropped; } video_status;
static request_t retained[3];
static int xSemaphoreTake(void *p, unsigned wait) { (void)p;assert(wait==0);return !lock_busy; }
static void xSemaphoreGive(void *p) { (void)p; }
static void *heap_caps_malloc(size_t n,unsigned caps) { assert(n<=262144 && caps==3);++allocated;return malloc(n); }
static uint64_t esp_timer_get_time(void) { return 1000000; }
static int xQueueSend(void *p,const request_t *r,unsigned wait)
{ assert(p==queue && wait==0);if(queue_full)return 0;assert(queued<3);retained[queued++]=*r;return 1; }
''' + producer + r'''
int main(void)
{
    uint8_t jpeg[8]={255,216,1,2,3,4,255,217};
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(!allocated && !queued);
    video_accepting=video_status.recording=true;
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(queued==1 && video_pending==1 && retained[0].capture!=jpeg);
    jpeg[2]=42;assert(retained[0].capture[2]==1);
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(video_pending==3 && allocated==3 && queued==3 && video_status.dropped==1);
    /* Worker owns its dequeued frame until the write completes. Removing a
     * queue item alone must not make a fourth allocation possible. */
    --queued;
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(allocated==3 && video_status.dropped==2);
    for(unsigned i=0;i<3;++i)free(retained[i].capture);
    video_pending=queued=0;queue_full=true;
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(!video_pending && video_status.dropped==3);
    lock_busy=true;
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(video_status.dropped==4);
    lock_busy=false;queue_full=false;suspended=true;
    ainekio_p4_video_frame(jpeg,sizeof(jpeg),640,480,2);
    assert(!queued);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-recording-test-") as directory:
            path = Path(directory)
            (path / "producer.c").write_text(harness)
            result = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                                     str(path / "producer.c"), "-o", str(path / "producer")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(path / "producer")], check=True)


    def test_rolling_slots_reuse_storage_and_cache_oldest_without_unlink(self):
        source = SOURCE.read_text()
        def function(name):
            start = source.index(name)
            start = source.rfind("\n", 0, start) + 1
            return source[start:source.index("\n}", start) + 2]
        operations = re.search(r"typedef enum \{[^}]*\} operation_t;", source).group()
        request = re.search(r"typedef struct \{[^}]*\} request_t;", source).group()
        config = source[source.index("#define VIDEO_SEGMENT_BYTES"):source.index("static void video_yield")]
        harness = r"""
#define _DEFAULT_SOURCE
#include <assert.h>
#include <errno.h>
#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "video_avi.h"
#define ROOT "."
#define MOUNT "."
#define RECORD_BYTES 1024U
#define ESP_OK 0
#define taskENTER_CRITICAL(p) ((void)(p))
#define taskEXIT_CRITICAL(p) ((void)(p))
static int status_lock;
static struct { unsigned frames,segments,overwritten;char path[96]; } video_status;
static ainekio_avi_t video;
static uint64_t video_started,video_synced;
static char video_path[96],download_name[64];
static uint32_t video_session=123,video_sequence;
static struct { struct { unsigned sector_size; } csd; } test_card={{512}},*card=&test_card;
static uint64_t free_bytes=32*1024*1024;
static unsigned scans;
static void video_yield(void) {}
static void ainekio_p4_log_stage(const char *stage) {(void)stage;}
static int esp_vfs_fat_info(const char *p,uint64_t *total,uint64_t *avail)
{ (void)p;*total=1024*1024*1024;*avail=free_bytes;return ESP_OK; }
static DIR *counted_opendir(const char *p) { ++scans;return opendir(p); }
#define opendir counted_opendir
""" + operations + request + "\n" + config + "\n" + function("static bool recording_name(const char *name)\n{")
        for name in ("static bool video_scan(void)", "static bool video_oldest_path(",
                     "static bool video_close(void)", "static bool video_append("):
            harness += "\n" + function(name)
        harness += r"""
static void fixture(const char *name,size_t bytes)
{ FILE *f=fopen(name,"wb");assert(f);for(size_t i=0;i<bytes;++i)fputc(0x55,f);assert(!fclose(f)); }
int main(void)
{
    char name[96];
    for(unsigned i=40;i>0;--i){snprintf(name,sizeof(name),"video-abcdef01-%08u.avi",i);fixture(name,32768);}
    fixture("video-abcdef01-00000050.avi.part",4096);
    fixture("events.0.bin",1024);fixture("capture.00.jpg",1024);fixture("personal.avi",1024);
    assert(video_scan() && video_sequence==50 && video_oldest_count==32);
    assert(video_oldest[0].sequence==1 && video_oldest[31].sequence==32);
    unsigned before=scans;
    for(unsigned i=1;i<=32;++i) {
        assert(video_oldest_path(name,sizeof(name)));
        char expected[96];snprintf(expected,sizeof(expected),"./video-abcdef01-%08u.avi",i);
        assert(!strcmp(name,expected));
    }
    assert(scans==before); /* no directory walk for each oldest selection */
    assert(video_scan());
    strcpy(download_name,"video-abcdef01-00000001.avi");
    struct stat old,new;
    assert(!stat("video-abcdef01-00000002.avi",&old));
    uint8_t jpeg[1000]={0xff,0xd8};
    request_t r={.timestamp=1000,.width=640,.height=480,.fps=1,.capture=jpeg,.size=sizeof(jpeg)};
    before=scans;
    assert(video_append(&r));
    assert(video_status.overwritten==1 && !stat(video_path,&new) && old.st_ino==new.st_ino);
    assert(new.st_size==old.st_size); /* opening reused the allocation, no initial truncation */
    assert(!stat("video-abcdef01-00000001.avi",&new)); /* download pinned */
    for(unsigned i=0;i<5;++i){r.timestamp+=1000;assert(video_append(&r));}
    assert(scans==before); /* no scans while recording frames */
    const size_t written=video.bytes;
    assert(video_close() && !stat(video_status.path,&new) && new.st_size==(off_t)written);
    assert(old.st_ino==new.st_ino); /* still the same file, not delete-and-recreate */
    FILE *f=fopen(video_status.path,"rb");char magic[4];assert(fread(magic,1,4,f)==4 && !memcmp(magic,"RIFF",4));fclose(f);
    assert(!stat("personal.avi",&new) && new.st_size==1024);
    assert(!stat("video-abcdef01-00000050.avi.part",&new) && new.st_size==4096);
    assert(!stat("events.0.bin",&new) && new.st_size==1024);
    assert(!stat("capture.00.jpg",&new) && new.st_size==1024);
    video_sequence=0;assert(video_scan() && video_sequence==51); /* reboot ordering */
    download_name[0]=0;free_bytes=0;r.timestamp+=60000;
    assert(video_append(&r) && video_limit==32768); /* overwrite works with zero data headroom */
    unsigned rolled=video_status.overwritten,completed=video_status.segments;
    for(unsigned i=0;i<70;++i){r.timestamp+=1000;assert(video_append(&r));assert(video.bytes<=video_limit);}
    assert(video_status.overwritten>=rolled+2 && video_status.segments>=completed+2);
    assert(video_close());
    free_bytes=128*1024*1024;r.timestamp+=60000;
    unsigned reused=video_status.overwritten;assert(video_append(&r) && video_status.overwritten==reused);
    assert(video_close());
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="ainekio-rolling-test-") as directory:
            path = Path(directory)
            (path / "rolling.c").write_text(harness)
            result = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(SOURCE.parent), str(path / "rolling.c"), str(SOURCE.parent / "video_avi.c"),
                "-o", str(path / "rolling")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(path / "rolling")], cwd=path, check=True)


if __name__ == "__main__":
    unittest.main()
