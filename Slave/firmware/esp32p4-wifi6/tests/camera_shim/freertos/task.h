#pragma once
#include "../../body_shim/freertos/task.h"
BaseType_t xTaskCreate(void (*function)(void *), const char *name, unsigned stack,
                      void *argument, unsigned priority, void *handle);
void vTaskDelete(void *task);
