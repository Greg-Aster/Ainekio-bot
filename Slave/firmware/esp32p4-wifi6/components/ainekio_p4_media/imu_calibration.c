#include "ainekio/p4_imu.h"
#include "nvs.h"
#include <string.h>

/* NVS supplies blob storage and integrity checking. The key
 * versions the layout: 9 rotation floats followed by 3 sensor-bias floats.
 * No robot joint, home, network or other media settings are touched. */
static bool calibration_valid(const ainekio_p4_imu_calibration_t *calibration)
{
    if (!calibration) return false;
    ainekio_imu_config_t config=ainekio_imu_default_config();
    memcpy(config.sensor_to_body,calibration->sensor_to_body,sizeof(config.sensor_to_body));
    memcpy(config.gyro_bias_rad_s,calibration->gyro_bias_rad_s,sizeof(config.gyro_bias_rad_s));
    ainekio_imu_t temporary;
    return ainekio_imu_init(&temporary,&config);
}

esp_err_t ainekio_p4_imu_calibration_load(ainekio_p4_imu_calibration_t *calibration,bool *found)
{
    if (!calibration || !found) return ESP_ERR_INVALID_ARG;
    *found=false;
    *calibration=(ainekio_p4_imu_calibration_t){.sensor_to_body={1,0,0,0,1,0,0,0,1}};
    nvs_handle_t handle;
    esp_err_t result=nvs_open("p4_imu",NVS_READONLY,&handle);
    if (result==ESP_ERR_NVS_NOT_FOUND) return ESP_OK;
    if (result!=ESP_OK) return result;
    ainekio_p4_imu_calibration_t saved;
    size_t size=sizeof(saved);
    result=nvs_get_blob(handle,"cal_v1",&saved,&size);
    nvs_close(handle);
    if (result==ESP_ERR_NVS_NOT_FOUND) return ESP_OK;
    if (result!=ESP_OK) return result;
    if (size!=sizeof(saved)) return ESP_ERR_NVS_INVALID_LENGTH;
    if (!calibration_valid(&saved)) return ESP_ERR_INVALID_ARG;
    *calibration=saved;
    *found=true;
    return ESP_OK;
}

esp_err_t ainekio_p4_imu_calibration_save(const ainekio_p4_imu_calibration_t *calibration)
{
    if (!calibration_valid(calibration)) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t result=nvs_open("p4_imu",NVS_READWRITE,&handle);
    if (result!=ESP_OK) return result;
    result=nvs_set_blob(handle,"cal_v1",calibration,sizeof(*calibration));
    if (result==ESP_OK) result=nvs_commit(handle);
    nvs_close(handle);
    return result;
}
