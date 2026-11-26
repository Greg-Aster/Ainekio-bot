#include "body.h"
#include "board.h"
#include "config.h"
#include "joint_calibration.h"
#include "servo_feedback.h"
#include "system.h"
#include "trajectory_program.h"
#include "ainekio/p4_imu.h"
#include "ainekio/v1_model.h"
#include "ainekio/v2_limits.h"

#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

/* Single authoritative 8-DOF output owner for V1-on-P4 (v1-8servo).
 * Implements the exact body.h contract on PCA9685 channels 0..7. */

typedef struct {
    uint64_t generation, deadline;
    uint32_t serial;
    bool home, prepare, hold, execute, freestyle, walk_target;
    uint64_t connection;
    uint32_t sequence;
    union {
        ainekio_intent_t intent;
        ainekio_motion_plan_t plan;
        ainekio_walk_target_t nominal;
    };
    uint8_t channel;
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
} body_request_t;

typedef struct {
    uint32_t serial;
    esp_err_t result;
} body_result_t;

typedef enum {
    MOTION_NONE = 0,
    MOTION_POSE,
    MOTION_WALK,
    MOTION_PLAN,
    MOTION_IDLE_LAY,
} motion_kind_t;

static QueueHandle_t requests, results, events;
static SemaphoreHandle_t caller_lock;
static uint32_t request_serial;
static portMUX_TYPE state_lock = portMUX_INITIALIZER_UNLOCKED;

static uint16_t commanded_pulses[AINEKIO_PCA_BODY_CHANNELS];
static uint64_t commanded_us;
static ainekio_p4_body_status_t motion_status;
static ainekio_p4_execution_t execution_history[4];
static unsigned execution_history_next;
static ainekio_p4_body_timing_t timing;
static TaskHandle_t output_handle;

static bool listen_requested;
static uint64_t disconnected_through;
static esp_timer_handle_t rest_timer;
static atomic_bool rest_expired;
static atomic_uint activity_revision;
static unsigned last_activity_revision;
static bool rest_armed_timer;

static struct {
    motion_kind_t kind;
    uint64_t generation;
    uint64_t connection;
    uint32_t sequence;
    uint64_t started_us;
    const char *command_name;
    const char *activity_name;
    const char *phase_name;
    uint32_t face_revision;
    bool pose_is_lay_down;

    /* Current & goal 8-DOF model state (centidegrees in v2_frame_t slots 0..7). */
    ainekio_v2_frame_t current;
    float goal_cd[AINEKIO_BODY_JOINT_COUNT];
    float pose_speed_cd_s;

    /* Walk state */
    bool walk_host_nominal;
    bool walk_use_neural;
    float walk_twist[3]; /* vx m/s, vy m/s, wz rad/s */
    float walk_stride_pct;
    float walk_rate;
    uint8_t walk_steps; /* 0 = ongoing */
    double walk_phase;
    double walk_end_phase;
    uint32_t walk_nominal_sample;
    bool walk_have_nominal;
    float walk_nominal_feet_mm[4][3]; /* physical FL, FR, RL, RR */
    ainekio_v1_microduck_state_t microduck;

    /* Motion plan (map=1, 8 joints) */
    ainekio_motion_plan_t plan;
    uint8_t plan_frame;
    uint64_t plan_frame_started_us;
    float plan_frame_start_cd[AINEKIO_V1_JOINT_COUNT];

    /* 4th-wire feedback stall & thermal fuse */
    ainekio_p4_feedback_progress_t feedback_progress;
    ainekio_p4_feedback_thermal_t feedback_thermal;
    uint16_t thermal_cutoff_mask;
    uint16_t stalled_joints;
    uint64_t stall_clock_us;
} body;

/* Max command twist scaling for V1 MG90S quadruped (full supported speed). */
#define V1_WALK_MAX_VX_M_S 0.18f
#define V1_WALK_MAX_VY_M_S 0.10f
#define V1_WALK_MAX_WZ_RAD_S 1.50f
#define V1_TICK_US UINT64_C(20000)
#define V1_TICK_S 0.02f

static const char *posture_name_for_intent(const ainekio_intent_t *intent)
{
    if (!intent) return NULL;
    if (intent->kind == AINEKIO_INTENT_STAND) return "stand";
    if (intent->kind == AINEKIO_INTENT_NEUTRAL) return "neutral";
    if (intent->kind == AINEKIO_INTENT_SIT) return "sit";
    if (intent->kind == AINEKIO_INTENT_EMOTE) {
        float tmp[AINEKIO_V1_JOINT_COUNT];
        if (ainekio_v1_posture_angles(intent->data.asset, tmp)) return intent->data.asset;
    }
    return NULL;
}

void ainekio_p4_body_activity(void)
{
    atomic_fetch_add(&activity_revision, 1);
}

static void rest_timeout(void *arg)
{
    (void)arg;
    atomic_store(&rest_expired, true);
}

uint64_t ainekio_p4_body_curve_epoch(void)
{
    portENTER_CRITICAL(&state_lock);
    const uint64_t epoch = disconnected_through;
    portEXIT_CRITICAL(&state_lock);
    return epoch;
}

bool ainekio_p4_body_stage_curve(struct ainekio_p4_curve_program *program, uint64_t epoch)
{
    (void)epoch;
    ainekio_p4_curve_free(program);
    return false;
}

void ainekio_p4_body_discard_curve(const char *token)
{
    (void)token;
}

void ainekio_p4_body_connection_lost(uint64_t connection)
{
    portENTER_CRITICAL(&state_lock);
    if (connection > disconnected_through) disconnected_through = connection;
    portEXIT_CRITICAL(&state_lock);
}

