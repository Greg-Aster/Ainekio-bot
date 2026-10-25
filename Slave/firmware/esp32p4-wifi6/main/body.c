#include "gait_learning.h"
#include "body.h"
#include "logs.h"
#include <stdio.h>
#include "board.h"
#include "system.h"
#include "config.h"
#include "servo_feedback.h"
#include "gait_trace_runtime.h"
#include "ainekio/v2_walk.h"
#include "ainekio/v2_limits.h"
#include "ainekio/v2_posture.h"
#include "ainekio/v2_balance.h"
#include "ainekio/p4_imu.h"

#include <stdatomic.h>
#include "ainekio/p4_media.h"
#include <math.h>
#include <stdlib.h>

#include <string.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

typedef struct {
    uint64_t generation, deadline;
    uint32_t serial;
    bool home, prepare, hold, execute, freestyle;
    uint64_t connection;
    uint32_t sequence;
    union {
        ainekio_intent_t intent;
        ainekio_motion_plan_t plan;
    };
    uint8_t channel;
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
} body_request_t;
typedef struct { uint32_t serial; esp_err_t result; } body_result_t;
static QueueHandle_t requests, results, events;
static SemaphoreHandle_t caller_lock;
static uint32_t request_serial;
static portMUX_TYPE pulse_lock = portMUX_INITIALIZER_UNLOCKED;
static uint16_t commanded[AINEKIO_PCA_BODY_CHANNELS];
static uint64_t commanded_us;
static ainekio_p4_body_status_t motion_status;
/* A target write and completion can publish in the same output frame. Four
 * snapshots retain the preceding 20 ms frame as well as these phase changes. */
static ainekio_p4_execution_t execution_history[4];
static unsigned execution_history_next;
static ainekio_p4_body_timing_t timing;
static TaskHandle_t output_handle;
static bool listen_requested;
static esp_timer_handle_t rest_timer;
static atomic_bool rest_expired;
static atomic_uint activity_revision;
static unsigned rest_revision;
static bool rest_busy, rest_eligible;
static uint64_t rest_deadline;
void ainekio_p4_body_activity(void) { atomic_fetch_add(&activity_revision,1); }
static void rest_timeout(void *arg)
{
    (void)arg;
    /* Shared esp_timer task only posts a notice. PWM stays with body_output. */
    atomic_store(&rest_expired,true);
}
static uint64_t disconnected_through;

void ainekio_p4_body_connection_lost(uint64_t connection)
{
    portENTER_CRITICAL(&pulse_lock);
    if(connection>disconnected_through)disconnected_through=connection;
    portEXIT_CRITICAL(&pulse_lock);
}

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
    const uint64_t now=esp_timer_get_time();
    portENTER_CRITICAL(&pulse_lock);
    memcpy(commanded, pulses, sizeof(commanded));
    commanded_us=now;
    portEXIT_CRITICAL(&pulse_lock);
    ainekio_p4_gait_trace_output(pulses,now,
        ainekio_pca_status(ainekio_p4_output()).armed);
}

void ainekio_p4_body_pulses(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS])
{
    uint64_t timestamp;bool armed;
    ainekio_p4_body_pulse_snapshot(pulses,&timestamp,&armed);
}

void ainekio_p4_body_pulse_snapshot(uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS],uint64_t *published_us,bool *armed)
{
    portENTER_CRITICAL(&pulse_lock);
    memcpy(pulses, commanded, sizeof(commanded));
    *published_us=commanded_us;
    portEXIT_CRITICAL(&pulse_lock);
    *armed=ainekio_pca_status(ainekio_p4_output()).armed;
    if (!*armed) memset(pulses, 0, sizeof(commanded));
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

esp_err_t ainekio_p4_body_startup(uint64_t generation)
{
    body_request_t request = {.generation=generation, .execute=true,
        .intent={.kind=AINEKIO_INTENT_STAND}};
    return submit(&request);
}

/* Stop or a mode handoff cancels choreography in the output owner, keeping an
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

typedef enum { MOTION_NONE, MOTION_POSE, MOTION_WALK, MOTION_CLIP, MOTION_FREESTYLE } motion_kind_t;
#define GROUNDED_ALIGN_US UINT64_C(500000)
typedef struct {
    motion_kind_t kind;
    uint64_t connection, entry_start, entry_duration, started;
    uint32_t sequence;
    bool entering, reverse_grounded_entry, contact_entry, balance_on_complete;
    bool startup_entry;
    bool release_on_complete; /* Only automatic inactivity lay-down. */
    bool feedback_pending_write;
    bool feedback_verified;
    ainekio_v2_frame_t feedback_frame;
    uint64_t feedback_commanded_us;
    uint16_t feedback_waiting_mask, feedback_targets[12];
    double posture_progress;
    uint16_t engaged_shoulders;
    uint32_t posture_replans;
    bool posture_replanning;
    /* Only one entry planner is active for a motion. */
    union {
        ainekio_v2_posture_t posture;
        ainekio_v2_rise_t rise;
    };
    size_t clip, recovery_clip;
    float playback_rate, requested_rate;
    double clip_joint_speed;
    ainekio_v2_clip_player_t clip_player;
    uint64_t clip_updated_us, clip_commanded_us;
    bool clip_pending_write;
    float entry_rate;
    const char *face_command;
    uint64_t face_elapsed_us;
    uint32_t face_revision;
    bool face_is_clip;
    float entry_up[3];
    uint16_t from[AINEKIO_PCA_BODY_CHANNELS], target[AINEKIO_PCA_BODY_CHANNELS];
    union {
        ainekio_v2_walk_state_t walk;
        struct {
            ainekio_motion_plan_t plan;
            ainekio_v2_frame_t from;
            uint64_t frame_start;
            uint8_t index;
        } freestyle;
    };
    ainekio_v2_frame_t entry_from, entry_to;
} motion_t;
typedef struct {
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS], targets[AINEKIO_PCA_BODY_CHANNELS];
    bool active, ramping;
    uint64_t generation, next_frame, last_frame, next_channel_at;
    size_t next_channel;
    uint32_t pending_home;
    motion_t motion;
    bool stand_goal_active;
    uint64_t stand_goal_since;
    ainekio_p4_feedback_progress_t feedback_progress;
    uint16_t stalled_joints;
    uint64_t stall_clock_us;
    ainekio_p4_body_event_t pending_jam;
    ainekio_p4_execution_t execution;
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
    ainekio_v2_balance_t balance;
    ainekio_v2_walk_pose_t balance_nominal;
    double balance_anchors[4][3];
    bool balance_hold, balance_contacts;
    bool balance_settled;
    ainekio_v2_frame_t balance_target;
    ainekio_v2_balance_tracking_t balance_tracking;
    bool balance_target_valid, balance_tracking_available, balance_tracking_active;
} body_state_t;
static body_state_t body;
static void report_stalled(uint16_t stalled,uint64_t now);

static void up_from_euler(const double euler[3],float up[3])
{
    up[0]=(float)-sin(euler[1]);
    up[1]=(float)(sin(euler[0])*cos(euler[1]));
    up[2]=(float)(cos(euler[0])*cos(euler[1]));
}

static void entry_reference(motion_t *next)
{
    next->entry_up[2]=1.F;
    if(body.execution.expected_up_known)
        memcpy(next->entry_up,body.execution.expected_up,sizeof(next->entry_up));
}

static void blend_up(const float from[3],const float to[3],double u,float up[3])
{
    double length=0.;
    for(unsigned j=0;j<3;j++){up[j]=(float)((1.-u)*from[j]+u*to[j]);length+=up[j]*up[j];}
    length=sqrt(length);
    for(unsigned j=0;j<3;j++)up[j]/=(float)length;
}

