/* Host binding of production geometry, mapping, ramp, feedback and attitude
 * owners. Callers supply sensor samples; geometry queries need none.
 * This file owns no alternate controller. */
#include "joint_calibration.h"
#include "servo_feedback.h"
#include "ainekio/imu.h"
#include "ainekio/pca9685.h"
#include "ainekio/v2_balance.h"
#include "ainekio/v2_learning.h"
#include "ainekio/control_codec.h"
#include "virtual_body.h"
#include "walk_data.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    ainekio_p4_joint_config_t mapping[12];
    ainekio_p4_feedback_snapshot_t sample;
    ainekio_feedback_filter_t filters[16];
    ainekio_p4_feedback_progress_t progress;
    ainekio_imu_t imu;
    ainekio_v2_walk_state_t walk;
    ainekio_v2_balance_t balance;
    ainekio_v2_balance_tuning_t tuning;
    ainekio_v2_learning_state_t learning;
    ainekio_v2_learning_model_t model;
    double speed, learning_amount;
    uint64_t last_frame_us;
    uint64_t last_sensor_us;
    bool heading_enabled, balance_enabled, model_supplied;
} simulation_t;
static _Thread_local simulation_t *current;
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out){*out=current->sample;}
void simulation_p4_activate(void *state){current=state;}
void simulation_p4_mapping(void *state,ainekio_p4_calibration_t *out)
{
    simulation_t *s=state;
    *out=(ainekio_p4_calibration_t){.valid=true,.saved=true,.profile_confirmed=true};
    memcpy(out->joints,s->mapping,sizeof s->mapping);
}
void simulation_p4_imu(void *state,uint64_t now,ainekio_p4_imu_status_t *out)
{
    simulation_t *s=state;memset(out,0,sizeof *out);
    ainekio_imu_observe(&s->imu,now,&out->attitude);
    /* Synthetic sensor axes are already the modeled body's axes. */
    out->calibration_applied=s->imu.initialized;
}

void *simulation_new(const double *mapping,const double *feedback,const double *settings)
{
    simulation_t *s=calloc(1,sizeof(*s));if(!s)return NULL;
    ainekio_feedback_defaults(&s->sample.config);
    s->sample.config.enabled=(uint8_t)settings[4];
    s->sample.config.jam_enabled=(uint8_t)settings[5];
    s->sample.config.tolerance_us=(uint16_t)settings[0];
    s->sample.config.arrival_tolerance_us=(uint16_t)settings[1];
    s->sample.config.no_progress_ms=(uint32_t)settings[2];
    s->sample.config.progress_us=(uint16_t)settings[3];
    s->sample.config.stand_enabled=(uint8_t)settings[6];
    s->sample.initialized=true;
    for(unsigned j=0;j<12;j++) {
        const double *m=mapping+j*5,*f=feedback+j*7;
        s->mapping[j]=(ainekio_p4_joint_config_t){.channel=m[0],.invert=m[1],.home_us=m[2],.home_cd=m[3],.us_per_degree=m[4]};
        ainekio_feedback_joint_t *p=&s->sample.config.joint[j];p->channel=f[0];p->points=7;
        for(unsigned k=0;k<3;k++)p->point[k]=(ainekio_feedback_point_t){.raw=f[1+2*k],.pulse_us=f[2+2*k]};
    }
    ainekio_imu_config_t cfg=ainekio_imu_default_config();
    if(!ainekio_p4_joints_valid(s->mapping)||!ainekio_feedback_config_valid(&s->sample.config)||!ainekio_imu_init(&s->imu,&cfg)){free(s);return NULL;}
    return s;
}
void simulation_free(void *state){free(state);}
/* Static tensor-backend constants come from the same generated geometry as
 * the P4. This query performs no motion and needs no acquired sensor sample. */
