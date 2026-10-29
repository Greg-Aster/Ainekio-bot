#include "ainekio/p4_imu.h"
#include "media_internal.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <math.h>

/* ST LSM6DS3 DocID026899 Rev 10. Single acquisition owner; ESP-IDF
 * serializes transactions with other devices on the existing media bus. */
enum { WHO_AM_I=0x0f, CTRL1_XL=0x10, CTRL2_G=0x11, CTRL3_C=0x12,
       STATUS_REG=0x1e, OUTX_L_G=0x22, IO_TIMEOUT_MS=20 };
static i2c_master_dev_handle_t device;
static ainekio_imu_t estimator;
static ainekio_p4_imu_status_t state;
static portMUX_TYPE snapshot_lock=portMUX_INITIALIZER_UNLOCKED;
static ainekio_p4_imu_status_t published;
static bool gyro_calibration_requested;
static double gyro_mean[3], gyro_m2[3];

esp_err_t ainekio_p4_imu_calibrate_gyro(void)
{
    portENTER_CRITICAL(&snapshot_lock);
    const bool running=published.running;
    if(running)gyro_calibration_requested=true;
    portEXIT_CRITICAL(&snapshot_lock);
    return running ? ESP_OK : ESP_ERR_INVALID_STATE;
}

static void calibrate_gyro_sample(const ainekio_imu_sample_t *sample)
{
    portENTER_CRITICAL(&snapshot_lock);
    const bool requested=gyro_calibration_requested;
    gyro_calibration_requested=false;
    portEXIT_CRITICAL(&snapshot_lock);
    if(requested) {
        state.gyro_calibration=(ainekio_p4_gyro_calibration_status_t){.phase=AINEKIO_GYRO_COLLECTING};
        memset(gyro_mean,0,sizeof gyro_mean);memset(gyro_m2,0,sizeof gyro_m2);
    }
    ainekio_p4_gyro_calibration_status_t *c=&state.gyro_calibration;
    if(c->phase!=AINEKIO_GYRO_COLLECTING)return;
    ++c->samples;
    for(unsigned i=0;i<3;i++) {
        const double delta=sample->angular_rate_rad_s[i]-gyro_mean[i];
        gyro_mean[i]+=delta/c->samples;
        gyro_m2[i]+=delta*(sample->angular_rate_rad_s[i]-gyro_mean[i]);
    }
    if(c->samples!=AINEKIO_GYRO_CALIBRATION_SAMPLES)return;
    ainekio_p4_imu_calibration_t calibration=state.calibration;
    for(unsigned i=0;i<3;i++) {
        calibration.gyro_bias_rad_s[i]=c->bias_rad_s[i]=(float)gyro_mean[i];
        c->deviation_rad_s[i]=(float)sqrt(gyro_m2[i]/(c->samples-1));
    }
    c->error=ainekio_p4_imu_calibration_save(&calibration);
    c->phase=c->error==ESP_OK ? AINEKIO_GYRO_SAVED : AINEKIO_GYRO_ERROR;
    if(c->error==ESP_OK) {
        state.calibration=calibration;
        memcpy(estimator.config.gyro_bias_rad_s,calibration.gyro_bias_rad_s,sizeof calibration.gyro_bias_rad_s);
        /* Bias measurement does not verify a previously unverified mounting. */
    }
}

static void publish(void)
{
    portENTER_CRITICAL(&snapshot_lock);
    published=state;
    portEXIT_CRITICAL(&snapshot_lock);
}

static esp_err_t read_reg(uint8_t reg,uint8_t *bytes,size_t size)
{ return i2c_master_transmit_receive(device,&reg,1,bytes,size,IO_TIMEOUT_MS); }
static esp_err_t write_reg(uint8_t reg,uint8_t value)
{
    const uint8_t bytes[]={reg,value};
    return i2c_master_transmit(device,bytes,sizeof(bytes),IO_TIMEOUT_MS);
}

