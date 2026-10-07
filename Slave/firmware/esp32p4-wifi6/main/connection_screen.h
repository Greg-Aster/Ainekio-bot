#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "ainekio/face.h"

/* Read-only presentation data. This module never changes connection policy,
 * saved settings, body state or motion. Passwords are local LCD data only. */
typedef enum {
    AINEKIO_SCREEN_STARTING,
    AINEKIO_SCREEN_SEARCHING,
    AINEKIO_SCREEN_SETUP,
    AINEKIO_SCREEN_RETRY,
    AINEKIO_SCREEN_WIFI_ONLINE,
    AINEKIO_SCREEN_WIFI_FAILED,
} ainekio_connection_phase_t;

typedef enum {
    AINEKIO_SCREEN_WIFI_UNKNOWN,
    AINEKIO_SCREEN_WIFI_NOT_FOUND,
    AINEKIO_SCREEN_WIFI_REJECTED,
    AINEKIO_SCREEN_WIFI_LOST,
} ainekio_connection_wifi_issue_t;

typedef struct {
    ainekio_connection_phase_t phase;
    ainekio_connection_wifi_issue_t wifi_issue;
    bool wifi_online;
    bool has_saved_wifi;
    bool portal_ready;
    unsigned seconds_remaining;
    char ssid[33];
    char address[16];
    char setup_ssid[33];
    char setup_password[65];
    char setup_address[16];
} ainekio_connection_network_t;

typedef enum {
    AINEKIO_SCREEN_GATEWAY_SEARCHING,
    AINEKIO_SCREEN_GATEWAY_CONNECTING,
    AINEKIO_SCREEN_GATEWAY_HANDSHAKE,
    AINEKIO_SCREEN_GATEWAY_ONLINE,
    AINEKIO_SCREEN_GATEWAY_UNAVAILABLE,
    AINEKIO_SCREEN_GATEWAY_AUTH_FAILED,
    AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED,
} ainekio_connection_gateway_t;

enum { AINEKIO_SCREEN_LINES = 8, AINEKIO_SCREEN_LINE_BYTES = 80 };
typedef struct {
    bool face_visible;
    unsigned page, pages;
    char heading[32];
    char lines[AINEKIO_SCREEN_LINES][AINEKIO_SCREEN_LINE_BYTES];
    char footer[48];
} ainekio_connection_page_t;

/* Page rotation time is relative to the current connection phase. */
void ainekio_connection_page(const ainekio_connection_network_t *network,
                            ainekio_connection_gateway_t gateway,
                            uint64_t elapsed_ms, ainekio_connection_page_t *page);
/* Draw a full information page. A connected face is left entirely untouched. */
void ainekio_connection_render(const ainekio_connection_page_t *page,
                              uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT]);
/* Small amber telltales, visible only while an actual fault is active. */
void ainekio_face_warning_icons(bool motion_fault, bool camera_fault,
                               uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT]);
/* Only an explicit server close code identifies a rejected pairing/protocol. */
ainekio_connection_gateway_t ainekio_connection_close_status(unsigned code);
