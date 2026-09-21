idf_component_register(SRCS "app_main.c" "board.c" "config.c" "network.c" "controller.c" INCLUDE_DIRS "."
    REQUIRES ainekio_pca9685 core v2-12servo esp_driver_gpio esp_driver_i2c esp_driver_uart
             esp_timer esp_system esp_wifi esp_event esp_netif nvs_flash console
             esp_websocket_client esp_hw_support json spi_flash esp_hosted mbedtls
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
