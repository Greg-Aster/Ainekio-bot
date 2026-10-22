#include <assert.h>
#include "../main/gait_learning.c"
static ainekio_p4_calibration_t calibration;
static ainekio_p4_feedback_snapshot_t sensor;
static ainekio_gait_trace_event_t last_event;
static char response[16384],http_status[64];
static const char *request_text;
static unsigned char stored[sizeof(saved_t)];static size_t stored_size;static bool has_stored;
static unsigned char run_stored[sizeof(saved_t)];static size_t run_stored_size;
static unsigned commits;
static ainekio_p4_imu_status_t imu;
static uint64_t clock_us;
ainekio_p4_calibration_t ainekio_p4_calibration(void){return calibration;}
ainekio_p4_imu_status_t ainekio_p4_imu_status(void){return imu;}
bool ainekio_p4_balance_enabled(void){return false;}
bool ainekio_p4_walking_feedback_enabled(void){return true;}
ainekio_v2_balance_tuning_t ainekio_p4_balance_tuning(void){return (ainekio_v2_balance_tuning_t)AINEKIO_V2_BALANCE_TUNING_DEFAULT;}
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out){*out=sensor;}
void ainekio_p4_gait_trace_tracking(const ainekio_gait_trace_event_t *event){last_event=*event;}
int64_t esp_timer_get_time(void){return clock_us;}
esp_err_t nvs_open(const char *name,int mode,nvs_handle_t *h){(void)mode;assert(!strcmp(name,"p4_learning"));*h=1;return ESP_OK;}
esp_err_t nvs_get_blob(nvs_handle_t h,const char *key,void *out,size_t *size)
{(void)h;if(!strcmp(key,"run")){if(!run_stored_size)return ESP_ERR_NVS_NOT_FOUND;if(out){assert(*size>=run_stored_size);memcpy(out,run_stored,run_stored_size);}*size=run_stored_size;return ESP_OK;}assert(!strcmp(key,"model"));if(!has_stored)return ESP_ERR_NVS_NOT_FOUND;if(out){assert(*size>=stored_size);memcpy(out,stored,stored_size);}*size=stored_size;return ESP_OK;}
esp_err_t nvs_set_blob(nvs_handle_t h,const char *key,const void *data,size_t size)
{(void)h;if(!strcmp(key,"run")){assert(size<=sizeof run_stored);memcpy(run_stored,data,size);run_stored_size=size;return ESP_OK;}assert(!strcmp(key,"model"));assert(size<=sizeof stored);memcpy(stored,data,size);stored_size=size;has_stored=true;return ESP_OK;}
esp_err_t nvs_commit(nvs_handle_t h){(void)h;commits++;return ESP_OK;}
void nvs_close(nvs_handle_t h){(void)h;}
esp_err_t httpd_resp_set_status(httpd_req_t *r,const char *s){(void)r;snprintf(http_status,sizeof http_status,"%s",s);return ESP_OK;}
esp_err_t httpd_resp_set_type(httpd_req_t *r,const char *s){(void)r;(void)s;return ESP_OK;}
esp_err_t httpd_resp_sendstr(httpd_req_t *r,const char *s){(void)r;snprintf(response,sizeof response,"%s",s);return ESP_OK;}
int httpd_req_recv(httpd_req_t *r,char *out,size_t length){(void)r;memcpy(out,request_text,length);request_text+=length;return (int)length;}
static void post(const char *text)
{request_text=text;http_status[0]=0;httpd_req_t req={.method=HTTP_POST,.content_len=strlen(text)};assert(ainekio_p4_learning_http(&req)==ESP_OK);}
static bool fit_frame(const ainekio_v2_frame_t *frame,void *context){(void)context;uint16_t pulses[12];return ainekio_p4_joint_map_frame(calibration.joints,frame,pulses);}
int main(void)
{
    /* Phase transition metadata is sampled from the same history as the target.
     * Never interpolate a boolean through a liftoff/touchdown boundary. */
    history[0]=(target_t){.time=100,.grounded={true,false,true,false}};
    history[1]=(target_t){.time=200,.grounded={false,false,true,true}};
    count=head=2;target_t observed;
    assert(target_at(150,&observed));
    assert(!observed.support_known[0]&&observed.support_known[1]&&observed.support_known[2]&&!observed.support_known[3]);
    assert(target_at(200,&observed)&&observed.support_known[0]&&!observed.grounded[0]&&observed.grounded[3]);
    count=head=0;
    assert(ainekio_p4_joint_defaults(calibration.joints));calibration.valid=true;
    const unsigned home[]={1760,2750,2870,1650,415,440,1650,2740,2800,1700,560,500};
    const unsigned invert[]={0,1,1,1,0,0,1,1,1,0,0,0};
    for(unsigned j=0;j<12;j++) {calibration.joints[j].home_us=home[j];calibration.joints[j].invert=invert[j];
        calibration.joints[j].home_cd=j%3==0?0:j%3==1?-3087:-11768;}
    ainekio_feedback_defaults(&sensor.config);sensor.config.enabled=true;sensor.initialized=true;sensor.revision=1;
    for(unsigned j=0;j<12;j++) {
        /* Deliberately mixed feedback polarities, independent of motor inversion. */
        sensor.config.joint[j].points=7;
        for(unsigned k=0;k<3;k++)sensor.config.joint[j].point[k]=(ainekio_feedback_point_t){
            .raw=j%2?3500-k*1500:500+k*1500,.pulse_us=500+k*1150};
    }
    ainekio_v2_walk_state_t walk={0};
    assert(ainekio_v2_walk_begin(&walk,0,(ainekio_v2_walk_controls_t){100,1},0));
    ainekio_v2_frame_t old=walk.pose.frame;
    for(unsigned tick=1;tick<=300;tick++) {
        clock_us=tick*20000;assert(ainekio_v2_walk_tick(&walk,clock_us));
        uint16_t pulse[12];assert(ainekio_p4_joint_map_frame(calibration.joints,&old,pulse));
        sensor.scan++;
        for(unsigned j=0;j<12;j++) {
            unsigned ch=sensor.config.joint[j].channel;sensor.valid_mask|=1U<<ch;
            const ainekio_feedback_joint_t *v=&sensor.config.joint[j];
            double raw=v->point[0].raw+(pulse[calibration.joints[j].channel]-500.)/2300.*((int)v->point[2].raw-v->point[0].raw);
            sensor.raw[ch]=lround(raw);sensor.sampled_us[ch]=clock_us-500-(j%3)*100;
        }
        ainekio_v2_frame_t output=walk.pose.frame;
        assert(ainekio_p4_joint_fit_frame(calibration.joints,&output));
        ainekio_v2_frame_t nominal=output;
        ainekio_p4_learning_frame(&walk,7,clock_us,&output,fit_frame,NULL);
        for(unsigned l=0;l<4;l++)assert(history[(head+15)%16].grounded[l]==walk.pose.grounded[(l+2)%4]);
        assert(!memcmp(&output,&nominal,sizeof output));
        old=output;
    }
    assert(last_event.tracking.valid_mask==15);
    assert(last_event.tracking.phase[0]<walk.phase);
    post("{\"op\":\"configure\",\"enabled\":true,\"amount\":0.5}");assert(!http_status[0]);
    cJSON *root=cJSON_CreateObject(),*model=cJSON_AddObjectToObject(root,"model");
    cJSON_AddStringToObject(root,"op","install");cJSON_AddStringToObject(model,"schema","gait_learning_v2");
    cJSON_AddStringToObject(model,"geometry",ainekio_v2_walk_geometry_id);cJSON_AddStringToObject(model,"id","test-model");
    cJSON_AddNumberToObject(model,"signature",status.signature);cJSON_AddNumberToObject(model,"stride",100);
    cJSON *low=cJSON_AddArrayToObject(model,"pulse_min_us"),*high=cJSON_AddArrayToObject(model,"pulse_max_us");
    for(unsigned j=0;j<12;j++){cJSON_AddItemToArray(low,cJSON_CreateNumber(500));cJSON_AddItemToArray(high,cJSON_CreateNumber(2800));}
    cJSON *coeff=cJSON_AddArrayToObject(model,"coefficients");for(unsigned i=0;i<60;i++)cJSON_AddItemToArray(coeff,cJSON_CreateNumber(i%15==0?.5:0));
    char *text=cJSON_PrintUnformatted(root);post(text);free(text);cJSON_Delete(root);
    assert(!http_status[0]);assert(saved.enabled&&saved.amount==.5f&&!strcmp(saved.id,"test-model"));
    memset(&saved,0,sizeof saved);ainekio_p4_learning_init();assert(saved.enabled&&!strcmp(saved.id,"test-model"));
    /* A previously flashed v2 blob must survive the larger policy structure. */
    saved_v2_t legacy={0};
    memcpy(&legacy,&saved,offsetof(saved_v2_t,model));
    memcpy(legacy.model.coefficient,saved.model.coefficient,sizeof legacy.model.coefficient);
    memcpy(stored,&legacy,sizeof legacy);stored_size=sizeof legacy;
    memset(&saved,0xff,sizeof saved);ainekio_p4_learning_init();
    assert(saved.version==2&&saved.enabled&&!strcmp(saved.id,"test-model"));
    for(unsigned i=0;i<96;i++)assert(((float *)saved.model.feedback)[i]==0);
    unsigned applied_frames=0;
    for(unsigned tick=301;tick<=340;tick++) {
        clock_us=tick*20000;assert(ainekio_v2_walk_tick(&walk,clock_us));
        uint16_t pulse[12];assert(ainekio_p4_joint_map_frame(calibration.joints,&old,pulse));
        sensor.scan++;
        for(unsigned j=0;j<12;j++) {
            unsigned ch=sensor.config.joint[j].channel;
            const ainekio_feedback_joint_t *v=&sensor.config.joint[j];
            sensor.raw[ch]=lround(v->point[0].raw+(pulse[j]-500.)/2300.*((int)v->point[2].raw-v->point[0].raw));
            sensor.sampled_us[ch]=clock_us-500-(j%3)*100;
        }
        ainekio_v2_frame_t frame=walk.pose.frame;assert(ainekio_p4_joint_fit_frame(calibration.joints,&frame));
        ainekio_p4_learning_frame(&walk,7,clock_us,&frame,fit_frame,NULL);
        assert(ainekio_p4_joint_frame_in_travel(calibration.joints,&frame));
        if(!strcmp(status.reason,"active")&&fabs(status.correction[0][0])>.01)applied_frames++;
        old=frame;
    }
    assert(applied_frames>10);
    float enabled_blend=learning.blend;
    sensor.valid_mask=0;
    ainekio_v2_frame_t output=walk.pose.frame;
    assert(ainekio_p4_joint_fit_frame(calibration.joints,&output));
    assert(ainekio_v2_walk_tick(&walk,clock_us+20000));
    ainekio_p4_learning_frame(&walk,7,clock_us+20000,&output,fit_frame,NULL);
    assert(!strcmp(status.reason,"feedback_unavailable"));assert(learning.blend<enabled_blend);
    assert(ainekio_p4_joint_frame_in_travel(calibration.joints,&output));
    calibration.joints[0].home_us++;
    ainekio_p4_learning_frame(&walk,7,clock_us+40000,&output,fit_frame,NULL);
    assert(!strcmp(status.reason,"calibration_or_geometry_changed"));
    calibration.joints[0].home_us--;
    imu.calibration_applied=imu.attitude.available=imu.attitude.fresh=true;
    imu.attitude.orientation_wxyz[0]=1;
    root=cJSON_CreateObject();model=cJSON_AddObjectToObject(root,"model");
    cJSON_AddStringToObject(root,"op","install");cJSON_AddStringToObject(model,"schema","gait_learning_v3");
    cJSON_AddStringToObject(model,"feature_schema","gait_policy_input_v1");
    cJSON_AddStringToObject(model,"geometry",ainekio_v2_walk_geometry_id);cJSON_AddStringToObject(model,"id","sensor-policy");
    cJSON_AddNumberToObject(model,"signature",policy_signature(context_signature(&calibration,&sensor),&imu));
    cJSON_AddNumberToObject(model,"stride",100);
    low=cJSON_AddArrayToObject(model,"pulse_min_us");high=cJSON_AddArrayToObject(model,"pulse_max_us");
    for(unsigned j=0;j<12;j++){cJSON_AddItemToArray(low,cJSON_CreateNumber(500));cJSON_AddItemToArray(high,cJSON_CreateNumber(2800));}
    coeff=cJSON_AddArrayToObject(model,"coefficients");for(unsigned i=0;i<60;i++)cJSON_AddItemToArray(coeff,cJSON_CreateNumber(0));
    cJSON *gains=cJSON_AddArrayToObject(model,"feedback_coefficients");
    for(unsigned i=0;i<96;i++)cJSON_AddItemToArray(gains,cJSON_CreateNumber(i%24==3?.2:0));
    text=cJSON_PrintUnformatted(root);post(text);free(text);
    assert(!http_status[0]&&saved.version==3&&!strcmp(saved.id,"sensor-policy"));
    memset(&saved,0,sizeof saved);ainekio_p4_learning_init();
    assert(saved.version==3&&saved.model.feedback[0][0][3]==.2f);
    stored_size=offsetof(saved_t,model)+offsetof(ainekio_v2_learning_model_t,command);
    memset(&saved,0xff,sizeof saved);ainekio_p4_learning_init();
    assert(saved.version==3&&saved.model.command[0][0][0]==0&&saved.model.gait.duty_delta==0);
    unsigned observed_policy=0;
    for(unsigned tick=343;tick<=420;tick++) {
        clock_us=tick*20000;assert(ainekio_v2_walk_tick(&walk,clock_us));
        uint16_t pulse[12];assert(ainekio_p4_joint_map_frame(calibration.joints,&old,pulse));
        sensor.scan++;
        for(unsigned j=0;j<12;j++) {
            unsigned ch=sensor.config.joint[j].channel;sensor.valid_mask|=1U<<ch;
            const ainekio_feedback_joint_t *v=&sensor.config.joint[j];
            sensor.raw[ch]=lround(v->point[0].raw+(pulse[j]-500.)/2300.*((int)v->point[2].raw-v->point[0].raw));
            sensor.sampled_us[ch]=clock_us-500-(j%3)*100;
        }
        const float roll=tick<380?.04f:-.04f;
        imu.attitude.orientation_wxyz[0]=cosf(roll/2);imu.attitude.orientation_wxyz[1]=sinf(roll/2);
        imu.attitude.timestamp_us=clock_us-100;
        output=walk.pose.frame;assert(ainekio_p4_joint_fit_frame(calibration.joints,&output));
        ainekio_p4_learning_frame(&walk,7,clock_us,&output,fit_frame,NULL);
        if(!strcmp(status.reason,"active")) {
            assert(last_event.tracking.policy_usable);
            assert(last_event.tracking.policy_imu_us==clock_us-100);
            assert(last_event.tracking.policy_phase==walk.phase);
            assert(fabs(status.input.feature[0][3]-(walk.pose.euler[0]-roll)/.1)<1e-5);
            assert(!memcmp(last_event.tracking.policy_input,status.input.feature,sizeof status.input.feature));
            assert(!memcmp(last_event.tracking.policy_correction,status.correction,sizeof status.correction));
            float requested=learning.blend*.2f*status.input.feature[0][3];
            assert(fabs(status.correction[0][0]-requested*status.leg_fit[0])<1e-5);
            observed_policy++;
        }
        old=output;
    }
    assert(observed_policy>60);
    imu.attitude.fresh=false;
    /* Keep fresh shaft samples: loss of the gyro alone must fade the learned
     * response while the ordinary walking state keeps advancing. */
    for(unsigned j=0;j<12;j++)sensor.sampled_us[sensor.config.joint[j].channel]+=20000;
    assert(ainekio_v2_walk_tick(&walk,clock_us+20000));
    output=walk.pose.frame;assert(ainekio_p4_joint_fit_frame(calibration.joints,&output));
    enabled_blend=learning.blend;
    ainekio_p4_learning_frame(&walk,7,clock_us+20000,&output,fit_frame,NULL);
    assert(!strcmp(status.reason,"imu_unavailable")&&learning.blend<enabled_blend);
    assert(!walk.failed);
    /* Failed imports leave the installed model intact. */
    cJSON_DeleteItemFromObjectCaseSensitive(model,"feedback_coefficients");
    text=cJSON_PrintUnformatted(root);post(text);free(text);
    assert(!strcmp(http_status,"400 Bad Request")&&saved.version==3&&!strcmp(saved.id,"sensor-policy"));
    cJSON_ReplaceItemInObjectCaseSensitive(model,"schema",cJSON_CreateString("gait_learning_v4"));
    cJSON_ReplaceItemInObjectCaseSensitive(model,"id",cJSON_CreateString("gait-policy"));
    cJSON_ReplaceItemInObjectCaseSensitive(model,"signature",cJSON_CreateNumber(gait_signature(policy_signature(context_signature(&calibration,&sensor),&imu))));
    cJSON_AddStringToObject(model,"command_schema","gait_policy_command_v1");
    gains=cJSON_AddArrayToObject(model,"feedback_coefficients");
    for(unsigned i=0;i<96;i++)cJSON_AddItemToArray(gains,cJSON_CreateNumber(0));
    cJSON *commands=cJSON_AddArrayToObject(model,"command_coefficients");
    for(unsigned i=0;i<48;i++)cJSON_AddItemToArray(commands,cJSON_CreateNumber(i%12==0?.05:i%12==1?.03:0));
    ainekio_v2_gait_profile_t profile={.duty_delta=-.001f,.sweep_delta_mm=-.2f,.phase_offset={.001f,-.001f,0,0}};
    float profile_values[AINEKIO_GAIT_PROFILE_PARAMETERS];memcpy(profile_values,&profile,sizeof profile);
    cJSON_AddItemToObject(model,"gait_profile",array(profile_values,AINEKIO_GAIT_PROFILE_PARAMETERS));
    cJSON_AddBoolToObject(root,"persist",false);
    unsigned before_install=commits;
    text=cJSON_PrintUnformatted(root);post(text);free(text);cJSON_Delete(root);
    assert(!http_status[0]&&saved.version==4&&!strcmp(saved.id,"gait-policy")&&!model_saved&&commits==before_install);
    post("{\"op\":\"configure\",\"enabled\":true,\"amount\":0.5,\"persist\":true}");
    assert(model_saved&&commits==before_install+1);
    memset(&saved,0,sizeof saved);ainekio_p4_learning_init();
    assert(saved.version==4&&!memcmp(&saved.model.gait,&profile,sizeof profile));
    unsigned committed=commits;
    saved_t persisted_model=saved;
    post("{\"op\":\"configure\",\"enabled\":false,\"amount\":0.25,\"persist\":false}");
    assert(!http_status[0]&&!saved.enabled&&saved.amount==.25f&&!model_saved&&commits==committed);
    ainekio_p4_learning_init();
    assert(model_saved&&!memcmp(&saved,&persisted_model,sizeof saved));
    post("{\"op\":\"configure\",\"enabled\":true,\"amount\":0.75,\"persist\":false}");
    assert(!model_saved&&commits==committed);
    post("{\"op\":\"configure\",\"enabled\":true,\"amount\":0.75,\"persist\":true}");
    assert(model_saved&&commits==committed+1);
    ainekio_p4_learning_init();assert(saved.amount==.75f);
    post("{\"op\":\"configure\",\"enabled\":false,\"amount\":0.25,\"persist\":\"false\"}");
    assert(!strcmp(http_status,"400 Bad Request")&&saved.enabled&&saved.amount==.75f);
    imu.attitude.fresh=true;imu.attitude.orientation_wxyz[0]=1;imu.attitude.orientation_wxyz[1]=0;
    for(unsigned direction=0;direction<4;direction++) {
        clock_us+=20000;
        assert(ainekio_v2_gait_begin(&walk,direction,AINEKIO_GAIT_WALK,2,(ainekio_v2_walk_controls_t){50,1},clock_us));
        ainekio_p4_learning_begin(&walk);
        assert(!memcmp(&walk.profile,&profile,sizeof profile));
        old=walk.pose.frame;assert(ainekio_p4_joint_fit_frame(calibration.joints,&old));
        unsigned active=0;
        while(!walk.complete) {
            clock_us+=20000;assert(ainekio_v2_walk_tick(&walk,clock_us));
            uint16_t pulse[12];assert(ainekio_p4_joint_map_frame(calibration.joints,&old,pulse));
            sensor.scan++;
            for(unsigned j=0;j<12;j++) {
                unsigned ch=sensor.config.joint[j].channel;
                const ainekio_feedback_joint_t *v=&sensor.config.joint[j];
                sensor.raw[ch]=lround(v->point[0].raw+(pulse[j]-500.)/2300.*((int)v->point[2].raw-v->point[0].raw));
                sensor.sampled_us[ch]=clock_us-500-(j%3)*100;
            }
            imu.attitude.timestamp_us=clock_us-100;
            output=walk.pose.frame;assert(ainekio_p4_joint_fit_frame(calibration.joints,&output));
            ainekio_p4_learning_frame(&walk,20+direction,clock_us,&output,fit_frame,NULL);
            if(!strcmp(status.reason,"active")) {
                assert(last_event.tracking.policy_eligible);
                assert(last_event.tracking.gait_signature==saved.signature);
                assert(last_event.tracking.profile_signature==hash_bytes(2166136261U,&profile,sizeof profile));
                assert(status.input.command[0]==(direction==AINEKIO_WALK_FORWARD?1.f:direction==AINEKIO_WALK_BACKWARD?-1.f:0.f));
                assert(status.input.command[1]==(direction==AINEKIO_WALK_TURN_LEFT?1.f:direction==AINEKIO_WALK_TURN_RIGHT?-1.f:0.f));
                active++;
            }
            assert(ainekio_p4_joint_frame_in_travel(calibration.joints,&output));old=output;
        }
        assert(active>40);
    }
    assert(ainekio_v2_walk_begin(&walk,0,(ainekio_v2_walk_controls_t){50,1},clock_us));
    ainekio_p4_learning_begin(&walk);saved.model.gait.landing_mm[0][0]=.1f;
    assert(ainekio_v2_walk_tick(&walk,clock_us+20000));output=walk.pose.frame;
    assert(ainekio_p4_joint_fit_frame(calibration.joints,&output));
    ainekio_p4_learning_frame(&walk,99,clock_us+20000,&output,fit_frame,NULL);
    assert(!strcmp(status.reason,"profile_pending_next_walk"));
    assert(walk.profile.landing_mm[0][0]==0&&!walk.failed);
    saved_t before_run=saved;
    saved_run=saved;
    saved_run.signature=selected_signature(policy_signature(context_signature(&calibration,&sensor),&imu),AINEKIO_GAIT_RUN);
    snprintf(saved_run.id,sizeof saved_run.id,"run-policy");
    memset(&saved_run.model.gait,0,sizeof saved_run.model.gait);
    saved_run.model.gait.lift_delta_mm[0]=.1f;
    post("{\"op\":\"configure\",\"gait\":\"run\",\"enabled\":true,\"amount\":1,\"persist\":true}");
    assert(!http_status[0]&&run_model_saved&&!memcmp(&saved,&before_run,sizeof saved));
    memset(&saved_run,0,sizeof saved_run);ainekio_p4_learning_init();
    assert(!strcmp(saved_run.id,"run-policy")&&saved_run.model.gait.lift_delta_mm[0]==.1f);
    unsigned before_read=commits;
    post("{\"op\":\"read\",\"gait\":\"run\"}");
    assert(!http_status[0]&&strstr(response,"run-policy")&&commits==before_read);
    assert(ainekio_v2_gait_begin(&walk,AINEKIO_WALK_FORWARD,AINEKIO_GAIT_RUN,2,(ainekio_v2_walk_controls_t){50,1},clock_us));
    ainekio_p4_learning_begin(&walk);
    assert(walk.profile.lift_delta_mm[0]==.1f);
    assert(walk.offset_target[0]==walk.offset_target[1]&&walk.offset_target[2]==walk.offset_target[3]);
    unsigned active_run=0;
    for(unsigned tick=0;tick<300&&!walk.complete;tick++) {
        clock_us+=20000;assert(ainekio_v2_walk_tick(&walk,clock_us));
        uint16_t pulse[12];assert(ainekio_p4_joint_map_frame(calibration.joints,&walk.pose.frame,pulse));
        sensor.scan++;
        for(unsigned j=0;j<12;j++) {
            unsigned ch=sensor.config.joint[j].channel;
            const ainekio_feedback_joint_t *v=&sensor.config.joint[j];
            sensor.raw[ch]=lround(v->point[0].raw+(pulse[j]-500.)/2300.*((int)v->point[2].raw-v->point[0].raw));
            sensor.sampled_us[ch]=clock_us-500-(j%3)*100;
        }
        imu.attitude.timestamp_us=clock_us-100;
        output=walk.pose.frame;
        ainekio_p4_learning_frame(&walk,200,clock_us,&output,fit_frame,NULL);
        if(!strcmp(status.reason,"active"))active_run++;
        assert(last_event.tracking.gait_mode==AINEKIO_GAIT_RUN);
        assert(!strcmp(last_event.tracking.model_id,"run-policy"));
    }
    assert(active_run>20);
    post("{\"op\":\"configure\",\"enabled\":true,\"amount\":-1}");assert(!strcmp(http_status,"400 Bad Request"));
    puts("Learning runtime: timestamp alignment, mirrored feedback, legacy migration, sensor policy, JSON/NVS round trip and sensor-loss fade passed");
}
