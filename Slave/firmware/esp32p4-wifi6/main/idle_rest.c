#include "idle_rest.h"
#include "body.h"
#include "config.h"
#include "cJSON.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

esp_err_t ainekio_p4_idle_rest_http(httpd_req_t *r)
{
    httpd_resp_set_type(r,"application/json");
    if(r->method==HTTP_POST) {
        char input[128];
        if(r->content_len<=0 || r->content_len>=sizeof input) {
            httpd_resp_set_status(r,"400 Bad Request");
            return httpd_resp_sendstr(r,"{\"error\":\"Expected op configure and integer seconds; 0 disables rest\"}");
        }
        size_t received=0;
        while(received<r->content_len) {
            const int n=httpd_req_recv(r,input+received,r->content_len-received);
            if(n<=0)return ESP_FAIL;
            received+=(size_t)n;
        }
        input[received]=0;
        cJSON *o=cJSON_Parse(input);
        const cJSON *op=cJSON_GetObjectItemCaseSensitive(o,"op");
        const cJSON *seconds=cJSON_GetObjectItemCaseSensitive(o,"seconds");
        const bool valid=cJSON_IsString(op) && !strcmp(op->valuestring,"configure") &&
            cJSON_IsNumber(seconds) && isfinite(seconds->valuedouble) &&
            seconds->valuedouble>=0 && seconds->valuedouble<=UINT32_MAX &&
            floor(seconds->valuedouble)==seconds->valuedouble;
        const esp_err_t result=valid ? ainekio_p4_idle_rest_save((uint32_t)seconds->valuedouble) : ESP_ERR_INVALID_ARG;
        cJSON_Delete(o);
        if(result!=ESP_OK) {
            httpd_resp_set_status(r,valid ? "500 Internal Server Error" : "400 Bad Request");
            return httpd_resp_sendstr(r,valid ? "{\"error\":\"Could not save inactivity setting\"}" :
                "{\"error\":\"Expected op configure and integer seconds; 0 disables rest\"}");
        }
        ainekio_p4_body_activity();
    }
    char output[96];
    snprintf(output,sizeof output,"{\"seconds\":%lu,\"saved\":%s}",
        (unsigned long)ainekio_p4_idle_rest_seconds(),ainekio_p4_idle_rest_saved()?"true":"false");
    return httpd_resp_sendstr(r,output);
}
