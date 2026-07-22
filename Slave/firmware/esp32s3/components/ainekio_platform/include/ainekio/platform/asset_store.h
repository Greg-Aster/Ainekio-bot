#ifndef AINEKIO_PLATFORM_ASSET_STORE_H
#define AINEKIO_PLATFORM_ASSET_STORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ainekio/assets.h"
#include "ainekio/servo.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define AINEKIO_ASSET_MOUNT_PATH "/assets"
#define AINEKIO_ASSET_MAX_MOTIONS 32U
#define AINEKIO_ASSET_MAX_FACES 64U
#define AINEKIO_ASSET_MAX_AUDIO 16U
#define AINEKIO_ASSET_MAX_FACE_FRAMES 6U
#define AINEKIO_FACE_FRAME_BYTES 1024U
#define AINEKIO_MOTION_MAX_FILE_BYTES 16384U

typedef struct {
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    char path[65];
    uint32_t bytes;
    bool available;
} ainekio_motion_index_entry_t;

typedef struct {
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    char frame_paths[AINEKIO_ASSET_MAX_FACE_FRAMES][65];
    uint8_t frame_count;
    uint8_t fps;
    ainekio_face_mode_t mode;
    bool available;
} ainekio_face_index_entry_t;

typedef struct {
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    char path[65];
    uint32_t samples;
    bool available;
} ainekio_audio_index_entry_t;

typedef struct ainekio_asset_storage ainekio_asset_storage_t;

typedef struct {
    ainekio_servo_bank_t *servos;
    SemaphoreHandle_t lock;
    StaticSemaphore_t lock_storage;
    ainekio_asset_storage_t *storage;
    uint8_t motion_count;
    uint8_t face_count;
    uint8_t audio_count;
    uint16_t unavailable_count;
    bool mounted;
} ainekio_asset_store_t;

esp_err_t ainekio_asset_store_init(
    ainekio_asset_store_t *store,
    ainekio_servo_bank_t *servos
);
esp_err_t ainekio_asset_store_load_motion(
    ainekio_asset_store_t *store,
    const char *name,
    ainekio_motion_asset_t *asset
);
const ainekio_motion_index_entry_t *ainekio_asset_store_motion(
    const ainekio_asset_store_t *store,
    const char *name
);
const ainekio_face_index_entry_t *ainekio_asset_store_face(
    const ainekio_asset_store_t *store,
    const char *name
);
esp_err_t ainekio_asset_store_read_face_frame(
    ainekio_asset_store_t *store,
    const ainekio_face_index_entry_t *face,
    uint8_t frame_index,
    uint8_t output[AINEKIO_FACE_FRAME_BYTES]
);
const ainekio_audio_index_entry_t *ainekio_asset_store_audio(
    const ainekio_asset_store_t *store,
    const char *name
);
esp_err_t ainekio_asset_store_audio_path(
    const ainekio_audio_index_entry_t *audio,
    char *output,
    size_t output_size
);

#endif
