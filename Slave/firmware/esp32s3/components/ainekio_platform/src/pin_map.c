#include "ainekio/platform/pin_map.h"

#include <stddef.h>

#include "driver/gpio.h"
#include "soc/soc_caps.h"

#define ASSERT_NOT_SD(pin)                                                        \
    _Static_assert((pin) != AINEKIO_PIN_SD_CMD && (pin) != AINEKIO_PIN_SD_CLK && \
                       (pin) != AINEKIO_PIN_SD_DAT0,                              \
                   "accessory pin conflicts with board-mounted SD_MMC")

ASSERT_NOT_SD(AINEKIO_PIN_SERVO_R1);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_R2);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_L1);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_L2);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_R4);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_R3);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_L3);
ASSERT_NOT_SD(AINEKIO_PIN_SERVO_L4);
ASSERT_NOT_SD(AINEKIO_PIN_BATTERY_ADC);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_MIC_DIN);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_AMP_DOUT);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_BCLK);
ASSERT_NOT_SD(AINEKIO_PIN_I2S_WS);
ASSERT_NOT_SD(AINEKIO_PIN_I2C_SDA);
ASSERT_NOT_SD(AINEKIO_PIN_I2C_SCL);

_Static_assert(AINEKIO_PIN_I2C_SDA == AINEKIO_PIN_BOOT,
               "OLED SDA must retain the GPIO0 boot-button handoff");
_Static_assert(AINEKIO_PIN_I2C_SCL == AINEKIO_PIN_UART_TX,
               "OLED SCL must retain the GPIO43 boot-UART handoff");

const ainekio_servo_pin_t ainekio_servo_pins[AINEKIO_SERVO_COUNT] = {
    {AINEKIO_JOINT_R1, "R1", AINEKIO_PIN_SERVO_R1, 0U, 0U, 0U, true},
    {AINEKIO_JOINT_R2, "R2", AINEKIO_PIN_SERVO_R2, 0U, 0U, 1U, true},
    {AINEKIO_JOINT_L1, "L1", AINEKIO_PIN_SERVO_L1, 0U, 1U, 0U, true},
    {AINEKIO_JOINT_L2, "L2", AINEKIO_PIN_SERVO_L2, 0U, 1U, 1U, true},
    {AINEKIO_JOINT_R4, "R4", AINEKIO_PIN_SERVO_R4, 0U, 2U, 0U, true},
    {AINEKIO_JOINT_R3, "R3", AINEKIO_PIN_SERVO_R3, 0U, 2U, 1U, true},
    {AINEKIO_JOINT_L3, "L3", AINEKIO_PIN_SERVO_L3, 1U, 0U, 0U, true},
    {AINEKIO_JOINT_L4, "L4", AINEKIO_PIN_SERVO_L4, 1U, 0U, 1U, true},
};

bool ainekio_pin_is_reserved_for_sd(int gpio)
{
    return gpio == AINEKIO_PIN_SD_CMD || gpio == AINEKIO_PIN_SD_CLK ||
           gpio == AINEKIO_PIN_SD_DAT0;
}

bool ainekio_pin_is_reserved_for_psram(int gpio)
{
    return gpio >= 33 && gpio <= 37;
}

static bool claim_pin(int gpio, bool output, uint64_t *claimed)
{
    if (!GPIO_IS_VALID_GPIO(gpio) || (output && !GPIO_IS_VALID_OUTPUT_GPIO(gpio)) ||
        ainekio_pin_is_reserved_for_psram(gpio) ||
        (*claimed & (UINT64_C(1) << gpio)) != 0U) {
        return false;
    }
    *claimed |= UINT64_C(1) << gpio;
    return true;
}

bool ainekio_pin_map_valid(void)
{
    uint64_t claimed = 0U;
    /* GPIO0 and GPIO43 are claimed once by I2C after their boot-time roles. */
    const int output_pins[] = {
        AINEKIO_PIN_I2S_AMP_DOUT, AINEKIO_PIN_I2S_BCLK,
        AINEKIO_PIN_I2S_WS,       AINEKIO_PIN_I2C_SDA,
        AINEKIO_PIN_I2C_SCL,      AINEKIO_PIN_SD_CMD,
        AINEKIO_PIN_SD_CLK,       AINEKIO_PIN_CAMERA_XCLK,
        AINEKIO_PIN_CAMERA_SCCB_SDA,
        AINEKIO_PIN_CAMERA_SCCB_SCL,
    };
    const int input_pins[] = {
        AINEKIO_PIN_BATTERY_ADC,  AINEKIO_PIN_I2S_MIC_DIN,
        AINEKIO_PIN_UART_RX,      AINEKIO_PIN_SD_DAT0,
        AINEKIO_PIN_CAMERA_D0,
        AINEKIO_PIN_CAMERA_D1,    AINEKIO_PIN_CAMERA_D2,
        AINEKIO_PIN_CAMERA_D3,    AINEKIO_PIN_CAMERA_D4,
        AINEKIO_PIN_CAMERA_D5,    AINEKIO_PIN_CAMERA_D6,
        AINEKIO_PIN_CAMERA_D7,    AINEKIO_PIN_CAMERA_VSYNC,
        AINEKIO_PIN_CAMERA_HREF,  AINEKIO_PIN_CAMERA_PCLK,
    };
    for (size_t index = 0U; index < sizeof(output_pins) / sizeof(output_pins[0]);
         ++index) {
        if (!claim_pin(output_pins[index], true, &claimed)) {
            return false;
        }
    }
    for (size_t index = 0U; index < sizeof(input_pins) / sizeof(input_pins[0]);
         ++index) {
        if (!claim_pin(input_pins[index], false, &claimed)) {
            return false;
        }
    }

    uint32_t mcpwm_slots = 0U;
    for (uint8_t index = 0U; index < AINEKIO_SERVO_COUNT; ++index) {
        const ainekio_servo_pin_t *pin = &ainekio_servo_pins[index];
        if (pin->joint_id != index || pin->label == NULL ||
            ainekio_pin_is_reserved_for_sd(pin->gpio) ||
            pin->mcpwm_group >= SOC_MCPWM_GROUPS ||
            pin->mcpwm_operator >= SOC_MCPWM_OPERATORS_PER_GROUP ||
            pin->mcpwm_generator >= SOC_MCPWM_GENERATORS_PER_OPERATOR ||
            !claim_pin(pin->gpio, true, &claimed)) {
            return false;
        }
        const uint8_t slot = (uint8_t)(
            (pin->mcpwm_group * SOC_MCPWM_OPERATORS_PER_GROUP +
             pin->mcpwm_operator) *
                SOC_MCPWM_GENERATORS_PER_OPERATOR +
            pin->mcpwm_generator
        );
        if ((mcpwm_slots & (UINT32_C(1) << slot)) != 0U) {
            return false;
        }
        mcpwm_slots |= UINT32_C(1) << slot;
    }
    return true;
}
