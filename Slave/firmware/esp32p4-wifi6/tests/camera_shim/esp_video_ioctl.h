#pragma once
#include <time.h>
#include <linux/videodev2.h>
#define VIDIOC_S_DQBUF_TIMEOUT _IOW('V', 200, struct timeval)
typedef struct { uint32_t regaddr, value; } esp_cam_sensor_reg_val_t;
typedef union { struct { unsigned pclk; } isp_v1_info; } esp_cam_sensor_isp_info_t;
typedef struct {
    unsigned width, height;
    const esp_cam_sensor_isp_info_t *isp_info;
} esp_cam_sensor_format_t;
struct v4l2_sensor_format_enum { uint32_t index; esp_cam_sensor_format_t format; };
#define VIDIOC_S_SENSOR_FMT _IOWR('V', 201, esp_cam_sensor_format_t)
#define VIDIOC_ENUM_SENSOR_FMT _IOWR('V', 210, struct v4l2_sensor_format_enum)
#define V4L2_CTRL_CLASS_ESP_CAM_IOCTL 0x00a70000
#define ESP_CAM_SENSOR_IOC_S_REG (0x07 | (sizeof(esp_cam_sensor_reg_val_t) << 16))
#define ESP_CAM_SENSOR_IOC_G_REG (0x08 | (sizeof(esp_cam_sensor_reg_val_t) << 16))
