#include "ainekio/platform/display_service.h"

#include <ctype.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

#include "ainekio/platform/pin_map.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define DISPLAY_WIDTH 128U
#define DISPLAY_HEIGHT 64U
#define DISPLAY_PAGES 8U
#define DISPLAY_COMMAND_LINES 4U
#define DISPLAY_LINE_CHARS 21U
#define DISPLAY_TASK_PERIOD_MS 20U
#define DISPLAY_TASK_PRIORITY 2U
#define DISPLAY_I2C_HZ 400000U
#define DISPLAY_IO_TIMEOUT_MS 25

typedef enum {
    DISPLAY_COMMAND_FACE = 0,
    DISPLAY_COMMAND_STATUS,
    DISPLAY_COMMAND_IDLE,
    DISPLAY_COMMAND_RESTORE,
} display_command_kind_t;

typedef struct {
    display_command_kind_t kind;
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    ainekio_face_mode_t mode;
    bool override_mode;
    char lines[DISPLAY_COMMAND_LINES][DISPLAY_LINE_CHARS + 1U];
} display_command_t;

typedef enum {
    IDLE_WAIT = 0,
    IDLE_BLINK_ONE,
    IDLE_DOUBLE_GAP,
    IDLE_BLINK_TWO,
} idle_phase_t;

struct ainekio_display_service {
    ainekio_asset_store_t *assets;
    i2c_master_bus_handle_t bus;
    i2c_master_dev_handle_t device;
    TaskHandle_t task;
    QueueHandle_t queue;
    StaticQueue_t queue_control;
    uint8_t queue_storage[sizeof(display_command_t)];
    portMUX_TYPE state_lock;
    char desired_non_talk[AINEKIO_ASSET_NAME_MAX + 1U];
    const ainekio_face_index_entry_t *current_face;
    ainekio_face_mode_t current_mode;
    uint32_t animation_tick;
    int64_t next_frame_us;
    int64_t idle_due_us;
    idle_phase_t idle_phase;
    bool idle;
    uint8_t source_frame[AINEKIO_FACE_FRAME_BYTES];
    uint8_t display_buffer[AINEKIO_FACE_FRAME_BYTES];
    uint8_t transfer[129U];
};

static const char *TAG = "ainekio_display";
static ainekio_display_service_t singleton;

/* Columns for ASCII 0x20 through 0x5f in a compact 5x7 font. */
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
};

static int64_t now_us(void)
{
    return esp_timer_get_time();
}

static void copy_line(char output[DISPLAY_LINE_CHARS + 1U], const char *input)
{
    if (input == NULL) {
        output[0] = '\0';
        return;
    }
    (void)snprintf(output, DISPLAY_LINE_CHARS + 1U, "%s", input);
}

static void queue_command(
    ainekio_display_service_t *service,
    const display_command_t *command
)
{
    (void)xQueueOverwrite(service->queue, command);
}

static esp_err_t send_commands(
    ainekio_display_service_t *service,
    const uint8_t *commands,
    size_t length
)
{
    if (length + 1U > sizeof(service->transfer)) {
        return ESP_ERR_INVALID_SIZE;
    }
    service->transfer[0] = 0x00U;
    memcpy(&service->transfer[1], commands, length);
    return i2c_master_transmit(
        service->device,
        service->transfer,
        length + 1U,
        DISPLAY_IO_TIMEOUT_MS
    );
}

static esp_err_t send_buffer(ainekio_display_service_t *service)
{
    static const uint8_t window[] = {0x21U, 0x00U, 0x7fU, 0x22U, 0x00U, 0x07U};
    esp_err_t result = send_commands(service, window, sizeof(window));
    for (size_t offset = 0U; result == ESP_OK &&
         offset < sizeof(service->display_buffer); offset += 128U) {
        service->transfer[0] = 0x40U;
        memcpy(&service->transfer[1], &service->display_buffer[offset], 128U);
        result = i2c_master_transmit(
            service->device,
            service->transfer,
            129U,
            DISPLAY_IO_TIMEOUT_MS
        );
    }
    return result;
}

static void set_pixel(uint8_t *buffer, uint8_t x, uint8_t y)
{
    if (x < DISPLAY_WIDTH && y < DISPLAY_HEIGHT) {
        buffer[(size_t)(y / 8U) * DISPLAY_WIDTH + x] |= (uint8_t)(1U << (y % 8U));
    }
}

