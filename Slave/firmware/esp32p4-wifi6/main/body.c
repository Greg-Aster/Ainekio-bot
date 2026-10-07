#include "body.h"
#include "board.h"
#include "system.h"
#include "config.h"
#include "ainekio/v2_walk.h"
#include "ainekio/v2_limits.h"

#include <math.h>
#include <stdlib.h>

#include <string.h>
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

typedef struct {
    uint64_t generation, deadline;
    uint32_t serial;
    bool home, prepare, hold, execute;
    uint64_t connection;
    uint32_t sequence;
    ainekio_intent_t intent;
    uint8_t channel;
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
} body_request_t;
typedef struct { uint32_t serial; esp_err_t result; } body_result_t;
static QueueHandle_t requests, results, events;
static SemaphoreHandle_t caller_lock;
static uint32_t request_serial;
static portMUX_TYPE pulse_lock = portMUX_INITIALIZER_UNLOCKED;
static uint16_t commanded[AINEKIO_PCA_BODY_CHANNELS];
static ainekio_p4_body_status_t motion_status;
static ainekio_p4_body_timing_t timing;
static TaskHandle_t output_handle;
static bool listen_requested;

void ainekio_p4_body_listen(bool active)
{
    portENTER_CRITICAL(&pulse_lock);
    listen_requested = active;
    portEXIT_CRITICAL(&pulse_lock);
}

ainekio_p4_body_timing_t ainekio_p4_body_timing(void)
{
    portENTER_CRITICAL(&pulse_lock);
    ainekio_p4_body_timing_t result=timing;
    portEXIT_CRITICAL(&pulse_lock);
    if(output_handle)result.stack_free_bytes=uxTaskGetStackHighWaterMark(output_handle);
    if(requests)result.queue_depth=uxQueueMessagesWaiting(requests);
    return result;
}

static void record_frame_timing(uint64_t calculation,uint64_t frame)
{
    portENTER_CRITICAL(&pulse_lock);
    if(calculation>timing.calculation_us)timing.calculation_us=(uint32_t)calculation;
    if(frame>timing.frame_us)timing.frame_us=(uint32_t)frame;
    timing.frames++;
    if(calculation>2000)timing.over_2ms++;
    if(frame>5000)timing.over_5ms++;
    portEXIT_CRITICAL(&pulse_lock);
}

static void publish(const uint16_t *pulses)
{
    portENTER_CRITICAL(&pulse_lock);
    memcpy(commanded, pulses, sizeof(commanded));
    portEXIT_CRITICAL(&pulse_lock);
}

void ainekio_p4_body_pulses(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    portENTER_CRITICAL(&pulse_lock);
    memcpy(pulses, commanded, sizeof(commanded));
    portEXIT_CRITICAL(&pulse_lock);
    if (!ainekio_pca_status(ainekio_p4_output()).armed) memset(pulses, 0, sizeof(commanded));
}

static esp_err_t submit(body_request_t *request)
{
    if (!caller_lock || xSemaphoreTake(caller_lock, pdMS_TO_TICKS(50)) != pdTRUE) return ESP_ERR_TIMEOUT;
    body_result_t result;
    while (xQueueReceive(results, &result, 0) == pdTRUE) { }
    request->serial = ++request_serial;
    request->deadline = esp_timer_get_time() + UINT64_C(100000);
    esp_err_t error = ESP_ERR_TIMEOUT;
    if (xQueueSend(requests, request, 0) == pdTRUE &&
        xQueueReceive(results, &result, pdMS_TO_TICKS(request->home ? 3000 : 150)) == pdTRUE &&
        result.serial == request->serial) error = result.result;
    if (error == ESP_ERR_TIMEOUT)
        ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    xSemaphoreGive(caller_lock);
    return error;
}

esp_err_t ainekio_p4_body_home(uint64_t generation, const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    if (!pulses) return ESP_ERR_INVALID_ARG;
    for (size_t i=0; i<AINEKIO_PCA_BODY_CHANNELS; ++i)
        if (pulses[i] && !ainekio_pca_pulse_valid(ainekio_p4_output(), pulses[i])) return ESP_ERR_INVALID_ARG;
    body_request_t request = {.generation=generation, .home=true};
    memcpy(request.pulses, pulses, sizeof(request.pulses));
    return submit(&request);
}

esp_err_t ainekio_p4_body_prepare(uint64_t generation)
{
    body_request_t request = {.generation=generation, .prepare=true};
    return submit(&request);
}

