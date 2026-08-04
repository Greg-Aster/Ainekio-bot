#include "ainekio/platform/sleep_service.h"

#include "esp_sleep.h"
#include "esp_wifi.h"

void ainekio_sleep_enter(uint32_t seconds)
{
    (void)esp_wifi_stop();
    (void)esp_sleep_enable_timer_wakeup((uint64_t)seconds * UINT64_C(1000000));
    esp_deep_sleep_start();
    __builtin_unreachable();
}
