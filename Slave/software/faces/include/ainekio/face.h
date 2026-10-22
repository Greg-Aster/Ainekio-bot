#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_FACE_WIDTH 320
#define AINEKIO_FACE_HEIGHT 170
/* Selected recessed LCD bezel only, measured in Blender on 2026-10-20.
 * Uninterrupted opening when viewed straight at the robot. Exclusive ends.
 * This is a layout reference, not a renderer crop or a face scale change. */
#define AINEKIO_LCD_VISIBLE_LEFT 0
#define AINEKIO_LCD_VISIBLE_TOP 35
#define AINEKIO_LCD_VISIBLE_RIGHT 315
#define AINEKIO_LCD_VISIBLE_BOTTOM 168
/* Mounting compensation: center at x=145, 15 pixels left of panel center.
 * Blender's active LCD center is 1.998 mm right of the chin/camera centerline
 * across a 42.72 mm active width. Keep every feature in the left 290 pixels. */
#define AINEKIO_FACE_LAYOUT_WIDTH 290
/* Expand around the mounting center; lower eyes/lights only, not speech. */
#define AINEKIO_FACE_WIDTH_PERCENT 105
#define AINEKIO_FACE_LIGHT_OFFSET_Y 10

/* Native RGB565, row-major. Hardware adapters own byte order and transport.
 * Rendering uses no heap, I/O, motion commands or platform clock. */
size_t ainekio_face_count(void);
const char *ainekio_face_name(size_t index);
bool ainekio_face_find(const char *name, size_t *index);
uint32_t ainekio_face_period_ms(size_t index);
void ainekio_face_render(size_t index, uint64_t elapsed_ms, bool talking,
                        uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT]);
