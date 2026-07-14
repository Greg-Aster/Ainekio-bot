cmake_minimum_required(VERSION 3.16)

set(PROJECT_VER "0.1.0-foundation")
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../software/core")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ainekio_slave_brain)

littlefs_create_partition_image(
    littlefs
    "${CMAKE_CURRENT_LIST_DIR}/../../software/assets/seed"
    FLASH_IN_PROJECT
)
