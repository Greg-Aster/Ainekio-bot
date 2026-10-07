#include "connection_screen.h"
#include <stdio.h>
#include <string.h>

/* V1 status font, extended through ASCII 0x7e to preserve password case. */
static const uint8_t font_5x7[][5] = {
    {0x00,0x00,0x00,0x00,0x00},{0x00,0x00,0x5f,0x00,0x00},
    {0x00,0x07,0x00,0x07,0x00},{0x14,0x7f,0x14,0x7f,0x14},
    {0x24,0x2a,0x7f,0x2a,0x12},{0x23,0x13,0x08,0x64,0x62},
    {0x36,0x49,0x55,0x22,0x50},{0x00,0x05,0x03,0x00,0x00},
    {0x00,0x1c,0x22,0x41,0x00},{0x00,0x41,0x22,0x1c,0x00},
    {0x14,0x08,0x3e,0x08,0x14},{0x08,0x08,0x3e,0x08,0x08},
    {0x00,0x50,0x30,0x00,0x00},{0x08,0x08,0x08,0x08,0x08},
    {0x00,0x60,0x60,0x00,0x00},{0x20,0x10,0x08,0x04,0x02},
    {0x3e,0x51,0x49,0x45,0x3e},{0x00,0x42,0x7f,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46},{0x21,0x41,0x45,0x4b,0x31},
    {0x18,0x14,0x12,0x7f,0x10},{0x27,0x45,0x45,0x45,0x39},
    {0x3c,0x4a,0x49,0x49,0x30},{0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36},{0x06,0x49,0x49,0x29,0x1e},
    {0x00,0x36,0x36,0x00,0x00},{0x00,0x56,0x36,0x00,0x00},
    {0x08,0x14,0x22,0x41,0x00},{0x14,0x14,0x14,0x14,0x14},
    {0x00,0x41,0x22,0x14,0x08},{0x02,0x01,0x51,0x09,0x06},
    {0x32,0x49,0x79,0x41,0x3e},{0x7e,0x11,0x11,0x11,0x7e},
    {0x7f,0x49,0x49,0x49,0x36},{0x3e,0x41,0x41,0x41,0x22},
    {0x7f,0x41,0x41,0x22,0x1c},{0x7f,0x49,0x49,0x49,0x41},
    {0x7f,0x09,0x09,0x09,0x01},{0x3e,0x41,0x49,0x49,0x7a},
    {0x7f,0x08,0x08,0x08,0x7f},{0x00,0x41,0x7f,0x41,0x00},
    {0x20,0x40,0x41,0x3f,0x01},{0x7f,0x08,0x14,0x22,0x41},
    {0x7f,0x40,0x40,0x40,0x40},{0x7f,0x02,0x0c,0x02,0x7f},
    {0x7f,0x04,0x08,0x10,0x7f},{0x3e,0x41,0x41,0x41,0x3e},
    {0x7f,0x09,0x09,0x09,0x06},{0x3e,0x41,0x51,0x21,0x5e},
    {0x7f,0x09,0x19,0x29,0x46},{0x46,0x49,0x49,0x49,0x31},
    {0x01,0x01,0x7f,0x01,0x01},{0x3f,0x40,0x40,0x40,0x3f},
    {0x1f,0x20,0x40,0x20,0x1f},{0x3f,0x40,0x38,0x40,0x3f},
    {0x63,0x14,0x08,0x14,0x63},{0x07,0x08,0x70,0x08,0x07},
    {0x61,0x51,0x49,0x45,0x43},{0x00,0x7f,0x41,0x41,0x00},
    {0x02,0x04,0x08,0x10,0x20},{0x00,0x41,0x41,0x7f,0x00},
    {0x04,0x02,0x01,0x02,0x04},{0x40,0x40,0x40,0x40,0x40},
    {0x00,0x01,0x02,0x04,0x00},{0x20,0x54,0x54,0x54,0x78},
    {0x7f,0x48,0x44,0x44,0x38},{0x38,0x44,0x44,0x44,0x20},
    {0x38,0x44,0x44,0x48,0x7f},{0x38,0x54,0x54,0x54,0x18},
    {0x08,0x7e,0x09,0x01,0x02},{0x0c,0x52,0x52,0x52,0x3e},
    {0x7f,0x08,0x04,0x04,0x78},{0x00,0x44,0x7d,0x40,0x00},
    {0x20,0x40,0x44,0x3d,0x00},{0x7f,0x10,0x28,0x44,0x00},
    {0x00,0x41,0x7f,0x40,0x00},{0x7c,0x04,0x18,0x04,0x78},
    {0x7c,0x08,0x04,0x04,0x78},{0x38,0x44,0x44,0x44,0x38},
    {0x7c,0x14,0x14,0x14,0x08},{0x08,0x14,0x14,0x18,0x7c},
    {0x7c,0x08,0x04,0x04,0x08},{0x48,0x54,0x54,0x54,0x20},
    {0x04,0x3f,0x44,0x40,0x20},{0x3c,0x40,0x40,0x20,0x7c},
    {0x1c,0x20,0x40,0x20,0x1c},{0x3c,0x40,0x30,0x40,0x3c},
    {0x44,0x28,0x10,0x28,0x44},{0x0c,0x50,0x50,0x50,0x3c},
    {0x44,0x64,0x54,0x4c,0x44},{0x00,0x08,0x36,0x41,0x00},
    {0x00,0x00,0x7f,0x00,0x00},{0x00,0x41,0x36,0x08,0x00},
    {0x08,0x04,0x08,0x10,0x08},
};

