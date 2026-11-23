#include "ota.h"
#include "display.h"
#include "face_timeline.h"
#include "system.h"
#include "network.h"
#include "controller.h"
#include "board.h"
#include "ainekio/face.h"
#include "ainekio/p4_media.h"

#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdkconfig.h"

/* 2.8-inch ILI9341 SPI TFT (MSP2807, 320x240 landscape) driver for V3-on-P4.
 * Centers the 320x170 V3 Cyclops Eye face canvas vertically at y=35..204 with
 * clean black letterbox bars behind the cast Display Bezel aperture. */

enum {
    ILI9341_WIDTH = 320,
    ILI9341_HEIGHT = 240,
    ILI9341_Y_OFFSET = (ILI9341_HEIGHT - AINEKIO_FACE_HEIGHT) / 2,
    STRIPE_ROWS = 16,
};

static atomic_bool ready;
static atomic_uint shown_face, frames, render_max_us;
static portMUX_TYPE selection_lock = portMUX_INITIALIZER_UNLOCKED;
static ainekio_p4_face_selection_t selection;

#if CONFIG_AINEKIO_LCD_ENABLED
static esp_lcd_panel_io_handle_t io;
static SemaphoreHandle_t transferred;
static uint16_t *pixels, *stripe;
#endif

bool ainekio_p4_display_ready(void) { return atomic_load(&ready); }
const char *ainekio_p4_display_face(void) { return ainekio_face_name(atomic_load(&shown_face)); }

void ainekio_p4_display_token(uint64_t at_ms, char token[AINEKIO_ASSET_NAME_MAX + 1U])
{
    portENTER_CRITICAL(&selection_lock);
    strcpy(token, ainekio_p4_face_token(&selection, at_ms));
    portEXIT_CRITICAL(&selection_lock);
}

void ainekio_p4_display_restore(void)
{
    portENTER_CRITICAL(&selection_lock);
    selection.foreground.active = false;
    selection.background.active = false;
    portEXIT_CRITICAL(&selection_lock);
}

esp_err_t ainekio_p4_display_expression(const char *name)
{
    if (!name || strlen(name) > AINEKIO_ASSET_NAME_MAX) return ESP_ERR_INVALID_ARG;
    ainekio_face_selection_t request = {0};
    strcpy(request.expression, name);
    return ainekio_p4_display_select(&request);
}

esp_err_t ainekio_p4_display_select(const ainekio_face_selection_t *request)
{
    if (!atomic_load(&ready)) return ESP_ERR_INVALID_STATE;
    const ainekio_p4_body_status_t body = ainekio_p4_body_status();
    portENTER_CRITICAL(&selection_lock);
    const bool found = ainekio_p4_face_select(&selection, request, body.face_revision,
        esp_timer_get_time() / 1000);
    portEXIT_CRITICAL(&selection_lock);
    return found ? ESP_OK : ESP_ERR_NOT_FOUND;
}

#if CONFIG_AINEKIO_LCD_ENABLED
static bool transferred_callback(esp_lcd_panel_io_handle_t handle,
    esp_lcd_panel_io_event_data_t *event, void *context)
{
    (void)handle; (void)event; (void)context;
    BaseType_t wake = pdFALSE;
    xSemaphoreGiveFromISR(transferred, &wake);
    return wake == pdTRUE;
}

static esp_err_t ili_cmd(uint8_t cmd, const uint8_t *data, size_t len)
{
    return esp_lcd_panel_io_tx_param(io, cmd, data, len);
}

static esp_err_t ili_set_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1)
{
    const uint8_t col[4] = {(uint8_t)(x0 >> 8), (uint8_t)x0, (uint8_t)(x1 >> 8), (uint8_t)x1};
    const uint8_t row[4] = {(uint8_t)(y0 >> 8), (uint8_t)y0, (uint8_t)(y1 >> 8), (uint8_t)y1};
    esp_err_t e = ili_cmd(0x2A, col, 4);
    if (e == ESP_OK) e = ili_cmd(0x2B, row, 4);
    return e;
}

static esp_err_t ili_clear_black(void)
{
    memset(stripe, 0, ILI9341_WIDTH * STRIPE_ROWS * sizeof(*stripe));
    for (int y = 0; y < ILI9341_HEIGHT; y += STRIPE_ROWS) {
        int rows = ILI9341_HEIGHT - y;
        if (rows > STRIPE_ROWS) rows = STRIPE_ROWS;
        esp_err_t e = ili_set_window(0, (uint16_t)y, ILI9341_WIDTH - 1, (uint16_t)(y + rows - 1));
        if (e != ESP_OK) return e;
        e = esp_lcd_panel_io_tx_color(io, 0x2C, stripe, (size_t)ILI9341_WIDTH * (size_t)rows * sizeof(*stripe));
        if (e != ESP_OK) return e;
        xSemaphoreTake(transferred, portMAX_DELAY);
    }
    return ESP_OK;
}