/* A mode handoff cancels choreography in the output owner while keeping an
 * already commanded pose energized. Detached outputs remain detached. */
esp_err_t ainekio_p4_body_hold(uint64_t generation)
{
    body_request_t request = {.generation=generation, .hold=true};
    return submit(&request);
}

esp_err_t ainekio_p4_body_move(uint64_t generation, uint8_t channel, uint16_t pulse)
{
    if (channel >= AINEKIO_PCA_BODY_CHANNELS || !ainekio_pca_pulse_valid(ainekio_p4_output(), pulse))
        return ESP_ERR_INVALID_ARG;
    body_request_t request = {.generation=generation, .channel=channel};
    request.pulses[channel] = pulse;
    return submit(&request);
}

typedef enum { MOTION_NONE, MOTION_POSE, MOTION_WALK, MOTION_CLIP } motion_kind_t;
typedef struct {
    motion_kind_t kind;
    uint64_t connection, entry_start, entry_duration, started;
    uint32_t sequence;
    bool entering;
    size_t clip;
    float playback_rate, requested_rate;
    float entry_rate;
    const char *face_command;
    uint64_t face_elapsed_us;
    uint32_t face_revision;
    bool face_is_clip;
    uint16_t from[AINEKIO_PCA_BODY_CHANNELS], target[AINEKIO_PCA_BODY_CHANNELS];
    ainekio_v2_walk_state_t walk;
    ainekio_v2_frame_t entry_from, entry_to;
} motion_t;
typedef struct {
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS], targets[AINEKIO_PCA_BODY_CHANNELS];
    bool active, ramping;
    uint64_t generation, next_frame, last_frame, next_channel_at;
    size_t next_channel;
    uint32_t pending_home;
    motion_t motion;
    struct {
        bool active, engaged;
        uint64_t started, duration;
        ainekio_v2_frame_t base, from, target;
        uint16_t base_pulses[AINEKIO_PCA_BODY_CHANNELS];
    } listen;
    /* Last successfully written target in model coordinates, never feedback. */
    ainekio_v2_frame_t pose;
    ainekio_p4_joint_config_t pose_mapping[AINEKIO_BODY_JOINT_COUNT];
    bool pose_valid;
} body_state_t;
static body_state_t body;

static void publish_motion(void)
{
    const ainekio_p4_body_status_t value = {
        .connection=body.motion.connection, .sequence=body.motion.sequence,
        .moving=body.motion.kind != MOTION_NONE,
        .listening_feedback=body.listen.active,
        .face_command=body.motion.face_command,
        .face_elapsed_us=body.motion.face_elapsed_us,
        .face_revision=body.motion.face_revision,
        .face_is_clip=body.motion.face_is_clip,
        .face_entering=body.motion.entering,
        .face_clip=body.motion.clip,
        .automatic_run=body.motion.kind==MOTION_WALK && body.motion.walk.automatic_run,
        .gait_cycles_s=body.motion.kind==MOTION_WALK && !body.motion.entering ? body.motion.walk.cycles_s : 0.F,
        .gait_requested_cycles_s=body.motion.kind==MOTION_WALK ? body.motion.walk.requested_cycles_s : 0.F,
        .stride_percent=body.motion.kind==MOTION_WALK ? body.motion.walk.stride_percent : 0.F,
        .requested_stride_percent=body.motion.kind==MOTION_WALK ? body.motion.walk.requested_stride_percent : 0.F,
        .speed_limited=body.motion.kind != MOTION_NONE && (body.motion.entering
            ? body.motion.entry_rate < body.motion.requested_rate
            : body.motion.kind == MOTION_WALK ? body.motion.walk.speed_flagged
            : body.motion.playback_rate < body.motion.requested_rate),
    };
    portENTER_CRITICAL(&pulse_lock);
    motion_status = value;
    portEXIT_CRITICAL(&pulse_lock);
}

ainekio_p4_body_status_t ainekio_p4_body_status(void)
{
    portENTER_CRITICAL(&pulse_lock);
    const ainekio_p4_body_status_t value = motion_status;
    portEXIT_CRITICAL(&pulse_lock);
    return value;
}

bool ainekio_p4_body_event(ainekio_p4_body_event_t *event)
{
    return event && events && xQueueReceive(events, event, 0) == pdTRUE;
}

