set(AINEKIO_CORE_SOURCES
    "src/assets.c"
    "src/core.c"
    "src/binary_codec.c"
    "src/config_store.c"
    "src/control_codec.c"
    "src/control_encode.c"
    "src/battery.c"
    "src/protocol.c"
    "src/provisioning.c"
    "src/provisioning_portal.c"
    "src/sd_record.c"
    "src/servo.c"
    "src/settings.c"
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

    add_executable(ainekio_config_store_tests "tests/test_config_store.c")
    target_link_libraries(ainekio_config_store_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_config_store_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_servo_battery_tests "tests/test_servo_battery.c")
    target_link_libraries(ainekio_servo_battery_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_servo_battery_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_provisioning_portal_tests "tests/test_provisioning_portal.c")
    target_link_libraries(ainekio_provisioning_portal_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_provisioning_portal_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_asset_tests "tests/test_assets.c")
    target_link_libraries(ainekio_asset_tests PRIVATE ainekio_core)
    target_compile_definitions(
        ainekio_asset_tests
        PRIVATE
        AINEKIO_TEST_ASSET_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/../assets/seed"
    )

    add_executable(ainekio_control_decode_cli "tests/control_decode_cli.c")
    target_link_libraries(ainekio_control_decode_cli PRIVATE ainekio_core)
    target_compile_options(
        ainekio_control_decode_cli
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_binary_decode_cli "tests/binary_decode_cli.c")
    target_link_libraries(ainekio_binary_decode_cli PRIVATE ainekio_core)
    target_compile_options(
        ainekio_binary_decode_cli
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_control_encode_tests "tests/test_control_encode.c")
    target_link_libraries(ainekio_control_encode_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_control_encode_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_settings_tests "tests/test_settings.c")
    target_link_libraries(ainekio_settings_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_settings_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    add_executable(ainekio_sd_record_tests "tests/test_sd_record.c")
    target_link_libraries(ainekio_sd_record_tests PRIVATE ainekio_core)
    target_compile_options(
        ainekio_sd_record_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    target_compile_options(
        ainekio_asset_tests
        PRIVATE
        -Wall
        -Wextra
        -Werror
        -Wpedantic
    )

    enable_testing()
    add_test(NAME ainekio_core_tests COMMAND ainekio_core_tests)
    add_test(NAME ainekio_provisioning_tests COMMAND ainekio_provisioning_tests)
    add_test(NAME ainekio_config_store_tests COMMAND ainekio_config_store_tests)
    add_test(NAME ainekio_servo_battery_tests COMMAND ainekio_servo_battery_tests)
    add_test(NAME ainekio_provisioning_portal_tests COMMAND ainekio_provisioning_portal_tests)
    add_test(NAME ainekio_asset_tests COMMAND ainekio_asset_tests)
    add_test(
        NAME ainekio_control_fixture_tests
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/run_control_fixtures.py"
            $<TARGET_FILE:ainekio_control_decode_cli>
            "${CMAKE_CURRENT_SOURCE_DIR}/../protocol/fixtures"
    )
    add_test(
        NAME ainekio_binary_fixture_tests
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/run_binary_fixtures.py"
            $<TARGET_FILE:ainekio_binary_decode_cli>
            "${CMAKE_CURRENT_SOURCE_DIR}/../protocol/fixtures/binary-v1.json"
    )
    add_test(NAME ainekio_control_encode_tests COMMAND ainekio_control_encode_tests)
    add_test(NAME ainekio_settings_tests COMMAND ainekio_settings_tests)
    add_test(NAME ainekio_sd_record_tests COMMAND ainekio_sd_record_tests)
endif()
