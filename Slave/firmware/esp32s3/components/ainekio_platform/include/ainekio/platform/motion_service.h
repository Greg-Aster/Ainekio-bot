#ifndef AINEKIO_PLATFORM_MOTION_SERVICE_H
#define AINEKIO_PLATFORM_MOTION_SERVICE_H

#include <stdbool.h>
#include <stdint.h>

#include "ainekio/assets.h"
#include "ainekio/platform/asset_store.h"
#include "ainekio/platform/mcpwm_adapter.h"
#include "ainekio/settings.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef enum {
    AINEKIO_MOTION_SUBMIT_OK = 0,
    AINEKIO_MOTION_SUBMIT_BUSY,
    AINEKIO_MOTION_SUBMIT_ASSET_MISSING,
    AINEKIO_MOTION_SUBMIT_LIMIT,
    AINEKIO_MOTION_SUBMIT_PREEMPTED,
    AINEKIO_MOTION_SUBMIT_IO_ERROR,
} ainekio_motion_submit_result_t;

typedef enum {
    AINEKIO_MOTION_JOB_ASSET = 0,
    AINEKIO_MOTION_JOB_NEUTRAL,
    AINEKIO_MOTION_JOB_STAND,
    AINEKIO_MOTION_JOB_POSE,
} ainekio_motion_job_kind_t;

typedef struct {
    uint32_t sequence;
    ainekio_motion_job_kind_t kind;
    char name[AINEKIO_ASSET_NAME_MAX + 1U];
    uint8_t repetitions;
} ainekio_motion_job_t;

typedef void (*ainekio_motion_done_fn)(void *context, uint32_t sequence);
typedef void (*ainekio_motion_failed_fn)(void *context, uint32_t sequence);
typedef void (*ainekio_motion_face_fn)(
    void *context,
    const char *name,
    ainekio_face_mode_t mode
);

typedef struct {
    void *context;
    ainekio_motion_done_fn done;
    ainekio_motion_failed_fn failed;
    ainekio_motion_face_fn face;
} ainekio_motion_callbacks_t;

typedef struct {
    ainekio_servo_bank_t *servos;
    ainekio_pose_bank_t *poses;
    ainekio_mcpwm_adapter_t *mcpwm;
    ainekio_asset_store_t *assets;
    ainekio_motion_callbacks_t callbacks;
    TaskHandle_t task;
    portMUX_TYPE state_lock;
    ainekio_motion_job_t pending_job;
    ainekio_motion_asset_t prepared_asset;
    uint32_t active_sequence;
    bool active_cancelled;
    bool job_pending;
    float calibration_degrees[AINEKIO_SERVO_COUNT];
    uint16_t calibration_duration_ms[AINEKIO_SERVO_COUNT];
    uint8_t calibration_pending_mask;
    SemaphoreHandle_t quiet_ready;
    SemaphoreHandle_t quiet_release;
    StaticSemaphore_t quiet_ready_storage;
    StaticSemaphore_t quiet_release_storage;
} ainekio_motion_service_t;

esp_err_t ainekio_motion_service_start(
    ainekio_motion_service_t *service,
    ainekio_servo_bank_t *servos,
    ainekio_pose_bank_t *poses,
    ainekio_mcpwm_adapter_t *mcpwm,
    ainekio_asset_store_t *assets,
    const ainekio_motion_callbacks_t *callbacks
);
ainekio_motion_submit_result_t ainekio_motion_service_submit(
    ainekio_motion_service_t *service,
    const ainekio_motion_job_t *job
);
ainekio_motion_submit_result_t ainekio_motion_service_prepare(
    ainekio_motion_service_t *service,
    const ainekio_motion_job_t *job
);
ainekio_motion_submit_result_t ainekio_motion_service_commit(
    ainekio_motion_service_t *service,
    uint32_t sequence
);
void ainekio_motion_service_abort(
    ainekio_motion_service_t *service,
    uint32_t sequence
);
uint32_t ainekio_motion_service_request_stop(ainekio_motion_service_t *service);
void ainekio_motion_service_request_failsafe(ainekio_motion_service_t *service);
bool ainekio_motion_service_busy(const ainekio_motion_service_t *service);
ainekio_motion_submit_result_t ainekio_motion_service_calibrate_servo(
    ainekio_motion_service_t *service,
    uint8_t joint_id,
    float logical_degrees,
    uint16_t duration_ms
);
bool ainekio_motion_service_begin_quiet_window(
    ainekio_motion_service_t *service,
    TickType_t timeout
);
void ainekio_motion_service_end_quiet_window(ainekio_motion_service_t *service);

#endif
