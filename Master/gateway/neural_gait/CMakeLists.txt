cmake_minimum_required(VERSION 3.16)
project(ainekio_gait_native C)
get_filename_component(ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
add_subdirectory("${ROOT}/Slave/software/models/v2-12servo" motion)
set(P4 "${ROOT}/Slave/firmware/esp32p4-wifi6/main")
set(IMU "${ROOT}/Slave/software/imu")
set(PCA "${P4}/../components/ainekio_pca9685")
set(JSON "${P4}/../managed_components/espressif__cjson/cJSON")
add_library(gait_native SHARED native.c virtual_body.c "${PCA}/pca9685.c" "${P4}/joint_calibration.c"
  "${P4}/servo_feedback_model.c" "${P4}/servo_feedback_position.c"
  "${P4}/controller_motion.c" "${P4}/body_readings.c" "${P4}/gait_learning.c" "${P4}/imu_telemetry.c" "${JSON}/cJSON.c"
  "${IMU}/imu.c" "${IMU}/vendor/Fusion/Fusion/FusionAhrs.c")
target_include_directories(gait_native PRIVATE "${PCA}/include" "${P4}" "${IMU}/include"
  "${IMU}/vendor/Fusion/Fusion" "${P4}/../tests/body_shim"
  "${P4}/../tests/imu_shim" "${P4}/../tests/ota_shim" "${PCA}/../ainekio_p4_media/include" "${JSON}")
target_link_libraries(gait_native PRIVATE ainekio_v2_motion m)
# Match Slave/software/imu/CMakeLists.txt on firmware and native builds.
target_compile_definitions(gait_native PRIVATE FUSION_USE_NORMAL_SQRT)
target_compile_options(gait_native PRIVATE -Wall -Wextra -Werror)
