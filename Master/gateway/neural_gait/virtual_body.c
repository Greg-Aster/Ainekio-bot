/* Offline platform port for the actual P4 output owner. The singleton matches
 * firmware ownership: one virtual robot per worker process. Physics and sensor
 * acquisition are supplied by the existing environment, never by this port.
 * There is no mocked arrival/jam result or alternative movement controller. */
#include "virtual_body.h"
#include "../../../Slave/firmware/esp32p4-wifi6/main/body.c"
#include "imu_telemetry.h"
#include "controller_motion.h"
#include "body_readings.h"
#include "face_timeline.h"
#include "ainekio/face.h"
#include "ainekio/control_codec.h"
#include "ainekio/control_encode.h"
#include "ainekio/admission.h"
#include "cJSON.h"
#include <inttypes.h>

static ainekio_admission_t admission;
static uint32_t stopped_sequence;
static uint64_t selected_connection;
static void *sensor_state;
static uint64_t device_us;
static uint64_t boot_us;
static ainekio_pca9685_t virtual_pca;
static uint8_t registers[256];
static bool output_disabled=true;
static double motion_rate;
static bool balance_enabled,heading_enabled;
static bool balance_saved=true,balance_tuning_saved=true,walking_saved=true;
static bool motion_rate_saved=true,joint_speed_saved=true;
static ainekio_v2_balance_tuning_t balance_tuning;
static uint32_t idle_rest_seconds;
static ainekio_p4_calibration_t calibration;

/* Full-parity simulator peripheral & face state (inert when full_parity=false). */
static bool full_parity;
static int sim_face_style;
static ainekio_p4_media_status_t sim_media;
static ainekio_body_state_t sim_system_state=AINEKIO_STATE_IDLE;
static float sim_battery_voltage=8.15F;
static ainekio_p4_face_selection_t sim_face_selection;
static ainekio_p4_face_clock_t sim_face_clock;
static size_t sim_shown_face;
static bool sim_was_listening;
static uint64_t sim_listening_since_ms;
static uint16_t sim_face_rgb565[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT];
static cJSON *sim_media_action_queue;

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
{
    const uint64_t elapsed_ms=device_us>=boot_us?(device_us-boot_us)/1000U:0U;
    return (ainekio_p4_system_status_t){
        .state=sim_system_state,
        .profile=admission.core.profile,
        .uptime_ms=elapsed_ms,
        .heap_free=16U*1024U*1024U,
        .battery_available=full_parity,
    };
}
ainekio_p4_media_status_t ainekio_p4_media_status(void)
{return full_parity ? sim_media : (ainekio_p4_media_status_t){0};}
void ainekio_p4_log_stage(const char *stage){(void)stage;}

static void queue_media_action(cJSON *action)
{
    if(!action)return;
    if(!sim_media_action_queue)sim_media_action_queue=cJSON_CreateArray();
    if(!sim_media_action_queue){cJSON_Delete(action);return;}
    cJSON_AddItemToArray(sim_media_action_queue,action);
}

static const char *camera_res_name(ainekio_camera_resolution_t res)
{
    switch(res) {
    case AINEKIO_CAMERA_QVGA:return "QVGA";
    case AINEKIO_CAMERA_VGA:return "VGA";
    case AINEKIO_CAMERA_XGA:return "XGA";
    case AINEKIO_CAMERA_960P:return "960P";
    case AINEKIO_CAMERA_FHD:return "FHD";
    case AINEKIO_CAMERA_AUTO:return "AUTO";
    default:return "QVGA";
    }
}

static const char *mic_gate_name(ainekio_microphone_gate_t gate)
{
    switch(gate) {
    case AINEKIO_MIC_GATE_WAKE:return "wake";
    case AINEKIO_MIC_GATE_VAD:return "vad";
    default:return "open";
    }
}

static const char *const full_base_commands[]={
    "stop","say","face","stand","neutral","walk","backward","left","right","crawl","run",
    "crab","crab_right","crab_forward","crab_backward","crab_turn_left","crab_turn_right"
};
enum { FULL_BASE_COMMAND_COUNT = sizeof(full_base_commands)/sizeof(full_base_commands[0]) };

static ainekio_capabilities_t build_full_capabilities(const char **commands)
{
    size_t count=FULL_BASE_COMMAND_COUNT;
    memcpy(commands,full_base_commands,sizeof full_base_commands);
    for(size_t i=0;i<ainekio_v2_clip_count;++i) {
        bool duplicate=false;
        for(size_t j=0;j<count;++j)
            if(strcmp(commands[j],ainekio_v2_clips[i].command)==0)duplicate=true;
        if(!duplicate)commands[count++]=ainekio_v2_clips[i].command;
    }
    return (ainekio_capabilities_t){
        .commands=commands,
        .command_count=count,
        .motion=calibration.valid,
        .camera=sim_media.camera_ready,
        .microphone=sim_media.microphone_ready,
        .speaker=sim_media.speaker_ready,
        .wake=sim_media.wake_ready,
        .profile=true,
        .power=true,
        .storage=false,
        .display=true,
        .motion_reason=calibration.valid?NULL:"Joint calibration is invalid.",
        .camera_reason=sim_media.camera_ready?NULL:"Virtual OV5647 camera is not connected.",
        .microphone_reason=sim_media.microphone_ready?NULL:"Virtual microphone is not ready.",
        .speaker_reason=sim_media.speaker_ready?NULL:"Virtual speaker is not ready.",
    };
}

