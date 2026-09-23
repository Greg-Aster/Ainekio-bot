#include "board.h"
#include "config.h"
#include "controller.h"
#include "network.h"
#include "system.h"
#include "ainekio/p4_assets.h"

#include <stdio.h>
#include <string.h>
#include "esp_check.h"
#include "esp_console.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static int board_command(int argc, char **argv)
{
    (void)argc; (void)argv;
    ainekio_p4_board_identify();
    const ainekio_pca_status_t s = ainekio_pca_status(ainekio_p4_output());
    printf("output ready=%d armed=%d fault=%d outstanding=%d\n",
           s.ready, s.armed, s.fault, s.in_flight);
    printf("console minimum_free_stack=%u bytes\n", (unsigned)uxTaskGetStackHighWaterMark(NULL));
    return 0;
}

static int disable_command(int argc, char **argv)
{
    (void)argc; (void)argv;
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    puts("Outputs disabled; use home to resume.");
    return 0;
}

void app_main(void)
{
    ESP_ERROR_CHECK(ainekio_p4_board_init());
    ainekio_p4_board_identify();
    /* Do not erase an existing NVS partition on an initialization error. */
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(ainekio_p4_config_init());
    ESP_ERROR_CHECK(ainekio_p4_system_start());
    ESP_ERROR_CHECK(ainekio_p4_network_prepare());
    /* Optional asset media must never format an existing filesystem or stop
     * body startup when no asset partition has been installed. */
    const esp_err_t assets = ainekio_p4_assets_init();
    if (assets != ESP_OK) printf("assets unavailable: %s\n", esp_err_to_name(assets));
    ESP_ERROR_CHECK(ainekio_p4_controller_start());
    const esp_err_t media = ainekio_p4_controller_media_start();
    if (media != ESP_OK) printf("media initialization: %s\n", esp_err_to_name(media));
    /* Complete one-time NVS provisioning before enabling PWM. Never retry a
     * stalled mechanism automatically following a watchdog or brownout reset. */
    const esp_reset_reason_t reset = esp_reset_reason();
    if (!ainekio_p4_calibration().saved) {
        puts("No saved joint mapping; startup leaves outputs disabled.");
    } else if (reset == ESP_RST_POWERON || reset == ESP_RST_EXT || reset == ESP_RST_SW ||
        reset == ESP_RST_USB || reset == ESP_RST_JTAG) {
        if (ainekio_p4_home_command(1, NULL) != 0) puts("automatic home unavailable; outputs disabled");
    } else printf("automatic home inhibited after reset=%d; use home to retry\n", reset);
    ESP_ERROR_CHECK(ainekio_p4_network_start());
    esp_console_repl_t *repl = NULL;
    const esp_console_dev_uart_config_t uart = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    esp_console_repl_config_t config = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    /* Keep the measured console stack budget for offline gait diagnostics. */
    config.task_stack_size = 12288;
    config.prompt = "ainekio-p4>";
    config.max_cmdline_length = 1024;
    ESP_ERROR_CHECK(esp_console_new_repl_uart(&uart, &config, &repl));
    ESP_ERROR_CHECK(esp_console_register_help_command());
    const esp_console_cmd_t identify = {.command="board", .help="Board and output status", .func=board_command};
    const esp_console_cmd_t stop = {.command="disable", .help="Latch direct emergency output disable", .func=disable_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&identify));
    ESP_ERROR_CHECK(esp_console_cmd_register(&stop));
    const esp_console_cmd_t network = {.command="net", .help="Network status; net ap/retry/key", .func=ainekio_p4_network_command};
    const esp_console_cmd_t configure = {.command="config", .help="Configure home, Wi-Fi or controller; commits then restarts", .func=ainekio_p4_config_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&network));
    ESP_ERROR_CHECK(esp_console_cmd_register(&configure));
    const esp_console_cmd_t controller = {.command="controller", .help="Selected controller session and readiness", .func=ainekio_p4_controller_command};
    const esp_console_cmd_t home = {.command="home", .help="Resume saved startup home after a stop", .func=ainekio_p4_home_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&controller));
    const esp_console_cmd_t system = {.command="system", .help="System status; profile/state/storage/restart", .func=ainekio_p4_system_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&system));
    const esp_console_cmd_t gait = {.command="gait", .help="Inspect installed geometric gait; no PWM output", .func=ainekio_p4_gait_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&gait));
    ESP_ERROR_CHECK(esp_console_cmd_register(&home));
    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}
