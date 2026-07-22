cmake_minimum_required(VERSION 3.16)

set(PROJECT_VER "0.1.0-foundation")
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../software/core")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ainekio_slave_brain)

set(AINEKIO_ASSET_SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../software/assets/seed")
set(AINEKIO_FIRMWARE_ASSET_DIR "${CMAKE_BINARY_DIR}/ainekio-firmware-assets")

add_custom_target(ainekio_firmware_assets
    COMMAND "${CMAKE_COMMAND}" -E remove_directory "${AINEKIO_FIRMWARE_ASSET_DIR}"
    COMMAND "${CMAKE_COMMAND}" -E copy_directory
        "${AINEKIO_ASSET_SOURCE_DIR}"
        "${AINEKIO_FIRMWARE_ASSET_DIR}"
    COMMAND "${CMAKE_COMMAND}" -E rm -f
        "${AINEKIO_FIRMWARE_ASSET_DIR}/motions-v1.json"
    COMMENT "Staging firmware LittleFS assets without emulator-only manifests"
)

littlefs_create_partition_image(
    littlefs
    "${AINEKIO_FIRMWARE_ASSET_DIR}"
    FLASH_IN_PROJECT
)

add_dependencies(littlefs_littlefs_bin ainekio_firmware_assets)