static size_t append_sim_motion_diagnostics(char *text,size_t capacity,size_t length)
{
    const ainekio_pca_status_t output=ainekio_pca_status(&virtual_pca);
    const ainekio_p4_body_timing_t t=ainekio_p4_body_timing();
    const ainekio_p4_body_status_t motion=ainekio_p4_body_status();
    const ainekio_p4_gyro_calibration_status_t gyro=ainekio_p4_imu_status().gyro_calibration;
    const char *face_name=ainekio_face_name(sim_shown_face);
    if(!face_name)face_name="default";
    const int added=snprintf(text+length-1U,capacity-length+1U,
        ",\"face\":\"%s\""
        ",\"gait_cadence\":{\"automatic_run\":%s,\"cycles_s\":%.6g,\"requested_cycles_s\":%.6g,\"stride_percent\":%.6g,\"requested_stride_percent\":%.6g},\"speed_limited\":%s,\"joint_speed_limit_deg_s\":%.9g,\"clock_ms\":%" PRIu64 ",\"output_fault\":%u,\"controller_queue_depth\":0,"
        "\"output_timing\":{\"last_io_us\":%" PRIu64 ",\"max_io_us\":%" PRIu64
        ",\"transfers\":%" PRIu32 ",\"failures\":%" PRIu32 ",\"budget_us\":%" PRIu64
        ",\"last_esp_error\":0},"
        "\"motion_timing\":{\"frames\":%" PRIu32 ",\"max_calculation_us\":%" PRIu32
        ",\"max_frame_us\":%" PRIu32 ",\"max_request_us\":%" PRIu32
        ",\"over_2ms\":%" PRIu32 ",\"over_5ms\":%" PRIu32 ",\"queue_depth\":%" PRIu32 "},"
        "\"walking_feedback\":{\"enabled\":%s,\"active\":%s,\"reduced\":%s,\"heading_error_rad\":%.6g,\"turn_percent\":%.6g},"
        "\"balance\":{\"enabled\":%s,\"active\":%s,\"reduced\":%s,\"settled\":%s,\"settle_deg\":%.3g,\"wake_deg\":%.3g,\"roll_rad\":%.6g,\"pitch_rad\":%.6g,"
        "\"roll_correction_rad\":%.6g,\"pitch_correction_rad\":%.6g,"
        "\"legs_valid\":%s,\"extension_mm\":[%.4g,%.4g,%.4g,%.4g],"
        "\"joint_delta_deg\":[%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g],"
        "\"joint_feedback\":{\"available\":%s,\"active\":%s,\"reduced\":%s,"
        "\"mode\":\"actuator_tracking\",\"gain\":0,\"tracking_rate_s\":4,\"body_lag_rad\":[%.5g,%.5g],\"tolerance_us\":%.3g,\"error_deg\":[%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g],"
        "\"trim_deg\":[%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g,%.4g]},"
        "\"gyro_calibration\":{\"phase\":%u,\"samples\":%u,\"target\":%u,\"error\":%d,"
        "\"bias_rad_s\":[%.6g,%.6g,%.6g],\"deviation_rad_s\":[%.6g,%.6g,%.6g]}}}",
        face_name,motion.automatic_run?"true":"false",(double)motion.gait_cycles_s,
        (double)motion.gait_requested_cycles_s,(double)motion.stride_percent,(double)motion.requested_stride_percent,
        motion.speed_limited?"true":"false",ainekio_v2_gait_joint_speed_limit(),
        device_us/1000U,(unsigned)output.fault,
        output.last_io_us,output.max_io_us,output.io_transfers,output.io_failures,
        (uint64_t)AINEKIO_PCA_IO_BUDGET_US,t.frames,t.calculation_us,t.frame_us,
        t.request_us,t.over_2ms,t.over_5ms,t.queue_depth,
        heading_enabled?"true":"false",(output.armed&&motion.walking_feedback_active)?"true":"false",
        motion.walking_feedback_reduced?"true":"false",
        (double)motion.walking_heading_error_rad,(double)motion.walking_turn_percent,
        balance_enabled?"true":"false",(balance_enabled&&output.armed&&motion.balance_active)?"true":"false",
        motion.balance_reduced?"true":"false",(output.armed&&motion.balance_settled)?"true":"false",
        (double)BALANCE_SETTLE_DEG,(double)BALANCE_WAKE_DEG,
        (double)motion.body_roll_rad,(double)motion.body_pitch_rad,
        (double)motion.balance_roll_rad,(double)motion.balance_pitch_rad,
        motion.balance_legs_valid?"true":"false",
        (double)motion.balance_extension_mm[0],(double)motion.balance_extension_mm[1],
        (double)motion.balance_extension_mm[2],(double)motion.balance_extension_mm[3],
        (double)motion.balance_joint_delta_deg[0],(double)motion.balance_joint_delta_deg[1],(double)motion.balance_joint_delta_deg[2],
        (double)motion.balance_joint_delta_deg[3],(double)motion.balance_joint_delta_deg[4],(double)motion.balance_joint_delta_deg[5],
        (double)motion.balance_joint_delta_deg[6],(double)motion.balance_joint_delta_deg[7],(double)motion.balance_joint_delta_deg[8],
        (double)motion.balance_joint_delta_deg[9],(double)motion.balance_joint_delta_deg[10],(double)motion.balance_joint_delta_deg[11],
        motion.balance_tracking_available?"true":"false",(output.armed&&motion.balance_tracking_active)?"true":"false",
        motion.balance_tracking_reduced?"true":"false",
        (double)motion.balance_tracking_lag_rad[0],(double)motion.balance_tracking_lag_rad[1],
        (double)BALANCE_SHAFT_TOLERANCE_US,
        (double)motion.balance_tracking_error_deg[0],(double)motion.balance_tracking_error_deg[1],(double)motion.balance_tracking_error_deg[2],
        (double)motion.balance_tracking_error_deg[3],(double)motion.balance_tracking_error_deg[4],(double)motion.balance_tracking_error_deg[5],
        (double)motion.balance_tracking_error_deg[6],(double)motion.balance_tracking_error_deg[7],(double)motion.balance_tracking_error_deg[8],
        (double)motion.balance_tracking_error_deg[9],(double)motion.balance_tracking_error_deg[10],(double)motion.balance_tracking_error_deg[11],
        (double)motion.balance_tracking_trim_deg[0],(double)motion.balance_tracking_trim_deg[1],(double)motion.balance_tracking_trim_deg[2],
        (double)motion.balance_tracking_trim_deg[3],(double)motion.balance_tracking_trim_deg[4],(double)motion.balance_tracking_trim_deg[5],
        (double)motion.balance_tracking_trim_deg[6],(double)motion.balance_tracking_trim_deg[7],(double)motion.balance_tracking_trim_deg[8],
        (double)motion.balance_tracking_trim_deg[9],(double)motion.balance_tracking_trim_deg[10],(double)motion.balance_tracking_trim_deg[11],
        gyro.phase,gyro.samples,AINEKIO_GYRO_CALIBRATION_SAMPLES,(int)gyro.error,
        (double)gyro.bias_rad_s[0],(double)gyro.bias_rad_s[1],(double)gyro.bias_rad_s[2],
        (double)gyro.deviation_rad_s[0],(double)gyro.deviation_rad_s[1],(double)gyro.deviation_rad_s[2]);
    if(added<=0 || length-1U+(size_t)added>=capacity)return 0;
    return length-1U+(size_t)added;
}