static void line(ainekio_connection_page_t *p, unsigned row, const char *text)
{
    snprintf(p->lines[row], sizeof(p->lines[row]), "%s", text);
}

/* 25 characters at 2x fits the 320-pixel LCD. Wrap credentials without
 * changing case, adding ellipses, or dropping their final characters. */
static void wrapped(ainekio_connection_page_t *p, unsigned row, const char *text)
{
    while (*text && row < AINEKIO_SCREEN_LINES) {
        size_t n = strlen(text);
        if (n > 25) n = 25;
        memcpy(p->lines[row], text, n);
        p->lines[row++][n] = 0;
        text += n;
    }
}

void ainekio_connection_page(const ainekio_connection_network_t *n,
                            ainekio_connection_gateway_t gateway,
                            uint64_t elapsed_ms, ainekio_connection_page_t *p)
{
    memset(p, 0, sizeof(*p));
    p->pages = 1;
    if (n->phase == AINEKIO_SCREEN_SETUP && n->portal_ready) {
        p->pages = 2;
        p->page = (elapsed_ms / 12000) % p->pages;
        if (!p->page) {
            snprintf(p->heading, sizeof(p->heading), "%s", n->wifi_online ? "Change Wi-Fi" :
                n->has_saved_wifi ? "Connection not found" : "First-time setup");
            line(p, 0, "1. Join robot Wi-Fi:");
            wrapped(p, 1, n->setup_ssid);
            line(p, 3, n->setup_password[0] ? "Password (case matters):" : "No Wi-Fi password needed");
            wrapped(p, 4, n->setup_password);
            snprintf(p->footer, sizeof(p->footer), "1/2  Browser instructions in %us",
                12U - (unsigned)(elapsed_ms / 1000 % 12));
        } else {
            snprintf(p->heading, sizeof(p->heading), "2. Open setup page");
            snprintf(p->lines[0], sizeof(p->lines[0]), "http://%s/", n->setup_address);
            line(p, 2, "Enter new Wi-Fi name/key.");
            line(p, 3, "Check Body Control");
            line(p, 4, "address and pairing token");
            line(p, 5, "Save; robot restarts.");
            line(p, 6, "Then rejoin your Wi-Fi.");
            snprintf(p->footer, sizeof(p->footer), "2/2  Stay connected if 'no Internet'");
        }
        return;
    }
    if (n->phase == AINEKIO_SCREEN_SETUP) {
        snprintf(p->heading, sizeof(p->heading), "Setup page unavailable");
        line(p, 0, "Restart robot and retry.");
        line(p, 2, "USB console: net ap");
        line(p, 4, "Saved networks retained.");
        return;
    }
    if (n->phase == AINEKIO_SCREEN_WIFI_FAILED) {
        snprintf(p->heading, sizeof(p->heading), "Wi-Fi could not start");
        line(p, 0, "Restart robot and retry.");
        line(p, 2, "If it persists, inspect");
        line(p, 3, "the USB startup log.");
        return;
    }
    if (n->phase == AINEKIO_SCREEN_STARTING) {
        snprintf(p->heading, sizeof(p->heading), "Starting Wi-Fi");
        line(p, 1, "Looking for a connection.");
        line(p, 3, "Setup help appears here.");
        return;
    }
    if (!n->wifi_online) {
        snprintf(p->heading, sizeof(p->heading), "%s",
            n->wifi_issue == AINEKIO_SCREEN_WIFI_REJECTED ? "Wi-Fi login failed" :
            n->wifi_issue == AINEKIO_SCREEN_WIFI_NOT_FOUND ? "Network not found" :
            n->wifi_issue == AINEKIO_SCREEN_WIFI_LOST ? "Wi-Fi connection lost" :
            n->has_saved_wifi ? "Searching for Wi-Fi" : "No saved Wi-Fi");
        line(p, 0, n->has_saved_wifi ? "Searching saved networks:" : "Setup Wi-Fi is reopening.");
        wrapped(p, 1, n->ssid);
        line(p, 4, n->wifi_issue == AINEKIO_SCREEN_WIFI_REJECTED ? "Check Wi-Fi password in" : "Turn on your router or");
        line(p, 5, n->wifi_issue == AINEKIO_SCREEN_WIFI_REJECTED ? "setup when it opens." : "Body Control hotspot.");
        snprintf(p->footer, sizeof(p->footer), "Robot setup Wi-Fi opens in %us", n->seconds_remaining);
        return;
    }
    if (gateway == AINEKIO_SCREEN_GATEWAY_ONLINE) {
        p->face_visible = true;
        return;
    }
    p->pages = 2;
    p->page = (elapsed_ms / 12000) % p->pages;
    snprintf(p->heading, sizeof(p->heading), "%s",
        gateway == AINEKIO_SCREEN_GATEWAY_AUTH_FAILED ? "Pairing rejected" :
        gateway == AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED ? "Versions do not match" :
        gateway == AINEKIO_SCREEN_GATEWAY_HANDSHAKE ? "Pairing Body Control" :
        gateway == AINEKIO_SCREEN_GATEWAY_UNAVAILABLE ? "Body Control not found" : "Finding Body Control");
    if (!p->page) {
        line(p, 0, "Wi-Fi connected:");
        wrapped(p, 1, n->ssid);
        snprintf(p->lines[3], sizeof(p->lines[3]), "Robot IP: %s", n->address);
        if (gateway == AINEKIO_SCREEN_GATEWAY_AUTH_FAILED) {
            line(p, 5, "Check robot pairing token");
            line(p, 6, "in Body Control Settings.");
        } else if (gateway == AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED) {
            line(p, 5, "Update Body Control and");
            line(p, 6, "robot versions together.");
        } else {
            line(p, 5, "Start Body Control on the");
            line(p, 6, "configured computer.");
        }
        snprintf(p->footer, sizeof(p->footer), "1/2  Retrying; Wi-Fi is connected");
    } else {
        snprintf(p->heading, sizeof(p->heading), "Change connection");
        line(p, 0, "When online: Body Control");
        line(p, 1, "Settings > Robot Wi-Fi");
        line(p, 2, "and pairing.");
        line(p, 4, "No Wi-Fi: setup opens");
        line(p, 5, "after 60s of searching.");
        line(p, 6, "Or USB console: net ap");
        snprintf(p->footer, sizeof(p->footer), "2/2  Setup details appear here");
    }
}

