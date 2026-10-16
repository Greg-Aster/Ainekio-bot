#pragma once
#include <stddef.h>
/* Bounded RAM logs, including the previous warm-reset boot. No SD/flash writes. */
#define AINEKIO_P4_LOG_BYTES 4096U
#define AINEKIO_P4_LOG_SNAPSHOT_BYTES (2U * AINEKIO_P4_LOG_BYTES + 512U)
void ainekio_p4_logs_init(void);
void ainekio_p4_logs_runtime(void);
void ainekio_p4_log_stage(const char *stage);
size_t ainekio_p4_logs_snapshot(char *buffer, size_t capacity);