void virtual_body_set_full_parity(int enabled)
{
    full_parity=enabled!=0;
}

void virtual_body_set_face_style(int style)
{
    sim_face_style=style==1 ? 1 : 0;
}

void virtual_body_set_media_state(int camera_ready,int microphone_ready,
    int speaker_ready,int wake_ready,int display_ready,int capturing,
    int speaker_busy,int external_speech,float mic_rms,float mic_peak,
    float battery_voltage)
{
    (void)display_ready;
    sim_media.camera_ready=camera_ready!=0;
    sim_media.microphone_ready=microphone_ready!=0;
    sim_media.speaker_ready=speaker_ready!=0;
    sim_media.wake_ready=wake_ready!=0;
    sim_media.utterance_open=capturing!=0;
    sim_media.speaker_busy=speaker_busy!=0;
    sim_media.external_speech=external_speech!=0;
    sim_media.microphone_rms=mic_rms;
    sim_media.microphone_peak=mic_peak;
    if(battery_voltage>0.F)sim_battery_voltage=battery_voltage;
}

void virtual_body_close(void)
{
    free(requests);free(results);free(events);requests=results=events=NULL;
    free(rest_timer);rest_timer=NULL;caller_lock=NULL;sensor_state=NULL;
    if(sim_media_action_queue){cJSON_Delete(sim_media_action_queue);sim_media_action_queue=NULL;}
    simulation_p4_activate(NULL);
    admission=(ainekio_admission_t){0};selected_connection=0;
    full_parity=false;
    sim_face_selection=(ainekio_p4_face_selection_t){0};
    sim_face_clock=(ainekio_p4_face_clock_t){0};
    sim_shown_face=0;sim_was_listening=false;sim_listening_since_ms=0;
}
int virtual_body_reset(void *sensor,const double *reference,const double *settings,uint64_t now)
{
    virtual_body_close();sensor_state=sensor;simulation_p4_activate(sensor);
    simulation_p4_mapping(sensor,&calibration);device_us=now;boot_us=now;
    motion_rate=settings[1];balance_enabled=settings[2];heading_enabled=settings[3];
    balance_saved=true;balance_tuning_saved=true;walking_saved=true;
    motion_rate_saved=true;joint_speed_saved=true;
    balance_tuning=(ainekio_v2_balance_tuning_t){settings[4],settings[5],settings[6],settings[7]};
    idle_rest_seconds=settings[8];
    if(!ainekio_v2_joint_speed_set(settings[0]))return 0;
    sim_system_state=AINEKIO_STATE_IDLE;
    sim_media=(ainekio_p4_media_status_t){
        .camera_ready=true,
        .microphone_ready=true,
        .speaker_ready=true,
        .wake_ready=true,
        .microphone_enabled=false,
        .microphone_listening=false,
        .microphone_gate=AINEKIO_MIC_GATE_OPEN,
        .microphone_gain_db=18,
        .vad_mode=2,
        .silence_ms=700,
        .max_recording_ms=15000,
        .speaker_volume_percent=80,
        .wake_enabled=false,
        .wake_threshold=0.5F,
    };
    strcpy(sim_media.wake_model,AINEKIO_DEFAULT_WAKE_MODEL);
    ainekio_face_find("default",&sim_shown_face);
    body=(body_state_t){0};motion_status=(ainekio_p4_body_status_t){0};
    timing=(ainekio_p4_body_timing_t){0};listen_requested=false;request_serial=0;
    memset(commanded,0,sizeof commanded);memset(registers,0,sizeof registers);
    const ainekio_pca_port_t port={.lock=bus_lock,.unlock=bus_lock,.disable_output=bus_oe,
        .now_us=bus_now,.sleep_us=bus_sleep,.write=bus_write,.read=bus_read};
    const ainekio_pca_config_t config={.oscillator_hz=settings[9],.frequency_hz=settings[10]};
    if(ainekio_pca_init(&virtual_pca,&port,&config)!=AINEKIO_PCA_OK ||
       ainekio_p4_body_start()!=ESP_OK)return 0;
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
    const char *token=full_parity ? ainekio_p4_face_token(&sim_face_selection,now/1000U) : NULL;
    return ainekio_imu_telemetry(&imu,1,&execution,token,&observation,text,capacity);
}

