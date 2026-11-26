if(NOT ESP_PLATFORM)
    cmake_minimum_required(VERSION 3.16)
    project(ainekio_v1_model C)
    enable_testing()
    add_compile_options(-UNDEBUG)
endif()

set(V1_MODEL_SOURCES
    v1_kinematics.c
    v1_motion.c
    v1_microduck.c
    motions/microduck/v1_microduck_data.c
)

if(ESP_PLATFORM)
    idf_component_register(
        SRCS ${V1_MODEL_SOURCES}
        INCLUDE_DIRS "include"
        REQUIRES core
    )
    target_compile_options(${COMPONENT_LIB} PRIVATE -O3)
else()
    add_library(ainekio_v1_model STATIC ${V1_MODEL_SOURCES})
    target_include_directories(ainekio_v1_model PUBLIC include)
    target_link_libraries(ainekio_v1_model PUBLIC m)
    target_compile_options(ainekio_v1_model PRIVATE -O3 -Wall -Wextra -Werror)

    add_executable(test_v1_model tests/test_v1_model.c)
    target_link_libraries(test_v1_model PRIVATE ainekio_v1_model m)
    target_compile_options(test_v1_model PRIVATE -Wall -Wextra -Werror)
    add_test(NAME v1_model_unit COMMAND test_v1_model)
endif()