bool ainekio_p4_body_supports(const ainekio_command_t *command)
{
    if (!command || command->kind != AINEKIO_COMMAND_INTENT) return false;
    uint8_t cycles;
    size_t clip;
    return command->data.intent.kind == AINEKIO_INTENT_STAND ||
        command->data.intent.kind == AINEKIO_INTENT_NEUTRAL ||
        ainekio_v2_walk_request(command, &cycles) || ainekio_v2_clip_request(command, &clip);
}

esp_err_t ainekio_p4_body_execute(uint64_t generation, uint64_t connection,
    const ainekio_command_t *command)
{
    if (!ainekio_p4_body_supports(command)) return ESP_ERR_NOT_SUPPORTED;
    if (!connection || !command->sequence || command->sequence > AINEKIO_MAX_SEQUENCE)
        return ESP_ERR_INVALID_ARG;
    body_request_t request = {.generation=generation, .connection=connection,
        .sequence=command->sequence, .intent=command->data.intent, .execute=true};
    return submit(&request);
}

static void finish_motion(bool completed, esp_err_t result)
{
    if (body.motion.kind == MOTION_NONE) {
        if(!completed && body.motion.face_command){
            body.motion.face_command=NULL;
            body.motion.face_elapsed_us=0;
            body.motion.face_is_clip=false;
            ++body.motion.face_revision;
            publish_motion();
        }
        return;
    }
    const ainekio_p4_body_event_t event = {.connection=body.motion.connection,
        .sequence=body.motion.sequence, .completed=completed, .reason=AINEKIO_CANCEL_STOP,
        .result=result};
    /* Admission reserves two slots: replacement and eventual completion. There
     * is one producer, and a reader can only increase the available space. */
    if (xQueueSend(events, &event, 0) != pdTRUE)
        ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    if (!completed) {
        body.motion.face_command = NULL;
        body.motion.face_elapsed_us = 0;
        body.motion.face_is_clip = false;
        ++body.motion.face_revision;
    } else if (body.motion.kind == MOTION_WALK) {
        body.motion.face_command = "stand";
        body.motion.face_elapsed_us = 0;
    }
    body.motion.kind = MOTION_NONE;
    body.motion.entering = false;
    publish_motion();
}

static void stop_body(esp_err_t result)
{
    body.listen.active = false;
    ainekio_p4_body_listen(false);
    finish_motion(false, result);
    body.active = body.ramping = body.pose_valid = false;
    memset(body.pulses, 0, sizeof(body.pulses));
    publish(body.pulses);
    if (body.pending_home) {
        const body_result_t stopped = {.serial=body.pending_home, .result=ESP_ERR_INVALID_STATE};
        xQueueOverwrite(results, &stopped);
        body.pending_home = 0;
    }
}

static void fail_motion(esp_err_t result)
{
    ainekio_pca_emergency_disable(ainekio_p4_output(), result == ESP_ERR_TIMEOUT ?
        AINEKIO_PCA_FAULT_PROGRESS : AINEKIO_PCA_FAULT_EMERGENCY);
    stop_body(result);
}

static bool any_pulses(const uint16_t *pulses)
{
    for (size_t i=0; i<AINEKIO_PCA_BODY_CHANNELS; ++i) if (pulses[i]) return true;
    return false;
}

/* Used by explicit Home and motion startup; engage one assigned channel per step. */
static bool home_channel(const uint16_t *targets, uint16_t *pulses, size_t *next)
{
    while (*next < AINEKIO_PCA_BODY_CHANNELS && !targets[*next]) ++*next;
    if (*next < AINEKIO_PCA_BODY_CHANNELS) {
        pulses[*next] = targets[*next];
        ++*next;
    }
    while (*next < AINEKIO_PCA_BODY_CHANNELS && !targets[*next]) ++*next;
    return *next < AINEKIO_PCA_BODY_CHANNELS;
}

static void retain_pose(const ainekio_v2_frame_t *frame,
                        const ainekio_p4_calibration_t *calibration)
{
    body.pose=*frame;
    memcpy(body.pose_mapping,calibration->joints,sizeof(body.pose_mapping));
    body.pose_valid=true;
}

static void retain_manual_reference(void)
{
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    ainekio_v2_frame_t frame;
    body.pose_valid=false;
    if(calibration.valid && ainekio_p4_joint_unmap_frame(calibration.joints,body.pulses,&frame))
        retain_pose(&frame,&calibration);
}

