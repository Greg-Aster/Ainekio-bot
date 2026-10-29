#include <assert.h>
#include <math.h>
#include <string.h>
#include "../components/ainekio_p4_media/imu_calibration.c"
#include "../components/ainekio_p4_media/imu.c"
#include "../main/imu_diagnostics.c"

static uint8_t registers[256];
static int64_t time_us;
static unsigned writes,reads,removed,tasks;
static int fail_read,fail_write;
static bool present,task_ok;
static bool stored;
static ainekio_p4_imu_calibration_t saved_calibration;
static size_t saved_size;
static unsigned nvs_writes,nvs_closes;
static esp_err_t open_error,set_error,commit_error;

esp_err_t nvs_open(const char *space,int mode,nvs_handle_t *handle)
{
    assert(!strcmp(space,"p4_imu") && (mode==NVS_READONLY || mode==NVS_READWRITE));
    if (open_error) return open_error;
    *handle=7;return ESP_OK;
}
esp_err_t nvs_get_blob(nvs_handle_t handle,const char *key,void *value,size_t *size)
{
    assert(handle==7 && !strcmp(key,"cal_v1"));
    if (!stored) return ESP_ERR_NVS_NOT_FOUND;
    assert(*size>=saved_size);*size=saved_size;
    memcpy(value,&saved_calibration,saved_size);return ESP_OK;
}
esp_err_t nvs_set_blob(nvs_handle_t handle,const char *key,const void *value,size_t size)
{
    assert(handle==7 && !strcmp(key,"cal_v1") && size==sizeof(saved_calibration));
    ++nvs_writes;if (set_error) return set_error;
    memcpy(&saved_calibration,value,size);stored=true;saved_size=size;return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t handle) { assert(handle==7);return commit_error; }
void nvs_close(nvs_handle_t handle) { assert(handle==7);++nvs_closes; }

