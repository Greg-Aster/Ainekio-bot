# ESP-IDF 5.5.4 releases the last DW-GDMA group's register clock before
# unregistering its shared interrupt. CSI STREAMOFF deletes that channel; an
# interrupt from another shared source can then read the unclocked status
# register (P4 load access fault at 0x50081030). Remove the interrupt first.
# Build a corrected SDK source in this build directory, leaving the installed
# SDK and managed components untouched. No driver API or framework upgrade.
idf_component_get_property(esp_hw_support_lib esp_hw_support COMPONENT_LIB)
idf_component_get_property(esp_hw_support_dir esp_hw_support COMPONENT_DIR)
set(dw_gdma_source "${esp_hw_support_dir}/dma/dw_gdma.c")
file(READ "${dw_gdma_source}" dw_gdma_contents)
string(REPLACE
"    if (chan->group) {
        channel_unregister_from_group(chan);
    }
    if (chan->intr) {
        esp_intr_free(chan->intr);
    }"
"    if (chan->intr) {
        esp_intr_free(chan->intr);
    }
    if (chan->group) {
        channel_unregister_from_group(chan);
    }"
    dw_gdma_contents "${dw_gdma_contents}")
set(dw_gdma_fixed "${CMAKE_BINARY_DIR}/ainekio-idf/dw_gdma.c")
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/ainekio-idf")
file(CONFIGURE OUTPUT "${dw_gdma_fixed}" CONTENT "${dw_gdma_contents}" @ONLY)
get_target_property(esp_hw_sources ${esp_hw_support_lib} SOURCES)
list(FILTER esp_hw_sources EXCLUDE REGEX "(^|/)dma/dw_gdma\\.c$")
set_property(TARGET ${esp_hw_support_lib} PROPERTY SOURCES "${esp_hw_sources}")
target_sources(${esp_hw_support_lib} PRIVATE "${dw_gdma_fixed}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${dw_gdma_source}")
