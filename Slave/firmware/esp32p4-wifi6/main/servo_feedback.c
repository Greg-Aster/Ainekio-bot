#include "servo_feedback.h"
#include "gait_trace_runtime.h"
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
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Allocate after scheduler startup: this board's pre-v3 early internal RAM is
 * scarce. Acquisition never runs inside the motion/output task. */
static ainekio_p4_feedback_snapshot_t *state;
static ainekio_feedback_filter_t *filters;
static SemaphoreHandle_t config_mutex;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
static adc_oneshot_unit_handle_t adc;
static adc_cali_handle_t cali;
static const int select_gpio[4]={27,28,29,30};

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
            if(!adc&&!attempted) {
                attempted=true;esp_err_t e=initialize_adc();
                portENTER_CRITICAL(&lock);state->error=e;state->initialized=e==ESP_OK;portEXIT_CRITICAL(&lock);
            }
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
                bool published=false;
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
                    sample.scan=state->scan;published=true;
                }
                portEXIT_CRITICAL(&lock);
                if(published)ainekio_p4_gait_trace_sample(&sample);
            }
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
        int id;if(!integer(o,"joint",0,11,&id))return ESP_ERR_INVALID_ARG;
        if(!strcmp(op->valuestring,"map")) {
            int channel;if(!integer(o,"channel",0,15,&channel))return ESP_ERR_INVALID_ARG;
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
static cJSON *health_json(const ainekio_p4_feedback_snapshot_t *s)
{
    ainekio_p4_feedback_health_t health;ainekio_p4_feedback_health(s,&health);
    cJSON *o=cJSON_CreateObject();if(!o)return NULL;
    cJSON_AddBoolToObject(o,"enabled",s->config.enabled);
    cJSON_AddBoolToObject(o,"usable",s->config.enabled && health.calibrated==0xfff &&
        !(health.unavailable|health.clipped|health.below_calibration|health.above_calibration));
    cJSON_AddNumberToObject(o,"scan",s->scan);
    cJSON_AddNumberToObject(o,"clock_us",esp_timer_get_time());
    cJSON_AddNumberToObject(o,"calibrated_mask",health.calibrated);
    cJSON_AddNumberToObject(o,"unavailable_mask",health.unavailable);
    cJSON_AddNumberToObject(o,"clipped_mask",health.clipped);
    cJSON_AddNumberToObject(o,"below_calibration_mask",health.below_calibration);
    cJSON_AddNumberToObject(o,"above_calibration_mask",health.above_calibration);
    cJSON_AddStringToObject(o,"adc_error",esp_err_to_name(s->error));
    cJSON_AddBoolToObject(o,"supply_voltage_available",false);
    cJSON *mv=cJSON_AddArrayToObject(o,"signal_millivolts");
    for(unsigned j=0;j<12;j++) {
        unsigned channel=s->config.joint[j].channel;
        cJSON_AddItemToArray(mv,s->config.enabled && (s->valid_mask&(1U<<channel)) &&
            s->millivolts[channel]>=0 ? cJSON_CreateNumber(s->millivolts[channel]):cJSON_CreateNull());
    }
    return o;
}
cJSON *ainekio_p4_feedback_health_json(void)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    return health_json(&s);
}
static cJSON *status_json(void)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    ainekio_p4_calibration_t mapping=ainekio_p4_calibration();
    uint16_t targets[12];ainekio_p4_body_pulses(targets);
    cJSON *o=cJSON_CreateObject();if(!o)return NULL;
    cJSON_AddBoolToObject(o,"enabled",s.config.enabled);cJSON_AddBoolToObject(o,"stand_enabled",s.config.stand_enabled);
    cJSON_AddItemToObject(o,"health",health_json(&s));
    cJSON_AddBoolToObject(o,"jam_enabled",s.config.jam_enabled);
    cJSON_AddBoolToObject(o,"initialized",s.initialized);cJSON_AddBoolToObject(o,"saved",s.saved);
    cJSON_AddNumberToObject(o,"tolerance_us",s.config.tolerance_us);
    cJSON_AddNumberToObject(o,"arrival_tolerance_us",s.config.arrival_tolerance_us);
    cJSON_AddNumberToObject(o,"no_progress_ms",s.config.no_progress_ms);
    cJSON_AddNumberToObject(o,"progress_us",s.config.progress_us);
    cJSON_AddNumberToObject(o,"scan",s.scan);cJSON_AddNumberToObject(o,"scan_us",s.scan_us);
    cJSON_AddNumberToObject(o,"revision",s.revision);
    cJSON_AddStringToObject(o,"error",esp_err_to_name(s.error));
    cJSON_AddStringToObject(o,"voltage_error",esp_err_to_name(s.voltage_error));
    cJSON_AddNumberToObject(o,"device_us",esp_timer_get_time());
    const ainekio_p4_body_status_t motion=ainekio_p4_body_status();
    cJSON_AddBoolToObject(o,"stand_waiting",motion.servo_feedback_waiting);
    cJSON_AddNumberToObject(o,"waiting_joints",motion.servo_feedback_waiting_mask);
    cJSON_AddNumberToObject(o,"stand_progress",motion.stand_progress);
    cJSON_AddBoolToObject(o,"stand_replanning",motion.stand_replanning);
    cJSON_AddNumberToObject(o,"stand_replans",motion.stand_replans);
    cJSON_AddNumberToObject(o,"stalled_joints",motion.stalled_joints);
    cJSON_AddNumberToObject(o,"stall_clock_us",motion.stall_clock_us);
    cJSON *channels=cJSON_AddArrayToObject(o,"channels"),*joints=cJSON_AddArrayToObject(o,"joints");
    for(unsigned channel=0;channel<16;channel++) {
        bool valid=s.config.enabled&&(s.valid_mask&(1U<<channel));
        cJSON *v=cJSON_CreateObject();cJSON_AddItemToArray(channels,v);
        cJSON_AddNumberToObject(v,"channel",channel);cJSON_AddBoolToObject(v,"valid",valid);
        if(valid) {
            cJSON_AddNumberToObject(v,"raw",s.raw[channel]);
            cJSON_AddNumberToObject(v,"filtered_raw",s.filtered_raw[channel]);
            cJSON_AddNumberToObject(v,"velocity_raw_s",s.velocity_raw_s[channel]);
            cJSON_AddNumberToObject(v,"spread",s.spread[channel]);
            cJSON_AddNumberToObject(v,"sampled_us",s.sampled_us[channel]);
            cJSON_AddBoolToObject(v,"at_adc_rail",s.raw[channel]==0||s.raw[channel]==4095);
            if(s.millivolts[channel]>=0)cJSON_AddNumberToObject(v,"millivolts",s.millivolts[channel]);
        }
    }
    for(unsigned id=0;id<12;id++) {
        const ainekio_feedback_joint_t *j=&s.config.joint[id];
        const ainekio_p4_joint_config_t *m=&mapping.joints[id];
        cJSON *v=cJSON_CreateObject();cJSON_AddItemToArray(joints,v);
        cJSON_AddNumberToObject(v,"id",id);cJSON_AddNumberToObject(v,"channel",j->channel);
        cJSON_AddNumberToObject(v,"output",m->channel);
        cJSON_AddBoolToObject(v,"calibrated",ainekio_feedback_calibrated(j));
        unsigned target=m->channel<0?0:targets[m->channel];
        cJSON_AddNumberToObject(v,"command_us",target);
        cJSON *points=cJSON_AddArrayToObject(v,"points");
        for(unsigned p=0;p<3;p++) {
            if(!(j->points&(1U<<p))){cJSON_AddItemToArray(points,cJSON_CreateNull());continue;}
            cJSON *point=cJSON_CreateObject();cJSON_AddItemToArray(points,point);
            cJSON_AddNumberToObject(point,"raw",j->point[p].raw);
            cJSON_AddNumberToObject(point,"pulse_us",j->point[p].pulse_us);
        }
        double measured;bool in_range;
        if(s.config.enabled&&(s.valid_mask&(1U<<j->channel))&&
           ainekio_feedback_position(j,s.raw[j->channel],&measured,&in_range)) {
            cJSON_AddNumberToObject(v,"measured_us",measured);
            cJSON_AddBoolToObject(v,"in_calibrated_range",in_range);
            double degrees=(measured-m->home_us)/m->us_per_degree;
            cJSON_AddNumberToObject(v,"model_deg",m->home_cd/100.+(m->invert?-degrees:degrees));
            if(target)cJSON_AddNumberToObject(v,"error_us",target-measured);
            double filtered,neighbor;
            if(ainekio_feedback_position(j,s.filtered_raw[j->channel],&filtered,&in_range)&&
               ainekio_feedback_position(j,s.filtered_raw[j->channel]+1.,&neighbor,&in_range)) {
                cJSON_AddNumberToObject(v,"filtered_us",filtered);
                cJSON_AddNumberToObject(v,"velocity_us_s",(neighbor-filtered)*s.velocity_raw_s[j->channel]);
                if(target)cJSON_AddNumberToObject(v,"filtered_error_us",target-filtered);
            }
        }
    }
    return o;
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
                    const cJSON *op=cJSON_GetObjectItemCaseSensitive(o,"op");
                    if(cJSON_IsString(op)&&!strncmp(op->valuestring,"trace_",6)) {
                        result=ainekio_p4_gait_trace_http(r,o);cJSON_Delete(o);return result;
                    }
                    xSemaphoreTake(config_mutex,portMAX_DELAY);
                    result=change(o);xSemaphoreGive(config_mutex);cJSON_Delete(o);
                }
            }
        }
    }
    cJSON *o=result==ESP_OK?status_json():cJSON_CreateObject();
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
