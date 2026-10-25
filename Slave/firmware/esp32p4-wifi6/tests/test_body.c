/* Host scheduler/driver boundary; executes the production body owner and native
 * model. No alternate motion implementation or firmware diagnostic path. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../main/body.c"
void ainekio_p4_gait_trace_output(const uint16_t pulses[12],uint64_t timestamp_us,bool armed)
{ (void)pulses;(void)timestamp_us;(void)armed; }
void ainekio_p4_log_stage(const char *stage){assert(stage && *stage);}
#include "ainekio/control_codec.h"
static float saved_motion_rate=1.F;
static bool leveling_enabled=true;
static ainekio_v2_balance_tuning_t leveling_tuning=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
ainekio_v2_balance_tuning_t ainekio_p4_balance_tuning(void) { return leveling_tuning; }
static bool walking_feedback_enabled;
bool ainekio_p4_walking_feedback_enabled(void) { return walking_feedback_enabled; }
bool ainekio_p4_balance_enabled(void) { return leveling_enabled; }
static ainekio_p4_imu_status_t imu_status;
ainekio_p4_imu_status_t ainekio_p4_imu_status(void){return imu_status;}
float ainekio_p4_motion_rate(void) { return saved_motion_rate; }

struct test_queue { unsigned capacity, size, count; unsigned char data[]; };
static uint64_t clock_us;
static uint32_t rest_seconds=180;
static bool speaker_busy;
uint32_t ainekio_p4_idle_rest_seconds(void) { return rest_seconds; }
ainekio_p4_media_status_t ainekio_p4_media_status(void)
{ return (ainekio_p4_media_status_t){.speaker_busy=speaker_busy}; }
struct test_timer { esp_timer_create_args_t args; uint64_t due; };
esp_err_t esp_timer_create(const esp_timer_create_args_t *a,esp_timer_handle_t *h)
{ *h=calloc(1,sizeof **h);(*h)->args=*a;return ESP_OK; }
esp_err_t esp_timer_start_once(esp_timer_handle_t t,uint64_t delay)
{ assert(!t->due);t->due=clock_us+delay;return ESP_OK; }
esp_err_t esp_timer_stop(esp_timer_handle_t t) { t->due=0;return ESP_OK; }
static void rest_tick(void)
{
    if(rest_timer->due && clock_us>=rest_timer->due) {
        rest_timer->due=0;rest_timer->args.callback(rest_timer->args.arg);
    }
    rest_step(clock_us);
}

static uint64_t mapping_delay_us, write_delay_us, last_mapping_started, last_write_started;
static ainekio_pca9685_t driver;
static unsigned writes, shaft_feedback_reads, shaft_goal_checks, shaft_jam_checks;
static bool shaft_sample_available;
static uint16_t last_written[12];
static unsigned enabled = 0xfff;
static bool mapping_failure, driver_failure, driver_timeout, defer_requests, power_pending;
static ainekio_body_state_t system_state;
static ainekio_p4_joint_config_t mapped_joints[12];
static bool shaft_feedback_enabled, shaft_feedback_reached, shaft_jam_enabled;
static bool shaft_tracking_available, shaft_measured_override;
static bool shaft_simulated;
static double shaft_pulses[12];
static ainekio_v2_frame_t shaft_measured;
static uint16_t shaft_wait_mask, shaft_stalled_mask;
uint16_t ainekio_p4_feedback_stalled(ainekio_p4_feedback_progress_t *progress,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets)
{
    (void)mapping;(void)targets;shaft_jam_checks++;
    uint16_t observed=0;
    for(unsigned j=0;j<12;j++) {
        if(!shaft_jam_enabled || !(shaft_stalled_mask&(1U<<j)))progress->joint[j].reported=false;
        else if(!progress->joint[j].reported) {
            observed|=1U<<j;progress->joint[j].reported=true;
        }
    }
    return observed;
}
bool ainekio_p4_feedback_stand_enabled(void){return shaft_feedback_enabled;}
bool ainekio_p4_feedback_jam_enabled(void){return shaft_jam_enabled;}
bool ainekio_p4_feedback_frame(const ainekio_p4_joint_config_t *mapping,ainekio_v2_frame_t *frame)
{
    shaft_feedback_reads++;
    if(shaft_simulated) {
        uint16_t measured[12];
        for(unsigned c=0;c<12;c++)measured[c]=(uint16_t)lround(shaft_pulses[c]);
        return ainekio_p4_joint_unmap_frame(mapping,measured,frame);
    }
    if(!shaft_tracking_available && !shaft_feedback_enabled && !shaft_jam_enabled)return false;
    if(shaft_measured_override){*frame=shaft_measured;return true;}
    uint16_t measured[12];memcpy(measured,last_written,sizeof measured);
    uint16_t modeled[12];assert(ainekio_p4_joint_map_frame(mapping,frame,modeled));
    /* An unpowered shoulder still has a physical position. This test starts
     * it at the crouch shoulder angle; real feedback reads its potentiometer. */
    for(unsigned i=0;i<12;i++)if(!measured[i])measured[i]=modeled[i];
    return ainekio_p4_joint_unmap_frame(mapping,measured,frame);
}
bool ainekio_p4_feedback_check(const ainekio_p4_joint_config_t *mapping,
    const uint16_t *targets,int64_t commanded_us,uint16_t *waiting)
{
    assert(commanded_us>0 && commanded_us<=(int64_t)clock_us);
    shaft_goal_checks++;
    if(!shaft_sample_available){*waiting=0xfff;return false;}
    *waiting=0;
    if(shaft_simulated) {
        for(unsigned j=0;j<12;j++) {
            int c=mapping[j].channel;
            if(c>=0 && targets[c] && fabs(shaft_pulses[c]-targets[c])>30.)*waiting|=1U<<j;
        }
        return true;
    }
    for(unsigned j=0;j<12;j++)if(mapping[j].channel>=0 && targets[mapping[j].channel] &&
        shaft_feedback_enabled && !shaft_feedback_reached && (shaft_wait_mask&(1U<<j)))*waiting|=1U<<j;
    return true;
}

QueueHandle_t xQueueCreate(unsigned n, unsigned size)
{
    QueueHandle_t q=calloc(1,sizeof(*q)+n*size); assert(q); q->capacity=n; q->size=size; return q;
}
int xQueueSend(QueueHandle_t q,const void *p,unsigned timeout)
{
    (void)timeout; if(q->count==q->capacity)return 0;
    memcpy(q->data+q->size*q->count++,p,q->size); return 1;
}
int xQueueReceive(QueueHandle_t q,void *p,unsigned timeout)
{
    /* Let the sole output owner service a synchronous caller's admission. */
    if(q==results && !q->count && timeout && requests->count && !defer_requests) {
        body_request_t request; assert(xQueueReceive(requests,&request,0));
        body_result_t result={request.serial,process_request(&request,clock_us)};
        if(result.result==ESP_OK && request.home && body.active && body.ramping) {
            body.pending_home=request.serial;
            while(body.pending_home && timeout>=20) { clock_us+=20000; output_step(clock_us); timeout-=20; }
        } else assert(xQueueSend(results,&result,0));
    }
    if(!q->count)return 0;
    memcpy(p,q->data,q->size); --q->count; memmove(q->data,q->data+q->size,q->count*q->size); return 1;
}
int xQueueOverwrite(QueueHandle_t q,const void *p)
{ assert(q->capacity==1); q->count=0; return xQueueSend(q,p,0); }
unsigned uxQueueSpacesAvailable(QueueHandle_t q) { return q->capacity-q->count; }
unsigned uxQueueMessagesWaiting(QueueHandle_t q) { return q->count; }
void *xSemaphoreCreateMutex(void) { return (void *)1; }
int xSemaphoreTake(void *p,unsigned t) { (void)p;(void)t;return 1; }
int xSemaphoreGive(void *p) { (void)p;return 1; }
int xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned stack,void*a,unsigned pri,void*h,unsigned core)
{ (void)fn;(void)n;(void)stack;(void)a;(void)pri;(void)h;(void)core;return 1; }
void vTaskDelay(unsigned t) { clock_us+=(uint64_t)t*1000; }
int64_t esp_timer_get_time(void) { return (int64_t)clock_us; }
ainekio_p4_system_status_t ainekio_p4_system_status(void)
{ return (ainekio_p4_system_status_t){.restart_pending=power_pending, .state=system_state}; }
ainekio_pca9685_t *ainekio_p4_output(void) { return &driver; }
bool ainekio_pca_pulse_valid(const ainekio_pca9685_t *d,uint16_t pulse)
{ (void)d; return pulse>=3 && pulse<=19986; } /* Nominal25MHz, prescale121 timer fixture. */
ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *d) { return d->state; }
void ainekio_pca_emergency_disable(ainekio_pca9685_t *d,ainekio_pca_fault_t f)
{ d->state.armed=false;d->state.fault=f;++d->state.generation; }
void ainekio_pca_idle(ainekio_pca9685_t *d) { d->state.armed=false; }
void ainekio_pca_disarm(ainekio_pca9685_t *d)
{ ainekio_pca_emergency_disable(d,AINEKIO_PCA_FAULT_NONE); }
ainekio_pca_result_t ainekio_pca_recover(ainekio_pca9685_t *d,uint64_t g)
{ return g==d->state.generation && !d->state.armed ? AINEKIO_PCA_OK : AINEKIO_PCA_STALE; }
static ainekio_pca_result_t write_pulses(ainekio_pca9685_t*d,uint64_t g,const uint16_t*p)
{
    if(g!=d->state.generation)return AINEKIO_PCA_STALE;
    if(driver_failure)return AINEKIO_PCA_IO;
    if(driver_timeout)return AINEKIO_PCA_TIMEOUT;
    for(unsigned i=0;i<12;i++)assert(!p[i] || ainekio_pca_pulse_valid(d,p[i]));
    last_write_started=clock_us;clock_us+=write_delay_us;
    memcpy(last_written,p,sizeof(last_written));writes++;d->state.last_frame_us=clock_us;return AINEKIO_PCA_OK;
}
ainekio_pca_result_t ainekio_pca_arm(ainekio_pca9685_t*d,uint64_t g,const uint16_t p[12])
{ ainekio_pca_result_t r=write_pulses(d,g,p);if(r==AINEKIO_PCA_OK)d->state.armed=true;return r; }
ainekio_pca_result_t ainekio_pca_write_frame(ainekio_pca9685_t*d,uint64_t g,const uint16_t p[12])
{ if(!d->state.armed)return AINEKIO_PCA_DISARMED;return write_pulses(d,g,p); }
bool ainekio_p4_home_pulses(uint16_t p[12])
{
    memset(p,0,12*sizeof(*p));
    for(unsigned i=0;i<12;i++)if(enabled&(1u<<i)) {
        const ainekio_p4_joint_config_t *j=&mapped_joints[i];
        if(j->channel>=0)p[j->channel]=j->home_us;
    }
    return true;
}
bool ainekio_p4_frame_pulses(const ainekio_v2_frame_t *f,uint16_t p[12])
{
    last_mapping_started=clock_us;clock_us+=mapping_delay_us;
    if(mapping_failure)return false;
    ainekio_p4_joint_config_t joints[12];memcpy(joints,mapped_joints,sizeof(joints));
    for(unsigned i=0;i<12;i++)if(!(enabled&(1u<<i)))joints[i].channel=-1;
    if(!ainekio_p4_joint_map_frame(joints,f,p))return false;
    for(unsigned i=0;i<12;i++)if(p[i]&&!ainekio_pca_pulse_valid(&driver,p[i])) {
        memset(p,0,12*sizeof(*p));return false;
    }
    return true;
}
ainekio_p4_calibration_t ainekio_p4_calibration(void)
{
    ainekio_p4_calibration_t state={.valid=true,.saved=true,.profile_confirmed=true};
    memcpy(state.joints,mapped_joints,sizeof(mapped_joints));
    for(unsigned i=0;i<12;i++)if(!(enabled&(1u<<i)))state.joints[i].channel=-1;
    return state;
}
static void reset(void)
{
    free(requests);free(results);free(events);requests=results=events=NULL;
    body=(body_state_t){0};motion_status=(ainekio_p4_body_status_t){0};
    ainekio_p4_body_listen(false);
    memset(commanded,0,sizeof(commanded));driver=(ainekio_pca9685_t){.state={.generation=1,.ready=true}};
    system_state=AINEKIO_STATE_IDLE;rest_seconds=180;speaker_busy=false;
    walking_feedback_enabled=false;
    saved_motion_rate=1.F;leveling_enabled=true;leveling_tuning=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
    shaft_feedback_enabled=shaft_feedback_reached=shaft_jam_enabled=false;shaft_wait_mask=0xfff;
    shaft_jam_checks=0;
    shaft_stalled_mask=0;shaft_goal_checks=0;shaft_sample_available=true;
    shaft_tracking_available=shaft_measured_override=false;
    shaft_simulated=false;
    imu_status=(ainekio_p4_imu_status_t){0};
    clock_us=1000000;writes=0;enabled=0xfff;mapping_failure=driver_failure=driver_timeout=defer_requests=power_pending=false;
    mapping_delay_us=write_delay_us=last_mapping_started=last_write_started=0;
    /* Broad test fixture for executor lifecycle coverage. The actual shipping
     * center-indexed calibration is exercised separately across the catalog. */
    for(unsigned i=0;i<12;i++)mapped_joints[i]=(ainekio_p4_joint_config_t){
        .channel=(int8_t)i,.home_us=1600,
        .home_cd=2000,.us_per_degree=5};
    assert(ainekio_p4_body_start()==ESP_OK);
    /* Established operator reference fixture. Tests below separately exercise
     * unknown/disarmed references and the real Home request. */
    driver.state.armed=true;driver.state.last_frame_us=clock_us;
    body.active=true;body.generation=driver.state.generation;
    body.last_frame=clock_us;body.next_frame=clock_us+20000;
    for(unsigned i=0;i<12;i++)body.pulses[i]=last_written[i]=1600;
    retain_manual_reference();
    publish(body.pulses);
}
static ainekio_command_t command(unsigned seq,ainekio_intent_kind_t kind)
{ return (ainekio_command_t){.sequence=seq,.kind=AINEKIO_COMMAND_INTENT,.data.intent={.kind=kind}}; }
static int execute(ainekio_command_t *c)
{ return ainekio_p4_body_execute(driver.state.generation,17,c); }
static void advance(unsigned ms)
{
    assert(ms%20==0);
    while(ms) {
        if(shaft_simulated)for(unsigned j=0;j<12;j++) {
            int c=mapped_joints[j].channel;if(c<0||!last_written[c])continue;
            /* Deliberately slower than the commanded path and unequal by
             * joint. This plant supplies observations, never completion. */
            double travel=(j%3?1800.:600.)*.02;
            double error=last_written[c]-shaft_pulses[c];
            shaft_pulses[c]+=fmax(-travel,fmin(travel,error));
        }
        clock_us+=20000;output_step(clock_us);rest_tick();ms-=20;
    }
}
static ainekio_p4_body_event_t finish_at(unsigned maximum_ms,unsigned line)
{
    ainekio_p4_body_event_t e;
    while(maximum_ms && !ainekio_p4_body_event(&e)) {advance(20);maximum_ms-=20;}
    if(!maximum_ms)fprintf(stderr,"Motion completion timed out at test line %u: kind=%u entering=%u contact_entry=%u posture_s=%.6f\n",
        line,body.motion.kind,body.motion.entering,body.motion.contact_entry,body.motion.posture_progress);
    assert(maximum_ms);return e;
}
#define finish(maximum_ms) finish_at((maximum_ms),__LINE__)
static void pose_and_replace(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_NEUTRAL);
    assert(execute(&c)==ESP_OK&&last_written[0]==1600);
    assert(ainekio_p4_body_status().moving);advance(200);
    assert(last_written[0]<1600&&last_written[0]>1500);
    c.sequence=2;c.data.intent.kind=AINEKIO_INTENT_STAND;
    const uint16_t before=last_written[0];assert(execute(&c)==ESP_OK&&last_written[0]==before);
    ainekio_p4_body_event_t e;assert(ainekio_p4_body_event(&e)&&e.sequence==1&&!e.completed&&e.result==ESP_OK);
    e=finish(10000);assert(e.sequence==2&&e.completed&&e.result==ESP_OK);
    uint16_t held[12];memcpy(held,last_written,sizeof(held));advance(100);
    assert(!memcmp(held,last_written,sizeof(held))&&!ainekio_p4_body_event(&e));
}
static void disconnected_motion_keeps_outputs(void)
{
    /* Finite trajectories are byte-for-byte identical with or without a link. */
    for(unsigned kind=0;kind<3;kind++) {
        uint16_t expected[12];unsigned normal_writes=0;
        for(unsigned lost=0;lost<2;lost++) {
            reset();leveling_enabled=false;
            ainekio_command_t c=command(560,kind==0?AINEKIO_INTENT_STAND:
                kind==1?AINEKIO_INTENT_SIT:AINEKIO_INTENT_WALK);
            if(kind==2)c.data.intent.data.walk.steps=2;
            assert(execute(&c)==ESP_OK);advance(100);
            const uint64_t generation=driver.state.generation;
            if(lost)ainekio_p4_body_connection_lost(17);
            ainekio_p4_body_event_t event=finish(70000);
            assert(event.completed && event.sequence==560 && event.result==ESP_OK);
            assert(driver.state.armed && driver.state.generation==generation);
            if(!lost){memcpy(expected,last_written,sizeof expected);normal_writes=writes;}
            else assert(writes==normal_writes && !memcmp(expected,last_written,sizeof expected));
            ainekio_p4_body_connection_lost(17);advance(2000);
            assert(driver.state.armed && !memcmp(expected,last_written,sizeof expected));
        }
    }
    const ainekio_gait_t gaits[]={AINEKIO_GAIT_WALK,AINEKIO_GAIT_CRAWL,AINEKIO_GAIT_RUN,AINEKIO_GAIT_CRAB};
    for(unsigned gait=0;gait<4;gait++)for(unsigned stage=0;stage<2;stage++) {
        reset();leveling_enabled=false;
        ainekio_command_t c=command(561,AINEKIO_INTENT_WALK);
        c.data.intent.data.walk.gait=gaits[gait];
        c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=50;
        assert(execute(&c)==ESP_OK);
        if(stage)advance(7000);
        assert(body.motion.kind==MOTION_WALK && !body.motion.walk.stopping);
        const uint64_t generation=driver.state.generation;
        ainekio_p4_body_connection_lost(17);
        assert(driver.state.armed && !body.motion.walk.stopping); /* asynchronous */
        advance(20);
        assert(body.motion.walk.stopping);
        ainekio_p4_body_event_t event=finish(70000);
        assert(event.completed && event.sequence==561 && event.result==ESP_OK);
        assert(driver.state.armed && driver.state.generation==generation);
        for(unsigned leg=0;leg<4;leg++)assert(body.motion.walk.pose.grounded[leg]);
    }
    /* A late old-session notice cannot finish movement from a new session. */
    reset();leveling_enabled=false;
    ainekio_p4_body_connection_lost(17);
    ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
    assert(ainekio_p4_body_execute(driver.state.generation,19,&c)==ESP_OK);
    ainekio_p4_body_connection_lost(17);advance(500);
    assert(body.motion.kind==MOTION_WALK && !body.motion.walk.stopping && driver.state.armed);
    /* Nor can a command accepted before loss miss the asynchronous notice. */
    reset();leveling_enabled=false;
    ainekio_p4_body_connection_lost(17);
    assert(execute(&c)==ESP_OK);advance(20);
    assert(body.motion.walk.stopping && driver.state.armed);
    assert(finish(70000).completed);
    puts("Disconnect preserves finite motion/hold, finishes all continuous gaits, and isolates later sessions.");
}