static esp_err_t start_motion(const body_request_t *request, uint64_t now)
{
    const ainekio_command_t command = {.sequence=request->sequence,
        .kind=AINEKIO_COMMAND_INTENT, .data.intent=request->intent};
    const bool update = request->intent.kind == AINEKIO_INTENT_WALK &&
        request->intent.data.walk.update_sequence != 0;
    if (update) {
        if (body.motion.kind != MOTION_WALK || body.motion.connection != request->connection)
            return ESP_ERR_INVALID_STATE;
        /* Updates apply at the last locally sampled frame. They never advance
         * or reset the output clock, and never acquire their own completion. */
        return ainekio_v2_walk_accept(&body.motion.walk, &command, body.motion.walk.last_us)
            ? ESP_OK : ESP_ERR_INVALID_ARG;
    }
    const bool named = request->intent.kind == AINEKIO_INTENT_SIT ||
        request->intent.kind == AINEKIO_INTENT_STAND || request->intent.kind == AINEKIO_INTENT_EMOTE;
    const float override = request->intent.playback_rate;
    if (override && (!named || !isfinite(override) || override < 0.F))
        return ESP_ERR_INVALID_ARG;
    if (uxQueueSpacesAvailable(events) < 2) return ESP_ERR_NO_MEM;
    motion_t next = {.connection=request->connection, .sequence=request->sequence,
        .face_revision=body.motion.face_revision+1,
        .face_command="stand",
        .entry_start=now, .entry_duration=UINT64_C(500000), .entering=true,
        .playback_rate=named ? (override ? override : ainekio_p4_motion_rate()) : 1.F};
    next.requested_rate = next.playback_rate;
    ainekio_v2_frame_t frame = {.geometry_id=ainekio_v2_walk_geometry_id};
    if (request->intent.kind == AINEKIO_INTENT_WALK) {
        next.kind = MOTION_WALK;
        if (!ainekio_v2_walk_accept(&next.walk, &command, now)) return ESP_ERR_INVALID_ARG;
        next.face_command=next.walk.gait_mode==AINEKIO_GAIT_CRAWL ? "crawl" :
            next.walk.gait_mode==AINEKIO_GAIT_CRAB ? "crab" :
            next.walk.gait_mode==AINEKIO_GAIT_RUN ? "run" : "walk";
        frame = next.walk.pose.frame;
    } else if (request->intent.kind == AINEKIO_INTENT_STAND) {
        ainekio_v2_walk_pose_t pose;
        next.kind = MOTION_POSE;
        if (!ainekio_v2_walk_pose(0, (ainekio_v2_walk_controls_t){0,1}, &pose))
            return ESP_ERR_INVALID_ARG;
        frame = pose.frame;
    } else if (request->intent.kind == AINEKIO_INTENT_NEUTRAL) {
        next.kind = MOTION_POSE;
    } else {
        next.kind = MOTION_CLIP;
        if (!ainekio_v2_clip_request(&command, &next.clip) ||
            !ainekio_v2_clip_sample(next.clip, 0, &frame)) return ESP_ERR_NOT_SUPPORTED;
        next.playback_rate = ainekio_v2_clip_playback_rate(next.clip, next.playback_rate);
        next.face_command = ainekio_v2_clips[next.clip].command;
        next.face_is_clip = true;
        ainekio_v2_frame_t minimum, maximum;
        uint16_t checked[AINEKIO_PCA_BODY_CHANNELS];
        /* A fitting first frame is insufficient: reject an unreachable clip
         * before replacing the current motion or writing any PWM. Each joint's
         * linear calibrated mapping is bounded by its two angle extrema. */
        if (!ainekio_v2_clip_bounds(next.clip, &minimum, &maximum) ||
            !ainekio_p4_frame_pulses(&minimum, checked) ||
            !ainekio_p4_frame_pulses(&maximum, checked)) return ESP_ERR_INVALID_ARG;
    }
    if (!ainekio_p4_frame_pulses(&frame, next.target) || !any_pulses(next.target))
        return ESP_ERR_INVALID_ARG;
    const ainekio_p4_calibration_t calibration = ainekio_p4_calibration();
    if (!calibration.valid || !calibration.profile_confirmed) return ESP_ERR_INVALID_STATE;
    bool home = !ainekio_pca_status(ainekio_p4_output()).armed || !body.pose_valid ||
        memcmp(body.pose_mapping,calibration.joints,sizeof(body.pose_mapping));
    for (unsigned i=0; i<AINEKIO_PCA_BODY_CHANNELS; ++i)
        if (calibration.joints[i].channel >= 0 && !body.pulses[calibration.joints[i].channel]) home = true;
    if (home) {
        if (!ainekio_p4_home_pulses(next.from)) return ESP_ERR_INVALID_ARG;
    } else memcpy(next.from, body.pulses, sizeof(next.from));
    /* A new operator motion request establishes Home when outputs are off or
     * only partly commanded. Validate that reference and the entry before PWM. */
    if (home) {
        next.entry_from.geometry_id=ainekio_v2_walk_geometry_id;
        for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++)
            next.entry_from.position[i]=calibration.joints[i].home_cd;
    } else next.entry_from=body.pose;
    if(!ainekio_v2_limits_frame(&next.entry_from))return AINEKIO_P4_ERR_REFERENCE;
    next.entry_to = frame;
    ainekio_v2_frame_t path_minimum, path_maximum;
    double derivatives[AINEKIO_PCA_BODY_CHANNELS];
    uint16_t checked[AINEKIO_PCA_BODY_CHANNELS];
    if (!ainekio_v2_transition_bounds(&next.entry_from, &next.entry_to,
        &path_minimum, &path_maximum, derivatives) ||
        !ainekio_p4_frame_pulses(&path_minimum, checked) ||
        !ainekio_p4_frame_pulses(&path_maximum, checked)) return ESP_ERR_INVALID_ARG;
    for(unsigned i=0;i<AINEKIO_PCA_BODY_CHANNELS;i++)if(!next.target[i])next.from[i]=0;
    double entry_peak=0.;
    for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++)
        if(calibration.joints[i].channel>=0)
            entry_peak=fmax(entry_peak,derivatives[i]/100.*1.875e6/next.entry_duration);
    next.entry_rate=ainekio_v2_speed_limited_rate(entry_peak,next.requested_rate);
    ainekio_pca9685_t *output = ainekio_p4_output();
    if ((uint64_t)esp_timer_get_time() >= request->deadline) return ESP_ERR_TIMEOUT;
    const ainekio_pca_status_t status = ainekio_pca_status(output);
    uint16_t initial[AINEKIO_PCA_BODY_CHANNELS] = {0};
    size_t next_channel = 0;
    bool ramping = false;
    if (home) ramping = home_channel(next.from, initial, &next_channel);
    else memcpy(initial, next.from, sizeof(initial));
    ainekio_pca_result_t result = AINEKIO_PCA_OK;
    if (!status.armed) result = ainekio_pca_recover(output, request->generation);
    if (result == AINEKIO_PCA_OK)
        result = status.armed ? ainekio_pca_write_frame(output, request->generation, initial)
                              : ainekio_pca_arm(output, request->generation, initial);
    if (result != AINEKIO_PCA_OK) return ESP_ERR_INVALID_STATE;
    finish_motion(false, ESP_OK);
    body.listen.active = false; /* Enter the new motion from the actual cue pose. */
    body.motion = next;
    retain_pose(&next.entry_from,&calibration);
    body.pose_valid=!ramping;
    body.active = true;
    body.ramping = ramping;
    body.next_channel = next_channel;
    memcpy(body.targets, next.from, sizeof(body.targets));
    body.generation = request->generation;
    body.last_frame = esp_timer_get_time();
    body.motion.entry_start = body.last_frame;
    body.next_channel_at = body.last_frame + UINT64_C(200000);
    body.next_frame = body.last_frame + UINT64_C(20000);
    memcpy(body.pulses, initial, sizeof(body.pulses));
    publish(body.pulses);
    publish_motion();
    return ESP_OK;
}

