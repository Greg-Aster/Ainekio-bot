/* Real shared DNS-SD owner; only mDNS and station I/O are simulated. */
#include <assert.h>
#include <arpa/inet.h>
#include <stdbool.h>
#include <string.h>
#include "ainekio/platform/local_discovery.h"
#include "mdns.h"

static mdns_result_t *available;
static esp_err_t query_error, init_error;
static bool station_available = true;
static unsigned freed, initialized;
static esp_netif_ip_info_t station;
static mdns_txt_item_t txt[] = {{"protocol","1"},{"path","/robot"},{"transport","lan"},{"tls","0"}};
static size_t lengths[] = {1,6,3,1};
esp_netif_t *esp_netif_get_handle_from_ifkey(const char *key)
{ assert(!strcmp(key,"WIFI_STA_DEF")); return station_available ? (esp_netif_t *)&station : NULL; }
esp_err_t esp_netif_get_ip_info(esp_netif_t *n, esp_netif_ip_info_t *info)
{ assert(n); *info=station; return ESP_OK; }
char *esp_ip4addr_ntoa(const esp_ip4_addr_t *a, char *s, int n)
{ return (char *)inet_ntop(AF_INET, &a->addr, s, (socklen_t)n); }
esp_err_t mdns_init(void) { ++initialized; return init_error; }
esp_err_t mdns_query_ptr(const char *s,const char *p,uint32_t t,size_t n,mdns_result_t **r)
{ assert(!strcmp(s,"_ainekio") && !strcmp(p,"_tcp") && t==2500 && n==8); *r=available; return query_error; }
void mdns_query_results_free(mdns_result_t *r) { (void)r; ++freed; }
void test_camera_log(const char *tag, const char *format, ...) { (void)tag; (void)format; }

int main(void)
{
    char endpoints[8][256], one[256]; size_t count=123;
    station.ip.addr=inet_addr("192.168.1.50"); station.netmask.addr=inet_addr("255.255.255.0");
    mdns_ip_addr_t addresses[3]={0};
    addresses[0].addr.u_addr.ip4.addr=inet_addr("192.168.1.10");
    addresses[1].addr.u_addr.ip4.addr=inet_addr("192.168.1.20");
    addresses[2].addr.u_addr.ip4.addr=inet_addr("203.0.113.1");
    mdns_result_t results[3]={0};
    for (unsigned i=0;i<3;++i) {
        results[i]=(mdns_result_t){.port=8790,.txt_count=4,.txt=txt,.txt_value_len=lengths,.addr=&addresses[i]};
        if(i<2)results[i].next=&results[i+1];
    }
    available=results; init_error=ESP_FAIL;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_FAIL && count==0);
    init_error=ESP_OK;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_OK && count==2);
    assert(!strcmp(endpoints[0],"ws://192.168.1.10:8790/robot"));
    assert(!strcmp(endpoints[1],"ws://192.168.1.20:8790/robot"));
    assert(initialized==2 && freed==1);
    assert(ainekio_local_gateway_discover(one,sizeof one)==ESP_ERR_INVALID_STATE && !one[0]);
    addresses[1].addr.u_addr.ip4.addr=addresses[0].addr.u_addr.ip4.addr;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_OK && count==1);
    assert(ainekio_local_gateway_discover(one,sizeof one)==ESP_OK);
    assert(ainekio_local_gateway_discover(one,3)==ESP_ERR_INVALID_SIZE && !one[0]);
    station_available=false;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_NOT_FOUND && count==0);
    station_available=true;
    station.netmask.addr=0;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_NOT_FOUND);
    station.netmask.addr=inet_addr("255.255.255.0");
    for(unsigned i=0;i<4;++i) {
        const char *old=txt[i].value; txt[i].value="wrong";
        assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_NOT_FOUND);
        txt[i].value=old;
    }
    lengths[1]=5;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_NOT_FOUND);
    lengths[1]=6;
    addresses[0].addr.type=addresses[1].addr.type=ESP_IPADDR_TYPE_V6;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_NOT_FOUND);
    addresses[0].addr.type=addresses[1].addr.type=ESP_IPADDR_TYPE_V4;
    addresses[0].addr.u_addr.ip4.addr=addresses[1].addr.u_addr.ip4.addr=station.ip.addr;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_NOT_FOUND);
    addresses[0].addr.u_addr.ip4.addr=inet_addr("192.168.1.10");
    addresses[1].addr.u_addr.ip4.addr=inet_addr("192.168.1.20");
    assert(ainekio_local_gateways_discover(endpoints,1,&count)==ESP_OK && count==1);
    query_error=ESP_ERR_TIMEOUT;
    unsigned before=freed;
    assert(ainekio_local_gateways_discover(endpoints,8,&count)==ESP_ERR_TIMEOUT && count==0 && freed==before+1);
    assert(ainekio_local_gateways_discover(NULL,8,&count)==ESP_ERR_INVALID_ARG);
    assert(ainekio_local_gateways_discover(endpoints,9,&count)==ESP_ERR_INVALID_ARG);
    return 0;
}
