#include "ainekio/platform/motion_service.h"

#include <string.h>

#include "esp_log.h"
#include "sdkconfig.h"

#define MOTION_NOTIFY_JOB BIT0
#define MOTION_NOTIFY_STOP BIT1
#define MOTION_NOTIFY_CALIBRATION BIT2
#define MOTION_NOTIFY_QUIET BIT3
#define MOTION_STACK_BYTES 6144U
#define MOTION_TASK_PRIORITY (configMAX_PRIORITIES - 1U)
#define STOP_DURATION_MS 300U

static const char *TAG = "ainekio_motion";

static float configured_logical_degrees(float logical_degrees)
{
    const float scale = (float)CONFIG_AINEKIO_MOTION_RANGE_PERCENT / 100.0F;
    return 90.0F + (logical_degrees - 90.0F) * scale;
}

static uint16_t configured_duration_ms(uint16_t duration_ms)
{
    return duration_ms < CONFIG_AINEKIO_MOTION_MIN_FRAME_MS
               ? CONFIG_AINEKIO_MOTION_MIN_FRAME_MS
               : duration_ms;
}

static bool motion_plan_valid(const ainekio_motion_plan_t *plan)
{
    if (plan == NULL ||
        plan->joint_map_version != AINEKIO_JOINT_MAP_VERSION ||
        plan->frame_count == 0U ||
        plan->frame_count > AINEKIO_MOTION_PLAN_MAX_FRAMES ||
        plan->end > AINEKIO_MOTION_PLAN_END_NEUTRAL) {
        return false;
    }
    uint32_t total_duration_ms = 0U;
    for (uint8_t frame_index = 0U; frame_index < plan->frame_count;
         ++frame_index) {
        const ainekio_motion_plan_frame_t *frame = &plan->frames[frame_index];
        if (frame->duration_ms < AINEKIO_MOTION_PLAN_MIN_FRAME_MS ||
            frame->duration_ms > AINEKIO_MOTION_PLAN_MAX_FRAME_MS) {
            return false;
        }
        total_duration_ms += frame->duration_ms;
        if (total_duration_ms > AINEKIO_MOTION_PLAN_MAX_TOTAL_MS) {
            return false;
        }
        for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT;
             ++joint_id) {
            if (frame->targets[joint_id] >
                AINEKIO_MOTION_PLAN_MAX_CENTIDEGREES) {
                return false;
            }
        }
    }
    return total_duration_ms == plan->total_duration_ms;
}

static bool service_notifications(ainekio_motion_service_t *service)
{
    uint32_t notifications = 0U;
    (void)xTaskNotifyWait(
        0U,
        MOTION_NOTIFY_STOP | MOTION_NOTIFY_QUIET,
        &notifications,
        0U
    );
    if ((notifications & MOTION_NOTIFY_STOP) != 0U) {
        return true;
    }
    if ((notifications & MOTION_NOTIFY_QUIET) != 0U) {
        (void)xSemaphoreGive(service->quiet_ready);
        (void)xSemaphoreTake(service->quiet_release, pdMS_TO_TICKS(20U));
    }
    return false;
}

