#pragma once
#include "FreeRTOS.h"
typedef struct test_queue *QueueHandle_t;
QueueHandle_t xQueueCreate(UBaseType_t, UBaseType_t);
BaseType_t xQueueSend(QueueHandle_t, const void *, TickType_t);
BaseType_t xQueueReceive(QueueHandle_t, void *, TickType_t);
BaseType_t xQueueOverwrite(QueueHandle_t, const void *);
UBaseType_t uxQueueSpacesAvailable(QueueHandle_t);
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t);
