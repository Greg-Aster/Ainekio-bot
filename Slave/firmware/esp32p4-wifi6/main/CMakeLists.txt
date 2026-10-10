if(CONFIG_AINEKIO_DISPLAY_SSD1306)
    set(AINEKIO_DISPLAY_SOURCE "display_ssd1306.c")
else()
    set(AINEKIO_DISPLAY_SOURCE "display.c")
endif()

idf_component_register(SRCS "app_main.c" "board.c" "body.c" "config.c" "joint_calibration.c" "network.c" "controller.c"
                           "system.c" "storage.c" "portal.c" "robot_settings.c" "gateway_selection.c"
                           "${AINEKIO_DISPLAY_SOURCE}" "face_timeline.c" "connection_screen.c" INCLUDE_DIRS "."
    REQUIRES ainekio_discovery ainekio_pca9685 core imu v2-12servo esp_driver_gpio esp_driver_i2c esp_driver_uart
             esp_timer esp_system esp_wifi esp_event esp_netif nvs_flash console
             esp_websocket_client esp_hw_support json spi_flash esp_hosted mbedtls
             ainekio_p4_media ainekio_p4_assets app_update esp_http_server fatfs sdmmc esp_driver_sdmmc
             faces esp_lcd esp_driver_spi
    PRIV_REQUIRES esp_app_format)

# Optional maintenance image, built from the same pinned Hosted package. This
# adds a real console update command only when an image is explicitly supplied.
if(AINEKIO_C6_IMAGE)
    if(NOT EXISTS "${AINEKIO_C6_IMAGE}")
        message(FATAL_ERROR "AINEKIO_C6_IMAGE does not exist")
    endif()
    file(SHA256 "${AINEKIO_C6_IMAGE}" C6_SHA256)
    target_add_binary_data(${COMPONENT_LIB} "${AINEKIO_C6_IMAGE}" BINARY RENAME_TO c6_firmware)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE AINEKIO_C6_IMAGE_INCLUDED=1 AINEKIO_C6_SHA256="${C6_SHA256}")
endif()
