# esp_video 2.5.0 does not retain capture completion time in its buffer queue.
# Compile generated source/header copies, as with the other pinned dependency
# repairs. Managed files remain untouched. Every component source must see the
# same private buffer layout, including headers that include one another.
idf_component_get_property(video_lib espressif__esp_video COMPONENT_LIB)
idf_component_get_property(video_dir espressif__esp_video COMPONENT_DIR)
set(video_copy "${CMAKE_BINARY_DIR}/ainekio-idf/esp_video")
file(MAKE_DIRECTORY "${video_copy}/private_include")
file(GLOB video_headers "${video_dir}/private_include/*.h")
foreach(header IN LISTS video_headers)
    get_filename_component(name "${header}" NAME)
    configure_file("${header}" "${video_copy}/private_include/${name}" COPYONLY)
endforeach()
file(READ "${video_dir}/private_include/esp_video_buffer.h" buffer_contents)
string(REPLACE "    uint32_t valid_size;"
    "    int64_t completed_us; /* Device clock at transfer completion, before queueing. */\n    uint32_t valid_size;"
    buffer_contents "${buffer_contents}")
file(CONFIGURE OUTPUT "${video_copy}/private_include/esp_video_buffer.h"
    CONTENT "${buffer_contents}" @ONLY)
target_include_directories(${video_lib} BEFORE PRIVATE "${video_copy}/private_include")

file(READ "${video_dir}/src/esp_video.c" video_contents)
string(REPLACE "#include <stdio.h>" "#include <stdio.h>\n#include \"esp_timer.h\""
    video_contents "${video_contents}")
string(REPLACE "        element->valid_size = n;"
    "        element->completed_us = esp_timer_get_time();\n        element->valid_size = n;"
    video_contents "${video_contents}")
file(CONFIGURE OUTPUT "${video_copy}/esp_video.c" CONTENT "${video_contents}" @ONLY)

file(READ "${video_dir}/src/esp_video_ioctl.c" ioctl_contents)
string(REPLACE "    vbuf->bytesused = element->valid_size;"
    "    vbuf->bytesused = element->valid_size;\n    vbuf->timestamp.tv_sec = element->completed_us / 1000000;\n    vbuf->timestamp.tv_usec = element->completed_us % 1000000;\n    if (element->completed_us > 0) vbuf->flags |= V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC | V4L2_BUF_FLAG_TSTAMP_SRC_EOF;"
    ioctl_contents "${ioctl_contents}")
file(CONFIGURE OUTPUT "${video_copy}/esp_video_ioctl.c" CONTENT "${ioctl_contents}" @ONLY)
get_target_property(video_sources ${video_lib} SOURCES)
list(FILTER video_sources EXCLUDE REGEX "(^|/)src/esp_video(_ioctl)?\\.c$")
set_property(TARGET ${video_lib} PROPERTY SOURCES "${video_sources}")
target_sources(${video_lib} PRIVATE "${video_copy}/esp_video.c" "${video_copy}/esp_video_ioctl.c")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${video_dir}/src/esp_video.c" "${video_dir}/src/esp_video_ioctl.c")
