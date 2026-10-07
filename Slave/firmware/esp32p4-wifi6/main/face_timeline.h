#pragma once
#include "body.h"
/* Pure selection, using motion time already advanced by the output owner. */
typedef struct { size_t face; uint64_t elapsed_ms; } ainekio_p4_face_sample_t;
ainekio_p4_face_sample_t ainekio_p4_face_sample(const ainekio_p4_body_status_t *body,
                                              uint64_t idle_ms);
/* Temporary audio overlay; the underlying manual/motion selection is retained. */
ainekio_p4_face_sample_t ainekio_p4_face_listen(ainekio_p4_face_sample_t previous,
                                             bool capturing, uint64_t elapsed_ms);
