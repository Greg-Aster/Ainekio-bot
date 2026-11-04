#pragma once
#include "ainekio/v2_motion.h"
#include "esp_err.h"
struct cJSON;

/* Allocation/parser only. The existing body owner stages, consumes and frees
 * these values; this module has no process, queue, timer or active operation. */
typedef struct ainekio_p4_curve_program {
    struct ainekio_p4_curve_program *next;
    char token[33];
    double speed_degrees_s;
    ainekio_v2_curve_t curve;
    ainekio_v2_clip_track_t track;
    ainekio_v2_clip_clock_t clock;
    ainekio_v2_clip_attitude_track_t attitude;
    float minimum[12], maximum[12];
} ainekio_p4_curve_program_t;
ainekio_p4_curve_program_t *ainekio_p4_curve_parse(const struct cJSON *root,esp_err_t *error);
void ainekio_p4_curve_free(ainekio_p4_curve_program_t *program);
