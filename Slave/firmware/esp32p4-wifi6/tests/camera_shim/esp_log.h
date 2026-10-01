#pragma once
void test_camera_log(const char *tag, const char *format, ...);
#define ESP_LOGI(...) test_camera_log(__VA_ARGS__)
#define ESP_LOGW(...) test_camera_log(__VA_ARGS__)
