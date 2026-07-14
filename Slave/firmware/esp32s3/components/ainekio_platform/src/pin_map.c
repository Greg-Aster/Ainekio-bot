#include "ainekio/platform/pin_map.h"

#include <stddef.h>

#define MAP_B_SERVO_R1 1
#define MAP_B_SERVO_R2 2
#define MAP_B_SERVO_L1 14
#define MAP_B_SERVO_L2 21
#define MAP_B_SERVO_R4 33
#define MAP_B_SERVO_R3 34
#define MAP_B_SERVO_L3 45
#define MAP_B_SERVO_L4 46

#define ASSERT_NOT_SD(pin)                                                        \
    _Static_assert((pin) != AINEKIO_PIN_SD_CMD && (pin) != AINEKIO_PIN_SD_CLK && \
                       (pin) != AINEKIO_PIN_SD_DAT0,                              \
                   "accessory pin conflicts with board-mounted SD_MMC")

ASSERT_NOT_SD(MAP_B_SERVO_R1);
ASSERT_NOT_SD(MAP_B_SERVO_R2);
ASSERT_NOT_SD(MAP_B_SERVO_L1);
ASSERT_NOT_SD(MAP_B_SERVO_L2);
ASSERT_NOT_SD(MAP_B_SERVO_R4);
ASSERT_NOT_SD(MAP_B_SERVO_R3);
ASSERT_NOT_SD(MAP_B_SERVO_L3);
ASSERT_NOT_SD(MAP_B_SERVO_L4);
ASSERT_NOT_SD(AINEKIO_PIN_BATTERY_ADC);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_MIC_DIN);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_AMP_DOUT);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_BCLK);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_WS);
ASSERT_NOT_SD(AINEKIO_PIN_I2C_SDA);
ASSERT_NOT_SD(AINEKIO_PIN_I2C_SCL);

const ainekio_servo_pin_t ainekio_servo_pins[AINEKIO_SERVO_COUNT] = {
    {AINEKIO_JOINT_R1, "R1", MAP_B_SERVO_R1, 0U, 0U, 0U, true},
    {AINEKIO_JOINT_R2, "R2", MAP_B_SERVO_R2, 0U, 0U, 1U, true},
    {AINEKIO_JOINT_L1, "L1", MAP_B_SERVO_L1, 0U, 1U, 0U, true},
    {AINEKIO_JOINT_L2, "L2", MAP_B_SERVO_L2, 0U, 1U, 1U, true},
    {AINEKIO_JOINT_R4, "R4", MAP_B_SERVO_R4, 0U, 2U, 0U, true},
    {AINEKIO_JOINT_R3, "R3", MAP_B_SERVO_R3, 0U, 2U, 1U, true},
    {AINEKIO_JOINT_L3, "L3", MAP_B_SERVO_L3, 1U, 0U, 0U, true},
    {AINEKIO_JOINT_L4, "L4", MAP_B_SERVO_L4, 1U, 0U, 1U, true},
};

bool ainekio_pin_is_reserved_for_sd(int gpio)
{
    return gpio == AINEKIO_PIN_SD_CMD || gpio == AINEKIO_PIN_SD_CLK ||
           gpio == AINEKIO_PIN_SD_DAT0;
}

bool ainekio_pin_map_valid(void)
{
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        const ainekio_servo_pin_t *pin = &ainekio_servo_pins[index];
        if (pin->joint_id != index || pin->label == NULL ||
            ainekio_pin_is_reserved_for_sd(pin->gpio)) {
            return false;
        }
        for (uint8_t other = (uint8_t)(index + 1U); other < AINEKIO_SERVO_COUNT;
             ++other) {
            if (pin->gpio == ainekio_servo_pins[other].gpio) {
                return false;
            }
        }
    }
    return true;
}
