#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <float.h>
#include <inttypes.h>
#include <stdio.h>
#include "../main/gait_trace_runtime.c"
static char response[300000],wire_response[300000],status[80],content_type[80];static size_t response_bytes;
static bool allocation_fail;
static bool fail_final_chunk;
static bool fail_data_chunk;
static unsigned data_chunks;
static uint64_t clock_us=100;
static bool host_nominal;
static uint32_t output_sequence=77;
void *heap_caps_calloc(size_t n,size_t size,unsigned caps)
{ assert(caps==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));return allocation_fail?NULL:calloc(n,size); }
uint32_t esp_random(void){return 12345;}
uint32_t ainekio_p4_controller_sensor_boot_id(void){return 67890;}
int64_t esp_timer_get_time(void){return clock_us;}
ainekio_p4_imu_status_t ainekio_p4_imu_status(void)
{
    ainekio_p4_imu_status_t s={0};s.attitude.available=s.attitude.fresh=true;s.calibration_applied=true;
    s.attitude.timestamp_us=clock_us-2;s.attitude.orientation_wxyz[0]=1;return s;
}
ainekio_p4_body_status_t ainekio_p4_body_status(void)
{ return (ainekio_p4_body_status_t){.gait_valid=true,.gait_host_nominal=host_nominal,.gait_phase=.25,.sequence=77,.stride_percent=100,
    .execution={.sequence=output_sequence,.host_nominal=host_nominal,.nominal_sample=42,.sampled_us=90}}; }
void ainekio_p4_body_pulse_snapshot(uint16_t pulses[12],uint64_t *stamp,bool *armed)
{ for(unsigned j=0;j<12;j++)pulses[j]=1500;*stamp=50;*armed=true; }
esp_err_t httpd_resp_set_status(httpd_req_t *r,const char *s){(void)r;strcpy(status,s);return ESP_OK;}
esp_err_t httpd_resp_set_type(httpd_req_t *r,const char *s){(void)r;strcpy(content_type,s);return ESP_OK;}
esp_err_t httpd_resp_set_hdr(httpd_req_t *r,const char *a,const char *b){(void)r;(void)a;(void)b;return ESP_OK;}
esp_err_t httpd_resp_send_chunk(httpd_req_t *r,const char *s,ssize_t n)
{
    (void)r;if(!n && fail_final_chunk)return ESP_FAIL;
    if(n){data_chunks++;if(fail_data_chunk)return ESP_FAIL;}
    if(n){assert(response_bytes+n<sizeof response);memcpy(wire_response+response_bytes,s,n);response_bytes+=n;}
    wire_response[response_bytes]=0;return ESP_OK;
}
esp_err_t httpd_resp_sendstr(httpd_req_t *r,const char *s){return httpd_resp_send_chunk(r,s,strlen(s));}
/* Small test reader for the emitted CBOR types. The maintained Python test
 * also decodes --wire-fixture with the independent cbor2 implementation. */
