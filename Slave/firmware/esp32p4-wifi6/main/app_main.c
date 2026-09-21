#include "board.h"
#include "config.h"
#include "controller.h"
#include "network.h"

#include <stdio.h>
#include <string.h>
#include "esp_check.h"
#include "esp_console.h"
#include "esp_system.h"
#include "nvs_flash.h"

static int board_command(int argc, char **argv)
{
    (void)argc; (void)argv;
    ainekio_p4_board_identify();
    const ainekio_pca_status_t s = ainekio_pca_status(ainekio_p4_output());
    printf("output ready=%d armed=%d fault=%d wiring_verified=%d outstanding=%d\n",
           s.ready, s.armed, s.fault, s.wiring_verified, s.in_flight);
    return 0;
}

static int disable_command(int argc, char **argv)
{
    (void)argc; (void)argv;
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    puts("Emergency disable latched; this log is not electrical evidence.");
    return 0;
}

static int wiring_command(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "verified-no-servos") != 0) {
        puts("Only after documenting OE bias, 3.3 V logic and disconnected V+/servos:\n"
             "wiring verified-no-servos\nAcknowledgement is RAM-only and never arms outputs.");
        return 1;
    }
    ainekio_pca_verify_wiring(ainekio_p4_output(), true);
    puts("Operator acknowledged bench wiring; outputs remain disarmed.");
    return 0;
}

void app_main(void)
{
    ESP_ERROR_CHECK(ainekio_p4_board_init());
    ainekio_p4_board_identify();
    /* Do not erase an existing NVS partition on an initialization error. */
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(ainekio_p4_config_init());
    ESP_ERROR_CHECK(ainekio_p4_controller_start());
    ESP_ERROR_CHECK(ainekio_p4_network_start());
    esp_console_repl_t *repl = NULL;
    const esp_console_dev_uart_config_t uart = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    esp_console_repl_config_t config = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    config.prompt = "ainekio-p4>";
    config.max_cmdline_length = 1024;
    ESP_ERROR_CHECK(esp_console_new_repl_uart(&uart, &config, &repl));
    ESP_ERROR_CHECK(esp_console_register_help_command());
    const esp_console_cmd_t identify = {.command="board", .help="Board and output status", .func=board_command};
    const esp_console_cmd_t stop = {.command="disable", .help="Latch direct emergency output disable", .func=disable_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&identify));
    ESP_ERROR_CHECK(esp_console_cmd_register(&stop));
    const esp_console_cmd_t network = {.command="net", .help="Network status; net ap/retry/key", .func=ainekio_p4_network_command};
    const esp_console_cmd_t configure = {.command="config", .help="Configure Wi-Fi and selected controller; commits then restarts", .func=ainekio_p4_config_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&network));
    ESP_ERROR_CHECK(esp_console_cmd_register(&configure));
    const esp_console_cmd_t controller = {.command="controller", .help="Selected controller session and readiness", .func=ainekio_p4_controller_command};
    const esp_console_cmd_t wiring = {.command="wiring", .help="Acknowledge completed electrical checks; does not arm", .func=wiring_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&controller));
    const esp_console_cmd_t gait = {.command="gait", .help="Inspect installed geometric gait; no PWM output", .func=ainekio_p4_gait_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&gait));
    ESP_ERROR_CHECK(esp_console_cmd_register(&wiring));
    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}