static void expected_up(uint64_t now,float up[3])
{
    const motion_t *motion=&body.motion;
    const float upright[3]={0,0,1};
    memcpy(up,upright,sizeof upright);
    if(motion->entering && motion->contact_entry) {
        up_from_euler(motion->posture.pose.euler,up);
    } else if(motion->entering && motion->startup_entry) {
        up_from_euler(motion->rise.crouch.euler,up);
    } else if(motion->entering) {
        float target[3]={0,0,1};
        if(motion->kind==MOTION_CLIP)ainekio_v2_clip_expected_up(motion->clip,0,target);
        if(motion->reverse_grounded_entry) {
            const double duration=ainekio_v2_clip_playback_seconds(motion->recovery_clip,
                motion->clip_joint_speed,motion->requested_rate)*1e6;
            const double elapsed=fmin((double)motion->entry_duration,(double)(now-motion->entry_start));
            if(elapsed<duration) {
                ainekio_v2_frame_t frame;uint64_t source_us;
                ainekio_v2_clip_playback_sample(motion->recovery_clip,elapsed/1e6,
                    motion->clip_joint_speed,motion->requested_rate,true,&frame,&source_us);
                ainekio_v2_clip_expected_up(motion->recovery_clip,source_us,up);
                return;
            }
            float source[3];ainekio_v2_clip_expected_up(motion->recovery_clip,0,source);
            const double u=fmin(1.,(elapsed-duration)*motion->entry_rate/GROUNDED_ALIGN_US);
            blend_up(source,target,u*u*u*(10.+u*(-15.+6.*u)),up);
        } else {
            const float u=fminf(1.F,((float)(now-motion->entry_start)/motion->entry_duration)*motion->entry_rate);
            const double half=u<=.5F?u:1.-u;
            const double ramp=half*half*half*(10.+half*(-15.+6.*half));
            blend_up(motion->entry_up,target,u<=.5F?ramp:1.-ramp,up);
        }
    } else if(motion->kind==MOTION_WALK) {
        up_from_euler(motion->walk.pose.euler,up);
    } else if(motion->kind==MOTION_CLIP) {
        ainekio_v2_clip_expected_up(motion->clip,motion->face_elapsed_us,up);
    }
}

static void publish_execution(uint64_t now,bool sampling,bool manual)
{
    ainekio_p4_execution_t *execution=&body.execution;
    if(sampling && body.motion.kind!=MOTION_NONE) {
        const char *command=body.motion.kind==MOTION_FREESTYLE?"motion_plan":body.motion.face_command;
        const uint64_t written=esp_timer_get_time();
        if(!execution->command || execution->connection!=body.motion.connection ||
           execution->sequence!=body.motion.sequence ||
           strcmp(execution->command,command))execution->started_us=written;
        execution->command=command;execution->sequence=body.motion.sequence;
        execution->connection=body.motion.connection;
        execution->activity=body.motion.kind==MOTION_WALK?"locomotion":
            body.motion.kind==MOTION_CLIP?"clip":body.motion.kind==MOTION_FREESTYLE?"freestyle":"pose";
        execution->phase=body.motion.posture_replanning?"replanning":
            body.motion.entering?"entry":"motion";
        execution->sampled_us=written;
        execution->expected_up_known=body.motion.kind!=MOTION_FREESTYLE;
        if(execution->expected_up_known)expected_up(now,execution->expected_up);
    } else if(manual) {
        const uint64_t written=esp_timer_get_time();
        const uint64_t started=execution->activity && !strcmp(execution->activity,"manual") &&
            execution->phase && !strcmp(execution->phase,"motion")?execution->started_us:written;
        *execution=(ainekio_p4_execution_t){.command="manual",.activity="manual",
            .phase=body.ramping?"motion":"hold",.started_us=started,.sampled_us=written};
    }
}

static void publish_motion(void)
{
    ainekio_p4_body_status_t value = {
        .connection=body.motion.connection, .sequence=body.motion.sequence,
        .moving=body.motion.kind != MOTION_NONE,
        .execution=body.execution,
        .listening_feedback=body.listen.active,
        .walking_feedback_active=body.motion.kind==MOTION_WALK && body.motion.walk.heading_active,
        .walking_feedback_reduced=body.motion.kind==MOTION_WALK && body.motion.walk.heading_reduced,
        .walking_heading_error_rad=body.motion.kind==MOTION_WALK ? body.motion.walk.heading_error : 0.,
        .walking_turn_percent=body.motion.kind==MOTION_WALK ? body.motion.walk.feedback_turn*100. : 0.,
        .balance_active=ainekio_p4_balance_enabled() && body.balance.sensor_usable && !body.balance_settled && (body.balance_hold ||
            (body.motion.kind!=MOTION_NONE && (body.motion.contact_entry ||
                body.motion.startup_entry || body.motion.kind==MOTION_WALK))),
        .balance_reduced=body.balance.reduced,
        .balance_settled=body.balance_settled && body.balance_hold && ainekio_p4_balance_enabled(),
        .balance_tracking_available=body.balance_tracking_available,
        .balance_tracking_active=body.balance_tracking_active && body.balance_hold &&
            ainekio_p4_balance_enabled(),
        .balance_tracking_reduced=body.balance_tracking_active && body.balance_tracking.reduced,
        .servo_feedback_waiting=body.motion.kind!=MOTION_NONE &&
            (body.motion.clip_commanded_us!=0 ||
             (body.motion.feedback_commanded_us!=0 && ainekio_p4_feedback_stand_enabled())),
        .servo_feedback_waiting_mask=body.motion.feedback_waiting_mask,
        .stalled_joints=body.stalled_joints,.stall_clock_us=body.stall_clock_us,
        .stand_progress=(float)(body.motion.posture_progress/ainekio_v2_posture_path_length()),
        .stand_replanning=body.motion.posture_replanning,.stand_replans=body.motion.posture_replans,
        .body_roll_rad=(float)body.balance.measured[0],
        .body_pitch_rad=(float)body.balance.measured[1],
        .balance_roll_rad=(float)body.balance.correction[0],
        .balance_pitch_rad=(float)body.balance.correction[1],
        .face_command=body.motion.face_command,
        .face_elapsed_us=body.motion.face_elapsed_us,
        .face_revision=body.motion.face_revision,
        .face_is_clip=body.motion.face_is_clip,
        .face_entering=body.motion.entering,
        .face_clip=body.motion.clip,
        .automatic_run=body.motion.kind==MOTION_WALK && body.motion.walk.automatic_run,
        .gait_valid=body.motion.kind==MOTION_WALK,
        .gait_phase=body.motion.kind==MOTION_WALK ? body.motion.walk.phase : 0.,
        .gait_cycles_s=body.motion.kind==MOTION_WALK && !body.motion.entering ? body.motion.walk.cycles_s : 0.F,
        .gait_requested_cycles_s=body.motion.kind==MOTION_WALK ? body.motion.walk.requested_cycles_s : 0.F,
        .stride_percent=body.motion.kind==MOTION_WALK ? body.motion.walk.stride_percent : 0.F,
        .requested_stride_percent=body.motion.kind==MOTION_WALK ? body.motion.walk.requested_stride_percent : 0.F,
        .speed_limited=body.motion.kind != MOTION_NONE &&
            !body.motion.contact_entry && !body.motion.startup_entry && (body.motion.entering
            ? body.motion.entry_rate < body.motion.requested_rate
            : body.motion.kind == MOTION_WALK ? body.motion.walk.speed_flagged
            : body.motion.playback_rate < body.motion.requested_rate),
    };
    for(unsigned j=0;j<12;j++) {
        value.balance_tracking_error_deg[j]=(float)body.balance_tracking.error_deg[j];
        value.balance_tracking_trim_deg[j]=(float)body.balance_tracking.trim_deg[j];
    }
    for(unsigned axis=0;axis<2;axis++)
        value.balance_tracking_lag_rad[axis]=(float)body.balance_tracking.body_lag_rad[axis];
    /* Observe the successfully written pose, with chassis translation and
     * rotation removed so a downward contact shift means leg extension.
     * This presentation does not feed back into the solver or output path. */
    if(body.pose_valid && (body.balance_hold || (body.motion.kind!=MOTION_NONE &&
        (body.motion.contact_entry || body.motion.startup_entry || body.motion.kind==MOTION_WALK)))) {
        ainekio_v2_walk_pose_t nominal=body.balance_nominal,actual=nominal;
        double points[4][3];memcpy(points,body.balance_anchors,sizeof points);
        memset(nominal.body,0,sizeof nominal.body);memset(nominal.euler,0,sizeof nominal.euler);
        memset(actual.body,0,sizeof actual.body);memset(actual.euler,0,sizeof actual.euler);
        for(unsigned l=0;l<4;l++)for(unsigned j=0;j<3;j++) {
            const unsigned joint=(l<2?l+2:l-2)*3+j;
            actual.joints[l][j]=body.pose.position[joint]*.00017453292519943296;
            value.balance_joint_delta_deg[joint]=(body.pose.position[joint]-nominal.frame.position[joint])*.01F;
        }
        value.balance_legs_valid=ainekio_v2_contact_forward(&nominal,points,!body.balance_contacts) &&
            ainekio_v2_contact_forward(&actual,points,false);
        if(value.balance_legs_valid)for(unsigned l=0;l<4;l++)
            value.balance_extension_mm[l]=(float)(nominal.feet[l][2]-actual.feet[l][2]);
    }
    portENTER_CRITICAL(&pulse_lock);
    motion_status = value;
    if(value.execution.sampled_us) {
        unsigned previous=(execution_history_next+3)%4;
        if(execution_history[previous].sampled_us==value.execution.sampled_us)
            execution_history[previous]=value.execution;
        else {
            execution_history[execution_history_next]=value.execution;
            execution_history_next=(execution_history_next+1)%4;
        }
    }
    portEXIT_CRITICAL(&pulse_lock);
}

