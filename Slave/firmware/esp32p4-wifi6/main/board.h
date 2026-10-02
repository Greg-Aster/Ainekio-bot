#ifndef AINEKIO_P4_BOARD_H
#define AINEKIO_P4_BOARD_H

#include "ainekio/pca9685.h"
#include "esp_err.h"

/* ESP32-P4-WIFI6 schematic: dedicate a separate HP I2C bus to servo signals.
 * GPIO7/8 are reserved for onboard codec/camera. GPIO24/25 and native HS USB
 * remain reserved for future host communication. No servo supply is switched. */
#define AINEKIO_P4_PCA_SDA 2
#define AINEKIO_P4_PCA_SCL 3
#define AINEKIO_P4_PCA_OE 4
#define AINEKIO_P4_PCA_ADDRESS 0x40

esp_err_t ainekio_p4_board_init(void);
ainekio_pca9685_t *ainekio_p4_output(void);
/* Last failed servo-bus ESP-IDF result; retained until the next failure/reboot. */
esp_err_t ainekio_p4_i2c_error(void);
void ainekio_p4_board_identify(void);

#endif