void simulation_foot_geometry(double *out)
{
    const float parameters[12]={V2_O_X,V2_O_Z,V2_C_X,V2_C_Z,V2_PRIMARY,V2_INPUT,
        V2_ROD,V2_PICKUP,V2_ALPHA_ZERO,V2_THETA_ZERO,V2_BETA_ZERO,V2_BRANCH};
    for(unsigned i=0;i<12;i++)out[i]=parameters[i];
    for(unsigned leg=0;leg<4;leg++) {
        const v2_walk_leg_t *g=&v2_walk_legs[(leg+2)%4];
        double *p=out+12+13*leg;
        for(unsigned i=0;i<3;i++) {
            p[i]=g->shoulder_sign[i];p[3+i]=g->shoulder_translation[i];
            p[6+i]=g->mechanism_translation[i];p[9+i]=g->reference[i];
        }
        p[12]=g->mirror;
    }
}
/* Episode-local sensor memory for JAX's functional environment state. Only
 * firmware-owned feedback/IMU state crosses this ABI, never a controller. */
typedef struct {
    ainekio_p4_feedback_snapshot_t sample;
    ainekio_feedback_filter_t filters[16];
    ainekio_p4_feedback_progress_t progress;
    ainekio_imu_t imu;
    uint64_t last_sensor_us;
} simulation_sensor_state_t;
size_t simulation_sensor_size(void){return sizeof(simulation_sensor_state_t);}
void simulation_sensor_export(void *state,unsigned char *bytes)
{
    simulation_t *s=state;simulation_sensor_state_t value={0};
    value.sample=s->sample;memcpy(value.filters,s->filters,sizeof value.filters);
    value.progress=s->progress;value.imu=s->imu;value.last_sensor_us=s->last_sensor_us;
    memcpy(bytes,&value,sizeof value);
}
void simulation_sensor_import(void *state,const unsigned char *bytes)
{
    simulation_t *s=state;simulation_sensor_state_t value;
    memcpy(&value,bytes,sizeof value);s->sample=value.sample;
    memcpy(s->filters,value.filters,sizeof s->filters);s->progress=value.progress;
    s->imu=value.imu;s->last_sensor_us=value.last_sensor_us;
}
int simulation_imu_calibration(void *state,const double *rotation,const double *bias)
{
    simulation_t *s=state;ainekio_imu_config_t cfg=ainekio_imu_default_config();
    for(unsigned i=0;i<9;i++)cfg.sensor_to_body[i]=(float)rotation[i];
    for(unsigned i=0;i<3;i++)cfg.gyro_bias_rad_s[i]=(float)bias[i];
    return ainekio_imu_init(&s->imu,&cfg);
}
int simulation_target(void *state,const double *target,const double *previous,double speed,double dt,double *out)
{
    simulation_t *s=state;ainekio_v2_frame_t goal={0},from={0},ramped;uint16_t pulses[12];
    for(unsigned j=0;j<12;j++){goal.position[j]=target[j]*100.;from.position[j]=previous[j]*100.;}
    if(!ainekio_p4_joint_fit_frame(s->mapping,&goal))return 0;
    if(!ainekio_p4_joint_ramp_frame(&from,goal.position,speed*100.,dt,&ramped))return 0;
    if(!ainekio_p4_joint_fit_frame(s->mapping,&ramped)||!ainekio_p4_joint_map_frame(s->mapping,&ramped,pulses))return 0;
    ainekio_p4_joint_unmap_frame(s->mapping,pulses,&ramped);
    for(unsigned j=0;j<12;j++){out[j]=ramped.position[j]/100.;out[12+j]=goal.position[j]/100.;}
    return 1;
}
/* Raw ADC samples already include the simulated transducer/noise/scan timing. */
unsigned simulation_feedback(void *state,const double *raw,const double *target,const double *timestamps,double *out)
{
    simulation_t *s=state;current=s;ainekio_v2_frame_t goal={0};uint16_t pulses[12];
    uint64_t latest=0;
    for(unsigned j=0;j<12;j++) {
        unsigned c=s->sample.config.joint[j].channel;
        if(timestamps[j]>latest)latest=(uint64_t)timestamps[j];
        goal.position[j]=target[j]*100.;
        if(!isfinite(raw[j])) {
            /* Same acquisition failure semantics as servo_feedback.c. */
            s->sample.valid_mask&=~(1U<<c);s->filters[c].initialized=false;
            out[j]=out[12+j]=out[24+j]=0.;
            continue;
        }
        ainekio_feedback_filter_update(&s->filters[c],raw[j],(int64_t)timestamps[j]);
        s->sample.raw[c]=(uint16_t)raw[j];s->sample.filtered_raw[c]=s->filters[c].position;
        s->sample.velocity_raw_s[c]=s->filters[c].velocity;s->sample.sampled_us[c]=(int64_t)timestamps[j];
        s->sample.valid_mask|=1U<<c;
        double pulse,neighbor;bool in_range,filtered_range,neighbor_range;
        ainekio_feedback_position(&s->sample.config.joint[j],raw[j],&pulse,&in_range);
        ainekio_feedback_position(&s->sample.config.joint[j],s->filters[c].position,&pulse,&filtered_range);
        ainekio_feedback_position(&s->sample.config.joint[j],s->filters[c].position+1.,&neighbor,&neighbor_range);
        double sign=s->mapping[j].invert?-1.:1.;
        out[j]=s->mapping[j].home_cd/100.+sign*(pulse-s->mapping[j].home_us)/s->mapping[j].us_per_degree;
        out[12+j]=sign*(neighbor-pulse)*s->filters[c].velocity/s->mapping[j].us_per_degree;
        out[24+j]=s->sample.config.enabled&&in_range&&filtered_range&&raw[j]>0&&raw[j]<4095;
    }
    s->sample.scan++;
    s->sample.scan_us=s->last_sensor_us && latest>=s->last_sensor_us?latest-s->last_sensor_us:0;
    s->last_sensor_us=latest;
    ainekio_p4_joint_map_frame(s->mapping,&goal,pulses);
    unsigned result=ainekio_p4_feedback_stalled(&s->progress,s->mapping,pulses);current=NULL;return result;
}
/* Reuse the endpoint/freshness rules, including calibrated endpoint noise. */
int simulation_arrival(void *state,const double *target,double commanded_us,double *out)
{
    simulation_t *s=state;current=s;
    ainekio_v2_frame_t goal={0};uint16_t pulses[12],remaining=0;
    for(unsigned j=0;j<12;j++)goal.position[j]=target[j]*100.;
    const bool mapped=ainekio_p4_joint_map_frame(s->mapping,&goal,pulses);
    const bool observed=mapped&&ainekio_p4_feedback_check(s->mapping,pulses,(int64_t)commanded_us,&remaining);
    ainekio_p4_feedback_health_t health;ainekio_p4_feedback_health(&s->sample,&health);
    out[0]=remaining;out[1]=health.calibrated;out[2]=health.unavailable;
    out[3]=health.clipped;out[4]=health.below_calibration;out[5]=health.above_calibration;
    current=NULL;return observed;
}
void simulation_imu(void *state,double now,const double *accel,const double *gyro,double *out)
{
    simulation_t *s=state;ainekio_imu_sample_t sample;uint8_t bytes[12];
    double sensor_accel[3],sensor_gyro[3];
    for(unsigned a=0;a<3;a++) {
        sensor_accel[a]=sensor_gyro[a]=0.;
        for(unsigned b=0;b<3;b++) {
            sensor_accel[a]+=s->imu.config.sensor_to_body[3*b+a]*accel[b];
            sensor_gyro[a]+=s->imu.config.sensor_to_body[3*b+a]*gyro[b];
        }
        sensor_accel[a]=sensor_accel[a]/s->imu.config.accel_scale[a]+s->imu.config.accel_bias_m_s2[a];
        sensor_gyro[a]+=s->imu.config.gyro_bias_rad_s[a];
    }
    /* Model digital acquisition: nearest count and signed-register saturation.
     * The existing estimator still rejects decoded samples outside its physical
     * configured range. Analog nonlinearity before a rail is not characterized. */
    for(unsigned a=0;a<6;a++) {
        const double value=a<3?sensor_gyro[a]:sensor_accel[a-3];
        const double unit=a<3?AINEKIO_LSM6DS3_GYRO_LSB_RAD_S:AINEKIO_LSM6DS3_ACCEL_LSB_M_S2;
        const int count=(int)fmax(-32768.,fmin(32767.,round(value/unit)));
        const uint16_t encoded=(uint16_t)count;
        bytes[2*a]=(uint8_t)encoded;bytes[2*a+1]=(uint8_t)(encoded>>8);
    }
    ainekio_imu_lsm6ds3_decode((uint64_t)now,bytes,&sample);
    ainekio_imu_update(&s->imu,&sample);
    ainekio_imu_observation_t obs;ainekio_imu_observe(&s->imu,sample.timestamp_us,&obs);
    for(unsigned a=0;a<4;a++)out[a]=obs.orientation_wxyz[a];
    for(unsigned a=0;a<3;a++){out[4+a]=obs.acceleration_m_s2[a];out[7+a]=obs.angular_rate_rad_s[a];}
    out[10]=obs.available;out[11]=obs.startup;out[12]=obs.gyro_recovery;out[13]=obs.acceleration_recovery;
}

