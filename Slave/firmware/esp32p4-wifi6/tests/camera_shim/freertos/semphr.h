#pragma once
#include "../../body_shim/freertos/semphr.h"
SemaphoreHandle_t xSemaphoreCreateBinary(void);
void vSemaphoreDelete(SemaphoreHandle_t semaphore);
