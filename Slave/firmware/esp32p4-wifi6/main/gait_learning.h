#pragma once
#include "ainekio/v2_learning.h"
#include "esp_err.h"
struct httpd_req;
void ainekio_p4_learning_init(void);
void ainekio_p4_learning_begin(ainekio_v2_walk_state_t *walk);
void ainekio_p4_learning_frame(const ainekio_v2_walk_state_t *walk,uint32_t sequence,
    uint64_t now,ainekio_v2_frame_t *frame,
    bool (*valid)(const ainekio_v2_frame_t *,void *),void *context);
esp_err_t ainekio_p4_learning_http(struct httpd_req *request);