void ainekio_p4_body_listen(bool active)
{
    portENTER_CRITICAL(&state_lock);
    listen_requested = active;
    portEXIT_CRITICAL(&state_lock);
}

ainekio_p4_body_timing_t ainekio_p4_body_timing(void)
{
    portENTER_CRITICAL(&state_lock);
    ainekio_p4_body_timing_t result = timing;
    portEXIT_CRITICAL(&state_lock);
    if (output_handle) result.stack_free_bytes = uxTaskGetStackHighWaterMark(output_handle);
    if (requests) result.queue_depth = uxQueueMessagesWaiting(requests);
    return result;
}

static void record_frame_timing(uint64_t calculation, uint64_t frame)
{
    portENTER_CRITICAL(&state_lock);
    if (calculation > timing.calculation_us) timing.calculation_us = (uint32_t)calculation;
    if (frame > timing.frame_us) timing.frame_us = (uint32_t)frame;
    timing.frames++;
    if (calculation > 2000U) timing.over_2ms++;
    if (frame > 5000U) timing.over_5ms++;
    portEXIT_CRITICAL(&state_lock);
}

static void publish_pulses(const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    const uint64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&state_lock);
    memcpy(commanded_pulses, pulses, sizeof(commanded_pulses));
    commanded_us = now;
    portEXIT_CRITICAL(&state_lock);
}

void ainekio_p4_body_pulses(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    uint64_t ts;
    bool armed;
    ainekio_p4_body_pulse_snapshot(pulses, &ts, &armed);
}

void ainekio_p4_body_pulse_snapshot(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS],
    uint64_t *published_us, bool *armed)
{
    portENTER_CRITICAL(&state_lock);
    memcpy(pulses, commanded_pulses, sizeof(commanded_pulses));
    *published_us = commanded_us;
    portEXIT_CRITICAL(&state_lock);
    *armed = ainekio_pca_status(ainekio_p4_output()).armed;
    if (!*armed) memset(pulses, 0, sizeof(commanded_pulses));
}

ainekio_p4_body_status_t ainekio_p4_body_status(void)
{
    portENTER_CRITICAL(&state_lock);
    const ainekio_p4_body_status_t result = motion_status;
    portEXIT_CRITICAL(&state_lock);
    return result;
}

ainekio_p4_execution_t ainekio_p4_body_execution_at(uint64_t timestamp_us)
{
    ainekio_p4_execution_t result = {0};
    portENTER_CRITICAL(&state_lock);
    bool found = false;
    uint64_t best = 0;
    for (unsigned i = 0; i < 4; ++i) {
        const ainekio_p4_execution_t *e = &execution_history[i];
        if (e->sampled_us && e->sampled_us <= timestamp_us && (!found || e->sampled_us >= best)) {
            result = *e;
            best = e->sampled_us;
            found = true;
        }
    }
    if (!found) result = motion_status.execution;
    portEXIT_CRITICAL(&state_lock);
    return result;
}

bool ainekio_p4_body_event(ainekio_p4_body_event_t *event)
{
    return event && events && xQueueReceive(events, event, 0) == pdTRUE;
}

static void emit_event(const ainekio_p4_body_event_t *event)
{
    if (events) (void)xQueueSend(events, event, 0);
}

static void publish_status(uint64_t now)
{
    const ainekio_p4_execution_t exec = {
        .command = body.command_name,
        .activity = body.activity_name ? body.activity_name : "idle",
        .phase = body.phase_name ? body.phase_name : "off",
        .sequence = body.sequence,
        .connection = body.connection,
        .started_us = body.started_us,
        .sampled_us = now,
        .expected_up = {0.0f, 0.0f, 1.0f},
        .expected_up_known = true,
        .host_nominal = body.walk_host_nominal,
        .nominal_sample = body.walk_nominal_sample,
    };
    ainekio_p4_body_status_t s = {
        .connection = body.connection,
        .sequence = body.sequence,
        .moving = body.kind != MOTION_NONE,
        .listening_feedback = listen_requested && body.kind == MOTION_NONE,
        .execution = exec,
        .stalled_joints = body.stalled_joints,
        .thermal_cutoff_mask = body.thermal_cutoff_mask,
        .stall_clock_us = body.stall_clock_us,
        .gait_cycles_s = body.kind == MOTION_WALK ? body.walk_rate : 0.0f,
        .gait_requested_cycles_s = body.kind == MOTION_WALK ? body.walk_rate : 0.0f,
        .stride_percent = body.kind == MOTION_WALK ? body.walk_stride_pct : 0.0f,
        .requested_stride_percent = body.kind == MOTION_WALK ? body.walk_stride_pct : 0.0f,
        .gait_valid = body.kind == MOTION_WALK,
        .gait_host_nominal = body.kind == MOTION_WALK && body.walk_host_nominal,
        .gait_phase = body.walk_phase,
        .face_command = body.command_name,
        .face_elapsed_us = body.started_us && now >= body.started_us ? now - body.started_us : 0U,
        .face_revision = body.face_revision,
        .face_is_clip = false,
    };
    memcpy(s.thermal_load, body.feedback_thermal.thermal_load, sizeof(s.thermal_load));
    portENTER_CRITICAL(&state_lock);
    motion_status = s;
    execution_history[execution_history_next & 3U] = exec;
    execution_history_next++;
    portEXIT_CRITICAL(&state_lock);
}

