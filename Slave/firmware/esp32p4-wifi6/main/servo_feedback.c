#include "servo_feedback.h"
#include "body_readings.h"
#include "board.h"
#include "body.h"
#include "config.h"
#include "esp_http_server.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "cJSON.h"
#include "sdkconfig.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Allocate after scheduler startup: this board's pre-v3 early internal RAM is
 * scarce. Acquisition never runs inside the motion/output task. */
static ainekio_p4_feedback_snapshot_t *state;
static ainekio_feedback_filter_t *filters;
static SemaphoreHandle_t config_mutex;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
#ifdef CONFIG_AINEKIO_FEEDBACK_DIRECT_ADC
/* V1 direct 8-channel 4th-wire feedback (no analog multiplexer):
 *   ch 0..3 -> ADC1 CH4..CH7 (GPIO20, 21, 22, 23) = R1, R2, L1, L2 hips
 *   ch 4..7 -> ADC2 CH0..CH3 (GPIO49, 50, 51, 52) = R4, R3, L3, L4 knees */
static adc_oneshot_unit_handle_t adc1_handle, adc2_handle;
static adc_cali_handle_t cali1_handle, cali2_handle;
typedef struct {
    adc_unit_t unit;
    adc_channel_t chan;
} direct_adc_map_t;
static const direct_adc_map_t direct_map[8] = {
    {ADC_UNIT_1, ADC_CHANNEL_4}, /* ch 0: GPIO20 */
    {ADC_UNIT_1, ADC_CHANNEL_5}, /* ch 1: GPIO21 */
    {ADC_UNIT_1, ADC_CHANNEL_6}, /* ch 2: GPIO22 */
    {ADC_UNIT_1, ADC_CHANNEL_7}, /* ch 3: GPIO23 */
    {ADC_UNIT_2, ADC_CHANNEL_0}, /* ch 4: GPIO49 */
    {ADC_UNIT_2, ADC_CHANNEL_1}, /* ch 5: GPIO50 */
    {ADC_UNIT_2, ADC_CHANNEL_2}, /* ch 6: GPIO51 */
    {ADC_UNIT_2, ADC_CHANNEL_3}, /* ch 7: GPIO52 */
};
#else
static adc_oneshot_unit_handle_t adc;
static adc_cali_handle_t cali;
static const int select_gpio[4]={27,28,29,30};
#endif

