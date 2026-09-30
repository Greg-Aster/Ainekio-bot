/* Production NVS loader with in-memory NVS and scheduler boundaries. */
#include <assert.h>
#include <string.h>
#define portMAX_DELAY 0xffffffffu
#include "../main/config.c"
static struct { char key[16]; unsigned char data[4096]; size_t size; } records[8];
static unsigned count, commits;
static bool fail_commit;
static ainekio_pca9685_t driver;
static void put(const char *key,const void *data,size_t size) {
    unsigned i=0; for(;i<count && strcmp(records[i].key,key);++i){}
    if(i==count){assert(count<8);++count;strcpy(records[i].key,key);}
    assert(size<=sizeof records[i].data);memcpy(records[i].data,data,size);records[i].size=size;
}
esp_err_t nvs_open(const char *n,int mode,nvs_handle_t *h){(void)n;(void)mode;*h=1;return ESP_OK;}
esp_err_t nvs_get_blob(nvs_handle_t h,const char *key,void *data,size_t *size){
    (void)h;for(unsigned i=0;i<count;++i)if(!strcmp(records[i].key,key)){
        if(*size<records[i].size)return ESP_ERR_NVS_INVALID_LENGTH;
        memcpy(data,records[i].data,records[i].size);*size=records[i].size;return ESP_OK;
    }return ESP_ERR_NVS_NOT_FOUND;
}
esp_err_t nvs_set_blob(nvs_handle_t h,const char *key,const void *data,size_t size){(void)h;if(!fail_commit)put(key,data,size);return ESP_OK;}
esp_err_t nvs_commit(nvs_handle_t h){(void)h;++commits;return fail_commit?ESP_FAIL:ESP_OK;}
esp_err_t nvs_erase_key(nvs_handle_t h,const char *key){(void)h;(void)key;return ESP_ERR_NVS_NOT_FOUND;}
void nvs_close(nvs_handle_t h){(void)h;}
void *xSemaphoreCreateMutex(void){return (void *)1;}
int xSemaphoreTake(void *p,unsigned t){(void)p;(void)t;return 1;}
int xSemaphoreGive(void *p){(void)p;return 1;}
ainekio_pca9685_t *ainekio_p4_output(void){return &driver;}
ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *d){return d->state;}
bool ainekio_pca_pulse_valid(const ainekio_pca9685_t *d,uint16_t p){(void)d;return p>=3 && p<=19986;}
ainekio_p4_system_status_t ainekio_p4_system_status(void) { return (ainekio_p4_system_status_t){0}; }
esp_err_t ainekio_p4_system_restart(void) { return ESP_OK; }
int main(void) {
    /* Import the installed legacy dual-slot record without rewriting it. */
    ainekio_config_record_t legacy = {.schema_version=AINEKIO_NVS_SCHEMA_VERSION, .generation=3, .complete=true};
    strcpy(legacy.robot_id,"robot"); strcpy(legacy.robot_token,"original-token");
    strcpy(legacy.wifi_ssid,"Home"); strcpy(legacy.wifi_psk,"original-wifi");
    strcpy(legacy.endpoint_url,"ws://home:8790/robot"); strcpy(legacy.transport_mode,"local");
    ainekio_config_meta_t meta={.schema_version=AINEKIO_NVS_SCHEMA_VERSION,.active_slot=AINEKIO_CONFIG_SLOT_A};
    put("slot_a",&legacy,sizeof legacy); put("meta",&meta,sizeof meta);
    assert(ainekio_p4_config_init()==ESP_OK && commits==0);
    assert(!strcmp(ainekio_p4_config()->robot_token,"original-token"));
    ainekio_robot_settings_command_t c={.operation=AINEKIO_SETTINGS_NETWORK,.index=1,.has_wifi_password=true};
    strcpy(c.ssid,"Hotspot");strcpy(c.wifi_password,"hotspot-password");strcpy(c.endpoint,"ws://10.42.77.1:8790/robot");
    fail_commit=true;
    assert(ainekio_p4_settings_change(&c)!=ESP_OK && ainekio_p4_saved_settings().revision==0);
    fail_commit=false;
    assert(ainekio_p4_settings_change(&c)==ESP_OK && ainekio_p4_saved_settings().revision==1);
    assert(ainekio_p4_boot_settings()->revision==0); /* save doesn't replace running identity */
    c=(ainekio_robot_settings_command_t){.operation=AINEKIO_SETTINGS_SECURITY,.revision=1,.has_robot_token=true,.has_setup_password=true};
    strcpy(c.robot_token,"replacement-token");strcpy(c.setup_password,"setup-password");
    assert(ainekio_p4_settings_change(&c)==ESP_OK);
    assert(!strcmp(ainekio_p4_config()->robot_token,"original-token"));
    assert(ainekio_p4_config_init()==ESP_OK);
    assert(!strcmp(ainekio_p4_config()->robot_token,"replacement-token"));
    assert(!strcmp(ainekio_p4_boot_settings()->networks[1].password,"hotspot-password"));
    assert(!strcmp(ainekio_p4_boot_settings()->setup_password,"setup-password"));
    assert(ainekio_p4_config_reset_network()==ESP_OK);
    assert(ainekio_p4_config_init()==ESP_OK);
    assert(ainekio_p4_network_next(ainekio_p4_boot_settings(),-1)==-1);
    assert(!strcmp(ainekio_p4_config()->robot_token,"replacement-token"));
    /* Portal/serial recovery must update the new owner, never revive legacy credentials. */
    legacy=*ainekio_p4_config();strcpy(legacy.wifi_ssid,"Recovered");strcpy(legacy.wifi_psk,"recovered-password");
    strcpy(legacy.endpoint_url,"ws://recovered:8790/robot");
    assert(ainekio_p4_config_save_record(&legacy)==ESP_OK);
    assert(ainekio_p4_config_init()==ESP_OK);
    assert(!strcmp(ainekio_p4_config()->wifi_ssid,"Recovered"));
    assert(!strcmp(ainekio_p4_config()->robot_token,"replacement-token"));
    return 0;
}