static esp_err_t motion_frame(uint64_t now, bool *complete, ainekio_v2_frame_t *sampled)
{
    motion_t *motion = &body.motion;
    *complete = false;
    if (motion->entering) {
        const float u = fminf(1.F, ((float)(now-motion->entry_start)/motion->entry_duration) * motion->entry_rate);
        /* Evaluate the nearer half in double. Mixed-precision u*u*u rounded
         * the upper end above 1 and rejected otherwise valid entry frames. */
        const double half = u <= .5F ? u : 1.-u;
        const double ramp = half*half*half*(10.+half*(-15.+6.*half));
        const double smooth = u <= .5F ? ramp : 1.-ramp;
        ainekio_v2_frame_t entry;
        if (!ainekio_v2_transition(&motion->entry_from, &motion->entry_to, smooth, &entry) ||
            !ainekio_p4_frame_pulses(&entry, body.pulses)) return ESP_ERR_INVALID_ARG;
        if (u == 1.) {
            motion->entering = false;
            motion->started = now;
            if (motion->kind == MOTION_WALK) motion->walk.last_us = now;
            *complete = motion->kind == MOTION_POSE;
        }
        *sampled=entry;
        return ESP_OK;
    }
    ainekio_v2_frame_t frame;
    if (motion->kind == MOTION_WALK) {
        if (now < motion->walk.last_us ||
            now-motion->walk.last_us > AINEKIO_PCA_PROGRESS_LIMIT_US) return ESP_ERR_TIMEOUT;
        if (!ainekio_v2_walk_tick(&motion->walk, now)) return ESP_FAIL;
        frame = motion->walk.pose.frame;
        motion->face_command=motion->walk.gait_mode==AINEKIO_GAIT_CRAWL ? "crawl" :
            motion->walk.gait_mode==AINEKIO_GAIT_CRAB ? "crab" :
            motion->walk.pose.run_blend>.5 ? "run" : "walk";
        motion->face_elapsed_us=(uint64_t)(motion->walk.phase*1000000.);
        *complete = motion->walk.complete;
    } else {
        if (now < motion->started) return ESP_ERR_TIMEOUT;
        const uint64_t duration = ainekio_v2_clips[motion->clip].duration_us;
        const uint64_t elapsed = now - motion->started;
        const float progress = (float)elapsed * motion->playback_rate;
        const uint64_t sample = progress >= duration ? duration : (uint64_t)progress;
        if (!ainekio_v2_clip_sample(motion->clip, sample, &frame)) return ESP_FAIL;
        motion->face_elapsed_us=sample;
        *complete = frame.phase == AINEKIO_V2_COMPLETE;
    }
    if(!ainekio_p4_frame_pulses(&frame,body.pulses))return ESP_ERR_INVALID_ARG;
    *sampled=frame;return ESP_OK;
}

