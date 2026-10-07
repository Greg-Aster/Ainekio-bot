/* Host scheduler/driver boundary; executes the production body owner and native
 * model. No alternate motion implementation or firmware diagnostic path. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../main/body.c"
#include "ainekio/control_codec.h"
static float saved_motion_rate=1.F;
float ainekio_p4_motion_rate(void) { return saved_motion_rate; }

struct test_queue { unsigned capacity, size, count; unsigned char data[]; };
static uint64_t clock_us;
static uint64_t mapping_delay_us, write_delay_us, last_mapping_started, last_write_started;
static ainekio_pca9685_t driver;
static unsigned writes;
static uint16_t last_written[12];
static unsigned enabled = 0xfff;
static bool mapping_failure, driver_failure, power_pending;
static ainekio_body_state_t system_state;
static ainekio_p4_joint_config_t mapped_joints[12];

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
    if(q==results && !q->count && timeout && requests->count) {
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
int esp_task_wdt_reconfigure(const esp_task_wdt_config_t *c) { (void)c;return 0; }
int esp_task_wdt_init(const esp_task_wdt_config_t *c) { (void)c;return 0; }
int esp_task_wdt_add_user(const char *n,void **h) { (void)n;*h=(void*)1;return 0; }
int esp_task_wdt_reset_user(void *h) { (void)h;return 0; }
ainekio_p4_system_status_t ainekio_p4_system_status(void)
{ return (ainekio_p4_system_status_t){.restart_pending=power_pending, .state=system_state}; }
ainekio_pca9685_t *ainekio_p4_output(void) { return &driver; }
bool ainekio_pca_pulse_valid(const ainekio_pca9685_t *d,uint16_t pulse)
{ (void)d; return pulse>=3 && pulse<=19986; } /* Nominal25MHz, prescale121 timer fixture. */
ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *d) { return d->state; }
void ainekio_pca_emergency_disable(ainekio_pca9685_t *d,ainekio_pca_fault_t f)
{ d->state.armed=false;d->state.fault=f;++d->state.generation; }
void ainekio_pca_disarm(ainekio_pca9685_t *d)
{ ainekio_pca_emergency_disable(d,AINEKIO_PCA_FAULT_NONE); }
ainekio_pca_result_t ainekio_pca_recover(ainekio_pca9685_t *d,uint64_t g)
{ return g==d->state.generation && !d->state.armed ? AINEKIO_PCA_OK : AINEKIO_PCA_STALE; }
static ainekio_pca_result_t write_pulses(ainekio_pca9685_t*d,uint64_t g,const uint16_t*p)
{
    if(g!=d->state.generation)return AINEKIO_PCA_STALE;
    if(driver_failure)return AINEKIO_PCA_IO;
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
    system_state=AINEKIO_STATE_IDLE;
    saved_motion_rate=1.F;
    clock_us=1000000;writes=0;enabled=0xfff;mapping_failure=driver_failure=power_pending=false;
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
{ assert(ms%20==0);while(ms){clock_us+=20000;output_step(clock_us);ms-=20;} }
static ainekio_p4_body_event_t finish(unsigned maximum_ms)
{
    ainekio_p4_body_event_t e;
    while(maximum_ms && !ainekio_p4_body_event(&e)) {advance(20);maximum_ms-=20;}
    assert(maximum_ms);return e;
}
static void pose_and_replace(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_NEUTRAL);
    assert(execute(&c)==ESP_OK&&last_written[0]==1600);
    assert(ainekio_p4_body_status().moving);advance(200);
    assert(last_written[0]<1600&&last_written[0]>1500);
    c.sequence=2;c.data.intent.kind=AINEKIO_INTENT_STAND;
    const uint16_t before=last_written[0];assert(execute(&c)==ESP_OK&&last_written[0]==before);
    ainekio_p4_body_event_t e;assert(ainekio_p4_body_event(&e)&&e.sequence==1&&!e.completed&&e.result==ESP_OK);
    e=finish(5000);assert(e.sequence==2&&e.completed&&e.result==ESP_OK);
    uint16_t held[12];memcpy(held,last_written,sizeof(held));advance(100);
    assert(!memcmp(held,last_written,sizeof(held))&&!ainekio_p4_body_event(&e));
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
    reset();c.data.intent.kind=AINEKIO_INTENT_SIT;assert(execute(&c)==ESP_OK);advance(5000);
    mapping_failure=true;advance(20);assert(!driver.state.armed);
    assert(ainekio_p4_body_event(&e)&&!e.completed&&e.result==ESP_ERR_INVALID_ARG);
    reset();c.data.intent.kind=AINEKIO_INTENT_NEUTRAL;assert(execute(&c)==ESP_OK);
    clock_us+=40001;output_step(clock_us);assert(!driver.state.armed);
    assert(ainekio_p4_body_event(&e)&&!e.completed&&e.result==ESP_ERR_TIMEOUT);
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
    system_state=AINEKIO_STATE_IDLE;power_pending=false;
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
        c.sequence=2;assert(execute(&c)==ESP_OK&&driver.state.armed&&body.ramping);
        assert(ainekio_p4_body_status().sequence==2);
    }
}
static void sample_clock_with_work(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_WALK);
    assert(execute(&c)==ESP_OK);advance(2000);
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

    /* The sample clock can expire while time since the last completed write
     * is still under40 ms. Report that as a timeout, never a range failure. */
    clock_us=body.motion.walk.last_us+40001;
    assert(clock_us-body.last_frame<AINEKIO_PCA_PROGRESS_LIMIT_US);
    before=writes;assert(!output_step(clock_us)&&writes==before&&!driver.state.armed);
    ainekio_p4_body_event_t e;
    assert(ainekio_p4_body_event(&e)&&!e.completed&&e.result==ESP_ERR_TIMEOUT);
}
static void rejected_clip_preserves_motion(void)
{
    reset();size_t rest,point;ainekio_v2_frame_t f;uint16_t p[12];
    assert(ainekio_v2_clip_find("rest",&rest)&&ainekio_v2_clip_find("point",&point));
    assert(ainekio_v2_clip_sample(rest,ainekio_v2_clips[rest].duration_us,&f));
    assert(ainekio_p4_joint_defaults(mapped_joints));
    /* The first pose fits the timer, but Point's extended carrier exceeds it.
     * No per-servo range is involved. */
    mapped_joints[7].home_us=19500;
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
    assert(finish(10000).completed);
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
    assert(execute(&walk)==ESP_OK && body.ramping);
    for(unsigned channel=0;channel<12;channel++) {
        for(unsigned i=0;i<12;i++)assert(last_written[i]==(i<=channel?homes[i]:0));
        if(channel<11)advance(200);
    }
    assert(!body.ramping && body.motion.entering);
    assert(!memcmp(saved,mapped_joints,sizeof(saved)));
    advance(10000);
    assert(body.motion.kind==MOTION_WALK && !body.motion.entering);
    ainekio_p4_body_event_t event;assert(!ainekio_p4_body_event(&event));

    /* Stop must cancel each phase of initial Home as well as the later gait. */
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
    mapped_joints[4].home_cd=6000; mapped_joints[5].home_cd=0;
    ainekio_pca_disarm(&driver);output_step(clock_us);
    unsigned before=writes;
    assert(execute(&walk)==AINEKIO_P4_ERR_REFERENCE && writes==before && !driver.state.armed);
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
    assert(body.motion.entry_from.position[0]==1500);
}