static esp_err_t submit(body_request_t *request)
{
    if (!caller_lock || xSemaphoreTake(caller_lock, pdMS_TO_TICKS(50)) != pdTRUE)
        return ESP_ERR_TIMEOUT;
    body_result_t result;
    while (xQueueReceive(results, &result, 0) == pdTRUE) {}
    request->serial = ++request_serial;
    request->deadline = esp_timer_get_time() + UINT64_C(100000);
    esp_err_t error = ESP_ERR_TIMEOUT;
    const uint32_t wait_ms = request->home ? 3000U : 150U;
    const int64_t reply_deadline = esp_timer_get_time() + (int64_t)wait_ms * 1000;
    TickType_t remaining = pdMS_TO_TICKS(wait_ms);
    if (xQueueSend(requests, request, 0) == pdTRUE) {
        while (xQueueReceive(results, &result, remaining) == pdTRUE) {
            if (result.serial == request->serial) {
                error = result.result;
                break;
            }
            const int64_t left_us = reply_deadline - esp_timer_get_time();
            if (left_us <= 0) break;
            remaining = pdMS_TO_TICKS((left_us + 999) / 1000);
        }
    }
    xSemaphoreGive(caller_lock);
    return error;
}

esp_err_t ainekio_p4_body_home(uint64_t generation,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    if (!pulses) return ESP_ERR_INVALID_ARG;
    for (size_t i = 0; i < AINEKIO_PCA_BODY_CHANNELS; ++i)
        if (pulses[i] && !ainekio_pca_pulse_valid(ainekio_p4_output(), pulses[i]))
            return ESP_ERR_INVALID_ARG;
    body_request_t request = {.generation = generation, .home = true};
    memcpy(request.pulses, pulses, sizeof(request.pulses));
    return submit(&request);
}

esp_err_t ainekio_p4_body_prepare(uint64_t generation)
{
    body_request_t request = {.generation = generation, .prepare = true};
    return submit(&request);
}

esp_err_t ainekio_p4_body_hold(uint64_t generation)
{
    body_request_t request = {.generation = generation, .hold = true};
    return submit(&request);
}

esp_err_t ainekio_p4_body_move(uint64_t generation, uint8_t channel, uint16_t pulse)
{
    if (channel >= AINEKIO_PCA_BODY_CHANNELS ||
        !ainekio_pca_pulse_valid(ainekio_p4_output(), pulse))
        return ESP_ERR_INVALID_ARG;
    body_request_t request = {.generation = generation, .channel = channel};
    request.pulses[channel] = pulse;
    return submit(&request);
}

bool ainekio_p4_body_supports(const ainekio_command_t *command)
{
    if (!command) return false;
    if (command->kind == AINEKIO_COMMAND_STOP || command->kind == AINEKIO_COMMAND_WALK_TARGET)
        return true;
    if (command->kind == AINEKIO_COMMAND_MOTION_PLAN) {
        return command->data.motion_plan.joint_map_version == AINEKIO_JOINT_MAP_VERSION &&
            command->data.motion_plan.frame_count > 0U;
    }
    if (command->kind != AINEKIO_COMMAND_INTENT) return false;
    if (command->data.intent.kind == AINEKIO_INTENT_WALK) return true;
    return posture_name_for_intent(&command->data.intent) != NULL;
}

esp_err_t ainekio_p4_body_execute(uint64_t generation, uint64_t connection,
    const ainekio_command_t *command)
{
    if (!ainekio_p4_body_supports(command)) return ESP_ERR_NOT_SUPPORTED;
    if (!connection || !command->sequence || command->sequence > AINEKIO_MAX_SEQUENCE)
        return ESP_ERR_INVALID_ARG;
    if (command->kind == AINEKIO_COMMAND_STOP)
        return command->data.stop.detach ? ESP_OK :
            ainekio_p4_body_hold(ainekio_pca_status(ainekio_p4_output()).generation);
    body_request_t request = {
        .generation = generation,
        .connection = connection,
        .sequence = command->sequence,
        .intent = command->data.intent,
        .execute = true,
    };
    if (command->kind == AINEKIO_COMMAND_MOTION_PLAN) {
        request.freestyle = true;
        request.plan = command->data.motion_plan;
    } else if (command->kind == AINEKIO_COMMAND_WALK_TARGET) {
        request.walk_target = true;
        request.execute = false;
        request.nominal = command->data.walk_target;
    }
    return submit(&request);
}

static esp_err_t pca_err(ainekio_pca_result_t r)
{
    switch (r) {
    case AINEKIO_PCA_OK: return ESP_OK;
    case AINEKIO_PCA_INVALID: return ESP_ERR_INVALID_ARG;
    case AINEKIO_PCA_STALE:
    case AINEKIO_PCA_DISARMED:
    case AINEKIO_PCA_BUSY: return ESP_ERR_INVALID_STATE;
    case AINEKIO_PCA_DEADLINE:
    case AINEKIO_PCA_TIMEOUT: return ESP_ERR_TIMEOUT;
    default: return ESP_FAIL;
    }
}

static void apply_thermal_cutoff(uint16_t mask, const ainekio_p4_joint_config_t *joints,
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    if (!mask) return;
    for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
        if ((mask & (1U << j)) && joints[j].channel >= 0)
            pulses[joints[j].channel] = 0U;
    }
}

