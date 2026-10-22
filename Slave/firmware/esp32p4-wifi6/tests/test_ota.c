/* Run the production HTTP/OTA state machine. Only SDK, flash, and hardware
 * boundaries are mocked; this does not emulate the ROM/rollback bootloader. */
#define taskENTER_CRITICAL portENTER_CRITICAL
#define taskEXIT_CRITICAL portEXIT_CRITICAL
#include "../main/ota.c"
#include <assert.h>
static unsigned feedback_requests;
esp_err_t ainekio_p4_idle_rest_http(struct httpd_req *r){(void)r;return ESP_OK;}
esp_err_t ainekio_p4_feedback_http(struct httpd_req *r){(void)r;feedback_requests++;return ESP_OK;}

static const esp_partition_t slot0 = {.address=0x20000, .size=0x800000, .label="ota_0"};
static const esp_partition_t slot1 = {.address=0x820000, .size=0x800000, .label="ota_1"};
static const esp_partition_t *boot_slot;
static const esp_app_desc_t app = {.magic_word=ESP_APP_DESC_MAGIC_WORD, .project_name="ainekio_p4_body"};
static ainekio_config_record_t configuration = {.robot_token="test-token"};
static unsigned char image_bytes[12000];
static size_t input_used, available, written;
static const char *input, *authorization;
static char response_code[32], response_body[512];
static int begins, aborts, ends, selects, restarts, stops, dozes, writes;
static esp_err_t stop_error, write_error, end_error, nvs_error;
static bool layout, camera, c6, body, display;
static bool output_ready, output_initialized;
static ainekio_pca_fault_t output_fault;
static uint32_t saved_expected;
static size_t file_remaining, file_sent;
static bool file_query, file_fail, file_closed, chunk_ended;
static int file_opens;

static void reset(void)
{
    atomic_store(&busy, false); staged=NULL; phase=NONE; expected=0;
    input_used=written=0; available=sizeof(image_bytes); input=(const char *)image_bytes;
    authorization="Bearer test-token"; boot_slot=&slot0;
    begins=aborts=ends=selects=restarts=stops=dozes=writes=0;
    stop_error=write_error=end_error=nvs_error=ESP_OK;
    layout=camera=c6=body=display=true;
    output_ready=output_initialized=true; output_fault=AINEKIO_PCA_FAULT_NONE;
    saved_expected=0; response_code[0]=response_body[0]=0;
    memset(image_bytes, 0, sizeof(image_bytes));
    const esp_image_header_t h = {.magic=ESP_IMAGE_HEADER_MAGIC, .chip_id=ESP_CHIP_ID_ESP32P4};
    memcpy(image_bytes, &h, sizeof(h));
    memcpy(image_bytes+sizeof(h)+sizeof(esp_image_segment_header_t), &app, sizeof(app));
}
static httpd_req_t request(size_t size) { return (httpd_req_t){.method=HTTP_POST,.content_len=size}; }

