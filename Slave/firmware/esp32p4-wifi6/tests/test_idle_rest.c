/* Production settings endpoint; mock only HTTP/NVS boundaries. */
#include "../main/idle_rest.c"
#include <assert.h>
static uint32_t setting=180;
static bool saved,fail_save;
static unsigned activity;
static const char *input;
static size_t offset;
static char status_code[32],body_text[256];
uint32_t ainekio_p4_idle_rest_seconds(void){return setting;}
bool ainekio_p4_idle_rest_saved(void){return saved;}
esp_err_t ainekio_p4_idle_rest_save(uint32_t seconds)
{if(fail_save)return ESP_FAIL;setting=seconds;saved=true;return ESP_OK;}
void ainekio_p4_body_activity(void){activity++;}
esp_err_t httpd_resp_set_type(httpd_req_t *r,const char *s){(void)r;assert(!strcmp(s,"application/json"));return ESP_OK;}
esp_err_t httpd_resp_set_status(httpd_req_t *r,const char *s){(void)r;snprintf(status_code,sizeof status_code,"%s",s);return ESP_OK;}
esp_err_t httpd_resp_sendstr(httpd_req_t *r,const char *s){(void)r;snprintf(body_text,sizeof body_text,"%s",s);return ESP_OK;}
int httpd_req_recv(httpd_req_t *r,char *s,size_t n)
{(void)r;if(n>3)n=3;memcpy(s,input+offset,n);offset+=n;return (int)n;}
static void call(const char *json)
{
    input=json;offset=0;strcpy(status_code,"200 OK");
    httpd_req_t r={.method=json?HTTP_POST:HTTP_GET,.content_len=json?strlen(json):0};
    assert(ainekio_p4_idle_rest_http(&r)==ESP_OK);
}
int main(void)
{
    call(NULL);assert(!strcmp(body_text,"{\"seconds\":180,\"saved\":false}") && !activity);
    call("{\"op\":\"configure\",\"seconds\":240}");assert(setting==240&&saved&&activity==1);
    call("{\"op\":\"configure\",\"seconds\":0}");assert(!setting&&activity==2);
    const char *bad[]={"{}","null","{\"op\":\"configure\",\"seconds\":-1}",
        "{\"op\":\"configure\",\"seconds\":0.1}","{\"op\":\"configure\",\"seconds\":4294967296}",
        "{\"op\":\"configure\",\"seconds\":\"180\"}"};
    for(unsigned i=0;i<sizeof bad/sizeof *bad;i++){
        call(bad[i]);assert(!strcmp(status_code,"400 Bad Request")&&!setting&&activity==2);
    }
    fail_save=true;call("{\"op\":\"configure\",\"seconds\":180}");
    assert(!strcmp(status_code,"500 Internal Server Error")&&!setting&&activity==2);
    puts("Inactivity HTTP configuration: default, save, disable, read, malformed input and storage failure passed.");
}
