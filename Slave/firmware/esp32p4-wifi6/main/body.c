#include "body.h"
#include "board.h"
#include "system.h"
#include "config.h"
#include "servo_feedback.h"
#include "ainekio/v2_walk.h"
#include "ainekio/v2_limits.h"
#include "ainekio/v2_posture.h"
#include "ainekio/v2_balance.h"
#include "ainekio/p4_imu.h"

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
    bool feedback_pending_write;
    uint64_t feedback_commanded_us;
    uint16_t feedback_waiting_mask, feedback_targets[12];
    double feedback_confirmed_progress;
    double posture_progress;
    /* Only one entry planner is active for a motion. */
    union {
        ainekio_v2_posture_t posture;
        ainekio_v2_rise_t rise;
    };
    size_t clip, recovery_clip;
    float playback_rate, requested_rate;
    float entry_rate;
    const char *face_command;
    uint64_t face_elapsed_us;
    uint32_t face_revision;
    bool face_is_clip;
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

static void publish_motion(void)
{
    ainekio_p4_body_status_t value = {
        .connection=body.motion.connection, .sequence=body.motion.sequence,
        .moving=body.motion.kind != MOTION_NONE,
        .listening_feedback=body.listen.active,
        .balance_active=ainekio_p4_balance_enabled() && body.balance.sensor_usable && !body.balance_settled && (body.balance_hold ||
            (body.motion.kind!=MOTION_NONE && (body.motion.contact_entry ||
                body.motion.startup_entry || body.motion.kind==MOTION_WALK))),
        .balance_reduced=body.balance.reduced,
        .balance_settled=body.balance_settled && body.balance_hold && ainekio_p4_balance_enabled(),
        .balance_tracking_available=body.balance_tracking_available,
        .balance_tracking_active=body.balance_tracking_active && body.balance_hold &&
            ainekio_p4_balance_enabled(),
        .balance_tracking_reduced=body.balance_tracking_active && body.balance_tracking.reduced,
        .servo_feedback_waiting=body.motion.feedback_commanded_us!=0 && ainekio_p4_feedback_stand_enabled(),
        .servo_feedback_waiting_mask=body.motion.feedback_waiting_mask,
        .stand_progress=(float)(body.motion.posture_progress/ainekio_v2_posture_path_length()),
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
    publish_motion();
}

static void stop_body(esp_err_t result)
{
    body.listen.active = false;
    ainekio_p4_body_listen(false);
    finish_motion(false, result);
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
            body.balance_tracking_active=false;
            memset(&body.balance_tracking,0,sizeof body.balance_tracking);
            *frame=body.pose; /* Keep the achieved pose, including any accepted tracking trim. */
            return;
        }
    }
    body.balance_settled=false;
    /* Gyro integration owns the desired pose, while the separate servo loop
     * owns its tracking trim. Feeding trim back as the next gyro target would
     * accumulate a correction even with zero attitude error. */
    const ainekio_v2_frame_t *previous=standing&&body.balance_target_valid ?
        &body.balance_target : &body.pose;
    /* Correct body attitude toward the saved reference. Mirrored servo
     * directions belong to the joint mapper, not the outer feedback sign. */
    ainekio_v2_balance_configured_apply(
        &body.balance,imu.attitude.orientation_wxyz,
        imu.attitude.angular_rate_rad_s,leveling,dt,
        nominal,anchors,previous,ainekio_v2_gait_joint_speed_limit(),&adjusted,&tuning,standing);
    *frame=adjusted.frame;
    body.balance_target=adjusted.frame;body.balance_target_valid=standing;
    body.balance_tracking_active=false;
    memset(&body.balance_tracking,0,sizeof body.balance_tracking);
    ainekio_v2_frame_t measured=adjusted.frame;
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    body.balance_tracking_available=ainekio_p4_feedback_frame(calibration.joints,&measured);
    if(standing && leveling && body.balance_tracking_available) {
        double tolerance[12];
        for(unsigned j=0;j<12;j++)tolerance[j]=BALANCE_SHAFT_TOLERANCE_US/calibration.joints[j].us_per_degree;
        ainekio_v2_balance_track_tolerant(&adjusted.frame,&measured,&body.pose,tolerance,dt,
            ainekio_v2_gait_joint_speed_limit(),frame,&body.balance_tracking);
        body.balance_tracking_active=true;
    }
    body.balance_nominal=*nominal;
    body.balance_contacts=anchors!=NULL;
    if(anchors && anchors!=(const double (*)[3])body.balance_anchors)
        memcpy(body.balance_anchors,anchors,sizeof(body.balance_anchors));
}

