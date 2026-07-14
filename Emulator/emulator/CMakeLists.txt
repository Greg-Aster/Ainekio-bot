cmake_minimum_required(VERSION 3.16)
project(ainekio_host_emulator C)

add_library(
    ainekio_emulator_core
    SHARED
    body/core_bridge.c
    ../../Slave/software/core/src/core.c
    ../../Slave/software/core/src/protocol.c
)
target_include_directories(
    ainekio_emulator_core
    PRIVATE
    ../../Slave/software/core/include
)
target_compile_features(ainekio_emulator_core PRIVATE c_std_11)
target_compile_options(
    ainekio_emulator_core
    PRIVATE
    -Wall
    -Wextra
    -Werror
    -Wpedantic
)
