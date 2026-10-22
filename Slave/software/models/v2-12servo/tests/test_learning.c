#include "ainekio/v2_learning.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static bool reject(const ainekio_v2_frame_t *f,void *p){(void)f;(void)p;return false;}
static bool hold_first_leg(const ainekio_v2_frame_t *f,void *p)
{return !memcmp(f->position,((ainekio_v2_frame_t *)p)->position,3*sizeof(float));}
int main(void)
{
    const char wire[]="{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"gait\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"stride\":100,\"rate\":2}";
    ainekio_control_message_t command;assert(ainekio_control_decode_with_walk_controls(wire,strlen(wire),&command)==AINEKIO_DECODE_OK);
    ainekio_v2_walk_state_t walk={0};assert(ainekio_v2_walk_accept(&walk,&command.command,0));
    ainekio_v2_learning_model_t model={0};
    for(unsigned l=0;l<4;l++){model.coefficient[l][0][1]=.8f;model.coefficient[l][2][2]=.4f;}
    ainekio_v2_learning_state_t state={0};unsigned moved=0;
    for(uint64_t t=20000;t<12000000;t+=20000) {
        double previous=walk.phase;assert(ainekio_v2_walk_tick(&walk,t));
        const ainekio_v2_frame_t nominal=walk.pose.frame;
        float before[4][3],after[4][3];assert(ainekio_v2_feet_forward(&nominal,before)==15);
        ainekio_v2_frame_t corrected;
        ainekio_v2_learning_apply(&state,&model,walk.phase,walk.phase-previous,true,1,&nominal,NULL,NULL,&corrected);
        assert(ainekio_v2_feet_forward(&corrected,after)==15);
        for(unsigned l=0;l<4;l++)for(unsigned a=0;a<3;a++) {
            assert(fabs(after[l][a]-before[l][a]-state.applied[l][a])<.002);
            if(fabs(state.applied[l][a])>.1)moved++;
        }
        assert(!memcmp(&walk.pose.frame,&nominal,sizeof nominal));
        ainekio_v2_learning_state_t off={0};
        ainekio_v2_learning_apply(&off,&model,walk.phase,.01,false,1,&nominal,NULL,NULL,&corrected);
        assert(!memcmp(&nominal,&corrected,sizeof nominal));
    }
    assert(moved>100);
    ainekio_v2_frame_t corrected;
    float start=state.blend;
    for(unsigned n=0;n<500;n++)ainekio_v2_learning_apply(&state,&model,walk.phase,.02,false,1,&walk.pose.frame,NULL,NULL,&corrected);
    assert(start>.9&&state.blend==0);assert(!memcmp(&corrected,&walk.pose.frame,sizeof corrected));
    ainekio_v2_learning_apply(&state,&model,walk.phase,1,true,1,&walk.pose.frame,reject,NULL,&corrected);
    assert(state.fit==0);assert(!memcmp(&corrected,&walk.pose.frame,sizeof corrected));
    /* An unavailable correction for one leg must not remove the others. */
    memset(&model,0,sizeof model);
    for(unsigned l=0;l<4;l++)model.coefficient[l][0][0]=.5f;
    ainekio_v2_learning_apply(&state,&model,walk.phase,1,true,1,&walk.pose.frame,hold_first_leg,&walk.pose.frame,&corrected);
    assert(state.leg_fit[0]<.01f);
    for(unsigned l=1;l<4;l++)assert(state.leg_fit[l]>.99f&&state.applied[l][0]>.4f);
    /* Same gait phase, different measured state: the policy must actually
     * change its target, without changing the base gait or sensor signs. */
    memset(&model,0,sizeof model);memset(&state,0,sizeof state);
    float errors[4][3]={{10,-5,2},{0}};
    const float angle=.04f,q[4]={cosf(angle/2),sinf(angle/2),0,0},rate[3]={.2f,-.3f,.4f};
    const double target[2]={.01,-.02};
    ainekio_v2_learning_input_t input;
    ainekio_v2_learning_features((const float (*)[3])errors,q,target,rate,&input);
    assert(fabs(input.feature[0][0]-1)<1e-6&&fabs(input.feature[0][1]+.5)<1e-6);
    assert(fabs(input.feature[0][3]+.3)<1e-6&&fabs(input.feature[0][4]+.2)<1e-6);
    assert(fabs(input.feature[0][5]-.2)<1e-6&&fabs(input.feature[3][7]-.4)<1e-6);
    model.feedback[0][0][0]=.2f;
    model.feedback[0][2][3]=.2f;
    ainekio_v2_learning_policy_apply(&state,&model,&input,walk.phase,4,true,1,&walk.pose.frame,NULL,NULL,&corrected);
    float before[4][3],after[4][3];
    assert(ainekio_v2_feet_forward(&walk.pose.frame,before)==15&&ainekio_v2_feet_forward(&corrected,after)==15);
    assert(fabs(after[0][0]-before[0][0]-.2)<.002&&fabs(after[0][2]-before[0][2]+.06)<.002);
    input.feature[0][0]=-1;
    ainekio_v2_learning_policy_apply(&state,&model,&input,walk.phase,.02,true,1,&walk.pose.frame,NULL,NULL,&corrected);
    assert(ainekio_v2_feet_forward(&corrected,after)==15);
    assert(fabs(after[0][0]-before[0][0]+.2)<.002);
    /* Sensor loss fades the last usable sensor response; it must not zero the
     * features abruptly or evaluate fabricated replacement measurements. */
    float prior=state.applied[0][0];memset(&input,0,sizeof input);
    ainekio_v2_learning_policy_apply(&state,&model,&input,walk.phase,.02,false,1,&walk.pose.frame,NULL,NULL,&corrected);
    assert(state.applied[0][0]<0&&state.applied[0][0]>prior&&fabs(state.applied[0][0]/prior-exp(-.02/.25))<1e-5);
    for(unsigned n=0;n<500;n++)ainekio_v2_learning_policy_apply(&state,&model,NULL,walk.phase,.02,false,1,&walk.pose.frame,NULL,NULL,&corrected);
    assert(state.blend==0&&!memcmp(&corrected,&walk.pose.frame,sizeof corrected));
    puts("Learning: fixed-shaft FK/IK agreement, exact disabled parity, unchanged nominal path, correction fade and rejection passed");
}
