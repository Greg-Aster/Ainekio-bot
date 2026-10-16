#include "video_avi.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

static uint32_t u32(const unsigned char *p)
{ return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }

int main(int argc, char **argv)
{
    /* Optional real JPEG input/output allows ffprobe/ffmpeg interoperability
     * checks using exactly the production muxer, including a dropped frame. */
    size_t size = 5;
    unsigned char *jpeg = NULL;
    const unsigned char fixture[] = {0xff, 0xd8, 0, 0xff, 0xd9};
    FILE *file = argc == 3 ? fopen(argv[2], "w+b") : tmpfile();
    assert(file);
    if (argc == 3) {
        FILE *input = fopen(argv[1], "rb"); assert(input);
        assert(fseek(input, 0, SEEK_END) == 0);
        size = ftell(input); rewind(input);
        jpeg = malloc(size); assert(jpeg);
        assert(fread(jpeg, 1, size, input) == size); fclose(input);
    }
    ainekio_avi_t avi;
    assert(!ainekio_avi_begin(&avi, file, 640, 480, 0));
    assert(ainekio_avi_begin(&avi, file, 640, 480, 2));
    assert(ainekio_avi_frame(&avi, jpeg ? jpeg : fixture, size));
    assert(ainekio_avi_frame(&avi, NULL, 0));
    assert(ainekio_avi_frame(&avi, jpeg ? jpeg : fixture, size));
    assert(!ainekio_avi_frame(&avi, NULL, 3));
    assert(!ainekio_avi_frame(&avi, fixture, 256U*1024U+1));
    assert(ainekio_avi_checkpoint(&avi));
    const uint32_t bytes = 224 + 24 + 2 * (size + (size & 1));
    assert(avi.bytes == bytes && avi.frames == 3);
    unsigned char header[224]; rewind(file);
    assert(fread(header, 1, sizeof(header), file) == sizeof(header));
    assert(!memcmp(header, "RIFF", 4) && !memcmp(header+220, "movi", 4));
    assert(u32(header+4) == bytes-8 && u32(header+216) == bytes-220);
    assert(u32(header+48) == 3 && u32(header+140) == 3);
    fclose(file); free(jpeg);
    /* Full-card/write failure propagates without claiming a valid recording. */
    file = fopen("/dev/full", "wb");
    if (file) { assert(!ainekio_avi_begin(&avi, file, 640, 480, 2)); fclose(file); }
    return 0;
}
