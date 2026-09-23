#pragma once
#include "FreeRTOS.h"
BaseType_t xTaskCreatePinnedToCore(void (*)(void *), const char *, unsigned, void *, unsigned, void *, unsigned);
void vTaskDelay(TickType_t);

typedef void *TaskHandle_t;
static inline unsigned uxTaskGetStackHighWaterMark(TaskHandle_t task) { (void)task; return 0; }
