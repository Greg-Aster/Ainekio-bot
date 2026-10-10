#pragma once
#include "body.h"
/* Pure selection, using motion time already advanced by the output owner. */
typedef struct { size_t face; uint64_t elapsed_ms; } ainekio_p4_face_sample_t;
ainekio_p4_face_sample_t ainekio_p4_face_sample(const ainekio_p4_body_status_t *body,
                                              uint64_t idle_ms);
/* Temporary audio overlay; the underlying manual/motion selection is retained. */
ainekio_p4_face_sample_t ainekio_p4_face_listen(ainekio_p4_face_sample_t previous,
                                             bool capturing, uint64_t elapsed_ms);

/* One replaceable display selection shared by library faces and workflow feedback.
 * Expiry is local to the body; releasing an old token cannot clear its replacement. */
typedef struct {
    size_t face;
    uint32_t revision;
    uint64_t started_ms, expires_ms;
    char token[AINEKIO_ASSET_NAME_MAX + 1U];
    bool active, background, legacy;
} ainekio_p4_face_selection_t;
bool ainekio_p4_face_select(ainekio_p4_face_selection_t *selection,
    const ainekio_face_selection_t *request, uint32_t revision, uint64_t now_ms);
ainekio_p4_face_sample_t ainekio_p4_face_selected(ainekio_p4_face_selection_t *selection,
    ainekio_p4_face_sample_t underlying, uint32_t revision, bool moving, bool talking, uint64_t now_ms);
