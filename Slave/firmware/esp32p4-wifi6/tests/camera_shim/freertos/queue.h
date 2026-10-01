#pragma once
#include "../../body_shim/freertos/queue.h"
BaseType_t xQueueReset(QueueHandle_t queue);
void vQueueDelete(QueueHandle_t queue);
