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
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static atomic_bool ready;
static atomic_uint shown_face, frames, render_max_us;
static portMUX_TYPE selection_lock=portMUX_INITIALIZER_UNLOCKED;
static struct { size_t face; uint32_t revision; uint64_t started_ms; bool manual; } selection;
#if CONFIG_AINEKIO_LCD_ENABLED
static esp_lcd_panel_handle_t panel;
static esp_lcd_panel_io_handle_t io;
static SemaphoreHandle_t transferred;
static uint16_t *pixels,*stripe;
enum { STRIPE_ROWS=16 };
#endif

bool ainekio_p4_display_ready(void){return atomic_load(&ready);}
const char *ainekio_p4_display_face(void){return ainekio_face_name(atomic_load(&shown_face));}
void ainekio_p4_display_restore(void)
{
    portENTER_CRITICAL(&selection_lock);selection.manual=false;portEXIT_CRITICAL(&selection_lock);
}
esp_err_t ainekio_p4_display_expression(const char *name)
{
    size_t face;
    if(!ainekio_face_find(name,&face))return ESP_ERR_NOT_FOUND;
    if(!atomic_load(&ready))return ESP_ERR_INVALID_STATE;
    const ainekio_p4_body_status_t body=ainekio_p4_body_status();
    portENTER_CRITICAL(&selection_lock);
    selection.face=face;selection.revision=body.face_revision;
    selection.started_ms=esp_timer_get_time()/1000;selection.manual=true;
    portEXIT_CRITICAL(&selection_lock);
    return ESP_OK;
}
#if CONFIG_AINEKIO_LCD_ENABLED
static bool transferred_callback(esp_lcd_panel_io_handle_t handle,
    esp_lcd_panel_io_event_data_t *event,void *context)
{
    (void)handle;(void)event;(void)context;
    BaseType_t wake=pdFALSE;xSemaphoreGiveFromISR(transferred,&wake);return wake==pdTRUE;
}
static esp_err_t draw(void)
{
    for(int y=0;y<AINEKIO_FACE_HEIGHT;y+=STRIPE_ROWS){
        int rows=AINEKIO_FACE_HEIGHT-y;if(rows>STRIPE_ROWS)rows=STRIPE_ROWS;
        memcpy(stripe,pixels+y*AINEKIO_FACE_WIDTH,rows*AINEKIO_FACE_WIDTH*sizeof(*pixels));
        esp_err_t e=esp_lcd_panel_draw_bitmap(panel,0,y,AINEKIO_FACE_WIDTH,y+rows,stripe);
        if(e!=ESP_OK)return e;
        /* DMA owns this stripe until the transaction callback. It cannot
         * stall the separate body task or cause a body stop. */
        xSemaphoreTake(transferred,portMAX_DELAY);
    }
    return ESP_OK;
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
        if(sleep!=sleeping){esp_lcd_panel_disp_on_off(panel,!sleep);sleeping=sleep;}
        if(!sleep){
            const uint64_t now=esp_timer_get_time()/1000;
            const ainekio_p4_body_status_t body=ainekio_p4_body_status();
            if(body.moving||was_moving||held_revision!=body.face_revision)held_since=now;
            was_moving=body.moving;held_revision=body.face_revision;
            ainekio_p4_face_sample_t sample=ainekio_p4_face_sample(&body,
                body.face_command ? now-held_since : now);
            portENTER_CRITICAL(&selection_lock);
            if(selection.manual&&selection.revision!=body.face_revision)selection.manual=false;
            if(selection.manual){sample.face=selection.face;sample.elapsed_ms=now-selection.started_ms;}
            portEXIT_CRITICAL(&selection_lock);
            const ainekio_p4_media_status_t media=ainekio_p4_media_status();
            const bool talking=media.speaker_busy;
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
            esp_err_t e=draw();
            atomic_store(&ready,e==ESP_OK);
            if(e==ESP_OK){atomic_store(&shown_face,sample.face);atomic_fetch_add(&frames,1);}
            else ESP_LOGE("display","SPI transfer: %s",esp_err_to_name(e));
        }
        vTaskDelayUntil(&last,pdMS_TO_TICKS(1000/CONFIG_AINEKIO_LCD_FPS));
    }
}
#endif
esp_err_t ainekio_p4_display_start(void)
{
#if CONFIG_AINEKIO_LCD_ENABLED
    esp_err_t result;
    bool bus_started=false;
    pixels=heap_caps_malloc(AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT*sizeof(*pixels),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    stripe=heap_caps_malloc(AINEKIO_FACE_WIDTH*STRIPE_ROWS*sizeof(*stripe),MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
    transferred=xSemaphoreCreateBinary();
    if(!pixels||!stripe||!transferred){result=ESP_ERR_NO_MEM;goto fail;}
    const spi_bus_config_t bus={.sclk_io_num=CONFIG_AINEKIO_LCD_SCLK,.mosi_io_num=CONFIG_AINEKIO_LCD_MOSI,
        .miso_io_num=-1,.quadwp_io_num=-1,.quadhd_io_num=-1,
        .max_transfer_sz=AINEKIO_FACE_WIDTH*STRIPE_ROWS*sizeof(*stripe)};
    result=spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO);
    if(result!=ESP_OK)goto fail;
    bus_started=true;
    const esp_lcd_panel_io_spi_config_t bus_io={.dc_gpio_num=CONFIG_AINEKIO_LCD_DC,.cs_gpio_num=CONFIG_AINEKIO_LCD_CS,
        .pclk_hz=CONFIG_AINEKIO_LCD_SPI_HZ,.lcd_cmd_bits=8,.lcd_param_bits=8,.spi_mode=0,
        .trans_queue_depth=1,.on_color_trans_done=transferred_callback};
    result=esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST,&bus_io,&io);
    if(result!=ESP_OK)goto fail;
    const esp_lcd_panel_dev_config_t config={.reset_gpio_num=CONFIG_AINEKIO_LCD_RESET,
#ifdef CONFIG_AINEKIO_LCD_BGR
        .rgb_ele_order=LCD_RGB_ELEMENT_ORDER_BGR,
#else
        .rgb_ele_order=LCD_RGB_ELEMENT_ORDER_RGB,
#endif
        .data_endian=LCD_RGB_DATA_ENDIAN_LITTLE,.bits_per_pixel=16};
    result=esp_lcd_new_panel_st7789(io,&config,&panel);
    if(result==ESP_OK)result=esp_lcd_panel_reset(panel);
    if(result==ESP_OK)result=esp_lcd_panel_init(panel);
    if(result==ESP_OK)result=esp_lcd_panel_swap_xy(panel,true);
#ifdef CONFIG_AINEKIO_LCD_ROTATE_180
    if(result==ESP_OK)result=esp_lcd_panel_mirror(panel,false,true);
#else
    if(result==ESP_OK)result=esp_lcd_panel_mirror(panel,true,false);
#endif
    if(result==ESP_OK)result=esp_lcd_panel_set_gap(panel,0,CONFIG_AINEKIO_LCD_Y_GAP);
#ifdef CONFIG_AINEKIO_LCD_INVERT
    if(result==ESP_OK)result=esp_lcd_panel_invert_color(panel,true);
#endif
    if(result==ESP_OK)result=esp_lcd_panel_disp_on_off(panel,true);
    if(result!=ESP_OK)goto fail;
    if(xTaskCreate(display_task,"face_lcd",4096,NULL,2,NULL)!=pdPASS){result=ESP_ERR_NO_MEM;goto fail;}
    atomic_store(&ready,true);
    ESP_LOGI("display","ST7789 320x170 SPI2; SCK=%d MOSI=%d CS=%d DC=%d RESET=%d. SPI cannot detect an absent panel.",
        CONFIG_AINEKIO_LCD_SCLK,CONFIG_AINEKIO_LCD_MOSI,CONFIG_AINEKIO_LCD_CS,CONFIG_AINEKIO_LCD_DC,CONFIG_AINEKIO_LCD_RESET);
    return ESP_OK;
fail:
    if(panel){esp_lcd_panel_del(panel);panel=NULL;}
    if(io){esp_lcd_panel_io_del(io);io=NULL;}
    if(bus_started)spi_bus_free(SPI2_HOST);
    if(transferred){vSemaphoreDelete(transferred);transferred=NULL;}
    heap_caps_free(pixels);pixels=NULL;heap_caps_free(stripe);stripe=NULL;
    return result;
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
    printf("display driver_ready=%d face=%s frames=%u max_render_us=%u; panel presence is not detectable over write-only SPI\n",
        ainekio_p4_display_ready(),ainekio_p4_display_face(),atomic_load(&frames),atomic_load(&render_max_us));
    return 0;
}