ainekio_p4_execution_t ainekio_p4_body_execution_at(uint64_t timestamp_us)
{
    ainekio_p4_execution_t result={0};
    portENTER_CRITICAL(&pulse_lock);
    for(unsigned i=0;i<4;i++) {
        const unsigned index=(execution_history_next+3-i)%4;
        if(execution_history[index].sampled_us && execution_history[index].sampled_us<=timestamp_us) {
            result=execution_history[index];break;
        }
    }
    portEXIT_CRITICAL(&pulse_lock);
    return result;
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
    if (!command) return false;
    if (command->kind == AINEKIO_COMMAND_MOTION_PLAN)
        return command->data.motion_plan.joint_map_version == AINEKIO_V2_JOINT_MAP_VERSION;
    if (command->kind != AINEKIO_COMMAND_INTENT) return false;
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
    if (command->kind == AINEKIO_COMMAND_MOTION_PLAN) {
        request.freestyle = true;
        request.plan = command->data.motion_plan;
    }
    return submit(&request);
}

static void finish_motion(bool completed, esp_err_t result)
{
    if(!completed)body.pending_jam=(ainekio_p4_body_event_t){0};
    const bool release=completed && result==ESP_OK && body.motion.release_on_complete;
    body.motion.release_on_complete=false;
    body.stand_goal_active=completed && body.motion.kind==MOTION_POSE &&
        body.motion.balance_on_complete && ainekio_p4_feedback_stand_enabled();
    if(body.stand_goal_active)body.stand_goal_since=body.last_frame;
    memset(&body.feedback_progress,0,sizeof body.feedback_progress);
    if(body.execution.command && body.execution.phase && strcmp(body.execution.phase,"hold"))
        body.execution.sampled_us=esp_timer_get_time();
    body.execution.phase="hold";
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
        .position_verification=completed && body.motion.kind==MOTION_POSE &&
            body.motion.balance_on_complete && ainekio_p4_feedback_stand_enabled() ?
            (body.motion.feedback_verified?2:1):0,
        .result=result,.stalled_joints=result==AINEKIO_P4_ERR_STALLED?body.stalled_joints:0,
        .clock_us=(uint64_t)esp_timer_get_time()};
    /* Admission reserves two slots: replacement and eventual completion. There
     * is one producer, and a reader can only increase the available space. */
    if (event.connection && xQueueSend(events, &event, 0) != pdTRUE)
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
    if(release) {
        /* The successful final frame owns completion. Leave the final face,
         * retire the commanded pose (shafts may now sag), and release OE.
         * Idle release preserves commands admitted just before this frame. */
        ainekio_pca_idle(ainekio_p4_output());
        body.active=body.ramping=body.pose_valid=body.listen.active=false;
        memset(body.pulses,0,sizeof body.pulses);
        publish(body.pulses);
    }
    publish_motion();
}

static void stop_body(esp_err_t result)
{
    body.listen.active = false;
    ainekio_p4_body_listen(false);
    finish_motion(false, result);
    body.execution=(ainekio_p4_execution_t){.sampled_us=(uint64_t)esp_timer_get_time()};
    body.active = body.ramping = body.pose_valid = false;
    body.balance_hold=false;body.balance_settled=false;body.balance_target_valid=false;body.balance_tracking_active=false;body.balance=(ainekio_v2_balance_t){0};
    memset(body.pulses, 0, sizeof(body.pulses));
    publish(body.pulses);
    publish_motion();
    if (body.pending_home) {
        const body_result_t stopped = {.serial=body.pending_home, .result=ESP_ERR_INVALID_STATE};
        xQueueOverwrite(results, &stopped);
        body.pending_home = 0;
    }
}