static esp_err_t write_model_frame(uint64_t generation, const ainekio_v2_frame_t *frame,
    bool stagger_if_disarmed)
{
    const ainekio_p4_calibration_t cal = ainekio_p4_calibration();
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS] = {0};
    if (!ainekio_p4_frame_pulses(frame, pulses)) return ESP_ERR_INVALID_ARG;
    apply_thermal_cutoff(body.thermal_cutoff_mask, cal.joints, pulses);

    ainekio_pca9685_t *pca = ainekio_p4_output();
    const ainekio_pca_status_t st = ainekio_pca_status(pca);
    ainekio_pca_result_t res;
    if (!st.armed) {
        if (stagger_if_disarmed) {
            uint16_t staged[AINEKIO_PCA_BODY_CHANNELS] = {0};
            bool armed = false;
            for (unsigned ch = 0; ch < AINEKIO_V1_JOINT_COUNT; ++ch) {
                if (!pulses[ch]) continue;
                staged[ch] = pulses[ch];
                res = armed ? ainekio_pca_write_frame(pca, generation, staged)
                            : ainekio_pca_arm(pca, generation, staged);
                if (res != AINEKIO_PCA_OK) return pca_err(res);
                armed = true;
                publish_pulses(staged);
                vTaskDelay(pdMS_TO_TICKS(20));
            }
            if (!armed) return ESP_ERR_INVALID_STATE;
            return ESP_OK;
        }
        res = ainekio_pca_arm(pca, generation, pulses);
    } else {
        res = ainekio_pca_write_frame(pca, generation, pulses);
    }
    if (res == AINEKIO_PCA_OK) publish_pulses(pulses);
    return pca_err(res);
}

static void finish_motion(bool completed, ainekio_cancel_code_t reason, esp_err_t result, uint64_t now)
{
    const bool had_work = body.kind != MOTION_NONE && body.kind != MOTION_IDLE_LAY;
    const uint64_t conn = body.connection;
    const uint32_t seq = body.sequence;
    body.kind = MOTION_NONE;
    body.activity_name = "hold";
    body.phase_name = "hold";
    body.sequence = 0U;
    body.walk_host_nominal = false;
    body.walk_have_nominal = false;
    if (had_work && seq) {
        const ainekio_p4_body_event_t ev = {
            .connection = conn,
            .sequence = seq,
            .completed = completed,
            .reason = reason,
            .result = result,
            .stalled_joints = body.stalled_joints,
            .clock_us = now,
        };
        emit_event(&ev);
    }
}

static void seed_current_from_outputs(void)
{
    const ainekio_p4_calibration_t cal = ainekio_p4_calibration();
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    ainekio_p4_body_pulses(pulses);
    if (!ainekio_p4_joint_unmap_frame(cal.joints, pulses, &body.current)) {
        memset(&body.current, 0, sizeof(body.current));
        body.current.geometry_id = ainekio_v1_geometry_id;
    }
    /* Prefer live 4th-wire shaft measurement when calibrated and valid. */
    ainekio_p4_feedback_walk_frame(cal.joints, &body.current);
}

static void configure_walk_twist(const ainekio_intent_t *intent)
{
    const typeof(intent->data.walk) *w = &intent->data.walk;
    float gain = 1.0f;
    if (w->gait == AINEKIO_GAIT_CRAWL) gain = 0.55f;
    else if (w->gait == AINEKIO_GAIT_RUN) gain = 1.25f;

    float speed_scale = 1.0f;
    if (w->controls == 1U && isfinite(w->speed_percent) && w->speed_percent > 0.0f) {
        speed_scale = w->speed_percent / 100.0f;
        if (speed_scale > 2.0f) speed_scale = 2.0f;
    } else if (w->controls == 2U && isfinite(w->stride_percent) && w->stride_percent > 0.0f) {
        speed_scale = w->stride_percent / 100.0f;
        if (speed_scale > 2.0f) speed_scale = 2.0f;
    }

    float vx = 0.0f, vy = 0.0f, wz = 0.0f;
    if (w->host_nominal && (isfinite(w->twist[0]) || isfinite(w->twist[1]) || isfinite(w->twist[2]))) {
        vx = w->twist[0];
        vy = w->twist[1];
        wz = w->twist[2];
    } else if (w->steering) {
        vx = (w->forward / 100.0f) * V1_WALK_MAX_VX_M_S * gain * speed_scale;
        vy = (w->lateral / 100.0f) * V1_WALK_MAX_VY_M_S * gain * speed_scale;
        wz = (w->turn / 100.0f) * V1_WALK_MAX_WZ_RAD_S * gain * speed_scale;
    } else {
        switch (w->direction) {
        case AINEKIO_WALK_FORWARD:    vx = +V1_WALK_MAX_VX_M_S * gain * speed_scale; break;
        case AINEKIO_WALK_BACKWARD:   vx = -V1_WALK_MAX_VX_M_S * gain * speed_scale; break;
        case AINEKIO_WALK_TURN_LEFT:  wz = +V1_WALK_MAX_WZ_RAD_S * gain * speed_scale; break;
        case AINEKIO_WALK_TURN_RIGHT: wz = -V1_WALK_MAX_WZ_RAD_S * gain * speed_scale; break;
        case AINEKIO_WALK_SIDE_LEFT:  vy = +V1_WALK_MAX_VY_M_S * gain * speed_scale; break;
        case AINEKIO_WALK_SIDE_RIGHT: vy = -V1_WALK_MAX_VY_M_S * gain * speed_scale; break;
        }
    }
    body.walk_twist[0] = vx;
    body.walk_twist[1] = vy;
    body.walk_twist[2] = wz;
    body.walk_stride_pct = speed_scale * 100.0f;
    body.walk_rate = (w->controls == 2U && isfinite(w->motion_rate) && w->motion_rate > 0.1f)
        ? w->motion_rate : (1.5f * gain);
}

