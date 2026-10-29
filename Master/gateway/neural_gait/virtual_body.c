/* Offline platform port for the actual P4 output owner. The singleton matches
 * firmware ownership: one virtual robot per worker process. Physics and sensor
 * acquisition are supplied by the existing environment, never by this port.
 * There is no mocked arrival/jam result or alternative movement controller. */
#include "virtual_body.h"
#include "../../../Slave/firmware/esp32p4-wifi6/main/body.c"
#include "imu_telemetry.h"
#include "controller_motion.h"
#include "body_readings.h"
#include "ainekio/control_codec.h"
#include "ainekio/control_encode.h"
#include "ainekio/admission.h"
#include "esp_http_server.h"
#include "nvs.h"
#include "cJSON.h"

static ainekio_admission_t admission;
static uint32_t stopped_sequence;
static uint64_t selected_connection;
static void *sensor_state;
static uint64_t device_us;
static ainekio_pca9685_t virtual_pca;
static uint8_t registers[256];
static bool output_disabled=true;
static double motion_rate;
static bool balance_enabled,heading_enabled;
static ainekio_v2_balance_tuning_t balance_tuning;
static uint32_t idle_rest_seconds;
static ainekio_p4_calibration_t calibration;

struct test_queue {unsigned capacity,size,count;unsigned char data[];};
struct test_timer {esp_timer_create_args_t args;uint64_t due;};
QueueHandle_t xQueueCreate(unsigned n,unsigned size)
{
    QueueHandle_t q=calloc(1,sizeof *q+n*size);
    if(q){q->capacity=n;q->size=size;}return q;
}
int xQueueSend(QueueHandle_t q,const void *value,unsigned wait)
{
    (void)wait;if(!q||q->count==q->capacity)return 0;
    memcpy(q->data+q->size*q->count++,value,q->size);return 1;
}
int xQueueReceive(QueueHandle_t q,void *value,unsigned wait)
{
    /* Deterministic service of the real body request queue, at the supplied
     * device time. No implicit physics advancement or target-arrival shortcut. */
    if(q==results&&!q->count&&wait&&requests->count) {
        body_request_t request;xQueueReceive(requests,&request,0);
        const body_result_t result={request.serial,process_request(&request,device_us)};
        xQueueSend(results,&result,0);
    }
    if(!q||!q->count)return 0;
    memcpy(value,q->data,q->size);--q->count;
    memmove(q->data,q->data+q->size,q->count*q->size);return 1;
}
int xQueueOverwrite(QueueHandle_t q,const void *value)
{if(!q||q->capacity!=1)return 0;q->count=0;return xQueueSend(q,value,0);}
unsigned uxQueueSpacesAvailable(QueueHandle_t q){return q->capacity-q->count;}
unsigned uxQueueMessagesWaiting(QueueHandle_t q){return q->count;}
void *xSemaphoreCreateMutex(void){return (void *)1;}
int xSemaphoreTake(void *p,unsigned t){(void)p;(void)t;return 1;}
int xSemaphoreGive(void *p){(void)p;return 1;}
int xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned stack,void*a,unsigned pri,void*h,unsigned core)
{(void)fn;(void)n;(void)stack;(void)a;(void)pri;(void)h;(void)core;return 1;}
void vTaskDelay(unsigned ticks){(void)ticks;}
int64_t esp_timer_get_time(void){return device_us;}
esp_err_t esp_timer_create(const esp_timer_create_args_t *args,esp_timer_handle_t *timer)
{*timer=calloc(1,sizeof **timer);if(!*timer)return ESP_ERR_NO_MEM;(*timer)->args=*args;return ESP_OK;}
esp_err_t esp_timer_start_once(esp_timer_handle_t timer,uint64_t delay)
{if(timer->due)return ESP_ERR_INVALID_STATE;timer->due=device_us+delay;return ESP_OK;}
esp_err_t esp_timer_stop(esp_timer_handle_t timer){timer->due=0;return ESP_OK;}