void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out)
{
    portENTER_CRITICAL(&lock);
    if(state)*out=*state;else memset(out,0,sizeof(*out));
    portEXIT_CRITICAL(&lock);
}
bool ainekio_p4_feedback_stand_enabled(void)
{
    portENTER_CRITICAL(&lock);
    bool enabled=state&&state->config.stand_enabled;
    portEXIT_CRITICAL(&lock);return enabled;
}
bool ainekio_p4_feedback_jam_enabled(void)
{
    portENTER_CRITICAL(&lock);
    bool enabled=state&&state->config.enabled&&state->config.jam_enabled&&state->config.no_progress_ms;
    portEXIT_CRITICAL(&lock);return enabled;
}
#ifdef CONFIG_AINEKIO_FEEDBACK_DIRECT_ADC
static esp_err_t initialize_adc(void)
{
    const adc_oneshot_unit_init_cfg_t u1={.unit_id=ADC_UNIT_1};
    const adc_oneshot_unit_init_cfg_t u2={.unit_id=ADC_UNIT_2};
    esp_err_t result=adc_oneshot_new_unit(&u1,&adc1_handle);
    if(result!=ESP_OK)return result;
    result=adc_oneshot_new_unit(&u2,&adc2_handle);
    if(result!=ESP_OK){adc_oneshot_del_unit(adc1_handle);adc1_handle=NULL;return result;}
    const adc_oneshot_chan_cfg_t channel={.atten=ADC_ATTEN_DB_12,.bitwidth=ADC_BITWIDTH_12};
    for(unsigned i=0;i<8;i++) {
        adc_oneshot_unit_handle_t h=direct_map[i].unit==ADC_UNIT_1?adc1_handle:adc2_handle;
        result=adc_oneshot_config_channel(h,direct_map[i].chan,&channel);
        if(result!=ESP_OK) {
            adc_oneshot_del_unit(adc1_handle);adc1_handle=NULL;
            adc_oneshot_del_unit(adc2_handle);adc2_handle=NULL;
            return result;
        }
    }
    const adc_cali_curve_fitting_config_t cfg1={.unit_id=ADC_UNIT_1,.chan=ADC_CHANNEL_4,
        .atten=ADC_ATTEN_DB_12,.bitwidth=ADC_BITWIDTH_12};
    const adc_cali_curve_fitting_config_t cfg2={.unit_id=ADC_UNIT_2,.chan=ADC_CHANNEL_0,
        .atten=ADC_ATTEN_DB_12,.bitwidth=ADC_BITWIDTH_12};
    esp_err_t v1=adc_cali_create_scheme_curve_fitting(&cfg1,&cali1_handle);
    esp_err_t v2=adc_cali_create_scheme_curve_fitting(&cfg2,&cali2_handle);
    portENTER_CRITICAL(&lock);state->voltage_error=v1!=ESP_OK?v1:v2;portEXIT_CRITICAL(&lock);
    return ESP_OK;
}
#else
static esp_err_t initialize_adc(void)
{
    const adc_oneshot_unit_init_cfg_t unit={.unit_id=ADC_UNIT_2};
    esp_err_t result=adc_oneshot_new_unit(&unit,&adc);
    if(result!=ESP_OK)return result;
    const adc_oneshot_chan_cfg_t channel={.atten=ADC_ATTEN_DB_12,.bitwidth=ADC_BITWIDTH_12};
    result=adc_oneshot_config_channel(adc,ADC_CHANNEL_0,&channel);
    if(result!=ESP_OK){adc_oneshot_del_unit(adc);adc=NULL;return result;}
    gpio_config_t pins={.mode=GPIO_MODE_OUTPUT};
    for(unsigned b=0;b<4;b++)pins.pin_bit_mask|=1ULL<<select_gpio[b];
    result=gpio_config(&pins);
    if(result!=ESP_OK){adc_oneshot_del_unit(adc);adc=NULL;return result;}
    const adc_cali_curve_fitting_config_t cfg={.unit_id=ADC_UNIT_2,.chan=ADC_CHANNEL_0,
        .atten=ADC_ATTEN_DB_12,.bitwidth=ADC_BITWIDTH_12};
    esp_err_t voltage=adc_cali_create_scheme_curve_fitting(&cfg,&cali);
    portENTER_CRITICAL(&lock);state->voltage_error=voltage;portEXIT_CRITICAL(&lock);
    return ESP_OK;
}
#endif
static void wait_for_next_scan(TickType_t *next)
{
    const TickType_t period = pdMS_TO_TICKS(20);
    /* ADC scans measure the present; missed samples cannot be replayed. Flash
     * writes can put this task many periods behind. Advance to the current
     * period before waiting, so catch-up scans cannot starve storage/OTA. Keep
     * the normal 50 Hz phase and use unsigned subtraction across tick wrap. */
    const TickType_t elapsed = xTaskGetTickCount() - *next;
    *next += (elapsed / period) * period;
    vTaskDelayUntil(next, period);
}

