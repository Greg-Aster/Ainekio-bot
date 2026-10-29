#include "ainekio/v2_walk.h"
#include "gait_trace_runtime.h"
#include "gait_trace.h"
#include "cJSON.h"
#include "body.h"
#include "ainekio/p4_imu.h"
#include "esp_http_server.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
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
static void floats(cJSON *o,const char *name,const float *v,unsigned n)
{
    cJSON *a=cJSON_AddArrayToObject(o,name);
    /* The recorded values are binary32. Nine significant decimal digits
     * round-trip them without cJSON's double-precision print/parse/reprint
     * work or its longer decimal expansion. The wire format remains JSON
     * numbers; nonfinite readings retain cJSON's existing null encoding. */
    for(unsigned i=0;i<n;i++) {
        char number[32];
        if(isfinite(v[i]))snprintf(number,sizeof number,"%.9g",(double)v[i]);
        else strcpy(number,"null");
        cJSON_AddItemToArray(a,cJSON_CreateRaw(number));
    }
}
typedef struct {
    httpd_req_t *request;
    char *data;
    size_t used;
} trace_writer_t;
static esp_err_t flush_trace(trace_writer_t *writer)
{
    if(!writer->used)return ESP_OK;
    esp_err_t result=httpd_resp_send_chunk(writer->request,writer->data,writer->used);
    if(result==ESP_OK)writer->used=0;
    return result;
}
static esp_err_t write_trace(trace_writer_t *writer,const char *text,size_t size)
{
    while(size) {
        size_t available=TRACE_HTTP_BUFFER-writer->used;
        size_t count=size<available?size:available;
        memcpy(writer->data+writer->used,text,count);
        writer->used+=count;text+=count;size-=count;
        if(writer->used==TRACE_HTTP_BUFFER) {
            esp_err_t result=flush_trace(writer);
            if(result!=ESP_OK)return result;
        }
    }
    return ESP_OK;
}
static esp_err_t send_json(trace_writer_t *writer,cJSON *o)
{
    if(!o)return ESP_ERR_NO_MEM;
    char *text=cJSON_PrintUnformatted(o);cJSON_Delete(o);
    if(!text)return ESP_ERR_NO_MEM;
    esp_err_t e=write_trace(writer,text,strlen(text));free(text);
    if(e==ESP_OK)e=write_trace(writer,"\n",1);
    return e;
}
static cJSON *event_json(uint64_t sequence,const ainekio_gait_trace_event_t *e)
{
    cJSON *o=cJSON_CreateObject();if(!o)return NULL;
    cJSON_AddNumberToObject(o,"sequence",sequence);cJSON_AddNumberToObject(o,"time_us",e->time_us);
    cJSON_AddStringToObject(o,"kind",e->kind==AINEKIO_TRACE_OUTPUT?"output":e->kind==AINEKIO_TRACE_TRACKING?"tracking":"sample");
    if(e->kind==AINEKIO_TRACE_TRACKING) {
        cJSON_AddNumberToObject(o,"signature",e->tracking.signature);
        cJSON_AddNumberToObject(o,"command_sequence",e->tracking.command_sequence);
        cJSON_AddNumberToObject(o,"stride",e->tracking.stride);
        cJSON_AddNumberToObject(o,"valid_mask",e->tracking.valid_mask);
        cJSON_AddBoolToObject(o,"eligible",e->tracking.eligible);
        cJSON *policy=cJSON_AddObjectToObject(o,"policy");
        cJSON_AddStringToObject(policy,"schema","gait_policy_input_v1");
        cJSON_AddNumberToObject(policy,"signature",e->tracking.policy_signature);
        cJSON_AddNumberToObject(policy,"gait_signature",e->tracking.gait_signature);
        cJSON_AddNumberToObject(policy,"profile_signature",e->tracking.profile_signature);
        cJSON_AddBoolToObject(policy,"eligible",e->tracking.policy_eligible);
        cJSON_AddStringToObject(policy,"gait",e->tracking.gait_mode==AINEKIO_GAIT_RUN?"run":
            e->tracking.gait_mode==AINEKIO_GAIT_CRAWL?"crawl":e->tracking.gait_mode==AINEKIO_GAIT_CRAB?"crab":"walk");
        cJSON_AddStringToObject(policy,"model_id",e->tracking.model_id);
        cJSON_AddNumberToObject(policy,"model_amount",e->tracking.model_amount);
        cJSON_AddBoolToObject(policy,"model_active",e->tracking.model_active);
        cJSON_AddNumberToObject(policy,"cycles_s",e->tracking.cycles_s);
        cJSON_AddNumberToObject(policy,"requested_rate",e->tracking.requested_rate);
        floats(policy,"reference_twist_m_s_rad_s",e->tracking.reference_twist,3);
        cJSON_AddStringToObject(policy,"command_schema","gait_policy_command_v1");
        floats(policy,"command",e->tracking.policy_command,4);
        cJSON_AddNumberToObject(policy,"phase",e->tracking.policy_phase);
        cJSON_AddNumberToObject(policy,"imu_timestamp_us",e->tracking.policy_imu_us);
        cJSON_AddBoolToObject(policy,"usable",e->tracking.policy_usable);
        floats(policy,"features",&e->tracking.policy_input[0][0],32);
        floats(policy,"correction_mm",&e->tracking.policy_correction[0][0],12);
        cJSON *pulses=cJSON_AddArrayToObject(o,"nominal_pulses_us");
        for(unsigned j=0;j<12;j++)cJSON_AddItemToArray(pulses,cJSON_CreateNumber(e->tracking.nominal_pulses[j]));
        cJSON *legs=cJSON_AddArrayToObject(o,"legs");
        for(unsigned l=0;l<4;l++) {
            cJSON *leg=cJSON_CreateObject();cJSON_AddItemToArray(legs,leg);
            cJSON_AddNumberToObject(leg,"sampled_us",e->tracking.sampled_us[l]);
            cJSON_AddNumberToObject(leg,"phase",e->tracking.phase[l]);
            cJSON_AddBoolToObject(leg,"support_known",e->tracking.support_known[l]);
            cJSON_AddBoolToObject(leg,"planned_grounded",e->tracking.grounded[l]);
            floats(leg,"target_mm",e->tracking.target[l],3);
            floats(leg,"measured_mm",e->tracking.measured[l],3);
            floats(leg,"correction_mm",e->tracking.correction[l],3);
        }
        return o;
    }
    if(e->kind==AINEKIO_TRACE_OUTPUT) {
        cJSON *a=cJSON_AddArrayToObject(o,"pulses_us");
        for(unsigned j=0;j<12;j++)cJSON_AddItemToArray(a,cJSON_CreateNumber(e->output.pulses[j]));
        cJSON_AddBoolToObject(o,"armed",e->output.armed);return o;
    }
    cJSON_AddNumberToObject(o,"revision",e->sample.revision);
    cJSON_AddNumberToObject(o,"scan",e->sample.scan);cJSON_AddNumberToObject(o,"scan_us",e->sample.scan_us);
    cJSON_AddNumberToObject(o,"valid_mask",e->sample.valid_mask);cJSON_AddNumberToObject(o,"error",e->sample.error);
    cJSON *times=cJSON_AddArrayToObject(o,"sampled_us"),*raw=cJSON_AddArrayToObject(o,"raw"),
          *spread=cJSON_AddArrayToObject(o,"spread");
    for(unsigned i=0;i<16;i++) {
        cJSON_AddItemToArray(times,cJSON_CreateNumber(e->sample.sampled_us[i]));
        cJSON_AddItemToArray(raw,cJSON_CreateNumber(e->sample.raw[i]));
        cJSON_AddItemToArray(spread,cJSON_CreateNumber(e->sample.spread[i]));
    }
    floats(o,"filtered_raw",e->sample.filtered,16);floats(o,"velocity_raw_s",e->sample.velocity,16);
    cJSON *imu=cJSON_AddObjectToObject(o,"imu");
    cJSON_AddNumberToObject(imu,"timestamp_us",e->sample.imu_us);
    cJSON_AddBoolToObject(imu,"available",e->sample.imu_available);cJSON_AddBoolToObject(imu,"fresh",e->sample.imu_fresh);
    cJSON_AddBoolToObject(imu,"calibration_applied",e->sample.imu_calibrated);
    cJSON_AddBoolToObject(imu,"startup",e->sample.imu_startup);cJSON_AddBoolToObject(imu,"recovering",e->sample.imu_recovering);
    floats(imu,"orientation_wxyz",e->sample.q,4);floats(imu,"angular_rate_rad_s",e->sample.gyro,3);
    floats(imu,"acceleration_m_s2",e->sample.accel,3);
    cJSON *motion=cJSON_AddObjectToObject(o,"motion");
    cJSON_AddNumberToObject(motion,"command_sequence",e->sample.command_sequence);
    cJSON_AddBoolToObject(motion,"walking",e->sample.walking);cJSON_AddBoolToObject(motion,"entering",e->sample.entering);
    cJSON_AddStringToObject(motion,"walk_source",e->sample.host_nominal?"host":"native");
    if(e->sample.host_nominal) {
        cJSON_AddNumberToObject(motion,"nominal_sample",e->sample.nominal_sample);
        cJSON_AddNumberToObject(motion,"sampled_us",e->sample.output_us);
    } else {
        cJSON_AddNumberToObject(motion,"phase",e->sample.phase);
        cJSON_AddNumberToObject(motion,"stride_percent",e->sample.stride_percent);
        cJSON_AddNumberToObject(motion,"cycles_s",e->sample.cycles_s);
    }
    return o;
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
    /* Pack NDJSON records and delimiters into network chunks. A one-byte
     * newline must not require its own HTTP/TCP write for every event. */
    trace_writer_t writer={.request=r,
        .data=heap_caps_calloc(TRACE_HTTP_BUFFER,1,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)};
    if(!writer.data)return fail(r,"500 Internal Server Error","{\"error\":\"Trace response allocation failed\"}");
    httpd_resp_set_type(r,"application/x-ndjson");httpd_resp_set_hdr(r,"Cache-Control","no-store");
    cJSON *header=cJSON_CreateObject();
    cJSON_AddStringToObject(header,"geometry",ainekio_v2_walk_geometry_id);
    cJSON_AddStringToObject(header,"schema","gait_trace_v1");cJSON_AddNumberToObject(header,"boot_id",boot_id);
    cJSON_AddNumberToObject(header,"session",current_session);cJSON_AddBoolToObject(header,"active",enabled);
    cJSON_AddNumberToObject(header,"oldest",oldest);cJSON_AddNumberToObject(header,"latest",latest);
    cJSON_AddNumberToObject(header,"capacity",ring.capacity);
    cJSON_AddNumberToObject(header,"storage_bytes",ring.capacity*sizeof(*ring.events));
    esp_err_t result=send_json(&writer,header);
    uint64_t next=after,lost=0;
    for(unsigned n=0;result==ESP_OK&&next<latest&&n<TRACE_BATCH;n++) {
        ainekio_gait_trace_event_t event;
        portENTER_CRITICAL(&trace_lock);
        oldest=ainekio_gait_trace_oldest(&ring);
        if(next+1<oldest){lost+=oldest-next-1;next=oldest-1;}
        bool found=next<latest&&ainekio_gait_trace_read(&ring,next+1,&event);
        portEXIT_CRITICAL(&trace_lock);
        if(!found)break;
        result=send_json(&writer,event_json(++next,&event));
    }
    if(result==ESP_OK) {
        cJSON *footer=cJSON_CreateObject();cJSON_AddNumberToObject(footer,"next",next);
        cJSON_AddNumberToObject(footer,"lost",lost);cJSON_AddBoolToObject(footer,"more",next<latest);
        result=send_json(&writer,footer);
    }
    if(result==ESP_OK)result=flush_trace(&writer);
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