#if CONFIG_AINEKIO_MOTION_SMOOTH_PLAYBACK
static esp_err_t run_smoothed_source_frame(
    ainekio_motion_service_t *service,
    const ainekio_motion_frame_t *frame,
    uint16_t duration_ms,
    TickType_t period,
    TickType_t *wake
)
{
    float start_degrees[AINEKIO_SERVO_COUNT];
    float target_degrees[AINEKIO_SERVO_COUNT];

    for (uint8_t index = 0U; index < frame->target_count; ++index) {
        const ainekio_motion_target_t *target = &frame->targets[index];
        const uint8_t joint_id = target->joint_id;
        if (joint_id >= AINEKIO_SERVO_COUNT) {
            return ESP_ERR_INVALID_ARG;
        }
        const ainekio_servo_result_t result = ainekio_servo_map_logical(
            &service->servos->channels[joint_id].calibration,
            configured_logical_degrees(
                (float)target->centidegrees / 100.0F
            ),
            &target_degrees[index]
        );
        if (result != AINEKIO_SERVO_OK) {
            return result == AINEKIO_SERVO_LIMIT ? ESP_ERR_INVALID_ARG
                                                 : ESP_ERR_INVALID_STATE;
        }
        start_degrees[index] =
            service->servos->channels[joint_id].current_degrees;
    }

    const uint16_t transition_ms =
        duration_ms < CONFIG_AINEKIO_MOTION_SMOOTH_TRANSITION_MS
            ? duration_ms
            : CONFIG_AINEKIO_MOTION_SMOOTH_TRANSITION_MS;
    const uint16_t transition_ticks = (uint16_t)(
        (transition_ms + AINEKIO_SERVO_TICK_MS - 1U) /
        AINEKIO_SERVO_TICK_MS
    );
    const uint16_t total_ticks = (uint16_t)(
        (duration_ms + AINEKIO_SERVO_TICK_MS - 1U) /
        AINEKIO_SERVO_TICK_MS
    );

    for (uint16_t tick = 1U; tick <= total_ticks; ++tick) {
        if (service_notifications(service)) {
            return ESP_ERR_INVALID_RESPONSE;
        }
        if (tick <= transition_ticks) {
            const float progress =
                (float)tick / (float)transition_ticks;
            const float eased =
                progress * progress * (3.0F - 2.0F * progress);
            for (uint8_t index = 0U; index < frame->target_count; ++index) {
                const uint8_t joint_id = frame->targets[index].joint_id;
                const float degrees =
                    start_degrees[index] +
                    (target_degrees[index] - start_degrees[index]) * eased;
                const ainekio_servo_result_t result =
                    ainekio_servo_move_physical(
                        service->servos,
                        joint_id,
                        degrees,
                        0U
                    );
                if (result != AINEKIO_SERVO_OK) {
                    return result == AINEKIO_SERVO_LIMIT
                               ? ESP_ERR_INVALID_ARG
                               : ESP_ERR_INVALID_STATE;
                }
            }
        }
        const esp_err_t result =
            ainekio_mcpwm_adapter_sync(service->mcpwm, service->servos);
        if (result != ESP_OK) {
            return result;
        }
        vTaskDelayUntil(wake, period);
    }
    return ESP_OK;
}
#endif

