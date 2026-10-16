#include "logs.h"
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "esp_app_desc.h"
#include "esp_attr.h"
#include "esp_log.h"
#include "esp_system.h"

#define LOG_MAGIC UINT32_C(0x414c4732)
typedef struct {
    uint32_t magic, inverse, current_used, previous_used;
    char current[AINEKIO_P4_LOG_BYTES], previous[AINEKIO_P4_LOG_BYTES];
} retained_log_t;
/* Keep layout/address stable across OTA successors for warm-reset retention.
 * An 8 KiB total payload leaves room for the early SDK task allocations. */
static RTC_NOINIT_ATTR retained_log_t retained;
static atomic_flag writing = ATOMIC_FLAG_INIT;
static vprintf_like_t console_log;
static char message[384];
static bool runtime_capture;

/* Panic output may run with flash cache off or another core halted. Never
 * wait for a lock here. Overlapping output can be dropped, never stall control. */
void IRAM_ATTR ainekio_p4_log_panic_character(char c)
{
    if (atomic_flag_test_and_set_explicit(&writing, memory_order_acquire)) return;
    retained.current[retained.current_used % AINEKIO_P4_LOG_BYTES] = c;
    ++retained.current_used;
    atomic_flag_clear_explicit(&writing, memory_order_release);
}

static int capture(const char *format, va_list arguments)
{
    if (!atomic_flag_test_and_set_explicit(&writing, memory_order_acquire)) {
        va_list copy;
        va_copy(copy, arguments);
        int length = vsnprintf(message, sizeof(message), format, copy);
        va_end(copy);
        if (length > 0) {
            size_t count = (size_t)length < sizeof(message) ? (size_t)length : sizeof(message)-1;
            if ((size_t)length >= sizeof(message)) memcpy(message + count - 4, "...\n", 4);
            for (size_t i=0; i<count; ++i) retained.current[retained.current_used++ % AINEKIO_P4_LOG_BYTES] = message[i];
        }
        atomic_flag_clear_explicit(&writing, memory_order_release);
    }
    return console_log ? console_log(format, arguments) : 0;
}

void ainekio_p4_logs_runtime(void)
{
    if (!runtime_capture) { console_log = esp_log_set_vprintf(capture); runtime_capture = true; }
}

void ainekio_p4_logs_init(void)
{
    const esp_reset_reason_t reason = esp_reset_reason();
    if (retained.magic != LOG_MAGIC || retained.inverse != ~LOG_MAGIC || reason == ESP_RST_POWERON) {
        /* Empty rings need only their lengths reset. Do not pass RTC RAM to
         * an optimized libc bulk fill: this P4 memory cannot use 128-bit SIMD
         * accesses. No unread bytes are exposed by snapshot(). */
        retained.current_used = retained.previous_used = 0;
        retained.magic = LOG_MAGIC;
        retained.inverse = ~LOG_MAGIC;
    } else {
        volatile char *previous = retained.previous;
        const volatile char *current = retained.current;
        for (size_t i=0; i<sizeof(retained.previous); ++i) previous[i] = current[i];
        retained.previous_used = retained.current_used;
        retained.current_used = 0;
    }
    console_log = vprintf;
    runtime_capture = false;
    ainekio_p4_log_stage(esp_app_get_description()->version);
}

void ainekio_p4_log_stage(const char *stage)
{
    /* Startup breadcrumbs must not add formatted console I/O or take libc
     * locks in the boot path. Normal SDK output keeps its existing owner. */
    while (*stage) ainekio_p4_log_panic_character(*stage++);
    ainekio_p4_log_panic_character('\n');
}

static size_t copy_ring(char *to, const char *ring, uint32_t used)
{
    const size_t length = used < AINEKIO_P4_LOG_BYTES ? used : AINEKIO_P4_LOG_BYTES;
    const size_t start = used < AINEKIO_P4_LOG_BYTES ? 0 : used % AINEKIO_P4_LOG_BYTES;
    for (size_t i=0; i<length; ++i) to[i] = ring[(start+i) % AINEKIO_P4_LOG_BYTES];
    return length;
}

size_t ainekio_p4_logs_snapshot(char *buffer, size_t capacity)
{
    if (capacity < AINEKIO_P4_LOG_SNAPSHOT_BYTES ||
        atomic_flag_test_and_set_explicit(&writing, memory_order_acquire)) return 0;
    size_t size = snprintf(buffer, capacity,
        "Bounded controller logs. Previous boot survives warm reset; power loss clears it.\n"
        "Last %u bytes per boot; long/overlapping messages may be truncated.\n\n--- Previous boot ---\n",
        (unsigned)AINEKIO_P4_LOG_BYTES);
    size += copy_ring(buffer + size, retained.previous, retained.previous_used);
    size += snprintf(buffer + size, capacity - size, "\n--- Current boot: %s; reset reason %d ---\n",
                     esp_app_get_description()->version, (int)esp_reset_reason());
    size += copy_ring(buffer + size, retained.current, retained.current_used);
    atomic_flag_clear_explicit(&writing, memory_order_release);
    return size;
}
