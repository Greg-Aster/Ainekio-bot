cmake_minimum_required(VERSION 3.16)
project(ainekio_gait_native C)
get_filename_component(ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
add_subdirectory("${ROOT}/Slave/software/models/v2-12servo" motion)
set(P4 "${ROOT}/Slave/firmware/esp32p4-wifi6/main")
set(IMU "${ROOT}/Slave/software/imu")
set(FACES "${ROOT}/Slave/software/faces")
set(PCA "${P4}/../components/ainekio_pca9685")
set(JSON "${P4}/../managed_components/espressif__cjson/cJSON")
set(GAIT_NATIVE_SOURCES
  native.c virtual_body.c "${PCA}/pca9685.c" "${P4}/joint_calibration.c"
  "${P4}/servo_feedback_model.c" "${P4}/servo_feedback_position.c"
  "${P4}/controller_motion.c" "${P4}/body_readings.c" "${P4}/trajectory_program.c" "${P4}/imu_telemetry.c"
  "${P4}/face_timeline.c" "${FACES}/face.c" "${FACES}/face_cyclops.c" "${JSON}/cJSON.c"
  "${IMU}/imu.c" "${IMU}/vendor/Fusion/Fusion/FusionAhrs.c")
set(GAIT_NATIVE_INCLUDES
  "${PCA}/include" "${P4}" "${IMU}/include" "${FACES}/include"
  "${CMAKE_CURRENT_BINARY_DIR}/motion/walk"
  "${IMU}/vendor/Fusion/Fusion" "${P4}/../tests/body_shim"
  "${P4}/../tests/imu_shim" "${P4}/../tests/ota_shim" "${PCA}/../ainekio_p4_media/include" "${PCA}/../ainekio_p4_media" "${JSON}")

if(EMSCRIPTEN)
  add_executable(ainekio_v2_firmware ${GAIT_NATIVE_SOURCES})
  target_include_directories(ainekio_v2_firmware PRIVATE ${GAIT_NATIVE_INCLUDES})
  target_link_libraries(ainekio_v2_firmware PRIVATE ainekio_v2_motion m)
  target_compile_definitions(ainekio_v2_firmware PRIVATE FUSION_USE_NORMAL_SQRT)
  target_compile_options(ainekio_v2_firmware PRIVATE -O3 -Wall -Wextra -Werror -Wno-implicit-const-int-float-conversion)
  set_target_properties(ainekio_v2_firmware PROPERTIES
    OUTPUT_NAME "ainekio-v2-firmware"
    SUFFIX ".mjs")
  target_link_options(ainekio_v2_firmware PRIVATE
    -O3
    -sMODULARIZE=1
    -sEXPORT_ES6=1
    -sENVIRONMENT=web,worker
    -sALLOW_MEMORY_GROWTH=1
    -sWASM_BIGINT=1
    -sINITIAL_MEMORY=16777216
    "-sEXPORTED_FUNCTIONS=['_malloc','_free','_simulation_new','_simulation_free','_simulation_imu','_simulation_feedback','_virtual_body_reset','_virtual_body_close','_virtual_body_tick','_virtual_body_telemetry','_virtual_body_open','_virtual_body_connection_lost','_virtual_body_hello','_virtual_body_receive','_virtual_body_events','_virtual_body_feedback','_virtual_body_set_full_parity','_virtual_body_set_face_style','_virtual_body_set_media_state','_virtual_body_status','_virtual_body_heartbeat','_virtual_body_feedback_health','_virtual_body_media_actions','_virtual_body_mic_gate','_virtual_body_mic_frame','_virtual_body_camera_frame','_virtual_body_face_frame']"
    "-sEXPORTED_RUNTIME_METHODS=['ccall','cwrap','UTF8ToString','stringToUTF8','lengthBytesUTF8','HEAPU8','HEAPF64','HEAP32']")
else()
  add_library(gait_native SHARED ${GAIT_NATIVE_SOURCES})
  target_include_directories(gait_native PRIVATE ${GAIT_NATIVE_INCLUDES})
  target_link_libraries(gait_native PRIVATE ainekio_v2_motion m)
  # Match Slave/software/imu/CMakeLists.txt on firmware and native builds.
  target_compile_definitions(gait_native PRIVATE FUSION_USE_NORMAL_SQRT)
  target_compile_options(gait_native PRIVATE -Wall -Wextra -Werror)
endif()