static esp_err_t ili_init_panel(void)
{
    if (CONFIG_AINEKIO_LCD_RESET >= 0) {
        const gpio_config_t rst = {
            .pin_bit_mask = 1ULL << CONFIG_AINEKIO_LCD_RESET,
            .mode = GPIO_MODE_OUTPUT,
        };
        gpio_config(&rst);
        gpio_set_level(CONFIG_AINEKIO_LCD_RESET, 0);
        vTaskDelay(pdMS_TO_TICKS(20));
        gpio_set_level(CONFIG_AINEKIO_LCD_RESET, 1);
        vTaskDelay(pdMS_TO_TICKS(120));
    } else {
        ili_cmd(0x01, NULL, 0);
        vTaskDelay(pdMS_TO_TICKS(120));
    }

    static const uint8_t p_ef[] = {0x03, 0x80, 0x02};
    static const uint8_t p_cf[] = {0x00, 0xC1, 0x30};
    static const uint8_t p_ed[] = {0x64, 0x03, 0x12, 0x81};
    static const uint8_t p_e8[] = {0x85, 0x00, 0x78};
    static const uint8_t p_cb[] = {0x39, 0x2C, 0x00, 0x34, 0x02};
    static const uint8_t p_f7[] = {0x20};
    static const uint8_t p_ea[] = {0x00, 0x00};
    static const uint8_t p_c0[] = {0x23};
    static const uint8_t p_c1[] = {0x10};
    static const uint8_t p_c5[] = {0x3E, 0x28};
    static const uint8_t p_c7[] = {0x86};
    /* Landscape 320x240: MV=1 (0x20). Rotate 180 flips MX|MY (0xC0). BGR=0x08. */
#ifdef CONFIG_AINEKIO_LCD_ROTATE_180
    uint8_t madctl = 0xE0;
#else
    uint8_t madctl = 0x20;
#endif
#ifdef CONFIG_AINEKIO_LCD_BGR
    madctl |= 0x08;
#endif
    const uint8_t p_36[] = {madctl};
    static const uint8_t p_3a[] = {0x55}; /* 16-bit RGB565 */
    static const uint8_t p_b1[] = {0x00, 0x18};
    static const uint8_t p_b6[] = {0x08, 0x82, 0x27};
    static const uint8_t p_f2[] = {0x00};
    static const uint8_t p_26[] = {0x01};
    static const uint8_t p_e0[] = {0x0F,0x31,0x2B,0x0C,0x0E,0x08,0x4E,0xF1,0x37,0x07,0x10,0x03,0x0E,0x09,0x00};
    static const uint8_t p_e1[] = {0x00,0x0E,0x14,0x03,0x11,0x07,0x31,0xC1,0x48,0x08,0x0F,0x0C,0x31,0x36,0x0F};

    esp_err_t e = ili_cmd(0xEF, p_ef, sizeof(p_ef));
    if (e == ESP_OK) e = ili_cmd(0xCF, p_cf, sizeof(p_cf));
    if (e == ESP_OK) e = ili_cmd(0xED, p_ed, sizeof(p_ed));
    if (e == ESP_OK) e = ili_cmd(0xE8, p_e8, sizeof(p_e8));
    if (e == ESP_OK) e = ili_cmd(0xCB, p_cb, sizeof(p_cb));
    if (e == ESP_OK) e = ili_cmd(0xF7, p_f7, sizeof(p_f7));
    if (e == ESP_OK) e = ili_cmd(0xEA, p_ea, sizeof(p_ea));
    if (e == ESP_OK) e = ili_cmd(0xC0, p_c0, sizeof(p_c0));
    if (e == ESP_OK) e = ili_cmd(0xC1, p_c1, sizeof(p_c1));
    if (e == ESP_OK) e = ili_cmd(0xC5, p_c5, sizeof(p_c5));
    if (e == ESP_OK) e = ili_cmd(0xC7, p_c7, sizeof(p_c7));
    if (e == ESP_OK) e = ili_cmd(0x36, p_36, sizeof(p_36));
    if (e == ESP_OK) e = ili_cmd(0x3A, p_3a, sizeof(p_3a));
    if (e == ESP_OK) e = ili_cmd(0xB1, p_b1, sizeof(p_b1));
    if (e == ESP_OK) e = ili_cmd(0xB6, p_b6, sizeof(p_b6));
    if (e == ESP_OK) e = ili_cmd(0xF2, p_f2, sizeof(p_f2));
    if (e == ESP_OK) e = ili_cmd(0x26, p_26, sizeof(p_26));
    if (e == ESP_OK) e = ili_cmd(0xE0, p_e0, sizeof(p_e0));
    if (e == ESP_OK) e = ili_cmd(0xE1, p_e1, sizeof(p_e1));
#ifdef CONFIG_AINEKIO_LCD_INVERT
    if (e == ESP_OK) e = ili_cmd(0x21, NULL, 0);
#else
    if (e == ESP_OK) e = ili_cmd(0x20, NULL, 0);
#endif
    if (e == ESP_OK) e = ili_cmd(0x11, NULL, 0); /* SLPOUT */
    vTaskDelay(pdMS_TO_TICKS(120));
    if (e == ESP_OK) e = ili_clear_black();
    if (e == ESP_OK) e = ili_cmd(0x29, NULL, 0); /* DISPON */
    return e;
}

