# IDF 5.5.4 panic_print_char writes directly to hardware, bypassing both
# esp_log_set_vprintf and ROM output channels. Tee each character to the bounded
# IRAM recorder without changing the existing panic output or reset behavior.
# Compile a project-local copy; do not modify the installed SDK.
idf_component_get_property(panic_lib esp_system COMPONENT_LIB)
idf_component_get_property(panic_dir esp_system COMPONENT_DIR)
set(panic_source "${panic_dir}/panic.c")
file(READ "${panic_source}" panic_contents)
string(REPLACE
"void panic_print_char(const char c)\n{"
"extern void ainekio_p4_log_panic_character(char c);\nvoid panic_print_char(const char c)\n{\n    ainekio_p4_log_panic_character(c);"
    panic_contents "${panic_contents}")
set(panic_copy "${CMAKE_BINARY_DIR}/ainekio-idf/panic.c")
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/ainekio-idf")
file(CONFIGURE OUTPUT "${panic_copy}" CONTENT "${panic_contents}" @ONLY)
get_target_property(panic_sources ${panic_lib} SOURCES)
list(FILTER panic_sources EXCLUDE REGEX "(^|/)panic\\.c$")
set_property(TARGET ${panic_lib} PROPERTY SOURCES "${panic_sources}")
target_sources(${panic_lib} PRIVATE "${panic_copy}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${panic_source}")
