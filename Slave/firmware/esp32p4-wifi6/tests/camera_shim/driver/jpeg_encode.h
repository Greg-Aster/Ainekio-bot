#pragma once
#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>
typedef void *jpeg_encoder_handle_t;
typedef struct { int timeout_ms; } jpeg_encode_engine_cfg_t;
typedef struct { int buffer_direction; } jpeg_encode_memory_alloc_cfg_t;
typedef struct {
    int src_type, sub_sample, image_quality;
    unsigned width, height;
} jpeg_encode_cfg_t;
#define JPEG_ENC_ALLOC_OUTPUT_BUFFER 0
#define JPEG_ENC_ALLOC_INPUT_BUFFER 1
#define JPEG_ENCODE_IN_FORMAT_RGB565 0
#define JPEG_DOWN_SAMPLING_YUV420 0
esp_err_t jpeg_new_encoder_engine(const jpeg_encode_engine_cfg_t *config, jpeg_encoder_handle_t *encoder);
void *jpeg_alloc_encoder_mem(size_t size, const jpeg_encode_memory_alloc_cfg_t *config, size_t *allocated);
esp_err_t jpeg_encoder_process(jpeg_encoder_handle_t encoder, const jpeg_encode_cfg_t *config,
                              uint8_t *input, size_t input_size, uint8_t *output,
                              size_t capacity, uint32_t *encoded);
esp_err_t jpeg_del_encoder_engine(jpeg_encoder_handle_t encoder);
