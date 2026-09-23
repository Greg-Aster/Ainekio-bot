idf_component_register(
    SRCS "wake_word_service.cpp"
    INCLUDE_DIRS "include"
    REQUIRES core esp_psram json mbedtls espressif__esp-tflite-micro esphome__esp-micro-speech-features
)
