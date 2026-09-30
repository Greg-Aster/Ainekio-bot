cmake_minimum_required(VERSION 3.16)
set(PROJECT_VER "0.7.0-p4-compact-motion")
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../software/core"
                        "${CMAKE_CURRENT_LIST_DIR}/../../software/imu"
                        "${CMAKE_CURRENT_LIST_DIR}/../../software/models/v2-12servo"
                        "${CMAKE_CURRENT_LIST_DIR}/../components/ainekio_wake")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ainekio_p4_body)

# Asset images exist only for the explicitly selected full partition layout.
# Building this target never changes a device's existing partition table.
partition_table_get_partition_info(AINEKIO_ASSET_SIZE "--partition-name littlefs" "size")
if(AINEKIO_ASSET_SIZE)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    set(AINEKIO_ASSET_STAGE "${CMAKE_BINARY_DIR}/ainekio-firmware-assets")
    add_custom_target(ainekio_firmware_assets
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/../../software/tools/stage_firmware_assets.py"
            --seed-dir "${CMAKE_CURRENT_LIST_DIR}/../../software/assets/seed"
            --local-dir "${CMAKE_CURRENT_LIST_DIR}/../../software/assets/local"
            --output-dir "${AINEKIO_ASSET_STAGE}" --profile p4
        COMMENT "Staging P4 voice and wake assets")
    littlefs_create_partition_image(littlefs "${AINEKIO_ASSET_STAGE}")
    add_dependencies(littlefs_littlefs_bin ainekio_firmware_assets)
endif()
