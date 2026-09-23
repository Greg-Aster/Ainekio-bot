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
add_executable(test_body test_body.c ../main/joint_calibration.c)
target_include_directories(test_body PRIVATE body_shim
    "../components/ainekio_pca9685/include")
target_link_libraries(test_body PRIVATE ainekio_v2_motion m)
target_compile_options(test_body PRIVATE -Wall -Wextra -Werror)
add_test(NAME body_execution COMMAND test_body)

add_executable(test_calibration_store test_calibration_store.c ../main/joint_calibration.c)
target_include_directories(test_calibration_store PRIVATE config_shim body_shim ../components/ainekio_pca9685/include)
target_compile_options(test_calibration_store PRIVATE -Wall -Wextra -Werror -ffunction-sections -fdata-sections)
target_link_options(test_calibration_store PRIVATE -Wl,--gc-sections)
target_link_libraries(test_calibration_store PRIVATE ainekio_v2_motion m)
add_test(NAME calibration_store COMMAND test_calibration_store)
