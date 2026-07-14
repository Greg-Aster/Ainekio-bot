#include "ainekio/core.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_system.h"

static const char *TAG = "ainekio_boot";
static ainekio_core_t slave_brain;

void app_main(void)
{
    const esp_app_desc_t *app = esp_app_get_description();

    ainekio_core_init(&slave_brain);

    ESP_LOGI(TAG,
             "{\"event\":\"boot\",\"firmware\":\"%s\",\"protocol\":%u,"
             "\"idf\":\"%s\",\"state\":%u,\"servos_attached\":false}",
             app->version,
             AINEKIO_PROTOCOL_VERSION,
             esp_get_idf_version(),
             (unsigned int)slave_brain.state);
}