/* Offline replay of WALK's production owners. No actuator or network owner.
 * Firmware saved-model admission and timestamp alignment remain gait_learning.c
 * responsibilities: optional features here must be explicit replay inputs. */
static bool simulation_walk_valid(const ainekio_v2_frame_t *frame,void *opaque)
{
    simulation_t *s=opaque;uint16_t pulses[12];
    return ainekio_p4_joint_map_frame(s->mapping,frame,pulses);
}
int simulation_walk_configure(void *state,const double *settings,const double *model,int supplied)
{
    simulation_t *s=state;
    if(!ainekio_v2_joint_speed_set(settings[0]))return 0;
    memset(&s->walk,0,sizeof s->walk);memset(&s->balance,0,sizeof s->balance);
    memset(&s->learning,0,sizeof s->learning);memset(&s->model,0,sizeof s->model);
    s->last_frame_us=0;s->speed=settings[0];s->heading_enabled=settings[1];s->balance_enabled=settings[2];
    s->tuning=(ainekio_v2_balance_tuning_t){settings[3],settings[4],settings[5],settings[6]};
    s->learning_amount=settings[7];s->model_supplied=supplied;
    if(supplied) {
        unsigned n=0;
        for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)for(unsigned k=0;k<5;k++)s->model.coefficient[l][a][k]=model[n++];
        for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)for(unsigned k=0;k<8;k++)s->model.feedback[l][a][k]=model[n++];
        for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)for(unsigned k=0;k<4;k++)s->model.command[l][a][k]=model[n++];
        s->model.gait.duty_delta=model[n++];s->model.gait.sweep_delta_mm=model[n++];
        for(unsigned l=0;l<4;l++)s->model.gait.phase_offset[l]=model[n++];
        for(unsigned l=0;l<4;l++)s->model.gait.lift_delta_mm[l]=model[n++];
        for(unsigned l=0;l<4;l++)for(unsigned a=0;a<2;a++)s->model.gait.landing_mm[l][a]=model[n++];
        for(unsigned a=0;a<3;a++)for(unsigned k=0;k<5;k++)s->model.gait.body_mm[a][k]=model[n++];
        if(!ainekio_v2_gait_profile_valid(&s->model.gait))return 0;
    }
    return 1;
}
int simulation_walk_accept(void *state,const char *json,double now_us)
{
    simulation_t *s=state;ainekio_control_message_t message;
    if(ainekio_control_decode_with_walk_controls(json,strlen(json),&message)!=AINEKIO_DECODE_OK)return 0;
    ainekio_v2_joint_speed_set(s->speed);
    const bool update=message.command.data.intent.data.walk.update_sequence!=0;
    if(!ainekio_v2_walk_accept(&s->walk,&message.command,update?s->walk.last_us:(uint64_t)now_us))return 0;
    if(!update) {
        s->last_frame_us=(uint64_t)now_us;memset(&s->learning,0,sizeof s->learning);
        if(s->model_supplied)ainekio_v2_walk_profile_begin(&s->walk,&s->model.gait);
    }
    return 1;
}
int simulation_walk_tick(void *state,double now_us,const double *previous,const double *features,int learning_usable,double *out)
{
    simulation_t *s=state;ainekio_imu_observation_t imu;
    ainekio_imu_observe(&s->imu,(uint64_t)now_us,&imu);
    const bool usable=imu.available&&imu.fresh&&!imu.startup&&!imu.gyro_recovery&&!imu.acceleration_recovery;
    const float *q=imu.orientation_wxyz;
    double yaw=atan2(2.*(q[0]*q[3]+q[1]*q[2]),1.-2.*(q[2]*q[2]+q[3]*q[3]));
    double old_phase=s->walk.phase,dt=(now_us-s->last_frame_us)/1e6;
    ainekio_v2_joint_speed_set(s->speed);
    if(!ainekio_v2_walk_feedback_tick(&s->walk,(uint64_t)now_us,s->heading_enabled,usable,yaw,simulation_walk_valid,s))return 0;
    ainekio_v2_frame_t from={0},frame;ainekio_v2_walk_pose_t balanced;
    for(unsigned j=0;j<12;j++)from.position[j]=previous[j]*100.;
    ainekio_v2_balance_configured_apply(&s->balance,q,imu.angular_rate_rad_s,s->balance_enabled&&usable,dt,
        &s->walk.pose,NULL,&from,s->speed,&balanced,&s->tuning,false);
    frame=balanced.frame;
    if(!ainekio_p4_joint_fit_frame(s->mapping,&frame))return 0;
    ainekio_v2_learning_input_t input={0};
    for(unsigned l=0;l<4;l++)for(unsigned k=0;k<8;k++)input.feature[l][k]=features[l*8+k];
    ainekio_v2_walk_command_features(&s->walk,input.command);
    ainekio_v2_frame_t applied;
    ainekio_v2_learning_policy_apply(&s->learning,&s->model,&input,s->walk.phase,s->walk.phase-old_phase,
        s->model_supplied&&learning_usable,s->learning_amount,&frame,simulation_walk_valid,s,&applied);
    uint16_t pulses[12];
    if(!ainekio_p4_joint_map_frame(s->mapping,&applied,pulses))return 0;
    ainekio_v2_frame_t mapped=applied;ainekio_p4_joint_unmap_frame(s->mapping,pulses,&mapped);
    for(unsigned j=0;j<12;j++) {
        out[j]=s->walk.pose.frame.position[j]/100.;out[12+j]=frame.position[j]/100.;
        out[24+j]=applied.position[j]/100.;out[36+j]=mapped.position[j]/100.;
    }
    out[48]=s->walk.phase;out[49]=s->walk.pose.run_blend;
    for(unsigned l=0;l<4;l++)out[50+l]=s->walk.pose.grounded[(l+2)%4];
    for(unsigned k=0;k<4;k++)out[54+k]=input.command[k];
    out[58]=s->walk.complete;out[59]=s->walk.stopping;out[60]=s->walk.failed;
    out[61]=s->walk.clock_scale;out[62]=s->walk.heading_active;out[63]=s->walk.heading_reduced;
    out[64]=s->balance.sensor_usable;out[65]=s->balance.reduced;out[66]=usable;
    out[67]=s->learning.blend;out[68]=s->learning.fit;
    out[69]=s->walk.command_sequence;out[70]=s->walk.latest_sequence;out[71]=s->walk.last_us;
    out[72]=s->walk.heading_error;out[73]=s->walk.feedback_turn;
    for(unsigned a=0;a<3;a++){out[74+a]=s->walk.pose.body[a];out[77+a]=s->walk.pose.euler[a];}
    s->last_frame_us=(uint64_t)now_us;return 1;
}