esp_err_t p4_imu_prepare(i2c_master_bus_handle_t bus)
{
    if (device) return ESP_ERR_INVALID_STATE;
    state=(ainekio_p4_imu_status_t){0};
    esp_err_t result=i2c_master_probe(bus,0x6a,IO_TIMEOUT_MS);
    if (result!=ESP_OK) goto failed;
    const i2c_device_config_t config={.dev_addr_length=I2C_ADDR_BIT_LEN_7,
        .device_address=0x6a,.scl_speed_hz=400000};
    result=i2c_master_bus_add_device(bus,&config,&device);
    if (result!=ESP_OK) goto failed;
    result=read_reg(WHO_AM_I,&state.identity,1);
    if (result!=ESP_OK) goto failed;
    if (state.identity!=0x69) { result=ESP_ERR_NOT_SUPPORTED; goto failed; }
    result=ainekio_p4_imu_calibration_load(&state.calibration,&state.calibration_applied);
    if (result!=ESP_OK) goto failed;
    uint8_t saved[3];
    for (unsigned i=0;i<3;++i) {
        result=read_reg(CTRL1_XL+i,&saved[i],1);
        if (result!=ESP_OK) goto failed;
    }
    /* BDU, little endian, auto-increment; 208 Hz, +/-16 g, +/-2000 dps.
     * Range and ODR match the portable estimator's default configuration. */
    result=write_reg(CTRL3_C,0x44);
    if (result==ESP_OK) result=write_reg(CTRL1_XL,0x54);
    if (result==ESP_OK) result=write_reg(CTRL2_G,0x5c);
    if (result!=ESP_OK) {
        for (unsigned i=0;i<3;++i) (void)write_reg(CTRL1_XL+i,saved[i]);
        goto failed;
    }
    ainekio_imu_config_t estimation=ainekio_imu_default_config();
    memcpy(estimation.sensor_to_body,state.calibration.sensor_to_body,sizeof(estimation.sensor_to_body));
    memcpy(estimation.gyro_bias_rad_s,state.calibration.gyro_bias_rad_s,sizeof(estimation.gyro_bias_rad_s));
    (void)ainekio_imu_init(&estimator,&estimation);
    state.configured=true;
    publish();
    return ESP_OK;
failed:
    state.last_error=result;
    if (device) { (void)i2c_master_bus_rm_device(device);device=NULL; }
    publish();
    return result;
}

static void poll_sample(void)
{
    uint8_t status=0,bytes[12];
    esp_err_t result=read_reg(STATUS_REG,&status,1);
    if (result!=ESP_OK) goto failed;
    if ((status&3)!=3) { ++state.no_data_polls;state.last_error=ESP_OK;publish();return; }
    const uint64_t before=(uint64_t)esp_timer_get_time();
    result=read_reg(OUTX_L_G,bytes,sizeof(bytes));
    const uint64_t after=(uint64_t)esp_timer_get_time();
    if (result!=ESP_OK) goto failed;
    ainekio_imu_sample_t sample;
    ainekio_imu_lsm6ds3_decode(before+(after-before)/2,bytes,&sample);
    state.read_us=(uint32_t)(after-before);
    if (state.read_us>state.read_max_us) state.read_max_us=state.read_us;
    if (state.samples) {
        const uint64_t interval=sample.timestamp_us-state.raw.timestamp_us;
        if (interval>state.interval_max_us) state.interval_max_us=interval;
    }
    state.raw=sample;
    ++state.samples;
    state.last_error=ESP_OK;
    calibrate_gyro_sample(&sample);
    (void)ainekio_imu_update(&estimator,&sample);
    (void)ainekio_imu_observe(&estimator,after,&state.attitude);
    publish();
    return;
failed:
    ++state.io_errors;
    state.last_error=result;
    /* Preserve acquisition time on errors: readers see increasing age. */
    publish();
}

static void acquisition_task(void *unused)
{
    (void)unused;
    vTaskDelay(pdMS_TO_TICKS(100));
    TickType_t wake=xTaskGetTickCount();
    for (;;) {
        poll_sample();
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(2));
    }
}

esp_err_t ainekio_p4_imu_start(void)
{
    if (!state.configured) return state.last_error ? state.last_error : ESP_ERR_INVALID_STATE;
    if (state.running) return ESP_ERR_INVALID_STATE;
    state.running=true;
    publish();
    /* Acquire the 208 Hz sensor ahead of network serialization (priority 5)
     * and the multiplexed ADC scan (3). The body output owner (10) still
     * preempts acquisition. Polling blocks between reads; no other owner
     * waits for the estimator. */
    if (xTaskCreate(acquisition_task,"p4_imu",4096,NULL,P4_SENSOR_IO_PRIORITY,NULL)!=pdPASS) {
        state.running=false;state.last_error=ESP_ERR_NO_MEM;publish();
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

ainekio_p4_imu_status_t ainekio_p4_imu_status(void)
{
    portENTER_CRITICAL(&snapshot_lock);
    ainekio_p4_imu_status_t result=published;
    portEXIT_CRITICAL(&snapshot_lock);
    const uint64_t now=(uint64_t)esp_timer_get_time();
    result.attitude.age_us=result.attitude.available && now>=result.attitude.timestamp_us ?
        now-result.attitude.timestamp_us : UINT64_MAX;
    result.attitude.fresh=result.attitude.available &&
        result.attitude.age_us<=20000; /* existing estimator freshness contract */
    return result;
}