const char *esp_err_to_name(esp_err_t e) { return e==ESP_OK ? "ESP_OK" : "ERROR"; }
int64_t esp_timer_get_time(void) { return time_us; }
TickType_t xTaskGetTickCount(void) { return (TickType_t)(time_us/1000); }
void vTaskDelay(TickType_t ticks) { time_us+=(int64_t)ticks*1000; }
void vTaskDelayUntil(TickType_t *wake,TickType_t ticks) { *wake+=ticks;vTaskDelay(ticks); }
BaseType_t xTaskCreate(void (*fn)(void *),const char *name,unsigned stack,void *arg,unsigned priority,void *handle)
{
    assert(fn==acquisition_task && !strcmp(name,"p4_imu") && stack==4096);
    assert(!arg && priority==6 && !handle);++tasks;return task_ok ? pdPASS : 0;
}
esp_err_t i2c_master_probe(i2c_master_bus_handle_t bus,uint16_t address,int timeout)
{ assert(bus==(void *)1 && address==0x6a && timeout==20);return present ? ESP_OK : ESP_ERR_TIMEOUT; }
esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus,const i2c_device_config_t *cfg,i2c_master_dev_handle_t *dev)
{ assert(bus==(void *)1 && cfg->device_address==0x6a && cfg->scl_speed_hz==400000);*dev=(void *)2;return ESP_OK; }
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t dev)
{ assert(dev==(void *)2);++removed;return ESP_OK; }
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t dev,const uint8_t *out,size_t n,uint8_t *in,size_t size,int timeout)
{
    assert(dev==(void *)2 && n==1 && timeout==20);++reads;time_us+=100;
    if (*out==fail_read) return ESP_FAIL;
    memcpy(in,registers+*out,size);return ESP_OK;
}
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t dev,const uint8_t *out,size_t size,int timeout)
{
    assert(dev==(void *)2 && size==2 && timeout==20);++writes;
    if (out[0]==fail_write) { fail_write=-1;return ESP_FAIL; }
    registers[out[0]]=out[1];return ESP_OK;
}
static void setup(void)
{
    memset(registers,0,sizeof(registers));registers[WHO_AM_I]=0x69;
    registers[CTRL3_C]=0x04;registers[STATUS_REG]=3;
    time_us=1000;writes=reads=removed=tasks=0;present=task_ok=true;
    fail_read=fail_write=-1;device=NULL;
    state=(ainekio_p4_imu_status_t){0};published=state;
    gyro_calibration_requested=false;
    stored=false;saved_size=0;nvs_writes=nvs_closes=0;
    open_error=set_error=commit_error=ESP_OK;
}
static void put_axis(unsigned reg,int value)
{ registers[reg]=(unsigned)value&255;registers[reg+1]=((unsigned)value>>8)&255; }
static void initialized(void)
{
    assert(p4_imu_prepare((void *)1)==ESP_OK);
    assert(registers[CTRL1_XL]==0x54 && registers[CTRL2_G]==0x5c && registers[CTRL3_C]==0x44);
    assert(ainekio_p4_imu_start()==ESP_OK && tasks==1);
}
int main(void)
{
    setup();present=false;assert(p4_imu_prepare((void *)1)!=ESP_OK);assert(writes==0);
    setup();registers[WHO_AM_I]=0x6a;assert(p4_imu_prepare((void *)1)==ESP_ERR_NOT_SUPPORTED);
    assert(writes==0 && removed==1 && published.identity==0x6a);
    setup();fail_write=CTRL2_G;assert(p4_imu_prepare((void *)1)!=ESP_OK);
    assert(registers[CTRL1_XL]==0 && registers[CTRL2_G]==0 && registers[CTRL3_C]==4 && removed==1);
    setup();assert(p4_imu_prepare((void *)1)==ESP_OK);task_ok=false;
    assert(ainekio_p4_imu_start()==ESP_ERR_NO_MEM && !published.running);
    setup();initialized();assert(p4_imu_prepare((void *)1)==ESP_ERR_INVALID_STATE);
    assert(ainekio_p4_imu_start()==ESP_ERR_INVALID_STATE && tasks==1);
    put_axis(OUTX_L_G,1000);put_axis(OUTX_L_G+2,-1000);put_axis(OUTX_L_G+10,2049);
    poll_sample();ainekio_p4_imu_status_t s=ainekio_p4_imu_status();
    assert(s.samples==1 && s.attitude.accepted_samples==1 && s.attitude.fresh && s.read_us==100);
    assert(fabsf(s.raw.acceleration_m_s2[2]-9.80665F)<0.005F);
    assert(fabsf(s.raw.angular_rate_rad_s[0]-1.2217305F)<0.00001F);
    assert(fabsf(s.raw.angular_rate_rad_s[1]+1.2217305F)<0.00001F);
    const uint64_t first=s.raw.timestamp_us;
    registers[STATUS_REG]=0;time_us+=5000;poll_sample();
    assert(state.samples==1 && state.no_data_polls==1 && state.raw.timestamp_us==first);
    registers[STATUS_REG]=3;fail_read=OUTX_L_G;time_us+=25000;poll_sample();
    s=ainekio_p4_imu_status();assert(s.samples==1 && s.io_errors==1 && !s.attitude.fresh);
    assert(s.raw.timestamp_us==first && s.attitude.timestamp_us==first);
    fail_read=-1;poll_sample();assert(state.samples==2 && state.attitude.gap_restarts==1);
    assert(ainekio_p4_imu_status().attitude.fresh && state.last_error==ESP_OK);
    const unsigned before_reads=reads,before_writes=writes;
    char *args[]={"imu","sample"};assert(ainekio_p4_imu_command(2,args)==0);
    assert(reads==before_reads && writes==before_writes); /* console does no bus I/O */
    assert(!ainekio_p4_imu_status().attitude.fresh); /* printing does not refresh data */
    const uint8_t negative_counts[12]={0,0x80,0xff,0xff};
    ainekio_imu_sample_t decoded;
    ainekio_imu_lsm6ds3_decode(123,negative_counts,&decoded);
    assert(decoded.timestamp_us==123);
    assert(decoded.angular_rate_rad_s[0]==-32768*AINEKIO_LSM6DS3_GYRO_LSB_RAD_S);
    assert(decoded.angular_rate_rad_s[1]==-AINEKIO_LSM6DS3_GYRO_LSB_RAD_S);

    /* Persistent calibration: reuse estimator validation; storage failures
     * never claim success or mutate the active acquisition configuration. */
    ainekio_p4_imu_calibration_t cal={.sensor_to_body={-1,0,0,0,-1,0,0,0,1}};
    setup();initialized();assert(!state.calibration_applied);
    cal.gyro_bias_rad_s[0]=100*(0.07F*0.017453292519943295F);
    cal.gyro_bias_rad_s[1]=-200*(0.07F*0.017453292519943295F);
    cal.gyro_bias_rad_s[2]=50*(0.07F*0.017453292519943295F);
    assert(ainekio_p4_imu_calibration_save(&cal)==ESP_OK);
    assert(nvs_writes==1 && !state.calibration_applied && estimator.config.gyro_bias_rad_s[0]==0);
    ainekio_p4_imu_calibration_t loaded;bool found;
    assert(ainekio_p4_imu_calibration_load(&loaded,&found)==ESP_OK && found);
    assert(!memcmp(&cal,&loaded,sizeof(cal)));
    /* Reboot acquisition while retaining mock flash contents. */
    device=NULL;state=(ainekio_p4_imu_status_t){0};published=state;tasks=0;
    initialized();assert(state.calibration_applied);
    put_axis(OUTX_L_G,100);put_axis(OUTX_L_G+2,-200);put_axis(OUTX_L_G+4,50);
    put_axis(OUTX_L_G+6,200);put_axis(OUTX_L_G+8,-400);put_axis(OUTX_L_G+10,2049);
    poll_sample();s=ainekio_p4_imu_status();
    for (unsigned i=0;i<3;++i) assert(fabsf(s.attitude.angular_rate_rad_s[i])<0.000001F);
    assert(s.attitude.acceleration_m_s2[0]==-s.raw.acceleration_m_s2[0]);
    assert(s.attitude.acceleration_m_s2[1]==-s.raw.acceleration_m_s2[1]);
    assert(s.attitude.acceleration_m_s2[2]==s.raw.acceleration_m_s2[2]);
    cal.sensor_to_body[4]=1; /* reflection, not a proper rotation */
    assert(ainekio_p4_imu_calibration_save(&cal)==ESP_ERR_INVALID_ARG && nvs_writes==1);
    cal.sensor_to_body[4]=-1;cal.gyro_bias_rad_s[0]=NAN;
    assert(ainekio_p4_imu_calibration_save(&cal)==ESP_ERR_INVALID_ARG && nvs_writes==1);
    cal=loaded;set_error=ESP_FAIL;
    assert(ainekio_p4_imu_calibration_save(&cal)==ESP_FAIL);
    set_error=ESP_OK;commit_error=ESP_FAIL;
    assert(ainekio_p4_imu_calibration_save(&cal)==ESP_FAIL);
    assert(!memcmp(&state.calibration,&loaded,sizeof(loaded)));
    commit_error=ESP_OK;saved_size--;
    assert(ainekio_p4_imu_calibration_load(&cal,&found)==ESP_ERR_NVS_INVALID_LENGTH && !found);
    open_error=ESP_FAIL;
    assert(ainekio_p4_imu_calibration_save(&loaded)==ESP_FAIL);
    setup();char *set_args[]={"imu","calibration","set","-1","0","0","0","-1","0","0","0","1","0.01","-0.02","0.03"};
    assert(ainekio_p4_imu_command(15,set_args)==0);
    assert(saved_calibration.gyro_bias_rad_s[1]==-0.02F && !state.calibration_applied);
    set_args[3]="1junk";assert(ainekio_p4_imu_command(15,set_args)==1 && nvs_writes==1);
    /* Explicit bias acquisition preserves mounting and the AHRS session.
     * It consumes unique hardware samples, not repeated status reads. */
    setup();assert(ainekio_p4_imu_calibrate_gyro()==ESP_ERR_INVALID_STATE);
    cal=(ainekio_p4_imu_calibration_t){.sensor_to_body={-1,0,0,0,-1,0,0,0,1}};
    assert(ainekio_p4_imu_calibration_save(&cal)==ESP_OK);initialized();
    put_axis(OUTX_L_G+10,2049);
    assert(ainekio_p4_imu_calibrate_gyro()==ESP_OK);
    const unsigned configured_writes=writes;
    for(unsigned i=0;i<AINEKIO_GYRO_CALIBRATION_SAMPLES;i++) {
        put_axis(OUTX_L_G,10+(int)(i%2)*2);
        put_axis(OUTX_L_G+2,-20);put_axis(OUTX_L_G+4,30);
        time_us+=4800;poll_sample();
        assert(state.gyro_calibration.samples==i+1);
        if(i==20) {
            registers[STATUS_REG]=0;poll_sample();registers[STATUS_REG]=3;
            (void)ainekio_p4_imu_status();
            assert(state.gyro_calibration.samples==21);
        }
    }
    const float unit=0.07F*0.017453292519943295F;
    assert(state.gyro_calibration.phase==AINEKIO_GYRO_SAVED && nvs_writes==2);
    assert(fabsf(saved_calibration.gyro_bias_rad_s[0]-11*unit)<1e-7F);
    assert(fabsf(state.gyro_calibration.deviation_rad_s[0]-unit*sqrtf(256.F/255.F))<1e-7F);
    assert(!memcmp(state.calibration.sensor_to_body,cal.sensor_to_body,sizeof cal.sensor_to_body));
    put_axis(OUTX_L_G,11);time_us+=4800;poll_sample();
    for(unsigned i=0;i<3;i++)assert(fabsf(state.attitude.angular_rate_rad_s[i])<1e-7F);
    assert(state.attitude.accepted_samples==257 && writes==configured_writes && tasks==1);
    const ainekio_p4_imu_calibration_t active=state.calibration;
    commit_error=ESP_FAIL;assert(ainekio_p4_imu_calibrate_gyro()==ESP_OK);
    put_axis(OUTX_L_G,40);
    for(unsigned i=0;i<AINEKIO_GYRO_CALIBRATION_SAMPLES;i++){time_us+=4800;poll_sample();}
    assert(state.gyro_calibration.phase==AINEKIO_GYRO_ERROR && state.gyro_calibration.error==ESP_FAIL);
    assert(!memcmp(&state.calibration,&active,sizeof active));
    assert(!memcmp(estimator.config.gyro_bias_rad_s,active.gyro_bias_rad_s,sizeof active.gyro_bias_rad_s));
    puts("IMU: stationary bias sampling, live application, unchanged mounting, persistence and failure reporting passed");
    return 0;
}