/* The simulated ADC/voltage acquisition supplies these ESP result values. */
const char *esp_err_to_name(esp_err_t error)
{
    switch(error) {
    case ESP_OK:return "ESP_OK";
    case ESP_FAIL:return "ESP_FAIL";
    case ESP_ERR_INVALID_STATE:return "ESP_ERR_INVALID_STATE";
    case ESP_ERR_INVALID_ARG:return "ESP_ERR_INVALID_ARG";
    case ESP_ERR_NOT_SUPPORTED:return "ESP_ERR_NOT_SUPPORTED";
    case ESP_ERR_TIMEOUT:return "ESP_ERR_TIMEOUT";
    case ESP_ERR_NO_MEM:return "ESP_ERR_NO_MEM";
    default:return "UNKNOWN ERROR";
    }
}

static void bus_lock(void *p){(void)p;}
static void bus_oe(void *p,bool disabled){(void)p;output_disabled=disabled;}
static uint64_t bus_now(void *p){(void)p;return device_us;}
static void bus_sleep(void *p,uint32_t delay){(void)p;(void)delay;}
static ainekio_pca_bus_result_t bus_write(void *p,uint8_t reg,const uint8_t *data,size_t n,uint32_t timeout)
{
    (void)p;(void)timeout;if((size_t)reg+n>sizeof registers)return AINEKIO_PCA_BUS_ERROR;
    memcpy(registers+reg,data,n);return AINEKIO_PCA_BUS_OK;
}
static ainekio_pca_bus_result_t bus_read(void *p,uint8_t reg,uint8_t *data,size_t n,uint32_t timeout)
{
    (void)p;(void)timeout;if((size_t)reg+n>sizeof registers)return AINEKIO_PCA_BUS_ERROR;
    memcpy(data,registers+reg,n);return AINEKIO_PCA_BUS_OK;
}
ainekio_pca9685_t *ainekio_p4_output(void){return &virtual_pca;}
ainekio_p4_calibration_t ainekio_p4_calibration(void){return calibration;}
bool ainekio_p4_home_pulses(uint16_t pulses[12])
{
    memset(pulses,0,12*sizeof *pulses);
    for(unsigned j=0;j<12;j++)if(calibration.joints[j].channel>=0)
        pulses[(unsigned)calibration.joints[j].channel]=calibration.joints[j].home_us;
    return calibration.valid;
}
bool ainekio_p4_frame_pulses(const ainekio_v2_frame_t *frame,uint16_t pulses[12])
{
    if(!ainekio_p4_joint_map_frame(calibration.joints,frame,pulses))return false;
    for(unsigned j=0;j<12;j++)if(pulses[j]&&!ainekio_pca_pulse_valid(&virtual_pca,pulses[j]))return false;
    return true;
}
bool ainekio_p4_balance_enabled(void){return balance_enabled;}
bool ainekio_p4_walking_feedback_enabled(void){return heading_enabled;}
ainekio_v2_balance_tuning_t ainekio_p4_balance_tuning(void){return balance_tuning;}
float ainekio_p4_motion_rate(void){return motion_rate;}
uint32_t ainekio_p4_idle_rest_seconds(void){return idle_rest_seconds;}
ainekio_p4_imu_status_t ainekio_p4_imu_status(void)
{ainekio_p4_imu_status_t out;simulation_p4_imu(sensor_state,device_us,&out);return out;}
bool ainekio_p4_feedback_stand_enabled(void)
{ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);return s.config.stand_enabled;}
bool ainekio_p4_feedback_jam_enabled(void)
{ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);return s.config.enabled&&s.config.jam_enabled&&s.config.no_progress_ms;}
ainekio_p4_system_status_t ainekio_p4_system_status(void)
{return (ainekio_p4_system_status_t){.state=AINEKIO_STATE_IDLE};}
ainekio_p4_media_status_t ainekio_p4_media_status(void)
{return (ainekio_p4_media_status_t){0};}
void ainekio_p4_log_stage(const char *stage){(void)stage;}
void ainekio_p4_gait_trace_output(const uint16_t p[12],uint64_t at,bool armed)
{(void)p;(void)at;(void)armed;}
void ainekio_p4_gait_trace_tracking(const ainekio_gait_trace_event_t *event){(void)event;}

/* The virtual body has no saved legacy gait model. Compile its real owner,
 * including its no-model path; do not substitute empty learning callbacks. */
