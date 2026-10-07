#include "connection_screen.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint16_t previews[12][AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT];
static unsigned preview_count;

static void check_page(const ainekio_connection_page_t *page)
{
    assert(strlen(page->heading) <= 25);
    assert(strlen(page->footer) <= 50);
    for (unsigned i = 0; i < AINEKIO_SCREEN_LINES; ++i)
        assert(strlen(page->lines[i]) <= 25);
    struct { uint16_t before; uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT]; uint16_t after; } frame;
    frame.before = 0x1234; frame.after = 0x5678;
    memset(frame.pixels, 0x55, sizeof(frame.pixels));
    ainekio_connection_render(page, frame.pixels);
    assert(frame.before == 0x1234 && frame.after == 0x5678);
    if (page->face_visible)
        for (unsigned i = 0; i < AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT; ++i)
            assert(frame.pixels[i] == 0x5555);
}

static void preview(const ainekio_connection_page_t *page)
{
    check_page(page);
    assert(preview_count < 12);
    uint16_t *pixels = previews[preview_count++];
    if (page->face_visible) ainekio_face_render(0, 0, false, pixels);
    ainekio_connection_render(page, pixels);
}

int main(int argc, char **argv)
{
    ainekio_connection_page_t p;
    ainekio_connection_network_t n = {0};
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 0, &p);
    assert(!p.face_visible && strstr(p.heading, "Starting"));
    preview(&p);
    n.phase = AINEKIO_SCREEN_SEARCHING;
    n.has_saved_wifi = true;
    n.seconds_remaining = 51;
    strcpy(n.ssid, "Example Home");
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_ONLINE, 0, &p);
    /* A stale controller welcome cannot hide a lost Wi-Fi connection. */
    assert(!p.face_visible && strstr(p.footer, "51s"));
    preview(&p);
    n.phase = AINEKIO_SCREEN_SETUP;
    n.portal_ready = true;
    strcpy(n.setup_ssid, "Ainekio-P4-EXAMPLE");
    strcpy(n.setup_password, "ExampleOnly123abc");
    strcpy(n.setup_address, "192.168.4.1");
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 0, &p);
    assert(strstr(p.heading, "not found"));
    assert(!strcmp(p.lines[1], n.setup_ssid));
    assert(!strcmp(p.lines[4], n.setup_password));
    preview(&p);
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 12000, &p);
    assert(strstr(p.lines[0], "http://192.168.4.1/"));
    assert(p.page == 1 && p.pages == 2);
    preview(&p);
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 24000, &p);
    assert(p.page == 0);
    /* The longest allowed ASCII credentials must survive wrapping intact. */
    memset(n.setup_ssid, 'S', 32); n.setup_ssid[32] = 0;
    for (unsigned i = 0; i < 64; ++i) n.setup_password[i] = "aZ0!"[i % 4];
    n.setup_password[64] = 0;
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 0, &p);
    char joined[80];
    snprintf(joined, sizeof(joined), "%.25s%.25s", p.lines[1], p.lines[2]);
    assert(!strcmp(joined, n.setup_ssid));
    snprintf(joined, sizeof(joined), "%.25s%.25s%.25s", p.lines[4], p.lines[5], p.lines[6]);
    assert(!strcmp(joined, n.setup_password));
    preview(&p);
    n.setup_password[0] = 0;
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 0, &p);
    assert(strstr(p.lines[3], "No Wi-Fi password"));
    n.portal_ready = false;
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 0, &p);
    assert(strstr(p.heading, "unavailable"));
    assert(!strstr(p.lines[0], "http"));
    check_page(&p);
    n.phase = AINEKIO_SCREEN_RETRY;
    n.seconds_remaining = 23;
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_SEARCHING, 0, &p);
    assert(strstr(p.footer, "23s"));
    check_page(&p);
    n.phase = AINEKIO_SCREEN_WIFI_ONLINE;
    n.wifi_online = true;
    strcpy(n.address, "192.168.0.89");
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_UNAVAILABLE, 0, &p);
    assert(!p.face_visible && strstr(p.heading, "Body Control not found"));
    preview(&p);
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_AUTH_FAILED, 0, &p);
    assert(strstr(p.heading, "Pairing rejected"));
    preview(&p);
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_AUTH_FAILED, 12000, &p);
    assert(strstr(p.lines[6], "net ap"));
    preview(&p);
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_ONLINE, 0, &p);
    assert(p.face_visible && !p.footer[0]);
    for (unsigned i = 0; i < AINEKIO_SCREEN_LINES; ++i) assert(!p.lines[i][0]);
    preview(&p);
    assert(ainekio_connection_close_status(4001) == AINEKIO_SCREEN_GATEWAY_AUTH_FAILED);
    assert(ainekio_connection_close_status(4002) == AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED);
    assert(ainekio_connection_close_status(1006) == AINEKIO_SCREEN_GATEWAY_UNAVAILABLE);
    n.phase = AINEKIO_SCREEN_WIFI_FAILED;
    ainekio_connection_page(&n, AINEKIO_SCREEN_GATEWAY_ONLINE, 0, &p);
    preview(&p);
    p = (ainekio_connection_page_t){.face_visible=true};
    preview(&p);
    ainekio_face_warning_icons(true, false, previews[10]);
    preview(&p);
    ainekio_face_warning_icons(true, true, previews[11]);
    /* With no faults, every original face pixel is preserved. Active icons
     * affect only their small lower-margin regions; redraw clears them. */
    uint16_t baseline[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT];
    ainekio_face_render(0, 0, false, baseline);
    ainekio_face_warning_icons(false, false, baseline);
    assert(!memcmp(baseline, previews[8], sizeof(baseline)));
    unsigned changed = 0;
    for (unsigned y = 0; y < AINEKIO_FACE_HEIGHT; ++y)
        for (unsigned x = 0; x < AINEKIO_FACE_WIDTH; ++x) {
            unsigned i = y * AINEKIO_FACE_WIDTH + x;
            if (baseline[i] != previews[11][i]) {
                assert(y >= 144 && y < 164 && ((x >= 8 && x < 32) || (x >= 40 && x < 64)));
                ++changed;
            }
        }
    assert(changed > 0);
    /* Exercise every state and both rotating pages for bounds/text fit. */
    for (unsigned phase = 0; phase <= AINEKIO_SCREEN_WIFI_FAILED; ++phase)
        for (unsigned gateway = 0; gateway <= AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED; ++gateway)
            for (unsigned issue = 0; issue <= AINEKIO_SCREEN_WIFI_LOST; ++issue)
                for (unsigned page = 0; page < 2; ++page) {
                    n.phase = phase; n.wifi_issue = issue;
                    n.wifi_online = phase == AINEKIO_SCREEN_WIFI_ONLINE;
                    ainekio_connection_page(&n, gateway, page * 12000, &p);
                    check_page(&p);
                }
    if (argc == 2) {
        FILE *out = fopen(argv[1], "wb");
        assert(out);
        fprintf(out, "P6\n640 1020\n255\n");
        for (unsigned y = 0; y < 1020; ++y)
            for (unsigned x = 0; x < 640; ++x) {
                const unsigned tile = y / 170 * 2 + x / 320;
                uint16_t pixel = previews[tile][(y % 170) * 320 + x % 320];
                const unsigned char rgb[] = {(pixel >> 11) * 255 / 31,
                    ((pixel >> 5) & 63) * 255 / 63, (pixel & 31) * 255 / 31};
                fwrite(rgb, 1, 3, out);
            }
        fclose(out);
    }
    puts("Connection guidance and rendering passed");
    return 0;
}
