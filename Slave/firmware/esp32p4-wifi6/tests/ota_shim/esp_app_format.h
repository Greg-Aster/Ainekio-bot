#pragma once
#include <stdint.h>
#define ESP_IMAGE_HEADER_MAGIC 0xe9
#define ESP_CHIP_ID_ESP32P4 18
typedef struct { uint8_t magic; uint16_t chip_id; } esp_image_header_t;
typedef struct { uint32_t address, length; } esp_image_segment_header_t;