static cJSON *decode_value(const uint8_t **cursor,const uint8_t *end)
{
    assert(*cursor<end);const uint8_t head=*(*cursor)++;
    const unsigned major=head>>5,additional=head&31;
    uint64_t value=additional;
    if(additional>=24 && additional<=27) {
        const unsigned count=1U<<(additional-24);assert((size_t)(end-*cursor)>=count);value=0;
        for(unsigned i=0;i<count;i++)value=value<<8|*(*cursor)++;
    }
    if(major==0)return cJSON_CreateNumber((double)value);
    if(major==1)return cJSON_CreateNumber(-1.-(double)value);
    if(major==3) {
        assert(value<=(uint64_t)(end-*cursor));char *text=malloc(value+1);assert(text);
        memcpy(text,*cursor,value);text[value]=0;*cursor+=value;
        cJSON *result=cJSON_CreateString(text);free(text);return result;
    }
    if(major==4) {
        assert(additional!=31);cJSON *result=cJSON_CreateArray();
        for(uint64_t i=0;i<value;i++)cJSON_AddItemToArray(result,decode_value(cursor,end));
        return result;
    }
    if(major==5) {
        assert(additional==31);cJSON *result=cJSON_CreateObject();
        while(*cursor<end && **cursor!=0xff) {
            cJSON *key=decode_value(cursor,end);assert(cJSON_IsString(key));
            cJSON_AddItemToObject(result,key->valuestring,decode_value(cursor,end));cJSON_Delete(key);
        }
        assert(*cursor<end && *(*cursor)++==0xff);return result;
    }
    assert(major==7);
    if(additional==20 || additional==21)return cJSON_CreateBool(additional==21);
    if(additional==22)return cJSON_CreateNull();
    if(additional==26) {uint32_t bits=(uint32_t)value;float number;memcpy(&number,&bits,4);return cJSON_CreateNumber(number);}
    assert(additional==27);double number;memcpy(&number,&value,8);return cJSON_CreateNumber(number);
}
static cJSON *decode_record(const void *data,size_t length)
{
    const uint8_t *cursor=data,*end=cursor+length;cJSON *result=decode_value(&cursor,end);
    assert(cursor==end);return result;
}
static cJSON *encoded_event(uint64_t sequence,const ainekio_gait_trace_event_t *event)
{
    char buffer[TRACE_HTTP_BUFFER];trace_writer_t writer={.data=buffer};
    event_cbor(&writer,sequence,event);assert(writer.result==ESP_OK && writer.used);
    return decode_record(buffer,writer.used);
}
static size_t json_allocations;
static void *count_json_malloc(size_t size){++json_allocations;return malloc(size);}
static void request(const char *json)
{
    response_bytes=0;data_chunks=0;status[0]=content_type[0]=0;response[0]=wire_response[0]=0;
    cJSON *op=cJSON_Parse(json);assert(op);httpd_req_t r={0};
    const size_t before=json_allocations;
    const esp_err_t result=ainekio_p4_gait_trace_http(&r,op);
    assert(json_allocations==before); /* No cJSON output tree or print allocation. */
    assert(result==(fail_final_chunk||fail_data_chunk?ESP_FAIL:ESP_OK));cJSON_Delete(op);
    if(result!=ESP_OK)return;
    if(status[0]){memcpy(response,wire_response,response_bytes+1);return;}
    assert(!strcmp(content_type,"application/cbor-seq"));
    const uint8_t *cursor=(const uint8_t *)wire_response,*end=cursor+response_bytes;size_t used=0;
    while(cursor<end) {
        cJSON *record=decode_value(&cursor,end);char *text=cJSON_PrintUnformatted(record);assert(text);
        const size_t size=strlen(text);assert(used+size+2<sizeof response);
        memcpy(response+used,text,size);used+=size;response[used++]='\n';response[used]=0;
        free(text);cJSON_Delete(record);
    }
}
static int wire_fixture(void)
{
    request("{\"op\":\"trace_start\"}");
    ainekio_p4_feedback_snapshot_t sample={.valid_mask=0xfff0,.revision=UINT32_MAX,.scan=91,.error=-7};
    sample.sampled_us[15]=UINT64_C(9007199254740991);sample.raw[15]=65535;
    sample.filtered_raw[0]=-.123f;sample.velocity_raw_s[1]=NAN;
    ainekio_p4_gait_trace_sample(&sample);
    ainekio_gait_trace_event_t tracking={.kind=AINEKIO_TRACE_TRACKING};
    strcpy(tracking.tracking.model_id,"quote\"line\n");tracking.tracking.policy_phase=nextafter(1.,2.);
    tracking.tracking.policy_input[3][7]=FLT_MAX;tracking.tracking.policy_correction[2][2]=1.25f;
    tracking.tracking.nominal_pulses[11]=2800;ainekio_p4_gait_trace_tracking(&tracking);
    ainekio_imu_observation_t imu={.timestamp_us=UINT64_C(10000000000),.available=true,.fresh=true,
        .accepted_samples=123456,.orientation_wxyz={1,0,0,0},.acceleration_m_s2={0,0,9.80665f}};
    imu.angular_rate_rad_s[1]=-.123f;ainekio_p4_gait_trace_imu(&imu,true);
    host_nominal=true;ainekio_p4_gait_trace_sample(&sample);
    request("{\"op\":\"trace_stop\",\"session\":1}");
    assert(!active && !ring.events);
    return fwrite(wire_response,1,response_bytes,stdout)==response_bytes?0:1;
}
int main(int argc,char **argv)
{
    cJSON_Hooks hooks={.malloc_fn=count_json_malloc,.free_fn=free};cJSON_InitHooks(&hooks);
    if(argc==2 && !strcmp(argv[1],"--wire-fixture"))return wire_fixture();
    assert(argc==1);
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
    char numeric_buffer[TRACE_HTTP_BUFFER];trace_writer_t numeric={.data=numeric_buffer};
    map(&numeric,NULL);floats(&numeric,"values",probes,1024);end_map(&numeric);
    cJSON *decoded=decode_record(numeric_buffer,numeric.used);
    cJSON *values=cJSON_GetObjectItemCaseSensitive(decoded,"values");assert(cJSON_GetArraySize(values)==1024);
    for(unsigned i=0;i<1024;i++) {
        cJSON *value=cJSON_GetArrayItem(values,i);
        if(isfinite(probes[i])) {
            assert(cJSON_IsNumber(value));float restored=(float)value->valuedouble;
            assert(memcmp(&restored,&probes[i],sizeof restored)==0);
        } else assert(cJSON_IsNull(value));
    }
    cJSON_Delete(decoded);
    const double doubles[]={DBL_MAX,-DBL_MAX,DBL_MIN,-DBL_MIN,0.,-0.,.1,
        nextafter(1.,2.),nextafter(1.,0.),INFINITY,NAN};
    numeric.used=0;map(&numeric,NULL);scalar(&numeric,"scalar_float",-.123f);
    integer(&numeric,"timestamp_us",UINT64_C(9007199254740991));
    for(unsigned i=0;i<sizeof doubles/sizeof doubles[0];i++) {
        char key[16];snprintf(key,sizeof key,"d%u",i);real(&numeric,key,doubles[i]);
    }
    end_map(&numeric);decoded=decode_record(numeric_buffer,numeric.used);
    assert((float)cJSON_GetObjectItemCaseSensitive(decoded,"scalar_float")->valuedouble==-.123f);
    assert(cJSON_GetObjectItemCaseSensitive(decoded,"timestamp_us")->valuedouble==9007199254740991.);
    for(unsigned i=0;i<sizeof doubles/sizeof doubles[0];i++) {
        char key[16];snprintf(key,sizeof key,"d%u",i);cJSON *value=cJSON_GetObjectItemCaseSensitive(decoded,key);
        if(isfinite(doubles[i]))assert(cJSON_IsNumber(value) && !memcmp(&value->valuedouble,&doubles[i],sizeof(double)));
        else assert(cJSON_IsNull(value));
    }
    cJSON_Delete(decoded);
    /* RFC 8949 byte-level vectors independently check endianness and widths. */
    numeric.used=0;argument(&numeric,0,UINT64_C(9007199254740991));float_value(&numeric,1.f);
    real(&numeric,"d",1.);signed_integer(&numeric,"e",-256);text(&numeric,"\"\n");
    const uint8_t expected[]={0x1b,0,0x1f,0xff,0xff,0xff,0xff,0xff,0xff,0xfa,0x3f,0x80,0,0,
        0x61,'d',0xfb,0x3f,0xf0,0,0,0,0,0,0,0x61,'e',0x38,0xff,0x62,'"','\n'};
    assert(numeric.used==sizeof expected && !memcmp(numeric_buffer,expected,sizeof expected));
    uint16_t pulses[12]={1800};
    ainekio_p4_gait_trace_output(pulses,1,true);assert(!ring.events);
    allocation_fail=true;request("{\"op\":\"trace_start\"}");assert(strstr(status,"500")&&!active);
    allocation_fail=false;request("{\"op\":\"trace_start\"}");assert(active&&session==1);
    assert(strstr(response,"gait_trace_v1")&&strstr(response,"\"time_us\":50"));
    assert(strstr(response,"\"sensor_boot_id\":67890") && strstr(response,"\"boot_id\":12345"));
    ainekio_p4_feedback_snapshot_t s={.valid_mask=0xfff0,.revision=7,.scan=9};
    s.sampled_us[15]=95;s.raw[15]=321;s.filtered_raw[15]=322;s.velocity_raw_s[15]=4;
    ainekio_p4_gait_trace_sample(&s);ainekio_p4_gait_trace_output(pulses,110,true);
    request("{\"op\":\"trace_read\",\"after\":1,\"session\":1,\"boot_id\":12345}");
    assert(strstr(response,"\"scan\":9")&&strstr(response,"\"phase\":0.25")&&strstr(response,"\"timestamp_us\":98"));
    assert(strstr(response,"\"next\":3")&&strstr(response,"\"lost\":0"));
    assert(strstr(response,"\"calibration_applied\":true"));
    /* Source attribution comes from the output owner, not native phase fields. */
    host_nominal=true;ainekio_p4_gait_trace_sample(&s);
    ainekio_gait_trace_event_t host_event;
    assert(ainekio_gait_trace_read(&ring,ring.latest,&host_event));
    cJSON *host_json=encoded_event(ring.latest,&host_event);
    cJSON *host_motion=cJSON_GetObjectItemCaseSensitive(host_json,"motion");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(host_motion,"walk_source")->valuestring,"host"));
    assert(cJSON_GetObjectItemCaseSensitive(host_motion,"nominal_sample")->valueint==42);
    assert(cJSON_GetObjectItemCaseSensitive(host_motion,"sampled_us")->valueint==90);
    assert(!cJSON_GetObjectItemCaseSensitive(host_motion,"phase"));
    assert(!cJSON_GetObjectItemCaseSensitive(host_motion,"cycles_s"));
    assert(!cJSON_GetObjectItemCaseSensitive(host_motion,"stride_percent"));
    cJSON_Delete(host_json);
    output_sequence=76;ainekio_p4_gait_trace_sample(&s);
    assert(ainekio_gait_trace_read(&ring,ring.latest,&host_event));
    assert(host_event.sample.host_nominal && !host_event.sample.nominal_sample && !host_event.sample.output_us);
    output_sequence=77;host_nominal=false;
    ainekio_gait_trace_event_t tracking={.kind=AINEKIO_TRACE_TRACKING};
    tracking.tracking.support_known[0]=true;tracking.tracking.grounded[0]=true;
    tracking.tracking.policy_signature=456;tracking.tracking.policy_phase=2.75;
    tracking.tracking.policy_imu_us=999;tracking.tracking.policy_usable=true;
    tracking.tracking.policy_input[3][7]=.123f;tracking.tracking.policy_correction[2][2]=1.25;
    cJSON *encoded=encoded_event(4,&tracking);
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
    assert(strstr(response,"\"lost\":90")&&strstr(response,"\"next\":157")&&strstr(response,"\"more\":true"));
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
    request("{\"op\":\"trace_read\",\"after\":605}");assert(ring.events);
    fail_final_chunk=false;
    fail_data_chunk=true;
    request("{\"op\":\"trace_read\",\"after\":605}");assert(ring.events);
    fail_data_chunk=false;
    request("{\"op\":\"trace_read\",\"after\":605}");assert(strstr(response,"\"more\":false"));
    assert(!ring.events&&ring.capacity==0);
    ainekio_p4_gait_trace_tracking(&tracking);ainekio_p4_gait_trace_sample(&s);
    assert(!ring.events&&ring.latest==last);
    request("{\"op\":\"trace_read\",\"after\":605}");
    assert(strstr(response,"\"storage_bytes\":0")&&strstr(response,"\"more\":false"));
    request("{\"op\":\"trace_start\"}");assert(session==2&&ring.latest==1&&active);
    request("{\"op\":\"trace_read\",\"after\":-1}");assert(strstr(status,"400"));
    request("{\"op\":\"trace_stop\",\"session\":2}");assert(!ring.events&&!active);
    /* Acquisition-rate inertial records share the same cursor, ring and final
     * drain as servo/output events. Reading never substitutes host time. */
    ainekio_imu_observation_t inertial={.available=true,.fresh=true,.accelerometer_ignored=true};
    inertial.orientation_wxyz[0]=1;inertial.acceleration_m_s2[2]=9.80665f;
    inertial.angular_rate_rad_s[1]=-.123f;
    ainekio_p4_gait_trace_imu(&inertial,true);assert(!ring.events);
    request("{\"op\":\"trace_start\"}");assert(session==3 && active);
    const size_t storage_bytes=ring.capacity*sizeof(*ring.events);
    for(unsigned i=0;i<208;++i) {
        inertial.timestamp_us=UINT64_C(10000000000)+i*4808;
        inertial.accepted_samples=i+1;
        ainekio_p4_gait_trace_imu(&inertial,true);
    }
    assert(ring.latest==209 && storage_bytes==307200);
    ainekio_gait_trace_event_t acquired;
    for(unsigned i=0;i<208;++i) {
        assert(ainekio_gait_trace_read(&ring,i+2,&acquired));
        assert(acquired.kind==AINEKIO_TRACE_IMU && acquired.time_us==UINT64_C(10000000000)+i*4808);
        assert(acquired.imu.sample.accepted_samples==i+1);
    }
    encoded=encoded_event(209,&acquired);
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(encoded,"kind")->valuestring,"imu"));
    cJSON *sample=cJSON_GetObjectItemCaseSensitive(encoded,"imu");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(sample,"frame")->valuestring,"body_nominal"));
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(sample,"accelerometer_ignored")));
    assert(cJSON_GetObjectItemCaseSensitive(sample,"timestamp_us")->valuedouble==(double)inertial.timestamp_us);
    assert((float)cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(sample,"angular_rate_rad_s"),1)->valuedouble==-.123f);
    cJSON_Delete(encoded);
    request("{\"op\":\"trace_stop\",\"session\":3,\"after\":1}");assert(!active && ring.events);
    const uint64_t stopped=ring.latest;
    ainekio_p4_gait_trace_imu(&inertial,true);assert(ring.latest==stopped);
    for(uint64_t after=65;after<209;after+=TRACE_BATCH) {
        char command[96];snprintf(command,sizeof command,"{\"op\":\"trace_read\",\"session\":3,\"after\":%" PRIu64 "}",after);
        request(command);assert(strstr(response,"\"lost\":0"));
    }
    assert(!ring.events && ring.capacity==0);
    ainekio_p4_gait_trace_imu(&inertial,true);assert(!ring.events && ring.latest==stopped);
    puts("Device trace: batching, loss, failed transfer retention, release after drain, inactive producers and restart passed.");
}