static void locomotion(void)
{
    for(unsigned gait=0;gait<3;gait++)for(unsigned dir=0;dir<4;dir++) {
        reset();ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
        c.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;c.data.intent.data.walk.gait=(ainekio_gait_t)gait;
        c.data.intent.data.walk.controls=2;c.data.intent.data.walk.stride_percent=50;c.data.intent.data.walk.motion_rate=3;
        assert(execute(&c)==ESP_OK);advance(6000);assert(ainekio_p4_body_status().moving);
        c.sequence=2;c.data.intent.data.walk.update_sequence=1;c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=0;
        assert(execute(&c)==ESP_OK);ainekio_p4_body_event_t e=finish(20000);
        assert(e.sequence==1&&e.completed&&e.result==ESP_OK&&!ainekio_p4_body_event(&e));
    }
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
    c.data.intent.data.walk.steps=1;c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
    assert(execute(&c)==ESP_OK);ainekio_p4_body_event_t e=finish(20000);assert(e.completed&&e.sequence==1);
}
static void clips(void)
{
    for(size_t i=0;i<ainekio_v2_clip_count;i++) {
        reset();ainekio_command_t c=command(1,ainekio_v2_clips[i].intent);
        if(c.data.intent.kind==AINEKIO_INTENT_EMOTE)strcpy(c.data.intent.data.asset,ainekio_v2_clips[i].command);
        assert(ainekio_p4_body_supports(&c)&&execute(&c)==ESP_OK);
        ainekio_p4_body_event_t e=finish(70000);assert(e.completed&&e.sequence==1&&e.result==ESP_OK);
        ainekio_v2_frame_t terminal;uint16_t expected[12];
        assert(ainekio_v2_clip_sample(i,ainekio_v2_clips[i].duration_us,&terminal));
        assert(ainekio_p4_frame_pulses(&terminal,expected));assert(!memcmp(expected,last_written,sizeof(expected)));
    }
}
static void rise_from_grounded_postures(void)
{
    const char *names[]={"lay_down","dead"};
    for(unsigned posture=0;posture<2;posture++) {
        reset();
        ainekio_command_t c=command(1,AINEKIO_INTENT_EMOTE);
        strcpy(c.data.intent.data.asset,names[posture]);
        assert(execute(&c)==ESP_OK);
        assert(finish(15000).completed);
        assert(body.motion.kind==MOTION_NONE && body.motion.face_is_clip);
        c=command(2,AINEKIO_INTENT_STAND);
        assert(execute(&c)==ESP_OK && body.motion.reverse_grounded_entry);
        const double recovery=ainekio_v2_clip_playback_seconds(body.motion.recovery_clip,
            body.motion.clip_joint_speed,body.motion.requested_rate);
        const unsigned elapsed_ms=(unsigned)(recovery*500./20.)*20;
        advance(elapsed_ms);
        ainekio_v2_frame_t expected;
        uint64_t source_us;
        assert(ainekio_v2_clip_playback_sample(body.motion.recovery_clip,elapsed_ms/1000.,
            body.motion.clip_joint_speed,body.motion.requested_rate,true,&expected,&source_us));
        for(unsigned i=0;i<12;i++)assert(fabsf(body.pose.position[i]-expected.position[i])<1.F);
        ainekio_p4_body_event_t event=finish(10000);
        assert(event.sequence==2 && event.completed && body.motion.kind==MOTION_NONE);
        ainekio_v2_walk_pose_t stand;
        assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
        for(unsigned i=0;i<12;i++)assert(fabsf(body.pose.position[i]-stand.frame.position[i])<1.F);
        assert(body.balance_hold);
        imu_status.calibration_applied=true;
        imu_status.attitude.available=imu_status.attitude.fresh=true;
        imu_status.attitude.orientation_wxyz[0]=cosf(.02F);
        imu_status.attitude.orientation_wxyz[1]=sinf(.02F);
        advance(100);
        assert(body.balance.sensor_usable && body.balance.correction[0]<0.);
    }
    reset();
    ainekio_command_t c=command(1,AINEKIO_INTENT_EMOTE);
    strcpy(c.data.intent.data.asset,"lay_down");
    assert(execute(&c)==ESP_OK && finish(15000).completed);
    c=command(2,AINEKIO_INTENT_WALK);
    c.data.intent.data.walk.controls=1;
    c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK && !body.motion.reverse_grounded_entry);
    assert(!body.motion.entering && !body.ramping && body.motion.walk.phase==0.);
    advance(20);
    assert(body.motion.walk.phase>0.);
    assert(body.motion.kind==MOTION_WALK && !body.motion.entering && driver.state.armed);
}
static void cancellation_and_faults(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_NEUTRAL);assert(execute(&c)==ESP_OK);
    const uint64_t stale=driver.state.generation;ainekio_pca_disarm(&driver);unsigned before=writes;
    advance(100);assert(writes==before&&!driver.state.armed);
    ainekio_p4_body_event_t e;assert(ainekio_p4_body_event(&e)&&!e.completed&&e.result==ESP_OK);
    assert(ainekio_p4_body_execute(stale,17,&c)==ESP_ERR_INVALID_STATE&&writes==before);
    reset();mapping_failure=true;assert(execute(&c)==ESP_ERR_INVALID_ARG&&writes==0);
    reset();assert(execute(&c)==ESP_OK);mapping_failure=true;advance(600);
    /* Pose entry uses its already validated targets; a running clip maps each frame. */
    reset();c.data.intent.kind=AINEKIO_INTENT_SIT;assert(execute(&c)==ESP_OK);
    while(body.motion.entering)advance(20);
    mapping_failure=true;advance(20);assert(!driver.state.armed);
    assert(ainekio_p4_body_event(&e)&&!e.completed&&e.result==ESP_ERR_INVALID_ARG);
    reset();c.data.intent.kind=AINEKIO_INTENT_NEUTRAL;assert(execute(&c)==ESP_OK);
    clock_us+=40001;output_step(clock_us);assert(driver.state.armed);
    assert(!ainekio_p4_body_event(&e));
    reset();assert(execute(&c)==ESP_OK);driver_failure=true;advance(20);
    assert(!driver.state.armed&&ainekio_p4_body_event(&e)&&e.result==ESP_FAIL);
    reset();enabled=7u<<6;assert(execute(&c)==ESP_OK);e=finish(5000);assert(e.completed);
    for(unsigned i=0;i<12;i++)assert((last_written[i]!=0)==(i>=6&&i<9));
    reset();power_pending=true;assert(execute(&c)==ESP_ERR_INVALID_STATE&&writes==0);
    reset();ainekio_pca_disarm(&driver);stop_body(ESP_OK);system_state=AINEKIO_STATE_DOZING;
    uint16_t asleep_homes[12];assert(ainekio_p4_home_pulses(asleep_homes));
    assert(execute(&c)==ESP_ERR_INVALID_STATE);
    assert(ainekio_p4_body_home(driver.state.generation,asleep_homes)==ESP_ERR_INVALID_STATE);
    assert(ainekio_p4_body_move(driver.state.generation,0,1500)==ESP_ERR_INVALID_STATE);
    assert(writes==0&&!driver.state.armed);
    /* Shutdown still needs to prepare all channels off while admission is closed. */
    power_pending=true;assert(ainekio_p4_body_prepare(driver.state.generation)==ESP_OK);
    system_state=AINEKIO_STATE_IDLE;rest_seconds=180;speaker_busy=false;power_pending=false;
    assert(execute(&c)==ESP_OK);
    assert(ainekio_p4_body_home(driver.state.generation,asleep_homes)==ESP_OK);
    assert(execute(&c)==ESP_OK);
    reset();uint16_t homes[12];assert(ainekio_p4_home_pulses(homes));
    assert(ainekio_p4_body_home(driver.state.generation,homes)==ESP_OK&&!memcmp(last_written,homes,sizeof(homes)));
    assert(ainekio_p4_body_move(driver.state.generation,6,1700)==ESP_OK&&last_written[6]==1700);
    /* Both command paths use the timer's actual representable pulse range. */
    assert(ainekio_p4_body_move(driver.state.generation,6,3000)==ESP_OK&&last_written[6]==3000);
    before=writes;
    assert(ainekio_p4_body_move(driver.state.generation,6,UINT16_MAX)==ESP_ERR_INVALID_ARG);
    assert(writes==before&&last_written[6]==3000&&driver.state.armed);
    homes[11]=UINT16_MAX;
    assert(ainekio_p4_body_home(driver.state.generation,homes)==ESP_ERR_INVALID_ARG);
    assert(writes==before&&last_written[6]==3000&&driver.state.armed);
}
static void stop_motion_phases(void)
{
    for(unsigned stage=0;stage<3;stage++) {
        reset();ainekio_command_t c=command(1,stage==2?AINEKIO_INTENT_WALK:AINEKIO_INTENT_SIT);
        assert(execute(&c)==ESP_OK);
        advance(stage==0?100:1000);
        assert(ainekio_p4_body_status().moving);
        const uint64_t generation=driver.state.generation;
        ainekio_pca_emergency_disable(&driver,AINEKIO_PCA_FAULT_EMERGENCY);
        const unsigned before=writes;advance(100);
        ainekio_p4_body_event_t e;
        assert(writes==before&&!driver.state.armed&&!ainekio_p4_body_status().moving);
        assert(ainekio_p4_body_event(&e)&&e.connection==17&&e.sequence==1&&!e.completed&&e.result==ESP_OK);
        assert(!ainekio_p4_body_event(&e));
        assert(ainekio_p4_body_execute(generation,17,&c)==ESP_ERR_INVALID_STATE&&writes==before);
        c.sequence=2;assert(execute(&c)==ESP_OK&&driver.state.armed);
        assert(body.ramping==(c.data.intent.kind!=AINEKIO_INTENT_WALK));
        assert(ainekio_p4_body_status().sequence==2);
    }
}
static void ordinary_stop_holds_commanded_pose(void)
{
    for(unsigned stage=0;stage<3;stage++) {
        reset();ainekio_command_t c=command(1,stage==2?AINEKIO_INTENT_WALK:AINEKIO_INTENT_SIT);
        assert(execute(&c)==ESP_OK);advance(stage==0?100:1000);
        uint16_t held[12];memcpy(held,last_written,sizeof held);
        const uint64_t generation=driver.state.generation;
        assert(ainekio_p4_body_hold(generation)==ESP_OK);
        assert(driver.state.armed && driver.state.generation==generation);
        assert(!ainekio_p4_body_status().moving);
        ainekio_p4_body_event_t e;
        assert(ainekio_p4_body_event(&e) && e.sequence==1 && !e.completed && e.result==ESP_OK);
        advance(1000);
        assert(!memcmp(held,last_written,sizeof held));
        assert(ainekio_p4_body_hold(generation)==ESP_OK);
        assert(!ainekio_p4_body_event(&e));
        assert(driver.state.armed && !memcmp(held,last_written,sizeof held));
        c.sequence=2;assert(execute(&c)==ESP_OK);
        assert(driver.state.armed && ainekio_p4_body_status().moving);
        ainekio_pca_emergency_disable(&driver,AINEKIO_PCA_FAULT_EMERGENCY);
        advance(20);const unsigned before=writes;
        system_state=AINEKIO_STATE_DOZING;power_pending=true;
        assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
        advance(100);
        assert(!driver.state.armed && writes==before);
    }
}
static void sample_clock_with_work(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
    assert(execute(&c)==ESP_OK);
    /* Walking has no posture or homing preamble. */
    assert(!body.motion.entering&&body.motion.kind==MOTION_WALK);
    /* Charge seven milliseconds to calculation/mapping and three to I2C.
     * The task wakes every five milliseconds, as the production owner does. */
    mapping_delay_us=7000;write_delay_us=3000;
    uint64_t previous=body.motion.walk.last_us;
    unsigned sampled=0;
    while(sampled<8) {
        const unsigned before=writes;
        const uint64_t now=clock_us;
        if(output_step(now)) {
            assert(writes==before+1&&last_mapping_started==now);
            assert(last_mapping_started-previous==20000);
            assert(last_write_started==now+7000&&clock_us==now+10000);
            assert(body.last_frame==clock_us&&body.next_frame==now+20000);
            assert(body.motion.walk.last_us==now);
            previous=now;sampled++;
        } else assert(writes==before);
        vTaskDelay(5);
    }
    /* A late wake samples the actual time once, then resumes a full interval.
     * It must not replay an earlier scheduled pose or emit a catch-up burst. */
    clock_us=body.next_frame+7000;
    const uint64_t late=clock_us;
    unsigned before=writes;
    assert(output_step(clock_us)&&writes==before+1);
    assert(body.motion.walk.last_us==late&&last_mapping_started==late);
    assert(body.next_frame==late+20000);
    before=writes;assert(!output_step(clock_us)&&writes==before);
    clock_us=body.next_frame;assert(output_step(clock_us));

    /* Paused scheduling resumes one current output without an automatic stop
     * or a burst of replayed writes, including gaps beyond the old 40 ms gate. */
    const uint64_t gaps[]={40001,100000,1000000};
    for(unsigned i=0;i<sizeof(gaps)/sizeof(gaps[0]);i++) {
        clock_us=body.motion.walk.last_us+gaps[i];
        before=writes;assert(output_step(clock_us)&&writes==before+1&&driver.state.armed);
        assert(body.motion.kind==MOTION_WALK && !body.motion.walk.failed);
        ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
    }
}
static void timed_out_output_resumes(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
    assert(execute(&c)==ESP_OK);advance(10000);
    const uint64_t generation=driver.state.generation;
    const unsigned before=writes;
    uint16_t held[12];memcpy(held,last_written,sizeof held);
    driver_timeout=true;advance(1000);
    assert(body.active && driver.state.armed && driver.state.generation==generation);
    assert(writes==before && !memcmp(held,last_written,sizeof held));
    ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
    driver_timeout=false;advance(20);
    assert(writes==before+1 && body.motion.kind==MOTION_WALK);
    driver_timeout=true;
    ainekio_pca_emergency_disable(&driver,AINEKIO_PCA_FAULT_EMERGENCY);advance(20);
    assert(!body.active && !driver.state.armed && writes==before+1);
    assert(ainekio_p4_body_event(&e) && !e.completed && e.sequence==1);

    /* A timed-out terminal frame must not report successful completion. */
    reset();c=command(2,AINEKIO_INTENT_NEUTRAL);assert(execute(&c)==ESP_OK);
    driver_timeout=true;advance(10000);
    assert(body.active && driver.state.armed && !ainekio_p4_body_event(&e));
    driver_timeout=false;advance(20);
    assert(ainekio_p4_body_event(&e) && e.completed && e.sequence==2 && e.result==ESP_OK);
    /* A missing admission response reports failure without disabling the
     * already active output. Existing request expiry is a separate contract. */
    reset();defer_requests=true;c=command(3,AINEKIO_INTENT_WALK);
    assert(execute(&c)==ESP_ERR_TIMEOUT && driver.state.armed && body.active);
    body_request_t pending;assert(xQueueReceive(requests,&pending,0));
    clock_us+=200000;
    assert(process_request(&pending,clock_us)==ESP_ERR_INVALID_STATE && driver.state.armed);
    puts("Output timeouts retain PWM, preserve explicit Stop and complete only after a successful write.");
}