/* Read the estimator at observation time, including freshness. The synthetic
 * samples enter in known model body axes; the initialized identity rotation is
 * an explicit simulation frame, not evidence about the installed IMU mount. */
void simulation_imu_status(void *state,double now_us,double *out)
{
    simulation_t *s=state;ainekio_imu_observation_t imu;
    ainekio_imu_observe(&s->imu,(uint64_t)now_us,&imu);
    out[0]=imu.available;out[1]=imu.fresh;out[2]=imu.startup;
    out[3]=imu.gyro_recovery;out[4]=imu.acceleration_recovery;
    out[5]=s->imu.initialized;out[6]=imu.accelerometer_ignored;
    out[7]=imu.timestamp_us;out[8]=imu.age_us==UINT64_MAX?-1.:imu.age_us/1e6;
}

/* Logical targets remain integer requested microseconds. This separately
 * reports the oscillator/prescale-quantized electrical pulse and channel phase. */
int simulation_pwm(void *state,const double *target,double oscillator,double frequency,double *out)
{
    simulation_t *s=state;ainekio_v2_frame_t frame={0};uint16_t pulses[12];
    ainekio_pca9685_t timer={.config={.oscillator_hz=(uint32_t)oscillator,.frequency_hz=(uint16_t)frequency}};
    if(!ainekio_pca_config_prescale(&timer.config,&timer.prescale))return 0;
    for(unsigned j=0;j<12;j++)frame.position[j]=target[j]*100.;
    if(!ainekio_p4_joint_map_frame(s->mapping,&frame,pulses))return 0;
    const double tick_us=1e6*(timer.prescale+1U)/timer.config.oscillator_hz;
    for(unsigned j=0;j<12;j++) {
        const ainekio_p4_joint_config_t *m=&s->mapping[j];int ch=m->channel;
        out[51+j]=ch>=0;
        if(ch<0){out[j]=target[j];out[12+j]=out[24+j]=out[36+j]=0.;continue;}
        if(!ainekio_pca_pulse_valid(&timer,pulses[ch]))return 0;
        const double width=ainekio_pca_pulse_ticks(&timer,pulses[ch])*tick_us;
        out[j]=m->home_cd/100.+(m->invert?-1.:1.)*(width-m->home_us)/m->us_per_degree;
        out[12+j]=pulses[ch];out[24+j]=width;
        out[36+j]=ainekio_pca_channel_phase((unsigned)ch)*tick_us/1e6;
    }
    out[48]=4096.*tick_us/1e6;out[49]=tick_us;out[50]=timer.prescale;
    return 1;
}

