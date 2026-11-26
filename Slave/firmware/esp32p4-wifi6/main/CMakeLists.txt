if(CONFIG_AINEKIO_MODEL_V1_8SERVO)
    set(AINEKIO_BODY_SRC "body_v1.c")
elseif(CONFIG_AINEKIO_MODEL_V3_12SERVO)
    set(AINEKIO_BODY_SRC "body_v3.c")
else()
    set(AINEKIO_BODY_SRC "body.c")
endif()

if(CONFIG_AINEKIO_DISPLAY_SSD1306)
    set(AINEKIO_DISPLAY_SRC "display_ssd1306.c")
elseif(CONFIG_AINEKIO_DISPLAY_ILI9341)
    set(AINEKIO_DISPLAY_SRC "display_ili9341.c")
else()
    set(AINEKIO_DISPLAY_SRC "display.c")
endif()

idf_component_register(SRCS "app_main.c" "board.c" "${AINEKIO_BODY_SRC}" "config.c" "joint_calibration.c" "network.c" "controller.c" "controller_motion.c" "body_readings.c"
                           "system.c" "idle_rest.c" "storage.c" "video_avi.c" "ota.c" "logs.c" "portal.c" "robot_settings.c" "gateway_selection.c"
                           "${AINEKIO_DISPLAY_SRC}" "face_timeline.c" "connection_screen.c" "imu_diagnostics.c" "imu_telemetry.c"
                           "servo_feedback.c" "servo_feedback_model.c" "servo_feedback_position.c"
                           "trajectory_program.c" INCLUDE_DIRS "."
    REQUIRES ainekio_discovery ainekio_pca9685 core imu v1-8servo v2-12servo v3-12servo esp_driver_gpio esp_driver_i2c esp_driver_uart
             esp_timer esp_system esp_wifi esp_event esp_netif nvs_flash console
             esp_websocket_client esp_hw_support json spi_flash esp_hosted mbedtls
             ainekio_p4_media ainekio_p4_assets app_update esp_http_server fatfs sdmmc esp_driver_sdmmc
             faces esp_lcd esp_driver_spi esp_adc
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