static esp_err_t run_frame(
    ainekio_motion_service_t *service,
    const ainekio_motion_frame_t *frame,
    bool sequential_servo_timing
)
{
    const uint16_t duration_ms = configured_duration_ms(frame->duration_ms);
    const TickType_t period = pdMS_TO_TICKS(AINEKIO_SERVO_TICK_MS);
    TickType_t wake = xTaskGetTickCount();

    if (sequential_servo_timing) {
#if CONFIG_AINEKIO_MOTION_SMOOTH_PLAYBACK
        return run_smoothed_source_frame(
            service,
            frame,
            duration_ms,
            period,
            &wake
        );
#else
        const uint16_t servo_time_ms =
            (uint16_t)frame->target_count * AINEKIO_SERVO_TICK_MS;
        if (duration_ms < servo_time_ms) {
            return ESP_ERR_INVALID_ARG;
        }
        for (uint8_t index = 0U; index < frame->target_count; ++index) {
            const ainekio_motion_target_t *target = &frame->targets[index];
            const ainekio_servo_result_t result = ainekio_servo_move_logical(
                service->servos,
                target->joint_id,
                configured_logical_degrees(
                    (float)target->centidegrees / 100.0F
                ),
                AINEKIO_SERVO_TICK_MS
            );
            if (result != AINEKIO_SERVO_OK) {
                return result == AINEKIO_SERVO_LIMIT
                           ? ESP_ERR_INVALID_ARG
                           : ESP_ERR_INVALID_STATE;
            }
            if (service_notifications(service)) {
                return ESP_ERR_INVALID_RESPONSE;
            }
            const esp_err_t sync_result =
                ainekio_mcpwm_adapter_sync(service->mcpwm, service->servos);
            if (sync_result != ESP_OK) {
                return sync_result;
            }
            vTaskDelayUntil(&wake, period);
        }

        const uint16_t hold_ticks = (uint16_t)(
            (duration_ms - servo_time_ms + AINEKIO_SERVO_TICK_MS - 1U) /
            AINEKIO_SERVO_TICK_MS
        );
        for (uint16_t tick = 0U; tick < hold_ticks; ++tick) {
            if (service_notifications(service)) {
                return ESP_ERR_INVALID_RESPONSE;
            }
            const esp_err_t sync_result =
                ainekio_mcpwm_adapter_sync(service->mcpwm, service->servos);
            if (sync_result != ESP_OK) {
                return sync_result;
            }
            vTaskDelayUntil(&wake, period);
        }
        return ESP_OK;
#endif
    }

    for (uint8_t index = 0U; index < frame->target_count; ++index) {
        const ainekio_motion_target_t *target = &frame->targets[index];
        const ainekio_servo_result_t result = ainekio_servo_move_logical(
            service->servos,
            target->joint_id,
            configured_logical_degrees((float)target->centidegrees / 100.0F),
            duration_ms
        );
        if (result != AINEKIO_SERVO_OK) {
            return result == AINEKIO_SERVO_LIMIT ? ESP_ERR_INVALID_ARG
                                                 : ESP_ERR_INVALID_STATE;
        }
    }

    const uint16_t ticks = (uint16_t)(
        (duration_ms + AINEKIO_SERVO_TICK_MS - 1U) /
        AINEKIO_SERVO_TICK_MS
    );
    for (uint16_t tick = 0U; tick < ticks; ++tick) {
        if (service_notifications(service)) {
            return ESP_ERR_INVALID_RESPONSE;
        }
        const esp_err_t result =
            ainekio_mcpwm_adapter_sync(service->mcpwm, service->servos);
        if (result != ESP_OK) {
            return result;
        }
        vTaskDelayUntil(&wake, period);
    }
    return ESP_OK;
}

static esp_err_t run_asset(
    ainekio_motion_service_t *service,
    const ainekio_motion_asset_t *asset,
    uint8_t repetitions
)
{
    uint8_t cue_index = 0U;
    for (uint8_t outer = 0U; outer < repetitions; ++outer) {
        for (uint8_t repeat = 0U; repeat < asset->repeat_count; ++repeat) {
            cue_index = 0U;
            for (uint16_t frame_index = 0U; frame_index < asset->frame_count;
                 ++frame_index) {
                while (cue_index < asset->face_cue_count &&
                       asset->face_cues[cue_index].frame_index == frame_index) {
                    if (service->callbacks.face != NULL) {
                        service->callbacks.face(
                            service->callbacks.context,
                            asset->face_cues[cue_index].name,
                            asset->face_cues[cue_index].mode
                        );
                    }
                    ++cue_index;
                }
                const esp_err_t result = run_frame(
                    service,
                    &asset->frames[frame_index],
                    asset->sequential_servo_timing
                );
                if (result != ESP_OK) {
                    return result;
                }
            }
        }
    }
    return ESP_OK;
}

static esp_err_t run_pose(
    ainekio_motion_service_t *service,
    const ainekio_named_pose_t *pose,
    uint16_t duration_ms
)
{
    ainekio_motion_frame_t frame = {
        .duration_ms = duration_ms,
        .target_count = pose->count,
    };
    for (uint8_t index = 0U; index < pose->count; ++index) {
        frame.targets[index].joint_id = pose->targets[index].id;
        frame.targets[index].centidegrees =
            (uint16_t)(pose->targets[index].degrees * 100.0F + 0.5F);
    }
    return run_frame(service, &frame, false);
}

static esp_err_t run_fallback(
    ainekio_motion_service_t *service,
    ainekio_fallback_motion_t fallback
)
{
    /* This asset is intentionally stored in the service rather than on the
     * motion task's 6 KiB stack. The full eight-channel fallback asset is
     * large enough to overflow that stack during a battery-cutoff stop. */
    ainekio_motion_asset_fallback(fallback, &service->prepared_asset);
    return run_asset(service, &service->prepared_asset, 1U);
}

