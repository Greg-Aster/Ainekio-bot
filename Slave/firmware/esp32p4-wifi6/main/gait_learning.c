#include "gait_learning.h"
#include "gait_trace_runtime.h"
#include "servo_feedback.h"
#include "config.h"
#include "ainekio/p4_imu.h"
#include "esp_http_server.h"
#include "esp_timer.h"
#include "nvs.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* Training runs on the host. Only the compact task-space policy executes here.
 * No second PWM writer, target-error integrator, wait, or change of gait clock. */
typedef struct {
    uint32_t version, signature;
    char geometry[96], id[65];
    float stride, amount;
    uint16_t pulse_min[12],pulse_max[12];
    bool enabled;
    ainekio_v2_learning_model_t model;
} saved_t;
/* Read the installed phase-only blob without changing its calibration, enable
 * setting or coefficients. Its model was exactly 60 floats. */
typedef struct {
    uint32_t version, signature;
    char geometry[96], id[65];
    float stride, amount;
    uint16_t pulse_min[12],pulse_max[12];
    bool enabled;
    struct { float coefficient[4][3][5]; } model;
} saved_v2_t;
static saved_t saved={.version=2,.amount=1.f};
static bool model_saved;
static saved_t saved_run={.version=4,.amount=1.f};
static bool run_model_saved;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
static struct {
    uint32_t signature, policy_signature, gait_signature, sequence;
    uint64_t time;
    unsigned valid_mask;
    float error[4][3],correction[4][3],blend,fit,leg_fit[4];
    bool range_reduced;
    bool policy_input_usable;
    ainekio_v2_learning_input_t input;
    ainekio_v2_gait_profile_t profile;
    const char *reason;
} status;
/* Body-task-owned history: interpolate the nominal path at sensor time. */
typedef struct { uint64_t time;double phase,body_x,body_y,body_yaw;ainekio_v2_frame_t frame;float correction[4][3];bool grounded[4],support_known[4]; } target_t;
static target_t history[16];
static unsigned count,head;
static uint32_t sequence, signature;
static ainekio_p4_feedback_snapshot_t previous;
static ainekio_v2_learning_state_t learning;
static uint32_t hash_bytes(uint32_t h,const void *p,size_t n)
{const unsigned char *v=p;for(size_t i=0;i<n;i++){h^=v[i];h*=16777619U;}return h;}
static uint32_t context_signature(const ainekio_p4_calibration_t *c,const ainekio_p4_feedback_snapshot_t *f)
{
    uint32_t h=hash_bytes(2166136261U,ainekio_v2_walk_geometry_id,strlen(ainekio_v2_walk_geometry_id));
    /* Explicit fields avoid padding and sensor revision counters across boots. */
    const char algorithm[]="walk-learning-v2-500-2800";h=hash_bytes(h,algorithm,sizeof algorithm);
    for(unsigned j=0;j<12;j++) {
        const ainekio_p4_joint_config_t *m=&c->joints[j];
        h=hash_bytes(h,&m->channel,sizeof m->channel);h=hash_bytes(h,&m->invert,sizeof m->invert);
        h=hash_bytes(h,&m->home_us,sizeof m->home_us);h=hash_bytes(h,&m->home_cd,sizeof m->home_cd);
        h=hash_bytes(h,&m->us_per_degree,sizeof m->us_per_degree);
        const ainekio_feedback_joint_t *v=&f->config.joint[j];
        h=hash_bytes(h,&v->channel,sizeof v->channel);h=hash_bytes(h,&v->points,sizeof v->points);
        h=hash_bytes(h,v->point,sizeof v->point);
    }
    bool level=ainekio_p4_balance_enabled(),heading=ainekio_p4_walking_feedback_enabled();
    h=hash_bytes(h,&level,sizeof level);h=hash_bytes(h,&heading,sizeof heading);
    if(level) {
        ainekio_v2_balance_tuning_t tuning=ainekio_p4_balance_tuning();
        h=hash_bytes(h,&tuning,sizeof tuning);
    }
    return h;
}
static uint32_t policy_signature(uint32_t h,const ainekio_p4_imu_status_t *imu)
{
    const char algorithm[]="walk-sensor-policy-v3";
    h=hash_bytes(h,algorithm,sizeof algorithm);
    h=hash_bytes(h,&imu->calibration,sizeof imu->calibration);
    const ainekio_v2_balance_tuning_t tuning=ainekio_p4_balance_tuning();
    /* The level reference is also an input when the separate leveling switch
     * is off. Do not silently reuse weights learned with a different reference. */
    h=hash_bytes(h,&tuning.roll_deg,sizeof tuning.roll_deg);
    return hash_bytes(h,&tuning.pitch_deg,sizeof tuning.pitch_deg);
}
static uint32_t gait_signature(uint32_t h)
{const char algorithm[]="walk-profile-policy-v4";return hash_bytes(h,algorithm,sizeof algorithm);}
static void load_model(const char *key,saved_t *destination,bool *persisted)
{
    nvs_handle_t h;if(nvs_open("p4_learning",NVS_READONLY,&h)!=ESP_OK)return;
    saved_t candidate={0};size_t size=0;
    esp_err_t e=nvs_get_blob(h,key,NULL,&size);
    _Static_assert(offsetof(saved_t,model)==offsetof(saved_v2_t,model),"NVS prefix changed");
    const size_t v3_size=offsetof(saved_t,model)+offsetof(ainekio_v2_learning_model_t,command);
    if(e==ESP_OK&&(size==sizeof(saved_v2_t)||size==v3_size||size==sizeof candidate))
        e=nvs_get_blob(h,key,&candidate,&size);
    nvs_close(h);
    bool compatible=(candidate.version==2&&(size==sizeof(saved_v2_t)||size==v3_size||size==sizeof candidate))||
        (candidate.version==3&&(size==v3_size||size==sizeof candidate))||(candidate.version==4&&size==sizeof candidate);
    if(e==ESP_OK&&compatible) {
        portENTER_CRITICAL(&lock);*destination=candidate;*persisted=true;portEXIT_CRITICAL(&lock);
    }
}
void ainekio_p4_learning_init(void)
{
    load_model("model",&saved,&model_saved);
    load_model("run",&saved_run,&run_model_saved);
}
static uint32_t selected_signature(uint32_t policy,unsigned gait)
{
    uint32_t h=gait_signature(policy);
    if(gait==AINEKIO_GAIT_RUN){const char run[]="bounding-run-v1";h=hash_bytes(h,run,sizeof run);}
    return h;
}
void ainekio_p4_learning_begin(ainekio_v2_walk_state_t *walk)
{
    const unsigned gait=walk->run_target==1.?AINEKIO_GAIT_RUN:walk->gait_mode;
    saved_t m;portENTER_CRITICAL(&lock);m=gait==AINEKIO_GAIT_RUN?saved_run:saved;portEXIT_CRITICAL(&lock);
    if(m.version!=4||!m.enabled||!m.id[0]||(walk->gait_mode!=AINEKIO_GAIT_WALK&&walk->gait_mode!=AINEKIO_GAIT_RUN))return;
    const ainekio_p4_calibration_t c=ainekio_p4_calibration();
    ainekio_p4_feedback_snapshot_t f;ainekio_p4_feedback_snapshot(&f);
    const ainekio_p4_imu_status_t imu=ainekio_p4_imu_status();
    if(m.signature==selected_signature(policy_signature(context_signature(&c,&f),&imu),gait)&&
       !strcmp(m.geometry,ainekio_v2_walk_geometry_id))
        ainekio_v2_walk_profile_begin(walk,&m.model.gait);
}
static bool target_at(uint64_t time,target_t *t)
{
    for(unsigned n=1;n<count;n++) {
        const target_t *a=&history[(head+16-count+n-1)%16],*b=&history[(head+16-count+n)%16];
        if(time<a->time||time>b->time||a->time==b->time)continue;
        double u=(double)(time-a->time)/(b->time-a->time);*t=*a;
        t->time=time;t->phase=a->phase+u*(b->phase-a->phase);
        for(unsigned l=0;l<4;l++) {
            t->support_known[l]=time==a->time||time==b->time||a->grounded[l]==b->grounded[l];
            t->grounded[l]=time==b->time?b->grounded[l]:a->grounded[l];
        }
        for(unsigned j=0;j<12;j++)t->frame.position[j]=a->frame.position[j]+u*(b->frame.position[j]-a->frame.position[j]);
        for(unsigned l=0;l<4;l++)for(unsigned k=0;k<3;k++)t->correction[l][k]=a->correction[l][k]+u*(b->correction[l][k]-a->correction[l][k]);
        return true;
    }
    return false;
}
typedef struct {
    const ainekio_p4_joint_config_t *mapping;
    const saved_t *model;
    const uint16_t *nominal;
    bool (*valid)(const ainekio_v2_frame_t *,void *);
    void *context;
    bool range_reduced;
} fit_context_t;
static bool residual_valid(const ainekio_v2_frame_t *frame,void *opaque)
{
    fit_context_t *c=opaque;uint16_t pulses[12];
    if(!ainekio_p4_joint_map_frame(c->mapping,frame,pulses))return false;
    for(unsigned j=0;j<12;j++) {
        int channel=c->mapping[j].channel;if(channel<0)continue;
        unsigned low=c->model->pulse_min[channel],high=c->model->pulse_max[channel];
        /* Preserve the underlying path when steering goes beyond the recorded
         * straight-travel envelope; never permit a learned addition farther. */
        if(c->nominal[channel]<low)low=c->nominal[channel];
        if(c->nominal[channel]>high)high=c->nominal[channel];
        if(pulses[channel]<low||pulses[channel]>high||
           (j%3 && (pulses[channel]<500||pulses[channel]>2800))) {c->range_reduced=true;return false;}
    }
    return !c->valid||c->valid(frame,c->context);
}
void ainekio_p4_learning_frame(const ainekio_v2_walk_state_t *walk,uint32_t seq,uint64_t now,
    ainekio_v2_frame_t *frame,bool (*valid)(const ainekio_v2_frame_t *,void *),void *context)
{
    const ainekio_p4_calibration_t c=ainekio_p4_calibration();
    ainekio_p4_feedback_snapshot_t f;ainekio_p4_feedback_snapshot(&f);
    const ainekio_p4_imu_status_t imu=ainekio_p4_imu_status();
    uint32_t sig=context_signature(&c,&f);
    uint32_t policy_sig=policy_signature(sig,&imu);
    const unsigned gait=walk->pose.run_blend==1.?AINEKIO_GAIT_RUN:walk->gait_mode;
    uint32_t gait_sig=selected_signature(policy_sig,gait);
    if(seq!=sequence||sig!=signature) {
        count=head=0;sequence=seq;signature=sig;memset(&previous,0,sizeof previous);memset(&learning,0,sizeof learning);
    }
    saved_t m;portENTER_CRITICAL(&lock);m=gait==AINEKIO_GAIT_RUN?saved_run:saved;portEXIT_CRITICAL(&lock);
    const bool straight=!walk->steering ||
        (walk->forward_from==100.&&walk->forward_target==100.&&walk->turn_from==0.&&walk->turn_target==0.&&
         walk->lateral_from==0.&&walk->lateral_target==0.);
    const bool eligible=walk->gait_mode==AINEKIO_GAIT_WALK&&walk->direction==AINEKIO_WALK_FORWARD&&
        walk->pose.run_blend==0.&&straight&&!walk->pending_update&&!walk->stopping&&!walk->complete;
    const bool policy_eligible=((gait==AINEKIO_GAIT_WALK&&walk->pose.run_blend==0.)||
        (gait==AINEKIO_GAIT_RUN&&walk->pose.run_blend==1.))&&!walk->stopping&&!walk->complete;
    double dp=count?walk->phase-history[(head+15)%16].phase:0.;
    float reference_twist[3]={0};
    if(count) {
        const target_t *last=&history[(head+15)%16];
        double dt=(now-last->time)/1e6;
        if(dt>0.) {
            double yaw=.5*(walk->body_yaw+last->body_yaw);
            double x=(walk->body_x-last->body_x)/(1000.*dt),y=(walk->body_y-last->body_y)/(1000.*dt);
            reference_twist[0]=x*cos(yaw)+y*sin(yaw);reference_twist[1]=-x*sin(yaw)+y*cos(yaw);
            reference_twist[2]=(walk->body_yaw-last->body_yaw)/dt;
        }
    }
    target_t *current=&history[head];
    *current=(target_t){.time=now,.phase=walk->phase,.frame=*frame,
        .body_x=walk->body_x,.body_y=walk->body_y,.body_yaw=walk->body_yaw};
    for(unsigned l=0;l<4;l++)current->grounded[l]=walk->pose.grounded[(l+2)%4];
    memcpy(current->correction,learning.applied,sizeof current->correction);
    head=(head+1)%16;if(count<16)count++;
    ainekio_gait_trace_event_t event={.kind=AINEKIO_TRACE_TRACKING,.time_us=now};
    event.tracking.signature=sig;event.tracking.command_sequence=seq;
    (void)ainekio_p4_joint_map_frame(c.joints,frame,event.tracking.nominal_pulses);
    event.tracking.stride=walk->stride_percent;event.tracking.eligible=eligible;
    unsigned fresh_mask=0;
    if(f.config.enabled&&f.initialized&&previous.scan&&f.revision==previous.revision)for(unsigned l=0;l<4;l++) {
        uint64_t stamp=UINT64_MAX;
        for(unsigned j=3*l;j<3*l+3;j++) {
            unsigned ch=f.config.joint[j].channel;
            if((uint64_t)f.sampled_us[ch]<stamp)stamp=f.sampled_us[ch];
        }
        target_t target;if(!target_at(stamp,&target))continue;
        ainekio_v2_frame_t measured=target.frame;bool usable=true;
        for(unsigned j=3*l;j<3*l+3;j++) {
            unsigned ch=f.config.joint[j].channel;
            uint64_t a=previous.sampled_us[ch],b=f.sampled_us[ch];
            double pulse;bool in_range;
            if(c.joints[j].channel<0||!(f.valid_mask&(1U<<ch))||!(previous.valid_mask&(1U<<ch))||
                a>stamp||b<stamp||a>=b) {usable=false;break;}
            double raw=previous.raw[ch]+((double)(stamp-a)/(b-a))*((double)f.raw[ch]-previous.raw[ch]);
            if(!ainekio_feedback_position(&f.config.joint[j],raw,&pulse,&in_range)){usable=false;break;}
            double delta=(pulse-c.joints[j].home_us)/c.joints[j].us_per_degree;
            measured.position[j]=c.joints[j].home_cd+100.*(c.joints[j].invert?-delta:delta);
        }
        float actual[4][3],expected[4][3];
        if(!usable||!(ainekio_v2_feet_forward(&measured,actual)&(1U<<l))||
            !(ainekio_v2_feet_forward(&target.frame,expected)&(1U<<l)))continue;
        fresh_mask|=1U<<l;
        event.tracking.sampled_us[l]=stamp;event.tracking.phase[l]=target.phase;
        event.tracking.support_known[l]=target.support_known[l];
        event.tracking.grounded[l]=target.grounded[l];
        memcpy(event.tracking.measured[l],actual[l],sizeof actual[l]);
        memcpy(event.tracking.target[l],expected[l],sizeof expected[l]);
        memcpy(event.tracking.correction[l],target.correction[l],sizeof target.correction[l]);
    }
    previous=f;event.tracking.valid_mask=fresh_mask;
    float error[4][3];
    for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)
        error[l][a]=event.tracking.target[l][a]-event.tracking.measured[l][a];
    const bool imu_usable=imu.calibration_applied&&imu.attitude.available&&imu.attitude.fresh&&
        !imu.attitude.startup&&!imu.attitude.gyro_recovery&&!imu.attitude.acceleration_recovery;
    ainekio_v2_learning_input_t input={0};
    if(imu_usable) {
        const ainekio_v2_balance_tuning_t tuning=ainekio_p4_balance_tuning();
        const double rad=acos(-1.)/180.;
        const double target[2]={walk->pose.euler[0]+tuning.roll_deg*rad,
                                walk->pose.euler[1]-tuning.pitch_deg*rad};
        ainekio_v2_learning_features((const float (*)[3])error,imu.attitude.orientation_wxyz,
            target,imu.attitude.angular_rate_rad_s,&input);
    }
    ainekio_v2_walk_command_features(walk,input.command);
    event.tracking.policy_signature=policy_sig;
    event.tracking.gait_signature=gait_sig;
    event.tracking.policy_eligible=policy_eligible;
    event.tracking.gait_mode=gait;
    event.tracking.cycles_s=walk->cycles_s;
    event.tracking.requested_rate=walk->target.motion_rate;
    memcpy(event.tracking.reference_twist,reference_twist,sizeof reference_twist);
    snprintf(event.tracking.model_id,sizeof event.tracking.model_id,"%s",m.id);
    event.tracking.model_amount=m.enabled?m.amount:0.f;
    event.tracking.profile_signature=hash_bytes(2166136261U,&walk->profile,sizeof walk->profile);
    event.tracking.policy_phase=walk->phase;
    event.tracking.policy_imu_us=imu.attitude.timestamp_us;
    event.tracking.policy_usable=imu_usable&&fresh_mask==15;
    memcpy(event.tracking.policy_input,input.feature,sizeof input.feature);
    memcpy(event.tracking.policy_command,input.command,sizeof input.command);
    const char *reason=!m.enabled?"disabled":!m.id[0]?"no_model":
        (m.signature!=(m.version==4?gait_sig:m.version==3?policy_sig:sig)||strcmp(m.geometry,ainekio_v2_walk_geometry_id))?"calibration_or_geometry_changed":
        (m.version==4? !policy_eligible : (!eligible||fabs(walk->stride_percent-m.stride)>.001))?"untrained_command":
        (m.version==4&&(memcmp(&walk->profile,&m.model.gait,sizeof walk->profile)||walk->profile_run!=(gait==AINEKIO_GAIT_RUN)))?"profile_pending_next_walk":
        fresh_mask!=15?"feedback_unavailable":(m.version>=3&&!imu_usable)?"imu_unavailable":"active";
    bool usable=!strcmp(reason,"active");
    event.tracking.model_active=usable;
    ainekio_v2_frame_t adjusted;
    fit_context_t fitting={.mapping=c.joints,.model=&m,.nominal=event.tracking.nominal_pulses,.valid=valid,.context=context};
    ainekio_v2_learning_policy_apply(&learning,&m.model,m.version>=3?&input:NULL,
        walk->phase,dp,usable,m.amount,frame,residual_valid,&fitting,&adjusted);
    *frame=adjusted;memcpy(current->correction,learning.applied,sizeof current->correction);
    memcpy(event.tracking.policy_correction,learning.applied,sizeof learning.applied);
    portENTER_CRITICAL(&lock);
    status.signature=sig;status.policy_signature=policy_sig;status.gait_signature=gait_sig;status.sequence=seq;status.time=now;status.valid_mask=fresh_mask;
    status.profile=walk->profile;
    status.input=input;status.policy_input_usable=event.tracking.policy_usable;
    status.reason=reason;status.blend=learning.blend;status.fit=learning.fit;status.range_reduced=fitting.range_reduced;
    memcpy(status.leg_fit,learning.leg_fit,sizeof status.leg_fit);
    memcpy(status.correction,learning.applied,sizeof status.correction);
    memcpy(status.error,error,sizeof error);
    portEXIT_CRITICAL(&lock);
    ainekio_p4_gait_trace_tracking(&event);
}
static esp_err_t reply(httpd_req_t *r,const char *code,const char *message)
{httpd_resp_set_status(r,code);httpd_resp_set_type(r,"application/json");return httpd_resp_sendstr(r,message);}
static bool number(cJSON *o,const char *name,double *out)
{cJSON *v=cJSON_GetObjectItemCaseSensitive(o,name);if(!cJSON_IsNumber(v)||!isfinite(v->valuedouble))return false;*out=v->valuedouble;return true;}
static cJSON *array(const float *values,unsigned n)
{cJSON *a=cJSON_CreateArray();for(unsigned i=0;i<n;i++)cJSON_AddItemToArray(a,cJSON_CreateNumber(values[i]));return a;}
static bool read_array(cJSON *o,const char *name,float *out,unsigned count)
{
    cJSON *a=cJSON_GetObjectItemCaseSensitive(o,name);
    if(!cJSON_IsArray(a)||cJSON_GetArraySize(a)!=(int)count)return false;
    for(unsigned i=0;i<count;i++) {
        cJSON *v=cJSON_GetArrayItem(a,i);
        if(!cJSON_IsNumber(v)||!isfinite(v->valuedouble)||!isfinite((float)v->valuedouble))return false;
        out[i]=v->valuedouble;
    }
    return true;
}
esp_err_t ainekio_p4_learning_http(httpd_req_t *r)
{
    bool run=false,changed=true;
    saved_t candidate;portENTER_CRITICAL(&lock);candidate=saved;portEXIT_CRITICAL(&lock);
    if(r->method==HTTP_POST) {
        if(r->content_len<=0||r->content_len>16384)return reply(r,"400 Bad Request","{\"error\":\"Expected a model JSON object\"}");
        char *input=malloc(r->content_len+1);if(!input)return ESP_ERR_NO_MEM;
        size_t used=0;while(used<(size_t)r->content_len) {int n=httpd_req_recv(r,input+used,r->content_len-used);if(n<=0){free(input);return ESP_FAIL;}used+=n;}
        input[used]=0;cJSON *root=cJSON_Parse(input);free(input);
        cJSON *op=cJSON_GetObjectItemCaseSensitive(root,"op");bool ok=cJSON_IsString(op);
        cJSON *gait=cJSON_GetObjectItemCaseSensitive(root,"gait");
        if(gait) {
            ok=ok&&cJSON_IsString(gait)&&(!strcmp(gait->valuestring,"walk")||!strcmp(gait->valuestring,"run"));
            run=ok&&!strcmp(gait->valuestring,"run");
            if(run){portENTER_CRITICAL(&lock);candidate=saved_run;portEXIT_CRITICAL(&lock);}
        }
        cJSON *persist_value=cJSON_GetObjectItemCaseSensitive(root,"persist");
        const bool persist=!persist_value||cJSON_IsTrue(persist_value);
        if(persist_value&&!cJSON_IsBool(persist_value))ok=false;
        if(ok&&!strcmp(op->valuestring,"read"))changed=false;
        else if(ok&&!strcmp(op->valuestring,"configure")) {
            double amount;cJSON *enabled=cJSON_GetObjectItemCaseSensitive(root,"enabled");
            ok=cJSON_IsBool(enabled)&&number(root,"amount",&amount)&&amount>=0.&&amount<=1.;
            if(ok){candidate.enabled=cJSON_IsTrue(enabled);candidate.amount=amount;}
        } else if(ok&&!strcmp(op->valuestring,"install")) {
            cJSON *model=cJSON_GetObjectItemCaseSensitive(root,"model"),*id=cJSON_GetObjectItemCaseSensitive(model,"id"),
                *geometry=cJSON_GetObjectItemCaseSensitive(model,"geometry"),*schema=cJSON_GetObjectItemCaseSensitive(model,"schema"),
                *features=cJSON_GetObjectItemCaseSensitive(model,"feature_schema");double sig,stride;
            unsigned version=cJSON_IsString(schema)&&!strcmp(schema->valuestring,"gait_learning_v4")?4:
                cJSON_IsString(schema)&&!strcmp(schema->valuestring,"gait_learning_v3")?3:2;
            ok=cJSON_IsString(schema)&&(version>=3||!strcmp(schema->valuestring,"gait_learning_v2"))&&cJSON_IsString(id)&&strlen(id->valuestring)>0&&strlen(id->valuestring)<sizeof candidate.id&&
                cJSON_IsString(geometry)&&!strcmp(geometry->valuestring,ainekio_v2_walk_geometry_id)&&
                number(model,"signature",&sig)&&sig>=0&&sig<=UINT32_MAX&&floor(sig)==sig&&
                number(model,"stride",&stride)&&stride>0&&stride<=100&&
                read_array(model,"coefficients",&candidate.model.coefficient[0][0][0],60);
            if(ok) {
                memset(candidate.model.feedback,0,sizeof candidate.model.feedback);
                memset(candidate.model.command,0,sizeof candidate.model.command);
                memset(&candidate.model.gait,0,sizeof candidate.model.gait);
                if(version>=3)ok=cJSON_IsString(features)&&!strcmp(features->valuestring,"gait_policy_input_v1")&&
                    read_array(model,"feedback_coefficients",&candidate.model.feedback[0][0][0],96);
                if(ok&&version==4) {
                    cJSON *command_schema=cJSON_GetObjectItemCaseSensitive(model,"command_schema");
                    float values[AINEKIO_GAIT_PROFILE_PARAMETERS];
                    _Static_assert(sizeof values==sizeof candidate.model.gait,"Gait profile serialization changed");
                    ok=cJSON_IsString(command_schema)&&!strcmp(command_schema->valuestring,"gait_policy_command_v1")&&
                        read_array(model,"command_coefficients",&candidate.model.command[0][0][0],48)&&
                        read_array(model,"gait_profile",values,AINEKIO_GAIT_PROFILE_PARAMETERS);
                    if(ok){memcpy(&candidate.model.gait,values,sizeof values);ok=ainekio_v2_gait_profile_valid(&candidate.model.gait);}
                }
            }
            if(ok) {
                cJSON *low=cJSON_GetObjectItemCaseSensitive(model,"pulse_min_us"),*high=cJSON_GetObjectItemCaseSensitive(model,"pulse_max_us");
                ok=cJSON_IsArray(low)&&cJSON_IsArray(high)&&cJSON_GetArraySize(low)==12&&cJSON_GetArraySize(high)==12;
                for(unsigned j=0;ok&&j<12;j++) {
                    cJSON *a=cJSON_GetArrayItem(low,j),*b=cJSON_GetArrayItem(high,j);
                    ok=cJSON_IsNumber(a)&&cJSON_IsNumber(b)&&isfinite(a->valuedouble)&&isfinite(b->valuedouble)&&
                       a->valuedouble>=1&&b->valuedouble<=65535&&a->valuedouble<=b->valuedouble&&
                       floor(a->valuedouble)==a->valuedouble&&floor(b->valuedouble)==b->valuedouble;
                    if(ok){candidate.pulse_min[j]=a->valueint;candidate.pulse_max[j]=b->valueint;}
                }
            }
            if(ok){candidate.version=version;candidate.signature=(uint32_t)sig;candidate.stride=stride;
                snprintf(candidate.id,sizeof candidate.id,"%s",id->valuestring);snprintf(candidate.geometry,sizeof candidate.geometry,"%s",geometry->valuestring);}
        } else ok=false;
        cJSON_Delete(root);
        if(!ok)return reply(r,"400 Bad Request","{\"error\":\"Invalid learning operation or model\"}");
        /* Training candidates can execute from RAM. Only explicit persistent
         * installation/configuration writes flash; legacy requests still save. */
        if(persist&&changed) {
            nvs_handle_t h;esp_err_t e=nvs_open("p4_learning",NVS_READWRITE,&h);
            if(e==ESP_OK){e=nvs_set_blob(h,run?"run":"model",&candidate,sizeof candidate);if(e==ESP_OK)e=nvs_commit(h);nvs_close(h);}
            if(e!=ESP_OK)return reply(r,"500 Internal Server Error","{\"error\":\"Model save failed\"}");
        }
        if(changed) {
            portENTER_CRITICAL(&lock);
            saved_t *target=run?&saved_run:&saved;bool *stored=run?&run_model_saved:&model_saved;
            *stored=persist||(*stored&&!memcmp(&candidate,target,sizeof candidate));
            *target=candidate;portEXIT_CRITICAL(&lock);
        }
    }
    /* Allocate JSON outside the body lock. Snapshot only the small telemetry. */
    float error[4][3],correction[4][3],blend,fit,leg_fit[4];
    bool range_reduced,input_usable,persisted;uint32_t sig,policy_sig,gait_sig,seq;uint64_t time;unsigned mask;const char *reason;
    float selected_profile[AINEKIO_GAIT_PROFILE_PARAMETERS],profile[AINEKIO_GAIT_PROFILE_PARAMETERS];
    ainekio_v2_learning_input_t input;
    portENTER_CRITICAL(&lock);persisted=run?run_model_saved:model_saved;sig=status.signature;seq=status.sequence;time=status.time;mask=status.valid_mask;
    policy_sig=status.policy_signature;gait_sig=status.gait_signature;input=status.input;input_usable=status.policy_input_usable;
    memcpy(selected_profile,&status.profile,sizeof selected_profile);
    range_reduced=status.range_reduced;memcpy(leg_fit,status.leg_fit,sizeof leg_fit);
    blend=status.blend;fit=status.fit;reason=status.reason;memcpy(error,status.error,sizeof error);memcpy(correction,status.correction,sizeof correction);portEXIT_CRITICAL(&lock);
    cJSON *o=cJSON_CreateObject();cJSON_AddStringToObject(o,"schema","gait_learning_status_v1");
    cJSON_AddStringToObject(o,"gait",run?"run":"walk");
    cJSON_AddBoolToObject(o,"run_policy_supported",true);
    cJSON_AddStringToObject(o,"geometry",ainekio_v2_walk_geometry_id);cJSON_AddStringToObject(o,"model_id",candidate.id);
    cJSON_AddStringToObject(o,"model_schema",candidate.version==4?"gait_learning_v4":candidate.version==3?"gait_learning_v3":"gait_learning_v2");
    cJSON_AddStringToObject(o,"feature_schema","gait_policy_input_v1");
    cJSON_AddStringToObject(o,"command_schema","gait_policy_command_v1");
    cJSON_AddNumberToObject(o,"gait_signature",gait_sig);
    cJSON_AddNumberToObject(o,"policy_signature",policy_sig);
    cJSON_AddBoolToObject(o,"policy_input_usable",input_usable);
    cJSON_AddItemToObject(o,"policy_features",array(&input.feature[0][0],32));
    cJSON_AddItemToObject(o,"policy_command",array(input.command,4));
    memcpy(profile,&candidate.model.gait,sizeof profile);
    cJSON_AddItemToObject(o,"gait_profile",array(profile,AINEKIO_GAIT_PROFILE_PARAMETERS));
    cJSON_AddItemToObject(o,"selected_gait_profile",array(selected_profile,AINEKIO_GAIT_PROFILE_PARAMETERS));
    cJSON_AddNumberToObject(o,"model_signature",candidate.signature);cJSON_AddNumberToObject(o,"signature",sig);
    cJSON_AddNumberToObject(o,"stride",candidate.stride);cJSON_AddNumberToObject(o,"amount",candidate.amount);
    cJSON_AddBoolToObject(o,"enabled",candidate.enabled);cJSON_AddStringToObject(o,"reason",reason?reason:"no_walk_observation");
    cJSON_AddBoolToObject(o,"model_saved",persisted);
    cJSON_AddNumberToObject(o,"observed_us",time);cJSON_AddNumberToObject(o,"command_sequence",seq);
    cJSON_AddNumberToObject(o,"valid_legs",mask);cJSON_AddNumberToObject(o,"blend",blend);cJSON_AddNumberToObject(o,"fit",fit);
    cJSON_AddBoolToObject(o,"range_reduced",range_reduced);cJSON_AddItemToObject(o,"leg_fit",array(leg_fit,4));
    cJSON *minimum=cJSON_AddArrayToObject(o,"pulse_min_us"),*maximum=cJSON_AddArrayToObject(o,"pulse_max_us");
    for(unsigned j=0;j<12;j++){cJSON_AddItemToArray(minimum,cJSON_CreateNumber(candidate.pulse_min[j]));cJSON_AddItemToArray(maximum,cJSON_CreateNumber(candidate.pulse_max[j]));}
    cJSON_AddItemToObject(o,"error_mm",array(&error[0][0],12));cJSON_AddItemToObject(o,"correction_mm",array(&correction[0][0],12));
    cJSON_AddItemToObject(o,"coefficients",array(&candidate.model.coefficient[0][0][0],60));
    cJSON_AddItemToObject(o,"feedback_coefficients",array(&candidate.model.feedback[0][0][0],96));
    cJSON_AddItemToObject(o,"command_coefficients",array(&candidate.model.command[0][0][0],48));
    char *text=cJSON_PrintUnformatted(o);cJSON_Delete(o);if(!text)return ESP_ERR_NO_MEM;
    httpd_resp_set_type(r,"application/json");esp_err_t result=httpd_resp_sendstr(r,text);free(text);return result;
}
