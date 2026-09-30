if(NOT ESP_PLATFORM)
    cmake_minimum_required(VERSION 3.16)
    project(ainekio_v2_motion C)
    enable_testing()
    add_compile_options(-UNDEBUG) # Assertions are required even in Release tests.
    add_subdirectory("../../core" "core")
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    set(PYTHON "${Python3_EXECUTABLE}")
endif()

set(WALK_OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/walk")
file(MAKE_DIRECTORY "${WALK_OUTPUT}")
set(CLIP_OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/clip")
file(MAKE_DIRECTORY "${CLIP_OUTPUT}")
set(SERVO_OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/servo")
file(MAKE_DIRECTORY "${SERVO_OUTPUT}")
set(MOTION_SOURCES motion.c walk_kinematics.c clip.c joint_limits.c transition.c "${SERVO_OUTPUT}/servo_data.c" "${WALK_OUTPUT}/walk_data.c" "${CLIP_OUTPUT}/clip_data.c")
if(ESP_PLATFORM)
    idf_component_register(SRCS ${MOTION_SOURCES}
        INCLUDE_DIRS "include" PRIV_INCLUDE_DIRS "${WALK_OUTPUT}" "${CLIP_OUTPUT}" "${SERVO_OUTPUT}" REQUIRES core)
else()
    add_library(ainekio_v2_motion STATIC ${MOTION_SOURCES})
    target_include_directories(ainekio_v2_motion PUBLIC include PRIVATE "${WALK_OUTPUT}" "${CLIP_OUTPUT}" "${SERVO_OUTPUT}")
    target_link_libraries(ainekio_v2_motion PUBLIC ainekio_core m)
    target_compile_options(ainekio_v2_motion PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_executable(test_v2_limits tests/test_limits.c)
    target_link_libraries(test_v2_limits PRIVATE ainekio_v2_motion m)
    add_test(NAME v2_limits COMMAND test_v2_limits)
    add_executable(test_v2_direct tests/test_direct_geometry.c)
    target_include_directories(test_v2_direct PRIVATE "${WALK_OUTPUT}")
    target_link_libraries(test_v2_direct PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_direct PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_direct_geometry COMMAND test_v2_direct)
    add_executable(test_v2_motion tests/test_motion.c)
    target_link_libraries(test_v2_motion PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_motion PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_motion COMMAND test_v2_motion)
    add_executable(test_v2_locomotion tests/test_locomotion.c)
    target_include_directories(test_v2_locomotion PRIVATE "${WALK_OUTPUT}")
    target_link_libraries(test_v2_locomotion PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_locomotion PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_locomotion COMMAND test_v2_locomotion)
    add_test(NAME v2_crab_geometry COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_crab_geometry.py" $<TARGET_FILE:v2_walk_command>)
    set_tests_properties(v2_crab_geometry PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME v2_gait_geometry COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tools/validate_walk.py" $<TARGET_FILE:v2_walk_command>)
    set_tests_properties(v2_gait_geometry PROPERTIES SKIP_RETURN_CODE 77)
    add_executable(test_v2_run tests/test_run.c)
    target_include_directories(test_v2_run PRIVATE "${WALK_OUTPUT}")
    target_link_libraries(test_v2_run PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_run PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_run COMMAND test_v2_run)
    add_executable(test_v2_gait_timing tests/test_gait_timing.c)
    target_link_libraries(test_v2_gait_timing PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_gait_timing PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_gait_timing COMMAND test_v2_gait_timing)
    add_executable(v2_walk_sample tests/sample_cli.c)
    target_link_libraries(v2_walk_sample PRIVATE ainekio_v2_motion)
    add_test(NAME v2_walk_source COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_source.py"
        $<TARGET_FILE:v2_walk_sample> $<TARGET_FILE:v2_walk_solve> $<TARGET_FILE:v2_walk_command>)
    add_executable(v2_walk_solve tests/solve_cli.c)
    target_link_libraries(v2_walk_solve PRIVATE ainekio_v2_motion)
    add_executable(v2_walk_command tests/walk_command_cli.c)
    target_link_libraries(v2_walk_command PRIVATE ainekio_v2_motion)
    add_test(NAME v2_run_source COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_run_source.py"
        $<TARGET_FILE:v2_walk_command>)
    add_executable(test_v2_clips tests/test_clips.c)
    target_link_libraries(test_v2_clips PRIVATE ainekio_v2_motion m)
    target_compile_options(test_v2_clips PRIVATE -Wall -Wextra -Werror -Wpedantic)
    add_test(NAME v2_clips COMMAND test_v2_clips)
    add_executable(v2_clip_sample tests/clip_sample_cli.c)
    target_link_libraries(v2_clip_sample PRIVATE ainekio_v2_motion)
    add_test(NAME v2_gesture_source COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_clip_source.py"
        $<TARGET_FILE:v2_clip_sample>)
    add_test(NAME v2_upright COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_upright.py")
    add_test(NAME v2_clip_compiler COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tests/test_clip_compiler.py")
    add_test(NAME v2_locomotion_generator COMMAND "${PYTHON}"
        "${CMAKE_CURRENT_LIST_DIR}/tests/test_locomotion_generator.py" $<TARGET_FILE:v2_walk_command>)
    set_tests_properties(v2_locomotion_generator PROPERTIES SKIP_RETURN_CODE 77)
endif()

add_custom_command(OUTPUT "${SERVO_OUTPUT}/servo_data.c" "${SERVO_OUTPUT}/servo_data.h"
    COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tools/compile_servo_profile.py" --out "${SERVO_OUTPUT}"
    DEPENDS tools/compile_servo_profile.py servo_profile.json
    VERBATIM)

file(GLOB GESTURE_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/reviewed.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/source.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/manifest.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/schema.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/execution-contract.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/posture.json"
                       "${CMAKE_CURRENT_LIST_DIR}/motions/gestures/*/posture-hulls.npz")
add_custom_command(OUTPUT "${CLIP_OUTPUT}/clip_data.c" "${CLIP_OUTPUT}/clip_data.h"
    COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tools/compile_clips.py" --out "${CLIP_OUTPUT}"
    DEPENDS tools/compile_clips.py model.json geometry.json
            motions/turns/sole-hulls.npz ${GESTURE_SOURCES}
            motions/gestures/catalog.json motions/gestures/execution-policy.json motions/gestures/reviewed-hulls.npz
    VERBATIM)

add_custom_command(OUTPUT "${WALK_OUTPUT}/walk_data.c" "${WALK_OUTPUT}/walk_data.h"
    COMMAND "${PYTHON}" "${CMAKE_CURRENT_LIST_DIR}/tools/compile_walk.py" --out "${WALK_OUTPUT}"
    DEPENDS tools/compile_walk.py model.json geometry.json motions/walk/reference.py
            motions/walk/manifest.json motions/walk/source.json
            motions/locomotion/config.json motions/locomotion/crab.json motions/locomotion/contact-hulls.json motions/locomotion/sole-profile.json motions/run/config.json servo_profile.json
            motions/gestures/sit/posture-hulls.npz
    VERBATIM)
