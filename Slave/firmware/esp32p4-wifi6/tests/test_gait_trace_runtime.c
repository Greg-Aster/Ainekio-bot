#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <float.h>
#include "../main/gait_trace_runtime.c"
static char response[300000],status[80];static size_t response_bytes;
static bool allocation_fail;
static bool fail_final_chunk;
static bool fail_data_chunk;
static unsigned data_chunks;
static uint64_t clock_us=100;
void *heap_caps_calloc(size_t n,size_t size,unsigned caps)
{ assert(caps==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));return allocation_fail?NULL:calloc(n,size); }
uint32_t esp_random(void){return 12345;}
int64_t esp_timer_get_time(void){return clock_us;}
ainekio_p4_imu_status_t ainekio_p4_imu_status(void)
{
    ainekio_p4_imu_status_t s={0};s.attitude.available=s.attitude.fresh=true;s.calibration_applied=true;
    s.attitude.timestamp_us=clock_us-2;s.attitude.orientation_wxyz[0]=1;return s;
}
ainekio_p4_body_status_t ainekio_p4_body_status(void)
{ return (ainekio_p4_body_status_t){.gait_valid=true,.gait_phase=.25,.sequence=77,.stride_percent=100}; }
void ainekio_p4_body_pulse_snapshot(uint16_t pulses[12],uint64_t *stamp,bool *armed)
{ for(unsigned j=0;j<12;j++)pulses[j]=1500;*stamp=50;*armed=true; }
esp_err_t httpd_resp_set_status(httpd_req_t *r,const char *s){(void)r;strcpy(status,s);return ESP_OK;}
esp_err_t httpd_resp_set_type(httpd_req_t *r,const char *s){(void)r;(void)s;return ESP_OK;}
esp_err_t httpd_resp_set_hdr(httpd_req_t *r,const char *a,const char *b){(void)r;(void)a;(void)b;return ESP_OK;}
esp_err_t httpd_resp_send_chunk(httpd_req_t *r,const char *s,ssize_t n)
{
    (void)r;if(!n && fail_final_chunk)return ESP_FAIL;
    if(n){data_chunks++;if(fail_data_chunk)return ESP_FAIL;}
    if(n){assert(response_bytes+n<sizeof response);memcpy(response+response_bytes,s,n);response_bytes+=n;}
    response[response_bytes]=0;return ESP_OK;
}
esp_err_t httpd_resp_sendstr(httpd_req_t *r,const char *s){return httpd_resp_send_chunk(r,s,strlen(s));}
static void request(const char *json)
{
    response_bytes=0;data_chunks=0;status[0]=0;response[0]=0;
    cJSON *op=cJSON_Parse(json);assert(op);httpd_req_t r={0};
    assert(ainekio_p4_gait_trace_http(&r,op)==(fail_final_chunk||fail_data_chunk?ESP_FAIL:ESP_OK));cJSON_Delete(op);
}
int main(void)
{
    /* Exercise the actual JSON wire representation, including tiny, large,
     * signed and nonfinite sensor values. Finite inputs must round-trip to
     * the same binary32 value; timestamps remain on the integer path. */
    float probes[1024]={FLT_MAX,-FLT_MAX,FLT_MIN,-FLT_MIN,0.f,-0.f,
        .123f,-.123f,INFINITY,-INFINITY,NAN};
    uint32_t bits=19;
    for(unsigned i=11;i<1024;i++) {
        bits=bits*1664525U+1013904223U;
        memcpy(&probes[i],&bits,sizeof bits);
    }
    cJSON *wire=cJSON_CreateObject();floats(wire,"values",probes,1024);
    char *serialized=cJSON_PrintUnformatted(wire);assert(serialized);
    cJSON *decoded=cJSON_Parse(serialized);assert(decoded);
    cJSON *values=cJSON_GetObjectItemCaseSensitive(decoded,"values");
    assert(cJSON_GetArraySize(values)==1024);
    for(unsigned i=0;i<1024;i++) {
        cJSON *value=cJSON_GetArrayItem(values,i);
        if(isfinite(probes[i])) {
            assert(cJSON_IsNumber(value));
            float restored=(float)value->valuedouble;
            assert(memcmp(&restored,&probes[i],sizeof restored)==0);
        } else assert(cJSON_IsNull(value));
    }
    cJSON_Delete(wire);cJSON_Delete(decoded);free(serialized);
    uint16_t pulses[12]={1800};
    ainekio_p4_gait_trace_output(pulses,1,true);assert(!ring.events);
    allocation_fail=true;request("{\"op\":\"trace_start\"}");assert(strstr(status,"500")&&!active);
    allocation_fail=false;request("{\"op\":\"trace_start\"}");assert(active&&session==1);
    assert(strstr(response,"gait_trace_v1")&&strstr(response,"\"time_us\":50"));
    ainekio_p4_feedback_snapshot_t s={.valid_mask=0xfff0,.revision=7,.scan=9};
    s.sampled_us[15]=95;s.raw[15]=321;s.filtered_raw[15]=322;s.velocity_raw_s[15]=4;
    ainekio_p4_gait_trace_sample(&s);ainekio_p4_gait_trace_output(pulses,110,true);
    request("{\"op\":\"trace_read\",\"after\":1,\"session\":1,\"boot_id\":12345}");
    assert(strstr(response,"\"scan\":9")&&strstr(response,"\"phase\":0.25")&&strstr(response,"\"timestamp_us\":98"));
    assert(strstr(response,"\"next\":3")&&strstr(response,"\"lost\":0"));
    assert(strstr(response,"\"calibration_applied\":true"));
    ainekio_gait_trace_event_t tracking={.kind=AINEKIO_TRACE_TRACKING};
    tracking.tracking.support_known[0]=true;tracking.tracking.grounded[0]=true;
    tracking.tracking.policy_signature=456;tracking.tracking.policy_phase=2.75;
    tracking.tracking.policy_imu_us=999;tracking.tracking.policy_usable=true;
    tracking.tracking.policy_input[3][7]=.123f;tracking.tracking.policy_correction[2][2]=1.25;
    cJSON *encoded=event_json(4,&tracking);
    serialized=cJSON_PrintUnformatted(encoded);assert(serialized);
    cJSON_Delete(encoded);encoded=cJSON_Parse(serialized);free(serialized);assert(encoded);
    cJSON *leg=cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(encoded,"legs"),0);
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(leg,"support_known")));
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(leg,"planned_grounded")));
    cJSON *policy=cJSON_GetObjectItemCaseSensitive(encoded,"policy");
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(policy,"usable")));
    assert(cJSON_GetObjectItemCaseSensitive(policy,"signature")->valueint==456);
    assert(cJSON_GetObjectItemCaseSensitive(policy,"imu_timestamp_us")->valueint==999);
    assert(cJSON_GetObjectItemCaseSensitive(policy,"phase")->valuedouble==2.75);
    cJSON *features=cJSON_GetObjectItemCaseSensitive(policy,"features");
    assert(cJSON_GetArraySize(features)==32);
    assert((float)cJSON_GetArrayItem(features,31)->valuedouble==.123f);
    assert(cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(policy,"correction_mm"),8)->valuedouble==1.25);
    cJSON_Delete(encoded);
    request("{\"op\":\"trace_stop\",\"session\":2}");assert(strstr(status,"409")&&active);
    request("{\"op\":\"trace_stop\",\"session\":1,\"boot_id\":9}");assert(strstr(status,"409")&&active);
    for(unsigned i=0;i<600;i++)ainekio_p4_gait_trace_output(pulses,i+200,true);
    request("{\"op\":\"trace_read\",\"after\":3,\"session\":1}");
    assert(strstr(response,"\"lost\":88")&&strstr(response,"\"next\":155")&&strstr(response,"\"more\":true"));
    assert(data_chunks==(response_bytes+TRACE_HTTP_BUFFER-1)/TRACE_HTTP_BUFFER);
    assert(data_chunks<TRACE_BATCH);
    unsigned lines=0;char *line=response;
    while(*line) {
        char *end=strchr(line,'\n');assert(end);*end=0;
        cJSON *parsed=cJSON_Parse(line);assert(parsed);cJSON_Delete(parsed);
        *end='\n';line=end+1;lines++;
    }
    assert(lines==TRACE_BATCH+2);
    request("{\"op\":\"trace_stop\",\"session\":1}");assert(!active&&ring.events);
    uint64_t last=ring.latest;ainekio_p4_gait_trace_output(pulses,999,true);assert(ring.latest==last);
    fail_final_chunk=true;
    request("{\"op\":\"trace_read\",\"after\":603}");assert(ring.events);
    fail_final_chunk=false;
    fail_data_chunk=true;
    request("{\"op\":\"trace_read\",\"after\":603}");assert(ring.events);
    fail_data_chunk=false;
    request("{\"op\":\"trace_read\",\"after\":603}");assert(strstr(response,"\"more\":false"));
    assert(!ring.events&&ring.capacity==0);
    ainekio_p4_gait_trace_tracking(&tracking);ainekio_p4_gait_trace_sample(&s);
    assert(!ring.events&&ring.latest==last);
    request("{\"op\":\"trace_read\",\"after\":603}");
    assert(strstr(response,"\"storage_bytes\":0")&&strstr(response,"\"more\":false"));
    request("{\"op\":\"trace_start\"}");assert(session==2&&ring.latest==1&&active);
    request("{\"op\":\"trace_read\",\"after\":-1}");assert(strstr(status,"400"));
    request("{\"op\":\"trace_stop\",\"session\":2}");assert(!ring.events&&!active);
    puts("Device trace: batching, loss, failed transfer retention, release after drain, inactive producers and restart passed.");
}