esp_err_t nvs_open(const char *name,int mode,nvs_handle_t *handle)
{(void)name;(void)mode;*handle=1;return ESP_OK;}
esp_err_t nvs_get_blob(nvs_handle_t h,const char *k,void *v,size_t *n)
{(void)h;(void)k;(void)v;(void)n;return ESP_ERR_NVS_NOT_FOUND;}
esp_err_t nvs_set_blob(nvs_handle_t h,const char *k,const void *v,size_t n)
{(void)h;(void)k;(void)v;(void)n;return ESP_ERR_NOT_SUPPORTED;}
esp_err_t nvs_commit(nvs_handle_t h){(void)h;return ESP_ERR_NOT_SUPPORTED;}
void nvs_close(nvs_handle_t h){(void)h;}
esp_err_t httpd_resp_set_status(httpd_req_t *r,const char *s){(void)r;(void)s;return ESP_ERR_NOT_SUPPORTED;}
esp_err_t httpd_resp_set_type(httpd_req_t *r,const char *s){(void)r;(void)s;return ESP_ERR_NOT_SUPPORTED;}
esp_err_t httpd_resp_sendstr(httpd_req_t *r,const char *s){(void)r;(void)s;return ESP_ERR_NOT_SUPPORTED;}
int httpd_req_recv(httpd_req_t *r,char *out,size_t n){(void)r;(void)out;(void)n;return -1;}

void virtual_body_close(void)
{
    free(requests);free(results);free(events);requests=results=events=NULL;
    free(rest_timer);rest_timer=NULL;caller_lock=NULL;sensor_state=NULL;
    simulation_p4_activate(NULL);
    admission=(ainekio_admission_t){0};selected_connection=0;
}
int virtual_body_reset(void *sensor,const double *reference,const double *settings,uint64_t now)
{
    virtual_body_close();sensor_state=sensor;simulation_p4_activate(sensor);
    simulation_p4_mapping(sensor,&calibration);device_us=now;
    motion_rate=settings[1];balance_enabled=settings[2];heading_enabled=settings[3];
    balance_tuning=(ainekio_v2_balance_tuning_t){settings[4],settings[5],settings[6],settings[7]};
    idle_rest_seconds=settings[8];
    if(!ainekio_v2_joint_speed_set(settings[0]))return 0;
    body=(body_state_t){0};motion_status=(ainekio_p4_body_status_t){0};
    timing=(ainekio_p4_body_timing_t){0};listen_requested=false;request_serial=0;
    memset(commanded,0,sizeof commanded);memset(registers,0,sizeof registers);
    const ainekio_pca_port_t port={.lock=bus_lock,.unlock=bus_lock,.disable_output=bus_oe,
        .now_us=bus_now,.sleep_us=bus_sleep,.write=bus_write,.read=bus_read};
    const ainekio_pca_config_t config={.oscillator_hz=settings[9],.frequency_hz=settings[10]};
    if(ainekio_pca_init(&virtual_pca,&port,&config)!=AINEKIO_PCA_OK ||
       ainekio_p4_body_start()!=ESP_OK)return 0;
    ainekio_p4_learning_init();
    /* Explicit episode initial condition, not a claimed boot/Stand completion. */
    ainekio_v2_frame_t frame={.geometry_id=ainekio_v2_walk_geometry_id};
    for(unsigned j=0;j<12;j++)frame.position[j]=reference[j]*100.;
    if(!ainekio_p4_frame_pulses(&frame,body.pulses) ||
       ainekio_pca_arm(&virtual_pca,virtual_pca.state.generation,body.pulses)!=AINEKIO_PCA_OK)return 0;
    body.active=true;body.generation=virtual_pca.state.generation;
    body.last_frame=now;body.next_frame=now+20000;
    retain_manual_reference();publish(body.pulses);publish_motion();return 1;
}
int virtual_body_tick(uint64_t now,double *out)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;simulation_p4_activate(sensor_state);
    if(ainekio_admission_check_stale(&admission,now))
        virtual_body_connection_lost(selected_connection);
    output_step(now);
    if(rest_timer->due&&now>=rest_timer->due){rest_timer->due=0;rest_timer->args.callback(rest_timer->args.arg);}
    rest_step(now);
    const double tick_us=1e6*(virtual_pca.prescale+1U)/virtual_pca.config.oscillator_hz;
    unsigned enabled=0;
    for(unsigned c=0;c<12;c++) {
        const uint8_t *p=registers+6+4*c;
        const bool on=!output_disabled&&!(p[3]&16);
        unsigned ticks=(((unsigned)p[2]|((p[3]&15)<<8))-((unsigned)p[0]|((p[1]&15)<<8)))&4095;
        if(p[1]&16)ticks=4096;
        out[c]=commanded[c];out[12+c]=ticks*tick_us;if(on)enabled|=1U<<c;
    }
    out[24]=enabled;out[25]=virtual_pca.state.generation;out[26]=virtual_pca.state.armed;
    out[27]=body.motion.sequence;out[28]=body.execution.nominal_sample;
    out[29]=body.execution.sampled_us;return 1;
}
size_t virtual_body_telemetry(uint64_t now,char *text,size_t capacity)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;simulation_p4_activate(sensor_state);
    const ainekio_p4_imu_status_t imu=ainekio_p4_imu_status();
    const ainekio_p4_execution_t execution=ainekio_p4_body_execution_at(imu.attitude.timestamp_us);
    ainekio_p4_feedback_snapshot_t sample;ainekio_p4_feedback_snapshot(&sample);
    ainekio_p4_feedback_observation_t observation;
    uint16_t targets[12];ainekio_p4_body_pulses(targets);
    ainekio_p4_feedback_observe(&sample,calibration.joints,targets,&observation);
    observation.device_us=now;observation.stalled_joints=body.stalled_joints;
    return ainekio_imu_telemetry(&imu,1,&execution,NULL,&observation,text,capacity);
}