static esp_err_t handle_request(const body_request_t *req, uint64_t now)
{
    ainekio_pca9685_t *pca = ainekio_p4_output();
    if (req->prepare) {
        finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
        const ainekio_pca_result_t r = ainekio_pca_recover(pca, req->generation);
        uint16_t zeros[AINEKIO_PCA_BODY_CHANNELS] = {0};
        publish_pulses(zeros);
        return pca_err(r);
    }
    if (req->hold) {
        finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
        return ESP_OK;
    }
    if (req->home) {
        finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
        uint16_t staged[AINEKIO_PCA_BODY_CHANNELS] = {0};
        bool armed = ainekio_pca_status(pca).armed;
        for (unsigned ch = 0; ch < AINEKIO_V1_JOINT_COUNT; ++ch) {
            if (!req->pulses[ch]) continue;
            staged[ch] = req->pulses[ch];
            const ainekio_pca_result_t r = armed
                ? ainekio_pca_write_frame(pca, req->generation, staged)
                : ainekio_pca_arm(pca, req->generation, staged);
            if (r != AINEKIO_PCA_OK) return pca_err(r);
            armed = true;
            publish_pulses(staged);
            vTaskDelay(pdMS_TO_TICKS(20));
        }
        seed_current_from_outputs();
        body.command_name = "home";
        body.activity_name = "hold";
        body.phase_name = "home";
        body.face_revision++;
        return ESP_OK;
    }
    if (req->walk_target) {
        if (body.kind != MOTION_WALK || !body.walk_host_nominal ||
            req->nominal.walk_sequence != body.sequence) {
            return ESP_ERR_INVALID_STATE;
        }
        memcpy(body.walk_nominal_feet_mm, req->nominal.feet_mm, sizeof(body.walk_nominal_feet_mm));
        body.walk_nominal_sample = req->nominal.sample;
        body.walk_have_nominal = true;
        return ESP_OK;
    }
    if (!req->execute) {
        /* Single-channel calibration move */
        finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
        uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
        ainekio_p4_body_pulses(pulses);
        pulses[req->channel] = req->pulses[req->channel];
        const ainekio_pca_status_t st = ainekio_pca_status(pca);
        const ainekio_pca_result_t r = st.armed
            ? ainekio_pca_write_frame(pca, req->generation, pulses)
            : ainekio_pca_arm(pca, req->generation, pulses);
        if (r == AINEKIO_PCA_OK) {
            publish_pulses(pulses);
            seed_current_from_outputs();
        }
        return pca_err(r);
    }

    /* Check calibration validity before any model-driven motion. */
    const ainekio_p4_calibration_t cal = ainekio_p4_calibration();
    if (!cal.valid || !cal.profile_confirmed) return ESP_ERR_INVALID_STATE;

    if (req->freestyle) {
        /* 8-joint motion_plan (map=1): target streaming or timed keyframes. */
        const bool same_stream = body.kind == MOTION_PLAN && req->plan.target_control &&
            body.plan.target_control && body.connection == req->connection;
        if (!same_stream) {
            finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
            seed_current_from_outputs();
        }
        body.kind = MOTION_PLAN;
        body.generation = req->generation;
        body.connection = req->connection;
        body.sequence = req->sequence;
        body.started_us = now;
        body.command_name = "freestyle";
        body.activity_name = "motion_plan";
        body.phase_name = req->plan.target_control ? "targets" : "keyframe";
        body.plan = req->plan;
        body.plan_frame = 0U;
        body.plan_frame_started_us = now;
        for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
            body.plan_frame_start_cd[j] = body.current.position[j];
        body.face_revision++;
        return write_model_frame(req->generation, &body.current, true);
    }

    /* Walk intent */
    if (req->intent.kind == AINEKIO_INTENT_WALK) {
        const bool is_update = req->intent.data.walk.update_sequence != 0U &&
            body.kind == MOTION_WALK && body.sequence == req->intent.data.walk.update_sequence &&
            body.connection == req->connection;
        if (is_update) {
            configure_walk_twist(&req->intent);
            return ESP_OK;
        }
        finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
        seed_current_from_outputs();
        configure_walk_twist(&req->intent);
        body.kind = MOTION_WALK;
        body.generation = req->generation;
        body.connection = req->connection;
        body.sequence = req->sequence;
        body.started_us = now;
        body.command_name = "walk";
        body.activity_name = "walk";
        body.walk_host_nominal = req->intent.data.walk.host_nominal;
        body.walk_use_neural = !body.walk_host_nominal && ainekio_v1_microduck_default_model.trained;
        body.phase_name = body.walk_host_nominal ? "host_nominal"
                        : body.walk_use_neural ? "neural_gait" : "analytic_trot";
        body.walk_steps = req->intent.data.walk.steps;
        body.walk_phase = 0.0;
        body.walk_end_phase = body.walk_steps ? (double)body.walk_steps : 0.0;
        body.walk_have_nominal = false;
        body.walk_nominal_sample = 0U;
        ainekio_v1_microduck_reset(&body.microduck);
        body.face_revision++;
        return write_model_frame(req->generation, &body.current, true);
    }

    /* Named V1 posture (stand, neutral, sit, crouch, lay_down, bow, stretch, wave) */
    const char *pname = posture_name_for_intent(&req->intent);
    float target_deg[AINEKIO_V1_JOINT_COUNT] = {0};
    if (!pname || !ainekio_v1_posture_angles(pname, target_deg)) return ESP_ERR_NOT_FOUND;

    finish_motion(false, AINEKIO_CANCEL_STOP, ESP_OK, now);
    seed_current_from_outputs();
    memset(body.goal_cd, 0, sizeof(body.goal_cd));
    for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
        body.goal_cd[j] = target_deg[j] * 100.0f;

    /* Respect owner's configured joint speed limit and optional playback_rate. */
    float speed_deg_s = (float)ainekio_v2_gait_joint_speed_limit();
    if (!isfinite(speed_deg_s) || speed_deg_s <= 0.0f) speed_deg_s = AINEKIO_V1_MAX_SPEED_DEG_S;
    if (req->intent.playback_rate > 0.0f && isfinite(req->intent.playback_rate)) {
        const float scaled = (AINEKIO_V1_MAX_SPEED_DEG_S * 0.5f) * req->intent.playback_rate;
        if (scaled < speed_deg_s) speed_deg_s = scaled;
    }
    body.pose_speed_cd_s = speed_deg_s * 100.0f;
    body.kind = MOTION_POSE;
    body.generation = req->generation;
    body.connection = req->connection;
    body.sequence = req->sequence;
    body.started_us = now;
    body.command_name = pname;
    body.activity_name = "pose";
    body.phase_name = "moving";
    body.pose_is_lay_down = (!strcmp(pname, "lay_down") || !strcmp(pname, "rest") || !strcmp(pname, "sleep"));
    body.face_revision++;
    return write_model_frame(req->generation, &body.current, true);
}