static bool simulation_foot_valid(const ainekio_v2_frame_t *frame,void *opaque)
{
    const simulation_t *s=opaque;
    return ainekio_p4_joint_frame_in_travel(s->mapping,frame);
}
static bool simulation_foot_project(ainekio_v2_frame_t *frame,void *opaque)
{
    const simulation_t *s=opaque;
    return ainekio_p4_joint_fit_frame(s->mapping,frame);
}
void simulation_balance_configure(void *state,const double *settings)
{
    simulation_t *s=state;
    memset(&s->balance,0,sizeof s->balance);
    s->balance_enabled=settings[0];
    s->tuning=(ainekio_v2_balance_tuning_t){settings[1],settings[2],settings[3],settings[4]};
}
int simulation_foot_action_scale(void *state,const double *reference,const double *limits,double *out)
{
    simulation_t *s=state;ainekio_v2_frame_t nominal={0};
    float low[12],high[12],lower[4][3],upper[4][3];
    for(unsigned j=0;j<12;j++) {
        nominal.position[j]=reference[j]*100.;
        low[j]=nextafterf((float)(limits[2*j]*100.),-INFINITY);
        high[j]=nextafterf((float)(limits[2*j+1]*100.),INFINITY);
    }
    if(!ainekio_p4_joint_fit_frame(s->mapping,&nominal)||!simulation_foot_valid(&nominal,s)||
       !ainekio_v2_foot_offset_bounds(&nominal,low,high,lower,upper))return 0;
    for(unsigned axis=0;axis<3;axis++) {
        out[axis]=0.;
        for(unsigned leg=0;leg<4;leg++)out[axis]=fmax(out[axis],fmax(fabs(lower[leg][axis]),fabs(upper[leg][axis])));
        if(!isfinite(out[axis])||out[axis]<=0.)return 0;
    }
    return 1;
}
int simulation_foot_offsets_for_angles(void *state,const double *angles,const double *reference,double *out)
{
    simulation_t *s=state;ainekio_v2_frame_t target={0},nominal={0};
    float feet[4][3],origin[4][3];
    for(unsigned j=0;j<12;j++) {
        target.position[j]=angles[j]*100.;nominal.position[j]=reference[j]*100.;
    }
    /* Match the action decoder's fitted origin, but preserve the supplied
     * target exactly. An invalid linkage is an error, not a clipped label. */
    if(!ainekio_p4_joint_fit_frame(s->mapping,&nominal)||!simulation_foot_valid(&nominal,s)||
       ainekio_v2_feet_forward(&nominal,origin)!=15||ainekio_v2_feet_forward(&target,feet)!=15)return 0;
    for(unsigned leg=0;leg<4;leg++)for(unsigned axis=0;axis<3;axis++)
        out[3*leg+axis]=(double)feet[leg][axis]-origin[leg][axis];
    return 1;
}
int simulation_foot_target(void *state,const double *offsets,const double *reference,
    const double *previous,double speed,double dt,double now_us,double *out)
{
    simulation_t *s=state;ainekio_v2_frame_t nominal={0},from={0},goal,ramped;
    float desired[4][3],applied[4][3],leg_fit[4];uint16_t pulses[12];
    for(unsigned j=0;j<12;j++) {
        nominal.position[j]=reference[j]*100.;from.position[j]=previous[j]*100.;
        desired[j/3][j%3]=offsets[j];
    }
    if(!ainekio_p4_joint_fit_frame(s->mapping,&nominal)||!simulation_foot_valid(&nominal,s))return 0;
    ainekio_v2_walk_pose_t pose={0};double anchors[4][3];
    if(!ainekio_v2_nominal_foot_pose(&nominal,(const float (*)[3])desired,
        simulation_foot_valid,simulation_foot_project,s,&pose,anchors,applied,leg_fit))return 0;
    goal=pose.frame;float fit=1.;for(unsigned l=0;l<4;l++)fit=fminf(fit,leg_fit[l]);
    for(unsigned j=0;j<12;j++)out[53+j]=goal.position[j]/100.;
    out[65]=out[66]=out[68]=out[69]=0.;out[67]=1.;
    if(s->balance_enabled) {
        ainekio_v2_walk_pose_t balanced;
        ainekio_imu_observation_t imu;ainekio_imu_observe(&s->imu,(uint64_t)now_us,&imu);
        const bool usable=imu.available&&imu.fresh&&!imu.startup&&!imu.gyro_recovery&&!imu.acceleration_recovery;
        ainekio_v2_balance_configured_apply(&s->balance,imu.orientation_wxyz,imu.angular_rate_rad_s,
            usable,dt,&pose,(const double (*)[3])anchors,&from,speed,&balanced,&s->tuning,false);
        goal=balanced.frame;
        out[65]=s->balance.sensor_usable;out[66]=s->balance.reduced;
        out[67]=s->balance.applied_fraction;
        out[68]=s->balance.correction[0];out[69]=s->balance.correction[1];
    }
    if(!ainekio_p4_joint_fit_frame(s->mapping,&goal))return 0;
    if(!ainekio_p4_joint_ramp_frame(&from,goal.position,speed*100.,dt,&ramped))return 0;
    if(!ainekio_p4_joint_fit_frame(s->mapping,&ramped)||!ainekio_p4_joint_map_frame(s->mapping,&ramped,pulses))return 0;
    ainekio_p4_joint_unmap_frame(s->mapping,pulses,&ramped);
    for(unsigned j=0;j<12;j++) {
        out[j]=ramped.position[j]/100.;out[12+j]=goal.position[j]/100.;
        out[24+j]=applied[j/3][j%3];out[41+j]=nominal.position[j]/100.;
    }
    for(unsigned l=0;l<4;l++)out[36+l]=leg_fit[l];
    out[40]=fit;
    return 1;
}
