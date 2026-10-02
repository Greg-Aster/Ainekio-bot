cmake_minimum_required(VERSION 3.16)
project(ainekio_p4_native C)
enable_testing()
add_compile_options(-UNDEBUG) # Assertions must execute in optimized test builds.

add_executable(test_joint_calibration test_joint_calibration.c ../main/joint_calibration.c)
target_include_directories(test_joint_calibration PRIVATE ../main
    ../../../software/core/include ../../../software/models/v2-12servo/include)
target_compile_features(test_joint_calibration PRIVATE c_std_11)
target_compile_options(test_joint_calibration PRIVATE -Wall -Wextra -Werror -Wpedantic)
target_link_libraries(test_joint_calibration PRIVATE ainekio_v2_motion m)
add_test(NAME joint_calibration COMMAND test_joint_calibration)

# Compile the production output owner against a host scheduler/driver boundary
# and the same native model used by the firmware.
add_subdirectory("../../../software/models/v2-12servo" "v2_model")
add_subdirectory("../../../software/imu" "imu")
add_executable(test_body test_body.c ../main/joint_calibration.c)
target_include_directories(test_body PRIVATE body_shim
    "../components/ainekio_pca9685/include")
target_link_libraries(test_body PRIVATE ainekio_v2_motion m)
target_compile_options(test_body PRIVATE -Wall -Wextra -Werror)
add_test(NAME body_execution COMMAND test_body)

# Exercise the real camera owner; only hardware I/O and task scheduling are virtual.
add_executable(test_camera test_camera.c ../components/ainekio_p4_media/camera.c)
target_include_directories(test_camera PRIVATE camera_shim body_shim
    ../components/ainekio_p4_media ../components/ainekio_p4_media/include)
target_link_libraries(test_camera PRIVATE ainekio_core)
target_compile_options(test_camera PRIVATE -Wall -Wextra -Werror)
add_test(NAME camera_profiles_and_snapshots COMMAND test_camera)

add_executable(test_calibration_store test_calibration_store.c ../main/joint_calibration.c ../main/robot_settings.c)
target_include_directories(test_calibration_store PRIVATE config_shim body_shim ../components/ainekio_pca9685/include)
target_compile_options(test_calibration_store PRIVATE -Wall -Wextra -Werror -ffunction-sections -fdata-sections)
target_link_options(test_calibration_store PRIVATE -Wl,--gc-sections)
target_link_libraries(test_calibration_store PRIVATE ainekio_v2_motion m)
add_test(NAME calibration_store COMMAND test_calibration_store)

add_executable(test_robot_settings test_robot_settings.c ../main/robot_settings.c)
target_include_directories(test_robot_settings PRIVATE ../main)
target_compile_options(test_robot_settings PRIVATE -Wall -Wextra -Werror)
target_link_libraries(test_robot_settings PRIVATE ainekio_core)
add_test(NAME robot_settings COMMAND test_robot_settings)

add_executable(test_robot_settings_store test_robot_settings_store.c ../main/joint_calibration.c ../main/robot_settings.c)
target_include_directories(test_robot_settings_store PRIVATE config_shim body_shim ../components/ainekio_pca9685/include)
target_compile_options(test_robot_settings_store PRIVATE -Wall -Wextra -Werror -ffunction-sections -fdata-sections)
target_link_options(test_robot_settings_store PRIVATE -Wl,--gc-sections)
target_link_libraries(test_robot_settings_store PRIVATE ainekio_v2_motion m)
add_test(NAME robot_settings_store COMMAND test_robot_settings_store)

add_executable(test_gateway_selection test_gateway_selection.c ../main/gateway_selection.c ../main/robot_settings.c)
target_include_directories(test_gateway_selection PRIVATE ../main body_shim
    ../../components/ainekio_discovery/include)
target_compile_options(test_gateway_selection PRIVATE -Wall -Wextra -Werror -Wpedantic)
target_link_libraries(test_gateway_selection PRIVATE ainekio_core)
add_test(NAME gateway_selection_and_session_fencing COMMAND test_gateway_selection)

add_executable(test_gateway_discovery test_gateway_discovery.c ../../components/ainekio_discovery/local_discovery.c)
target_include_directories(test_gateway_discovery PRIVATE discovery_shim camera_shim
    ../../components/ainekio_discovery/include)
target_compile_options(test_gateway_discovery PRIVATE -Wall -Wextra -Werror -Wpedantic)
add_test(NAME shared_gateway_discovery COMMAND test_gateway_discovery)