static void acquire(void *unused)
{
    (void)unused;bool attempted=false;
    TickType_t next=xTaskGetTickCount();
    for(;;) {
        ainekio_p4_feedback_snapshot_t sample;ainekio_p4_feedback_snapshot(&sample);
        if(!sample.config.enabled) {
            attempted=false;
            memset(filters,0,16*sizeof(*filters));
            portENTER_CRITICAL(&lock);state->valid_mask=0;portEXIT_CRITICAL(&lock);
        } else {
#ifdef CONFIG_AINEKIO_FEEDBACK_DIRECT_ADC
            const bool adc_ready = adc1_handle != NULL && adc2_handle != NULL;
#else
            const bool adc_ready = adc != NULL;
#endif
            if(!adc_ready&&!attempted) {
                attempted=true;esp_err_t e=initialize_adc();
                portENTER_CRITICAL(&lock);state->error=e;state->initialized=e==ESP_OK;portEXIT_CRITICAL(&lock);
            }
#ifdef CONFIG_AINEKIO_FEEDBACK_DIRECT_ADC
            if(adc1_handle && adc2_handle) {
                int64_t start=esp_timer_get_time();
                sample.valid_mask=0;sample.error=ESP_OK;
                for(unsigned channel=0;channel<8;channel++) {
                    esp_err_t e=ESP_OK;int raw=0,total=0,lo=4095,hi=0;
                    adc_oneshot_unit_handle_t h=direct_map[channel].unit==ADC_UNIT_1?adc1_handle:adc2_handle;
                    adc_cali_handle_t c=direct_map[channel].unit==ADC_UNIT_1?cali1_handle:cali2_handle;
                    const adc_channel_t ch=direct_map[channel].chan;
                    /* Discard the first sample after switching ADC channel; average 4 reads. */
                    e=adc_oneshot_read(h,ch,&raw);
                    for(unsigned n=0;n<4&&e==ESP_OK;n++) {
                        e=adc_oneshot_read(h,ch,&raw);
                        if(e==ESP_OK){total+=raw;if(raw<lo)lo=raw;if(raw>hi)hi=raw;}
                    }
                    sample.sampled_us[channel]=esp_timer_get_time();
                    sample.millivolts[channel]=-1;
                    if(e==ESP_OK) {
                        sample.raw[channel]=(total+2)/4;sample.spread[channel]=hi-lo;
                        ainekio_feedback_filter_update(&filters[channel],sample.raw[channel],sample.sampled_us[channel]);
                        sample.filtered_raw[channel]=(float)filters[channel].position;
                        sample.velocity_raw_s[channel]=(float)filters[channel].velocity;
                        sample.valid_mask|=1U<<channel;
                        if(c) {
                            int mv;
                            esp_err_t v=adc_cali_raw_to_voltage(c,sample.raw[channel],&mv);
                            if(v==ESP_OK)sample.millivolts[channel]=mv;
                        }
                    } else {sample.error=e;filters[channel].initialized=false;}
                }
                sample.scan_us=esp_timer_get_time()-start;
                portENTER_CRITICAL(&lock);
                if(state->revision==sample.revision&&state->config.enabled) {
                    memcpy(state->raw,sample.raw,sizeof(sample.raw));
                    memcpy(state->spread,sample.spread,sizeof(sample.spread));
                    memcpy(state->filtered_raw,sample.filtered_raw,sizeof(sample.filtered_raw));
                    memcpy(state->velocity_raw_s,sample.velocity_raw_s,sizeof(sample.velocity_raw_s));
                    memcpy(state->millivolts,sample.millivolts,sizeof(sample.millivolts));
                    memcpy(state->sampled_us,sample.sampled_us,sizeof(sample.sampled_us));
                    state->valid_mask=sample.valid_mask;state->error=sample.error;
                    state->scan_us=sample.scan_us;state->scan++;
                    sample.scan=state->scan;
                }
                portEXIT_CRITICAL(&lock);
            }
#else
            if(adc) {
                int64_t start=esp_timer_get_time();
                sample.valid_mask=0;sample.error=ESP_OK;
                for(unsigned channel=0;channel<16;channel++) {
                    esp_err_t e=ESP_OK;int raw=0,total=0,lo=4095,hi=0;
                    for(unsigned b=0;b<4;b++) {
                        esp_err_t pin=gpio_set_level(select_gpio[b],(channel>>b)&1U);
                        if(pin!=ESP_OK)e=pin;
                    }
                    /* Discard the first conversion after switching; retain the
                     * spread of four samples so settling/noise is observable.
                     * Bench qualification must check inter-channel settling. */
                    if(e==ESP_OK)e=adc_oneshot_read(adc,ADC_CHANNEL_0,&raw);
                    for(unsigned n=0;n<4&&e==ESP_OK;n++) {
                        e=adc_oneshot_read(adc,ADC_CHANNEL_0,&raw);
                        if(e==ESP_OK){total+=raw;if(raw<lo)lo=raw;if(raw>hi)hi=raw;}
                    }
                    sample.sampled_us[channel]=esp_timer_get_time();
                    sample.millivolts[channel]=-1;
                    if(e==ESP_OK) {
                        sample.raw[channel]=(total+2)/4;sample.spread[channel]=hi-lo;
                        ainekio_feedback_filter_update(&filters[channel],sample.raw[channel],sample.sampled_us[channel]);
                        sample.filtered_raw[channel]=(float)filters[channel].position;
                        sample.velocity_raw_s[channel]=(float)filters[channel].velocity;
                        sample.valid_mask|=1U<<channel;
                        if(cali) {
                            int mv;
                            esp_err_t v=adc_cali_raw_to_voltage(cali,sample.raw[channel],&mv);
                            if(v==ESP_OK)sample.millivolts[channel]=mv;
                        }
                    } else {sample.error=e;filters[channel].initialized=false;}
                }
                sample.scan_us=esp_timer_get_time()-start;
                portENTER_CRITICAL(&lock);
                /* A configuration write invalidates an in-progress old scan. */
                if(state->revision==sample.revision&&state->config.enabled) {
                    memcpy(state->raw,sample.raw,sizeof(sample.raw));
                    memcpy(state->spread,sample.spread,sizeof(sample.spread));
                    memcpy(state->filtered_raw,sample.filtered_raw,sizeof(sample.filtered_raw));
                    memcpy(state->velocity_raw_s,sample.velocity_raw_s,sizeof(sample.velocity_raw_s));
                    memcpy(state->millivolts,sample.millivolts,sizeof(sample.millivolts));
                    memcpy(state->sampled_us,sample.sampled_us,sizeof(sample.sampled_us));
                    state->valid_mask=sample.valid_mask;state->error=sample.error;
                    state->scan_us=sample.scan_us;state->scan++;
                    sample.scan=state->scan;
                }
                portEXIT_CRITICAL(&lock);
            }
#endif
        }
        /* Sensor scan cadence; never delays the independent body task. */
        wait_for_next_scan(&next);
    }
}
esp_err_t ainekio_p4_feedback_start(void)
{
    if(state)return ESP_ERR_INVALID_STATE;
    state=calloc(1,sizeof(*state));config_mutex=xSemaphoreCreateMutex();
    filters=calloc(16,sizeof(*filters));
    if(!state||!config_mutex||!filters) {
        free(state);state=NULL;free(filters);filters=NULL;
        if(config_mutex)vSemaphoreDelete(config_mutex);
        config_mutex=NULL;return ESP_ERR_NO_MEM;
    }
    ainekio_feedback_defaults(&state->config);
    for(unsigned c=0;c<16;c++)state->millivolts[c]=-1;
    nvs_handle_t handle;esp_err_t e=nvs_open("p4_feedback",NVS_READONLY,&handle);
    if(e==ESP_OK) {
        ainekio_feedback_config_t saved;size_t bytes=sizeof(saved);
        e=nvs_get_blob(handle,"config",&saved,&bytes);nvs_close(handle);
        if(e==ESP_OK&&ainekio_feedback_config_decode(&saved,bytes,&state->config)) {
            state->saved=true;
        } else if(e==ESP_OK)e=ESP_ERR_INVALID_ARG;
    }
    state->error=e==ESP_ERR_NVS_NOT_FOUND?ESP_OK:e;
    if(xTaskCreate(acquire,"servo-feedback",4096,NULL,3,NULL)!=pdPASS) {
        free(state);state=NULL;free(filters);filters=NULL;vSemaphoreDelete(config_mutex);config_mutex=NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

static esp_err_t save(const ainekio_feedback_config_t *candidate)
{
    if(!ainekio_feedback_config_valid(candidate))return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;esp_err_t e=nvs_open("p4_feedback",NVS_READWRITE,&handle);
    if(e!=ESP_OK)return e;
    e=nvs_set_blob(handle,"config",candidate,sizeof(*candidate));
    if(e==ESP_OK)e=nvs_commit(handle);
    nvs_close(handle);
    if(e==ESP_OK) {
        portENTER_CRITICAL(&lock);state->config=*candidate;state->saved=true;
        state->revision++;state->valid_mask=0;portEXIT_CRITICAL(&lock);
    }
    return e;
}
static bool integer(cJSON *o,const char *key,int min,int max,int *out)
{
    cJSON *v=cJSON_GetObjectItemCaseSensitive(o,key);
    if(!cJSON_IsNumber(v)||!isfinite(v->valuedouble)||v->valuedouble<min||v->valuedouble>max||
       trunc(v->valuedouble)!=v->valuedouble)return false;
    *out=v->valueint;return true;
}
static esp_err_t change(cJSON *o)
{
    cJSON *op=cJSON_GetObjectItemCaseSensitive(o,"op");
    if(!cJSON_IsString(op))return ESP_ERR_INVALID_ARG;
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    ainekio_feedback_config_t c=s.config;
    if(!strcmp(op->valuestring,"configure")) {
        cJSON *enabled=cJSON_GetObjectItemCaseSensitive(o,"enabled");
        cJSON *stand=cJSON_GetObjectItemCaseSensitive(o,"stand_enabled");int tolerance;
        if(!cJSON_IsBool(enabled)||!cJSON_IsBool(stand)||
           !integer(o,"tolerance_us",1,65535,&tolerance))return ESP_ERR_INVALID_ARG;
        c.enabled=cJSON_IsTrue(enabled);c.stand_enabled=cJSON_IsTrue(stand);c.tolerance_us=tolerance;
        cJSON *jam=cJSON_GetObjectItemCaseSensitive(o,"jam_enabled");
        if(jam) {
            if(!cJSON_IsBool(jam))return ESP_ERR_INVALID_ARG;
            c.jam_enabled=cJSON_IsTrue(jam);
        }
        int value;
        if(cJSON_HasObjectItem(o,"arrival_tolerance_us")) {
            if(!integer(o,"arrival_tolerance_us",1,65535,&value))return ESP_ERR_INVALID_ARG;
            c.arrival_tolerance_us=value;
        }
        if(cJSON_HasObjectItem(o,"no_progress_ms")) {
            if(!integer(o,"no_progress_ms",0,INT32_MAX,&value))return ESP_ERR_INVALID_ARG;
            c.no_progress_ms=value;
        }
        if(cJSON_HasObjectItem(o,"progress_us")) {
            if(!integer(o,"progress_us",1,65535,&value))return ESP_ERR_INVALID_ARG;
            c.progress_us=value;
        }
    } else {
        int id;if(!integer(o,"joint",0,(int)AINEKIO_FEEDBACK_ACTIVE_JOINTS-1,&id))return ESP_ERR_INVALID_ARG;
        if(!strcmp(op->valuestring,"map")) {
#ifdef CONFIG_AINEKIO_FEEDBACK_DIRECT_ADC
            int channel;if(!integer(o,"channel",0,7,&channel))return ESP_ERR_INVALID_ARG;
#else
            int channel;if(!integer(o,"channel",0,15,&channel))return ESP_ERR_INVALID_ARG;
#endif
            /* Channel changes cannot silently reuse another servo's curve. */
            if(c.joint[id].channel!=channel){c.joint[id].channel=channel;c.joint[id].points=0;}
        } else if(!strcmp(op->valuestring,"clear"))c.joint[id].points=0;
        else if(!strcmp(op->valuestring,"capture")) {
            int point,pulse,expected_scan,raw,revision;
            if(!integer(o,"point",0,2,&point)||!integer(o,"pulse_us",1,65535,&pulse)||
               !integer(o,"raw",0,4095,&raw)||!integer(o,"scan",1,INT32_MAX,&expected_scan)||
               !integer(o,"revision",0,INT32_MAX,&revision))return ESP_ERR_INVALID_ARG;
            /* Capture uses the explicit observed raw value and pulse entered
             * by the owner, never an assumption that the commanded shaft arrived.
             * Scan id identifies that observation; no motor movement is sent. */
            if(!s.config.enabled||expected_scan>(int64_t)s.scan||revision!=(int64_t)s.revision)
                return ESP_ERR_INVALID_STATE;
            c.joint[id].point[point]=(ainekio_feedback_point_t){raw,pulse};
            c.joint[id].points|=1U<<point;
        } else return ESP_ERR_INVALID_ARG;
    }
    return save(&c);
}
esp_err_t ainekio_p4_feedback_http(httpd_req_t *r)
{
    esp_err_t result=state?ESP_OK:ESP_ERR_INVALID_STATE;
    if(result==ESP_OK&&r->method==HTTP_POST) {
        char input[1024];
        if(r->content_len<=0||r->content_len>=sizeof(input))result=ESP_ERR_INVALID_SIZE;
        else {
            size_t read=0;
            while(read<(size_t)r->content_len) {
                int n=httpd_req_recv(r,input+read,r->content_len-read);
                if(n<=0){result=ESP_FAIL;break;}read+=n;
            }
            input[read]=0;
            if(result==ESP_OK) {
                cJSON *o=cJSON_Parse(input);
                if(!o)result=ESP_ERR_INVALID_ARG;
                else {
                    xSemaphoreTake(config_mutex,portMAX_DELAY);
                    result=change(o);xSemaphoreGive(config_mutex);cJSON_Delete(o);
                }
            }
        }
    }
    cJSON *o=result==ESP_OK?ainekio_p4_feedback_status_json():cJSON_CreateObject();
    if(!o)return ESP_ERR_NO_MEM;
    if(result!=ESP_OK) {
        httpd_resp_set_status(r,"409 Conflict");
        cJSON_AddStringToObject(o,"error",esp_err_to_name(result));
    }
    char *text=cJSON_PrintUnformatted(o);cJSON_Delete(o);
    if(!text)return ESP_ERR_NO_MEM;
    httpd_resp_set_type(r,"application/json");httpd_resp_set_hdr(r,"Cache-Control","no-store");
    esp_err_t sent=httpd_resp_sendstr(r,text);free(text);return sent;
}
