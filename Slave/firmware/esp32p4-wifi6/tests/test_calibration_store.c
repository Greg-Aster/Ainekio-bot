/* Production NVS loader with in-memory NVS and scheduler boundaries. */
#include <assert.h>
#include "ainekio/v2_walk.h"
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
static void boot(void){memset(&calibration,0,sizeof calibration);memset(&committed,0,sizeof committed);assert(ainekio_p4_config_init()==ESP_OK);}
int main(void){
    boot();assert(calibration.valid && calibration.dirty && !calibration.saved && !calibration.profile_confirmed && commits==0);
    assert(calibration.joints[1].home_us==1650 && calibration.joints[1].home_cd==117);
    assert(sizeof(ainekio_p4_joint_config_t)==12 && sizeof(ainekio_p4_joint_record_t)==148);
    ainekio_p4_joint_config_t joint=calibration.joints[1];
    joint.home_us=3000;joint.home_cd=-1200;joint.us_per_degree=10;joint.invert=1;
    assert(ainekio_p4_calibration_stage(1,&joint)==ESP_OK && calibration.dirty);
    fail_commit=true;assert(ainekio_p4_calibration_save()!=ESP_OK && !calibration.saved);
    fail_commit=false;assert(ainekio_p4_calibration_save()==ESP_OK);
    assert(calibration.saved && calibration.profile_confirmed && !calibration.dirty);
    boot();assert(calibration.saved && calibration.profile_confirmed);
    assert(!memcmp(&calibration.joints[1],&joint,sizeof joint));
    uint16_t pulses[12];assert(ainekio_p4_home_pulses(pulses) && pulses[1]==3000);
    ainekio_p4_joint_record_t stored;size_t size=sizeof stored;
    assert(nvs_get_blob(1,"joint_mapping",&stored,&size)==ESP_OK && stored.version==1 && size==148);
    joint.channel=0;assert(ainekio_p4_calibration_stage(1,&joint)==ESP_ERR_INVALID_ARG);
    joint=calibration.joints[1];joint.home_us=19987;
    assert(ainekio_p4_calibration_stage(1,&joint)==ESP_ERR_INVALID_ARG);
    assert(calibration.joints[1].home_us==3000);
    assert(ainekio_p4_joint_defaults(calibration.joints));
    calibration.valid=calibration.profile_confirmed=true;
    ainekio_v2_frame_t frame={0};
    for(unsigned i=0;i<12;i++)frame.position[i]=calibration.joints[i].home_cd;
    calibration.joints[0].us_per_degree=10;
    calibration.joints[0].home_us=1600;
    frame.position[0]=13000;
    assert(ainekio_p4_frame_pulses(&frame,pulses) && pulses[0]==2900);
    frame.position[0]=-13000;
    assert(ainekio_p4_frame_pulses(&frame,pulses) && pulses[0]==300);
    frame.position[0]=183870;
    assert(!ainekio_p4_frame_pulses(&frame,pulses));
    for(unsigned i=0;i<12;i++)assert(!pulses[i]);
    boot();ainekio_p4_joint_record_t preserved=committed;
    assert(ainekio_p4_motion_rate()==2.F && !ainekio_p4_motion_rate_saved());
    driver.state.armed=true;assert(ainekio_p4_motion_rate_save(1.5F)==ESP_ERR_INVALID_STATE);
    driver.state.armed=false;assert(ainekio_p4_motion_rate_save(0.F)==ESP_ERR_INVALID_ARG);
    fail_commit=true;assert(ainekio_p4_motion_rate_save(1.5F)!=ESP_OK);
    assert(ainekio_p4_motion_rate()==2.F && !ainekio_p4_motion_rate_saved());
    fail_commit=false;assert(ainekio_p4_motion_rate_save(4.5F)==ESP_OK);
    boot();assert(ainekio_p4_motion_rate()==4.5F && ainekio_p4_motion_rate_saved());
    assert(!memcmp(&preserved,&committed,sizeof committed));
    assert(!ainekio_p4_joint_speed_saved());
    driver.state.armed=true;assert(ainekio_p4_joint_speed_save(900.F)==ESP_ERR_INVALID_STATE);
    driver.state.armed=false;assert(ainekio_p4_joint_speed_save(0.F)==ESP_ERR_INVALID_ARG);
    fail_commit=true;assert(ainekio_p4_joint_speed_save(900.F)!=ESP_OK);
    assert(!ainekio_p4_joint_speed_saved());
    fail_commit=false;assert(ainekio_p4_joint_speed_save(2000.F)==ESP_OK);
    boot();assert(ainekio_p4_joint_speed_saved() && ainekio_v2_gait_joint_speed_limit()==2000.);
    assert(ainekio_p4_motion_rate()==4.5F && !memcmp(&preserved,&committed,sizeof committed));
    float invalid_limit=0;put("joint_speed",&invalid_limit,sizeof invalid_limit);
    boot();assert(!ainekio_p4_joint_speed_saved());
    assert(fabs(ainekio_v2_gait_joint_speed_limit()-ainekio_v2_joint_speed_default())<.001);
    float invalid_rate=0;put("motion_rate",&invalid_rate,sizeof invalid_rate);
    boot();assert(ainekio_p4_motion_rate()==2.F && !ainekio_p4_motion_rate_saved());
    assert(!memcmp(&preserved,&committed,sizeof committed));
    count=0;stored.version=99;put("joint_mapping",&stored,sizeof stored);boot();
    assert(!calibration.valid && !calibration.saved);
    count=0;stored.version=1;put("joint_mapping",&stored,sizeof stored-1);boot();
    assert(!calibration.valid && !calibration.saved);
    puts("Compact calibration persistence, invalid records, commit failure and hardware pulse capacity passed");
    return 0;
}