static void clear_active(ainekio_motion_service_t *service, uint32_t sequence)
{
    taskENTER_CRITICAL(&service->state_lock);
    if (service->active_sequence == sequence) {
        service->active_sequence = 0U;
        service->active_cancelled = false;
        service->job_pending = false;
    }
    taskEXIT_CRITICAL(&service->state_lock);
}

static void perform_stop(ainekio_motion_service_t *service)
{
    bool detach = false;
    taskENTER_CRITICAL(&service->state_lock);
    detach = service->detach_requested;
    taskEXIT_CRITICAL(&service->state_lock);

    esp_err_t hold_result = ESP_OK;
    while (!detach) {
        hold_result = run_fallback(service, AINEKIO_FALLBACK_NEUTRAL);
        taskENTER_CRITICAL(&service->state_lock);
        detach = service->detach_requested;
        taskEXIT_CRITICAL(&service->state_lock);
        if (hold_result != ESP_ERR_INVALID_RESPONSE) {
            break;
        }
    }

    taskENTER_CRITICAL(&service->state_lock);
    detach = detach || service->detach_requested;
    service->detach_requested = false;
    service->active_sequence = 0U;
    service->active_cancelled = false;
    service->job_pending = false;
    service->calibration_pending_mask = 0U;
    taskEXIT_CRITICAL(&service->state_lock);

    if (detach || hold_result != ESP_OK) {
        ainekio_servo_detach_all(service->servos);
        (void)ainekio_mcpwm_adapter_detach_all(service->mcpwm);
        ESP_LOGW(
            TAG,
            "motion outputs detached%s",
            hold_result == ESP_OK ? "" : " after neutral hold failed"
        );
    } else {
        ESP_LOGI(TAG, "motion stopped at neutral; PWM hold remains enabled");
    }
}

static esp_err_t run_calibration(ainekio_motion_service_t *service)
{
    const TickType_t period = pdMS_TO_TICKS(AINEKIO_SERVO_TICK_MS);
    TickType_t wake = xTaskGetTickCount();
    while (true) {
        uint8_t pending = 0U;
        float degrees[AINEKIO_SERVO_COUNT];
        uint16_t durations[AINEKIO_SERVO_COUNT];
        taskENTER_CRITICAL(&service->state_lock);
        pending = service->calibration_pending_mask;
        service->calibration_pending_mask = 0U;
        memcpy(degrees, service->calibration_degrees, sizeof(degrees));
        memcpy(durations, service->calibration_duration_ms, sizeof(durations));
        taskEXIT_CRITICAL(&service->state_lock);

        for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
            if ((pending & (uint8_t)(1U << joint_id)) != 0U &&
                ainekio_servo_move_logical(
                    service->servos,
                    joint_id,
                    configured_logical_degrees(degrees[joint_id]),
                    configured_duration_ms(durations[joint_id])
                ) != AINEKIO_SERVO_OK) {
                return ESP_ERR_INVALID_ARG;
            }
        }
        if (service_notifications(service)) {
            return ESP_ERR_INVALID_RESPONSE;
        }
        const esp_err_t result =
            ainekio_mcpwm_adapter_sync(service->mcpwm, service->servos);
        if (result != ESP_OK) {
            return result;
        }

        bool moving = false;
        for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
            moving = moving || service->servos->channels[joint_id].remaining_ticks > 0U;
        }
        taskENTER_CRITICAL(&service->state_lock);
        const bool more_pending = service->calibration_pending_mask != 0U;
        taskEXIT_CRITICAL(&service->state_lock);
        if (!moving && !more_pending) {
            return ESP_OK;
        }
        vTaskDelayUntil(&wake, period);
    }
}