static void rejected_clip_preserves_motion(void)
{
    reset();size_t rest,point;ainekio_v2_frame_t f;uint16_t p[12];
    assert(ainekio_v2_clip_find("rest",&rest)&&ainekio_v2_clip_find("point",&point));
    assert(ainekio_v2_clip_sample(rest,ainekio_v2_clips[rest].duration_us,&f));
    assert(ainekio_p4_joint_defaults(mapped_joints));
    /* Use an unrestricted shoulder to exercise timer representability;
     * carrier/crank targets now use the owner-confirmed mechanical range. */
    mapped_joints[6].home_us=19500;mapped_joints[6].us_per_degree=80;
    for(unsigned i=0;i<12;i++)body.pulses[i]=last_written[i]=mapped_joints[i].home_us;
    retain_manual_reference();
    /* This regression specifically catches validation of only the first pose. */
    assert(ainekio_v2_clip_sample(point,0,&f)&&ainekio_p4_frame_pulses(&f,p));
    ainekio_command_t c=command(1,AINEKIO_INTENT_NEUTRAL);
    assert(execute(&c)==ESP_OK);advance(100);
    const unsigned before=writes;uint16_t held[12];memcpy(held,last_written,sizeof(held));
    c=command(2,AINEKIO_INTENT_EMOTE);strcpy(c.data.intent.data.asset,"point");
    assert(execute(&c)==ESP_ERR_INVALID_ARG&&writes==before);
    assert(!memcmp(held,last_written,sizeof(held))&&driver.state.armed);
    assert(ainekio_p4_body_status().sequence==1&&ainekio_p4_body_status().moving);
    ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
    e=finish(5000);assert(e.sequence==1&&e.completed&&e.result==ESP_OK);
    assert(!ainekio_v2_clip_bounds(ainekio_v2_clip_count,&f,&f));
    assert(!ainekio_v2_clip_bounds(point,NULL,&f));
    assert(!ainekio_v2_clip_bounds(point,&f,NULL));
    assert(!ainekio_v2_clip_bounds(point,&f,&f));
}
static void retired_turns_preserve_active_gait(void)
{
    reset();ainekio_command_t c=command(70,AINEKIO_INTENT_WALK);
    c.data.intent.data.walk.steps=0;
    assert(execute(&c)==ESP_OK);advance(6000);
    const char *names[]={"turn_left_15","turn_right_15","turn_left_45","turn_right_45",
        "turn_left_90","turn_right_90","turn_left_180","turn_right_180"};
    for(unsigned i=0;i<sizeof(names)/sizeof(names[0]);++i) {
        const unsigned before=writes;
        const ainekio_v2_frame_t pose=body.pose;
        c=command(71+i,AINEKIO_INTENT_EMOTE);strcpy(c.data.intent.data.asset,names[i]);
        assert(execute(&c)==ESP_ERR_NOT_SUPPORTED);
        assert(writes==before&&driver.state.armed&&body.pose_valid);
        assert(!memcmp(&pose,&body.pose,sizeof(pose)));
        assert(ainekio_p4_body_status().sequence==70&&ainekio_p4_body_status().moving);
        ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
        advance(20);assert(writes>before);
    }
}
static void integrated_catalog(void)
{
    unsigned completed=0,rejected=0;
    for(size_t clip=0;clip<ainekio_v2_clip_count;clip++) {
        reset();
        size_t rest;ainekio_v2_frame_t rest_frame;
        assert(ainekio_v2_clip_find("rest",&rest));
        assert(ainekio_v2_clip_sample(rest,ainekio_v2_clips[rest].duration_us,&rest_frame));
        assert(ainekio_p4_joint_defaults(mapped_joints));
        uint16_t homes[12];assert(ainekio_p4_home_pulses(homes));
        assert(ainekio_p4_body_home(driver.state.generation,homes)==ESP_OK);
        unsigned before=writes;
        ainekio_v2_frame_t minimum,maximum;
        assert(ainekio_v2_clip_bounds(clip,&minimum,&maximum));
        uint16_t low[12],high[12];
        const bool reachable=ainekio_p4_joint_map_frame(mapped_joints,&minimum,low)&&
            ainekio_p4_joint_map_frame(mapped_joints,&maximum,high);
        for(uint64_t t=0;t<=ainekio_v2_clips[clip].duration_us;t+=20000) {
            ainekio_v2_frame_t f;uint16_t p[12];
            assert(ainekio_v2_clip_sample(clip,t,&f));
            for(unsigned j=0;j<12;j++)assert(f.position[j]>=minimum.position[j]-.01f&&
                f.position[j]<=maximum.position[j]+.01f);
            if(reachable)assert(ainekio_p4_joint_map_frame(mapped_joints,&f,p));
        }
        ainekio_command_t c=command(1,ainekio_v2_clips[clip].intent);
        if(c.data.intent.kind==AINEKIO_INTENT_EMOTE)strcpy(c.data.intent.data.asset,ainekio_v2_clips[clip].command);
        int result=execute(&c);
        if(!reachable) {
            assert(result==ESP_ERR_INVALID_ARG&&writes==before&&driver.state.armed);
            assert(!ainekio_p4_body_status().moving);rejected++;continue;
        }
        assert(result==ESP_OK);
        ainekio_p4_body_event_t e=finish(70000);
        assert(e.completed&&e.result==ESP_OK);completed++;
    }
    assert(completed+rejected==ainekio_v2_clip_count && completed>0);
    printf("Current center-indexed default mapper: %u clips completed, %u rejected before PWM at timer capacity.\n",completed,rejected);
}
static void calibration_normal_handoff(void)
{
    reset();assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_pca_disarm(&driver);output_step(clock_us);
    assert(ainekio_p4_body_prepare(driver.state.generation)==ESP_OK);
    assert(!driver.state.armed);
    uint16_t homes[12];assert(ainekio_p4_home_pulses(homes));
    assert(ainekio_p4_body_home(driver.state.generation,homes)==ESP_OK);
    unsigned before=writes;uint64_t generation=driver.state.generation;
    assert(ainekio_p4_body_hold(generation)==ESP_OK);
    assert(driver.state.armed && writes==before && !memcmp(last_written,homes,sizeof homes));
    ainekio_command_t stand=command(73,AINEKIO_INTENT_STAND);
    assert(execute(&stand)==ESP_OK);assert(finish(10000).completed);
    ainekio_pca_disarm(&driver);output_step(clock_us);before=writes;
    assert(ainekio_p4_body_hold(generation)==ESP_ERR_INVALID_STATE);
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    assert(execute(&stand)==ESP_OK && writes==before+1 && driver.state.armed);
    /* Re-arming Stand folds the legs, positions shoulders, then rises. */
    assert(finish(12000).completed);
}

static void motion_from_saved_home(void)
{
    reset();assert(ainekio_p4_joint_defaults(mapped_joints));
    for(unsigned i=0;i<12;i++)mapped_joints[i].home_us=1500;
    mapped_joints[1].home_us=1270; mapped_joints[7].home_us=1230;
    ainekio_p4_joint_config_t saved[12];memcpy(saved,mapped_joints,sizeof(saved));
    uint16_t homes[12];assert(ainekio_p4_home_pulses(homes));
    ainekio_pca_disarm(&driver);output_step(clock_us);
    ainekio_command_t walk=command(80,AINEKIO_INTENT_WALK);
    assert(execute(&walk)==ESP_OK && !body.ramping && !body.motion.entering);
    assert(!body.motion.contact_entry && !body.motion.reverse_grounded_entry);
    uint16_t first_gait[12];assert(ainekio_p4_frame_pulses(&body.motion.walk.pose.frame,first_gait));
    assert(!memcmp(first_gait,last_written,sizeof first_gait));
    assert(memcmp(homes,last_written,sizeof homes));
    assert(!memcmp(saved,mapped_joints,sizeof saved));
    advance(20);
    assert(body.motion.kind==MOTION_WALK && body.motion.walk.phase>0.);
    ainekio_p4_body_event_t event;assert(!ainekio_p4_body_event(&event));

    /* Stop still cancels walking immediately after admission or while active. */
    for(unsigned delay=0;delay<=2000;delay+=1000) {
        reset();ainekio_pca_disarm(&driver);output_step(clock_us);
        assert(execute(&walk)==ESP_OK);advance(delay);
        uint64_t generation=driver.state.generation;
        ainekio_pca_emergency_disable(&driver,AINEKIO_PCA_FAULT_EMERGENCY);
        unsigned before=writes;advance(3000);
        assert(writes==before && !driver.state.armed && !body.ramping);
        assert(ainekio_p4_body_event(&event) && !event.completed && event.sequence==80);
        assert(ainekio_p4_body_execute(generation,17,&walk)==ESP_ERR_INVALID_STATE);
    }

    /* A single manually commanded joint must not strand normal motion. */
    reset();assert(ainekio_p4_joint_defaults(mapped_joints));enabled=7u<<6;
    ainekio_pca_disarm(&driver);output_step(clock_us);
    assert(ainekio_p4_body_move(driver.state.generation,6,mapped_joints[6].home_us)==ESP_OK);
    assert(execute(&walk)==ESP_OK);advance(400);
    assert(!body.ramping);
    for(unsigned i=0;i<12;i++)assert((last_written[i]!=0)==(i>=6 && i<9));

    /* Invalid model references are distinguished from BUSY before any PWM. */
    reset();assert(ainekio_p4_joint_defaults(mapped_joints));
    mapped_joints[4].home_cd=12000; mapped_joints[5].home_cd=0;
    /* Keep the requested target electrically representable so this reaches
     * reference geometry validation rather than failing pulse mapping first. */
    mapped_joints[4].home_us=2000;
    ainekio_pca_disarm(&driver);output_step(clock_us);
    unsigned before=writes;
    ainekio_command_t stand=command(81,AINEKIO_INTENT_STAND);
    /* An invalid saved Home is not the startup reference anymore. */
    assert(execute(&stand)==ESP_OK && writes==before+1 && body.motion.startup_entry);
    assert(finish(4000).completed);
}

static void supervised_faults_are_failures(void)
{
    for(unsigned fault=AINEKIO_PCA_FAULT_EMERGENCY;fault<=AINEKIO_PCA_FAULT_PROGRESS;fault++) {
        reset();ainekio_command_t c=command(90,AINEKIO_INTENT_WALK);
        assert(execute(&c)==ESP_OK);
        ainekio_pca_emergency_disable(&driver,(ainekio_pca_fault_t)fault);
        unsigned before=writes;advance(100);
        ainekio_p4_body_event_t e;assert(ainekio_p4_body_event(&e));
        assert(!e.completed && e.sequence==90 && writes==before && !driver.state.armed);
        assert(e.result==(fault==AINEKIO_PCA_FAULT_EMERGENCY?ESP_OK:
            fault==AINEKIO_PCA_FAULT_IO?ESP_FAIL:ESP_ERR_TIMEOUT));
    }
}

/* Exercise entry through the production body owner, including a retained
 * Crawl endpoint outside the former provisional angle envelope. */
static void crawl_finish_handoff(void)
{
    for(unsigned family=0;family<2;family++)for(unsigned target=0;target<2;target++)for(unsigned dir=0;dir<(family?6:4);dir++) {
        reset();assert(ainekio_p4_joint_defaults(mapped_joints));
        for(unsigned i=0;i<12;i++)mapped_joints[i].home_us=1500;
        mapped_joints[1].home_us=1270;mapped_joints[7].home_us=1230;
        ainekio_p4_joint_config_t saved[12];memcpy(saved,mapped_joints,sizeof(saved));
        ainekio_pca_disarm(&driver);output_step(clock_us);
        ainekio_command_t crawl=command(200,AINEKIO_INTENT_WALK);
        crawl.data.intent.data.walk.gait=family?AINEKIO_GAIT_CRAB:AINEKIO_GAIT_CRAWL;
        crawl.data.intent.data.walk.direction=(ainekio_walk_direction_t)dir;
        crawl.data.intent.data.walk.controls=1;crawl.data.intent.data.walk.speed_percent=100;
        assert(execute(&crawl)==ESP_OK);
        for(unsigned i=0;i<480;i++) {clock_us+=(20000+(i%4)*3000);output_step(clock_us);}
        assert(body.motion.kind==MOTION_WALK&&!body.motion.entering);
        crawl.sequence=201;crawl.data.intent.data.walk.update_sequence=200;crawl.data.intent.data.walk.speed_percent=0;
        assert(execute(&crawl)==ESP_OK);
        ainekio_p4_body_event_t e=finish(20000);assert(e.completed&&e.sequence==200&&e.result==ESP_OK);
        ainekio_v2_frame_t held=body.pose;assert(body.pose_valid&&ainekio_v2_limits_frame(&held));
        ainekio_command_t next=command(202,target?AINEKIO_INTENT_STAND:AINEKIO_INTENT_WALK);
        if(!target){next.data.intent.data.walk.steps=2;next.data.intent.data.walk.controls=1;next.data.intent.data.walk.speed_percent=100;}
        assert(execute(&next)==ESP_OK&&!body.ramping);
        assert(!memcmp(held.position,body.motion.entry_from.position,sizeof(held.position)));
        e=finish(25000);assert(e.completed&&e.sequence==202&&e.result==ESP_OK);
        assert(!memcmp(saved,mapped_joints,sizeof(saved)));
    }
}