static esp_err_t draw(void)
{
    for (int y = 0; y < AINEKIO_FACE_HEIGHT; y += STRIPE_ROWS) {
        int rows = AINEKIO_FACE_HEIGHT - y;
        if (rows > STRIPE_ROWS) rows = STRIPE_ROWS;
        /* ILI9341 expects big-endian RGB565 bytes over 8-bit SPI. */
        const uint16_t *src = pixels + y * AINEKIO_FACE_WIDTH;
        const int count = rows * AINEKIO_FACE_WIDTH;
        for (int i = 0; i < count; ++i)
            stripe[i] = (uint16_t)((src[i] >> 8) | (src[i] << 8));
        const uint16_t y0 = (uint16_t)(ILI9341_Y_OFFSET + y);
        esp_err_t e = ili_set_window(0, y0, AINEKIO_FACE_WIDTH - 1, (uint16_t)(y0 + rows - 1));
        if (e != ESP_OK) return e;
        e = esp_lcd_panel_io_tx_color(io, 0x2C, stripe, (size_t)count * sizeof(*stripe));
        if (e != ESP_OK) return e;
        xSemaphoreTake(transferred, portMAX_DELAY);
    }
    return ESP_OK;
}

static void display_task(void *unused)
{
    (void)unused;
    bool sleeping = false;
    bool was_listening = false;
    uint64_t listening_since = 0;
    ainekio_p4_face_clock_t face_clock = {0};
    uint64_t connection_since = 0;
    int connection_phase = -1;
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        ainekio_connection_page_t page;
        const bool updating = ainekio_p4_ota_page(&page);
        const ainekio_body_state_t state = ainekio_p4_system_status().state;
        const bool sleep = !updating && (state == AINEKIO_STATE_DOZING || state == AINEKIO_STATE_DEEP_SLEEP);
        if (sleep != sleeping) {
            ili_cmd(sleep ? 0x28 : 0x29, NULL, 0);
            sleeping = sleep;
        }
        if (!sleep) {
            const uint64_t now = esp_timer_get_time() / 1000;
            const ainekio_p4_body_status_t body = ainekio_p4_body_status();
            ainekio_p4_face_sample_t sample = ainekio_p4_face_sample(&face_clock, &body, now);
            const ainekio_p4_media_status_t media = ainekio_p4_media_status();
            const bool talking = media.speaker_busy;
            portENTER_CRITICAL(&selection_lock);
            sample = ainekio_p4_face_selected(&selection, sample, body.face_revision, body.moving, talking, now);
            portEXIT_CRITICAL(&selection_lock);
            if (media.utterance_open && !was_listening) listening_since = now;
            was_listening = media.utterance_open;
            sample = ainekio_p4_face_listen(sample, media.utterance_open, now - listening_since);
            const uint64_t started = esp_timer_get_time();
            const ainekio_connection_network_t network = ainekio_p4_network_display_status();
            const ainekio_connection_gateway_t gateway = ainekio_p4_controller_display_status();
            const int phase = network.phase * 16 + (gateway == AINEKIO_SCREEN_GATEWAY_ONLINE ? 1 :
                gateway == AINEKIO_SCREEN_GATEWAY_AUTH_FAILED ? 2 :
                gateway == AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED ? 3 : 0);
            if (phase != connection_phase) { connection_phase = phase; connection_since = now; }
            if (!updating) ainekio_connection_page(&network, gateway, now - connection_since, &page);
            if (page.face_visible)
                ainekio_face_cyclops_render(sample.face, talking ? now : sample.elapsed_ms, talking, pixels);
            ainekio_connection_render(&page, pixels);
            if (page.face_visible) {
                const ainekio_pca_fault_t fault = ainekio_pca_status(ainekio_p4_output()).fault;
                const bool motion_fault = fault == AINEKIO_PCA_FAULT_IO ||
                    fault == AINEKIO_PCA_FAULT_DEADLINE || fault == AINEKIO_PCA_FAULT_PROGRESS;
                ainekio_face_warning_icons(motion_fault,
                    !media.camera_ready && media.camera_failures > 0, pixels);
            }
            const uint32_t elapsed = (uint32_t)(esp_timer_get_time() - started);
            if (elapsed > atomic_load(&render_max_us)) atomic_store(&render_max_us, elapsed);
            const esp_err_t e = draw();
            atomic_store(&ready, e == ESP_OK);
            if (e == ESP_OK) { atomic_store(&shown_face, sample.face); atomic_fetch_add(&frames, 1); }
            else ESP_LOGE("display", "ILI9341 SPI transfer: %s", esp_err_to_name(e));
        }
        vTaskDelayUntil(&last, pdMS_TO_TICKS(1000 / CONFIG_AINEKIO_LCD_FPS));
    }
}
#endif