static void compiled_default_face(uint8_t *buffer)
{
    memset(buffer, 0, AINEKIO_FACE_FRAME_BYTES);
    for (uint8_t y = 18U; y < 31U; ++y) {
        for (uint8_t x = 28U; x < 42U; ++x) {
            set_pixel(buffer, x, y);
            set_pixel(buffer, (uint8_t)(127U - x), y);
        }
    }
    for (uint8_t x = 45U; x < 83U; ++x) {
        const uint8_t distance = x < 64U ? (uint8_t)(64U - x)
                                         : (uint8_t)(x - 64U);
        set_pixel(buffer, x, (uint8_t)(49U - distance / 5U));
        set_pixel(buffer, x, (uint8_t)(50U - distance / 5U));
    }
}

static void convert_bitmap(
    const uint8_t source[AINEKIO_FACE_FRAME_BYTES],
    uint8_t output[AINEKIO_FACE_FRAME_BYTES]
)
{
    memset(output, 0, AINEKIO_FACE_FRAME_BYTES);
    for (uint8_t y = 0U; y < DISPLAY_HEIGHT; ++y) {
        for (uint8_t x = 0U; x < DISPLAY_WIDTH; ++x) {
            const size_t source_index = (size_t)y * 16U + x / 8U;
            if ((source[source_index] & (uint8_t)(0x80U >> (x % 8U))) != 0U) {
                set_pixel(output, x, y);
            }
        }
    }
}

static const uint8_t *glyph(char character)
{
    const unsigned char upper = (unsigned char)toupper((unsigned char)character);
    if (upper < 0x20U || upper > 0x5fU) {
        return font_5x7['?' - 0x20];
    }
    return font_5x7[upper - 0x20U];
}

static void draw_text(uint8_t *buffer, uint8_t page, const char *text)
{
    if (text == NULL || page >= DISPLAY_PAGES) {
        return;
    }
    size_t x = 1U;
    for (size_t index = 0U; text[index] != '\0' && x + 5U < DISPLAY_WIDTH;
         ++index, x += 6U) {
        memcpy(&buffer[(size_t)page * DISPLAY_WIDTH + x], glyph(text[index]), 5U);
    }
}

static esp_err_t render_status(
    ainekio_display_service_t *service,
    const display_command_t *command
)
{
    memset(service->display_buffer, 0, sizeof(service->display_buffer));
    static const uint8_t pages[DISPLAY_COMMAND_LINES] = {0U, 2U, 4U, 6U};
    for (size_t index = 0U; index < DISPLAY_COMMAND_LINES; ++index) {
        draw_text(service->display_buffer, pages[index], command->lines[index]);
    }
    return send_buffer(service);
}

static uint32_t face_period_us(const ainekio_face_index_entry_t *face)
{
    return face == NULL || face->fps == 0U ? UINT32_C(1000000)
                                           : UINT32_C(1000000) / face->fps;
}

static uint8_t frame_index(
    ainekio_face_mode_t mode,
    uint8_t count,
    uint32_t tick
)
{
    if (count <= 1U) {
        return 0U;
    }
    if (mode == AINEKIO_FACE_MODE_ONCE) {
        return tick >= count ? (uint8_t)(count - 1U) : (uint8_t)tick;
    }
    if (mode == AINEKIO_FACE_MODE_LOOP) {
        return (uint8_t)(tick % count);
    }
    const uint32_t period = (uint32_t)count * 2U - 2U;
    const uint32_t position = tick % period;
    return position < count ? (uint8_t)position
                            : (uint8_t)(period - position);
}

static esp_err_t render_face(
    ainekio_display_service_t *service,
    const ainekio_face_index_entry_t *face,
    uint8_t index
)
{
    esp_err_t result = face == NULL
                           ? ESP_ERR_NOT_FOUND
                           : ainekio_asset_store_read_face_frame(
                                 service->assets,
                                 face,
                                 index,
                                 service->source_frame
                             );
    if (result == ESP_OK) {
        convert_bitmap(service->source_frame, service->display_buffer);
    } else {
        compiled_default_face(service->display_buffer);
    }
    const esp_err_t display_result = send_buffer(service);
    return display_result == ESP_OK ? result : display_result;
}

static void select_face(
    ainekio_display_service_t *service,
    const char *name,
    ainekio_face_mode_t mode,
    bool override_mode
)
{
    service->current_face = ainekio_asset_store_face(service->assets, name);
    service->current_mode = override_mode || service->current_face == NULL
                                ? mode
                                : service->current_face->mode;
    service->animation_tick = 0U;
    service->next_frame_us = now_us() + face_period_us(service->current_face);
    const esp_err_t result = render_face(service, service->current_face, 0U);
    if (result != ESP_OK && result != ESP_ERR_NOT_FOUND) {
        ESP_LOGW(TAG, "display frame failed: %s", esp_err_to_name(result));
    }
}

