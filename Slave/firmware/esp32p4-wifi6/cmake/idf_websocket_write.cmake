# ESP-IDF 5.5.4's WebSocket transport writes a frame header and then calls
# TCP write once for its payload. TCP may accept only a prefix. Returning that
# positive count makes esp_websocket_client emit another frame header inside
# the unfinished payload. Complete each frame's bytes before returning.
# As with the other pinned IDF fixes, compile a project-local source copy.
idf_component_get_property(ws_transport_lib tcp_transport COMPONENT_LIB)
idf_component_get_property(ws_transport_dir tcp_transport COMPONENT_DIR)
set(ws_transport_source "${ws_transport_dir}/transport_ws.c")
file(READ "${ws_transport_source}" ws_transport_contents)
set(ws_write_all [=[
extern bool ainekio_p4_controller_transport_active(void);

static int ainekio_ws_write_all(esp_transport_handle_t transport, const char *data, int length, int timeout_ms)
{
    int offset = 0;
    while (offset < length) {
        if (!ainekio_p4_controller_transport_active()) return -1;
        errno = 0;
        const int written = esp_transport_write(transport, data + offset, length - offset, timeout_ms);
        /* select() timing out is backpressure, not a broken TCP stream.
         * Continue this same frame; existing connection retirement cancels
         * the write. RX and command admission use their separate lock. */
        if (written == 0 || (written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))) continue;
        if (written < 0) return -1;
        offset += written;
    }
    return length;
}
]=])
string(REPLACE "static int _ws_write(" "${ws_write_all}\nstatic int _ws_write("
    ws_transport_contents "${ws_transport_contents}")
string(REPLACE [=[
    int poll_write;
    if ((poll_write = esp_transport_poll_write(ws->parent, timeout_ms)) <= 0) {
        ESP_LOGE(TAG, "Error transport_poll_write(%d)", poll_write);
        return poll_write;
    }
]=] "" ws_transport_contents "${ws_transport_contents}")
string(REPLACE [=[
    if (esp_transport_write(ws->parent, ws_header, header_len, timeout_ms) != header_len) {
        ESP_LOGE(TAG, "Error write header");
        return -1;
    }
    if (len == 0) {
        return 0;
    }

    int ret = esp_transport_write(ws->parent, buffer, len, timeout_ms);
]=] [=[
    int ret = ainekio_ws_write_all(ws->parent, ws_header, header_len, timeout_ms);
    if (ret == header_len) {
        ret = ainekio_ws_write_all(ws->parent, buffer, len, timeout_ms);
    }
]=] ws_transport_contents "${ws_transport_contents}")
set(ws_transport_fixed "${CMAKE_BINARY_DIR}/ainekio-idf/transport_ws.c")
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/ainekio-idf")
file(CONFIGURE OUTPUT "${ws_transport_fixed}" CONTENT "${ws_transport_contents}" @ONLY)
get_target_property(ws_transport_sources ${ws_transport_lib} SOURCES)
list(FILTER ws_transport_sources EXCLUDE REGEX "(^|/)transport_ws\\.c$")
set_property(TARGET ${ws_transport_lib} PROPERTY SOURCES "${ws_transport_sources}")
target_sources(${ws_transport_lib} PRIVATE "${ws_transport_fixed}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${ws_transport_source}")
