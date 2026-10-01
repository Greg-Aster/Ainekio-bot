#pragma once
#include "driver/i2c_master.h"
#include <stdbool.h>
typedef struct {
    struct { bool init_sccb; i2c_master_bus_handle_t i2c_handle; unsigned freq; } sccb_config;
    int reset_pin, pwdn_pin;
} esp_video_init_csi_config_t;
typedef struct { const esp_video_init_csi_config_t *csi; } esp_video_init_config_t;
#define ESP_VIDEO_INIT_FLAGS_MIPI_CSI 1
#define ESP_VIDEO_INIT_FLAGS_ISP 2
esp_err_t esp_video_init_with_flags(const esp_video_init_config_t *config, int flags);
esp_err_t esp_video_deinit_with_flags(int flags);