int main(void)
{
    httpd_req_t r=request(sizeof(image_bytes));
    reset();authorization="Bearer wrong";servo_feedback(&r);
    assert(!feedback_requests&&!strcmp(response_code,"401 Unauthorized"));
    reset();servo_feedback(&r);assert(feedback_requests==1);
    reset(); authorization="Bearer wrong"; upload(&r);
    assert(!begins && !stops && !selects && !strcmp(response_code,"401 Unauthorized"));
    reset(); layout=false; upload(&r); assert(!begins && !stops);
    reset(); boot_slot=&slot1; upload(&r); assert(!begins && !stops);
    reset(); ((esp_image_header_t *)image_bytes)->chip_id=13; upload(&r); assert(!begins && !stops);
    reset(); image_bytes[sizeof(esp_image_header_t)+sizeof(esp_image_segment_header_t)+sizeof(uint32_t)]='x';
    upload(&r); assert(!begins && !stops);
    reset(); stop_error=ESP_ERR_TIMEOUT; upload(&r); assert(!begins && !selects && phase==FAILED);
    reset(); available=5000; upload(&r);
    assert(begins==1 && aborts==1 && !ends && !selects && !staged && !ainekio_p4_ota_busy());
    reset(); write_error=ESP_FAIL; upload(&r); assert(aborts==1 && !selects);
    reset(); end_error=ESP_FAIL; upload(&r); assert(ends==1 && !aborts && !selects && !staged);
    reset(); upload(&r);
    assert(begins==1 && stops==1 && dozes==1 && ends==1 && !selects && !restarts);
    assert(written==sizeof(image_bytes) && staged==&slot1 && phase==STAGED && !ainekio_p4_ota_busy());
    ainekio_connection_page_t page = {.face_visible=true};
    assert(ainekio_p4_ota_page(&page) && !page.face_visible && !strcmp(page.lines[0],"Upload verified"));
    input="next_boot";input_used=0;available=9;r=request(9);activate(&r);
    assert(selects==1 && !restarts && boot_slot==&slot1 && saved_expected);
    assert(ainekio_p4_ota_startup_check()==ESP_OK);
    /* Authentication disables outputs before checking the new firmware.
     * A deliberate disable is not a missing/faulty PCA device. */
    output_ready=false;output_fault=AINEKIO_PCA_FAULT_EMERGENCY;
    assert(ainekio_p4_ota_startup_check()==ESP_OK);
    output_initialized=false;assert(ainekio_p4_ota_startup_check()!=ESP_OK);
    output_initialized=true;
    output_fault=AINEKIO_PCA_FAULT_IO;assert(ainekio_p4_ota_startup_check()!=ESP_OK);
    output_fault=AINEKIO_PCA_FAULT_DEADLINE;assert(ainekio_p4_ota_startup_check()!=ESP_OK);
    output_fault=AINEKIO_PCA_FAULT_PROGRESS;assert(ainekio_p4_ota_startup_check()!=ESP_OK);
    output_ready=true;output_fault=AINEKIO_PCA_FAULT_NONE;
    camera=false;assert(ainekio_p4_ota_startup_check()!=ESP_OK);camera=true;
    c6=false;assert(ainekio_p4_ota_startup_check()!=ESP_OK);c6=true;
    body=false;assert(ainekio_p4_ota_startup_check()!=ESP_OK);body=true;
    input="restart";input_used=0;available=7;r=request(7);activate(&r);
    assert(restarts==1);
    reset();r=request(sizeof(image_bytes));upload(&r);nvs_error=ESP_FAIL;
    input="next_boot";input_used=0;available=9;r=request(9);activate(&r);
    assert(!selects && !restarts);
    reset(); r=(httpd_req_t){.method=HTTP_GET}; file_query=true;
    file_remaining=9000;file_sent=0;file_closed=chunk_ended=false;
    assert(recordings(&r)==ESP_OK && file_sent==9000 && file_closed && chunk_ended);
    file_remaining=9000;file_sent=0;file_fail=true;file_closed=chunk_ended=false;
    assert(recordings(&r)==ESP_FAIL && !file_sent && file_closed && !chunk_ended);
    file_fail=false;authorization="Bearer wrong";file_opens=0;
    recordings(&r);assert(!file_opens && !strcmp(response_code,"401 Unauthorized"));
    puts("OTA admission, truncation, write/hash failures, explicit activation, readiness and display passed");
    return 0;
}

