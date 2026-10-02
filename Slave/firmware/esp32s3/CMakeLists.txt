cmake_minimum_required(VERSION 3.16)

set(PROJECT_VER "0.1.0-foundation")
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../software/core"
                        "${CMAKE_CURRENT_LIST_DIR}/../components/ainekio_wake"
                        "${CMAKE_CURRENT_LIST_DIR}/../components/ainekio_discovery")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ainekio_slave_brain)

find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(AINEKIO_ASSET_SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../software/assets/seed")
set(AINEKIO_LOCAL_ASSET_SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../software/assets/local")
set(AINEKIO_FIRMWARE_ASSET_DIR "${CMAKE_BINARY_DIR}/ainekio-firmware-assets")
set(AINEKIO_ASSET_STAGE_SCRIPT "${CMAKE_CURRENT_LIST_DIR}/../../software/tools/stage_firmware_assets.py")

add_custom_target(ainekio_firmware_assets
    COMMAND
        "${Python3_EXECUTABLE}"
        "${AINEKIO_ASSET_STAGE_SCRIPT}"
        --seed-dir "${AINEKIO_ASSET_SOURCE_DIR}"
        --local-dir "${AINEKIO_LOCAL_ASSET_SOURCE_DIR}"
        --output-dir "${AINEKIO_FIRMWARE_ASSET_DIR}"
    COMMENT "Staging firmware LittleFS assets with the device-local overlay"
)

littlefs_create_partition_image(
    littlefs
    "${AINEKIO_FIRMWARE_ASSET_DIR}"
)

add_dependencies(littlefs_littlefs_bin ainekio_firmware_assets)