size_t virtual_body_status(uint64_t now,char *text,size_t capacity)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;simulation_p4_activate(sensor_state);
    const ainekio_p4_system_status_t system=ainekio_p4_system_status();
    const ainekio_pca_status_t output=ainekio_pca_status(&virtual_pca);
    const ainekio_body_state_t state=(system.state==AINEKIO_STATE_DOZING ||
        system.state==AINEKIO_STATE_DEEP_SLEEP)?system.state:admission.core.state;
    const char *commands[FULL_BASE_COMMAND_COUNT+ainekio_v2_clip_count];
    const ainekio_capabilities_t caps=build_full_capabilities(commands);
    ainekio_body_status_fields_t body_fields={
        .mode=admission.core.mode,
        .output_ready=output.ready,
        .output_armed=output.armed,
        .output_fault=output.fault,
        .calibration_dirty=calibration.dirty,
        .calibration_saved=calibration.saved,
        .power_monitor_ready=true,
        .microphone_ready=sim_media.microphone_ready,
        .speaker_ready=sim_media.speaker_ready,
        .display_ready=true,
        .capabilities=&caps,
    };
    ainekio_status_t status={
        .battery_voltage=sim_battery_voltage,
        .rssi=-42,
        .state=state,
        .uptime_seconds=(uint32_t)(system.uptime_ms/1000U),
        .free_heap=system.heap_free,
        .sd_available=false,
        .camera_ready=sim_media.camera_ready,
        .camera_drops=0,
        .speaker_underruns=0,
        .microphone_drops=0,
        .wake_enabled=sim_media.wake_enabled,
        .wake_ready=sim_media.wake_ready,
        .body=&body_fields,
    };
    memcpy(status.wake_model,sim_media.wake_model,sizeof status.wake_model);
    if(!status.wake_model[0])strcpy(status.wake_model,AINEKIO_DEFAULT_WAKE_MODEL);
    const size_t length=ainekio_encode_status(&status,text,capacity);
    if(!length)return 0;
    return append_sim_motion_diagnostics(text,capacity,length);
}

size_t virtual_body_heartbeat(uint64_t now,int pong,char *text,size_t capacity)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;
    if(!full_parity)return ainekio_encode_ping(pong!=0,text,capacity);
    const int n=snprintf(text,capacity,
        "{\"t\":\"%s\",\"clock_ms\":%" PRIu64
        ",\"audio\":{\"on\":%s,\"listening\":%s,\"gate\":\"%s\",\"gain_db\":%u,"
        "\"wake_enabled\":%s,\"wake_threshold\":%.5f,\"rms\":%.6f,\"peak\":%.6f,"
        "\"capturing\":%s,\"speaker_busy\":%s,\"speaker_volume_percent\":%u,"
        "\"external_speech\":%s,\"vad_mode\":%u,\"silence_ms\":%u,\"max_recording_ms\":%u}}",
        pong?"pong":"ping",now/1000U,
        sim_media.microphone_enabled?"true":"false",
        sim_media.microphone_listening?"true":"false",
        mic_gate_name(sim_media.microphone_gate),
        (unsigned)sim_media.microphone_gain_db,
        sim_media.wake_enabled?"true":"false",
        (double)sim_media.wake_threshold,
        (double)sim_media.microphone_rms,
        (double)sim_media.microphone_peak,
        sim_media.utterance_open?"true":"false",
        sim_media.speaker_busy?"true":"false",
        (unsigned)sim_media.speaker_volume_percent,
        sim_media.external_speech?"true":"false",
        (unsigned)sim_media.vad_mode,
        (unsigned)sim_media.silence_ms,
        (unsigned)sim_media.max_recording_ms);
    if(n<=0||(size_t)n>=capacity)return 0;
    return (size_t)n;
}

size_t virtual_body_feedback_health(uint64_t now,char *text,size_t capacity)
{
    if(!sensor_state||now<device_us)return 0;
    device_us=now;simulation_p4_activate(sensor_state);
    if(ainekio_p4_body_status().gait_valid)return 0;
    cJSON *feedback=cJSON_CreateObject();
    if(!feedback)return 0;
    cJSON_AddStringToObject(feedback,"t","event");
    cJSON_AddStringToObject(feedback,"name","servo_feedback");
    cJSON_AddItemToObject(feedback,"data",ainekio_p4_feedback_health_json());
    const bool ok=cJSON_PrintPreallocated(feedback,text,capacity,false);
    cJSON_Delete(feedback);
    return ok?strlen(text):0;
}

size_t virtual_body_media_actions(char *text,size_t capacity)
{
    if(!sim_media_action_queue) {
        if(capacity<3)return 0;
        memcpy(text,"[]",3);
        return 2;
    }
    const bool ok=cJSON_PrintPreallocated(sim_media_action_queue,text,capacity,false);
    cJSON_Delete(sim_media_action_queue);
    sim_media_action_queue=NULL;
    return ok?strlen(text):0;
}

