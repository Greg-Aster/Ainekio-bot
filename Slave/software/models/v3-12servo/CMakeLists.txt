if(DEFINED ESP_PLATFORM)
    idf_component_register(
        SRCS
            "v3_kinematics.c"
            "v3_motion.c"
            "v3_microduck.c"
            "motions/microduck/v3_microduck_data.c"
        INCLUDE_DIRS "include"
    )
    return()
endif()

cmake_minimum_required(VERSION 3.16)
project(ainekio_v3_model C)

add_library(ainekio_v3_model STATIC
    v3_kinematics.c
    v3_motion.c
    v3_microduck.c
    motions/microduck/v3_microduck_data.c
)
target_include_directories(ainekio_v3_model PUBLIC include)
target_link_libraries(ainekio_v3_model PUBLIC m)

add_executable(test_v3_model tests/test_v3_model.c)
target_link_libraries(test_v3_model PRIVATE ainekio_v3_model m)