static esp_err_t execute_job(
    ainekio_motion_service_t *service,
    const ainekio_motion_job_t *job
)
{
    if (job->kind == AINEKIO_MOTION_JOB_NEUTRAL) {
        return run_fallback(service, AINEKIO_FALLBACK_NEUTRAL);
    }
    if (job->kind == AINEKIO_MOTION_JOB_STAND) {
        return run_fallback(service, AINEKIO_FALLBACK_STAND);
    }
    if (job->kind == AINEKIO_MOTION_JOB_POSE) {
        const ainekio_named_pose_t *pose =
            ainekio_pose_bank_find(service->poses, job->name);
        return pose == NULL ? ESP_ERR_NOT_FOUND : run_pose(service, pose, 300U);
    }
    if (job->kind == AINEKIO_MOTION_JOB_PLAN) {
        const esp_err_t result = run_asset(service, &service->prepared_asset, 1U);
        if (result != ESP_OK ||
            job->plan_end == AINEKIO_MOTION_PLAN_END_HOLD) {
            return result;
        }
        return run_fallback(
            service,
            job->plan_end == AINEKIO_MOTION_PLAN_END_STAND
                ? AINEKIO_FALLBACK_STAND
                : AINEKIO_FALLBACK_NEUTRAL
        );
    }

    esp_err_t result = run_asset(
        service,
        &service->prepared_asset,
        job->repetitions
    );
    if (result == ESP_OK && service->prepared_asset.return_pose[0] != '\0') {
        const ainekio_named_pose_t *pose = ainekio_pose_bank_find(
            service->poses,
            service->prepared_asset.return_pose
        );
        result = pose != NULL
                     ? run_pose(service, pose, 300U)
                     : run_fallback(service, AINEKIO_FALLBACK_STAND);
    }
    return result;
}

static void motion_task(void *argument)
{
    ainekio_motion_service_t *service = argument;
    while (true) {
        uint32_t notifications = 0U;
        (void)xTaskNotifyWait(0U, UINT32_MAX, &notifications, portMAX_DELAY);
        if ((notifications & MOTION_NOTIFY_STOP) != 0U) {
            perform_stop(service);
            continue;
        }
        if ((notifications & MOTION_NOTIFY_QUIET) != 0U) {
            (void)xSemaphoreGive(service->quiet_ready);
            (void)xSemaphoreTake(service->quiet_release, pdMS_TO_TICKS(20U));
        }
        if ((notifications & MOTION_NOTIFY_CALIBRATION) != 0U) {
            const esp_err_t result = run_calibration(service);
            if (result == ESP_ERR_INVALID_STATE) {
                perform_stop(service);
            } else if (result != ESP_OK) {
                ESP_LOGE(TAG, "calibration motion failed: %s", esp_err_to_name(result));
                perform_stop(service);
            }
            continue;
        }
        if ((notifications & MOTION_NOTIFY_JOB) == 0U) {
            continue;
        }

        ainekio_motion_job_t job;
        bool cancelled = false;
        taskENTER_CRITICAL(&service->state_lock);
        job = service->pending_job;
        cancelled = service->active_cancelled;
        service->job_pending = false;
        taskEXIT_CRITICAL(&service->state_lock);
        if (cancelled) {
            perform_stop(service);
            continue;
        }

        const esp_err_t result = execute_job(service, &job);
        taskENTER_CRITICAL(&service->state_lock);
        cancelled = service->active_cancelled;
        taskEXIT_CRITICAL(&service->state_lock);
        if (cancelled || result == ESP_ERR_INVALID_STATE) {
            perform_stop(service);
            continue;
        }
        clear_active(service, job.sequence);
        if (result == ESP_OK) {
            if (service->callbacks.done != NULL) {
                service->callbacks.done(service->callbacks.context, job.sequence);
            }
        } else {
            ESP_LOGE(TAG,
                     "motion seq=%lu failed: %s",
                     (unsigned long)job.sequence,
                     esp_err_to_name(result));
            ainekio_servo_detach_all(service->servos);
            (void)ainekio_mcpwm_adapter_detach_all(service->mcpwm);
            if (service->callbacks.failed != NULL) {
                service->callbacks.failed(service->callbacks.context, job.sequence);
            }
        }
    }
}