static uint32_t random_between(uint32_t minimum, uint32_t maximum)
{
    return minimum + esp_random() % (maximum - minimum + 1U);
}

static int64_t face_duration_us(
    const ainekio_display_service_t *service,
    const char *name
)
{
    const ainekio_face_index_entry_t *face =
        ainekio_asset_store_face(service->assets, name);
    return face == NULL ? INT64_C(200000)
                        : (int64_t)face->frame_count * face_period_us(face);
}

static void select_idle_face(ainekio_display_service_t *service, const char *name)
{
    const ainekio_face_index_entry_t *face =
        ainekio_asset_store_face(service->assets, name);
    select_face(
        service,
        face == NULL ? "default" : name,
        face == NULL ? AINEKIO_FACE_MODE_ONCE : face->mode,
        false
    );
}

static void service_idle(ainekio_display_service_t *service, int64_t now)
{
    if (!service->idle || now < service->idle_due_us) {
        return;
    }
    if (service->idle_phase == IDLE_WAIT) {
        select_idle_face(service, "idle_blink");
        service->idle_phase = IDLE_BLINK_ONE;
        service->idle_due_us = now + face_duration_us(service, "idle_blink");
    } else if (service->idle_phase == IDLE_BLINK_ONE) {
        select_idle_face(service, "idle");
        if (esp_random() % 100U < 30U) {
            service->idle_phase = IDLE_DOUBLE_GAP;
            service->idle_due_us =
                now + (int64_t)random_between(120U, 220U) * 1000;
        } else {
            service->idle_phase = IDLE_WAIT;
            service->idle_due_us =
                now + (int64_t)random_between(3000U, 7000U) * 1000;
        }
    } else if (service->idle_phase == IDLE_DOUBLE_GAP) {
        select_idle_face(service, "idle_blink");
        service->idle_phase = IDLE_BLINK_TWO;
        service->idle_due_us = now + face_duration_us(service, "idle_blink");
    } else {
        select_idle_face(service, "idle");
        service->idle_phase = IDLE_WAIT;
        service->idle_due_us =
            now + (int64_t)random_between(3000U, 7000U) * 1000;
    }
}

static void service_animation(ainekio_display_service_t *service, int64_t now)
{
    if (service->current_face == NULL || now < service->next_frame_us) {
        return;
    }
    const uint32_t period = face_period_us(service->current_face);
    const uint32_t elapsed = (uint32_t)((now - service->next_frame_us) / period) + 1U;
    service->animation_tick += elapsed;
    service->next_frame_us += (int64_t)elapsed * period;
    const uint8_t index = frame_index(
        service->current_mode,
        service->current_face->frame_count,
        service->animation_tick
    );
    const esp_err_t result = render_face(service, service->current_face, index);
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "display animation failed: %s", esp_err_to_name(result));
    }
    if (service->current_mode == AINEKIO_FACE_MODE_ONCE &&
        service->animation_tick >= service->current_face->frame_count - 1U) {
        service->next_frame_us = INT64_MAX;
    }
}

static void apply_command(
    ainekio_display_service_t *service,
    const display_command_t *command
)
{
    if (command->kind == DISPLAY_COMMAND_STATUS) {
        service->idle = false;
        service->current_face = NULL;
        const esp_err_t result = render_status(service, command);
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "display status failed: %s", esp_err_to_name(result));
        }
        return;
    }
    if (command->kind == DISPLAY_COMMAND_IDLE) {
        service->idle = true;
        service->idle_phase = IDLE_WAIT;
        service->idle_due_us =
            now_us() + (int64_t)random_between(3000U, 7000U) * 1000;
        select_idle_face(service, "idle");
        return;
    }
    service->idle = false;
    select_face(
        service,
        command->name,
        command->mode,
        command->override_mode
    );
}

static void display_task(void *argument)
{
    ainekio_display_service_t *service = argument;
    while (true) {
        display_command_t command;
        if (xQueueReceive(
                service->queue,
                &command,
                pdMS_TO_TICKS(DISPLAY_TASK_PERIOD_MS)
            ) == pdTRUE) {
            apply_command(service, &command);
        }
        const int64_t now = now_us();
        service_idle(service, now);
        service_animation(service, now);
    }
}

