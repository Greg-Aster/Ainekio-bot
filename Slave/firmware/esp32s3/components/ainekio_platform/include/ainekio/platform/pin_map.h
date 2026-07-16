#ifndef AINEKIO_PLATFORM_PIN_MAP_H
#define AINEKIO_PLATFORM_PIN_MAP_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/protocol.h"
#include "sdkconfig.h"

#if !CONFIG_AINEKIO_PIN_MAP_B
#error "No reviewed Ainekio ESP32-S3 pin map is selected"
#endif

#define AINEKIO_BOARD_PROFILE_ID "freenove-esp32s3-cam-n16r8-map-b"
#define AINEKIO_EXPECTED_FLASH_BYTES (16U * 1024U * 1024U)
#define AINEKIO_EXPECTED_PSRAM_BYTES (8U * 1024U * 1024U)

#define AINEKIO_PIN_BOOT 0
#define AINEKIO_PIN_BATTERY_ADC 3
#define AINEKIO_PIN_I2S_MIC_DIN 19
#define AINEKIO_PIN_I2S_AMP_DOUT 20
#define AINEKIO_PIN_I2S_BCLK 41
#define AINEKIO_PIN_I2S_WS 42
#define AINEKIO_PIN_I2C_SDA 47
#define AINEKIO_PIN_I2C_SCL 48
#define AINEKIO_PIN_UART_TX 43
#define AINEKIO_PIN_UART_RX 44

#define AINEKIO_PIN_SD_CMD 38
#define AINEKIO_PIN_SD_CLK 39
#define AINEKIO_PIN_SD_DAT0 40

#define AINEKIO_PIN_CAMERA_PWDN -1
#define AINEKIO_PIN_CAMERA_RESET -1
#define AINEKIO_PIN_CAMERA_XCLK 15
#define AINEKIO_PIN_CAMERA_SCCB_SDA 4
#define AINEKIO_PIN_CAMERA_SCCB_SCL 5
#define AINEKIO_PIN_CAMERA_D0 11
#define AINEKIO_PIN_CAMERA_D1 9
#define AINEKIO_PIN_CAMERA_D2 8
#define AINEKIO_PIN_CAMERA_D3 10
#define AINEKIO_PIN_CAMERA_D4 12
#define AINEKIO_PIN_CAMERA_D5 18
#define AINEKIO_PIN_CAMERA_D6 17
#define AINEKIO_PIN_CAMERA_D7 16
#define AINEKIO_PIN_CAMERA_VSYNC 6
#define AINEKIO_PIN_CAMERA_HREF 7
#define AINEKIO_PIN_CAMERA_PCLK 13

#define AINEKIO_PIN_SERVO_R1 1
#define AINEKIO_PIN_SERVO_R2 2
#define AINEKIO_PIN_SERVO_L1 14
#define AINEKIO_PIN_SERVO_L2 21
#define AINEKIO_PIN_SERVO_R4 33
#define AINEKIO_PIN_SERVO_R3 34
#define AINEKIO_PIN_SERVO_L3 45
#define AINEKIO_PIN_SERVO_L4 46

typedef struct {
    uint8_t joint_id;
    const char *label;
    int gpio;
    uint8_t mcpwm_group;
    uint8_t mcpwm_operator;
    uint8_t mcpwm_generator;
    bool positive_angle;
} ainekio_servo_pin_t;

extern const ainekio_servo_pin_t ainekio_servo_pins[AINEKIO_SERVO_COUNT];

bool ainekio_pin_is_reserved_for_sd(int gpio);
bool ainekio_pin_is_reserved_for_psram(int gpio);
bool ainekio_pin_map_valid(void);

#endif
