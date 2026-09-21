#include "board.h"
#include "controller.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdatomic.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_chip_info.h"
#include "esp_check.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static portMUX_TYPE gate_lock = portMUX_INITIALIZER_UNLOCKED;
static i2c_master_bus_handle_t bus;
static i2c_master_dev_handle_t device;
static ainekio_pca9685_t output;
static atomic_bool interrupt_arm;

void ainekio_p4_interrupt_arm(bool enable) { atomic_store(&interrupt_arm, enable); }

static void enter(void *context) { (void)context; portENTER_CRITICAL(&gate_lock); }
static void leave(void *context) { (void)context; portEXIT_CRITICAL(&gate_lock); }
static void disable(void *context, bool disabled)
{
    (void)context;
    gpio_set_level(AINEKIO_P4_PCA_OE, disabled ? 1 : 0);
}
static uint64_t now(void *context) { (void)context; return (uint64_t)esp_timer_get_time(); }
static void delay(void *context, uint32_t us) { (void)context; esp_rom_delay_us(us); }

static bool write_registers(void *context, uint8_t reg, const uint8_t *data,
                            size_t length, uint32_t timeout_ms)
{
    (void)context;
    if (length > 64U || !device) return false;
    uint8_t bytes[65];
    bytes[0] = reg;
    memcpy(bytes + 1, data, length);
    const bool ok = i2c_master_transmit(device, bytes, length + 1U, (int)timeout_ms) == ESP_OK;
    if (reg == 0x06 && length == 64 && atomic_exchange(&interrupt_arm, false))
        ainekio_pca_emergency_disable(&output, AINEKIO_PCA_FAULT_EMERGENCY);
    return ok;
}
static bool read_registers(void *context, uint8_t reg, uint8_t *data,
                           size_t length, uint32_t timeout_ms)
{
    (void)context;
    return device && i2c_master_transmit_receive(device, &reg, 1U, data, length,
                                                (int)timeout_ms) == ESP_OK;
}

static void supervisor(void *context)
{
    (void)context;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        ainekio_pca_supervise(&output);
        ainekio_p4_controller_supervise();
        xTaskDelayUntil(&wake, pdMS_TO_TICKS(5U));
    }
}

static void shutdown_outputs(void)
{
    ainekio_pca_emergency_disable(&output, AINEKIO_PCA_FAULT_EMERGENCY);
}

esp_err_t ainekio_p4_board_init(void)
{
    /* Preload the output latch before enabling the pad driver. The external
     * pull-up is still required during reset and cannot be proven in firmware. */
    gpio_set_level(AINEKIO_P4_PCA_OE, 1);
    const gpio_config_t oe = {
        .pin_bit_mask = UINT64_C(1) << AINEKIO_P4_PCA_OE,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&oe), "board", "OE configuration");
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_1,
        .sda_io_num = AINEKIO_P4_PCA_SDA,
        .scl_io_num = AINEKIO_P4_PCA_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        /* Internal pull-ups permit a bounded absent-device probe. They are
         * not accepted as the verified external bus pull-ups. */
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_config, &bus), "board", "PCA bus");
    const i2c_device_config_t device_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = AINEKIO_P4_PCA_ADDRESS,
        .scl_speed_hz = 400000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &device_config, &device), "board", "PCA device");
    const ainekio_pca_port_t port = {
        .lock = enter, .unlock = leave, .disable_output = disable,
        .now_us = now, .sleep_us = delay, .write = write_registers, .read = read_registers,
    };
    const ainekio_pca_config_t config = {.oscillator_hz = 25000000U, .frequency_hz = 50U};
    const ainekio_pca_result_t result = ainekio_pca_init(&output, &port, &config);
    ESP_LOGI("board", "PCA initialization=%d; wiring unverified; OE disabled", result);
    ESP_RETURN_ON_ERROR(esp_register_shutdown_handler(shutdown_outputs), "board", "shutdown gate");
    if (xTaskCreatePinnedToCore(supervisor, "output_guard", 3072, NULL,
                                configMAX_PRIORITIES - 1, NULL, 0) != pdPASS)
        return ESP_ERR_NO_MEM;
    return ESP_OK;
}

ainekio_pca9685_t *ainekio_p4_output(void) { return &output; }

void ainekio_p4_board_identify(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);
    uint32_t flash_size = 0;
    uint8_t mac[6];
    esp_flash_get_size(NULL, &flash_size);
    esp_read_mac(mac, ESP_MAC_BASE);
    printf("board=esp32-p4-wifi6 silicon=%u.%u cores=%u flash=%" PRIu32
           " idf=%s reset=%d mac=%02x:%02x:%02x:%02x:%02x:%02x\n",
           info.revision / 100, info.revision % 100, info.cores, flash_size,
           esp_get_idf_version(), esp_reset_reason(),
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    printf("PCA: SDA=%d SCL=%d OE=%d address=0x%02x; native USB HS P1 reserved\n",
           AINEKIO_P4_PCA_SDA, AINEKIO_P4_PCA_SCL, AINEKIO_P4_PCA_OE, AINEKIO_P4_PCA_ADDRESS);
}