static void commanded_pose_survives_pwm_rounding(void)
{
    reset();assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_v2_frame_t frame={.geometry_id=ainekio_v2_walk_geometry_id};
    for(unsigned i=0;i<12;i++)frame.position[i]=mapped_joints[i].home_cd;
    frame.position[0]=-5500;
    assert(ainekio_p4_joint_map_frame(mapped_joints,&frame,body.pulses));
    memcpy(last_written,body.pulses,sizeof(last_written));
    ainekio_p4_calibration_t calibration=ainekio_p4_calibration();retain_pose(&frame,&calibration);
    ainekio_command_t c=command(101,AINEKIO_INTENT_NEUTRAL);
    assert(execute(&c)==ESP_OK);
    assert(body.motion.entry_from.position[0]==-5500); /* exact requested angle */
    advance(20);assert(body.pose_valid);
    ainekio_v2_frame_t before=body.pose;
    driver_failure=true;advance(20);
    assert(!body.pose_valid && !driver.state.armed);
    assert(!memcmp(before.position,body.pose.position,sizeof(before.position)));
    /* A changed saved mapping cannot reuse an old model-coordinate reference. */
    reset();mapped_joints[0].home_cd=1500;
    c=command(102,AINEKIO_INTENT_NEUTRAL);assert(execute(&c)==ESP_OK);
    assert(body.motion.entry_from.position[0]==0); /* Neutral, never calibration Home. */
}

static void entry_endpoint_precision(void)
{
    /* Neutral uses this scalar entry ramp. Stand now uses the separately
     * tested contact planner and cannot be sampled as a two-second ramp. */
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_NEUTRAL);
    assert(execute(&c)==ESP_OK && body.motion.entering);
    assert(!body.motion.contact_entry);
    body.motion.entry_duration=2000000;
    bool complete;ainekio_v2_frame_t frame;
    /* Previously u=0.999633491 produced progress=1.0000000138. */
    assert(motion_frame(body.motion.entry_start+1999267,&complete,&frame)==ESP_OK);
    assert(!complete && ainekio_v2_limits_frame(&frame));
    assert(motion_frame(body.motion.entry_start+2000000,&complete,&frame)==ESP_OK);
    assert(complete && !memcmp(frame.position,body.motion.entry_to.position,sizeof frame.position));
}

static void motion_speed(void)
{
    ainekio_control_message_t decoded;
    const char *wire="{\"t\":\"intent\",\"name\":\"emote\",\"asset\":\"wave\",\"playback_rate\":2,\"seq\":1}";
    assert(ainekio_control_decode_for_body(wire,strlen(wire),&decoded)==AINEKIO_DECODE_OK);
    assert(decoded.command.data.intent.playback_rate==2.F);
    assert(ainekio_control_decode(wire,strlen(wire),&decoded)==AINEKIO_DECODE_VALUE);
    wire="{\"t\":\"motion_speed\",\"op\":\"save\",\"rate\":1.35,\"seq\":2}";
    assert(ainekio_control_decode_for_body(wire,strlen(wire),&decoded)==AINEKIO_DECODE_OK);
    assert(decoded.command.data.motion_speed.save && decoded.command.data.motion_speed.rate==1.35F);
    assert(ainekio_control_decode(wire,strlen(wire),&decoded)==AINEKIO_DECODE_VALUE);
    wire="{\"t\":\"motion_speed\",\"op\":\"save\",\"joint_speed_limit_deg_s\":2000,\"seq\":3}";
    assert(ainekio_control_decode_for_body(wire,strlen(wire),&decoded)==AINEKIO_DECODE_OK);
    assert(decoded.command.data.motion_speed.has_joint_speed_limit && decoded.command.data.motion_speed.joint_speed_limit_deg_s==2000.F);
    const char *invalid[]={
        "{\"t\":\"motion_speed\",\"op\":\"save\",\"rate\":2,\"joint_speed_limit_deg_s\":2000,\"seq\":1}",
        "{\"t\":\"motion_speed\",\"op\":\"get\",\"joint_speed_limit_deg_s\":2000,\"seq\":1}",
        "{\"t\":\"motion_speed\",\"op\":\"save\",\"joint_speed_limit_deg_s\":0,\"seq\":1}",
        "{\"t\":\"intent\",\"name\":\"neutral\",\"playback_rate\":2,\"seq\":1}",
        "{\"t\":\"intent\",\"name\":\"sit\",\"playback_rate\":0,\"seq\":1}",
        "{\"t\":\"intent\",\"name\":\"sit\",\"playback_rate\":-1,\"seq\":1}",
        "{\"t\":\"motion_speed\",\"op\":\"get\",\"rate\":2,\"seq\":1}",
        "{\"t\":\"motion_speed\",\"op\":\"save\",\"rate\":true,\"seq\":1}",
        "{\"t\":\"motion_speed\",\"op\":\"save\",\"rate\":-1,\"seq\":1}"};
    for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++)
        assert(ainekio_control_decode_for_body(invalid[i],strlen(invalid[i]),&decoded)!=AINEKIO_DECODE_OK);
    const float rates[]={1.F,.25F,2.F,3.F,4.F,6.F,8.F,12.F};
    for(size_t clip=0;clip<ainekio_v2_clip_count;clip++) {
        uint64_t entry_at_1x=0;
        for(unsigned r=0;r<sizeof rates/sizeof rates[0];r++) {
            reset();ainekio_command_t c=command(1,ainekio_v2_clips[clip].intent);
            if(c.data.intent.kind==AINEKIO_INTENT_EMOTE)strcpy(c.data.intent.data.asset,ainekio_v2_clips[clip].command);
            c.data.intent.playback_rate=rates[r];
            assert(execute(&c)==ESP_OK);
            assert(body.motion.playback_rate==rates[r]);
            const double duration=ainekio_v2_clip_playback_seconds(clip,body.motion.clip_joint_speed,rates[r]);
            if(!r)entry_at_1x=body.motion.entry_duration;
            else assert(body.motion.entry_duration==entry_at_1x);
            const uint64_t entry_started=clock_us;
            while(body.motion.entering)advance(20);
            const uint64_t entry_expected=(uint64_t)ceil(entry_at_1x/(double)body.motion.entry_rate);
            assert(clock_us-entry_started>=entry_expected && clock_us-entry_started-entry_expected<20000);
            const uint64_t started=clock_us;
            assert(body.motion.clip_joint_speed==ainekio_v2_gait_joint_speed_limit()*.5);
            /* Output is paced by acknowledged targets, never by wall time. */
            unsigned frames=0;
            while(body.motion.kind!=MOTION_NONE) {
                assert(++frames<10000);
                advance(20);
                ainekio_v2_frame_t expected_frame;uint16_t expected_pulses[12];
                assert(ainekio_v2_clip_sample(clip,body.motion.face_elapsed_us,&expected_frame));
                assert(ainekio_p4_joint_map_frame(mapped_joints,&expected_frame,expected_pulses));
                for(unsigned j=0;j<12;j++) {
                    assert(abs(expected_pulses[j]-last_written[j])<=1);
                    assert(fabs(expected_frame.position[j]-body.pose.position[j])<.2);
                }
                assert(!ainekio_p4_body_status().speed_limited);
            }
            ainekio_p4_body_event_t e=finish(1000);
            assert(e.completed && e.sequence==1 && e.result==ESP_OK);
            const uint64_t expected=(uint64_t)ceil(duration*1e6);
            assert(clock_us-started>=expected);
        }
    }
    /* Finite-clip entry uses degrees/s independently of pulse mapping. Stand's
     * contact-planned rate is checked per frame in imu_posture_feedback. */
    const float entry_limits[]={100.F,2000.F};
    float entry_rates[2];
    for(unsigned k=0;k<2;k++) {
        reset();assert(ainekio_v2_joint_speed_set(entry_limits[k]));
        ainekio_command_t sit=command(1,AINEKIO_INTENT_SIT);
        sit.data.intent.playback_rate=8.F;
        assert(execute(&sit)==ESP_OK && !body.motion.contact_entry);
        double derivatives[12];ainekio_v2_frame_t low,high;
        assert(ainekio_v2_transition_bounds(&body.motion.entry_from,&body.motion.entry_to,&low,&high,derivatives));
        for(unsigned j=0;j<12;j++)
            assert(derivatives[j]/100.*1.875e6/body.motion.entry_duration*body.motion.entry_rate<=entry_limits[k]+.001);
        entry_rates[k]=body.motion.entry_rate;
        assert(ainekio_p4_body_status().speed_limited==(body.motion.entry_rate<8.F));
    }
    assert(entry_rates[1]>entry_rates[0]);
    assert(ainekio_v2_joint_speed_set(ainekio_v2_joint_speed_default()));
    reset();saved_motion_rate=2.F;
    ainekio_command_t c=command(1,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
    assert(body.motion.playback_rate==1.F && !ainekio_p4_body_status().speed_limited);
    saved_motion_rate=3.F;assert(body.motion.playback_rate==1.F);
    c=command(2,AINEKIO_INTENT_WALK);c.data.intent.data.walk.steps=1;
    assert(execute(&c)==ESP_OK && body.motion.playback_rate==1.F);
    puts("Named motion speed: half-speed travel, unchanged holds at all legacy rates, preserved entry easing, feedback-paced faces and completion passed.");
}

static void face_playback_clock(void)
{
    reset();
    ainekio_command_t c=command(83,AINEKIO_INTENT_EMOTE);
    strcpy(c.data.intent.data.asset,"wave");c.data.intent.playback_rate=.5F;
    assert(execute(&c)==ESP_OK);
    assert(ainekio_p4_body_status().face_entering);
    assert(ainekio_p4_body_status().face_elapsed_us==0);
    while(body.motion.entering||body.ramping)advance(20);
    advance(200);
    ainekio_p4_body_status_t status=ainekio_p4_body_status();
    assert(!strcmp(status.face_command,"wave")&&status.face_is_clip);
    ainekio_v2_frame_t frame;uint64_t source_us;
    source_us=body.motion.face_elapsed_us;
    assert(ainekio_v2_clip_sample(body.motion.clip,source_us,&frame));
    assert(status.face_elapsed_us==source_us && source_us>0);
    assert(!strcmp(status.execution.command,"wave") && !strcmp(status.execution.activity,"clip"));
    assert(status.execution.sequence==83 && status.execution.sampled_us<=clock_us);
    float expected[3];assert(ainekio_v2_clip_expected_up(status.face_clip,status.face_elapsed_us,expected));
    for(unsigned j=0;j<3;j++)assert(fabsf(status.execution.expected_up[j]-expected[j])<1e-6F);
    uint32_t revision=status.face_revision;
    finish_motion(false,ESP_OK);
    ainekio_p4_body_status_t status_after=ainekio_p4_body_status();
    assert(!status_after.face_command&&status_after.face_revision!=revision);
    assert(!strcmp(status_after.execution.phase,"hold") && status_after.execution.expected_up_known);
    assert(!memcmp(status.execution.expected_up,status_after.execution.expected_up,sizeof expected));
    puts("Presentation follows the body sample clock and cancellation without display I/O in the output task.");
}

static void notification_execution_context(void)
{
    reset();leveling_enabled=false;
    ainekio_command_t c=command(2001,AINEKIO_INTENT_WALK);
    c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK);
    assert(!ainekio_p4_body_status().execution.command); /* Admission is not execution. */
    driver_timeout=true;advance(20);
    assert(!ainekio_p4_body_status().execution.command); /* Failed writes explain no sample. */
    driver_timeout=false;advance(20);
    ainekio_p4_execution_t e=ainekio_p4_body_status().execution;
    assert(!strcmp(e.activity,"locomotion") && e.sequence==2001);
    assert(e.started_us==e.sampled_us && e.expected_up_known);
    assert(!ainekio_p4_body_execution_at(e.sampled_us-1).command);
    assert(ainekio_p4_body_execution_at(e.sampled_us).sequence==2001);
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    e=ainekio_p4_body_status().execution;
    assert(!strcmp(e.phase,"hold") && e.expected_up_known);
    ainekio_p4_body_event_t cancelled;
    assert(ainekio_p4_body_event(&cancelled) && !cancelled.completed && cancelled.sequence==2001);
    c=command(2002,AINEKIO_INTENT_EMOTE);strcpy(c.data.intent.data.asset,"upright");
    assert(execute(&c)==ESP_OK);
    assert(ainekio_p4_body_status().execution.sequence==2001);
    const uint64_t before_first_output=clock_us;
    advance(20);
    assert(ainekio_p4_body_execution_at(before_first_output).sequence==2001);
    assert(ainekio_p4_body_execution_at(clock_us).sequence==2002);
    assert(finish(120000).completed);
    e=ainekio_p4_body_status().execution;
    assert(!strcmp(e.command,"upright") && !strcmp(e.phase,"hold") && e.sequence==2002);
    assert(fabs(e.expected_up[2]-.5)<.001); /* Authored 60-degree upright hold. */
    assert(e.expected_up_known);
    advance(1000);
    assert(!memcmp(e.expected_up,ainekio_p4_body_status().execution.expected_up,sizeof(e.expected_up)));
    ainekio_pca_emergency_disable(&driver,AINEKIO_PCA_FAULT_EMERGENCY);advance(20);
    assert(!ainekio_p4_body_status().execution.expected_up_known);
}

static void listening_feedback(void)
{
    reset();assert(ainekio_v2_joint_speed_set(1000));
    ainekio_command_t c=command(1,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);assert(finish(10000).completed);
    const ainekio_v2_frame_t original=body.pose;
    uint16_t pulses[12];memcpy(pulses,last_written,sizeof pulses);
    const uint32_t face_revision=body.motion.face_revision;
    ainekio_p4_body_listen(true);advance(400);
    assert(body.listen.active && body.listen.engaged);
    for(unsigned i=0;i<12;i++) {
        assert(body.pose.position[i]==original.position[i]+((i==6||i==9)?600.F:0.F));
        if(i!=6&&i!=9)assert(last_written[i]==pulses[i]);
    }
    assert(body.motion.face_revision==face_revision && !body.motion.kind);
    advance(400);assert(body.listen.active); /* Hold for the utterance. */
    ainekio_p4_body_listen(false);advance(400);
    assert(!body.listen.active && !memcmp(pulses,last_written,sizeof pulses));
    assert(!memcmp(original.position,body.pose.position,sizeof original.position));
    ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
    /* Closing early reverses smoothly from the last written pose. */
    ainekio_p4_body_listen(true);advance(100);
    uint16_t middle[12];memcpy(middle,last_written,sizeof middle);
    ainekio_p4_body_listen(false);advance(20);
    assert(!memcmp(middle,last_written,sizeof middle));
    advance(400);assert(!memcmp(pulses,last_written,sizeof pulses));
    /* The configured joint limit, including low values, controls both ramps. */
    assert(ainekio_v2_joint_speed_set(5));
    ainekio_p4_body_listen(true);advance(20);
    assert(body.listen.duration>=2250000);
    float previous=body.pose.position[6];
    for(unsigned n=0;n<120;n++) {
        advance(20);assert(fabsf(body.pose.position[6]-previous)<=10.01F);previous=body.pose.position[6];
    }
    assert(body.pose.position[6]==original.position[6]+600.F);
    ainekio_p4_body_listen(false);advance(2400);
    assert(!memcmp(pulses,last_written,sizeof pulses));
    assert(ainekio_v2_joint_speed_set(1000));
    /* A command takes over from the actual gesture pose, without a snap. */
    ainekio_p4_body_listen(true);advance(400);
    ainekio_v2_frame_t cue=body.pose;
    c.sequence=2;assert(execute(&c)==ESP_OK);
    assert(!body.listen.active && !memcmp(cue.position,body.motion.entry_from.position,sizeof cue.position));
    ainekio_p4_body_listen(false);assert(finish(10000).completed);
    /* Wake feedback never interrupts a continuous gait or acquires its seq. */
    c=command(3,AINEKIO_INTENT_WALK);c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK);advance(1500);
    ainekio_p4_body_listen(true);advance(1000);
    assert(body.motion.kind==MOTION_WALK && body.motion.sequence==3 && !body.listen.active);
    ainekio_pca_disarm(&driver);advance(20);
    const unsigned stopped_writes=writes;advance(400);
    assert(!body.active && !body.listen.active && writes==stopped_writes && !listen_requested);
    /* Current calibration owns manual targets and cancels gesture restoration. */
    reset();ainekio_p4_body_listen(true);advance(400);
    assert(ainekio_p4_body_move(driver.state.generation,6,1700)==ESP_OK);
    ainekio_p4_body_listen(false);advance(400);assert(last_written[6]==1700);
    /* Sample every retained gesture pose with the actual calibrated mapper. */
    for(size_t clip=0;clip<ainekio_v2_clip_count;clip++) {
        reset();assert(ainekio_p4_joint_defaults(mapped_joints));
        ainekio_v2_frame_t frame;assert(ainekio_v2_clip_sample(clip,ainekio_v2_clips[clip].duration_us,&frame));
        assert(ainekio_p4_frame_pulses(&frame,body.pulses));
        ainekio_p4_calibration_t calibration=ainekio_p4_calibration();retain_pose(&frame,&calibration);
        memcpy(pulses,body.pulses,sizeof pulses);
        ainekio_p4_body_listen(true);advance(400);
        assert(body.active && body.listen.active && !driver.state.fault);
        for(unsigned i=0;i<12;i++)assert(!last_written[i] || (last_written[i]>=400 && last_written[i]<=2900));
        ainekio_p4_body_listen(false);advance(400);
        assert(!memcmp(pulses,last_written,sizeof pulses));
    }
    puts("Listening cue: exact restoration, early close, saved speed limit, motion/calibration priority, Stop and all retained clip poses pass.");
}

