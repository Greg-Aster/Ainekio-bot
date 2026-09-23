idf_component_register(
    SRCS "media.c" "camera.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES core ainekio_p4_assets ainekio_wake esp_driver_i2c esp_driver_i2s esp_driver_gpio
             esp_driver_jpeg esp_timer nvs_flash espressif__esp_codec_dev espressif__esp_video espressif__esp-sr
)
