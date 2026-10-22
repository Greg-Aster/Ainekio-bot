#pragma once
#include "body.h"
/* Source progress selects the expression; wall time animates it independently
 * of servo arrival waits, holds, entry easing and motion speed. */
typedef struct { size_t face; uint64_t elapsed_ms; } ainekio_p4_face_sample_t;
typedef struct {
    size_t face, clip, cue;
    uint32_t revision;
    uint64_t started_ms;
    bool initialized;
} ainekio_p4_face_clock_t;
ainekio_p4_face_sample_t ainekio_p4_face_sample(ainekio_p4_face_clock_t *clock,
    const ainekio_p4_body_status_t *body,uint64_t now_ms);
/* Temporary audio overlay; the underlying manual/motion selection is retained. */
ainekio_p4_face_sample_t ainekio_p4_face_listen(ainekio_p4_face_sample_t previous,
                                             bool capturing, uint64_t elapsed_ms);

/* Foreground and background selections retain independent tokens and expiry.
 * Releasing an old token cannot clear its replacement in either layer. */
typedef struct {
    size_t face;
    uint32_t revision;
    uint64_t started_ms, expires_ms;
    char token[AINEKIO_ASSET_NAME_MAX + 1U];
    bool active, background, legacy;
} ainekio_p4_face_layer_t;
typedef struct {
    ainekio_p4_face_layer_t foreground, background;
} ainekio_p4_face_selection_t;
const char *ainekio_p4_face_token(const ainekio_p4_face_selection_t *selection, uint64_t at_ms);
bool ainekio_p4_face_select(ainekio_p4_face_selection_t *selection,
    const ainekio_face_selection_t *request, uint32_t revision, uint64_t now_ms);
ainekio_p4_face_sample_t ainekio_p4_face_selected(ainekio_p4_face_selection_t *selection,
    ainekio_p4_face_sample_t underlying, uint32_t revision, bool moving, bool talking, uint64_t now_ms);
