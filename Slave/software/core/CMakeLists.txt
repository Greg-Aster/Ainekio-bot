set(AINEKIO_CORE_SOURCES
    "src/core.c"
    "src/protocol.c"
    "src/provisioning.c"
)

if(ESP_PLATFORM)
    idf_component_register(
        SRCS ${AINEKIO_CORE_SOURCES}
        INCLUDE_DIRS "include"
    )
else()
    cmake_minimum_required(VERSION 3.16)
    project(ainekio_core C)

    add_library(ainekio_core STATIC ${AINEKIO_CORE_SOURCES})
    target_include_directories(ainekio_core PUBLIC "include")
    target_compile_features(ainekio_core PUBLIC c_std_11)
    target_compile_options(ainekio_core PRIVATE -Wall -Wextra -Werror -Wpedantic)

    add_executable(ainekio_core_tests "tests/test_core.c")
    target_link_libraries(ainekio_core_tests PRIVATE ainekio_core)
    target_compile_options(ainekio_core_tests PRIVATE -Wall -Wextra -Werror -Wpedantic)

    add_executable(ainekio_provisioning_tests "tests/test_provisioning.c")
    target_link_libraries(ainekio_provisioning_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_provisioning_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    enable_testing()
    add_test(NAME ainekio_core_tests COMMAND ainekio_core_tests)
    add_test(NAME ainekio_provisioning_tests COMMAND ainekio_provisioning_tests)
endif()
