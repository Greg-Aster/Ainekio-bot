#include "ainekio/v2_learning.h"
#include <math.h>
#include <string.h>
void ainekio_v2_learning_basis(double phase,double b[5])
{
    double t=6.2831853071795864769*phase;
    b[0]=1.;b[1]=sin(t);b[2]=cos(t);b[3]=sin(2.*t);b[4]=cos(2.*t);
}
bool ainekio_v2_nominal_foot_pose(const ainekio_v2_frame_t *reference,
    const float desired[4][3],bool (*valid)(const ainekio_v2_frame_t *,void *),
    void *context,ainekio_v2_walk_pose_t *pose,double anchors[4][3],
    float applied[4][3],float leg_fit[4])
{
    if(!reference||!desired||!pose||!anchors||!applied||!leg_fit)return false;
    for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)if(!isfinite(desired[l][a]))return false;
    if(valid&&!valid(reference,context))return false;
    ainekio_v2_frame_t goal;
    ainekio_v2_learning_offsets_apply(desired,reference,valid,context,&goal,applied,leg_fit);
    *pose=(ainekio_v2_walk_pose_t){0};
    ainekio_v2_pose_from_frame(pose,&goal);
    return ainekio_v2_contact_forward(pose,anchors,true);
}
void ainekio_v2_learning_features(const float error_mm[4][3],const float q[4],
    const double target[2],const float rate[3],ainekio_v2_learning_input_t *input)
{
    memset(input,0,sizeof *input);
    const double w=q[0],x=q[1],y=q[2],z=q[3];
    const double roll=atan2(2.*(w*x+y*z),1.-2.*(x*x+y*y));
    const double pitch=asin(fmax(-1.,fmin(1.,2.*(w*y-z*x))));
    for(unsigned l=0;l<4;l++) {
        for(unsigned a=0;a<3;a++)input->feature[l][a]=error_mm[l][a]/10.f;
        input->feature[l][3]=(target[0]-roll)/.1;
        input->feature[l][4]=(target[1]-pitch)/.1;
        for(unsigned a=0;a<3;a++)input->feature[l][5+a]=rate[a];
    }
}
float ainekio_v2_learning_offsets_apply(const float desired[4][3],
    const ainekio_v2_frame_t *nominal,bool (*valid)(const ainekio_v2_frame_t *,void *),
    void *context,ainekio_v2_frame_t *output,float applied[4][3],float leg_fit[4])
{
    *output=*nominal;float fit=1;memset(applied,0,12*sizeof(float));
    for(unsigned l=0;l<4;l++) {
        leg_fit[l]=1;
        if(desired[l][0]==0&&desired[l][1]==0&&desired[l][2]==0)continue;
        bool accepted=false;
        for(unsigned attempt=0;attempt<13;attempt++) {
            float scale=ldexpf(1.f,-(int)attempt),candidate[4][3]={{0}};
            for(unsigned a=0;a<3;a++)candidate[l][a]=desired[l][a]*scale;
            ainekio_v2_frame_t frame;
            if(ainekio_v2_feet_offset(output,(const float (*)[3])candidate,&frame)&&(!valid||valid(&frame,context))) {
                *output=frame;memcpy(applied[l],candidate[l],sizeof candidate[l]);leg_fit[l]=scale;accepted=true;break;
            }
        }
        if(!accepted)leg_fit[l]=0;
        fit=fminf(fit,leg_fit[l]);
    }
    return fit;
}
void ainekio_v2_learning_policy_apply(ainekio_v2_learning_state_t *s,
    const ainekio_v2_learning_model_t *m,const ainekio_v2_learning_input_t *input,
    double phase,double dp,bool usable,float amount,
    const ainekio_v2_frame_t *nominal,bool (*valid)(const ainekio_v2_frame_t *,void *),
    void *context,ainekio_v2_frame_t *output)
{
    /* Fade only the optional residual. Nominal motion never waits for feedback. */
    float goal=usable?amount:0.f;
    s->blend+=(goal-s->blend)*(float)(-expm1(-fmax(0.,dp)/.25));
    if(!usable && fabsf(s->blend)<1e-6f)s->blend=0;
    double b[5];ainekio_v2_learning_basis(phase,b);
    float desired[4][3]={{0}};
    if(usable) {
        memset(s->feedback_residual,0,sizeof s->feedback_residual);
        if(m&&input)for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)
            for(unsigned k=0;k<AINEKIO_LEARNING_FEEDBACK_TERMS;k++)
                s->feedback_residual[l][a]+=m->feedback[l][a][k]*input->feature[l][k];
        if(m&&input)for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++)
            for(unsigned k=0;k<AINEKIO_LEARNING_COMMAND_TERMS;k++)
                s->feedback_residual[l][a]+=m->command[l][a][k]*input->command[k];
    }
    if(m)for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++) {
        desired[l][a]=s->blend*s->feedback_residual[l][a];
        for(unsigned k=0;k<5;k++)desired[l][a]+=(float)(s->blend*m->coefficient[l][a][k]*b[k]);
    }
    s->fit=ainekio_v2_learning_offsets_apply((const float (*)[3])desired,nominal,valid,
        context,output,s->applied,s->leg_fit);
}
void ainekio_v2_learning_apply(ainekio_v2_learning_state_t *s,
    const ainekio_v2_learning_model_t *m,double phase,double dp,bool usable,float amount,
    const ainekio_v2_frame_t *nominal,bool (*valid)(const ainekio_v2_frame_t *,void *),
    void *context,ainekio_v2_frame_t *output)
{
    ainekio_v2_learning_policy_apply(s,m,NULL,phase,dp,usable,amount,nominal,valid,context,output);
}
