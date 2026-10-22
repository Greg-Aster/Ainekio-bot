/* Offline preview only. stdin: 12 mapping rows (channel invert home_us home_cd
 * us/degree), then 60 task-space coefficients and optional 12 min/max pairs. Args: amount, heading drift rad/s.
 * Optional args: amount drift v4 direction stride. In that mode read 237 model
 * floats (periodic, feedback, command, profile), then 32 fixed sensor features,
 * then optional envelope pairs. A final JSON command argument selects the
 * gait and steering through the production command decoder. This checks paths under a specified sensor
 * condition; it does not predict the robot's physical sensor response.
 * Emits calibrated pulse extrema; no robot/network access. */
#include "ainekio/v2_learning.h"
#include "ainekio/control_codec.h"
#include "joint_calibration.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
static ainekio_p4_joint_config_t mapping[12];
static unsigned envelope_low[12],envelope_high[12];
static uint16_t nominal[12];
static bool residual_valid(const ainekio_v2_frame_t *f,void *context)
{
    (void)context;uint16_t p[12];
    if(!ainekio_p4_joint_frame_in_travel(mapping,f)||!ainekio_p4_joint_map_frame(mapping,f,p))return false;
    for(unsigned j=0;j<12;j++) {
        unsigned low=envelope_low[j]<nominal[j]?envelope_low[j]:nominal[j];
        unsigned high=envelope_high[j]>nominal[j]?envelope_high[j]:nominal[j];
        if(p[j]<low||p[j]>high)return false;
    }
    return true;
}
static bool valid(const ainekio_v2_frame_t *f,void *context)
{(void)context;uint16_t p[12];return ainekio_p4_joint_map_frame(mapping,f,p);}
int main(int argc,char **argv)
{
    const bool policy=(argc==6||argc==7)&&!strcmp(argv[3],"v4");
    if(argc!=3&&!policy)return 2;
    float amount=strtof(argv[1],NULL);double drift=strtod(argv[2],NULL);
    for(unsigned j=0;j<12;j++) {
        int channel,invert,home,cd;float scale;
        if(scanf("%d%d%d%d%f",&channel,&invert,&home,&cd,&scale)!=5)return 2;
        mapping[j]=(ainekio_p4_joint_config_t){channel,invert,home,cd,scale};
    }
    ainekio_v2_learning_model_t model={0};
    for(unsigned i=0;i<60;i++)if(scanf("%f",((float *)model.coefficient)+i)!=1)return 2;
    ainekio_v2_learning_input_t input={0};
    if(policy) {
        for(unsigned i=0;i<96;i++)if(scanf("%f",((float *)model.feedback)+i)!=1)return 2;
        for(unsigned i=0;i<48;i++)if(scanf("%f",((float *)model.command)+i)!=1)return 2;
        _Static_assert(sizeof(model.gait)==33*sizeof(float),"Profile wire layout");
        for(unsigned i=0;i<33;i++)if(scanf("%f",((float *)&model.gait)+i)!=1)return 2;
        for(unsigned i=0;i<32;i++)if(scanf("%f",((float *)input.feature)+i)!=1)return 2;
        if(!ainekio_v2_gait_profile_valid(&model.gait))return 3;
    }
    bool explicit_envelope=true;
    for(unsigned j=0;j<12;j++)if(scanf("%u%u",&envelope_low[j],&envelope_high[j])!=2){explicit_envelope=false;break;}
    char wire[256];
    snprintf(wire,sizeof wire,"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"gait\":\"walk\",\"dir\":\"%s\",\"steps\":4,\"stride\":%s,\"rate\":2}",policy?argv[4]:"fwd",policy?argv[5]:"100");
    ainekio_control_message_t command;
    const char *requested=argc==7?argv[6]:wire;
    if(ainekio_control_decode_with_walk_controls(requested,strlen(requested),&command)!=AINEKIO_DECODE_OK)return 3;
    ainekio_v2_walk_state_t walk={0};ainekio_v2_learning_state_t learning={0};
    if(!ainekio_v2_walk_accept(&walk,&command.command,0))return 3;
    if(policy)ainekio_v2_walk_profile_begin(&walk,&model.gait);
    unsigned lo[12],hi[12]={0},base_lo[12],base_hi[12]={0},frames=0,reduced=0;
    for(unsigned j=0;j<12;j++)lo[j]=base_lo[j]=65535;
    /* No candidate envelope supplied: calculate it from the nominal run. */
    if(!explicit_envelope) {
        for(unsigned j=0;j<12;j++){envelope_low[j]=65535;envelope_high[j]=0;}
        ainekio_v2_walk_state_t baseline=walk;
        for(uint64_t now=20000;!baseline.complete;now+=20000) {
            if(!ainekio_v2_walk_feedback_tick(&baseline,now,true,true,drift*now/1e6,valid,NULL))return 4;
            ainekio_v2_frame_t frame=baseline.pose.frame;uint16_t p[12];
            if(!ainekio_p4_joint_fit_frame(mapping,&frame)||!ainekio_p4_joint_map_frame(mapping,&frame,p))return 6;
            for(unsigned j=0;j<12;j++){if(p[j]<envelope_low[j])envelope_low[j]=p[j];if(p[j]>envelope_high[j])envelope_high[j]=p[j];}
        }
    }
    double displacement=0,max_displacement=0;unsigned fitted=0;
    for(uint64_t now=20000;!walk.complete;now+=20000) {
        double phase=walk.phase;
        if(!ainekio_v2_walk_feedback_tick(&walk,now,true,true,drift*now/1e6,valid,NULL))return 4;
        ainekio_v2_frame_t frame,base_frame=walk.pose.frame;
        float before[4][3],after[4][3];
        if(ainekio_v2_feet_forward(&base_frame,before)!=15)return 7;
        if(!ainekio_p4_joint_fit_frame(mapping,&base_frame)||!ainekio_p4_joint_map_frame(mapping,&base_frame,nominal))return 6;
        if(ainekio_v2_feet_forward(&base_frame,after)!=15)return 7;
        if(memcmp(&base_frame,&walk.pose.frame,sizeof base_frame))fitted++;
        for(unsigned l=0;l<4;l++){double e=0;for(unsigned a=0;a<3;a++)e+=pow(after[l][a]-before[l][a],2);displacement+=e;if(sqrt(e)>max_displacement)max_displacement=sqrt(e);}
        bool usable=(policy||fabs(walk.stride_percent-100.)<.001)&&!walk.stopping&&!walk.complete;
        ainekio_v2_walk_command_features(&walk,input.command);
        ainekio_v2_learning_policy_apply(&learning,&model,policy?&input:NULL,walk.phase,walk.phase-phase,usable,amount,&base_frame,residual_valid,NULL,&frame);
        uint16_t pulse[12],base[12];
        if(!ainekio_p4_joint_map_frame(mapping,&frame,pulse)||!ainekio_p4_joint_map_frame(mapping,&base_frame,base))return 5;
        frames++;if(usable&&learning.fit<1)reduced++;
        for(unsigned j=0;j<12;j++) {
            if(pulse[j]<lo[j])lo[j]=pulse[j];if(pulse[j]>hi[j])hi[j]=pulse[j];
            if(base[j]<base_lo[j])base_lo[j]=base[j];if(base[j]>base_hi[j])base_hi[j]=base[j];
        }
    }
    fprintf(stderr,"Fitted frames %u/%u, reference displacement RMS %.3f mm max %.3f mm\n",fitted,frames,sqrt(displacement/(4*frames)),max_displacement);
    printf("{\"frames\":%u,\"reduced_frames\":%u,\"fixed_sensor_input\":%s,\"joints\":[",frames,reduced,policy?"true":"false");
    for(unsigned j=0;j<12;j++)printf("%s{\"id\":%u,\"baseline\":[%u,%u],\"candidate\":[%u,%u]}",j?",":"",j,base_lo[j],base_hi[j],lo[j],hi[j]);
    puts("]}");return 0;
}