int virtual_body_face_frame(uint64_t now_ms,int talking,int capturing,
    uint8_t *rgba_out,char *name_out,size_t name_cap,
    char *token_out,size_t token_cap)
{
    if(!sensor_state)return 0;
    simulation_p4_activate(sensor_state);
    const ainekio_p4_body_status_t st=ainekio_p4_body_status();
    ainekio_p4_face_sample_t sample=ainekio_p4_face_sample(&sim_face_clock,&st,now_ms);
    sample=ainekio_p4_face_selected(&sim_face_selection,sample,st.face_revision,
        st.moving,talking!=0,now_ms);
    if(capturing && !sim_was_listening)sim_listening_since_ms=now_ms;
    sim_was_listening=capturing!=0;
    sample=ainekio_p4_face_listen(sample,capturing!=0,now_ms-sim_listening_since_ms);
    sim_shown_face=sample.face;
    if(name_out && name_cap>0) {
        const char *name=ainekio_face_name(sample.face);
        snprintf(name_out,name_cap,"%s",name?name:"default");
    }
    if(token_out && token_cap>0) {
        const char *tok=ainekio_p4_face_token(&sim_face_selection,now_ms);
        snprintf(token_out,token_cap,"%s",tok?tok:"");
    }
    if(rgba_out) {
        if(sim_face_style==1) {
            ainekio_face_cyclops_render(sample.face,talking?now_ms:sample.elapsed_ms,
                talking!=0,sim_face_rgb565);
        } else {
            ainekio_face_render(sample.face,talking?now_ms:sample.elapsed_ms,
                talking!=0,sim_face_rgb565);
        }
        for(size_t i=0;i<AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT;++i) {
            const uint16_t p=sim_face_rgb565[i];
            const unsigned r5=(p>>11)&31U;
            const unsigned g6=(p>>5)&63U;
            const unsigned b5=p&31U;
            rgba_out[i*4+0]=(uint8_t)((r5<<3)|(r5>>2));
            rgba_out[i*4+1]=(uint8_t)((g6<<2)|(g6>>4));
            rgba_out[i*4+2]=(uint8_t)((b5<<3)|(b5>>2));
            rgba_out[i*4+3]=255U;
        }
    }
    return 1;
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
    uint32_t allowed=
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_INTENT)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STOP)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MOTION_PLAN)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_WALK_TARGET)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_BODY_CALIBRATION)|
        AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MOTION_SPEED);
    if(full_parity) {
        allowed|=
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MODE)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_PROFILE)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STATE)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_CAMERA)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_SNAPSHOT)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_MICROPHONE)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_TTS)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_WAKE_CONFIG)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STORAGE)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_ROBOT_SETTINGS)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_SPEAKER)|
            AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_BALANCE);
    }
    ainekio_admission_init(&admission,allowed,true);
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
    if(full_parity) {
        const char *commands[FULL_BASE_COMMAND_COUNT+ainekio_v2_clip_count];
        const ainekio_capabilities_t caps=build_full_capabilities(commands);
        const char *features[]={
            AINEKIO_MOTION_TARGETS_FEATURE,AINEKIO_MOTION_CURVES_FEATURE,
            "command_deadline_v1","body_capabilities_v1","body_commands_v1",
            "body_calibration_v2","walk_controls_v2",
            AINEKIO_WALK_STEERING_FEATURE,AINEKIO_WALK_LATERAL_FEATURE,AINEKIO_WALK_NOMINAL_FEATURE,
            "run_gait_v1","crab_gait_v1","motion_speed_v1","joint_speed_limit_v1",
            "balance_control_v1","balance_tuning_v1","balance_feedback_v1",
            "walking_feedback_v1","servo_feedback_v1",
            "camera_profiles_v1","camera_adaptive_v1",AINEKIO_CAMERA_MOTION_EXPOSURE_FEATURE,
            "audio_input_v1","face_feedback_v1"
        };
        const ainekio_hello_t hello={
            .firmware="virtual-p4-sim",.robot_id=id,.auth_token=token,
            .features=features,.feature_count=sizeof features/sizeof *features,
            .model="v2-12servo",.clock_ms=now/1000,.capabilities=&caps
        };
        return ainekio_encode_hello(&hello,text,capacity);
    }
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

static size_t encode_pair(const char *first_json,cJSON *second_obj,char *text,size_t capacity)
{
    cJSON *packets=cJSON_CreateArray();
    cJSON *first=cJSON_Parse(first_json);
    if(!packets||!first||!second_obj){cJSON_Delete(packets);cJSON_Delete(first);cJSON_Delete(second_obj);return 0;}
    cJSON_AddItemToArray(packets,first);
    cJSON_AddItemToArray(packets,second_obj);
    const bool ok=cJSON_PrintPreallocated(packets,text,capacity,false);
    cJSON_Delete(packets);
    return ok?strlen(text):0;
}