esp_err_t ainekio_motion_service_start(
    ainekio_motion_service_t *service,
    ainekio_servo_bank_t *servos,
    ainekio_pose_bank_t *poses,
    ainekio_mcpwm_adapter_t *mcpwm,
    ainekio_asset_store_t *assets,
    const ainekio_motion_callbacks_t *callbacks
)
{
    if (service == NULL || servos == NULL || poses == NULL || mcpwm == NULL ||
        assets == NULL || !mcpwm->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(service, 0, sizeof(*service));
    service->servos = servos;
    service->poses = poses;
    service->mcpwm = mcpwm;
    service->assets = assets;
    service->state_lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    service->quiet_ready =
        xSemaphoreCreateBinaryStatic(&service->quiet_ready_storage);
    service->quiet_release =
        xSemaphoreCreateBinaryStatic(&service->quiet_release_storage);
    if (service->quiet_ready == NULL || service->quiet_release == NULL) {
        return ESP_ERR_NO_MEM;
    }
    if (callbacks != NULL) {
        service->callbacks = *callbacks;
    }
    if (xTaskCreatePinnedToCore(
            motion_task,
            "motion",
            MOTION_STACK_BYTES,
            service,
            MOTION_TASK_PRIORITY,
            &service->task,
            1
        ) != pdPASS) {
        service->task = NULL;
        return ESP_ERR_NO_MEM;
    }
#if CONFIG_AINEKIO_MOTION_SMOOTH_PLAYBACK
    ESP_LOGI(
        TAG,
        "all-servo profile range=%d%% logical=%.1f..%.1f min_frame_ms=%d "
        "playback=smooth transition_ms=%d",
        CONFIG_AINEKIO_MOTION_RANGE_PERCENT,
        (double)configured_logical_degrees(0.0F),
        (double)configured_logical_degrees(180.0F),
        CONFIG_AINEKIO_MOTION_MIN_FRAME_MS,
        CONFIG_AINEKIO_MOTION_SMOOTH_TRANSITION_MS
    );
#else
    ESP_LOGI(
        TAG,
        "all-servo profile range=%d%% logical=%.1f..%.1f min_frame_ms=%d "
        "playback=sesame_exact",
        CONFIG_AINEKIO_MOTION_RANGE_PERCENT,
        (double)configured_logical_degrees(0.0F),
        (double)configured_logical_degrees(180.0F),
        CONFIG_AINEKIO_MOTION_MIN_FRAME_MS
    );
#endif
    return ESP_OK;
}

ainekio_motion_submit_result_t ainekio_motion_service_prepare(
    ainekio_motion_service_t *service,
    const ainekio_motion_job_t *job
)
{
    if (service == NULL || service->task == NULL || job == NULL ||
        job->sequence == 0U || job->repetitions == 0U) {
        return AINEKIO_MOTION_SUBMIT_IO_ERROR;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool busy = service->active_sequence != 0U;
    if (!busy) {
        service->active_sequence = job->sequence;
        service->active_cancelled = false;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (busy) {
        return AINEKIO_MOTION_SUBMIT_BUSY;
    }

    if (job->kind == AINEKIO_MOTION_JOB_ASSET) {
        if (ainekio_asset_store_motion(service->assets, job->name) == NULL) {
            clear_active(service, job->sequence);
            return AINEKIO_MOTION_SUBMIT_ASSET_MISSING;
        }
        const esp_err_t loaded = ainekio_asset_store_load_motion(
            service->assets,
            job->name,
            &service->prepared_asset
        );
        if (loaded != ESP_OK) {
            clear_active(service, job->sequence);
            return loaded == ESP_ERR_INVALID_ARG ? AINEKIO_MOTION_SUBMIT_LIMIT
                                                 : AINEKIO_MOTION_SUBMIT_IO_ERROR;
        }
    } else if (job->kind == AINEKIO_MOTION_JOB_POSE &&
               ainekio_pose_bank_find(service->poses, job->name) == NULL) {
        clear_active(service, job->sequence);
        return AINEKIO_MOTION_SUBMIT_ASSET_MISSING;
    }

    taskENTER_CRITICAL(&service->state_lock);
    const bool preempted = service->active_cancelled;
    if (!preempted) {
        service->pending_job = *job;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (preempted) {
        return AINEKIO_MOTION_SUBMIT_PREEMPTED;
    }
    return AINEKIO_MOTION_SUBMIT_OK;
}

ainekio_motion_submit_result_t ainekio_motion_service_prepare_plan(
    ainekio_motion_service_t *service,
    uint32_t sequence,
    const ainekio_motion_plan_t *plan
)
{
    if (service == NULL || service->task == NULL || sequence == 0U ||
        !motion_plan_valid(plan)) {
        return AINEKIO_MOTION_SUBMIT_LIMIT;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool busy = service->active_sequence != 0U;
    if (!busy) {
        service->active_sequence = sequence;
        service->active_cancelled = false;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (busy) {
        return AINEKIO_MOTION_SUBMIT_BUSY;
    }

    ainekio_motion_asset_t *asset = &service->prepared_asset;
    memset(asset, 0, sizeof(*asset));
    (void)strcpy(asset->name, "motion_plan");
    asset->frame_count = plan->frame_count;
    asset->repeat_count = 1U;
    for (uint8_t frame_index = 0U; frame_index < plan->frame_count;
         ++frame_index) {
        const ainekio_motion_plan_frame_t *input = &plan->frames[frame_index];
        ainekio_motion_frame_t *output = &asset->frames[frame_index];
        output->duration_ms = input->duration_ms;
        output->target_count = AINEKIO_SERVO_COUNT;
        for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT;
             ++joint_id) {
            output->targets[joint_id].joint_id = joint_id;
            output->targets[joint_id].centidegrees = input->targets[joint_id];
        }
    }
    if (ainekio_motion_asset_check_limits(asset, service->servos) !=
        AINEKIO_ASSET_OK) {
        clear_active(service, sequence);
        return AINEKIO_MOTION_SUBMIT_LIMIT;
    }

    const ainekio_motion_job_t job = {
        .sequence = sequence,
        .kind = AINEKIO_MOTION_JOB_PLAN,
        .repetitions = 1U,
        .plan_end = plan->end,
    };
    taskENTER_CRITICAL(&service->state_lock);
    const bool preempted = service->active_cancelled;
    if (!preempted) {
        service->pending_job = job;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (preempted) {
        return AINEKIO_MOTION_SUBMIT_PREEMPTED;
    }
    return AINEKIO_MOTION_SUBMIT_OK;
}

ainekio_motion_submit_result_t ainekio_motion_service_commit(
    ainekio_motion_service_t *service,
    uint32_t sequence
)
{
    if (service == NULL || service->task == NULL || sequence == 0U) {
        return AINEKIO_MOTION_SUBMIT_IO_ERROR;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const bool matches = service->active_sequence == sequence;
    const bool preempted = service->active_cancelled;
    if (matches && !preempted) {
        service->job_pending = true;
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (!matches) {
        return AINEKIO_MOTION_SUBMIT_IO_ERROR;
    }
    if (preempted) {
        return AINEKIO_MOTION_SUBMIT_PREEMPTED;
    }
    (void)xTaskNotify(service->task, MOTION_NOTIFY_JOB, eSetBits);
    return AINEKIO_MOTION_SUBMIT_OK;
}

void ainekio_motion_service_abort(
    ainekio_motion_service_t *service,
    uint32_t sequence
)
{
    if (service != NULL && sequence != 0U) {
        clear_active(service, sequence);
    }
}

ainekio_motion_submit_result_t ainekio_motion_service_submit(
    ainekio_motion_service_t *service,
    const ainekio_motion_job_t *job
)
{
    const ainekio_motion_submit_result_t prepared =
        ainekio_motion_service_prepare(service, job);
    return prepared == AINEKIO_MOTION_SUBMIT_OK
               ? ainekio_motion_service_commit(service, job->sequence)
               : prepared;
}

static uint32_t request_stop_mode(
    ainekio_motion_service_t *service,
    bool detach
)
{
    if (service == NULL || service->task == NULL) {
        return 0U;
    }
    taskENTER_CRITICAL(&service->state_lock);
    const uint32_t cancelled = service->active_cancelled
                                   ? 0U
                                   : service->active_sequence;
    service->active_cancelled = true;
    service->job_pending = false;
    service->detach_requested = service->detach_requested || detach;
    taskEXIT_CRITICAL(&service->state_lock);
    (void)xTaskNotify(service->task, MOTION_NOTIFY_STOP, eSetBits);
    return cancelled;
}

uint32_t ainekio_motion_service_request_stop(ainekio_motion_service_t *service)
{
    return request_stop_mode(service, false);
}

uint32_t ainekio_motion_service_request_detach(ainekio_motion_service_t *service)
{
    return request_stop_mode(service, true);
}

void ainekio_motion_service_request_failsafe(ainekio_motion_service_t *service)
{
    if (service == NULL || service->task == NULL) {
        return;
    }
    bool should_hold = false;
    taskENTER_CRITICAL(&service->state_lock);
    should_hold = service->active_sequence != 0U;
    taskEXIT_CRITICAL(&service->state_lock);
    for (uint8_t index = 0U; !should_hold && index < AINEKIO_SERVO_COUNT; ++index) {
        should_hold = service->servos->channels[index].attached;
    }
    if (should_hold) {
        (void)ainekio_motion_service_request_stop(service);
    }
}

bool ainekio_motion_service_busy(const ainekio_motion_service_t *service)
{
    if (service == NULL) {
        return false;
    }
    taskENTER_CRITICAL((portMUX_TYPE *)&service->state_lock);
    const bool busy = service->active_sequence != 0U;
    taskEXIT_CRITICAL((portMUX_TYPE *)&service->state_lock);
    return busy;
}

ainekio_motion_submit_result_t ainekio_motion_service_calibrate_servo(
    ainekio_motion_service_t *service,
    uint8_t joint_id,
    float logical_degrees,
    uint16_t duration_ms
)
{
    if (service == NULL || service->task == NULL || joint_id >= AINEKIO_SERVO_COUNT ||
        duration_ms < 20U || duration_ms > 5000U) {
        return AINEKIO_MOTION_SUBMIT_LIMIT;
    }
    float physical = 0.0F;
    if (ainekio_servo_map_logical(
            &service->servos->channels[joint_id].calibration,
            logical_degrees,
            &physical
        ) != AINEKIO_SERVO_OK) {
        return AINEKIO_MOTION_SUBMIT_LIMIT;
    }
    (void)physical;
    taskENTER_CRITICAL(&service->state_lock);
    const bool busy = service->active_sequence != 0U;
    if (!busy) {
        service->calibration_degrees[joint_id] = logical_degrees;
        service->calibration_duration_ms[joint_id] = duration_ms;
        service->calibration_pending_mask |= (uint8_t)(1U << joint_id);
    }
    taskEXIT_CRITICAL(&service->state_lock);
    if (busy) {
        return AINEKIO_MOTION_SUBMIT_BUSY;
    }
    (void)xTaskNotify(service->task, MOTION_NOTIFY_CALIBRATION, eSetBits);
    return AINEKIO_MOTION_SUBMIT_OK;
}

bool ainekio_motion_service_begin_quiet_window(
    ainekio_motion_service_t *service,
    TickType_t timeout
)
{
    if (service == NULL || service->task == NULL) {
        return false;
    }
    (void)xSemaphoreTake(service->quiet_ready, 0U);
    (void)xSemaphoreTake(service->quiet_release, 0U);
    (void)xTaskNotify(service->task, MOTION_NOTIFY_QUIET, eSetBits);
    return xSemaphoreTake(service->quiet_ready, timeout) == pdTRUE;
}

void ainekio_motion_service_end_quiet_window(ainekio_motion_service_t *service)
{
    if (service != NULL && service->quiet_release != NULL) {
        (void)xSemaphoreGive(service->quiet_release);
    }
}
