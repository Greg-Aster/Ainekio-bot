#ifndef AINEKIO_PLATFORM_PIN_MAP_H
#define AINEKIO_PLATFORM_PIN_MAP_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/protocol.h"
#include "sdkconfig.h"

#if !CONFIG_AINEKIO_PIN_MAP_B
#error "No reviewed Ainekio ESP32-S3 pin map is selected"
#endif

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
bool ainekio_pin_map_valid(void);

#endif