/* The shoulder axis rotates the complete linkage, leaving carrier/crank
 * closure unchanged. Model joints 6 and 9 are the physical front shoulders;
 * their CAD transforms and saved mapper handle the mirrored hardware. */
static esp_err_t listen_frame(uint64_t now, ainekio_v2_frame_t *sampled, bool *sampling)
{
    portENTER_CRITICAL(&pulse_lock);
    const bool requested = listen_requested;
    portEXIT_CRITICAL(&pulse_lock);
    *sampling = false;
    if (!body.pose_valid || (!requested && !body.listen.active)) return ESP_OK;
    if (!body.listen.active || requested != body.listen.engaged) {
        if (!body.listen.active) {
            body.listen.base = body.pose;
            memcpy(body.listen.base_pulses, body.pulses, sizeof(body.pulses));
        }
        body.listen.from = body.pose;
        body.listen.target = body.listen.base;
        if (requested) {
            body.listen.target.position[6] += 600.F;
            body.listen.target.position[9] += 600.F;
        }
        uint16_t checked[AINEKIO_PCA_BODY_CHANNELS];
        if (!ainekio_p4_frame_pulses(&body.listen.target, checked)) return ESP_ERR_INVALID_ARG;
        double largest = 0;
        for (unsigned i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i)
            largest = fmax(largest, fabs(body.listen.target.position[i] - body.listen.from.position[i]) / 100.);
        /* Same owner-selected joint-speed ceiling as every other motion. */
        body.listen.duration = (uint64_t)ceil(fmax(300000., largest * 1.875e6 / ainekio_v2_gait_joint_speed_limit()));
        body.listen.started = now;
        body.listen.engaged = requested;
        body.listen.active = true;
    }
    const double u = fmin(1., (double)(now - body.listen.started) / body.listen.duration);
    const double smooth = u*u*u*(10.+u*(-15.+6.*u));
    *sampled = body.listen.base;
    for (unsigned i = 0; i < AINEKIO_BODY_JOINT_COUNT; ++i) {
        sampled->position[i] = u == 1. ? body.listen.target.position[i] :
            (float)(body.listen.from.position[i] + smooth * (body.listen.target.position[i] - body.listen.from.position[i]));
        sampled->velocity[i] = sampled->acceleration[i] = 0;
    }
    uint16_t mapped[AINEKIO_PCA_BODY_CHANNELS];
    if (!ainekio_p4_frame_pulses(sampled, mapped)) return ESP_ERR_INVALID_ARG;
    /* Keep every unmodified output bit-for-bit, including manual pulse targets. */
    memcpy(body.pulses, body.listen.base_pulses, sizeof(body.pulses));
    const unsigned shoulders[] = {6, 9};
    for (unsigned i = 0; i < 2; ++i) {
        const int channel = body.pose_mapping[shoulders[i]].channel;
        if (channel >= 0 && body.listen.base_pulses[channel]) body.pulses[channel] = mapped[channel];
    }
    if (u == 1. && !requested) {
        *sampled = body.listen.base;
        memcpy(body.pulses, body.listen.base_pulses, sizeof(body.pulses));
        body.listen.active = false;
    }
    *sampling = true;
    return ESP_OK;
}

