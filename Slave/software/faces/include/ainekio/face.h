#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_FACE_WIDTH 320
#define AINEKIO_FACE_HEIGHT 170

/* Native RGB565, row-major. Hardware adapters own byte order and transport.
 * Rendering uses no heap, I/O, motion commands or platform clock. */
size_t ainekio_face_count(void);
const char *ainekio_face_name(size_t index);
bool ainekio_face_find(const char *name, size_t *index);
uint32_t ainekio_face_period_ms(size_t index);
void ainekio_face_render(size_t index, uint64_t elapsed_ms, bool talking,
                        uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT]);