const char *esp_err_to_name(esp_err_t e) { return e==ESP_OK ? "ESP_OK" : "test_failure"; }
int64_t esp_timer_get_time(void) { return 1000000; }
void vTaskDelay(TickType_t ticks) { (void)ticks; }
const ainekio_config_record_t *ainekio_p4_config(void) { return &configuration; }
const esp_app_desc_t *esp_app_get_description(void) { return &app; }
ainekio_p4_system_status_t ainekio_p4_system_status(void) { return (ainekio_p4_system_status_t){.ota_layout=layout}; }
ainekio_p4_media_status_t ainekio_p4_media_status(void) { return (ainekio_p4_media_status_t){.camera_ready=camera}; }
ainekio_p4_video_status_t ainekio_p4_video_status(void) { return (ainekio_p4_video_status_t){0}; }
ainekio_p4_storage_status_t ainekio_p4_storage_status(void) { return (ainekio_p4_storage_status_t){0}; }
bool ainekio_p4_display_ready(void) { return display; }
ainekio_pca9685_t *ainekio_p4_output(void) { return NULL; }
bool ainekio_p4_output_initialized(void) { return output_initialized; }
ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *p) { (void)p;return (ainekio_pca_status_t){.ready=output_ready,.fault=output_fault}; }
ainekio_p4_body_timing_t ainekio_p4_body_timing(void) { return (ainekio_p4_body_timing_t){.stack_free_bytes=body?1000:0}; }
esp_err_t ainekio_p4_video_start(void) { return ESP_OK; }
esp_err_t ainekio_p4_video_stop(void) { ++stops; return stop_error; }
esp_err_t ainekio_p4_system_state(ainekio_state_request_t s,uint32_t seconds)
{ (void)seconds;assert(s==AINEKIO_STATE_REQUEST_DOZE);++dozes;return ESP_OK; }
esp_err_t ainekio_p4_system_restart(void) { ++restarts;return ESP_OK; }
esp_err_t esp_hosted_get_coprocessor_fwversion(esp_hosted_coprocessor_fwver_t *v)
{ *v=(esp_hosted_coprocessor_fwver_t){.major1=2,.minor1=12,.patch1=8};return c6?ESP_OK:ESP_FAIL; }
const esp_partition_t *esp_ota_get_running_partition(void) { return &slot0; }
const esp_partition_t *esp_ota_get_boot_partition(void) { return boot_slot; }
const esp_partition_t *esp_ota_get_next_update_partition(const esp_partition_t *p) { (void)p;return &slot1; }
esp_err_t esp_ota_begin(const esp_partition_t *p,size_t n,esp_ota_handle_t *h)
{ assert(p==&slot1 && n==OTA_WITH_SEQUENTIAL_WRITES && dozes && stops);*h=1;++begins;return ESP_OK; }
esp_err_t esp_ota_write(esp_ota_handle_t h,const void *p,size_t n)
{ assert(h==1 && n<=4096 && !memcmp(p,image_bytes+written,n));++writes;written+=n;return write_error; }
esp_err_t esp_ota_end(esp_ota_handle_t h) { assert(h==1);++ends;return end_error; }
esp_err_t esp_ota_abort(esp_ota_handle_t h) { assert(h==1);++aborts;return ESP_OK; }
esp_err_t esp_ota_set_boot_partition(const esp_partition_t *p) { assert(p==&slot1);++selects;boot_slot=p;return ESP_OK; }
esp_err_t nvs_open(const char *name,int mode,nvs_handle_t *n) { (void)mode;assert(!strcmp(name,"p4_ota"));*n=1;return nvs_error; }
esp_err_t nvs_get_u32(nvs_handle_t n,const char *key,uint32_t *v) { (void)n;(void)key;*v=saved_expected;return ESP_OK; }
esp_err_t nvs_set_u32(nvs_handle_t n,const char *key,uint32_t v) { (void)n;(void)key;saved_expected=v;return ESP_OK; }
esp_err_t nvs_commit(nvs_handle_t n) { (void)n;return ESP_OK; }
void nvs_close(nvs_handle_t n) { (void)n; }
esp_err_t httpd_resp_set_status(httpd_req_t *r,const char *s) { (void)r;snprintf(response_code,sizeof(response_code),"%s",s);return ESP_OK; }
esp_err_t httpd_resp_set_type(httpd_req_t *r,const char *s) { (void)r;(void)s;return ESP_OK; }
esp_err_t httpd_resp_set_hdr(httpd_req_t *r,const char *k,const char *v) { (void)r;(void)k;(void)v;return ESP_OK; }
esp_err_t httpd_resp_sendstr(httpd_req_t *r,const char *s) { (void)r;snprintf(response_body,sizeof(response_body),"%s",s);return ESP_OK; }
esp_err_t httpd_sess_trigger_close(httpd_handle_t h,int s) { (void)h;(void)s;return ESP_OK; }
int httpd_req_to_sockfd(httpd_req_t *r) { (void)r;return 1; }
esp_err_t httpd_req_get_hdr_value_str(httpd_req_t *r,const char *key,char *s,size_t n)
{ (void)r;assert(!strcmp(key,"Authorization"));snprintf(s,n,"%s",authorization);return ESP_OK; }
int httpd_req_recv(httpd_req_t *r,char *s,size_t n)
{ (void)r;size_t left=available-input_used;if(!left)return -1;if(n>left)n=left;if(n>137)n=137;
  memcpy(s,input+input_used,n);input_used+=n;return n; }
esp_err_t httpd_register_uri_handler(httpd_handle_t h,const httpd_uri_t *u) { (void)h;(void)u;return ESP_OK; }

/* SDK/storage boundaries for the production chunked-download handler. */
esp_err_t httpd_resp_send_chunk(httpd_req_t *r,const char *s,ssize_t n) { (void)r;(void)s;if(n==0)chunk_ended=true;else if(n>0){assert(n<=4096);file_sent+=n;}return ESP_OK; }
size_t httpd_req_get_url_query_len(httpd_req_t *r) { (void)r;return file_query?35:0; }
esp_err_t httpd_req_get_url_query_str(httpd_req_t *r,char *s,size_t n) { (void)r;snprintf(s,n,"name=video-1234abcd-00000001.avi");return ESP_OK; }
esp_err_t httpd_query_key_value(const char *q,const char *k,char *s,size_t n) { (void)q;(void)k;snprintf(s,n,"video-1234abcd-00000001.avi");return ESP_OK; }
esp_err_t ainekio_p4_recording_list_open(void) { return ESP_OK; }
esp_err_t ainekio_p4_recording_list_next(ainekio_p4_recording_file_t *f,bool *done) { (void)f;*done=true;return ESP_OK; }
esp_err_t ainekio_p4_recording_read_open(const char *name,uint64_t *bytes) { (void)name;++file_opens;*bytes=file_remaining;return ESP_OK; }
esp_err_t ainekio_p4_recording_read(void *b,size_t n,size_t *bytes) { if(file_fail)return ESP_FAIL;*bytes=file_remaining<n?file_remaining:n;memset(b,1,*bytes);file_remaining-=*bytes;return ESP_OK; }
void ainekio_p4_recording_read_close(void) {file_closed=true;}

size_t ainekio_p4_logs_snapshot(char *buffer,size_t capacity) {(void)buffer;(void)capacity;return 0;}
void ainekio_p4_log_stage(const char *stage) {(void)stage;}

void ainekio_p4_learning_init(void){}
esp_err_t ainekio_p4_learning_http(struct httpd_req *r){(void)r;return ESP_OK;}
