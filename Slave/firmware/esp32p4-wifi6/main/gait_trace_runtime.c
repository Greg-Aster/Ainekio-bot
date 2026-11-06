#include "ainekio/v2_walk.h"
#include "gait_trace_runtime.h"
#include "gait_trace.h"
#include "cJSON.h"
#include "body.h"
#include "controller.h"
#include "ainekio/p4_imu.h"
#include "esp_http_server.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include <math.h>
#include <string.h>
#include <stdlib.h>

/* Allocated only by an explicit recording request. After recording stops,
 * release storage once the final batch has been delivered. Producers and the
 * pointer detachment share trace_lock; heap release happens outside the lock. */
#define TRACE_CAPACITY 512
#define TRACE_BATCH 64
#define TRACE_HTTP_BUFFER 8192
static ainekio_gait_trace_ring_t ring;
static portMUX_TYPE trace_lock=portMUX_INITIALIZER_UNLOCKED;
static bool active;
static uint32_t boot_id,session;
static esp_err_t fail(httpd_req_t *r,const char *status,const char *message)
{
    httpd_resp_set_status(r,status);httpd_resp_set_type(r,"application/json");
    return httpd_resp_sendstr(r,message);
}
static void append(const ainekio_gait_trace_event_t *e)
{
    portENTER_CRITICAL(&trace_lock);
    if(active)ainekio_gait_trace_push(&ring,e);
    portEXIT_CRITICAL(&trace_lock);
}
void ainekio_p4_gait_trace_tracking(const ainekio_gait_trace_event_t *event){append(event);}
static bool recording(void)
{
    portENTER_CRITICAL(&trace_lock);bool enabled=active;portEXIT_CRITICAL(&trace_lock);
    return enabled;
}
void ainekio_p4_gait_trace_output(const uint16_t pulses[12],uint64_t timestamp_us,bool armed)
{
    if(!recording())return;
    ainekio_gait_trace_event_t e={.kind=AINEKIO_TRACE_OUTPUT,.time_us=timestamp_us};
    memcpy(e.output.pulses,pulses,sizeof e.output.pulses);e.output.armed=armed;append(&e);
}
void ainekio_p4_gait_trace_imu(const ainekio_imu_observation_t *sample,bool calibration_applied)
{
    if(!recording())return;
    ainekio_gait_trace_event_t e={.kind=AINEKIO_TRACE_IMU,.time_us=sample->timestamp_us};
    e.imu.sample=*sample;e.imu.calibration_applied=calibration_applied;
    append(&e);
}
void ainekio_p4_gait_trace_sample(const ainekio_p4_feedback_snapshot_t *s)
{
    if(!recording())return;
    const ainekio_p4_imu_status_t imu=ainekio_p4_imu_status();
    const ainekio_p4_body_status_t body=ainekio_p4_body_status();
    ainekio_gait_trace_event_t e={.kind=AINEKIO_TRACE_SAMPLE,.time_us=esp_timer_get_time()};
    memcpy(e.sample.sampled_us,s->sampled_us,sizeof e.sample.sampled_us);
    memcpy(e.sample.raw,s->raw,sizeof e.sample.raw);
    memcpy(e.sample.spread,s->spread,sizeof e.sample.spread);
    memcpy(e.sample.filtered,s->filtered_raw,sizeof e.sample.filtered);
    memcpy(e.sample.velocity,s->velocity_raw_s,sizeof e.sample.velocity);
    e.sample.valid_mask=s->valid_mask;e.sample.revision=s->revision;e.sample.scan=s->scan;
    e.sample.scan_us=s->scan_us;e.sample.error=s->error;
    e.sample.imu_us=imu.attitude.timestamp_us;
    memcpy(e.sample.q,imu.attitude.orientation_wxyz,sizeof e.sample.q);
    memcpy(e.sample.gyro,imu.attitude.angular_rate_rad_s,sizeof e.sample.gyro);
    memcpy(e.sample.accel,imu.attitude.acceleration_m_s2,sizeof e.sample.accel);
    e.sample.imu_available=imu.attitude.available;e.sample.imu_fresh=imu.attitude.fresh;
    e.sample.imu_calibrated=imu.calibration_applied;
    e.sample.imu_startup=imu.attitude.startup;
    e.sample.imu_recovering=imu.attitude.gyro_recovery||imu.attitude.acceleration_recovery;
    e.sample.command_sequence=body.sequence;e.sample.walking=body.gait_valid;
    e.sample.entering=body.face_entering;e.sample.phase=body.gait_phase;
    e.sample.host_nominal=body.gait_valid && body.gait_host_nominal;
    if(body.execution.sequence==body.sequence && body.execution.connection==body.connection) {
        e.sample.nominal_sample=body.execution.nominal_sample;
        e.sample.output_us=body.execution.sampled_us;
    }
    e.sample.stride_percent=body.stride_percent;e.sample.cycles_s=body.gait_cycles_s;
    append(&e);
}
/* RFC 8742 CBOR sequence. The existing trace chunk buffer is the only
 * serialization storage: no per-event object tree or decimal conversion.
 * Definite arrays and indefinite maps preserve the existing record structure. */
