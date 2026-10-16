#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

/* Streaming MJPEG AVI, one video stream, no audio or in-memory index.
 * RIFF permits an absent idx1; players can scan the bounded segment. */
typedef struct {
    FILE *file;
    uint32_t frames, bytes;
    uint16_t width, height;
    uint8_t fps;
    void (*yield)(void);
} ainekio_avi_t;
bool ainekio_avi_begin(ainekio_avi_t *avi, FILE *file, unsigned width, unsigned height, unsigned fps);
/* NULL/zero inserts a dropped-frame slot, retaining elapsed playback time. */
bool ainekio_avi_frame(ainekio_avi_t *avi, const void *jpeg, size_t size);
/* Update lengths and flush; caller owns fsync, close, and rename. */
bool ainekio_avi_checkpoint(ainekio_avi_t *avi);
