#include "display.h"
#include "face_timeline.h"
#include "system.h"
#include "network.h"
#include "controller.h"
#include "board.h"
#include "ainekio/face.h"
#include "ainekio/p4_media.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "esp_rom_sys.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static atomic_bool ready;
static atomic_uint shown_face, frames, render_max_us;
static portMUX_TYPE selection_lock=portMUX_INITIALIZER_UNLOCKED;
static ainekio_p4_face_selection_t selection;
#if CONFIG_AINEKIO_LCD_ENABLED
/* Four-wire SSD1306 backend selected by the firmware display configuration. */
enum { OLED_SCL=20, OLED_SDA=21, OLED_WIDTH=128, OLED_HEIGHT=64 };
static uint16_t *pixels;
static uint8_t mono[OLED_WIDTH*OLED_HEIGHT/8];
static char oled_rows[48][22];
#endif

bool ainekio_p4_display_ready(void){return atomic_load(&ready);}
const char *ainekio_p4_display_face(void){return ainekio_face_name(atomic_load(&shown_face));}
void ainekio_p4_display_restore(void)
{
    portENTER_CRITICAL(&selection_lock);selection.active=false;portEXIT_CRITICAL(&selection_lock);
}
esp_err_t ainekio_p4_display_expression(const char *name)
{
    if(!name || strlen(name)>AINEKIO_ASSET_NAME_MAX)return ESP_ERR_INVALID_ARG;
    ainekio_face_selection_t request={0};
    strcpy(request.expression,name);
    return ainekio_p4_display_select(&request);
}
esp_err_t ainekio_p4_display_select(const ainekio_face_selection_t *request)
{
    if(!atomic_load(&ready))return ESP_ERR_INVALID_STATE;
    const ainekio_p4_body_status_t body=ainekio_p4_body_status();
    portENTER_CRITICAL(&selection_lock);
    const bool found=ainekio_p4_face_select(&selection,request,body.face_revision,esp_timer_get_time()/1000);
    portEXIT_CRITICAL(&selection_lock);
    return found ? ESP_OK : ESP_ERR_NOT_FOUND;
}
#if CONFIG_AINEKIO_LCD_ENABLED
static void i2c_delay(void){esp_rom_delay_us(2);}
static void i2c_start(void)
{
    gpio_set_level(OLED_SDA,1);gpio_set_level(OLED_SCL,1);i2c_delay();
    gpio_set_level(OLED_SDA,0);i2c_delay();gpio_set_level(OLED_SCL,0);
}
static void i2c_stop(void)
{
    gpio_set_level(OLED_SDA,0);i2c_delay();gpio_set_level(OLED_SCL,1);
    i2c_delay();gpio_set_level(OLED_SDA,1);i2c_delay();
}
static bool i2c_byte(uint8_t value)
{
    for(int bit=7;bit>=0;--bit){
        gpio_set_level(OLED_SDA,(value>>bit)&1);i2c_delay();
        gpio_set_level(OLED_SCL,1);i2c_delay();gpio_set_level(OLED_SCL,0);
    }
    gpio_set_level(OLED_SDA,1);i2c_delay();gpio_set_level(OLED_SCL,1);
    i2c_delay();const bool ack=!gpio_get_level(OLED_SDA);
    gpio_set_level(OLED_SCL,0);return ack;
}
static esp_err_t oled_packet(uint8_t control,const uint8_t *data,size_t size)
{
    i2c_start();
    if(!i2c_byte(0x78)||!i2c_byte(control)){i2c_stop();return ESP_ERR_NOT_FOUND;}
    for(size_t i=0;i<size;++i)
        if(!i2c_byte(data[i])){i2c_stop();return ESP_ERR_INVALID_RESPONSE;}
    i2c_stop();return ESP_OK;
}
static esp_err_t oled_cmd(uint8_t command)
{
    return oled_packet(0x00,&command,1);
}
static const uint8_t ainekio_oled_font[][5] = {
    {0x00,0x00,0x00,0x00,0x00},{0x00,0x00,0x5f,0x00,0x00},
    {0x00,0x07,0x00,0x07,0x00},{0x14,0x7f,0x14,0x7f,0x14},
    {0x24,0x2a,0x7f,0x2a,0x12},{0x23,0x13,0x08,0x64,0x62},
    {0x36,0x49,0x55,0x22,0x50},{0x00,0x05,0x03,0x00,0x00},
    {0x00,0x1c,0x22,0x41,0x00},{0x00,0x41,0x22,0x1c,0x00},
    {0x14,0x08,0x3e,0x08,0x14},{0x08,0x08,0x3e,0x08,0x08},
    {0x00,0x50,0x30,0x00,0x00},{0x08,0x08,0x08,0x08,0x08},
    {0x00,0x60,0x60,0x00,0x00},{0x20,0x10,0x08,0x04,0x02},
    {0x3e,0x51,0x49,0x45,0x3e},{0x00,0x42,0x7f,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46},{0x21,0x41,0x45,0x4b,0x31},
    {0x18,0x14,0x12,0x7f,0x10},{0x27,0x45,0x45,0x45,0x39},
    {0x3c,0x4a,0x49,0x49,0x30},{0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36},{0x06,0x49,0x49,0x29,0x1e},
    {0x00,0x36,0x36,0x00,0x00},{0x00,0x56,0x36,0x00,0x00},
    {0x08,0x14,0x22,0x41,0x00},{0x14,0x14,0x14,0x14,0x14},
    {0x00,0x41,0x22,0x14,0x08},{0x02,0x01,0x51,0x09,0x06},
    {0x32,0x49,0x79,0x41,0x3e},{0x7e,0x11,0x11,0x11,0x7e},
    {0x7f,0x49,0x49,0x49,0x36},{0x3e,0x41,0x41,0x41,0x22},
    {0x7f,0x41,0x41,0x22,0x1c},{0x7f,0x49,0x49,0x49,0x41},
    {0x7f,0x09,0x09,0x09,0x01},{0x3e,0x41,0x49,0x49,0x7a},
    {0x7f,0x08,0x08,0x08,0x7f},{0x00,0x41,0x7f,0x41,0x00},
    {0x20,0x40,0x41,0x3f,0x01},{0x7f,0x08,0x14,0x22,0x41},
    {0x7f,0x40,0x40,0x40,0x40},{0x7f,0x02,0x0c,0x02,0x7f},
    {0x7f,0x04,0x08,0x10,0x7f},{0x3e,0x41,0x41,0x41,0x3e},
    {0x7f,0x09,0x09,0x09,0x06},{0x3e,0x41,0x51,0x21,0x5e},
    {0x7f,0x09,0x19,0x29,0x46},{0x46,0x49,0x49,0x49,0x31},
    {0x01,0x01,0x7f,0x01,0x01},{0x3f,0x40,0x40,0x40,0x3f},
    {0x1f,0x20,0x40,0x20,0x1f},{0x3f,0x40,0x38,0x40,0x3f},
    {0x63,0x14,0x08,0x14,0x63},{0x07,0x08,0x70,0x08,0x07},
    {0x61,0x51,0x49,0x45,0x43},{0x00,0x7f,0x41,0x41,0x00},
    {0x02,0x04,0x08,0x10,0x20},{0x00,0x41,0x41,0x7f,0x00},
    {0x04,0x02,0x01,0x02,0x04},{0x40,0x40,0x40,0x40,0x40},
    {0x00,0x01,0x02,0x04,0x00},{0x20,0x54,0x54,0x54,0x78},
    {0x7f,0x48,0x44,0x44,0x38},{0x38,0x44,0x44,0x44,0x20},
    {0x38,0x44,0x44,0x48,0x7f},{0x38,0x54,0x54,0x54,0x18},
    {0x08,0x7e,0x09,0x01,0x02},{0x0c,0x52,0x52,0x52,0x3e},
    {0x7f,0x08,0x04,0x04,0x78},{0x00,0x44,0x7d,0x40,0x00},
    {0x20,0x40,0x44,0x3d,0x00},{0x7f,0x10,0x28,0x44,0x00},
    {0x00,0x41,0x7f,0x40,0x00},{0x7c,0x04,0x18,0x04,0x78},
    {0x7c,0x08,0x04,0x04,0x78},{0x38,0x44,0x44,0x44,0x38},
    {0x7c,0x14,0x14,0x14,0x08},{0x08,0x14,0x14,0x18,0x7c},
    {0x7c,0x08,0x04,0x04,0x08},{0x48,0x54,0x54,0x54,0x20},
    {0x04,0x3f,0x44,0x40,0x20},{0x3c,0x40,0x40,0x20,0x7c},
    {0x1c,0x20,0x40,0x20,0x1c},{0x3c,0x40,0x30,0x40,0x3c},
    {0x44,0x28,0x10,0x28,0x44},{0x0c,0x50,0x50,0x50,0x3c},
    {0x44,0x64,0x54,0x4c,0x44},{0x00,0x08,0x36,0x41,0x00},
    {0x00,0x00,0x7f,0x00,0x00},{0x00,0x41,0x36,0x08,0x00},
    {0x08,0x04,0x08,0x10,0x08},
};
static void oled_text(char rows[48][22],unsigned *count,const char *value)
{
    const size_t length=strlen(value);
    if(!length)return;
    for(size_t start=0;start<length && *count<48;start+=21){
        const size_t span=length-start<21 ? length-start : 21;
        memcpy(rows[*count],value+start,span);
        rows[(*count)++][span]=0;
    }
}
static void oled_status(const ainekio_connection_page_t *page,uint64_t elapsed)
{
    memset(oled_rows,0,sizeof(oled_rows));
    unsigned count=0;
    oled_text(oled_rows,&count,page->heading);
    for(unsigned i=0;i<AINEKIO_SCREEN_LINES;++i)oled_text(oled_rows,&count,page->lines[i]);
    oled_text(oled_rows,&count,page->footer);
    const unsigned windows=(count+7)/8;
    const unsigned first=windows ? ((elapsed/4000)%windows)*8 : 0;
    for(unsigned row=0;row<8 && first+row<count;++row){
        const char *line=oled_rows[first+row];
        for(unsigned col=0;line[col];++col){
            unsigned ch=(unsigned char)line[col];
            if(ch<32||ch>126)ch='?';
            for(unsigned pixel=0;pixel<5;++pixel)
                mono[row*OLED_WIDTH+col*6+pixel]=ainekio_oled_font[ch-32][pixel];
        }
    }
}
static esp_err_t draw(const ainekio_connection_page_t *page,uint64_t elapsed)
{
    memset(mono,0,sizeof(mono));
    if(!page->face_visible)oled_status(page,elapsed);
    else for(int y=0;y<OLED_HEIGHT;++y){
        const int sy=y*AINEKIO_FACE_HEIGHT/OLED_HEIGHT;
        for(int x=0;x<OLED_WIDTH;++x){
            const int sx=x*AINEKIO_FACE_WIDTH/OLED_WIDTH;
            unsigned brightest=0;
            for(int dy=0;dy<2;++dy)for(int dx=0;dx<2;++dx){
                const uint16_t p=pixels[(sy+dy)*AINEKIO_FACE_WIDTH+sx+dx];
                const unsigned value=((p>>11)&31)*8+((p>>5)&63)*8+(p&31)*8;
                if(value>brightest)brightest=value;
            }
            if(brightest>100)mono[(y/8)*OLED_WIDTH+x]|=1U<<(y%8);
        }
    }
    static const uint8_t window[]={0x21,0x00,0x7f,0x22,0x00,0x07};
    esp_err_t e=oled_packet(0x00,window,sizeof(window));
    for(int page=0;page<8&&e==ESP_OK;++page)
        e=oled_packet(0x40,mono+page*OLED_WIDTH,OLED_WIDTH);
    return e;
}
static void display_task(void *unused)
{
    (void)unused;
    bool sleeping=false;
    bool was_moving=false, was_listening=false;
    uint64_t listening_since=0;
    uint32_t held_revision=0;
    uint64_t held_since=0;
    uint64_t connection_since=0;
    int connection_phase=-1;
    TickType_t last=xTaskGetTickCount();
    for(;;){
        const ainekio_body_state_t state=ainekio_p4_system_status().state;
        bool sleep=state==AINEKIO_STATE_DOZING||state==AINEKIO_STATE_DEEP_SLEEP;
        if(sleep!=sleeping){oled_cmd(sleep ? 0xae : 0xaf);sleeping=sleep;}
        if(!sleep){
            const uint64_t now=esp_timer_get_time()/1000;
            const ainekio_p4_body_status_t body=ainekio_p4_body_status();
            if(body.moving||was_moving||held_revision!=body.face_revision)held_since=now;
            was_moving=body.moving;held_revision=body.face_revision;
            ainekio_p4_face_sample_t sample=ainekio_p4_face_sample(&body,
                body.face_command ? now-held_since : now);
            const ainekio_p4_media_status_t media=ainekio_p4_media_status();
            const bool talking=media.speaker_busy;
            portENTER_CRITICAL(&selection_lock);
            sample=ainekio_p4_face_selected(&selection,sample,body.face_revision,body.moving,talking,now);
            portEXIT_CRITICAL(&selection_lock);
            if(media.utterance_open && !was_listening)listening_since=now;
            was_listening=media.utterance_open;
            sample=ainekio_p4_face_listen(sample,media.utterance_open,now-listening_since);
            const uint64_t started=esp_timer_get_time();
            const ainekio_connection_network_t network=ainekio_p4_network_display_status();
            const ainekio_connection_gateway_t gateway=ainekio_p4_controller_display_status();
            /* Retry attempts must not continually reset the instruction pages.
             * Reset on network phase or a meaningful pairing result change. */
            const int phase=network.phase*16+(gateway==AINEKIO_SCREEN_GATEWAY_ONLINE ? 1 :
                gateway==AINEKIO_SCREEN_GATEWAY_AUTH_FAILED ? 2 :
                gateway==AINEKIO_SCREEN_GATEWAY_PROTOCOL_FAILED ? 3 : 0);
            if(phase!=connection_phase){connection_phase=phase;connection_since=now;}
            ainekio_connection_page_t page;
            ainekio_connection_page(&network,gateway,now-connection_since,&page);
            /* Speech continues independently even while the body holds a pose. */
            if(page.face_visible)
                ainekio_face_render(sample.face,talking ? now : sample.elapsed_ms,talking,pixels);
            ainekio_connection_render(&page,pixels);
            if(page.face_visible){
                const ainekio_pca_fault_t fault=ainekio_pca_status(ainekio_p4_output()).fault;
                const bool motion_fault=fault==AINEKIO_PCA_FAULT_IO ||
                    fault==AINEKIO_PCA_FAULT_DEADLINE || fault==AINEKIO_PCA_FAULT_PROGRESS;
                ainekio_face_warning_icons(motion_fault,
                    !media.camera_ready && media.camera_failures>0,pixels);
            }
            const uint32_t elapsed=esp_timer_get_time()-started;
            if(elapsed>atomic_load(&render_max_us))atomic_store(&render_max_us,elapsed);
            esp_err_t e=draw(&page,now-connection_since);
            atomic_store(&ready,e==ESP_OK);
            if(e==ESP_OK){atomic_store(&shown_face,sample.face);atomic_fetch_add(&frames,1);}
            else ESP_LOGE("display","OLED transfer: %s",esp_err_to_name(e));
        }
        vTaskDelayUntil(&last,pdMS_TO_TICKS(1000/CONFIG_AINEKIO_LCD_FPS));
    }
}
#endif
esp_err_t ainekio_p4_display_start(void)
{
#if CONFIG_AINEKIO_LCD_ENABLED
    pixels=heap_caps_malloc(AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT*sizeof(*pixels),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!pixels)return ESP_ERR_NO_MEM;
    const gpio_config_t pins={
        .pin_bit_mask=(1ULL<<OLED_SCL)|(1ULL<<OLED_SDA),
        .mode=GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en=GPIO_PULLUP_ENABLE,
    };
    esp_err_t e=gpio_config(&pins);
    if(e!=ESP_OK)goto fail;
    gpio_set_level(OLED_SCL,1);gpio_set_level(OLED_SDA,1);
    static const uint8_t init[]={
        0xae,0xd5,0x80,0xa8,0x3f,0xd3,0x00,0x40,
        0x8d,0x14,0x20,0x00,0xa1,0xc8,0xda,0x12,
        0x81,0xcf,0xd9,0xf1,0xdb,0x40,0xa4,0xa6,0xaf,
    };
    e=oled_packet(0x00,init,sizeof(init));
    if(e!=ESP_OK)goto fail;
    if(xTaskCreate(display_task,"face_oled",4096,NULL,2,NULL)!=pdPASS){e=ESP_ERR_NO_MEM;goto fail;}
    atomic_store(&ready,true);
    ESP_LOGI("display","SSD1306 128x64 I2C: SCL GPIO20, SDA GPIO21, address 0x3c");
    return ESP_OK;
fail:
    heap_caps_free(pixels);pixels=NULL;
    return e;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}
int ainekio_p4_display_command(int argc,char **argv)
{
    if(argc>1&&!strcmp(argv[1],"auto"))ainekio_p4_display_restore();
    else if(argc>1&&!strcmp(argv[1],"list")){
        for(size_t i=0;i<ainekio_face_count();++i)puts(ainekio_face_name(i));
    }else if(argc>1){esp_err_t e=ainekio_p4_display_expression(argv[1]);if(e!=ESP_OK){puts(esp_err_to_name(e));return 1;}}
    printf("display driver_ready=%d face=%s frames=%u max_render_us=%u; SSD1306 address 0x3c on GPIO20/21\n",
        ainekio_p4_display_ready(),ainekio_p4_display_face(),atomic_load(&frames),atomic_load(&render_max_us));
    return 0;
}
