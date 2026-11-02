#pragma once
/* Host declarations for the existing storage owner tests; no device driver runs. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#define portMAX_DELAY UINT32_MAX
#define taskENTER_CRITICAL(p) portENTER_CRITICAL(p)
#define taskEXIT_CRITICAL(p) portEXIT_CRITICAL(p)
#define GPIO_MODE_OUTPUT 1
#define SDMMC_HOST_FLAG_4BIT 1
#define SDMMC_HOST_FLAG_DEINIT_ARG 2
#define SDMMC_FREQ_DEFAULT 20000
#define ESP_LOGW(...) ((void)0)
typedef struct {uint64_t pin_bit_mask;int mode;} gpio_config_t;
typedef void *sd_pwr_ctrl_handle_t;
typedef struct {int ldo_chan_id;} sd_pwr_ctrl_ldo_config_t;
typedef struct {struct {unsigned sector_size;} csd;} sdmmc_card_t;
typedef struct {int slot,flags,max_freq_khz;sd_pwr_ctrl_handle_t pwr_ctrl_handle;esp_err_t (*deinit_p)(int);} sdmmc_host_t;
typedef struct {int width,clk,cmd,d0,d1,d2,d3,flags;} sdmmc_slot_config_t;
typedef struct {bool format_if_mount_failed;int max_files;size_t allocation_unit_size;} esp_vfs_fat_mount_config_t;
#define SDMMC_HOST_DEFAULT() ((sdmmc_host_t){0})
#define SDMMC_SLOT_CONFIG_DEFAULT() ((sdmmc_slot_config_t){0})
#define SDMMC_SLOT_FLAG_INTERNAL_PULLUP 1
esp_err_t gpio_set_level(int,int);
esp_err_t gpio_config(const gpio_config_t *);
esp_err_t sd_pwr_ctrl_new_on_chip_ldo(const sd_pwr_ctrl_ldo_config_t *,sd_pwr_ctrl_handle_t *);
esp_err_t sd_pwr_ctrl_del_on_chip_ldo(sd_pwr_ctrl_handle_t);
esp_err_t sdmmc_host_deinit_slot(int);
esp_err_t esp_vfs_fat_sdmmc_mount(const char *,const sdmmc_host_t *,const sdmmc_slot_config_t *,const esp_vfs_fat_mount_config_t *,sdmmc_card_t **);
esp_err_t esp_vfs_fat_sdcard_unmount(const char *,sdmmc_card_t *);
esp_err_t esp_vfs_fat_info(const char *,uint64_t *,uint64_t *);
void *heap_caps_malloc(size_t,unsigned);
SemaphoreHandle_t xSemaphoreCreateBinary(void);
void vSemaphoreDelete(SemaphoreHandle_t);
void vQueueDelete(QueueHandle_t);
BaseType_t xTaskCreate(void (*)(void *),const char *,unsigned,void *,unsigned,void *);
TickType_t xTaskGetTickCount(void);