esp_err_t ainekio_p4_display_start(void)
{
#if CONFIG_AINEKIO_LCD_ENABLED
    esp_err_t result;
    bool bus_started = false;
    pixels = heap_caps_malloc(AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT * sizeof(*pixels),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    stripe = heap_caps_malloc(ILI9341_WIDTH * STRIPE_ROWS * sizeof(*stripe),
        MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    transferred = xSemaphoreCreateBinary();
    if (!pixels || !stripe || !transferred) { result = ESP_ERR_NO_MEM; goto fail; }
    const spi_bus_config_t bus = {
        .sclk_io_num = CONFIG_AINEKIO_LCD_SCLK,
        .mosi_io_num = CONFIG_AINEKIO_LCD_MOSI,
        .miso_io_num = -1, .quadwp_io_num = -1, .quadhd_io_num = -1,
        .max_transfer_sz = ILI9341_WIDTH * STRIPE_ROWS * sizeof(*stripe),
    };
    result = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO);
    if (result != ESP_OK) goto fail;
    bus_started = true;
    const esp_lcd_panel_io_spi_config_t bus_io = {
        .dc_gpio_num = CONFIG_AINEKIO_LCD_DC,
        .cs_gpio_num = CONFIG_AINEKIO_LCD_CS,
        .pclk_hz = CONFIG_AINEKIO_LCD_SPI_HZ,
        .lcd_cmd_bits = 8, .lcd_param_bits = 8, .spi_mode = 0,
        .trans_queue_depth = 1,
        .on_color_trans_done = transferred_callback,
    };
    result = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST, &bus_io, &io);
    if (result != ESP_OK) goto fail;
    result = ili_init_panel();
    if (result != ESP_OK) goto fail;
    if (xTaskCreate(display_task, "face_ili9341", 4096, NULL, 2, NULL) != pdPASS) {
        result = ESP_ERR_NO_MEM;
        goto fail;
    }
    atomic_store(&ready, true);
    ESP_LOGI("display", "ILI9341 320x240 SPI2 (MSP2807); SCK=%d MOSI=%d CS=%d DC=%d RESET=%d",
        CONFIG_AINEKIO_LCD_SCLK, CONFIG_AINEKIO_LCD_MOSI, CONFIG_AINEKIO_LCD_CS,
        CONFIG_AINEKIO_LCD_DC, CONFIG_AINEKIO_LCD_RESET);
    return ESP_OK;
fail:
    if (io) { esp_lcd_panel_io_del(io); io = NULL; }
    if (bus_started) spi_bus_free(SPI2_HOST);
    if (transferred) { vSemaphoreDelete(transferred); transferred = NULL; }
    heap_caps_free(pixels); pixels = NULL;
    heap_caps_free(stripe); stripe = NULL;
    return result;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

int ainekio_p4_display_command(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "auto")) ainekio_p4_display_restore();
    else if (argc > 1 && !strcmp(argv[1], "list")) {
        for (size_t i = 0; i < ainekio_face_count(); ++i) puts(ainekio_face_name(i));
    } else if (argc > 1) {
        const esp_err_t e = ainekio_p4_display_expression(argv[1]);
        if (e != ESP_OK) { puts(esp_err_to_name(e)); return 1; }
    }
    printf("display=ili9341_320x240 driver_ready=%d face=%s frames=%u max_render_us=%u\n",
        ainekio_p4_display_ready(), ainekio_p4_display_face(),
        atomic_load(&frames), atomic_load(&render_max_us));
    return 0;
}