static void step_walk(uint64_t now)
{
    const double dt = (double)V1_TICK_S;
    float next_deg[AINEKIO_V1_JOINT_COUNT] = {0};
    const float vx_norm = body.walk_twist[0] / V1_WALK_MAX_VX_M_S;
    const float vy_norm = body.walk_twist[1] / V1_WALK_MAX_VY_M_S;
    const float wz_norm = body.walk_twist[2] / V1_WALK_MAX_WZ_RAD_S;
    const float stride_scale = fmaxf(0.25f, fminf(1.5f, body.walk_stride_pct / 100.0f));

    if (body.walk_host_nominal && body.walk_have_nominal) {
        /* Host walk_nominal_v1 sends feet_mm in physical order [FL, FR, RL, RR].
         * V1 model leg order is [0:FR, 1:RR, 2:FL, 3:RL]. */
        static const ainekio_v1_leg_t phys_to_v1[4] = {
            AINEKIO_V1_LEG_FL, AINEKIO_V1_LEG_FR, AINEKIO_V1_LEG_RL, AINEKIO_V1_LEG_RR
        };
        for (unsigned p = 0; p < 4; ++p) {
            const ainekio_v1_leg_t v1_leg = phys_to_v1[p];
            float hip_deg = 0.0f, knee_deg = 0.0f;
            ainekio_v1_leg_ik_offset(v1_leg, body.walk_nominal_feet_mm[p], &hip_deg, &knee_deg);
            next_deg[ainekio_v1_legs[v1_leg].hip_joint] = hip_deg;
            next_deg[ainekio_v1_legs[v1_leg].knee_joint] = knee_deg;
        }
    } else if (body.walk_use_neural) {
        const ainekio_p4_imu_status_t imu = ainekio_p4_imu_status();
        const float q_default[4] = {1.0f, 0.0f, 0.0f, 0.0f};
        const float z3[3] = {0.0f, 0.0f, 0.0f};
        const float g3[3] = {0.0f, 0.0f, 9.81f};
        const float *quat = imu.attitude.available ? imu.attitude.orientation_wxyz : q_default;
        const float *gyro = imu.attitude.available ? imu.attitude.angular_rate_rad_s : z3;
        const float *accel = imu.attitude.available ? imu.attitude.acceleration_m_s2 : g3;

        /* Feed live 4th-wire joint positions/velocities when available, else commanded state. */
        ainekio_v2_frame_t obs = body.current;
        const ainekio_p4_calibration_t cal = ainekio_p4_calibration();
        ainekio_p4_feedback_walk_frame(cal.joints, &obs);
        float q_deg[AINEKIO_V1_JOINT_COUNT], dq_deg_s[AINEKIO_V1_JOINT_COUNT];
        for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
            q_deg[j] = obs.position[j] / 100.0f;
            dq_deg_s[j] = obs.velocity[j] / 100.0f;
        }
        const double t_s = (double)(now - body.started_us) * 1e-6;
        if (!ainekio_v1_microduck_step(&body.microduck, &ainekio_v1_microduck_default_model,
                t_s, q_deg, dq_deg_s, quat, gyro, accel, body.walk_twist, next_deg)) {
            ainekio_v1_walk_sample(body.walk_phase, vx_norm, vy_norm, wz_norm, stride_scale, next_deg);
        }
    } else {
        ainekio_v1_walk_sample(body.walk_phase, vx_norm, vy_norm, wz_norm, stride_scale, next_deg);
    }

    for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
        const float target_cd = ainekio_v1_clamp_joint_deg((uint8_t)j, next_deg[j]) * 100.0f;
        body.current.velocity[j] = (target_cd - body.current.position[j]) / V1_TICK_S;
        body.current.position[j] = target_cd;
    }

    body.walk_phase += (double)body.walk_rate * dt;
    const esp_err_t werr = write_model_frame(body.generation, &body.current, false);
    if (werr != ESP_OK) {
        finish_motion(false, AINEKIO_CANCEL_STOP, werr, now);
        return;
    }

    if (body.walk_steps > 0U && body.walk_phase >= body.walk_end_phase) {
        /* Finite walk completed: smoothly return to stand and signal done. */
        float stand_deg[AINEKIO_V1_JOINT_COUNT] = {0};
        ainekio_v1_posture_angles("stand", stand_deg);
        for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
            body.goal_cd[j] = stand_deg[j] * 100.0f;
        body.pose_speed_cd_s = (float)ainekio_v2_gait_joint_speed_limit() * 100.0f;
        body.kind = MOTION_POSE;
        body.phase_name = "returning";
        body.walk_host_nominal = false;
    }
}

