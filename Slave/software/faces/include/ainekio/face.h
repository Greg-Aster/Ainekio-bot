#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_FACE_WIDTH 320
#define AINEKIO_FACE_HEIGHT 170
/* Owner-confirmed centered mounting with the full LCD exposed, 2026-11-03.
 * Exclusive ends; shared by face and connection-page layout. */
#define AINEKIO_LCD_VISIBLE_LEFT 0
#define AINEKIO_LCD_VISIBLE_TOP 0
#define AINEKIO_LCD_VISIBLE_RIGHT 320
#define AINEKIO_LCD_VISIBLE_BOTTOM 170
/* Wide composition: retain horizontal size and shorten vertical geometry.
 * Stroke thickness and round pupils retain their enlarged size. */
#define AINEKIO_FACE_SCALE_X 1.5F
#define AINEKIO_FACE_SCALE_Y 1.0F
/* Owner-requested lowering of the complete face, including speech/symbols. */
#define AINEKIO_FACE_OFFSET_Y 10

/* Native RGB565, row-major. Hardware adapters own byte order and transport.
 * Rendering uses no heap, I/O, motion commands or platform clock. */
size_t ainekio_face_count(void);
const char *ainekio_face_name(size_t index);
bool ainekio_face_find(const char *name, size_t *index);
uint32_t ainekio_face_period_ms(size_t index);
void ainekio_face_render(size_t index, uint64_t elapsed_ms, bool talking,
                        uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT]);
