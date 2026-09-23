#pragma once
#include "esp_err.h"
#include <stdbool.h>
typedef struct { int timeout_ms, idle_core_mask; bool trigger_panic; } esp_task_wdt_config_t;
typedef void *esp_task_wdt_user_handle_t;
int esp_task_wdt_reconfigure(const esp_task_wdt_config_t *);
int esp_task_wdt_init(const esp_task_wdt_config_t *);
int esp_task_wdt_add_user(const char *, esp_task_wdt_user_handle_t *);
int esp_task_wdt_reset_user(esp_task_wdt_user_handle_t);