/* Networking is replaced by a synchronous transport, not by a second command
 * owner. Decode, session/sequence admission, Stop and body receipts remain the
 * production implementations. Receive-to-dispatch latency is zero in this port. */
void virtual_body_open(uint64_t connection,uint64_t now)
{
    if(admission.connected) {
        ainekio_admission_close(&admission,admission.generation);
        ainekio_p4_body_connection_lost(selected_connection);
    }
    device_us=now;selected_connection=connection;stopped_sequence=0;
    ainekio_admission_init(&admission,
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_INTENT)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STOP)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MOTION_PLAN)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_WALK_TARGET)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_BODY_CALIBRATION)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MOTION_SPEED),true);
    admission.generation=connection-1;
    ainekio_admission_open(&admission);
    ainekio_core_set_boot_ready(&admission.core,true);
}
void virtual_body_connection_lost(uint64_t connection)
{
    const bool current=admission.connected&&admission.generation==connection;
    ainekio_admission_close(&admission,connection);
    if(current)ainekio_p4_body_connection_lost(connection);
}
size_t virtual_body_hello(const char *id,const char *token,uint64_t now,char *text,size_t capacity)
{
    const char *commands[]={"walk","stop","motion_plan"};
    const ainekio_capabilities_t caps={.motion=true,.commands=commands,.command_count=3};
    const char *features[]={AINEKIO_MOTION_TARGETS_FEATURE,"command_deadline_v1",
        "body_capabilities_v1","body_commands_v1","walk_controls_v2",
        AINEKIO_WALK_STEERING_FEATURE,AINEKIO_WALK_LATERAL_FEATURE,AINEKIO_WALK_NOMINAL_FEATURE,
        "run_gait_v1","crab_gait_v1","servo_feedback_v1",
        "body_calibration_v2","motion_speed_v1","joint_speed_limit_v1"};
    const ainekio_hello_t hello={.firmware="virtual-p4-body",.robot_id=id,.auth_token=token,
        .features=features,.feature_count=sizeof features/sizeof *features,
        .model="v2-12servo",.clock_ms=now/1000,.capabilities=&caps};
    return ainekio_encode_hello(&hello,text,capacity);
}
size_t virtual_body_receive(const char *wire,uint64_t connection,uint64_t now,char *text,size_t capacity)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;simulation_p4_activate(sensor_state);
    ainekio_control_message_t message;
    if(ainekio_control_decode_for_body(wire,strlen(wire),&message)!=AINEKIO_DECODE_OK)
        return ainekio_encode_nak(false,0,AINEKIO_NAK_MALFORMED,"Invalid control frame",text,capacity);
    if(message.kind==AINEKIO_MESSAGE_WELCOME) {
        ainekio_admission_welcome(&admission,connection,message.data.welcome.epoch,
            message.data.welcome.profile,message.data.welcome.deadline_supported,now);
        return 0;
    }
    if(ainekio_admission_check_stale(&admission,now))virtual_body_connection_lost(connection);
    if(!ainekio_admission_control(&admission,connection,now))
        return message.has_command?ainekio_p4_rejection(&message,AINEKIO_REJECT_STALE,text,capacity):0;
    if(message.kind==AINEKIO_MESSAGE_PING)return ainekio_encode_ping(true,text,capacity);
    if(!message.has_command)return 0;
    const uint64_t generation=ainekio_pca_status(&virtual_pca).generation;
    const ainekio_body_state_t previous_state=admission.core.state;
    ainekio_core_set_boot_ready(&admission.core,true);
    const bool stop=message.command.kind==AINEKIO_COMMAND_STOP;
    const bool calibration_get=message.command.kind==AINEKIO_COMMAND_BODY_CALIBRATION &&
        message.command.data.calibration.operation==AINEKIO_CALIBRATION_GET;
    const bool speed_get=message.command.kind==AINEKIO_COMMAND_MOTION_SPEED &&
        !message.command.data.motion_speed.save;
    const ainekio_decision_t decision=stop?
        ainekio_p4_stop_accept(&admission,&virtual_pca,connection,&message,now,now):
        ainekio_admission_accept(&admission,connection,&message,now,now,
            (calibration_get||speed_get||ainekio_p4_body_supports(&message.command)));
    if(!decision.accepted)return ainekio_p4_rejection(&message,decision.rejection,text,capacity);
    if(calibration_get||speed_get) {
        char ack[80],speed[320];
        ainekio_encode_ack(message.sequence,0,ack,sizeof ack);
        cJSON *status;
        if(calibration_get)status=ainekio_p4_calibration_json(message.sequence);
        else {
            ainekio_p4_motion_speed_json(message.sequence,motion_rate,false,
                ainekio_v2_gait_joint_speed_limit(),false,speed,sizeof speed);
            status=cJSON_Parse(speed);
        }
        cJSON *packets=cJSON_CreateArray();
        if(!packets||!status){cJSON_Delete(packets);cJSON_Delete(status);return 0;}
        cJSON_AddItemToArray(packets,cJSON_Parse(ack));cJSON_AddItemToArray(packets,status);
        const bool ok=cJSON_PrintPreallocated(packets,text,capacity,false);
        cJSON_Delete(packets);return ok?strlen(text):0;
    }
    if(stop)stopped_sequence=message.sequence;
    const esp_err_t result=ainekio_p4_body_execute(generation,connection,&message.command);
    if(result!=ESP_OK) {
        admission.core.state=previous_state;
        return ainekio_p4_execution_error(message.sequence,result,
            ainekio_pca_status(&virtual_pca).fault,false,AINEKIO_STATE_IDLE,text,capacity);
    }
    if(message.command.kind!=AINEKIO_COMMAND_WALK_TARGET)ainekio_p4_body_activity();
    return ainekio_encode_ack(message.sequence,0,text,capacity);
}
size_t virtual_body_events(char *text,size_t capacity)
{
    cJSON *array=cJSON_CreateArray();if(!array)return 0;
    ainekio_p4_body_event_t event;char buffer[1024];
    while(admission.connected&&admission.authenticated&&ainekio_p4_body_event(&event)) {
        if(ainekio_p4_body_notice(&event,1,buffer,sizeof buffer))
            cJSON_AddItemToArray(array,cJSON_Parse(buffer));
        if(event.connection!=selected_connection)continue;
        size_t n=ainekio_p4_body_receipt(&event,stopped_sequence,buffer,sizeof buffer);
        if(!n&&!event.jam_observation&&event.sequence>stopped_sequence&&event.result!=ESP_OK)
            n=ainekio_p4_execution_error(event.sequence,event.result,
                ainekio_pca_status(&virtual_pca).fault,false,AINEKIO_STATE_IDLE,buffer,sizeof buffer);
        if(n)cJSON_AddItemToArray(array,cJSON_Parse(buffer));
    }
    const bool ok=cJSON_PrintPreallocated(array,text,capacity,false);
    cJSON_Delete(array);return ok?strlen(text):0;
}

size_t virtual_body_feedback(uint64_t now,char *text,size_t capacity)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;simulation_p4_activate(sensor_state);
    cJSON *value=ainekio_p4_feedback_status_json();
    const bool ok=value && cJSON_PrintPreallocated(value,text,capacity,false);
    cJSON_Delete(value);return ok?strlen(text):0;
}