static esp_err_t initialize_display(ainekio_display_service_t *service)
{
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = AINEKIO_PIN_I2C_SDA,
        .scl_io_num = AINEKIO_PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7U,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t result = i2c_new_master_bus(&bus_config, &service->bus);
    const i2c_device_config_t device_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = CONFIG_AINEKIO_SSD1306_ADDRESS,
        .scl_speed_hz = DISPLAY_I2C_HZ,
    };
    if (result == ESP_OK) {
        result = i2c_master_bus_add_device(
            service->bus,
            &device_config,
            &service->device
        );
    }
    static const uint8_t init[] = {
        0xaeU,0xd5U,0x80U,0xa8U,0x3fU,0xd3U,0x00U,0x40U,
        0x8dU,0x14U,0x20U,0x00U,0xa1U,0xc8U,0xdaU,0x12U,
        0x81U,0xcfU,0xd9U,0xf1U,0xdbU,0x40U,0xa4U,0xa6U,0xafU,
    };
    if (result == ESP_OK) {
        result = send_commands(service, init, sizeof(init));
    }
    return result;
}

esp_err_t ainekio_display_service_start(
    ainekio_asset_store_t *assets,
    ainekio_display_service_t **service_output
)
{
    if (assets == NULL || service_output == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ainekio_display_service_t *service = &singleton;
    memset(service, 0, sizeof(*service));
    service->assets = assets;
    service->state_lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    (void)strcpy(service->desired_non_talk, "default");
    service->queue = xQueueCreateStatic(
        1U,
        sizeof(display_command_t),
        service->queue_storage,
        &service->queue_control
    );
    if (service->queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t result = initialize_display(service);
    if (result != ESP_OK) {
        return result;
    }
    compiled_default_face(service->display_buffer);
    result = send_buffer(service);
    if (result != ESP_OK) {
        return result;
    }
    if (xTaskCreate(
            display_task,
            "oled",
            4096U,
            service,
            DISPLAY_TASK_PRIORITY,
            &service->task
        ) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    *service_output = service;
    return ESP_OK;
}

esp_err_t ainekio_display_show_face(
    ainekio_display_service_t *service,
    const char *name,
    ainekio_face_mode_t mode,
    bool override_mode,
    bool remember
)
{
    if (service == NULL || name == NULL ||
        ainekio_asset_store_face(service->assets, name) == NULL) {
        return ESP_ERR_NOT_FOUND;
    }
    display_command_t command = {
        .kind = DISPLAY_COMMAND_FACE,
        .mode = mode,
        .override_mode = override_mode,
    };
    (void)strcpy(command.name, name);
    if (remember && strncmp(name, "talk_", 5U) != 0) {
        taskENTER_CRITICAL(&service->state_lock);
        (void)strcpy(service->desired_non_talk, name);
        taskEXIT_CRITICAL(&service->state_lock);
    }
    queue_command(service, &command);
    return ESP_OK;
}

esp_err_t ainekio_display_show_status(
    ainekio_display_service_t *service,
    const char *line_1,
    const char *line_2,
    const char *line_3,
    const char *line_4
)
{
    if (service == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    display_command_t command = {.kind = DISPLAY_COMMAND_STATUS};
    copy_line(command.lines[0], line_1);
    copy_line(command.lines[1], line_2);
    copy_line(command.lines[2], line_3);
    copy_line(command.lines[3], line_4);
    queue_command(service, &command);
    return ESP_OK;
}

void ainekio_display_begin_talk(ainekio_display_service_t *service)
{
    if (service == NULL) {
        return;
    }
    char prior[AINEKIO_ASSET_NAME_MAX + 1U];
    taskENTER_CRITICAL(&service->state_lock);
    (void)strcpy(prior, service->desired_non_talk);
    taskEXIT_CRITICAL(&service->state_lock);
    char candidate[AINEKIO_ASSET_NAME_MAX + 1U];
    const int written = snprintf(candidate, sizeof(candidate), "talk_%s", prior);
    if (written > 0 && (size_t)written < sizeof(candidate) &&
        ainekio_asset_store_face(service->assets, candidate) != NULL) {
        (void)ainekio_display_show_face(
            service,
            candidate,
            AINEKIO_FACE_MODE_LOOP,
            false,
            false
        );
    }
}

void ainekio_display_end_talk(ainekio_display_service_t *service)
{
    if (service == NULL) {
        return;
    }
    display_command_t command = {
        .kind = DISPLAY_COMMAND_RESTORE,
        .mode = AINEKIO_FACE_MODE_ONCE,
        .override_mode = false,
    };
    taskENTER_CRITICAL(&service->state_lock);
    (void)strcpy(command.name, service->desired_non_talk);
    taskEXIT_CRITICAL(&service->state_lock);
    queue_command(service, &command);
}

void ainekio_display_set_idle(ainekio_display_service_t *service, bool idle)
{
    if (service == NULL) {
        return;
    }
    if (idle) {
        const display_command_t command = {.kind = DISPLAY_COMMAND_IDLE};
        queue_command(service, &command);
    } else {
        ainekio_display_end_talk(service);
    }
}