/* Startup has no shaft readback. Send the fold target at once and allow the
 * profile's full stroke at its nominal servo rate, not an eased movement.
 * This is an arrival estimate, never a measured position acknowledgement. */
static uint64_t startup_fold_us(void)
{
    return (uint64_t)ceil(ainekio_v2_profile_travel_degrees()/
        ainekio_v2_joint_speed_default()*1e6);
}
#define STARTUP_PAIR_OFFSET_US UINT64_C(20000)
/* Model joints 6..11 are physically front; 0..5 rear. CAD names are reversed.
 * Use joint roles, never the configurable PCA channel number, for timing. */
static uint64_t startup_pair_offset(unsigned joint)
{
    return joint<6?STARTUP_PAIR_OFFSET_US:0;
}
static esp_err_t start_rise(const body_request_t *request,uint64_t now)
{
    motion_t next={.kind=MOTION_POSE,.connection=request->connection,
        .sequence=request->sequence,.face_command="stand",
        .face_revision=body.motion.face_revision+1,.entering=true,.startup_entry=true,
        .entry_start=now,.requested_rate=1.F,.entry_rate=1.F,.playback_rate=1.F};
    if(!ainekio_v2_rise_begin(&next.rise))return ESP_ERR_INVALID_ARG;
    next.entry_from=next.rise.crouch.frame;
    next.entry_to=next.rise.stand.frame;
    const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
    uint16_t initial[AINEKIO_PCA_BODY_CHANNELS];
    if(!calibration.valid || !calibration.profile_confirmed)return ESP_ERR_INVALID_STATE;
    if(!ainekio_p4_frame_pulses(&next.rise.crouch.frame,initial) ||
       !ainekio_p4_frame_pulses(&next.rise.stand.frame,next.target))return ESP_ERR_INVALID_ARG;
    for(unsigned j=0;j<AINEKIO_BODY_JOINT_COUNT;j++)
        if(calibration.joints[j].channel>=0 && (j%3==0 || startup_pair_offset(j)))
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
    retain_pose(&next.rise.crouch.frame,&calibration);
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
    if(request->intent.kind==AINEKIO_INTENT_STAND)
        next.requested_rate=next.playback_rate=1.F;
    ainekio_v2_frame_t frame = {.geometry_id=ainekio_v2_walk_geometry_id};
    if (request->intent.kind == AINEKIO_INTENT_WALK) {
        next.kind = MOTION_WALK;
        next.entering = false;
        next.started = now;
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
        /* Calibration Home is only requested explicitly. Detached named
         * motions engage their own entry pose; Stand uses start_rise above. */
        memcpy(next.from, next.target, sizeof(next.from));
    } else memcpy(next.from, body.pulses, sizeof(next.from));
    if (home) next.entry_from=frame;
    else next.entry_from=body.pose;
    if(request->intent.kind==AINEKIO_INTENT_STAND&&ainekio_p4_feedback_stand_enabled()) {
        if(!ainekio_p4_feedback_frame(calibration.joints,&next.entry_from))return ESP_ERR_INVALID_STATE;
        if(!ainekio_p4_frame_pulses(&next.entry_from,next.from))return ESP_ERR_INVALID_ARG;
    }
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
                next.entry_duration = ainekio_v2_clips[next.recovery_clip].duration_us + GROUNDED_ALIGN_US;
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
    else if (next.reverse_grounded_entry)
        next.entry_rate = fminf(ainekio_v2_clip_playback_rate(next.recovery_clip, next.requested_rate),
            ainekio_v2_speed_limited_rate(align_peak,next.requested_rate));
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
    if (!ainekio_p4_frame_pulses(&from,pulses)) return ESP_ERR_INVALID_ARG;
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
    if (!ainekio_p4_frame_pulses(frame,body.pulses)) return ESP_ERR_INVALID_ARG;
    /* Emit every authored endpoint even when it falls between 50 Hz output
     * ticks. Advance after the actual write, so an I2C retry cannot skip it. */
    *complete=u==1. && index+1==plan->frame_count;
    return ESP_OK;
}