/* One local output clock drives entry, algorithms, finite clips and holding.
 * Stop/generation fencing is checked before sampling and again by the driver. */
static bool output_step(uint64_t now)
{
    ainekio_pca9685_t *output = ainekio_p4_output();
    ainekio_pca_status_t status = ainekio_pca_status(output);
    if (body.active && (!status.armed || status.generation != body.generation)) {
        const esp_err_t error = status.fault == AINEKIO_PCA_FAULT_IO ? ESP_FAIL :
            status.fault == AINEKIO_PCA_FAULT_DEADLINE || status.fault == AINEKIO_PCA_FAULT_PROGRESS ?
            ESP_ERR_TIMEOUT : ESP_OK;
        stop_body(error);
    }
    if (!body.active || now < body.next_frame) return false;
    if (now < body.last_frame || now-body.last_frame > AINEKIO_PCA_PROGRESS_LIMIT_US) {
        fail_motion(ESP_ERR_TIMEOUT);
        return false;
    }
    const uint64_t frame_started=esp_timer_get_time();
    bool complete = false;
    const bool was_ramping=body.ramping;
    ainekio_v2_frame_t sampled=body.pose;
    bool sampling=!body.ramping && body.motion.kind!=MOTION_NONE;
    if (body.ramping) {
        if (now >= body.next_channel_at) {
            body.ramping = home_channel(body.targets, body.pulses, &body.next_channel);
            body.next_channel_at = now + UINT64_C(200000);
            if (!body.ramping) body.motion.entry_start = now;
        }
    } else if (body.motion.kind != MOTION_NONE) {
        const esp_err_t error = motion_frame(now, &complete, &sampled);
        if (error != ESP_OK) {
            fail_motion(error);
            return false;
        }
    } else {
        const esp_err_t error = listen_frame(now, &sampled, &sampling);
        if (error != ESP_OK) { fail_motion(error); return false; }
    }
    const uint64_t calculated=esp_timer_get_time();
    const ainekio_pca_result_t write_result=ainekio_pca_write_frame(output,body.generation,body.pulses);
    record_frame_timing(calculated-frame_started,(uint64_t)esp_timer_get_time()-frame_started);
    if (write_result != AINEKIO_PCA_OK) {
        fail_motion(ESP_FAIL);
        return false;
    }
    if(sampling) { body.pose=sampled;body.pose_valid=true; }
    else if(was_ramping && !body.ramping)retain_manual_reference();
    publish(body.pulses);
    publish_motion();
    body.last_frame = esp_timer_get_time();
    /* Compute/write time consumes this frame's budget instead of extending the
     * next interval. If late, sample the current time once; never replay missed
     * frames. Completion time remains the independent output progress clock. */
    body.next_frame = now + UINT64_C(20000);
    if (complete) finish_motion(true, ESP_OK);
    if (body.pending_home && !body.ramping) {
        const body_result_t finished = {.serial=body.pending_home, .result=ESP_OK};
        xQueueOverwrite(results, &finished);
        body.pending_home = 0;
    }
    return true;
}