static void entry_endpoint_precision(void)
{
    reset();ainekio_command_t c=command(1,AINEKIO_INTENT_STAND);
    assert(execute(&c)==ESP_OK && body.motion.entering);
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
        const uint64_t duration=ainekio_v2_clips[clip].duration_us;
        const size_t count=(size_t)((duration-1)/480000);
        uint64_t entry_at_1x=0;
        for(unsigned r=0;r<sizeof rates/sizeof rates[0];r++) {
            reset();ainekio_command_t c=command(1,ainekio_v2_clips[clip].intent);
            if(c.data.intent.kind==AINEKIO_INTENT_EMOTE)strcpy(c.data.intent.data.asset,ainekio_v2_clips[clip].command);
            c.data.intent.playback_rate=rates[r];
            assert(execute(&c)==ESP_OK);
            const float actual_rate=ainekio_v2_clip_playback_rate(clip,rates[r]);
            assert(body.motion.playback_rate==actual_rate);
            if(!r)entry_at_1x=body.motion.entry_duration;
            else assert(body.motion.entry_duration==entry_at_1x);
            const uint64_t entry_started=clock_us;
            while(body.motion.entering)advance(20);
            const uint64_t entry_expected=(uint64_t)ceil(entry_at_1x/(double)body.motion.entry_rate);
            assert(clock_us-entry_started>=entry_expected && clock_us-entry_started-entry_expected<20000);
            const uint64_t started=clock_us;
            /* Compare the output owner with native choreography at its exact
             * source time. A retimed 1x request is not a usable cross-rate
             * reference, and scheduler rounding can select different samples. */
            for(size_t i=0;i<count;i++) {
                const uint64_t target=(uint64_t)ceil((i+1)*480000./actual_rate/20000.)*20000;
                const uint64_t elapsed=clock_us-started;
                if(target>elapsed)advance((unsigned)((target-elapsed)/1000));
                const float progress=(float)(clock_us-started)*actual_rate;
                const uint64_t source_time=progress>=duration ? duration : (uint64_t)progress;
                ainekio_v2_frame_t expected_frame;uint16_t expected_pulses[12];
                assert(ainekio_v2_clip_sample(clip,source_time,&expected_frame));
                assert(ainekio_p4_joint_map_frame(mapped_joints,&expected_frame,expected_pulses));
                assert(!memcmp(expected_pulses,last_written,sizeof last_written));
                assert(!memcmp(expected_frame.position,body.pose.position,sizeof expected_frame.position));
            }
            ainekio_p4_body_event_t e=finish((unsigned)(duration/actual_rate/1000)+1000);
            assert(e.completed && e.sequence==1 && e.result==ESP_OK);
            const uint64_t expected=(uint64_t)ceil(duration/(double)actual_rate);
            assert(clock_us-started>=expected && clock_us-started-expected<20000);
        }
    }
    /* The entry path uses degrees/s, independently of pulse mapping, and a
     * raised limit releases the old slow-entry ceiling without changing paths. */
    const float entry_limits[]={100.F,2000.F};
    float entry_rates[2];
    for(unsigned k=0;k<2;k++) {
        reset();assert(ainekio_v2_joint_speed_set(entry_limits[k]));
        ainekio_command_t stand=command(1,AINEKIO_INTENT_STAND);
        stand.data.intent.playback_rate=8.F;
        assert(execute(&stand)==ESP_OK);
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
    assert(body.motion.playback_rate==2.F);
    saved_motion_rate=3.F;assert(body.motion.playback_rate==2.F);
    c=command(2,AINEKIO_INTENT_WALK);c.data.intent.data.walk.steps=1;
    assert(execute(&c)==ESP_OK && body.motion.playback_rate==1.F);
    puts("Named motion speed: every clip at 0.25x through 12x, configured joint limit and coordinated retiming, requested and retimed source parity, scaled entry, exact completion and V1 rejection passed.");
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
    assert(status.face_elapsed_us==(uint64_t)((float)(clock_us-body.motion.started)*body.motion.playback_rate));
    assert(status.face_elapsed_us<=100001); /* 0.5x body clock, not 200 ms wall time */
    uint32_t revision=status.face_revision;
    finish_motion(false,ESP_OK);
    ainekio_p4_body_status_t status_after=ainekio_p4_body_status();
    assert(!status_after.face_command&&status_after.face_revision!=revision);
    puts("Presentation follows the body sample clock and cancellation without display I/O in the output task.");
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

int main(void)
{
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
    pose_and_replace();locomotion();clips();cancellation_and_faults();
    stop_motion_phases();sample_clock_with_work();rejected_clip_preserves_motion();integrated_catalog();
    puts("Production body: 12 locomotion variants, finite walk, all clips, smooth entry, updates, replacement, stop, deadlines, mapping/driver faults, partial assembly and calibration passed.");
    return 0;
}
