idf_component_register(
    SRCS
        "src/asset_store.c"
        "src/audio_service.c"
        "src/battery_adc.c"
        "src/camera_service.c"
        "src/display_service.c"
        "src/mcpwm_adapter.c"
        "src/motion_service.c"
        "src/nvs_adapter.c"
        "src/pin_map.c"
        "src/provisioning_portal.c"
        "src/provisioning_service.c"
        "src/runtime_service.c"
        "src/sd_service.c"
        "src/sleep_service.c"
        "src/telemetry_service.c"
        "src/wake_word_service.cpp"
        "src/wifi_adapter.c"
    INCLUDE_DIRS "include"
    REQUIRES app_update core esp_adc esp_driver_gpio esp_driver_i2c esp_driver_i2s esp_driver_mcpwm esp_driver_sdmmc esp_event esp_http_server esp_netif esp_psram esp_timer esp_wifi espressif__esp32-camera espressif__esp-tflite-micro espressif__esp_websocket_client esphome__esp-micro-speech-features fatfs joltwallet__littlefs json mbedtls nvs_flash sdmmc
)
