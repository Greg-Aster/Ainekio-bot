#pragma once
#include "freertos/FreeRTOS.h"
typedef void *TaskHandle_t;
TickType_t xTaskGetTickCount(void);
void vTaskDelay(TickType_t);
void vTaskDelayUntil(TickType_t *,TickType_t);
BaseType_t xTaskCreate(void (*)(void *),const char *,unsigned,void *,unsigned,void *);
