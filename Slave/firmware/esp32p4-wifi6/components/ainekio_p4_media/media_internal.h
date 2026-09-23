#pragma once
#include "ainekio/p4_media.h"
#include "driver/i2c_master.h"
esp_err_t p4_camera_start(i2c_master_bus_handle_t bus, const ainekio_p4_media_callbacks_t *callbacks);
bool p4_camera_ready(void);
uint32_t p4_camera_failures(void);
esp_err_t p4_camera_suspend(bool suspended);
void p4_camera_session(uint64_t session);