static void step_plan(uint64_t now)
{
    if (body.plan.target_control) {
        /* Real-time target streaming (NeuralPose / Freestyle): ramp directly toward latest frame. */
        const ainekio_motion_plan_frame_t *f = &body.plan.frames[body.plan.frame_count - 1U];
        float goal[AINEKIO_BODY_JOINT_COUNT] = {0};
        for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) goal[j] = (float)f->targets[j];
        double speed_cd_s = f->speed_cd_s ? (double)f->speed_cd_s
            : ainekio_v2_gait_joint_speed_limit() * 100.0;
        ainekio_v2_frame_t next;
        if (!ainekio_p4_joint_ramp_frame(&body.current, goal, speed_cd_s, V1_TICK_S, &next)) {
            finish_motion(false, AINEKIO_CANCEL_STOP, ESP_ERR_INVALID_ARG, now);
            return;
        }
        body.current = next;
        const esp_err_t werr = write_model_frame(body.generation, &body.current, false);
        if (werr != ESP_OK) {
            finish_motion(false, AINEKIO_CANCEL_STOP, werr, now);
            return;
        }
        float max_err = 0.0f;
        for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
            max_err = fmaxf(max_err, fabsf(goal[j] - body.current.position[j]));
        if (max_err <= 25.0f) {
            finish_motion(true, AINEKIO_CANCEL_STOP, ESP_OK, now);
        }
        return;
    }

    /* Timed keyframe plan */
    const ainekio_motion_plan_frame_t *f = &body.plan.frames[body.plan_frame];
    const uint64_t dur_us = (uint64_t)f->duration_ms * 1000U;
    const uint64_t elapsed_us = now >= body.plan_frame_started_us ? now - body.plan_frame_started_us : 0U;
    const double u = dur_us ? fmin(1.0, (double)elapsed_us / (double)dur_us) : 1.0;
    for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
        const float start = body.plan_frame_start_cd[j];
        const float target = (float)f->targets[j];
        const float pos = ainekio_v1_clamp_joint_deg((uint8_t)j, (float)((start + u * (target - start)) / 100.0)) * 100.0f;
        body.current.velocity[j] = (pos - body.current.position[j]) / V1_TICK_S;
        body.current.position[j] = pos;
    }
    const esp_err_t werr = write_model_frame(body.generation, &body.current, false);
    if (werr != ESP_OK) {
        finish_motion(false, AINEKIO_CANCEL_STOP, werr, now);
        return;
    }
    if (u >= 1.0) {
        body.plan_frame++;
        if (body.plan_frame >= body.plan.frame_count) {
            if (body.plan.end == AINEKIO_MOTION_PLAN_END_STAND ||
                body.plan.end == AINEKIO_MOTION_PLAN_END_NEUTRAL) {
                float stand_deg[AINEKIO_V1_JOINT_COUNT] = {0};
                ainekio_v1_posture_angles("stand", stand_deg);
                for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
                    body.goal_cd[j] = stand_deg[j] * 100.0f;
                body.pose_speed_cd_s = (float)ainekio_v2_gait_joint_speed_limit() * 100.0f;
                body.kind = MOTION_POSE;
                body.phase_name = "returning";
            } else {
                finish_motion(true, AINEKIO_CANCEL_STOP, ESP_OK, now);
            }
        } else {
            body.plan_frame_started_us = now;
            for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
                body.plan_frame_start_cd[j] = body.current.position[j];
        }
    }
}

static void step_pose(uint64_t now)
{
    ainekio_v2_frame_t next;
    if (!ainekio_p4_joint_ramp_frame(&body.current, body.goal_cd, body.pose_speed_cd_s,
            V1_TICK_S, &next)) {
        finish_motion(false, AINEKIO_CANCEL_STOP, ESP_ERR_INVALID_ARG, now);
        return;
    }
    body.current = next;
    const esp_err_t werr = write_model_frame(body.generation, &body.current, false);
    if (werr != ESP_OK) {
        finish_motion(false, AINEKIO_CANCEL_STOP, werr, now);
        return;
    }
    float max_err = 0.0f;
    for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
        max_err = fmaxf(max_err, fabsf(body.goal_cd[j] - body.current.position[j]));
    if (max_err <= 25.0f) {
        if (body.kind == MOTION_IDLE_LAY) {
            ainekio_pca_idle(ainekio_p4_output());
            body.kind = MOTION_NONE;
            body.activity_name = "idle";
            body.phase_name = "rest";
        } else {
            finish_motion(true, AINEKIO_CANCEL_STOP, ESP_OK, now);
        }
    }
}

static void step_feedback_guard(uint64_t now)
{
    const ainekio_p4_calibration_t cal = ainekio_p4_calibration();
    const bool armed = ainekio_pca_status(ainekio_p4_output()).armed;
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    ainekio_p4_body_pulses(pulses);

    const uint16_t tripped = ainekio_p4_feedback_thermal_step(&body.feedback_thermal,
        cal.joints, pulses, armed, now);
    uint16_t next_cutoff = body.thermal_cutoff_mask | tripped;
    for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j) {
        if ((next_cutoff & (1U << j)) &&
            body.feedback_thermal.thermal_load[j] < AINEKIO_FEEDBACK_THERMAL_REARM_LOAD) {
            next_cutoff &= (uint16_t)~(1U << j);
        }
    }
    if (next_cutoff != body.thermal_cutoff_mask) {
        body.thermal_cutoff_mask = next_cutoff;
        if (armed && next_cutoff) {
            apply_thermal_cutoff(next_cutoff, cal.joints, pulses);
            if (ainekio_pca_write_frame(ainekio_p4_output(), body.generation, pulses) == AINEKIO_PCA_OK)
                publish_pulses(pulses);
        }
    }

    if (armed) {
        const uint16_t newly_stalled = ainekio_p4_feedback_stalled(&body.feedback_progress,
            cal.joints, pulses);
        if (newly_stalled) {
            body.stalled_joints |= newly_stalled;
            body.stall_clock_us = now;
            const ainekio_p4_body_event_t ev = {
                .connection = body.connection,
                .sequence = body.sequence,
                .jam_observation = true,
                .stalled_joints = newly_stalled,
                .clock_us = now,
            };
            emit_event(&ev);
        }
    } else {
        memset(&body.feedback_progress, 0, sizeof(body.feedback_progress));
        body.stalled_joints = 0U;
    }
}

