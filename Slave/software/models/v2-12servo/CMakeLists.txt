if(NOT ESP_PLATFORM)
    cmake_minimum_required(VERSION 3.16)
    project(ainekio_v2_motion C)
    enable_testing()
    add_subdirectory("../../core" "core")
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    set(PYTHON "${Python3_EXECUTABLE}")
endif()

set(WALK_OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/walk")
file(MAKE_DIRECTORY "${WALK_OUTPUT}")
set(CLIP_OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/clip")
file(MAKE_DIRECTORY "${CLIP_OUTPUT}")
set(MOTION_SOURCES motion.c clip.c "${WALK_OUTPUT}/walk_data.c" "${CLIP_OUTPUT}/clip_data.c")
if(ESP_PLATFORM)
    idf_component_register(SRCS ${MOTION_SOURCES}
        INCLUDE_DIRS "include" PRIV_INCLUDE_DIRS "${WALK_OUTPUT}" "${CLIP_OUTPUT}" REQUIRES core)
else()
    add_library(ainekio_v2_motion STATIC ${MOTION_SOURCES})
    target_include_directories(ainekio_v2_motion PUBLIC include PRIVATE "${WALK_OUTPUT}" "${CLIP_OUTPUT}")
    target_link_libraries(ainekio_v2_motion PUBLIC ainekio_core)
    target_compile_options(ainekio_v2_motion PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_executable(test_v2_motion tests/test_motion.c)
    target_link_libraries(test_v2_motion PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_motion PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_motion COMMAND test_v2_motion)
    add_executable(v2_walk_sample tests/sample_cli.c)
    target_link_libraries(v2_walk_sample PRIVATE ainekio_v2_motion)
    add_test(NAME v2_walk_source COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_source.py"
        $<TARGET_FILE:v2_walk_sample>)
    add_executable(test_v2_clips tests/test_clips.c)
    target_link_libraries(test_v2_clips PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_clips PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_clips COMMAND test_v2_clips)
    add_executable(v2_clip_sample tests/clip_sample_cli.c)
    target_link_libraries(v2_clip_sample PRIVATE ainekio_v2_motion)
    add_test(NAME v2_turn_source COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_clip_source.py"
        $<TARGET_FILE:v2_clip_sample> turns)
    add_test(NAME v2_gesture_source COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_clip_source.py"
        $<TARGET_FILE:v2_clip_sample> gestures)
    add_test(NAME v2_clip_compiler COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_clip_compiler.py")
endif()

file(GLOB TURN_SOURCES "${CMAKE_CURRENT_LIST_DIR}/motions/turns/commands/*/source.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/turns/commands/*/manifest.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/turns/commands/*/schema.json")
file(GLOB GESTURE_SOURCES "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/source.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/manifest.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/schema.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/execution-contract.json")
add_custom_command(OUTPUT "${CLIP_OUTPUT}/clip_data.c" "${CLIP_OUTPUT}/clip_data.h"
    COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tools/compile_clips.py" --out "${CLIP_OUTPUT}"
    DEPENDS tools/compile_clips.py model.json geometry.json motions/turns/catalog.json
            motions/turns/sole-hulls.npz ${TURN_SOURCES} ${GESTURE_SOURCES}
            motions/gestures/catalog.json motions/gestures/execution-policy.json
    VERBATIM)

add_custom_command(OUTPUT "${WALK_OUTPUT}/walk_data.c" "${WALK_OUTPUT}/walk_data.h"
    COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tools/compile_walk.py" --out "${WALK_OUTPUT}"
    DEPENDS tools/compile_walk.py model.json geometry.json motions/walk/source.json
            motions/walk/manifest.json motions/walk/loop-contract.json
    VERBATIM)