static esp_err_t motion_frame(uint64_t now, bool *complete, ainekio_v2_frame_t *sampled)
{
    motion_t *motion = &body.motion;
    *complete = false;
    if (motion->kind == MOTION_FREESTYLE) return freestyle_frame(now,complete,sampled);
    const bool feedback=ainekio_p4_feedback_stand_enabled();
    if(motion->feedback_commanded_us) {
        if(feedback) {
            const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
            if(!ainekio_p4_feedback_arrived(calibration.joints,motion->feedback_targets,
                motion->feedback_commanded_us,&motion->feedback_waiting_mask)) {
                *sampled=body.pose;
                memcpy(body.pulses,motion->feedback_targets,sizeof(body.pulses));
                return ESP_OK;
            }
        }
        motion->feedback_commanded_us=0;motion->feedback_waiting_mask=0;
        motion->feedback_confirmed_progress=motion->posture_progress;
        if(motion->startup_entry&&!motion->contact_entry) {
            if(feedback) {
                const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
                if(!ainekio_p4_feedback_frame(calibration.joints,&motion->entry_from))
                    return ESP_ERR_INVALID_STATE;
            }
            double euler[3];starting_attitude(euler);
            if(!ainekio_v2_posture_begin(&motion->posture,&motion->entry_from,&motion->entry_to,euler))
                return ESP_ERR_INVALID_ARG;
            motion->contact_entry=true;motion->posture_progress=0.;
        } else if(motion->contact_entry &&
                  motion->posture_progress>=ainekio_v2_posture_path_length()) {
            /* Complete the target whose physical arrival was just measured.
             * Standing balance can resume on the following output tick. */
            *sampled=body.pose;
            memcpy(body.pulses,motion->feedback_targets,sizeof(body.pulses));
            motion->startup_entry=false;motion->entering=false;motion->started=now;
            *complete=motion->kind==MOTION_POSE;body.balance_hold=*complete;
            return ESP_OK;
        }
    }
    if(motion->startup_entry && !motion->contact_entry) {
        const uint64_t elapsed=now-motion->entry_start;
        if(feedback || elapsed<startup_fold_us()+STARTUP_PAIR_OFFSET_US) {
            *sampled=motion->entry_from;
            if(!ainekio_p4_frame_pulses(sampled,body.pulses))return ESP_ERR_INVALID_ARG;
            const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
            for(unsigned j=0;j<AINEKIO_BODY_JOINT_COUNT;j++) {
                const int ch=calibration.joints[j].channel;
                if(ch>=0 && (j%3==0 || elapsed<startup_pair_offset(j)))body.pulses[ch]=0;
            }
            if(feedback&&elapsed>=STARTUP_PAIR_OFFSET_US)motion->feedback_pending_write=true;
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
            const bool already_at_end=motion->posture_progress>=ainekio_v2_posture_path_length();
            if(!ainekio_v2_posture_advance(&motion->posture,&motion->posture_progress,dt))
                return ESP_ERR_INVALID_ARG;
            motion->entry_rate=1.F;
            balance_frame(&motion->posture.pose,(const double (*)[3])motion->posture.anchors,now,sampled);
            body.balance_nominal=motion->posture.pose;
            body.balance_contacts=true;
            memcpy(body.balance_anchors,motion->posture.anchors,sizeof(body.balance_anchors));
            if(!ainekio_p4_frame_pulses(sampled,body.pulses))return ESP_ERR_INVALID_ARG;
            if(motion->startup_entry) {
                const ainekio_p4_calibration_t calibration=ainekio_p4_calibration();
                for(unsigned leg=0;leg<4;leg++) {
                    int ch=calibration.joints[3*leg].channel;
                    const double progress=feedback?motion->feedback_confirmed_progress:motion->posture_progress;
                    if(ch>=0 && !ainekio_v2_posture_shoulder_engaged(progress,leg))
                        body.pulses[ch]=0;
                }
            }
            if(feedback&&!already_at_end&&ainekio_v2_posture_landmark(motion->posture_progress))
                motion->feedback_pending_write=true;
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
        const float u = fminf(1.F, ((float)(now-motion->entry_start)/motion->entry_duration) * motion->entry_rate);
        /* Evaluate the nearer half in double. Mixed-precision u*u*u rounded
         * the upper end above 1 and rejected otherwise valid entry frames. */
        const double half = u <= .5F ? u : 1.-u;
        const double ramp = half*half*half*(10.+half*(-15.+6.*half));
        const double smooth = u <= .5F ? ramp : 1.-ramp;
        ainekio_v2_frame_t entry;
        bool entry_ok;
        if (motion->reverse_grounded_entry) {
            const uint64_t clip_duration = ainekio_v2_clips[motion->recovery_clip].duration_us;
            const double elapsed = fmin((double)motion->entry_duration,
                (double)(now-motion->entry_start)*motion->entry_rate);
            if (elapsed < clip_duration)
                entry_ok = ainekio_v2_clip_sample(motion->recovery_clip,
                    clip_duration-(uint64_t)elapsed, &entry);
            else {
                ainekio_v2_frame_t clip_start;
                const double align = (elapsed-clip_duration)/GROUNDED_ALIGN_US;
                const double ease = align*align*align*(10.+align*(-15.+6.*align));
                entry_ok = ainekio_v2_clip_sample(motion->recovery_clip, 0, &clip_start) &&
                    ainekio_v2_transition(&clip_start, &motion->entry_to, ease, &entry);
            }
        } else entry_ok = ainekio_v2_transition(&motion->entry_from, &motion->entry_to, smooth, &entry);
        if (!entry_ok || !ainekio_p4_frame_pulses(&entry, body.pulses)) return ESP_ERR_INVALID_ARG;
        if (u == 1.) {
            motion->entering = false;
            motion->started = now;
            if (motion->kind == MOTION_WALK) motion->walk.last_us = now;
            *complete = motion->kind == MOTION_POSE;
            if(motion->balance_on_complete) {
                const double level[3]={0};
                if(!ainekio_v2_posture_begin(&motion->posture,&entry,&entry,level))return ESP_ERR_INVALID_ARG;
                body.balance_nominal=motion->posture.pose;
                memcpy(body.balance_anchors,motion->posture.anchors,sizeof(body.balance_anchors));
                body.balance_contacts=body.balance_hold=true;
            }
        }
        *sampled=entry;
        return ESP_OK;
    }
    ainekio_v2_frame_t frame;
    if (motion->kind == MOTION_WALK) {
        if (!ainekio_v2_walk_tick(&motion->walk, now)) return ESP_FAIL;
        balance_frame(&motion->walk.pose,NULL,now,&frame);
        motion->face_command=motion->walk.gait_mode==AINEKIO_GAIT_CRAWL ? "crawl" :
            motion->walk.gait_mode==AINEKIO_GAIT_CRAB ? "crab" :
            motion->walk.pose.run_blend>.5 ? "run" : "walk";
        motion->face_elapsed_us=(uint64_t)(motion->walk.phase*1000000.);
        *complete = motion->walk.complete;
        body.balance_hold=*complete;
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
                portEXIT_CRITICAL(&pulse_lock);
                body.last_frame=esp_timer_get_time();body.next_frame=now+UINT64_C(20000);
                return true;
            }
            sampling=true;
            if(!ainekio_p4_frame_pulses(&sampled,body.pulses))error=ESP_ERR_INVALID_ARG;
        } else { body.balance_settled=false;error = listen_frame(now, &sampled, &sampling); }
        if (error != ESP_OK) { fail_motion(error); return false; }
    }
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
        /* Yield after a late frame without adding another 5 ms of lateness.
         * The next iteration samples current time without replaying outputs. */
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
    return xTaskCreatePinnedToCore(output_task, "body_output", 16384, NULL, 10, &output_handle, 1) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