static void imu_posture_feedback(float joint_speed,float motion_rate)
{
    reset();assert(ainekio_v2_joint_speed_set(joint_speed));
    saved_motion_rate=motion_rate;
    const unsigned homes[12]={1600,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
    const bool inverted[12]={false,true,true,true,false,false,true,true,true,false,false,false};
    for(unsigned i=0;i<12;i++) {
        mapped_joints[i]=(ainekio_p4_joint_config_t){.channel=(int8_t)i,.home_us=homes[i],
            .invert=inverted[i],.home_cd=i%3==0?0:i%3==1?117:-4041,.us_per_degree=11.111111F};
        body.pulses[i]=last_written[i]=(uint16_t)homes[i];
    }
    retain_manual_reference();publish(body.pulses);
    imu_status.calibration_applied=true;
    imu_status.attitude.available=imu_status.attitude.fresh=true;
    imu_status.attitude.orientation_wxyz[0]=cosf(.02F);
    imu_status.attitude.orientation_wxyz[1]=sinf(.02F);
    ainekio_command_t c=command(1,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK && body.motion.contact_entry);
    assert(fabs(body.motion.posture.start.euler[0]-.04)<1e-6);
    uint16_t previous_pulses[12];memcpy(previous_pulses,last_written,sizeof(last_written));
    const uint64_t stand_started=clock_us;
    while(body.motion.entering) {
        advance(20);
        if(!body.active || driver.state.fault) {
            fprintf(stderr,"Stand feedback failed: limit=%g rate=%g authored_s=%.6f fault=%u\n",
                joint_speed,motion_rate,body.motion.posture_progress,driver.state.fault);

        }
        assert(body.active && !driver.state.fault);
        for(unsigned j=0;j<12;j++) {
            assert(last_written[j]>=300 && last_written[j]<=3000);
            assert(isfinite(body.pose.position[j]));
        }
    }
    assert(clock_us-stand_started<1500000);
    ainekio_p4_body_event_t event;assert(ainekio_p4_body_event(&event) && event.completed && event.sequence==1);
    assert(body.balance_hold && body.balance.sensor_usable && body.balance.correction[0]<0.);
    advance(1000);
    assert(ainekio_p4_body_status().balance_active && body.balance.measured[0]>.039);
    assert(memcmp(previous_pulses,last_written,sizeof(last_written)));
    const double correction=fabs(body.balance.correction[0]);
    imu_status.attitude.fresh=false;advance(20);
    assert(body.balance_hold && body.active && fabs(body.balance.correction[0])<correction);
    assert(!ainekio_p4_body_status().balance_active);
    /* Direct active correction can reach farther before sensor loss. The
     * existing speed-limited fade must decrease monotonically from that pose. */
    for(unsigned n=0;n<500 && fabs(body.balance.correction[0])>=1e-7;n++) {
        const double before=fabs(body.balance.correction[0]);advance(20);
        assert(fabs(body.balance.correction[0])<=before+1e-10);
    }
    assert(fabs(body.balance.correction[0])<1e-7);
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    assert(!ainekio_p4_body_status().balance_active);
    memcpy(previous_pulses,last_written,sizeof previous_pulses);
    imu_status.attitude.fresh=true;
    imu_status.attitude.orientation_wxyz[0]=cosf(.04F);
    imu_status.attitude.orientation_wxyz[1]=sinf(.04F);
    advance(1000);
    assert(!body.balance_hold && !ainekio_p4_body_status().balance_active);
    assert(driver.state.armed && !memcmp(previous_pulses,last_written,sizeof previous_pulses));
    c=command(2,AINEKIO_INTENT_WALK);c.data.intent.data.walk.controls=1;
    c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK);
    while(body.motion.entering){advance(20);assert(body.active);}
    imu_status.attitude.fresh=true;advance(1000);
    assert(body.motion.kind==MOTION_WALK && body.balance.sensor_usable);
    double phase=body.motion.walk.phase;
    leveling_enabled=false;advance(1000);
    assert(body.motion.kind==MOTION_WALK && body.motion.walk.phase>phase && body.active);
    assert(driver.state.armed && !ainekio_p4_body_status().balance_active);
    leveling_enabled=true;advance(20);
    assert(ainekio_p4_body_status().balance_active);
    phase=body.motion.walk.phase;
    imu_status.attitude.fresh=false;advance(1000);
    assert(body.motion.kind==MOTION_WALK && body.motion.walk.phase>phase && body.active);
    ainekio_pca_disarm(&driver);advance(20);
    assert(!body.balance_hold && !body.active && !ainekio_p4_body_status().balance_active);
    puts("Production IMU feedback: measured starting tilt, contact entry, mapped pulses, standing hold, stale fade, continued walking and disarm passed.");
}

static void stand_full_rate_without_leveling(void)
{
    unsigned durations[2]={0};uint16_t reference[100][12];
    for(unsigned test=0;test<2;test++) {
        reset();leveling_enabled=false;saved_motion_rate=test?12.F:.05F;
        assert(ainekio_v2_joint_speed_set(test?2000:20));
        imu_status.calibration_applied=true;
        imu_status.attitude.available=imu_status.attitude.fresh=true;
        imu_status.attitude.orientation_wxyz[0]=cosf(.125F);
        imu_status.attitude.orientation_wxyz[2]=-sinf(.125F);
        ainekio_command_t c=command(180,AINEKIO_INTENT_STAND);
        assert(execute(&c)==ESP_OK && body.motion.contact_entry);
        assert(body.motion.posture.start.euler[1]==0.);
        while(body.motion.entering) {
            assert(durations[test]<100);
            advance(20);assert(body.active && !driver.state.fault);
            if(!test)memcpy(reference[durations[test]],last_written,sizeof last_written);
            else assert(!memcmp(reference[durations[test]],last_written,sizeof last_written));
            durations[test]++;
        }
        ainekio_p4_body_event_t event;assert(ainekio_p4_body_event(&event) && event.completed);
    }
    assert(durations[0]==durations[1]);
    printf("Stand: %ums, identical pulses at playback 0.05/12 and saved speed 20/2000; disabled leveling ignores tilted IMU.\n",durations[0]*20);
}

/* Close the ideal planted-body loop through the production scheduler, mapper
 * and shaft-feedback path. Testing the portable +1 wrapper alone missed the
 * previous P4-specific -1 call. This proves model convergence, not loaded gait. */
static void standing_feedback_converges(void)
{
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2) {
        reset();assert(ainekio_v2_joint_speed_set(2000));
        const unsigned homes[12]={1760,2825,2870,1650,415,440,1650,2740,2800,1730,560,500};
        const bool inverted[12]={false,true,true,true,false,false,true,true,true,false,false,false};
        for(unsigned j=0;j<12;j++)mapped_joints[j]=(ainekio_p4_joint_config_t){
            .channel=(int8_t)j,.home_us=homes[j],.invert=inverted[j],
            .home_cd=j%3==0?0:j%3==1?-3087:-11768,.us_per_degree=11.111111F};
        ainekio_p4_joint_config_t saved[12];memcpy(saved,mapped_joints,sizeof saved);
        imu_status.calibration_applied=true;
        imu_status.attitude.available=imu_status.attitude.fresh=true;
        imu_status.attitude.orientation_wxyz[0]=1;
        ainekio_pca_disarm(&driver);output_step(clock_us);
        ainekio_command_t c=command(303,AINEKIO_INTENT_STAND);
        assert(execute(&c)==ESP_OK && finish(4000).completed && body.balance_hold);
        shaft_tracking_available=true;
        const double target=sign*.03,disturbance=sign*.08;
        if(axis==0)leveling_tuning.roll_deg=target*180./acos(-1.);
        else leveling_tuning.pitch_deg=-target*180./acos(-1.);
        double measured=target+disturbance,rate=0.;
        for(unsigned n=0;n<300;n++) {
            memset(imu_status.attitude.orientation_wxyz,0,sizeof imu_status.attitude.orientation_wxyz);
            imu_status.attitude.orientation_wxyz[0]=(float)cos(measured*.5);
            imu_status.attitude.orientation_wxyz[axis+1]=(float)sin(measured*.5);
            imu_status.attitude.angular_rate_rad_s[axis]=(float)rate;
            advance(20);
            assert(body.active && body.balance_hold && driver.state.armed && !driver.state.fault);
            assert(body.balance_tracking_available && (body.balance_tracking_active || body.balance_settled));
            double next=target+disturbance+body.balance.correction[axis];
            rate=(next-measured)/.02;measured=next;
        }
        assert(fabs(measured-target)*180./acos(-1.)<=BALANCE_SETTLE_DEG);
        assert(body.balance_settled);
        assert(!memcmp(saved,mapped_joints,sizeof saved));
        printf("P4 closed-loop axis=%u sign=%d: residual %.5f deg; saved mapping unchanged.\n",
            axis,sign,(measured-target)*180./acos(-1.));
    }
}