static cJSON *build_balance_status_json(uint32_t sequence)
{
    const bool active=balance_enabled && ainekio_pca_status(&virtual_pca).armed &&
        ainekio_p4_body_status().balance_active;
    cJSON *obj=cJSON_CreateObject();
    if(!obj)return NULL;
    cJSON_AddStringToObject(obj,"t","balance_status");
    cJSON_AddNumberToObject(obj,"seq",sequence);
    cJSON_AddBoolToObject(obj,"enabled",balance_enabled);
    cJSON_AddBoolToObject(obj,"saved",balance_saved);
    cJSON_AddBoolToObject(obj,"active",active);
    cJSON_AddNumberToObject(obj,"strength",balance_tuning.strength);
    cJSON_AddNumberToObject(obj,"damping",balance_tuning.damping);
    cJSON_AddNumberToObject(obj,"roll_deg",balance_tuning.roll_deg);
    cJSON_AddNumberToObject(obj,"pitch_deg",balance_tuning.pitch_deg);
    cJSON_AddBoolToObject(obj,"tuning_saved",balance_tuning_saved);
    cJSON_AddBoolToObject(obj,"walking_enabled",heading_enabled);
    cJSON_AddBoolToObject(obj,"walking_saved",walking_saved);
    return obj;
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
        if(full_parity && message.has_external_speech) {
            sim_media.external_speech=message.external_speech;
            cJSON *act=cJSON_CreateObject();
            if(act) {
                cJSON_AddStringToObject(act,"kind","external_speech");
                cJSON_AddBoolToObject(act,"active",message.external_speech);
                cJSON_AddNumberToObject(act,"ms",message.external_speech_ms);
                queue_media_action(act);
            }
        }
        return 0;
    }
    if(ainekio_admission_check_stale(&admission,now))virtual_body_connection_lost(connection);
    if(!ainekio_admission_control(&admission,connection,now))
        return message.has_command?ainekio_p4_rejection(&message,AINEKIO_REJECT_STALE,text,capacity):0;
    if(full_parity && (message.kind==AINEKIO_MESSAGE_PING || message.kind==AINEKIO_MESSAGE_PONG) &&
       message.has_external_speech) {
        sim_media.external_speech=message.external_speech;
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","external_speech");
            cJSON_AddBoolToObject(act,"active",message.external_speech);
            cJSON_AddNumberToObject(act,"ms",message.external_speech_ms);
            queue_media_action(act);
        }
    }
    if(message.kind==AINEKIO_MESSAGE_PING)return virtual_body_heartbeat(now,1,text,capacity);
    if(message.kind==AINEKIO_MESSAGE_PONG)return 0;
    if(!message.has_command)return 0;
    const uint64_t generation=ainekio_pca_status(&virtual_pca).generation;
    const ainekio_body_state_t previous_state=admission.core.state;
    ainekio_core_set_boot_ready(&admission.core,true);
    const ainekio_command_t *cmd=&message.command;
    const bool stop=cmd->kind==AINEKIO_COMMAND_STOP;
    const bool calibration_get=cmd->kind==AINEKIO_COMMAND_BODY_CALIBRATION &&
        cmd->data.calibration.operation==AINEKIO_CALIBRATION_GET;
    const bool speed_get=cmd->kind==AINEKIO_COMMAND_MOTION_SPEED &&
        !cmd->data.motion_speed.save;
    bool model_supported=calibration_get||speed_get||ainekio_p4_body_supports(cmd);
    if(full_parity) {
        if(cmd->kind==AINEKIO_COMMAND_INTENT &&
           (cmd->data.intent.kind==AINEKIO_INTENT_FACE || cmd->data.intent.kind==AINEKIO_INTENT_SAY))
            model_supported=true;
        else if(cmd->kind==AINEKIO_COMMAND_BALANCE ||
                cmd->kind==AINEKIO_COMMAND_MOTION_SPEED ||
                cmd->kind==AINEKIO_COMMAND_BODY_CALIBRATION ||
                cmd->kind==AINEKIO_COMMAND_CAMERA ||
                cmd->kind==AINEKIO_COMMAND_SNAPSHOT ||
                cmd->kind==AINEKIO_COMMAND_MICROPHONE ||
                cmd->kind==AINEKIO_COMMAND_SPEAKER ||
                cmd->kind==AINEKIO_COMMAND_TTS ||
                cmd->kind==AINEKIO_COMMAND_WAKE_CONFIG ||
                cmd->kind==AINEKIO_COMMAND_STATE ||
                cmd->kind==AINEKIO_COMMAND_MODE ||
                cmd->kind==AINEKIO_COMMAND_PROFILE)
            model_supported=true;
    }
    const ainekio_decision_t decision=stop?
        ainekio_p4_stop_accept(&admission,&virtual_pca,connection,&message,now,now):
        ainekio_admission_accept(&admission,connection,&message,now,now,model_supported);
    if(!decision.accepted)return ainekio_p4_rejection(&message,decision.rejection,text,capacity);

    if(!full_parity) {
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
            return encode_pair(ack,status,text,capacity);
        }
        if(stop)stopped_sequence=message.sequence;
        const esp_err_t result=ainekio_p4_body_execute(generation,connection,cmd);
        if(result!=ESP_OK) {
            admission.core.state=previous_state;
            return ainekio_p4_execution_error(message.sequence,result,
                ainekio_pca_status(&virtual_pca).fault,false,AINEKIO_STATE_IDLE,text,capacity);
        }
        if(cmd->kind!=AINEKIO_COMMAND_WALK_TARGET)ainekio_p4_body_activity();
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }

    /* Full-parity P4 command dispatch matching controller.c::apply(). */
    char ack[96];
    switch(cmd->kind) {
    case AINEKIO_COMMAND_STOP: {
        stopped_sequence=message.sequence;
        sim_face_selection.foreground.active=false;
        sim_face_selection.background.active=false;
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","stop_media");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            cJSON_AddBoolToObject(act,"detach",cmd->data.stop.detach);
            queue_media_action(act);
        }
        const esp_err_t result=ainekio_p4_body_execute(generation,connection,cmd);
        if(result!=ESP_OK) {
            admission.core.state=previous_state;
            return ainekio_p4_execution_error(message.sequence,result,
                ainekio_pca_status(&virtual_pca).fault,false,sim_system_state,text,capacity);
        }
        ainekio_p4_body_activity();
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_INTENT:
        if(cmd->data.intent.kind==AINEKIO_INTENT_FACE) {
            const ainekio_p4_body_status_t st=ainekio_p4_body_status();
            if(!ainekio_p4_face_select(&sim_face_selection,&cmd->data.intent.data.face,
                                       st.face_revision,now/1000U)) {
                admission.core.state=previous_state;
                return ainekio_encode_nak(true,message.sequence,AINEKIO_NAK_ASSET_MISSING,
                    "Unknown face expression",text,capacity);
            }
            ainekio_p4_body_activity();
            ainekio_encode_ack(message.sequence,0,ack,sizeof ack);
            char done_buf[96];
            ainekio_encode_done(message.sequence,done_buf,sizeof done_buf);
            return encode_pair(ack,cJSON_Parse(done_buf),text,capacity);
        }
        if(cmd->data.intent.kind==AINEKIO_INTENT_SAY) {
            ainekio_p4_body_activity();
            cJSON *act=cJSON_CreateObject();
            if(act) {
                cJSON_AddStringToObject(act,"kind","say");
                cJSON_AddNumberToObject(act,"seq",message.sequence);
                cJSON_AddStringToObject(act,"asset",cmd->data.intent.data.asset);
                queue_media_action(act);
            }
            return ainekio_encode_ack(message.sequence,0,text,capacity);
        }
        /* All motion intents flow through the real body.c executor. */
        {
            const esp_err_t result=ainekio_p4_body_execute(generation,connection,cmd);
            if(result!=ESP_OK) {
                admission.core.state=previous_state;
                return ainekio_p4_execution_error(message.sequence,result,
                    ainekio_pca_status(&virtual_pca).fault,false,sim_system_state,text,capacity);
            }
            ainekio_p4_body_activity();
            return ainekio_encode_ack(message.sequence,0,text,capacity);
        }
    case AINEKIO_COMMAND_MOTION_PLAN:
    case AINEKIO_COMMAND_WALK_TARGET: {
        const esp_err_t result=ainekio_p4_body_execute(generation,connection,cmd);
        if(result!=ESP_OK) {
            admission.core.state=previous_state;
            return ainekio_p4_execution_error(message.sequence,result,
                ainekio_pca_status(&virtual_pca).fault,false,sim_system_state,text,capacity);
        }
        if(cmd->kind!=AINEKIO_COMMAND_WALK_TARGET)ainekio_p4_body_activity();
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_BALANCE: {
        if(cmd->data.balance.walking_feedback) {
            heading_enabled=cmd->data.balance.enabled;
            walking_saved=true;
        } else if(cmd->data.balance.save) {
            balance_enabled=cmd->data.balance.enabled;
            balance_saved=true;
            if(cmd->data.balance.has_tuning) {
                balance_tuning=(ainekio_v2_balance_tuning_t){
                    cmd->data.balance.strength,cmd->data.balance.damping,
                    cmd->data.balance.roll_deg,cmd->data.balance.pitch_deg
                };
                balance_tuning_saved=true;
            }
        }
        ainekio_encode_ack(message.sequence,0,ack,sizeof ack);
        return encode_pair(ack,build_balance_status_json(message.sequence),text,capacity);
    }
    case AINEKIO_COMMAND_MOTION_SPEED: {
        if(cmd->data.motion_speed.save) {
            ainekio_pca_disarm(&virtual_pca);
            if(cmd->data.motion_speed.has_joint_speed_limit) {
                if(!ainekio_v2_joint_speed_set(cmd->data.motion_speed.joint_speed_limit_deg_s)) {
                    admission.core.state=previous_state;
                    return ainekio_encode_nak(true,message.sequence,AINEKIO_NAK_LIMIT,
                        "Invalid joint speed limit",text,capacity);
                }
                joint_speed_saved=true;
            } else {
                motion_rate=cmd->data.motion_speed.rate;
                motion_rate_saved=true;
            }
        }
        char speed[320];
        ainekio_encode_ack(message.sequence,0,ack,sizeof ack);
        ainekio_p4_motion_speed_json(message.sequence,motion_rate,motion_rate_saved,
            ainekio_v2_gait_joint_speed_limit(),joint_speed_saved,speed,sizeof speed);
        return encode_pair(ack,cJSON_Parse(speed),text,capacity);
    }
    case AINEKIO_COMMAND_BODY_CALIBRATION: {
        const typeof(cmd->data.calibration) *c=&cmd->data.calibration;
        esp_err_t result=ESP_OK;
        if(c->operation==AINEKIO_CALIBRATION_SET) {
            if(c->id<0 || c->id>=(int)AINEKIO_BODY_JOINT_COUNT)result=ESP_ERR_INVALID_ARG;
            else {
                ainekio_pca_disarm(&virtual_pca);
                calibration.joints[c->id].channel=c->channel;
                calibration.joints[c->id].home_us=c->home_us;
                calibration.joints[c->id].invert=c->invert;
                if(c->has_mapping) {
                    calibration.joints[c->id].home_cd=c->home_cd;
                    calibration.joints[c->id].us_per_degree=c->us_per_degree;
                }
                calibration.dirty=true;
            }
        } else if(c->operation==AINEKIO_CALIBRATION_SAVE) {
            ainekio_pca_disarm(&virtual_pca);
            calibration.dirty=false;calibration.saved=true;
        } else if(c->operation==AINEKIO_CALIBRATION_HOME) {
            if(c->id<0) {
                uint16_t pulses[12];
                if(ainekio_p4_home_pulses(pulses))result=ainekio_p4_body_home(generation,pulses);
                else result=ESP_ERR_INVALID_STATE;
            } else if(c->id<(int)AINEKIO_BODY_JOINT_COUNT && calibration.joints[c->id].channel>=0) {
                result=ainekio_p4_body_move(generation,calibration.joints[c->id].channel,
                    calibration.joints[c->id].home_us);
            } else result=ESP_ERR_INVALID_ARG;
        } else if(c->operation==AINEKIO_CALIBRATION_MOVE) {
            if(c->id>=0 && c->id<(int)AINEKIO_BODY_JOINT_COUNT && calibration.joints[c->id].channel>=0)
                result=ainekio_p4_body_move(generation,calibration.joints[c->id].channel,c->pulse_us);
            else result=ESP_ERR_INVALID_ARG;
        }
        if(result!=ESP_OK) {
            admission.core.state=previous_state;
            return ainekio_p4_execution_error(message.sequence,result,
                ainekio_pca_status(&virtual_pca).fault,false,sim_system_state,text,capacity);
        }
        ainekio_encode_ack(message.sequence,0,ack,sizeof ack);
        return encode_pair(ack,ainekio_p4_calibration_json(message.sequence),text,capacity);
    }
    case AINEKIO_COMMAND_CAMERA: {
        if(cmd->data.camera.has_controls) {
            admission.core.state=previous_state;
            return ainekio_encode_nak(true,message.sequence,AINEKIO_NAK_UNKNOWN,
                "Manual camera controls unsupported on P4",text,capacity);
        }
        ainekio_p4_body_activity();
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","camera");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            cJSON_AddBoolToObject(act,"enabled",cmd->data.camera.enabled);
            cJSON_AddNumberToObject(act,"fps",cmd->data.camera.fps);
            cJSON_AddStringToObject(act,"res",camera_res_name(cmd->data.camera.resolution));
            if(cmd->data.camera.has_snapshot_resolution)
                cJSON_AddStringToObject(act,"snapshot_res",camera_res_name(cmd->data.camera.snapshot_resolution));
            if(cmd->data.camera.has_max_exposure_us)
                cJSON_AddNumberToObject(act,"max_exposure_us",cmd->data.camera.max_exposure_us);
            queue_media_action(act);
        }
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_SNAPSHOT: {
        ainekio_p4_body_activity();
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","snapshot");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            queue_media_action(act);
        }
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_MICROPHONE: {
        sim_media.microphone_enabled=cmd->data.microphone.enabled;
        sim_media.microphone_listening=cmd->data.microphone.enabled;
        sim_media.microphone_gate=cmd->data.microphone.gate;
        if(cmd->data.microphone.has_gain_db)sim_media.microphone_gain_db=cmd->data.microphone.gain_db;
        if(cmd->data.microphone.speech.has_vad_mode)sim_media.vad_mode=cmd->data.microphone.speech.vad_mode;
        if(cmd->data.microphone.speech.has_silence_ms)sim_media.silence_ms=cmd->data.microphone.speech.silence_ms;
        if(cmd->data.microphone.speech.has_max_recording_ms)
            sim_media.max_recording_ms=cmd->data.microphone.speech.max_recording_ms;
        ainekio_p4_body_activity();
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","microphone");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            cJSON_AddBoolToObject(act,"on",sim_media.microphone_enabled);
            cJSON_AddStringToObject(act,"gate",mic_gate_name(sim_media.microphone_gate));
            cJSON_AddNumberToObject(act,"gain_db",sim_media.microphone_gain_db);
            cJSON_AddNumberToObject(act,"vad_mode",sim_media.vad_mode);
            cJSON_AddNumberToObject(act,"silence_ms",sim_media.silence_ms);
            cJSON_AddNumberToObject(act,"max_recording_ms",sim_media.max_recording_ms);
            queue_media_action(act);
        }
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_SPEAKER: {
        sim_media.speaker_volume_percent=cmd->data.speaker_volume_percent;
        ainekio_p4_body_activity();
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","speaker");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            cJSON_AddNumberToObject(act,"volume_percent",sim_media.speaker_volume_percent);
            queue_media_action(act);
        }
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_TTS: {
        ainekio_p4_body_activity();
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","tts");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            cJSON_AddStringToObject(act,"op",
                cmd->data.tts_operation==AINEKIO_TTS_START?"start":
                cmd->data.tts_operation==AINEKIO_TTS_END?"end":"cancel");
            queue_media_action(act);
        }
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_WAKE_CONFIG: {
        ainekio_pca_disarm(&virtual_pca);
        sim_media.wake_enabled=cmd->data.wake.enabled;
        if(cmd->data.wake.model[0])memcpy(sim_media.wake_model,cmd->data.wake.model,sizeof sim_media.wake_model);
        if(cmd->data.wake.has_threshold)sim_media.wake_threshold=cmd->data.wake.threshold;
        ainekio_p4_body_activity();
        cJSON *act=cJSON_CreateObject();
        if(act) {
            cJSON_AddStringToObject(act,"kind","wake");
            cJSON_AddNumberToObject(act,"seq",message.sequence);
            cJSON_AddBoolToObject(act,"enabled",sim_media.wake_enabled);
            cJSON_AddStringToObject(act,"model",sim_media.wake_model);
            cJSON_AddNumberToObject(act,"threshold",sim_media.wake_threshold);
            queue_media_action(act);
        }
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_MODE: {
        if(cmd->data.mode==AINEKIO_MODE_CALIBRATE) {
            ainekio_pca_disarm(&virtual_pca);
            (void)ainekio_p4_body_prepare(ainekio_pca_status(&virtual_pca).generation);
        } else {
            (void)ainekio_p4_body_hold(generation);
        }
        ainekio_p4_body_activity();
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    }
    case AINEKIO_COMMAND_PROFILE:
        ainekio_p4_body_activity();
        return ainekio_encode_ack(message.sequence,0,text,capacity);
    case AINEKIO_COMMAND_STATE: {
        if(cmd->data.state.request==AINEKIO_STATE_REQUEST_IDLE)sim_system_state=AINEKIO_STATE_IDLE;
        else if(cmd->data.state.request==AINEKIO_STATE_REQUEST_DOZE)sim_system_state=AINEKIO_STATE_DOZING;
        else sim_system_state=AINEKIO_STATE_DEEP_SLEEP;
        ainekio_p4_body_activity();
        ainekio_encode_ack(message.sequence,cmd->data.state.sleep_seconds,ack,sizeof ack);
        if(cmd->data.state.request==AINEKIO_STATE_REQUEST_SLEEP) {
            char done_buf[96];
            ainekio_encode_done(message.sequence,done_buf,sizeof done_buf);
            return encode_pair(ack,cJSON_Parse(done_buf),text,capacity);
        }
        return strlen(ack)<=capacity?(memcpy(text,ack,strlen(ack)+1),strlen(ack)):0;
    }
    default:
        admission.core.state=previous_state;
        return ainekio_encode_nak(true,message.sequence,AINEKIO_NAK_UNKNOWN,
            "Unsupported command on virtual P4 body",text,capacity);
    }
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
                ainekio_pca_status(&virtual_pca).fault,false,sim_system_state,buffer,sizeof buffer);
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