_Static_assert(sizeof(float)==4 && sizeof(double)==8,"Trace CBOR uses IEEE binary32/binary64");
typedef struct {
    httpd_req_t *request;
    char *data;
    size_t used;
    esp_err_t result;
} trace_writer_t;
static esp_err_t flush_trace(trace_writer_t *writer)
{
    if(writer->result!=ESP_OK || !writer->used)return writer->result;
    writer->result=httpd_resp_send_chunk(writer->request,writer->data,writer->used);
    if(writer->result==ESP_OK)writer->used=0;
    return writer->result;
}
static void write_trace(trace_writer_t *writer,const void *bytes,size_t size)
{
    const char *text=bytes;
    while(size && writer->result==ESP_OK) {
        const size_t available=TRACE_HTTP_BUFFER-writer->used;
        const size_t count=size<available?size:available;
        memcpy(writer->data+writer->used,text,count);
        writer->used+=count;text+=count;size-=count;
        if(writer->used==TRACE_HTTP_BUFFER)(void)flush_trace(writer);
    }
}
static void byte(trace_writer_t *writer,uint8_t value){write_trace(writer,&value,1);}
static void argument(trace_writer_t *writer,unsigned major,uint64_t value)
{
    uint8_t encoded[9];unsigned bytes=0;
    if(value<24){byte(writer,(uint8_t)(major<<5|value));return;}
    if(value<=UINT8_MAX){encoded[0]=(uint8_t)(major<<5|24);bytes=1;}
    else if(value<=UINT16_MAX){encoded[0]=(uint8_t)(major<<5|25);bytes=2;}
    else if(value<=UINT32_MAX){encoded[0]=(uint8_t)(major<<5|26);bytes=4;}
    else {encoded[0]=(uint8_t)(major<<5|27);bytes=8;}
    for(unsigned i=0;i<bytes;i++)encoded[i+1]=(uint8_t)(value>>(8*(bytes-i-1)));
    write_trace(writer,encoded,bytes+1);
}
static void text(trace_writer_t *writer,const char *value)
{const size_t n=strlen(value);argument(writer,3,n);write_trace(writer,value,n);}
static void map(trace_writer_t *writer,const char *name)
{if(name)text(writer,name);byte(writer,0xbf);}
static void end_map(trace_writer_t *writer){byte(writer,0xff);}
static void integer(trace_writer_t *writer,const char *name,uint64_t value)
{if(name)text(writer,name);argument(writer,0,value);}
static void signed_integer(trace_writer_t *writer,const char *name,int value)
{text(writer,name);if(value<0)argument(writer,1,(uint64_t)(-(int64_t)value-1));else argument(writer,0,(unsigned)value);}
static void boolean(trace_writer_t *writer,const char *name,bool value)
{text(writer,name);byte(writer,value?0xf5:0xf4);}
static void string(trace_writer_t *writer,const char *name,const char *value)
{text(writer,name);text(writer,value);}
static void float_value(trace_writer_t *writer,float value)
{
    if(!isfinite(value)){byte(writer,0xf6);return;}
    uint32_t bits;memcpy(&bits,&value,sizeof bits);
    const uint8_t encoded[5]={0xfa,(uint8_t)(bits>>24),(uint8_t)(bits>>16),(uint8_t)(bits>>8),(uint8_t)bits};
    write_trace(writer,encoded,sizeof encoded);
}
static void scalar(trace_writer_t *writer,const char *name,float value)
{text(writer,name);float_value(writer,value);}
static void real(trace_writer_t *writer,const char *name,double value)
{
    text(writer,name);
    if(!isfinite(value)){byte(writer,0xf6);return;}
    uint64_t bits;memcpy(&bits,&value,sizeof bits);uint8_t encoded[9]={0xfb};
    for(unsigned i=0;i<8;i++)encoded[i+1]=(uint8_t)(bits>>(8*(7-i)));
    write_trace(writer,encoded,sizeof encoded);
}
static void floats(trace_writer_t *writer,const char *name,const float *values,unsigned count)
{
    text(writer,name);argument(writer,4,count);
    for(unsigned i=0;i<count;i++)float_value(writer,values[i]);
}
static void u16_array(trace_writer_t *writer,const char *name,const uint16_t *values,unsigned count)
{
    text(writer,name);argument(writer,4,count);
    for(unsigned i=0;i<count;i++)argument(writer,0,values[i]);
}
static void u64_array(trace_writer_t *writer,const char *name,const uint64_t *values,unsigned count)
{
    text(writer,name);argument(writer,4,count);
    for(unsigned i=0;i<count;i++)argument(writer,0,values[i]);
}
static void event_cbor(trace_writer_t *w,uint64_t sequence,const ainekio_gait_trace_event_t *e)
{
    map(w,NULL);integer(w,"sequence",sequence);integer(w,"time_us",e->time_us);
    string(w,"kind",e->kind==AINEKIO_TRACE_OUTPUT?"output":e->kind==AINEKIO_TRACE_TRACKING?"tracking":
        e->kind==AINEKIO_TRACE_IMU?"imu":"sample");
    if(e->kind==AINEKIO_TRACE_IMU) {
        const ainekio_imu_observation_t *s=&e->imu.sample;
        map(w,"imu");
        integer(w,"timestamp_us",s->timestamp_us);
        integer(w,"accepted_samples",s->accepted_samples);
        integer(w,"rejected_samples",s->rejected_samples);
        integer(w,"gap_restarts",s->gap_restarts);
        boolean(w,"available",s->available);boolean(w,"fresh",s->fresh);
        boolean(w,"calibration_applied",e->imu.calibration_applied);
        string(w,"frame",e->imu.calibration_applied?"body_nominal":"sensor_unverified");
        boolean(w,"startup",s->startup);boolean(w,"gyro_recovery",s->gyro_recovery);
        boolean(w,"acceleration_recovery",s->acceleration_recovery);
        boolean(w,"accelerometer_ignored",s->accelerometer_ignored);
        floats(w,"orientation_wxyz",s->orientation_wxyz,4);
        floats(w,"angular_rate_rad_s",s->angular_rate_rad_s,3);
        floats(w,"acceleration_m_s2",s->acceleration_m_s2,3);
        end_map(w);
    } else if(e->kind==AINEKIO_TRACE_TRACKING) {
        integer(w,"signature",e->tracking.signature);integer(w,"command_sequence",e->tracking.command_sequence);
        scalar(w,"stride",e->tracking.stride);integer(w,"valid_mask",e->tracking.valid_mask);
        boolean(w,"eligible",e->tracking.eligible);
        map(w,"policy");string(w,"schema","gait_policy_input_v1");
        integer(w,"signature",e->tracking.policy_signature);integer(w,"gait_signature",e->tracking.gait_signature);
        integer(w,"profile_signature",e->tracking.profile_signature);boolean(w,"eligible",e->tracking.policy_eligible);
        string(w,"gait",e->tracking.gait_mode==AINEKIO_GAIT_RUN?"run":e->tracking.gait_mode==AINEKIO_GAIT_CRAWL?"crawl":
            e->tracking.gait_mode==AINEKIO_GAIT_CRAB?"crab":"walk");
        string(w,"model_id",e->tracking.model_id);scalar(w,"model_amount",e->tracking.model_amount);
        boolean(w,"model_active",e->tracking.model_active);scalar(w,"cycles_s",e->tracking.cycles_s);
        scalar(w,"requested_rate",e->tracking.requested_rate);floats(w,"reference_twist_m_s_rad_s",e->tracking.reference_twist,3);
        string(w,"command_schema","gait_policy_command_v1");floats(w,"command",e->tracking.policy_command,4);
        real(w,"phase",e->tracking.policy_phase);integer(w,"imu_timestamp_us",e->tracking.policy_imu_us);
        boolean(w,"usable",e->tracking.policy_usable);floats(w,"features",&e->tracking.policy_input[0][0],32);
        floats(w,"correction_mm",&e->tracking.policy_correction[0][0],12);end_map(w);
        u16_array(w,"nominal_pulses_us",e->tracking.nominal_pulses,12);
        text(w,"legs");argument(w,4,4);
        for(unsigned l=0;l<4;l++) {
            map(w,NULL);integer(w,"sampled_us",e->tracking.sampled_us[l]);real(w,"phase",e->tracking.phase[l]);
            boolean(w,"support_known",e->tracking.support_known[l]);boolean(w,"planned_grounded",e->tracking.grounded[l]);
            floats(w,"target_mm",e->tracking.target[l],3);floats(w,"measured_mm",e->tracking.measured[l],3);
            floats(w,"correction_mm",e->tracking.correction[l],3);end_map(w);
        }
    } else if(e->kind==AINEKIO_TRACE_OUTPUT) {
        u16_array(w,"pulses_us",e->output.pulses,12);boolean(w,"armed",e->output.armed);
    } else {
        integer(w,"revision",e->sample.revision);integer(w,"scan",e->sample.scan);integer(w,"scan_us",e->sample.scan_us);
        integer(w,"valid_mask",e->sample.valid_mask);signed_integer(w,"error",e->sample.error);
        u64_array(w,"sampled_us",e->sample.sampled_us,16);u16_array(w,"raw",e->sample.raw,16);
        u16_array(w,"spread",e->sample.spread,16);floats(w,"filtered_raw",e->sample.filtered,16);
        floats(w,"velocity_raw_s",e->sample.velocity,16);
        map(w,"imu");integer(w,"timestamp_us",e->sample.imu_us);
        boolean(w,"available",e->sample.imu_available);boolean(w,"fresh",e->sample.imu_fresh);
        boolean(w,"calibration_applied",e->sample.imu_calibrated);boolean(w,"startup",e->sample.imu_startup);
        boolean(w,"recovering",e->sample.imu_recovering);floats(w,"orientation_wxyz",e->sample.q,4);
        floats(w,"angular_rate_rad_s",e->sample.gyro,3);floats(w,"acceleration_m_s2",e->sample.accel,3);end_map(w);
        map(w,"motion");integer(w,"command_sequence",e->sample.command_sequence);
        boolean(w,"walking",e->sample.walking);boolean(w,"entering",e->sample.entering);
        string(w,"walk_source",e->sample.host_nominal?"host":"native");
        if(e->sample.host_nominal) {
            integer(w,"nominal_sample",e->sample.nominal_sample);integer(w,"sampled_us",e->sample.output_us);
        } else {
            real(w,"phase",e->sample.phase);scalar(w,"stride_percent",e->sample.stride_percent);scalar(w,"cycles_s",e->sample.cycles_s);
        }
        end_map(w);
    }
    end_map(w);
}
esp_err_t ainekio_p4_gait_trace_http(httpd_req_t *r,const cJSON *operation)
{
    const cJSON *op=cJSON_GetObjectItemCaseSensitive(operation,"op");
    const cJSON *cursor=cJSON_GetObjectItemCaseSensitive(operation,"after");
    const cJSON *expected=cJSON_GetObjectItemCaseSensitive(operation,"session");
    const cJSON *expected_boot=cJSON_GetObjectItemCaseSensitive(operation,"boot_id");
    if(!cJSON_IsString(op))return fail(r,"400 Bad Request","{\"error\":\"Missing trace operation\"}");
    bool start=!strcmp(op->valuestring,"trace_start"),stop=!strcmp(op->valuestring,"trace_stop");
    if(!start&&!stop&&strcmp(op->valuestring,"trace_read"))return fail(r,"400 Bad Request","{\"error\":\"Unknown trace operation\"}");
    if(cursor&&(!cJSON_IsNumber(cursor)||!isfinite(cursor->valuedouble)||cursor->valuedouble<0||
                cursor->valuedouble>9007199254740991.||floor(cursor->valuedouble)!=cursor->valuedouble))return fail(r,"400 Bad Request","{\"error\":\"Invalid trace cursor\"}");
    if(expected&&(!cJSON_IsNumber(expected)||expected->valuedouble<1||expected->valuedouble>UINT32_MAX||
                  floor(expected->valuedouble)!=expected->valuedouble))return fail(r,"400 Bad Request","{\"error\":\"Invalid trace session\"}");
    if(expected_boot&&(!cJSON_IsNumber(expected_boot)||expected_boot->valuedouble<0||expected_boot->valuedouble>UINT32_MAX||
                  floor(expected_boot->valuedouble)!=expected_boot->valuedouble))return fail(r,"400 Bad Request","{\"error\":\"Invalid trace boot\"}");
    if(start&&!ring.events) {
        ring.events=heap_caps_calloc(TRACE_CAPACITY,sizeof(*ring.events),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        if(!ring.events)return fail(r,"500 Internal Server Error","{\"error\":\"Trace allocation failed\"}");
        ring.capacity=TRACE_CAPACITY;if(!boot_id)boot_id=esp_random();
    }
    portENTER_CRITICAL(&trace_lock);
    if(start){ring.latest=0;++session;active=true;}
    bool mismatch=(expected&&(uint32_t)expected->valuedouble!=session)||
        (expected_boot&&(uint32_t)expected_boot->valuedouble!=boot_id);
    if(stop&&!mismatch)active=false;
    uint64_t latest=ring.latest,oldest=ainekio_gait_trace_oldest(&ring);
    uint32_t current_session=session;bool enabled=active;
    portEXIT_CRITICAL(&trace_lock);
    if(mismatch)return fail(r,"409 Conflict","{\"error\":\"Trace session changed\"}");
    if(start) {
        uint16_t pulses[12];uint64_t stamp;bool armed;
        ainekio_p4_body_pulse_snapshot(pulses,&stamp,&armed);
        ainekio_p4_gait_trace_output(pulses,stamp,armed);
        portENTER_CRITICAL(&trace_lock);latest=ring.latest;oldest=ainekio_gait_trace_oldest(&ring);portEXIT_CRITICAL(&trace_lock);
    }
    uint64_t after=cursor?(uint64_t)cursor->valuedouble:0;
    if(after>latest)return fail(r,"409 Conflict","{\"error\":\"Trace cursor is ahead of recording\"}");
    /* Stream typed records into the existing response buffer. */
    trace_writer_t writer={.request=r,
        .data=heap_caps_calloc(TRACE_HTTP_BUFFER,1,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)};
    if(!writer.data)return fail(r,"500 Internal Server Error","{\"error\":\"Trace response allocation failed\"}");
    httpd_resp_set_type(r,"application/cbor-seq");httpd_resp_set_hdr(r,"Cache-Control","no-store");
    map(&writer,NULL);string(&writer,"geometry",ainekio_v2_walk_geometry_id);string(&writer,"schema","gait_trace_v1");
    integer(&writer,"boot_id",boot_id);integer(&writer,"sensor_boot_id",ainekio_p4_controller_sensor_boot_id());
    integer(&writer,"session",current_session);boolean(&writer,"active",enabled);
    integer(&writer,"oldest",oldest);integer(&writer,"latest",latest);integer(&writer,"capacity",ring.capacity);
    integer(&writer,"storage_bytes",ring.capacity*sizeof(*ring.events));end_map(&writer);
    uint64_t next=after,lost=0;
    for(unsigned n=0;writer.result==ESP_OK&&next<latest&&n<TRACE_BATCH;n++) {
        ainekio_gait_trace_event_t event;
        portENTER_CRITICAL(&trace_lock);
        oldest=ainekio_gait_trace_oldest(&ring);
        if(next+1<oldest){lost+=oldest-next-1;next=oldest-1;}
        bool found=next<latest&&ainekio_gait_trace_read(&ring,next+1,&event);
        portEXIT_CRITICAL(&trace_lock);
        if(!found)break;
        event_cbor(&writer,++next,&event);
    }
    if(writer.result==ESP_OK) {
        map(&writer,NULL);integer(&writer,"next",next);integer(&writer,"lost",lost);
        boolean(&writer,"more",next<latest);end_map(&writer);
    }
    esp_err_t result=flush_trace(&writer);
    free(writer.data);
    if(result==ESP_OK)result=httpd_resp_send_chunk(r,NULL,0);
    if(result==ESP_OK) {
        ainekio_gait_trace_event_t *finished=NULL;
        portENTER_CRITICAL(&trace_lock);
        if(!active && session==current_session && next==ring.latest) {
            finished=ring.events;ring.events=NULL;ring.capacity=0;
        }
        portEXIT_CRITICAL(&trace_lock);
        free(finished);
    }
    return result;
}