ainekio_connection_gateway_t ainekio_connection_close_status(unsigned code)
{
    if (code == 4001) return AINEKIO_SCREEN_GATEWAY_AUTH_FAILED;
    if (code == 4002) return AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED;
    return AINEKIO_SCREEN_GATEWAY_UNAVAILABLE;
}

static void text(uint16_t *pixels, int x, int y, const char *s, int scale, uint16_t color)
{
    for (; *s; ++s, x += 6 * scale) {
        unsigned ch = (unsigned char)*s;
        if (ch < 32 || ch > 126) ch = '?';
        for (int col = 0; col < 5; ++col)
            for (int row = 0; row < 7; ++row)
                if (font_5x7[ch - 32][col] & (1U << row))
                    for (int dy = 0; dy < scale; ++dy)
                        for (int dx = 0; dx < scale; ++dx) {
                            int px = x + col * scale + dx, py = y + row * scale + dy;
                            if (px >= 0 && px < AINEKIO_FACE_WIDTH && py >= 0 && py < AINEKIO_FACE_HEIGHT)
                                pixels[py * AINEKIO_FACE_WIDTH + px] = color;
                        }
    }
}

void ainekio_connection_render(const ainekio_connection_page_t *p,
                              uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT])
{
    if (p->face_visible) return;
    memset(pixels, 0, AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT * sizeof(*pixels));
    text(pixels, 10, 9, p->heading, 2, 0x07ff);
    for (unsigned i = 0; i < AINEKIO_SCREEN_LINES; ++i)
        text(pixels, 10, 35 + i * 16, p->lines[i], 2, 0xffff);
    /* Instruction pages retain their page/countdown footer. */
    for (int y = 160; y < AINEKIO_FACE_HEIGHT; ++y)
        memset(pixels + y * AINEKIO_FACE_WIDTH, 0, AINEKIO_FACE_WIDTH * sizeof(*pixels));
    text(pixels, 10, 162, p->footer, 1, 0xbdf7);
}

static void warning_icon(uint16_t *pixels, int x, const uint32_t rows[20])
{
    for (int y = 0; y < 20; ++y)
        for (int col = 0; col < 24; ++col)
            pixels[(144 + y) * AINEKIO_FACE_WIDTH + x + col] =
                rows[y] & (1U << (23 - col)) ? 0xfd20 : 0;
}

void ainekio_face_warning_icons(bool motion_fault, bool camera_fault,
                               uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT])
{
    /* Bottom-left margin: no text strip, and no changes to eyes or voice bars.
     * A new face frame clears a resolved warning automatically. */
    static const uint32_t motion[20] = {
        0, 0x001800, 0x003c00, 0x006600, 0x006600,
        0x00c300, 0x018180, 0x018180, 0x0318c0, 0x061860,
        0x061860, 0x0c1830, 0x181818, 0x180018, 0x30180c,
        0x601806, 0x600006, 0x7ffffe, 0, 0,
    };
    static const uint32_t camera[20] = {
        0, 0x001f00, 0x003180, 0x7ffffe, 0x400006,
        0x401806, 0x406626, 0x408146, 0x410286, 0x410486,
        0x410886, 0x409106, 0x406206, 0x401c06, 0x404006,
        0x408006, 0x7ffffe, 0x020000, 0, 0,
    };
    if (motion_fault) warning_icon(pixels, 8, motion);
    if (camera_fault) warning_icon(pixels, 40, camera);
}