static void fail_motion(esp_err_t result)
{
    char diagnostic[128];
    snprintf(diagnostic,sizeof diagnostic,"motion failure: result=%d kind=%d stationary_level=%d",
        (int)result,(int)body.motion.kind,(int)body.balance_hold);
    ainekio_p4_log_stage(diagnostic);
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

static bool fit_motion_frame(ainekio_v2_frame_t *frame)
{
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    return calibration.valid && ainekio_p4_joint_fit_frame(calibration.joints,frame);
}
static bool motion_pulses(ainekio_v2_frame_t *frame,uint16_t *pulses)
{
    return fit_motion_frame(frame) && ainekio_p4_frame_pulses(frame,pulses);
}
static bool posture_fit(ainekio_v2_frame_t *frame,void *context)
{
    const ainekio_p4_calibration_t *calibration=context;
    uint16_t pulses[12];
    return ainekio_p4_joint_fit_frame(calibration->joints,frame) &&
        ainekio_p4_frame_pulses(frame,pulses);
}

static bool walking_frame_valid(const ainekio_v2_frame_t *frame,void *context)
{
    (void)context;
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    return ainekio_p4_frame_pulses(frame,pulses);
}

static bool usable_attitude(const ainekio_p4_imu_status_t *s)
{
    return s->calibration_applied && s->attitude.available && s->attitude.fresh &&
        !s->attitude.startup && !s->attitude.gyro_recovery && !s->attitude.acceleration_recovery;
}

static void starting_attitude(double euler[3])
{
    const ainekio_p4_imu_status_t s=ainekio_p4_imu_status();
    memset(euler,0,3*sizeof(*euler));
    /* The owner's leveling switch also controls IMU-driven Stand entry.
     * Otherwise disabling a suspect calibration still rotates the entry path. */
    if(!ainekio_p4_balance_enabled() || !usable_attitude(&s))return;
    const float *q=s.attitude.orientation_wxyz;
    const double w=q[0],x=q[1],y=q[2],z=q[3];
    euler[0]=atan2(2.*(w*x+y*z),1.-2.*(x*x+y*y));
    euler[1]=asin(fmax(-1.,fmin(1.,2.*(w*y-z*x))));
    /* Relative yaw is sufficient for posture; six-axis heading is arbitrary. */
}

static void balance_frame(const ainekio_v2_walk_pose_t *nominal,const double anchors[4][3],
                          uint64_t now,ainekio_v2_frame_t *frame)
{
    const ainekio_p4_imu_status_t imu=ainekio_p4_imu_status();
    ainekio_v2_walk_pose_t adjusted;
    /* Only the stationary hold accumulates leveling. Entry and walking keep
     * their trajectory-relative feedback and cannot inherit this offset. */
    const bool standing=body.motion.kind==MOTION_NONE && body.balance_hold;
    const ainekio_v2_balance_tuning_t tuning=ainekio_p4_balance_tuning();
    const bool leveling=ainekio_p4_balance_enabled() && usable_attitude(&imu);
    const double dt=(now-body.last_frame)/1e6;
    if(standing && leveling) {
        const float *q=imu.attitude.orientation_wxyz;
        const double w=q[0],x=q[1],y=q[2],z=q[3],deg=180./acos(-1.);
        body.balance.measured[0]=atan2(2.*(w*x+y*z),1.-2.*(x*x+y*y));
        body.balance.measured[1]=asin(fmax(-1.,fmin(1.,2.*(w*y-z*x))));
        double error=0.,rate=0.;
        for(unsigned axis=0;axis<2;axis++) {
            const double target=nominal->euler[axis]*deg+(axis==0?tuning.roll_deg:-tuning.pitch_deg);
            error=fmax(error,fabs(target-body.balance.measured[axis]*deg));
            rate=fmax(rate,fabs(imu.attitude.angular_rate_rad_s[axis])*deg);
        }
        if(body.balance_settled ? error<=BALANCE_WAKE_DEG :
            error<=BALANCE_SETTLE_DEG && rate<=BALANCE_SETTLE_RATE_DEG_S) {
            body.balance_settled=true;body.balance.sensor_usable=true;body.balance.reduced=false;
            body.balance.actuator_reference_valid=false;
            body.balance_tracking_active=false;
            memset(&body.balance_tracking,0,sizeof body.balance_tracking);
            *frame=body.pose; /* Keep the achieved pose, including any accepted tracking trim. */
            return;
        }
    }
    body.balance_settled=false;
    /* The outer body controller owns the target. Measured joint lag unwinds
     * excess accumulated demand rather than adding another servo drive loop. */
    const ainekio_v2_frame_t *previous=standing&&body.balance_target_valid ?
        &body.balance_target : &body.pose;
    body.balance_tracking_active=false;
    memset(&body.balance_tracking,0,sizeof body.balance_tracking);
    ainekio_v2_frame_t measured=*previous;
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    body.balance_tracking_available=ainekio_p4_feedback_frame(calibration.joints,&measured);
    if(standing && leveling && body.balance_tracking_available) {
        double tolerance[12];
        for(unsigned j=0;j<12;j++)tolerance[j]=BALANCE_SHAFT_TOLERANCE_US/calibration.joints[j].us_per_degree;
        ainekio_v2_balance_feedback_apply(&body.balance,imu.attitude.orientation_wxyz,
            imu.attitude.angular_rate_rad_s,dt,nominal,anchors,previous,&measured,
            tolerance,&adjusted,&tuning,&body.balance_tracking);
        body.balance_tracking_active=body.balance_tracking.observable;
    } else {
        body.balance.actuator_reference_valid=false;
        /* Existing gyro-only behavior when usable shaft feedback is unavailable.
         * Moving gaits retain their authored-pose controller. */
        ainekio_v2_balance_configured_apply(&body.balance,imu.attitude.orientation_wxyz,
            imu.attitude.angular_rate_rad_s,leveling,dt,nominal,anchors,previous,
            ainekio_v2_gait_joint_speed_limit(),&adjusted,&tuning,standing);
    }
    *frame=adjusted.frame;
    body.balance_target=adjusted.frame;body.balance_target_valid=standing;
    body.balance_nominal=*nominal;
    body.balance_contacts=anchors!=NULL;
    if(anchors && anchors!=(const double (*)[3])body.balance_anchors)
        memcpy(body.balance_anchors,anchors,sizeof(body.balance_anchors));
}

/* The initial authored fold and stepping pass run independently of feedback.
 * Position verification happens after the complete Stand pass. */
static uint64_t startup_fold_us(void)
{
    return (uint64_t)ceil(ainekio_v2_profile_travel_degrees()/
        ainekio_v2_joint_speed_default()*1e6);
}
/* Model joints 6..11 are physically front; 0..5 rear. CAD names are reversed.
 * Fold one leg's coupled crank/carrier at a time, in the stepping order.
 * Transit remains an estimate from the existing travel/speed model, not a
 * claim of measured arrival. Round to the output cadence so stages do not
 * overlap just because the next tick falls beyond a fractional interval. */
static uint64_t startup_leg_us(void)
{
    return ((startup_fold_us()+19999)/20000)*20000;
}
static uint64_t startup_leg_offset(unsigned joint)
{
    static const unsigned rank[4]={3,1,0,2};
    return rank[joint/3]*startup_leg_us();
}
static esp_err_t start_rise(const body_request_t *request,uint64_t now)
{
    motion_t next={.kind=MOTION_POSE,.connection=request->connection,
        .sequence=request->sequence,.face_command="stand",
        .face_revision=body.motion.face_revision+1,.entering=true,.startup_entry=true,.balance_on_complete=true,
        .entry_start=now,.requested_rate=1.F,.entry_rate=1.F,.playback_rate=1.F};
    entry_reference(&next);
    if(!ainekio_v2_rise_begin(&next.rise))return ESP_ERR_INVALID_ARG;
    next.entry_from=next.rise.crouch.frame;
    next.entry_to=next.rise.stand.frame;
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    uint16_t initial[AINEKIO_PCA_BODY_CHANNELS];
    if(!calibration.valid || !calibration.profile_confirmed)return ESP_ERR_INVALID_STATE;
    if(!motion_pulses(&next.rise.crouch.frame,initial) ||
       !motion_pulses(&next.rise.stand.frame,next.target))return ESP_ERR_INVALID_ARG;
    next.entry_from=next.rise.crouch.frame;next.entry_to=next.rise.stand.frame;
    for(unsigned j=0;j<AINEKIO_BODY_JOINT_COUNT;j++)
        if(calibration.joints[j].channel>=0 && (j%3==0 || startup_leg_offset(j)))
            initial[calibration.joints[j].channel]=0;
    ainekio_pca9685_t *output=ainekio_p4_output();
    const bool armed=ainekio_pca_status(output).armed;
    ainekio_pca_result_t result=armed?AINEKIO_PCA_OK:ainekio_pca_recover(output,request->generation);
    if(result==AINEKIO_PCA_OK)result=armed?
        ainekio_pca_write_frame(output,request->generation,initial):
        ainekio_pca_arm(output,request->generation,initial);
    if(result!=AINEKIO_PCA_OK)return ESP_ERR_INVALID_STATE;
    finish_motion(false,ESP_OK);
    body.balance_hold=false;body.balance_settled=false;body.balance_target_valid=false;body.balance_tracking_active=false;body.balance=(ainekio_v2_balance_t){0};
    body.listen.active=false;body.ramping=false;body.active=true;
    body.motion=next;body.generation=request->generation;
    body.last_frame=esp_timer_get_time();body.motion.entry_start=body.last_frame;
    body.next_frame=body.last_frame+UINT64_C(20000);
    retain_pose(&next.entry_from,&calibration);
    body.pose_valid=false; /* Shoulders have not been commanded yet. */
    memcpy(body.pulses,initial,sizeof(initial));publish(body.pulses);publish_motion();
    return ESP_OK;
}

static esp_err_t start_motion(const body_request_t *request, uint64_t now)
{
    if(request->intent.kind==AINEKIO_INTENT_STAND &&
       (!request->connection || !ainekio_pca_status(ainekio_p4_output()).armed || !body.pose_valid))
        return start_rise(request,now);
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
    next.clip_joint_speed=ainekio_v2_gait_joint_speed_limit()*AINEKIO_V2_GESTURE_SPEED_SCALE;
    entry_reference(&next);
    if(request->intent.kind==AINEKIO_INTENT_STAND)
        next.requested_rate=next.playback_rate=1.F;
    ainekio_v2_frame_t frame = {.geometry_id=ainekio_v2_walk_geometry_id};
    if (request->intent.kind == AINEKIO_INTENT_WALK) {
        next.kind = MOTION_WALK;
        next.entering = false;
        next.started = now;
        if (!ainekio_v2_walk_accept(&next.walk, &command, now)) return ESP_ERR_INVALID_ARG;
        ainekio_p4_learning_begin(&next.walk);
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
    if (!motion_pulses(&frame, next.target) || !any_pulses(next.target))
        return ESP_ERR_INVALID_ARG;
    const ainekio_p4_calibration_t calibration = ainekio_p4_calibration();
    if (!calibration.valid || !calibration.profile_confirmed) return ESP_ERR_INVALID_STATE;
    bool home = !ainekio_pca_status(ainekio_p4_output()).armed || !body.pose_valid ||
        memcmp(body.pose_mapping,calibration.joints,sizeof(body.pose_mapping));
    for (unsigned i=0; i<AINEKIO_PCA_BODY_CHANNELS; ++i)
        if (calibration.joints[i].channel >= 0 && !body.pulses[calibration.joints[i].channel]) home = true;
    if (home) {
        /* Calibration Home is only requested explicitly. Detached named
         * motions engage their own entry pose; Stand uses start_rise above. */
        memcpy(next.from, next.target, sizeof(next.from));
    } else memcpy(next.from, body.pulses, sizeof(next.from));
    if (home) next.entry_from=frame;
    else next.entry_from=body.pose;
    if(!ainekio_v2_limits_frame(&next.entry_from))return AINEKIO_P4_ERR_REFERENCE;
    next.entry_to = frame;
    ainekio_v2_frame_t path_minimum, path_maximum;
    double derivatives[AINEKIO_PCA_BODY_CHANNELS];
    uint16_t checked[AINEKIO_PCA_BODY_CHANNELS];
    /* Stand/named motions retain their explicit posture transitions. Walk
     * never prepends recovery choreography from a preceding stored pose. */
    if (next.entering && !home && body.motion.kind == MOTION_NONE &&
        body.motion.face_is_clip && body.motion.face_command &&
        (!strcmp(body.motion.face_command, "lay_down") ||
         !strcmp(body.motion.face_command, "dead"))) {
        ainekio_v2_frame_t terminal;
        if (ainekio_v2_clip_sample(body.motion.clip, UINT64_MAX, &terminal)) {
            bool at_terminal = true;
            for (unsigned i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i)
                if (fabsf(body.pose.position[i]-terminal.position[i]) > 1.F)
                    at_terminal = false;
            if (at_terminal) {
                next.reverse_grounded_entry = true;
                next.recovery_clip = body.motion.clip;
            }
        }
    }
    next.contact_entry=!next.reverse_grounded_entry &&
        request->intent.kind==AINEKIO_INTENT_STAND;
    next.balance_on_complete=request->intent.kind==AINEKIO_INTENT_STAND;
    if(next.contact_entry) {
        double euler[3];starting_attitude(euler);
        if(!ainekio_v2_posture_begin(&next.posture,&next.entry_from,&next.entry_to,euler))return ESP_ERR_INVALID_ARG;
        next.entry_duration=0; /* Full-rate geometry clock owns this path. */
    } else if (next.entering && (!(next.reverse_grounded_entry ?
          ainekio_v2_clip_bounds(next.recovery_clip, &path_minimum, &path_maximum) :
          ainekio_v2_transition_bounds(&next.entry_from, &next.entry_to,
              &path_minimum, &path_maximum, derivatives)) ||
        !ainekio_p4_frame_pulses(&path_minimum, checked) ||
        !ainekio_p4_frame_pulses(&path_maximum, checked))) return ESP_ERR_INVALID_ARG;
    double align_peak=0.;
    if (next.reverse_grounded_entry) {
        ainekio_v2_frame_t clip_start, align_minimum, align_maximum;
        double align_derivatives[AINEKIO_PCA_BODY_CHANNELS];
        if (!ainekio_v2_clip_sample(next.recovery_clip, 0, &clip_start) ||
            !ainekio_v2_transition_bounds(&clip_start, &next.entry_to,
                &align_minimum, &align_maximum, align_derivatives) ||
            !ainekio_p4_frame_pulses(&align_minimum, checked) ||
            !ainekio_p4_frame_pulses(&align_maximum, checked)) return ESP_ERR_INVALID_ARG;
        for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++)
            if(calibration.joints[i].channel>=0)
                align_peak=fmax(align_peak,align_derivatives[i]/100.*1.875e6/GROUNDED_ALIGN_US);
    }
    for(unsigned i=0;i<AINEKIO_PCA_BODY_CHANNELS;i++)if(!next.target[i])next.from[i]=0;
    if(!next.entering)next.entry_rate=next.requested_rate;
    else if(next.contact_entry)next.entry_rate=next.requested_rate;
    else if (next.reverse_grounded_entry) {
        next.entry_rate=ainekio_v2_speed_limited_rate(align_peak,next.requested_rate);
        next.entry_duration=(uint64_t)ceil(ainekio_v2_clip_playback_seconds(next.recovery_clip,
            next.clip_joint_speed,next.requested_rate)*1e6+GROUNDED_ALIGN_US/next.entry_rate);
    }
    else {
        double entry_peak=0.;
        for(unsigned i=0;i<AINEKIO_BODY_JOINT_COUNT;i++)
            if(calibration.joints[i].channel>=0)
                entry_peak=fmax(entry_peak,derivatives[i]/100.*1.875e6/next.entry_duration);
        next.entry_rate=ainekio_v2_speed_limited_rate(entry_peak,next.requested_rate);
    }
    ainekio_pca9685_t *output = ainekio_p4_output();
    if ((uint64_t)esp_timer_get_time() >= request->deadline) return ESP_ERR_TIMEOUT;
    const ainekio_pca_status_t status = ainekio_pca_status(output);
    uint16_t initial[AINEKIO_PCA_BODY_CHANNELS] = {0};
    size_t next_channel = 0;
    bool ramping = false;
    if (home && next.entering) ramping = home_channel(next.from, initial, &next_channel);
    else memcpy(initial, next.from, sizeof(initial));
    ainekio_pca_result_t result = AINEKIO_PCA_OK;
    if (!status.armed) result = ainekio_pca_recover(output, request->generation);
    if (result == AINEKIO_PCA_OK)
        result = status.armed ? ainekio_pca_write_frame(output, request->generation, initial)
                              : ainekio_pca_arm(output, request->generation, initial);
    if (result != AINEKIO_PCA_OK) return ESP_ERR_INVALID_STATE;
    finish_motion(false, ESP_OK);
    body.balance_hold=false;body.balance_settled=false;body.balance_target_valid=false;body.balance_tracking_active=false;
    body.balance=(ainekio_v2_balance_t){0};
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

/* Freestyle targets are model angles. The same saved mounting calibration and
 * PCA frame writer used by named motions own all electrical pulses. */
static esp_err_t start_freestyle(const body_request_t *request, uint64_t now)
{
    const ainekio_motion_plan_t *plan = &request->plan;
    if (plan->joint_map_version != AINEKIO_V2_JOINT_MAP_VERSION ||
        !plan->frame_count || plan->frame_count > AINEKIO_MOTION_PLAN_MAX_FRAMES)
        return ESP_ERR_INVALID_ARG;
    if (uxQueueSpacesAvailable(events) < 2) return ESP_ERR_NO_MEM;
    const ainekio_p4_calibration_t calibration = ainekio_p4_calibration();
    if (!calibration.valid || !calibration.profile_confirmed) return ESP_ERR_INVALID_STATE;
    ainekio_v2_frame_t from = {.geometry_id=ainekio_v2_walk_geometry_id};
    if (body.pose_valid && !memcmp(body.pose_mapping,calibration.joints,sizeof(body.pose_mapping)))
        from = body.pose;
    else for (unsigned j=0;j<AINEKIO_BODY_JOINT_COUNT;j++)
        from.position[j] = plan->frames[0].targets[j];
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    if (!motion_pulses(&from,pulses)) return ESP_ERR_INVALID_ARG;
    ainekio_pca9685_t *output = ainekio_p4_output();
    const ainekio_pca_status_t status = ainekio_pca_status(output);
    ainekio_pca_result_t result = status.armed ? AINEKIO_PCA_OK :
        ainekio_pca_recover(output,request->generation);
    if (result == AINEKIO_PCA_OK)
        result = status.armed ? ainekio_pca_write_frame(output,request->generation,pulses) :
            ainekio_pca_arm(output,request->generation,pulses);
    if (result != AINEKIO_PCA_OK) return ESP_ERR_INVALID_STATE;
    finish_motion(false,ESP_OK);
    body.motion = (motion_t){.kind=MOTION_FREESTYLE,.connection=request->connection,
        .sequence=request->sequence,.started=now,.playback_rate=1,.requested_rate=1,
        .face_revision=body.motion.face_revision+1};
    body.motion.freestyle.plan = *plan;
    body.motion.freestyle.from = from;
    body.motion.freestyle.frame_start = now;
    body.balance_hold=false;body.balance_settled=false;body.balance_target_valid=false;body.balance_tracking_active=false;
    body.balance=(ainekio_v2_balance_t){0};
    body.listen.active=false;
    body.active=true;body.ramping=false;body.generation=request->generation;
    body.last_frame=esp_timer_get_time();body.next_frame=body.last_frame+UINT64_C(20000);
    memcpy(body.pulses,pulses,sizeof(pulses));
    retain_pose(&from,&calibration);
    publish(body.pulses);publish_motion();
    return ESP_OK;
}

static esp_err_t freestyle_frame(uint64_t now, bool *complete, ainekio_v2_frame_t *frame)
{
    motion_t *motion=&body.motion;
    const ainekio_motion_plan_t *plan=&motion->freestyle.plan;
    const unsigned index=motion->freestyle.index;
    const ainekio_motion_plan_frame_t *target=&plan->frames[index];
    const uint64_t duration=(uint64_t)target->duration_ms*1000U;
    const uint64_t elapsed=now-motion->freestyle.frame_start;
    const double u=duration ? fmin(1.,(double)elapsed/duration) : 1.;
    *frame=(ainekio_v2_frame_t){.geometry_id=ainekio_v2_walk_geometry_id,.phase=AINEKIO_V2_CLIP};
    for (unsigned j=0;j<AINEKIO_BODY_JOINT_COUNT;j++) {
        const double start=motion->freestyle.from.position[j];
        frame->position[j]=(float)(start+u*(target->targets[j]-start));
        frame->velocity[j]=u<1. && duration ? (target->targets[j]-start)*1e6/duration : 0;
    }
    if (!motion_pulses(frame,body.pulses)) return ESP_ERR_INVALID_ARG;
    /* Emit every authored endpoint even when it falls between 50 Hz output
     * ticks. Advance after the actual write, so an I2C retry cannot skip it. */
    *complete=u==1. && index+1==plan->frame_count;
    return ESP_OK;
}

static void stand_verify_after_write(motion_t *motion,const ainekio_v2_frame_t *frame)
{
    motion->feedback_pending_write=true;
    motion->feedback_frame=*frame;
    memcpy(motion->feedback_targets,body.pulses,sizeof body.pulses);
}

/* One Stand goal survives every complete pass. Verification selects the legs
 * still short; every corrective path starts from the last written pose, retaining PWM ownership,
 * the request/receipt and already engaged shoulders. Try each physical leg
 * ordering, rather than aborting because one intermediate contact path fails.
 * A measured discrepancy is not a new commanded pose. Replacing the trajectory
 * origin with that observation can jump every support joint or construct an
 * unreachable linkage. Continue the lift/place sequence, then measure again. */
static bool stand_replan(motion_t *motion,double dt)
{
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    motion->posture_replanning=true;
    double euler[3];starting_attitude(euler);
    const unsigned first=ainekio_v2_posture_order_for_joints(motion->feedback_waiting_mask,
        motion->posture.order_offset+1);
    for(unsigned leg=0;leg<4;leg++) {
        ainekio_v2_posture_t candidate;double progress=0.;
        if(!ainekio_v2_posture_begin_ordered(&candidate,&body.pose,&motion->entry_to,euler,first+leg) ||
           !ainekio_v2_posture_advance_mapped(&candidate,&progress,dt,posture_fit,(void *)&calibration))
            continue;
        motion->posture=candidate;motion->posture_progress=progress;
        motion->contact_entry=true;motion->entering=true;motion->reverse_grounded_entry=false;
        motion->feedback_commanded_us=0;motion->feedback_waiting_mask=0;
        motion->feedback_pending_write=false;motion->posture_replanning=false;
        motion->feedback_verified=false;
        motion->posture_replans++;
        return true;
    }
    return false;
}

static esp_err_t entry_finished(motion_t *motion,uint64_t now,const ainekio_v2_frame_t *entry,bool *complete)
{
    motion->entering=false;motion->started=now;
    motion->clip_updated_us=now;
    if(motion->kind==MOTION_WALK)motion->walk.last_us=now;
    *complete=motion->kind==MOTION_POSE;
    if(motion->balance_on_complete) {
        const double level[3]={0};
        if(!ainekio_v2_posture_begin(&motion->posture,entry,entry,level))return ESP_ERR_INVALID_ARG;
        body.balance_nominal=motion->posture.pose;
        memcpy(body.balance_anchors,motion->posture.anchors,sizeof body.balance_anchors);
        body.balance_contacts=body.balance_hold=true;
    }
    return ESP_OK;
}

static esp_err_t posture_output(uint64_t now,bool *complete,ainekio_v2_frame_t *sampled)
{
    motion_t *motion=&body.motion;
    const bool feedback=ainekio_p4_feedback_stand_enabled() || ainekio_p4_feedback_jam_enabled();
    motion->entry_rate=1.F;
    balance_frame(&motion->posture.pose,(const double (*)[3])motion->posture.anchors,now,sampled);
    body.balance_nominal=motion->posture.pose;
    body.balance_contacts=true;
    memcpy(body.balance_anchors,motion->posture.anchors,sizeof(body.balance_anchors));
    if(!motion_pulses(sampled,body.pulses))return ESP_ERR_INVALID_ARG;
    if(motion->startup_entry) {
        const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
        motion->engaged_shoulders|=
            ainekio_v2_posture_arrival_joints(&motion->posture,motion->posture_progress)&0x249;
        for(unsigned leg=0;leg<4;leg++) {
            int ch=calibration.joints[3*leg].channel;
            bool engaged=(motion->engaged_shoulders&(1U<<(3*leg)))!=0;
            if(ch>=0 && !engaged)
                body.pulses[ch]=0;
        }
    }
    if(feedback && motion->posture_progress>=ainekio_v2_posture_path_length() &&
       !motion->feedback_commanded_us)
        stand_verify_after_write(motion,sampled);
    if(motion->posture_progress>=ainekio_v2_posture_path_length() &&
       !motion->feedback_pending_write) {
        motion->startup_entry=false;
        motion->entering=false;motion->started=now;
        if(motion->kind==MOTION_WALK)motion->walk.last_us=now;
        *complete=motion->kind==MOTION_POSE;
        body.balance_hold=*complete;
    }
    return ESP_OK;
}

static esp_err_t motion_frame(uint64_t now, bool *complete, ainekio_v2_frame_t *sampled)
{
    motion_t *motion = &body.motion;
    *complete = false;
    if(motion->feedback_pending_write) {
        *sampled=motion->feedback_frame;
        memcpy(body.pulses,motion->feedback_targets,sizeof body.pulses);
        return ESP_OK;
    }
    const bool feedback=ainekio_p4_feedback_stand_enabled();
    if(motion->feedback_commanded_us) {
        if(feedback || ainekio_p4_feedback_jam_enabled()) {
            const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
            const bool observed=ainekio_p4_feedback_check(calibration.joints,motion->feedback_targets,
                motion->feedback_commanded_us,&motion->feedback_waiting_mask);
            motion->feedback_verified=feedback && observed && !motion->feedback_waiting_mask;
            if(observed && !feedback) {
                /* With goal verification disabled, retain the independent
                 * jam-only behavior. Verified Stand owns its discrepancies
                 * through correction, never the separate release timer. */
                const uint16_t stalled=ainekio_p4_feedback_stalled(&body.feedback_progress,
                    calibration.joints,motion->feedback_targets);
                if(stalled) {
                    report_stalled(stalled,now);
                }
            }
            if(feedback && observed && motion->feedback_waiting_mask) {
                if(stand_replan(motion,(now-body.last_frame)/1e6))
                    return posture_output(now,complete,sampled);
                *sampled=body.pose;
                memcpy(body.pulses,motion->feedback_targets,sizeof(body.pulses));
                return ESP_OK;
            }
            /* Missing/untrusted feedback never holds command completion.
             * Finish the authored path, retain its powered target, and let
             * the existing goal observer resume when measurements return. */
        }
        motion->feedback_commanded_us=0;motion->feedback_waiting_mask=0;
        *sampled=body.pose;
        memcpy(body.pulses,motion->feedback_targets,sizeof body.pulses);
        motion->startup_entry=false;
        return entry_finished(motion,now,sampled,complete);
    }
    if(motion->kind==MOTION_FREESTYLE)
        return freestyle_frame(now,complete,sampled);
    if(motion->startup_entry && !motion->contact_entry) {
        const uint64_t elapsed=now-motion->entry_start;
        if(elapsed<4*startup_leg_us()) {
            *sampled=motion->entry_from;
            if(!motion_pulses(sampled,body.pulses))return ESP_ERR_INVALID_ARG;
            const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
            for(unsigned j=0;j<AINEKIO_BODY_JOINT_COUNT;j++) {
                const int ch=calibration.joints[j].channel;
                if(ch>=0 && (j%3==0 || elapsed<startup_leg_offset(j)))body.pulses[ch]=0;
            }
            return ESP_OK;
        }
        /* Reuse Stand's lift/place/plant path. In particular, do not engage all
         * shoulders at their calibration Home while the feet remain planted. */
        double euler[3];starting_attitude(euler);
        if(!ainekio_v2_posture_begin(&motion->posture,&motion->entry_from,&motion->entry_to,euler))
            return ESP_ERR_INVALID_ARG;
        motion->contact_entry=true;
        motion->posture_progress=0.;
    }
    if (motion->entering) {
        if(motion->contact_entry) {
            const double dt=(now-body.last_frame)/1e6;
            const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
            if(!ainekio_v2_posture_advance_mapped(&motion->posture,&motion->posture_progress,dt,
                posture_fit,(void *)&calibration)) {
                if(!stand_replan(motion,dt)) {
                    *sampled=body.pose;ainekio_p4_body_pulses(body.pulses);
                    return ESP_OK;
                }
            } else motion->posture_replanning=false;
            return posture_output(now,complete,sampled);
        }
        double elapsed=(double)(now-motion->entry_start)*
            (motion->reverse_grounded_entry ? 1. : motion->entry_rate);
        const float u=fminf(1.F,elapsed/motion->entry_duration);
        /* Evaluate the nearer half in double. Mixed-precision u*u*u rounded
         * the upper end above 1 and rejected otherwise valid entry frames. */
        const double half = u <= .5F ? u : 1.-u;
        const double ramp = half*half*half*(10.+half*(-15.+6.*half));
        const double smooth = u <= .5F ? ramp : 1.-ramp;
        ainekio_v2_frame_t entry;
        bool entry_ok;
        if (motion->reverse_grounded_entry) {
            const double clip_duration=ainekio_v2_clip_playback_seconds(motion->recovery_clip,
                motion->clip_joint_speed,motion->requested_rate)*1e6;

            if (elapsed < clip_duration) {
                uint64_t source_us;
                entry_ok=ainekio_v2_clip_playback_sample(motion->recovery_clip,elapsed/1e6,
                    motion->clip_joint_speed,motion->requested_rate,true,&entry,&source_us);
            }
            else {
                ainekio_v2_frame_t clip_start;
                const double align=fmin(1.,(elapsed-clip_duration)*motion->entry_rate/GROUNDED_ALIGN_US);
                const double ease = align*align*align*(10.+align*(-15.+6.*align));
                entry_ok = ainekio_v2_clip_sample(motion->recovery_clip, 0, &clip_start) &&
                    ainekio_v2_transition(&clip_start, &motion->entry_to, ease, &entry);
            }
        } else entry_ok = ainekio_v2_transition(&motion->entry_from, &motion->entry_to, smooth, &entry);
        if (!entry_ok || !motion_pulses(&entry, body.pulses)) return ESP_ERR_INVALID_ARG;
        if(u==1. && (feedback || ainekio_p4_feedback_jam_enabled()) && motion->kind==MOTION_POSE && motion->balance_on_complete)
            stand_verify_after_write(motion,&entry);
        else if(u==1.) {
            const esp_err_t result=entry_finished(motion,now,&entry,complete);
            if(result!=ESP_OK)return result;
        }
        *sampled=entry;
        return ESP_OK;
    }
    ainekio_v2_frame_t frame;
    if (motion->kind == MOTION_WALK) {
        const ainekio_p4_imu_status_t imu=ainekio_p4_imu_status();
        const float *q=imu.attitude.orientation_wxyz;
        const double yaw=atan2(2.*(q[0]*q[3]+q[1]*q[2]),1.-2.*(q[2]*q[2]+q[3]*q[3]));
        if (!ainekio_v2_walk_feedback_tick(&motion->walk,now,
            ainekio_p4_walking_feedback_enabled(),usable_attitude(&imu),yaw,
            walking_frame_valid,NULL)) return ESP_FAIL;
        balance_frame(&motion->walk.pose,NULL,now,&frame);
        if(!fit_motion_frame(&frame))return ESP_ERR_INVALID_ARG;
        ainekio_p4_learning_frame(&motion->walk,motion->sequence,now,&frame,walking_frame_valid,NULL);
        motion->face_command=motion->walk.gait_mode==AINEKIO_GAIT_CRAWL ? "crawl" :
            motion->walk.gait_mode==AINEKIO_GAIT_CRAB ? "crab" :
            motion->walk.pose.run_blend>.5 ? "run" : "walk";
        motion->face_elapsed_us=(uint64_t)(motion->walk.phase*1000000.);
        *complete = motion->walk.complete;
        body.balance_hold=*complete;
    } else if(motion->kind==MOTION_POSE) {
        /* Retry the completed pose after a failed output write. It must not
         * enter the gesture player (nor accidentally play clip zero). */
        frame=motion->feedback_frame;
        *complete=true;
    } else {
        if (now < motion->started) return ESP_ERR_TIMEOUT;
        bool arrived=false;
        if(motion->clip_commanded_us) {
            const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
            arrived=ainekio_p4_feedback_check(calibration.joints,motion->feedback_targets,
                motion->clip_commanded_us,&motion->feedback_waiting_mask) && !motion->feedback_waiting_mask;
        }
        const double dt=(now-motion->clip_updated_us)/1e6;
        motion->clip_updated_us=now;
        if(!ainekio_v2_clip_player_tick(motion->clip,&motion->clip_player,dt,motion->clip_joint_speed,
            motion->playback_rate,arrived,&frame,&motion->face_elapsed_us))return ESP_FAIL;
        if(arrived) {
            motion->clip_commanded_us=0;
            motion->feedback_waiting_mask=0;
        }
        if(motion->clip_player.waiting && !motion->clip_commanded_us)
            motion->clip_pending_write=true;
        *complete = frame.phase == AINEKIO_V2_COMPLETE;
    }
    if(!motion_pulses(&frame,body.pulses))return ESP_ERR_INVALID_ARG;
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

static void report_stalled(uint16_t stalled,uint64_t now)
{
    if(stalled) {
        body.stalled_joints=stalled;body.stall_clock_us=now;
        if(!body.pending_jam.stalled_joints)
            body.pending_jam=(ainekio_p4_body_event_t){.connection=body.motion.connection,
                .sequence=body.motion.sequence,.jam_observation=true,.clock_us=now};
        body.pending_jam.stalled_joints|=stalled;
    }
    /* Retain an undelivered observation in this owner. The existing command
     * lifecycle reserves two queue slots for replacement/completion receipts. */
    if(body.pending_jam.stalled_joints && uxQueueSpacesAvailable(events)>2 &&
       xQueueSend(events,&body.pending_jam,0)==pdTRUE)
        body.pending_jam=(ainekio_p4_body_event_t){0};
}

/* Completion acknowledges reaching the goal once; it does not abandon that
 * standing goal. Drift is handled by the same full-pass planner, without a
 * second externally admitted command or another completion receipt. */
static void stand_hold_recover(void)
{
    if(!body.stand_goal_active || !ainekio_p4_feedback_stand_enabled() ||
       listen_requested || body.listen.active)return;
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    uint16_t remaining=0;
    if(!ainekio_p4_feedback_check(calibration.joints,body.pulses,
        body.stand_goal_since,&remaining) || !remaining)return;
    motion_t *motion=&body.motion;
    motion->kind=MOTION_POSE;motion->connection=0;motion->sequence=0;
    motion->entering=true;motion->balance_on_complete=true;
    motion->entry_to=body.pose;
    motion->feedback_commanded_us=body.stand_goal_since;
    motion->feedback_waiting_mask=remaining;
    memcpy(motion->feedback_targets,body.pulses,sizeof motion->feedback_targets);
    body.stand_goal_active=false;
    body.balance_hold=body.balance_settled=false;
}

/* One local output clock drives entry, algorithms, finite clips and holding.
 * Stop/generation fencing is checked before sampling and again by the driver. */
static bool output_step(uint64_t now)
{
    report_stalled(0,now);
    ainekio_pca9685_t *output = ainekio_p4_output();
    ainekio_pca_status_t status = ainekio_pca_status(output);
    if (body.active && (!status.armed || status.generation != body.generation)) {
        const esp_err_t error = status.fault == AINEKIO_PCA_FAULT_IO ? ESP_FAIL :
            status.fault == AINEKIO_PCA_FAULT_DEADLINE || status.fault == AINEKIO_PCA_FAULT_PROGRESS ?
            ESP_ERR_TIMEOUT : ESP_OK;
        stop_body(error);
    }
    if (!body.active || now < body.next_frame) return false;
    portENTER_CRITICAL(&pulse_lock);
    const uint64_t lost=disconnected_through;
    portEXIT_CRITICAL(&pulse_lock);
    /* Retain locally accepted work across link changes. Only an open-ended
     * gait needs an ending: the same Finish trajectory lands its feet and
     * keeps their final targets powered. A later session is independent. */
    if(body.motion.kind==MOTION_WALK && body.motion.connection &&
       body.motion.connection<=lost && !isfinite(body.motion.walk.end_phase) &&
       !body.motion.walk.stopping && !body.motion.walk.complete)
        (void)ainekio_v2_walk_update(&body.motion.walk,
            (ainekio_v2_walk_controls_t){0.,body.motion.walk.target.motion_rate});
    const uint64_t frame_started=esp_timer_get_time();
    if(body.motion.kind==MOTION_NONE)stand_hold_recover();
    const ainekio_p4_calibration_t feedback_mapping=ainekio_p4_calibration();
    uint16_t written[12];ainekio_p4_body_pulses(written);
    const bool stand_pass=body.motion.kind==MOTION_POSE && body.motion.balance_on_complete;
    const bool standing_goal=body.stand_goal_active && ainekio_p4_feedback_stand_enabled();
    const uint16_t stalled=stand_pass || standing_goal?0:
        ainekio_p4_feedback_stalled(&body.feedback_progress,feedback_mapping.joints,written);
    if(stalled) {
        report_stalled(stalled,now);
    }
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
        esp_err_t error=ESP_OK;
        if(body.balance_hold && !listen_requested && !body.listen.active) {
            balance_frame(&body.balance_nominal,body.balance_contacts ?
                (const double (*)[3])body.balance_anchors : NULL,now,&sampled);
            if(body.balance_settled) {
                /* PCA9685 continues its existing PWM autonomously. Monitor only:
                 * no IK/FK, shaft conversion, target rewrite or I2C transfer. */
                portENTER_CRITICAL(&pulse_lock);
                motion_status.balance_settled=true;
                motion_status.balance_active=motion_status.balance_reduced=false;
                motion_status.body_roll_rad=(float)body.balance.measured[0];
                motion_status.body_pitch_rad=(float)body.balance.measured[1];
                motion_status.balance_tracking_active=motion_status.balance_tracking_reduced=false;
                memset(motion_status.balance_tracking_error_deg,0,sizeof motion_status.balance_tracking_error_deg);
                memset(motion_status.balance_tracking_trim_deg,0,sizeof motion_status.balance_tracking_trim_deg);
                memset(motion_status.balance_tracking_lag_rad,0,sizeof motion_status.balance_tracking_lag_rad);
                portEXIT_CRITICAL(&pulse_lock);
                body.last_frame=esp_timer_get_time();body.next_frame=now+UINT64_C(20000);
                return true;
            }
            sampling=true;
            if(!motion_pulses(&sampled,body.pulses)) {
                ainekio_p4_log_stage("stationary leveling target cannot map to PWM");
                error=ESP_ERR_INVALID_ARG;
            }
        } else { body.balance_settled=false;error = listen_frame(now, &sampled, &sampling); }
        if (error != ESP_OK) { fail_motion(error); return false; }
    }
    if(complete && body.motion.kind==MOTION_POSE)body.motion.feedback_frame=sampled;
    const uint64_t calculated=esp_timer_get_time();
    const ainekio_pca_result_t write_result=ainekio_pca_write_frame(output,body.generation,body.pulses);
    record_frame_timing(calculated-frame_started,(uint64_t)esp_timer_get_time()-frame_started);
    if (write_result == AINEKIO_PCA_TIMEOUT) {
        /* No completed frame or completion receipt: retain the current output
         * and let the normal frame scheduler make its next write. */
        body.next_frame = now + UINT64_C(20000);
        return false;
    }
    if (write_result != AINEKIO_PCA_OK) {
        fail_motion(ESP_FAIL);
        return false;
    }
    if(sampling) {
        body.pose=sampled;
        body.pose_valid=!body.motion.startup_entry;
    }
    else if(was_ramping && !body.ramping)retain_manual_reference();
    if(body.motion.feedback_pending_write) {
        body.motion.feedback_pending_write=false;
        body.motion.feedback_commanded_us=esp_timer_get_time();
        memcpy(body.motion.feedback_targets,body.pulses,sizeof(body.pulses));
    }
    if(body.motion.clip_pending_write) {
        body.motion.clip_pending_write=false;
        body.motion.clip_commanded_us=esp_timer_get_time();
        memcpy(body.motion.feedback_targets,body.pulses,sizeof(body.pulses));
    }
    if(body.stand_goal_active && memcmp(written,body.pulses,sizeof written))
        body.stand_goal_since=esp_timer_get_time();
    publish_execution(now,sampling,was_ramping || body.ramping);
    publish(body.pulses);
    publish_motion();
    body.last_frame = esp_timer_get_time();
    /* Compute/write time consumes this frame's budget instead of extending the
     * next interval. If late, sample the current time once; never replay missed
     * frames. Completion time remains the independent output progress clock. */
    body.next_frame = now + UINT64_C(20000);
    if (body.motion.kind == MOTION_FREESTYLE) {
        motion_t *motion=&body.motion;
        const ainekio_motion_plan_frame_t *target=&motion->freestyle.plan.frames[motion->freestyle.index];
        if (now-motion->freestyle.frame_start >= (uint64_t)target->duration_ms*1000U) {
            if (!complete) {
                motion->freestyle.index++;
                motion->freestyle.from=sampled;
                motion->freestyle.frame_start=now;
            } else if (motion->freestyle.plan.end != AINEKIO_MOTION_PLAN_END_HOLD) {
                const body_request_t ending={.generation=body.generation,.deadline=UINT64_MAX,
                    .connection=motion->connection,.sequence=motion->sequence,.execute=true,
                    .intent={.kind=motion->freestyle.plan.end==AINEKIO_MOTION_PLAN_END_STAND ?
                        AINEKIO_INTENT_STAND : AINEKIO_INTENT_NEUTRAL}};
                /* Explicit end-pose belongs to this same completion receipt. */
                motion->kind=MOTION_NONE;
                const esp_err_t result=start_motion(&ending,now);
                if (result!=ESP_OK) {
                    motion->kind=MOTION_FREESTYLE;
                    fail_motion(result);
                }
                complete=false;
            }
        }
    }
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
    ainekio_p4_body_activity();
    if(!request->hold)rest_eligible=request->execute || request->freestyle;
    if (request->hold) {
        body.listen.active = false;
        ainekio_p4_body_listen(false);
        finish_motion(false, ESP_OK);
        body.ramping = false;
        body.balance_hold=false;body.balance_settled=false;body.balance_target_valid=false;body.balance_tracking_active=false;body.balance=(ainekio_v2_balance_t){0};
        publish_motion();
        if (!status.armed) stop_body(ESP_OK);
        return ESP_OK;
    }
    const ainekio_p4_system_status_t system = ainekio_p4_system_status();
    if (!request->prepare && (system.restart_pending || system.state == AINEKIO_STATE_DOZING ||
                             system.state == AINEKIO_STATE_DEEP_SLEEP)) return ESP_ERR_INVALID_STATE;
    if (request->freestyle) return start_freestyle(request, now);
    if (request->execute) return start_motion(request, now);
    if (request->prepare && status.armed) return ESP_ERR_INVALID_STATE;
    if (!status.armed && ainekio_pca_recover(output, request->generation) != AINEKIO_PCA_OK)
        return ESP_ERR_INVALID_STATE;
    body.listen.active = false;
    ainekio_p4_body_listen(false);
    finish_motion(false, ESP_OK);
    body.balance_hold=false;body.balance_settled=false;body.balance_target_valid=false;body.balance_tracking_active=false;body.balance=(ainekio_v2_balance_t){0};
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

/* Called by the existing output owner. Only state changes rearm the timer;
 * there is no new polling task, periodic timer or per-frame deadline scan. */
static void rest_step(uint64_t now)
{
    bool listening;
    portENTER_CRITICAL(&pulse_lock);
    listening=listen_requested;
    portEXIT_CRITICAL(&pulse_lock);
    const bool busy=body.motion.kind!=MOTION_NONE || body.ramping || listening || body.listen.active;
    const unsigned revision=atomic_load(&activity_revision);
    if(revision!=rest_revision || busy!=rest_busy) {
        rest_revision=revision;rest_busy=busy;
        esp_timer_stop(rest_timer);
        atomic_store(&rest_expired,false);
        rest_deadline=0;
        const uint32_t seconds=ainekio_p4_idle_rest_seconds();
        if(!busy && rest_eligible && body.active && seconds) {
            rest_deadline=now+(uint64_t)seconds*1000000;
            if(esp_timer_start_once(rest_timer,(uint64_t)seconds*1000000)!=ESP_OK) {
                rest_deadline=0;
                puts("Unable to arm inactivity rest timer");
            }
        }
    }
    if(!atomic_exchange(&rest_expired,false) || !rest_deadline || now<rest_deadline)return;
    rest_deadline=0;
    /* A stale callback cannot override a new command or released outputs.
     * Long audio finishes through its existing callback, which resets activity. */
    if(busy || !rest_eligible || !body.active ||
       !ainekio_pca_status(ainekio_p4_output()).armed ||
       ainekio_p4_media_status().speaker_busy)return;
    body_request_t request={.generation=body.generation,.deadline=UINT64_MAX,.execute=true,
        .intent={.kind=AINEKIO_INTENT_EMOTE}};
    strcpy(request.intent.data.asset,"lay_down");
    rest_eligible=false; /* One rest per activity period, never repeated clips. */
    const esp_err_t result=start_motion(&request,now);
    if(result==ESP_OK)body.motion.release_on_complete=true;
    else printf("Inactivity lay-down failed: %d\n",(int)result);
}

static void output_task(void *arg)
{
    (void)arg;
    for (;;) {
        output_step(esp_timer_get_time());
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
        }
        rest_step(esp_timer_get_time());
        /* Yield after a late frame without adding another 5 ms of lateness.
         * The next iteration samples current time without replaying outputs. */
        vTaskDelay(body.active && (uint64_t)esp_timer_get_time() >= body.next_frame ?
            1 : pdMS_TO_TICKS(5));
    }
}

esp_err_t ainekio_p4_body_start(void)
{
    disconnected_through=0;
    rest_deadline=0;rest_revision=0;rest_busy=false;rest_eligible=false;
    atomic_store(&activity_revision,0);atomic_store(&rest_expired,false);
    if(!rest_timer) {
        const esp_timer_create_args_t timer={.callback=rest_timeout,.name="idle_rest"};
        const esp_err_t result=esp_timer_create(&timer,&rest_timer);
        if(result!=ESP_OK)return result;
    } else esp_timer_stop(rest_timer);
    memset(execution_history,0,sizeof execution_history);execution_history_next=0;
    requests = xQueueCreate(1, sizeof(body_request_t));
    results = xQueueCreate(1, sizeof(body_result_t));
    events = xQueueCreate(16, sizeof(ainekio_p4_body_event_t));
    caller_lock = xSemaphoreCreateMutex();
    if (!requests || !results || !events || !caller_lock) return ESP_ERR_NO_MEM;
    return xTaskCreatePinnedToCore(output_task, "body_output", 16384, NULL, 10, &output_handle, 1) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
