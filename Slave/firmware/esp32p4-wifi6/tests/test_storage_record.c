#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <setjmp.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include "storage_port.h"
static void record_free(void *);
#define free record_free
#include "../main/storage.c"
#undef free

struct test_queue { request_t entries[4]; size_t item_size; unsigned count; } fixture_queue;
static jmp_buf worker_boundary;
static bool in_worker, allocation_fails, queue_full, maintenance_call, drained_ready;
static unsigned unmounts;
static void drain(void);
static unsigned outstanding, freed;
static sdmmc_card_t fixture_card;

static void record_free(void *p) { if(p){assert(outstanding);--outstanding;++freed;free(p);} }
void *heap_caps_malloc(size_t size,unsigned flags) {
    assert(flags==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(allocation_fails)return NULL;
    void *p=malloc(size);if(p)++outstanding;return p;
}
BaseType_t xQueueSend(QueueHandle_t q,const void *p,TickType_t ticks) {
    assert((!ticks || maintenance_call) && q==&fixture_queue);
    if(queue_full || q->count==4)return 0;
    memcpy(&q->entries[q->count++],p,q->item_size);return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t q,void *p,TickType_t ticks) {
    assert(q==&fixture_queue);
    if(q->count){memcpy(p,&q->entries[0],q->item_size);memmove(q->entries,q->entries+1,--q->count*sizeof(q->entries[0]));return pdTRUE;}
    if(in_worker && ticks==portMAX_DELAY)longjmp(worker_boundary,1);
    return 0;
}
BaseType_t xQueueOverwrite(QueueHandle_t q,const void *p){(void)q;(void)p;assert(false);return 0;}
BaseType_t xSemaphoreTake(SemaphoreHandle_t h,TickType_t ticks){
    if(!in_worker && !maintenance_call)assert(!ticks);
    if(h==drained) {
        if(ticks && !drained_ready)drain();
        bool ready=drained_ready;drained_ready=false;return ready?pdTRUE:0;
    }
    return pdTRUE;
}
BaseType_t xSemaphoreGive(SemaphoreHandle_t h){if(h==drained)drained_ready=true;return pdTRUE;}
TickType_t xTaskGetTickCount(void){return 0;}
void vTaskDelay(TickType_t ticks){(void)ticks;}
int64_t esp_timer_get_time(void){return 1234000;}
esp_err_t esp_vfs_fat_info(const char *name,uint64_t *total,uint64_t *available){(void)name;*total=*available=1000000;return ESP_OK;}
bool ainekio_p4_network_initialized(void){return false;}
ainekio_p4_system_status_t ainekio_p4_system_status(void){return (ainekio_p4_system_status_t){0};}
void ainekio_p4_log_stage(const char *s){(void)s;}
esp_err_t sd_pwr_ctrl_del_on_chip_ldo(sd_pwr_ctrl_handle_t h){(void)h;assert(false);return ESP_FAIL;}
esp_err_t sd_pwr_ctrl_new_on_chip_ldo(const sd_pwr_ctrl_ldo_config_t *c,sd_pwr_ctrl_handle_t *h){(void)c;(void)h;assert(false);return ESP_FAIL;}
esp_err_t esp_vfs_fat_sdcard_unmount(const char *name,sdmmc_card_t *c){assert(!strcmp(name,MOUNT) && c==&fixture_card);++unmounts;return ESP_OK;}
esp_err_t esp_vfs_fat_sdmmc_mount(const char *name,const sdmmc_host_t *h,const sdmmc_slot_config_t *s,const esp_vfs_fat_mount_config_t *v,sdmmc_card_t **c){(void)name;(void)h;(void)s;(void)v;(void)c;assert(false);return ESP_FAIL;}
esp_err_t sdmmc_host_deinit_slot(int slot){(void)slot;assert(false);return ESP_FAIL;}
esp_err_t gpio_set_level(int pin,int level){(void)pin;(void)level;assert(false);return ESP_FAIL;}
esp_err_t gpio_config(const gpio_config_t *c){(void)c;assert(false);return ESP_FAIL;}

static void drain(void) {
    in_worker=true;
    if(!setjmp(worker_boundary))storage_task(NULL);
    in_worker=false;
    assert(!outstanding && !fixture_queue.count);
}
static void verify(FILE *file,const void *payload,size_t size) {
    rewind(file);uint8_t encoded[AINEKIO_SD_RECORD_HEADER_BYTES],copy[AINEKIO_SD_RECORD_MAX_PAYLOAD];
    assert(fread(encoded,1,sizeof encoded,file)==sizeof encoded);
    ainekio_sd_record_header_t header;assert(ainekio_sd_record_decode_header(encoded,&header));
    assert(header.type==1 && header.payload_length==size && header.timestamp_ms==1234);
    assert(fread(copy,1,size,file)==size && !memcmp(copy,payload,size));
    assert(header.crc32==ainekio_sd_record_crc(1,size,1234,copy));
}
int main(void) {
    queue=&fixture_queue;fixture_queue.item_size=sizeof(request_t);
    enqueue_lock=io_lock=(void *)1;card=&fixture_card;
    status.mounted=true;
    uint8_t payload[AINEKIO_SD_RECORD_MAX_PAYLOAD];
    for(size_t n=0;n<sizeof payload;n++)payload[n]=(uint8_t)n;
    const size_t sizes[]={0,1217,sizeof payload};
    for(unsigned i=0;i<sizeof sizes/sizeof sizes[0];i++) {
        const size_t size=sizes[i];
        uint8_t expected[sizeof payload];memcpy(expected,payload,sizeof payload);
        log_file=tmpfile();assert(log_file);
        assert(ainekio_p4_storage_record(1,payload,size)==ESP_OK);
        assert(outstanding==(size?1U:0U) && fixture_queue.count==1);
        payload[0]^=1;payload[sizeof payload-1]^=1;
        assert(!memcmp(fixture_queue.entries[0].payload,expected,size));
        drain();verify(log_file,expected,size);fclose(log_file);log_file=NULL;
    }
    assert(sizeof(request_t)<256); /* Payload is not copied onto firmware task stacks. */
    unsigned lost=status.dropped_records;
    allocation_fails=true;assert(ainekio_p4_storage_record(1,payload,1217)==ESP_ERR_NO_MEM);allocation_fails=false;
    assert(!outstanding && status.dropped_records==++lost && status.last_error==ESP_ERR_NO_MEM);
    queue_full=true;assert(ainekio_p4_storage_record(1,payload,1217)==ESP_ERR_TIMEOUT);queue_full=false;
    assert(!outstanding && status.dropped_records==++lost && status.last_error==ESP_ERR_TIMEOUT);
    assert(ainekio_p4_storage_record(1,payload,sizeof payload+1)==ESP_ERR_INVALID_SIZE);
    assert(!outstanding && status.dropped_records==++lost && status.last_error==ESP_ERR_INVALID_SIZE);
    assert(ainekio_p4_storage_record(1,payload,1217)==ESP_OK);
    card=NULL;drain();assert(status.last_error==ESP_ERR_INVALID_STATE);
    assert(freed==4);
    card=&fixture_card;status.mounted=true;drained=(void *)3;
    log_file=tmpfile();assert(log_file);
    FILE *retained=fdopen(dup(fileno(log_file)),"rb");assert(retained);
    assert(ainekio_p4_storage_record(1,payload,1217)==ESP_OK);
    maintenance_call=true;
    assert(ainekio_p4_storage_suspend(100)==ESP_OK);
    maintenance_call=false;
    assert(!outstanding && !card && !log_file && !status.mounted && unmounts==1);
    verify(retained,payload,1217);fclose(retained);
    assert(freed==5);
    puts("Complete status records, CRC, bounded queue/stack ownership and allocation/admission/worker failure release passed.");
    return 0;
}
