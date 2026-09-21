cmake_minimum_required(VERSION 3.16)
set(PROJECT_VER "0.4.0-p4-motions")
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../software/core"
                        "${CMAKE_CURRENT_LIST_DIR}/../../software/models/v2-12servo")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ainekio_p4_body)