static void sustained_standing_feedback(void)
{
    reset();assert(ainekio_v2_joint_speed_set(1000));
    const unsigned homes[12]={1500,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
    const bool inverted[12]={false,true,true,true,false,false,true,true,true,false,false,false};
    for(unsigned j=0;j<12;j++)mapped_joints[j]=(ainekio_p4_joint_config_t){
        .channel=(int8_t)j,.home_us=homes[j],.invert=inverted[j],
        .home_cd=j%3==0?0:j%3==1?117:-4041,.us_per_degree=11.111111F};
    imu_status.calibration_applied=true;
    imu_status.attitude.available=imu_status.attitude.fresh=true;
    imu_status.attitude.orientation_wxyz[0]=1;
    ainekio_pca_disarm(&driver);output_step(clock_us);
    ainekio_command_t c=command(302,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);
    assert(finish(4000).completed && body.balance_hold);
    uint16_t standing[12];memcpy(standing,last_written,sizeof standing);
    imu_status.attitude.orientation_wxyz[0]=cosf(.1F);
    imu_status.attitude.orientation_wxyz[2]=-sinf(.1F); /* Front raised. */
    const double held_correction=body.balance.correction[1];
    leveling_tuning.strength=leveling_tuning.damping=0;
    advance(200);
    assert(body.balance.correction[1]==held_correction && !memcmp(standing,last_written,sizeof standing));
    leveling_tuning=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
    advance(500);double first=body.balance.correction[1];
    advance(500);
    assert(body.balance.correction[1]>=first && first>.08);
    assert(body.motion.kind==MOTION_NONE && body.active && driver.state.armed);
    assert(ainekio_p4_body_status().balance_active && !driver.state.fault);
    assert(abs((int)last_written[1]-standing[1])>100);
    assert(abs((int)last_written[4]-standing[4])>100);
    ainekio_v2_walk_pose_t relative=body.balance_nominal,start=body.balance_nominal;
    for(unsigned l=0;l<4;l++)for(unsigned j=0;j<3;j++)
        relative.joints[l][j]=body.pose.position[(l<2?l+2:l-2)*3+j]*.00017453292519943296;
    memset(relative.body,0,sizeof relative.body);memset(relative.euler,0,sizeof relative.euler);
    memset(start.body,0,sizeof start.body);memset(start.euler,0,sizeof start.euler);
    assert(ainekio_v2_contact_forward(&relative,body.balance_anchors,false));
    assert(ainekio_v2_contact_forward(&start,body.balance_anchors,false));
    for(unsigned l=2;l<4;l++)assert(start.feet[l][2]-relative.feet[l][2]>10.);
    const ainekio_p4_body_status_t feedback=ainekio_p4_body_status();
    assert(feedback.balance_legs_valid);
    for(unsigned l=0;l<4;l++) {
        assert(fabs(feedback.balance_extension_mm[l]-(start.feet[l][2]-relative.feet[l][2]))<.001);
        if(l<2)assert(feedback.balance_extension_mm[l]<0.); /* Raised fronts shorten. */
        else assert(feedback.balance_extension_mm[l]>10.); /* Lower rears extend. */
    }
    for(unsigned j=0;j<12;j++)assert(fabs(feedback.balance_joint_delta_deg[j]-
        (body.pose.position[j]-body.balance_nominal.frame.position[j])*.01)<.001);
    /* The setting fades only feedback, keeps outputs enabled, and can be
     * re-enabled in the same Stand hold without issuing a new motion. */
    const double before_off=body.balance.correction[1];
    leveling_enabled=false;advance(20);
    assert(body.balance_hold && body.active && driver.state.armed);
    assert(!ainekio_p4_body_status().balance_active);
    assert(body.balance.correction[1]>0. && body.balance.correction[1]<before_off);
    advance(4000);assert(fabs(body.balance.correction[1])<1e-7);
    leveling_enabled=true;advance(1000);
    assert(ainekio_p4_body_status().balance_active && body.balance.correction[1]>.08);
    /* An explicit Stop keeps its existing hold semantics. */
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    memcpy(standing,last_written,sizeof standing);advance(1000);
    assert(!body.balance_hold && !memcmp(standing,last_written,sizeof standing));
    puts("Standing: sustained nose-up feedback reaches mapped carrier outputs and extends modeled rear feet >10mm; Stop holds.");
}

static void startup_crouch_shoulders_rise(void)
{
    for(unsigned manual=0;manual<2;manual++) {
        reset();
        const unsigned homes[12]={1500,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
        const bool inverted[12]={false,true,true,true,false,false,true,true,true,false,false,false};
        /* Deliberately permute channels: stage order follows joint roles. */
        for(unsigned j=0;j<12;j++)mapped_joints[j]=(ainekio_p4_joint_config_t){
            .channel=(int8_t)((j+5)%12),.home_us=homes[j],.invert=inverted[j],
            .home_cd=j%3==0?0:j%3==1?117:-4041,.us_per_degree=11.111111F};
        ainekio_p4_joint_config_t saved[12];memcpy(saved,mapped_joints,sizeof saved);
        if(manual) {
            imu_status.calibration_applied=true;
            imu_status.attitude.available=imu_status.attitude.fresh=true;
            imu_status.attitude.orientation_wxyz[0]=cosf(.02F);
            imu_status.attitude.orientation_wxyz[1]=sinf(.02F);
        }
        ainekio_pca_disarm(&driver);output_step(clock_us);
        const unsigned before=writes;
        ainekio_command_t c=command(301,AINEKIO_INTENT_STAND);
        assert((manual?execute(&c):ainekio_p4_body_startup(driver.state.generation))==ESP_OK);
        assert(writes==before+1 && body.motion.startup_entry && !body.ramping);
        uint16_t folded[12];assert(ainekio_p4_frame_pulses(&body.motion.rise.crouch.frame,folded));
        bool shoulder_on[4]={0};unsigned lifted_shoulders=0,elapsed=0;
        while(body.motion.kind!=MOTION_NONE && elapsed<10000) {
            assert(body.active && driver.state.armed && !driver.state.fault);
            for(unsigned j=0;j<12;j++) {
                unsigned ch=(unsigned)mapped_joints[j].channel;
                if(j%3==0) {
                    unsigned leg=j/3;
                    if(last_written[ch] && !shoulder_on[leg]) {
                        assert(body.motion.contact_entry);
                        unsigned source=leg<2?leg+2:leg-2;
                        const ainekio_v2_posture_t *p=&body.motion.posture;
                        assert(!p->pose.grounded[source]);
                        /* Check the commanded, travel-fitted lift, not the
                         * unfitted 8 mm request previously reported here. */
                        ainekio_v2_walk_pose_t actual=p->pose;
                        assert(ainekio_v2_contact_forward(&actual,(double (*)[3])p->anchors,false));
                        assert(fabs(actual.sole_height[source]-p->pose.sole_height[source])<.002);
                        assert(actual.sole_height[source]>
                            fmax(p->start.sole_height[source],p->target.sole_height[source]));
                        shoulder_on[leg]=true;lifted_shoulders++;
                    }
                } else if(elapsed*1000ULL<4*startup_leg_us()) {
                    if(elapsed*1000ULL<startup_leg_offset(j))assert(!last_written[ch]);
                    else assert(last_written[ch]==folded[ch]);
                }
            }
            advance(20);elapsed+=20;
        }
        assert(elapsed<10000 && lifted_shoulders==4);
        assert(!body.motion.startup_entry && body.motion.kind==MOTION_NONE && body.balance_hold);
        if(manual)assert(body.balance.sensor_usable && body.balance.correction[0]<0.);
        assert(!memcmp(saved,mapped_joints,sizeof saved));
        ainekio_p4_body_event_t event;
        if(manual)assert(ainekio_p4_body_event(&event) && event.completed && event.sequence==301);
        assert(!ainekio_p4_body_event(&event));
        ainekio_v2_walk_pose_t stand;
        assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
        for(unsigned j=0;j<12;j++)assert(fabs(body.motion.posture.pose.frame.position[j]-stand.frame.position[j])<.1);
        printf("Startup: %ums, one leg folds per modeled transit; each shoulder engages at lifted-foot stage; no Home.\n",elapsed);
        /* A later explicit calibration Home still uses the owner's matchmarks. */
        uint16_t home[12];assert(ainekio_p4_home_pulses(home));
        assert(ainekio_p4_body_home(driver.state.generation,home)==ESP_OK);
        assert(!memcmp(last_written,home,sizeof home));
    }
    for(unsigned elapsed=200;elapsed<2400;elapsed+=800) {
        reset();assert(ainekio_p4_joint_defaults(mapped_joints));
        ainekio_pca_disarm(&driver);output_step(clock_us);
        assert(ainekio_p4_body_startup(driver.state.generation)==ESP_OK);advance(elapsed);
        assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
        unsigned before=writes;uint16_t held[12];memcpy(held,last_written,sizeof held);
        advance(3000);assert(writes>before && !memcmp(held,last_written,sizeof held));
        assert(body.motion.kind==MOTION_NONE);
    }
}

static ainekio_command_t freestyle(unsigned seq, unsigned speed, unsigned frames)
{
    ainekio_command_t c={.kind=AINEKIO_COMMAND_MOTION_PLAN,.sequence=seq};
    c.data.motion_plan=(ainekio_motion_plan_t){.joint_map_version=2,.frame_count=frames,
        .target_control=true,.end=AINEKIO_MOTION_PLAN_END_HOLD};
    for(unsigned f=0;f<frames;f++) {
        c.data.motion_plan.frames[f].speed_cd_s=speed;
        for(unsigned j=0;j<12;j++)c.data.motion_plan.frames[f].targets[j]=(f?1000:-1000)+(int)j*10;
    }
    return c;
}
static void freestyle_execution(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=true;
    ainekio_command_t c=freestyle(41,10000,2);
    assert(ainekio_p4_body_supports(&c));assert(execute(&c)==ESP_OK);
    const float start=body.pose.position[0];
    advance(20);
    assert(fabs(body.pose.position[0]-start)<=201.); /* <=100 degrees/s */
    advance(5000);
    assert(body.motion.kind==MOTION_FREESTYLE && body.motion.freestyle.index==0);
    assert(body.motion.freestyle.target_written && last_written[0]==1450);
    ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
    /* Time does not complete a target. A later measurement does. */
    shaft_feedback_reached=true;advance(20);
    assert(body.motion.freestyle.index==1);
    e=finish(5000);assert(e.completed && e.sequence==41 && e.position_verification==2);
    assert(last_written[0]==1550);

    reset();leveling_enabled=false;shaft_feedback_enabled=true;
    c=freestyle(42,10000,1);assert(execute(&c)==ESP_OK);
    driver_timeout=true;advance(1000);
    assert(!body.motion.freestyle.target_written && !shaft_goal_checks);
    driver_timeout=false;advance(1000);
    assert(body.motion.freestyle.target_written);
    /* Missing feedback retains the powered goal, without preventing replacement. */
    shaft_sample_available=false;advance(20000);
    assert(driver.state.armed && !ainekio_p4_body_event(&e));
    c=freestyle(43,5000,1);assert(execute(&c)==ESP_OK);
    assert(ainekio_p4_body_event(&e) && !e.completed && e.sequence==42);
    advance(20);const uint16_t held=last_written[0];
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    assert(ainekio_p4_body_event(&e) && !e.completed && e.sequence==43);
    advance(100);assert(last_written[0]==held);

    reset();c=freestyle(45,10000,1);c.data.motion_plan.target_control=false;
    assert(!ainekio_p4_body_supports(&c) && execute(&c)==ESP_ERR_NOT_SUPPORTED);
    c.data.motion_plan.target_control=true;c.data.motion_plan.joint_map_version=1;
    assert(!ainekio_p4_body_supports(&c));
    for(unsigned end=1;end<=2;end++) {
        reset();leveling_enabled=false;
        ainekio_command_t stand=command(1,AINEKIO_INTENT_STAND);
        assert(execute(&stand)==ESP_OK);assert(finish(10000).completed);
        c=freestyle(46,10000,1);c.data.motion_plan.end=end;
        for(unsigned j=0;j<12;j++)c.data.motion_plan.frames[0].targets[j]=(int32_t)lroundf(body.pose.position[j]);
        assert(execute(&c)==ESP_OK);
        e=finish(10000);assert(e.sequence==46 && e.completed && e.result==ESP_OK);
        assert(!ainekio_p4_body_event(&e));
    }
    puts("Speed targets: measured arrival, sensor loss, write retry, immediate replacement and native endings passed.");
}

static void stand_lifts_and_settles(void)
{
    for(unsigned feedback=0;feedback<2;feedback++) {
        reset();leveling_enabled=false;
        shaft_feedback_enabled=feedback;shaft_feedback_reached=true;
        assert(ainekio_p4_joint_defaults(mapped_joints));
        ainekio_command_t c=command(443,AINEKIO_INTENT_STAND);
        assert(execute(&c)==ESP_OK);
        unsigned elapsed=0;
        while(!body.motion.settle_phase && elapsed<10000){advance(20);elapsed+=20;}
        assert(elapsed<10000 && body.motion.settle_phase==1 && !shaft_goal_checks);
        const ainekio_v2_frame_t base=body.motion.settle_base,peak=body.motion.settle_peak;
        const double level[3]={0};ainekio_v2_posture_t geometry;
        assert(ainekio_v2_posture_begin(&geometry,&base,&peak,level));
        assert(fabs(geometry.target.body[2]-geometry.start.body[2]-2.)<.1);
        for(unsigned l=0;l<4;l++)for(unsigned axis=0;axis<2;axis++)
            assert(fabs(geometry.start.feet[l][axis]-geometry.target.feet[l][axis])<.1);
        uint16_t base_pulses[12],peak_pulses[12];
        assert(ainekio_p4_frame_pulses(&base,base_pulses));
        assert(ainekio_p4_frame_pulses(&peak,peak_pulses));
        assert(memcmp(base_pulses,peak_pulses,sizeof base_pulses));
        /* The reversal must follow an actual peak write, including I2C retry. */
        driver_timeout=true;advance(240);
        assert(body.motion.settle_phase==1 && body.motion.settle_pending_write);
        assert(!body.motion.feedback_commanded_us && !shaft_goal_checks);
        assert(!memcmp(base_pulses,last_written,sizeof base_pulses));
        driver_timeout=false;advance(20);
        assert(body.motion.settle_phase==2 && !memcmp(peak_pulses,last_written,sizeof peak_pulses));
        advance(180);assert(body.motion.settle_phase==2 && !shaft_goal_checks);
        ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
        advance(20);assert(body.motion.settle_phase==3 && !shaft_goal_checks);
        assert(!memcmp(base_pulses,last_written,sizeof base_pulses));
        e=finish(1000);assert(e.completed && e.sequence==443);
        assert(body.balance_hold && driver.state.armed);
        assert(!memcmp(base_pulses,last_written,sizeof base_pulses));
    }
    /* The small terminal motion is replaceable in either direction. */
    for(unsigned phase=1;phase<=2;phase++) {
        reset();leveling_enabled=false;
        ainekio_command_t c=command(440,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
        unsigned elapsed=0;
        while(body.motion.settle_phase!=phase && elapsed<10000){advance(20);elapsed+=20;}
        assert(elapsed<10000);
        c=command(441,AINEKIO_INTENT_NEUTRAL);assert(execute(&c)==ESP_OK);
        ainekio_p4_body_event_t e;assert(ainekio_p4_body_event(&e) && !e.completed && e.sequence==440);
        assert(!body.motion.settle_phase && finish(2000).completed);
    }
    puts("Stand settling: 2 mm lift, written reversal, exact return, final-only feedback and immediate replacement passed.");
}

static void measured_stand_arrival(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=true;shaft_sample_available=false;
    assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_pca_disarm(&driver);output_step(clock_us);
    assert(ainekio_p4_body_startup(driver.state.generation)==ESP_OK);
    assert(body.motion.startup_entry && !body.motion.contact_entry);
    for(unsigned j=0;j<12;j+=3)assert(!last_written[mapped_joints[j].channel]);
    /* Even unavailable feedback cannot prevent the complete authored first pass. */
    unsigned elapsed=0;
    while(!body.motion.feedback_commanded_us && elapsed<10000) {
        advance(20);elapsed+=20;assert(!shaft_goal_checks);
    }
    assert(elapsed<10000 && body.motion.posture_progress==ainekio_v2_posture_path_length());
    assert(driver.state.armed);
    for(unsigned j=0;j<12;j++)assert(last_written[mapped_joints[j].channel]);
    const ainekio_v2_frame_t goal=body.motion.entry_to;
    ainekio_p4_body_event_t event;
    advance(100);assert(!ainekio_p4_body_event(&event));
    assert(!body.motion.posture_replans); /* Missing data does not assert arrival. */
    shaft_sample_available=true;shaft_wait_mask=1;
    advance(20);
    assert(driver.state.armed && body.motion.kind==MOTION_POSE);
    assert(body.motion.posture_replans==1 && !body.motion.feedback_commanded_us);
    assert(!memcmp(&goal,&body.motion.entry_to,sizeof goal));
    /* Several failed final checks repeat full passes immediately, without a
     * non-progress timer, intermediate checks, retry cap or extra receipt. */
    for(unsigned pass=1;pass<=3;pass++) {
        const unsigned checks=shaft_goal_checks;elapsed=0;
        while(!body.motion.feedback_commanded_us && elapsed<10000) {
            advance(20);elapsed+=20;assert(shaft_goal_checks==checks);
        }
        assert(elapsed<10000 && body.motion.posture_progress==ainekio_v2_posture_path_length());
        assert(!ainekio_p4_body_event(&event));
        if(pass<3) {
            advance(20);assert(body.motion.posture_replans==pass+1);
            assert(!memcmp(&goal,&body.motion.entry_to,sizeof goal));
        }
    }
    shaft_feedback_reached=true;advance(20);
    assert(body.motion.kind==MOTION_NONE && body.balance_hold);
    /* The startup request has no external receipt; a named request has one. */
    assert(!ainekio_p4_body_event(&event));
    ainekio_command_t stand=command(444,AINEKIO_INTENT_STAND);
    shaft_feedback_reached=false;assert(execute(&stand)==ESP_OK);
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    assert(body.motion.kind==MOTION_NONE);
    assert(ainekio_p4_body_event(&event) && !event.completed && event.sequence==444);
    puts("Stand: complete passes, final-only observation, immediate correction, fixed goal and cancellation passed.");
}

static void stand_replans_installed_mapping(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_feedback_reached=true;
    /* Captured mechanical configuration that makes the old fixed contact
     * trajectory lose its crank branch. Replay without a physical robot. */
    const uint16_t home[12]={1760,2750,2870,1650,415,440,1650,2740,2800,1700,560,500};
    const bool inverted[12]={false,true,true,true,false,false,true,true,true,false,false,false};
    ainekio_v2_frame_t actual={.geometry_id=ainekio_v2_walk_geometry_id,
        .position={-64.5417,-3568.02,-5140.01,-93.8654,-2121.07,-4120.85,
            -586.834,1222.48,-7088.33,229.524,2472.87,-9371.47}};
    for(unsigned j=0;j<12;j++)mapped_joints[j]=(ainekio_p4_joint_config_t){
        .channel=j,.invert=inverted[j],.home_us=home[j],
        .home_cd=j%3==0?0:j%3==1?-3087:-11768,.us_per_degree=11.111111F};
    assert(ainekio_p4_frame_pulses(&actual,last_written));
    memcpy(body.pulses,last_written,sizeof last_written);
    retain_manual_reference();publish(body.pulses);
    ainekio_command_t c=command(447,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);
    const ainekio_v2_frame_t goal=body.motion.entry_to;
    ainekio_p4_body_event_t event=finish(10000);
    assert(event.completed && driver.state.armed && body.balance_hold);
    assert(body.motion.posture_replans>0);
    for(unsigned j=0;j<12;j++)assert(fabs(body.pose.position[j]-goal.position[j])<.1);
    printf("Installed mapping: Stand completed after %u corrective paths with unchanged final target.\n",body.motion.posture_replans);

    /* An unavailable intermediate mapping is visible and recoverable. It
     * does not erase the request, release PWM, or report completion. */
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_feedback_reached=true;
    c=command(448,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
    uint16_t held[12];memcpy(held,last_written,sizeof held);
    mapping_failure=true;advance(100);
    assert(body.motion.posture_replanning && driver.state.armed);
    assert(!memcmp(held,last_written,sizeof held));
    assert(!ainekio_p4_body_event(&event));
    mapping_failure=false;assert(finish(5000).completed);
    assert(!body.motion.posture_replanning);
}

static void stand_continues_without_feedback(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_jam_enabled=true;
    assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_pca_disarm(&driver);output_step(clock_us);
    shaft_sample_available=false;shaft_stalled_mask=0xfff;
    ainekio_command_t c=command(451,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);
    ainekio_p4_body_event_t event=finish(10000);
    assert(event.completed && event.sequence==451 && event.position_verification==1);
    assert(driver.state.armed && body.motion.kind==MOTION_NONE && body.stand_goal_active);
    assert(!shaft_jam_checks);
    uint16_t held[12];memcpy(held,last_written,sizeof held);advance(2000);
    assert(!memcmp(held,last_written,sizeof held) && !body.motion.posture_replans);
    /* A returned discrepancy resumes correction with the same held goal.
     * It does not create a second external completion. */
    shaft_sample_available=true;shaft_feedback_reached=false;shaft_wait_mask=1;
    advance(20);assert(body.motion.kind==MOTION_POSE && body.motion.posture_replans);
    shaft_feedback_reached=true;advance(5000);
    assert(body.stand_goal_active && body.motion.kind==MOTION_NONE);
    assert(!ainekio_p4_body_event(&event));
    /* Missing observations do not prevent a new movement command. */
    shaft_sample_available=false;shaft_stalled_mask=0;shaft_jam_enabled=false;
    c=command(452,AINEKIO_INTENT_WALK);c.data.intent.data.walk.controls=1;
    c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK);advance(100);
    assert(body.motion.kind==MOTION_WALK && driver.state.armed);
    puts("Feedback loss: authored Stand completes unverified, powered hold and new commands continue, recovery resumes without duplicate receipt.");
}

static void stand_correction_keeps_commanded_reference(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=true;
    assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_pca_disarm(&driver);output_step(clock_us);
    ainekio_command_t c=command(450,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);
    unsigned elapsed=0;
    while(!body.motion.feedback_commanded_us && elapsed<10000){advance(20);elapsed+=20;}
    assert(body.motion.feedback_commanded_us);
    const ainekio_v2_frame_t goal=body.motion.entry_to,previous=body.pose;
    /* A large reported shortfall must select correction, not turn the
     * observation into a replacement command for all supporting joints.
     * Such an observation can also be outside the model's closed linkage. */
    shaft_measured_override=true;shaft_measured=previous;
    for(unsigned j=0;j<12;j++)shaft_measured.position[j]+=(j%2?1:-1)*12000.;
    shaft_wait_mask=1U<<6;
    advance(20);
    assert(body.motion.posture_replans==1 && !body.motion.posture_replanning);
    assert(!memcmp(body.motion.posture.from.position,previous.position,sizeof previous.position));
    assert(!memcmp(body.motion.entry_to.position,goal.position,sizeof goal.position));
    assert(ainekio_v2_posture_arrival_joints(&body.motion.posture,.9)==(7U<<6));
    for(unsigned j=0;j<12;j++)
        assert(fabs(body.pose.position[j]-previous.position[j])/100.<=
            ainekio_v2_joint_speed_default()*.02+.01);
    ainekio_p4_body_event_t event;
    for(unsigned pass=1;pass<=3;pass++) {
        elapsed=0;
        const unsigned checks=shaft_goal_checks;
        while(!body.motion.feedback_commanded_us && elapsed<10000) {
            advance(20);elapsed+=20;assert(shaft_goal_checks==checks);
        }
        assert(body.motion.feedback_commanded_us && driver.state.armed);
        assert(!ainekio_p4_body_event(&event));
        if(pass<3){advance(20);assert(body.motion.posture_replans==pass+1);}
    }
    shaft_feedback_reached=true;advance(20);
    assert(ainekio_p4_body_event(&event) && event.completed && event.sequence==450);
    assert(body.stand_goal_active && driver.state.armed);
    puts("Stand correction: large shortfalls select legs without rebasing support targets; complete passes retain the goal.");
}

static void measured_stand_with_servo_lag(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_simulated=true;
    assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_v2_rise_t rise;assert(ainekio_v2_rise_begin(&rise));
    ainekio_v2_frame_t actual=rise.crouch.frame;
    for(unsigned j=0;j<12;j+=3)actual.position[j]+=(j%2?1:-1)*1500.;
    assert(ainekio_p4_joint_fit_frame(mapped_joints,&actual));
    uint16_t pulses[12];assert(ainekio_p4_frame_pulses(&actual,pulses));
    for(unsigned c=0;c<12;c++)shaft_pulses[c]=pulses[c];
    ainekio_pca_disarm(&driver);output_step(clock_us);
    ainekio_command_t c=command(449,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);
    unsigned elapsed=0;ainekio_p4_body_event_t event={0};
    while(!ainekio_p4_body_event(&event) && elapsed<20000) {
        advance(20);elapsed+=20;assert(driver.state.armed);
    }
    /* Settling can let this slower plant catch up. Whether it converges or
     * needs another pass, completion must describe the measured final goal. */
    if(!event.completed) {
        assert(body.motion.kind==MOTION_POSE && body.motion.posture_replans>1);
        while(!body.motion.feedback_commanded_us && elapsed<30000){advance(20);elapsed+=20;}
        assert(body.motion.feedback_commanded_us);
        for(unsigned ch=0;ch<12;ch++)shaft_pulses[ch]=last_written[ch];
        advance(20);assert(ainekio_p4_body_event(&event) && event.completed);
    }
    assert(event.sequence==449 && body.motion.settle_phase==3);
    for(unsigned joint=0;joint<12;joint++)
        assert(fabs(shaft_pulses[mapped_joints[joint].channel]-last_written[mapped_joints[joint].channel])<=30.);
    puts("Lagging Stand plant: measured final arrival after settling, no false completion passed.");
}

static void standing_tracks_measured_joints(void)
{
    reset();assert(ainekio_v2_joint_speed_set(3));
    imu_status.calibration_applied=true;
    imu_status.attitude.available=imu_status.attitude.fresh=true;
    imu_status.attitude.orientation_wxyz[0]=1;
    ainekio_command_t c=command(1901,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);assert(finish(4000).completed && body.balance_hold);
    /* Isolate the shaft loop during an active leveling episode. */
    leveling_tuning.strength=leveling_tuning.damping=0;
    imu_status.attitude.orientation_wxyz[0]=cosf(.02F);
    imu_status.attitude.orientation_wxyz[1]=sinf(.02F);
    advance(20);
    const ainekio_v2_frame_t target=body.balance_target;
    shaft_tracking_available=shaft_measured_override=true;shaft_measured=target;
    /* An existing loaded offset is not new lag: preserve it as the episode
     * reference, without changing calibration or asking for extra overdrive. */
    shaft_measured.position[1]-=2000.;
    const ainekio_v2_frame_t loaded=shaft_measured;
    advance(20);
    const double band=BALANCE_SHAFT_TOLERANCE_US/mapped_joints[1].us_per_degree*100.;
    for(int n=-120;n<=120;n+=10) {
        shaft_measured=loaded;shaft_measured.position[1]+=(float)(n/mapped_joints[1].us_per_degree*100.);
        advance(20);
        assert(body.balance_tracking_active && body.balance_tracking_available);
        assert(fabs(body.pose.position[1]-target.position[1])<.01);
    }
    shaft_measured=loaded;shaft_measured.position[1]-=(float)(band+100.);
    advance(20);
    assert(body.balance_tracking.observable);
    assert(fabs(body.balance_tracking.body_lag_rad[0])+fabs(body.balance_tracking.body_lag_rad[1])>0.);
    for(unsigned j=0;j<12;j++)assert(body.balance_tracking.trim_deg[j]==0.);
    shaft_tracking_available=false;
    advance(20);assert(body.active && body.balance_hold && driver.state.armed);
    assert(!body.balance_tracking_active && !body.balance_tracking_available);
    assert(!body.balance.actuator_reference_valid);
    shaft_tracking_available=true;advance(20);assert(body.balance_tracking_active);
    assert(body.balance.actuator_reference_valid);
    leveling_enabled=false;advance(20);
    assert(!body.balance_tracking_active && !body.balance.actuator_reference_valid);
    puts("Standing shaft feedback: +/-120us relative noise ignored; excess lag feeds outer-loop tracking without extra joint overdrive; gyro-only recovery and switch passed.");
}

static void standing_sends_tapered_targets(void)
{
    uint16_t expected[2][12];
    for(unsigned test=0;test<4;test++) {
        reset();assert(ainekio_v2_joint_speed_set(test&2?2000:3));
        leveling_enabled=false;
        imu_status.calibration_applied=true;
        imu_status.attitude.available=imu_status.attitude.fresh=true;
        imu_status.attitude.orientation_wxyz[0]=1;
        ainekio_command_t c=command(1904,AINEKIO_INTENT_STAND);
        assert(execute(&c)==ESP_OK && finish(4000).completed);
        const ainekio_v2_frame_t previous=body.pose;
        leveling_enabled=true;shaft_tracking_available=true;
        imu_status.attitude.orientation_wxyz[0]=cosf(.02F);
        imu_status.attitude.orientation_wxyz[1]=sinf(.02F);
        clock_us+=test&1?100000:20000;
        assert(output_step(clock_us));
        assert(!body.balance.reduced && body.balance.correction[0]<0. && body.balance.correction[0]>-.04);
        double largest=0.;
        for(unsigned j=0;j<12;j++)largest=fmax(largest,fabs(body.pose.position[j]-previous.position[j]));
        assert(largest>6.01);
        if(test<2)memcpy(expected[test],last_written,sizeof last_written);
        else assert(!memcmp(expected[test%2],last_written,sizeof last_written));
    }
    puts("Stationary tapered targets: partial correction on first tick, no added joint-speed ramp at 3/2000deg/s with 20/100ms updates.");
}

static void standing_settles_and_wakes(void)
{
    reset();imu_status.calibration_applied=true;
    imu_status.attitude.available=imu_status.attitude.fresh=true;
    imu_status.attitude.orientation_wxyz[0]=1;
    shaft_tracking_available=true;
    ainekio_command_t c=command(1902,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK && finish(4000).completed);
    advance(20);
    assert(body.balance_settled && !ainekio_p4_body_status().balance_active);
    unsigned held_writes=writes,held_reads=shaft_feedback_reads;
    uint16_t held[12];memcpy(held,last_written,sizeof held);
    /* No position feedback work or PWM rewrites even with noisy wipers. */
    shaft_measured_override=true;shaft_measured=body.pose;
    shaft_measured.position[1]+=2000;
    for(unsigned n=0;n<100;n++) {
        const float roll=(n%2?.7F:-.7F)*.01745329252F;
        imu_status.attitude.orientation_wxyz[0]=cosf(roll/2);
        imu_status.attitude.orientation_wxyz[1]=sinf(roll/2);
        advance(20);
        assert(body.balance_settled && writes==held_writes && shaft_feedback_reads==held_reads);
    }
    assert(driver.state.armed && !memcmp(held,last_written,sizeof held));
    shaft_measured_override=false;
    imu_status.attitude.orientation_wxyz[0]=cosf(.012F);
    imu_status.attitude.orientation_wxyz[1]=sinf(.012F); /* 1.375 degrees: wake. */
    advance(20);
    assert(!body.balance_settled && writes>held_writes && shaft_feedback_reads>held_reads);
    assert(ainekio_p4_body_status().balance_active);
    imu_status.attitude.orientation_wxyz[0]=1;imu_status.attitude.orientation_wxyz[1]=0;
    imu_status.attitude.angular_rate_rad_s[0]=.04F;
    advance(20);assert(!body.balance_settled); /* Passing through level is not settled. */
    imu_status.attitude.angular_rate_rad_s[0]=0;advance(20);
    assert(body.balance_settled);
    memcpy(held,last_written,sizeof held);held_writes=writes;
    advance(1000);assert(writes==held_writes && !memcmp(held,last_written,sizeof held));
    /* A changed target wakes the same hold; no new Stand is needed. */
    leveling_tuning.roll_deg=2;advance(20);assert(!body.balance_settled);
    leveling_tuning.roll_deg=0;advance(20);assert(body.balance_settled);
    imu_status.attitude.fresh=false;advance(20);
    assert(!body.balance_settled && !ainekio_p4_body_status().balance_active && driver.state.armed);
    imu_status.attitude.fresh=true;advance(20);assert(body.balance_settled);
    c=command(1903,AINEKIO_INTENT_WALK);c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK);advance(20);
    assert(!body.balance_settled && body.motion.kind==MOTION_WALK && driver.state.armed);
    puts("Standing quiet hold: hysteresis, no shaft reads/PWM writes, rate-aware settling, disturbance/target wake, IMU loss and immediate Walk passed.");
}

static void walking_heading_feedback(void)
{
    reset();leveling_enabled=false;walking_feedback_enabled=true;
    imu_status.calibration_applied=true;
    imu_status.attitude.available=imu_status.attitude.fresh=true;
    imu_status.attitude.orientation_wxyz[0]=1.;
    ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
    c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=100;
    assert(execute(&c)==ESP_OK);
    double measured=0.;
    for(unsigned i=0;i<300;i++) {
        double phase=body.motion.walk.phase,yaw=body.motion.walk.body_yaw;
        imu_status.attitude.orientation_wxyz[0]=(float)cos(measured*.5);
        imu_status.attitude.orientation_wxyz[3]=(float)sin(measured*.5);
        advance(20);
        assert(body.motion.kind==MOTION_WALK && driver.state.armed);
        measured+=body.motion.walk.body_yaw-yaw-.065*(body.motion.walk.phase-phase);
    }
    ainekio_p4_body_status_t status=ainekio_p4_body_status();
    assert(status.walking_feedback_active && status.walking_turn_percent>0. && !status.balance_active);
    assert(body.motion.walk.fast_stroke);
    walking_feedback_enabled=false;
    double phase=body.motion.walk.phase,correction=body.motion.walk.feedback_turn;
    advance(2000);
    assert(body.motion.walk.phase>phase && fabs(body.motion.walk.feedback_turn)<fabs(correction)*.02);
    assert(!ainekio_p4_body_status().walking_feedback_active && !leveling_enabled);
}

static void stall_release_event(void)
{
    for(unsigned startup=0;startup<4;startup++) {
        reset();leveling_enabled=false;shaft_feedback_enabled=false;shaft_jam_enabled=true;
        if(startup==1) {
            assert(ainekio_p4_joint_defaults(mapped_joints));
            ainekio_pca_disarm(&driver);output_step(clock_us);
            assert(ainekio_p4_body_startup(driver.state.generation)==ESP_OK);
        } else if(startup==0 || startup==3) {
            ainekio_command_t c=command(944,AINEKIO_INTENT_STAND);
            assert(execute(&c)==ESP_OK);
        } /* 2 tests powered holding without an active command. */
        shaft_stalled_mask=(1U<<4)|(1U<<5);
        if(startup!=2) {
            unsigned elapsed=0;
            while(!body.motion.feedback_commanded_us && elapsed<10000) {
                advance(20);elapsed+=20;
                assert(driver.state.armed && !shaft_jam_checks);
            }
            assert(elapsed<10000);
        }
        advance(20);
        assert(driver.state.armed && body.active && driver.state.fault==AINEKIO_PCA_FAULT_NONE);
        ainekio_p4_body_event_t e;assert(ainekio_p4_body_event(&e));
        assert(e.result==ESP_OK && !e.completed && e.jam_observation);
        assert(e.stalled_joints==shaft_stalled_mask && e.clock_us);
        assert(e.sequence==(startup==0 || startup==3?944:0));
        uint16_t powered[12];ainekio_p4_body_pulses(powered);
        bool any=false;for(unsigned j=0;j<12;j++)any|=powered[j]!=0;assert(any);
        assert(ainekio_p4_body_status().stalled_joints==shaft_stalled_mask);
        advance(2000);
        while(ainekio_p4_body_event(&e))assert(e.result==ESP_OK);
        assert(driver.state.armed && body.active);
    }
    /* Jam observations cannot consume the command's reserved receipt slots.
     * The body retains a pending observation until its existing reader drains. */
    reset();leveling_enabled=false;shaft_jam_enabled=true;shaft_stalled_mask=1;
    ainekio_p4_body_event_t filler={0};
    while(uxQueueSpacesAvailable(events)>2)assert(xQueueSend(events,&filler,0)==pdTRUE);
    advance(20);assert(body.pending_jam.stalled_joints==1 && driver.state.armed);
    while(ainekio_p4_body_event(&filler))assert(!filler.jam_observation);
    advance(20);assert(!body.pending_jam.stalled_joints && driver.state.armed);
    assert(ainekio_p4_body_event(&filler) && filler.jam_observation && filler.stalled_joints==1);
    advance(2000);assert(!ainekio_p4_body_event(&filler));
    /* Explicit output shutdown still wins over an undelivered observation. */
    reset();leveling_enabled=false;shaft_jam_enabled=true;shaft_stalled_mask=1;
    while(uxQueueSpacesAvailable(events)>2)assert(xQueueSend(events,&filler,0)==pdTRUE);
    advance(20);assert(body.pending_jam.stalled_joints);
    ainekio_pca_emergency_disable(&driver,AINEKIO_PCA_FAULT_EMERGENCY);
    advance(20);assert(!body.pending_jam.stalled_joints && !driver.state.armed && !body.active);

    /* An in-pass dip cannot enter the observer. Recovered end-of-pass
     * feedback completes normally instead of retaining a false stall. */
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_jam_enabled=true;
    shaft_wait_mask=0;shaft_feedback_reached=true;
    ainekio_command_t c=command(945,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);shaft_stalled_mask=0xfff;
    unsigned elapsed=0;
    while(!body.motion.feedback_commanded_us && elapsed<10000) {
        advance(20);elapsed+=20;assert(driver.state.armed && !shaft_jam_checks);
    }
    assert(elapsed<10000);shaft_stalled_mask=0;
    ainekio_p4_body_event_t event=finish(1000);
    assert(event.completed && event.sequence==945 && driver.state.armed);
    /* With verification disabled, jam protection alone does not turn a
     * missing endpoint sample into a new completion barrier. */
    reset();leveling_enabled=false;shaft_jam_enabled=true;shaft_sample_available=false;
    c=command(946,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
    event=finish(10000);
    assert(event.completed && event.sequence==946 && driver.state.armed);
    puts("Stall: nonterminal jam observations preserve motion, powered holds and completion receipts.");
}

static void persistent_standing_goal(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_jam_enabled=true;
    shaft_wait_mask=1;shaft_stalled_mask=0xfff;
    ainekio_command_t c=command(947,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);
    const ainekio_v2_frame_t goal=body.motion.entry_to;
    advance(6000);
    ainekio_p4_body_event_t event;
    assert(driver.state.armed && body.motion.kind==MOTION_POSE && body.motion.posture_replans);
    assert(!shaft_jam_checks && !ainekio_p4_body_event(&event));
    assert(!memcmp(&goal,&body.motion.entry_to,sizeof goal));
    shaft_feedback_reached=true;
    event=finish(10000);assert(event.completed && event.sequence==947);
    assert(body.stand_goal_active && body.motion.kind==MOTION_NONE);
    /* A stricter jam detector must not undo the accepted Stand tolerance. */
    advance(6000);
    assert(body.stand_goal_active && driver.state.armed && !shaft_jam_checks);
    assert(!ainekio_p4_body_event(&event));
    /* Drift after completion starts correction with the same goal and no
     * duplicate command receipt. Missing observations do not drop outputs. */
    shaft_sample_available=false;advance(4000);
    assert(body.stand_goal_active && driver.state.armed);
    shaft_sample_available=true;shaft_feedback_reached=false;
    const unsigned replans=body.motion.posture_replans;
    advance(20);
    assert(body.motion.kind==MOTION_POSE && body.motion.posture_replans>replans);
    assert(body.motion.connection==0 && body.motion.sequence==0);
    assert(!memcmp(&goal,&body.motion.entry_to,sizeof goal));
    advance(6000);
    assert(driver.state.armed && !shaft_jam_checks && !ainekio_p4_body_event(&event));
    shaft_feedback_reached=true;advance(5000);
    assert(body.stand_goal_active && body.motion.kind==MOTION_NONE && driver.state.armed);
    assert(!ainekio_p4_body_event(&event));
    /* Stop cancels persistent recovery; it cannot silently restart. */
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    assert(!body.stand_goal_active);
    shaft_stalled_mask=0;shaft_feedback_reached=false;
    const unsigned checks=shaft_goal_checks;advance(4000);
    assert(body.motion.kind==MOTION_NONE && shaft_goal_checks==checks);
    /* A new action replaces the standing objective normally. */
    shaft_feedback_reached=true;c=command(948,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK && finish(10000).completed && body.stand_goal_active);
    c=command(949,AINEKIO_INTENT_WALK);c.data.intent.data.walk.controls=1;
    c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK && !body.stand_goal_active);
    advance(100);assert(body.motion.kind==MOTION_WALK);
    puts("Stand goal: repeat until reached, retain through drift/missing samples, no jam release or duplicate receipts, Stop/replacement respected.");
}

static void measured_walk_finish(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=true;shaft_sample_available=false;
    ainekio_command_t c=command(846,AINEKIO_INTENT_WALK);
    c.data.intent.data.walk.steps=1;c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=50;
    assert(execute(&c)==ESP_OK);
    ainekio_p4_body_event_t e=finish(40000);
    assert(e.completed && e.sequence==846 && !shaft_goal_checks);
}

static void measured_freestyle_targets(void)
{
    reset();leveling_enabled=false;shaft_feedback_enabled=true;shaft_sample_available=false;
    ainekio_command_t c=freestyle(847,10000,2);assert(execute(&c)==ESP_OK);
    advance(5000);assert(body.motion.freestyle.index==0 && last_written[0]==1450);
    ainekio_p4_body_event_t e;assert(!ainekio_p4_body_event(&e));
    assert(shaft_goal_checks);
    shaft_sample_available=shaft_feedback_reached=true;
    e=finish(5000);assert(e.completed && e.sequence==847 && e.position_verification==2);
    /* Reverse lay-down recovery executes the full reverse path and alignment
     * before Stand checks its final pose. */
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_feedback_reached=true;
    c=command(848,AINEKIO_INTENT_EMOTE);strcpy(c.data.intent.data.asset,"lay_down");
    assert(execute(&c)==ESP_OK);assert(finish(70000).completed);assert(shaft_goal_checks);
    shaft_goal_checks=0;shaft_sample_available=false;
    c=command(849,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
    assert(body.motion.reverse_grounded_entry);
    unsigned elapsed=0;
    while(!body.motion.feedback_commanded_us && elapsed<70000){advance(20);elapsed+=20;assert(!shaft_goal_checks);}
    assert(elapsed<70000);
    shaft_sample_available=shaft_feedback_reached=true;
    assert(finish(1000).completed);
    puts("Freestyle uses measured targets; native reverse lay-down preserves its authored posture entry.");
}

static void measured_clip_targets(void)
{
    for(size_t i=0;i<ainekio_v2_clip_count;i++) {
        reset();leveling_enabled=false;shaft_feedback_enabled=true;shaft_sample_available=false;
        ainekio_command_t c=command(545,ainekio_v2_clips[i].intent);
        if(c.data.intent.kind==AINEKIO_INTENT_EMOTE)strcpy(c.data.intent.data.asset,ainekio_v2_clips[i].command);
        assert(execute(&c)==ESP_OK);
        while(body.motion.entering)advance(20);
        advance(200);
        assert(body.motion.clip_player.waiting && body.motion.face_elapsed_us==0);
        const ainekio_v2_frame_t start=body.pose;
        advance(2000); /* Missing measurements cannot skip the first pose. */
        assert(!memcmp(start.position,body.pose.position,sizeof start.position));
        assert(body.motion.clip_player.target==0 && body.motion.clip_commanded_us);
        shaft_sample_available=shaft_simulated=true;
        for(unsigned j=0;j<12;j++)shaft_pulses[j]=last_written[j];
        unsigned frames=0,arrivals=0;
        while(body.motion.kind!=MOTION_NONE) {
            assert(++frames<10000);
            const size_t before=body.motion.clip_player.target;
            uint16_t target[12];memcpy(target,body.motion.feedback_targets,sizeof target);
            advance(20);
            if(body.motion.clip_player.target>before) {
                arrivals++;
                for(unsigned j=0;j<12;j++)assert(fabs(shaft_pulses[j]-target[j])<=30.);
            }
        }
        ainekio_p4_body_event_t event=finish(20);
        assert(event.completed && event.sequence==545 && shaft_goal_checks && arrivals>2);
        ainekio_v2_frame_t terminal;uint16_t expected[12];
        assert(ainekio_v2_clip_sample(i,UINT64_MAX,&terminal));
        assert(ainekio_p4_frame_pulses(&terminal,expected));
        assert(!memcmp(last_written,expected,sizeof expected));
        for(unsigned j=0;j<12;j++)assert(fabs(shaft_pulses[j]-expected[j])<=30.);
    }
    /* A delayed target remains replaceable through the normal command owner. */
    reset();shaft_feedback_enabled=true;shaft_sample_available=false;
    ainekio_command_t replacement=command(547,AINEKIO_INTENT_EMOTE);
    strcpy(replacement.data.intent.data.asset,"wave");assert(execute(&replacement)==ESP_OK);
    advance(1000);assert(body.motion.clip_player.waiting);
    replacement=command(548,AINEKIO_INTENT_NEUTRAL);assert(execute(&replacement)==ESP_OK);
    ainekio_p4_body_event_t replaced;assert(ainekio_p4_body_event(&replaced));
    assert(replaced.sequence==547 && !replaced.completed);
    assert(finish(2000).completed);
    /* A gesture target enters feedback verification only after its PWM write.
     * Repeated output timeouts retain that exact target and source progress. */
    reset();shaft_feedback_enabled=shaft_feedback_reached=true;
    replacement=command(549,AINEKIO_INTENT_EMOTE);
    strcpy(replacement.data.intent.data.asset,"wave");assert(execute(&replacement)==ESP_OK);
    while(body.motion.entering)advance(20);
    driver_timeout=true;advance(200);
    assert(body.motion.clip_pending_write && !body.motion.clip_commanded_us && !shaft_goal_checks);
    assert(body.motion.face_elapsed_us==0 && body.motion.clip_player.target==0);
    driver_timeout=false;advance(20);
    assert(body.motion.clip_commanded_us && !shaft_goal_checks);
    assert(finish(20000).completed && shaft_goal_checks);
    /* A failed final write cannot start verification or claim completion. */
    reset();leveling_enabled=false;shaft_feedback_enabled=shaft_feedback_reached=true;
    ainekio_command_t c=command(546,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
    unsigned elapsed=0;
    while(body.motion.settle_phase!=2 && elapsed<10000){advance(20);elapsed+=20;}
    assert(elapsed<10000 && !shaft_goal_checks);
    driver_timeout=true;
    elapsed=0;
    while(!body.motion.feedback_pending_write && elapsed<10000){advance(20);elapsed+=20;}
    assert(elapsed<10000 && !body.motion.feedback_commanded_us && !shaft_goal_checks);
    const ainekio_v2_frame_t target=body.motion.feedback_frame;
    advance(200);assert(!memcmp(&target,&body.motion.feedback_frame,sizeof target));
    driver_timeout=false;advance(20);assert(body.motion.feedback_commanded_us && !shaft_goal_checks);
    assert(finish(1000).completed);
    puts("All 23 clips reach every target with unequal servo lag; missing feedback preserves targets, replacement stays immediate, and completion follows actual arrival.");
}

static void inactivity_rest(void)
{
    reset();
    ainekio_command_t c=command(91,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK);assert(finish(15000).completed);rest_tick();
    assert(rest_timer->due==clock_us+180000000);
    clock_us=rest_timer->due-1;rest_tick();assert(body.motion.kind==MOTION_NONE);
    ++clock_us;rest_tick();assert(body.motion.kind==MOTION_CLIP);
    assert(!strcmp(body.motion.face_command,"lay_down"));assert(driver.state.armed);
    const uint64_t admitted=driver.state.generation;
    driver_timeout=true;advance(2000);
    assert(driver.state.armed && body.motion.kind==MOTION_CLIP && body.motion.release_on_complete);
    driver_timeout=false;
    unsigned remaining=15000;
    while(body.motion.kind!=MOTION_NONE && remaining){advance(20);remaining-=20;}
    assert(remaining && driver.state.generation==admitted);
    assert(!driver.state.armed && !body.active && !body.pose_valid && !rest_timer->due);
    assert(!strcmp(body.motion.face_command,"lay_down"));
    for(unsigned j=0;j<12;j++)assert(!commanded[j]);
    clock_us+=600000000;rest_tick();assert(body.motion.kind==MOTION_NONE);
    /* New commands remain immediate. A superseded timer notice cannot override them. */
    c.sequence++;assert(execute(&c)==ESP_OK);rest_timeout(NULL);rest_tick();
    assert(body.motion.kind==MOTION_POSE && driver.state.armed);assert(finish(15000).completed);
    assert(rest_timer->due);
    rest_seconds=0;ainekio_p4_body_activity();rest_tick();assert(!rest_timer->due);
    clock_us+=600000000;rest_tick();assert(body.motion.kind==MOTION_NONE);
    rest_seconds=240;ainekio_p4_body_activity();rest_tick();
    assert(rest_timer->due==clock_us+240000000);
    /* Long speech delays rest until the audio completion resets inactivity. */
    speaker_busy=true;clock_us=rest_timer->due;rest_tick();assert(body.motion.kind==MOTION_NONE);
    speaker_busy=false;ainekio_p4_body_activity();rest_tick();assert(rest_timer->due==clock_us+240000000);
    ainekio_p4_body_listen(true);ainekio_p4_body_activity();rest_tick();assert(!rest_timer->due);
    ainekio_p4_body_listen(false);ainekio_p4_body_activity();rest_tick();assert(rest_timer->due);
    /* Continuous locomotion is work, irrespective of command age. */
    c=command(95,AINEKIO_INTENT_WALK);c.data.intent.data.walk.speed_percent=20;
    assert(execute(&c)==ESP_OK);rest_tick();assert(!rest_timer->due);
    clock_us+=600000000;rest_timeout(NULL);rest_tick();assert(body.motion.kind==MOTION_WALK);
    /* Released and manually calibrated outputs are not automatically re-armed. */
    reset();assert(ainekio_p4_body_move(driver.state.generation,0,1600)==ESP_OK);
    rest_tick();assert(!rest_timer->due);
    /* Manual lay-down still holds; automatic release belongs to its own motion. */
    reset();c=command(100,AINEKIO_INTENT_EMOTE);strcpy(c.data.intent.data.asset,"lay_down");
    assert(execute(&c)==ESP_OK);assert(finish(15000).completed);assert(driver.state.armed);
    c=command(101,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);assert(finish(15000).completed);
    rest_tick();clock_us=rest_timer->due;rest_tick();assert(body.motion.release_on_complete);
    advance(100);c=command(102,AINEKIO_INTENT_STAND);assert(execute(&c)==ESP_OK);
    assert(!body.motion.release_on_complete);assert(finish(15000).completed && driver.state.armed);
    rest_tick();clock_us=rest_timer->due;rest_tick();assert(body.motion.release_on_complete);
    assert(ainekio_p4_body_hold(driver.state.generation)==ESP_OK);
    advance(1000);assert(driver.state.armed && !body.motion.release_on_complete);
    puts("Shared inactivity timer: completion releases outputs; normal motions and replacements retain control.");
}

int main(int argc,char **argv)
{
    stand_lifts_and_settles();
    inactivity_rest();
    disconnected_motion_keeps_outputs();
    measured_walk_finish();
    measured_freestyle_targets();
    stall_release_event();
    persistent_standing_goal();
    measured_clip_targets();
    notification_execution_context();
    walking_heading_feedback();
    measured_stand_arrival();
    stand_replans_installed_mapping();
    stand_correction_keeps_commanded_reference();
    stand_continues_without_feedback();
    measured_stand_with_servo_lag();
    startup_crouch_shoulders_rise();stand_full_rate_without_leveling();
    standing_feedback_converges();standing_sends_tapered_targets();standing_settles_and_wakes();
    if(argc==2 && !strcmp(argv[1],"--feedback")){
        standing_tracks_measured_joints();
        sustained_standing_feedback();
        imu_posture_feedback(1000,1);
        imu_posture_feedback(80,3);
        assert(ainekio_v2_joint_speed_set(1000));
        rise_from_grounded_postures();
        return 0;
    }
    listening_feedback();
    face_playback_clock();
    entry_endpoint_precision();
    motion_speed();
    retired_turns_preserve_active_gait();
    crawl_finish_handoff();
    commanded_pose_survives_pwm_rounding();
    supervised_faults_are_failures();
    motion_from_saved_home();
    calibration_normal_handoff();
    freestyle_execution();
    pose_and_replace();locomotion();clips();rise_from_grounded_postures();cancellation_and_faults();
    stop_motion_phases();ordinary_stop_holds_commanded_pose();sample_clock_with_work();timed_out_output_resumes();rejected_clip_preserves_motion();integrated_catalog();
    puts("Production body: 12 locomotion variants, finite walk, all clips, smooth entry, updates, replacement, stop, delayed resumption, mapping/driver faults, partial assembly and calibration passed.");
    return 0;
}

void ainekio_p4_learning_begin(ainekio_v2_walk_state_t *walk){(void)walk;}
void ainekio_p4_learning_frame(const ainekio_v2_walk_state_t *walk,uint32_t sequence,uint64_t now,
    ainekio_v2_frame_t *frame,bool (*valid)(const ainekio_v2_frame_t *,void *),void *context)
{(void)walk;(void)sequence;(void)now;(void)frame;(void)valid;(void)context;}
