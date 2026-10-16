#include "video_avi.h"
#include <string.h>

enum { HEADER_BYTES = 224 };
static void u32(uint8_t *p, uint32_t n)
{ for (unsigned i = 0; i < 4; ++i) p[i] = n >> (8 * i); }
static void tag(uint8_t *p, const char *s) { memcpy(p, s, 4); }

bool ainekio_avi_checkpoint(ainekio_avi_t *a)
{
    uint8_t h[HEADER_BYTES] = {0};
    tag(h, "RIFF"); u32(h+4, a->bytes-8); tag(h+8, "AVI ");
    tag(h+12, "LIST"); u32(h+16, 192); tag(h+20, "hdrl");
    tag(h+24, "avih"); u32(h+28, 56);
    u32(h+32, 1000000U / a->fps); u32(h+48, a->frames);
    u32(h+56, 1); u32(h+64, a->width); u32(h+68, a->height);
    tag(h+88, "LIST"); u32(h+92, 116); tag(h+96, "strl");
    tag(h+100, "strh"); u32(h+104, 56);
    tag(h+108, "vids"); tag(h+112, "MJPG");
    u32(h+128, 1); u32(h+132, a->fps); u32(h+140, a->frames);
    u32(h+148, UINT32_MAX);
    h[160] = a->width; h[161] = a->width >> 8;
    h[162] = a->height; h[163] = a->height >> 8;
    tag(h+164, "strf"); u32(h+168, 40); u32(h+172, 40);
    u32(h+176, a->width); u32(h+180, a->height);
    h[184] = 1; h[186] = 24; tag(h+188, "MJPG");
    u32(h+192, (uint32_t)a->width * a->height * 3);
    tag(h+212, "LIST"); u32(h+216, a->bytes-220); tag(h+220, "movi");
    return fseek(a->file, 0, SEEK_SET) == 0 &&
        fwrite(h, 1, sizeof(h), a->file) == sizeof(h) &&
        fflush(a->file) == 0 && fseek(a->file, a->bytes, SEEK_SET) == 0;
}

bool ainekio_avi_begin(ainekio_avi_t *a, FILE *file, unsigned width, unsigned height, unsigned fps)
{
    if (!a || !file || !width || width > UINT16_MAX || !height || height > UINT16_MAX || !fps || fps > 15)
        return false;
    *a = (ainekio_avi_t){.file=file, .bytes=HEADER_BYTES, .width=width, .height=height, .fps=fps};
    return ainekio_avi_checkpoint(a);
}

bool ainekio_avi_frame(ainekio_avi_t *a, const void *jpeg, size_t size)
{
    if (!a || !a->file || (!jpeg && size) || size > 256U * 1024U ||
        size + 9 > UINT32_MAX - a->bytes) return false;
    uint8_t chunk[8]; tag(chunk, "00dc"); u32(chunk+4, size);
    const uint8_t pad = 0;
    if (fwrite(chunk, 1, sizeof(chunk), a->file) != sizeof(chunk)) return false;
    for (size_t offset=0; offset<size;) {
        const size_t count = size-offset > 4096 ? 4096 : size-offset;
        if (fwrite((const uint8_t *)jpeg+offset, 1, count, a->file) != count) return false;
        offset += count;
        if (a->yield) a->yield();
    }
    if ((size & 1) && fwrite(&pad, 1, 1, a->file) != 1) return false;
    a->bytes += 8 + size + (size & 1);
    ++a->frames;
    return true;
}