static void update_idle_rest(uint64_t now)
{
    const unsigned rev = atomic_load(&activity_revision);
    const bool armed = ainekio_pca_status(ainekio_p4_output()).armed;
    const uint32_t rest_s = ainekio_p4_idle_rest_seconds();
    const bool eligible = armed && body.kind == MOTION_NONE && rest_s > 0U;

    if (!eligible) {
        if (rest_armed_timer) {
            esp_timer_stop(rest_timer);
            rest_armed_timer = false;
        }
        atomic_store(&rest_expired, false);
        last_activity_revision = rev;
        return;
    }

    if (!rest_armed_timer || rev != last_activity_revision) {
        esp_timer_stop(rest_timer);
        atomic_store(&rest_expired, false);
        esp_timer_start_once(rest_timer, (uint64_t)rest_s * UINT64_C(1000000));
        rest_armed_timer = true;
        last_activity_revision = rev;
        return;
    }

    if (atomic_exchange(&rest_expired, false)) {
        rest_armed_timer = false;
        float lay_deg[AINEKIO_V1_JOINT_COUNT] = {0};
        if (ainekio_v1_posture_angles("lay_down", lay_deg)) {
            seed_current_from_outputs();
            for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
                body.goal_cd[j] = lay_deg[j] * 100.0f;
            body.pose_speed_cd_s = 12000.0f; /* 120 deg/s gentle rest descent */
            body.generation = ainekio_pca_status(ainekio_p4_output()).generation;
            body.kind = MOTION_IDLE_LAY;
            body.command_name = "lay_down";
            body.activity_name = "rest";
            body.phase_name = "lowering";
            body.started_us = now;
            body.face_revision++;
        } else {
            ainekio_pca_idle(ainekio_p4_output());
        }
    }
}

static void body_task(void *arg)
{
    (void)arg;
    output_handle = xTaskGetCurrentTaskHandle();
    body.current.geometry_id = ainekio_v1_geometry_id;
    TickType_t last_wake = xTaskGetTickCount();

    for (;;) {
        const uint64_t frame_start = esp_timer_get_time();

        /* Drain pending control requests */
        body_request_t req;
        while (xQueueReceive(requests, &req, 0) == pdTRUE) {
            const uint64_t req_start = esp_timer_get_time();
            esp_err_t res = req_start > req.deadline ? ESP_ERR_TIMEOUT : handle_request(&req, req_start);
            const uint32_t req_us = (uint32_t)(esp_timer_get_time() - req_start);
            portENTER_CRITICAL(&state_lock);
            if (req_us > timing.request_us) timing.request_us = req_us;
            portEXIT_CRITICAL(&state_lock);
            const body_result_t reply = {.serial = req.serial, .result = res};
            (void)xQueueSend(results, &reply, 0);
        }

        const uint64_t now = esp_timer_get_time();

        /* Stop open-ended walk cleanly if its controlling session disconnected. */
        if (body.kind == MOTION_WALK && body.walk_steps == 0U && body.connection) {
            portENTER_CRITICAL(&state_lock);
            const bool lost = body.connection <= disconnected_through;
            portEXIT_CRITICAL(&state_lock);
            if (lost) {
                float stand_deg[AINEKIO_V1_JOINT_COUNT] = {0};
                ainekio_v1_posture_angles("stand", stand_deg);
                for (unsigned j = 0; j < AINEKIO_V1_JOINT_COUNT; ++j)
                    body.goal_cd[j] = stand_deg[j] * 100.0f;
                body.pose_speed_cd_s = (float)ainekio_v2_gait_joint_speed_limit() * 100.0f;
                body.kind = MOTION_POSE;
                body.phase_name = "returning";
                body.walk_host_nominal = false;
            }
        }

        /* Execute active 50 Hz motion frame */
        const uint64_t calc_start = esp_timer_get_time();
        switch (body.kind) {
        case MOTION_WALK:     step_walk(now); break;
        case MOTION_PLAN:     step_plan(now); break;
        case MOTION_POSE:
        case MOTION_IDLE_LAY: step_pose(now); break;
        case MOTION_NONE:     break;
        }
        const uint64_t calc_us = esp_timer_get_time() - calc_start;

        step_feedback_guard(now);
        update_idle_rest(now);
        publish_status(now);

        const uint64_t frame_us = esp_timer_get_time() - frame_start;
        record_frame_timing(calc_us, frame_us);

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(20));
    }
}

esp_err_t ainekio_p4_body_start(void)
{
    if (caller_lock) return ESP_ERR_INVALID_STATE;
    caller_lock = xSemaphoreCreateMutex();
    requests = xQueueCreate(4, sizeof(body_request_t));
    results = xQueueCreate(4, sizeof(body_result_t));
    events = xQueueCreate(8, sizeof(ainekio_p4_body_event_t));
    if (!caller_lock || !requests || !results || !events) return ESP_ERR_NO_MEM;
    const esp_timer_create_args_t timer_args = {
        .callback = rest_timeout,
        .name = "v1_idle_rest",
    };
    const esp_err_t terr = esp_timer_create(&timer_args, &rest_timer);
    if (terr != ESP_OK) return terr;
    if (xTaskCreate(body_task, "body_output_v1", 8192, NULL, 6, &output_handle) != pdPASS)
        return ESP_ERR_NO_MEM;
    return ESP_OK;
}