static esp_err_t process_request(const body_request_t *request, uint64_t now)
{
    ainekio_pca9685_t *output = ainekio_p4_output();
    const ainekio_pca_status_t status = ainekio_pca_status(output);
    if (now >= request->deadline || status.generation != request->generation)
        return ESP_ERR_INVALID_STATE;
    const ainekio_p4_system_status_t system = ainekio_p4_system_status();
    if (!request->prepare && (system.restart_pending || system.state == AINEKIO_STATE_DOZING ||
                             system.state == AINEKIO_STATE_DEEP_SLEEP)) return ESP_ERR_INVALID_STATE;
    if (request->hold) {
        body.listen.active = false;
        ainekio_p4_body_listen(false);
        finish_motion(false, ESP_OK);
        body.ramping = false;
        if (!status.armed) stop_body(ESP_OK);
        return ESP_OK;
    }
    if (request->execute) return start_motion(request, now);
    if (request->prepare && status.armed) return ESP_ERR_INVALID_STATE;
    if (!status.armed && ainekio_pca_recover(output, request->generation) != AINEKIO_PCA_OK)
        return ESP_ERR_INVALID_STATE;
    body.listen.active = false;
    ainekio_p4_body_listen(false);
    finish_motion(false, ESP_OK);
    if (request->prepare) return ESP_OK;
    if (request->home) {
        memcpy(body.targets, request->pulses, sizeof(body.targets));
        memset(body.pulses, 0, sizeof(body.pulses));
        body.next_channel = 0;
        body.ramping = home_channel(body.targets, body.pulses, &body.next_channel);
        body.next_channel_at = now + UINT64_C(200000);
    } else {
        if (!status.armed) memset(body.pulses, 0, sizeof(body.pulses));
        body.pulses[request->channel] = request->pulses[request->channel];
        body.ramping = false;
    }
    if (!any_pulses(body.pulses)) {
        ainekio_pca_disarm(output);
        body.active = body.ramping = false;
    } else {
        const ainekio_pca_result_t result = status.armed ?
            ainekio_pca_write_frame(output, request->generation, body.pulses) :
            ainekio_pca_arm(output, request->generation, body.pulses);
        if (result != AINEKIO_PCA_OK) { stop_body(ESP_FAIL); return ESP_ERR_INVALID_STATE; }
        body.active = true;
        body.generation = request->generation;
        body.last_frame = esp_timer_get_time();
        body.next_frame = body.last_frame + UINT64_C(20000);
    }
    if(body.active)retain_manual_reference();else body.pose_valid=false;
    publish(body.pulses);
    return ESP_OK;
}

static void output_task(void *arg)
{
    (void)arg;
    const esp_task_wdt_config_t config = {.timeout_ms=100, .idle_core_mask=0, .trigger_panic=true};
    esp_err_t error = esp_task_wdt_reconfigure(&config);
    if (error == ESP_ERR_INVALID_STATE) error = esp_task_wdt_init(&config);
    ESP_ERROR_CHECK(error);
    esp_task_wdt_user_handle_t watchdog;
    ESP_ERROR_CHECK(esp_task_wdt_add_user("body progress", &watchdog));
    for (;;) {
        if (output_step(esp_timer_get_time())) ESP_ERROR_CHECK(esp_task_wdt_reset_user(watchdog));
        body_request_t request;
        if (xQueueReceive(requests, &request, 0) == pdTRUE) {
            const uint64_t requested=esp_timer_get_time();
            const body_result_t response = {.serial=request.serial,
                .result=process_request(&request, requested)};
            const uint64_t request_us=(uint64_t)esp_timer_get_time()-requested;
            portENTER_CRITICAL(&pulse_lock);
            if(request_us>timing.request_us)timing.request_us=(uint32_t)request_us;
            portEXIT_CRITICAL(&pulse_lock);
            if (response.result == ESP_OK && request.home && body.active && body.ramping)
                body.pending_home = request.serial;
            else xQueueOverwrite(results, &response);
            if (response.result == ESP_OK) ESP_ERROR_CHECK(esp_task_wdt_reset_user(watchdog));
        }
        const ainekio_pca_status_t status = ainekio_pca_status(ainekio_p4_output());
        if (!status.armed && !status.in_flight) ESP_ERROR_CHECK(esp_task_wdt_reset_user(watchdog));
        /* Yield after a late frame without adding another 5 ms of lateness.
         * The next iteration samples current time and retains every deadline. */
        vTaskDelay(body.active && (uint64_t)esp_timer_get_time() >= body.next_frame ?
            1 : pdMS_TO_TICKS(5));
    }
}

esp_err_t ainekio_p4_body_start(void)
{
    requests = xQueueCreate(1, sizeof(body_request_t));
    results = xQueueCreate(1, sizeof(body_result_t));
    events = xQueueCreate(16, sizeof(ainekio_p4_body_event_t));
    caller_lock = xSemaphoreCreateMutex();
    if (!requests || !results || !events || !caller_lock) return ESP_ERR_NO_MEM;
    return xTaskCreatePinnedToCore(output_task, "body_output", 12288, NULL, 10, &output_handle, 1) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
