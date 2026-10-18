#include "ainekio/v2_balance.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "ainekio/v2_limits.h"

/* A planted body with a constant attitude disturbance. The ideal actuator
 * follows each solved pose; this isolates feedback error from motor loading. */
static void standing_rejects_persistent_tilt(void)
{
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2) {
        ainekio_v2_walk_pose_t nominal,output;
        double anchors[4][3];
        assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
        assert(ainekio_v2_contact_forward(&nominal,anchors,true));
        ainekio_v2_balance_t s={0};
        ainekio_v2_frame_t previous=nominal.frame;
        double measured=sign*.08,rate=0.;
        for(unsigned i=0;i<200;i++) {
            float q[4]={(float)cos(measured*.5),0,0,0},rates[3]={0};
            q[axis+1]=(float)sin(measured*.5);rates[axis]=(float)rate;
            ainekio_v2_balance_hold_apply(&s,q,rates,true,.02,&nominal,
                (const double (*)[3])anchors,&previous,1000,&output);
            double next=sign*.08+output.euler[axis];
            rate=(next-measured)/.02;measured=next;previous=output.frame;
        }
        printf("Standing residual axis=%u sign=%d: %.6f rad\n",axis,sign,measured);
        fflush(stdout);
        assert(fabs(measured)<.005);
    }
}

static void standing_extension_and_release(void)
{
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2) {
        ainekio_v2_walk_pose_t nominal,output,relative,start;
        double anchors[4][3];
        assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
        assert(ainekio_v2_contact_forward(&nominal,anchors,true));
        start=nominal;memset(start.body,0,sizeof start.body);memset(start.euler,0,sizeof start.euler);
        assert(ainekio_v2_contact_forward(&start,anchors,false));
        ainekio_v2_balance_t s={0};
        ainekio_v2_frame_t previous=nominal.frame;
        float q[4]={(float)cos(.1),0,0,0},rates[3]={0};q[axis+1]=sign*(float)sin(.1);
        double initial=0.;unsigned reduced=0;
        for(unsigned i=0;i<400;i++) {
            double before=s.correction[axis];
            ainekio_v2_balance_hold_apply(&s,q,rates,true,.02,&nominal,
                (const double (*)[3])anchors,&previous,1000,&output);
            assert(sign*s.correction[axis]<=sign*before+1e-10);
            assert(isfinite(s.correction[axis]));
            for(unsigned j=0;j<12;j++)assert(fabs(output.frame.position[j]-previous.position[j])<=2000.01);
            if(s.reduced)reduced++;
            previous=output.frame;
            if(i==24)initial=fabs(s.correction[axis]);
        }
        /* Held tilt must progress beyond the old 0.08 rad response and retain
         * that compensation at the reachable boundary instead of resetting. */
        assert(initial>.08 && fabs(s.correction[axis])>=initial);
        assert(reduced>0);
        relative=output;memset(relative.body,0,sizeof relative.body);memset(relative.euler,0,sizeof relative.euler);
        assert(ainekio_v2_contact_forward(&relative,anchors,false));
        for(unsigned l=0;l<4;l++) {
            /* Source order front-left/right, rear-left/right. Nose up (negative
             * pitch) must extend the rear; left up must extend the right. */
            bool extends=axis==1 ? ((l>=2)==(sign<0)) : ((l%2==1)==(sign>0));
            double extension=start.feet[l][2]-relative.feet[l][2];
            assert(extends ? extension>1. : extension< -1.);
        }
        printf("Standing axis=%u sign=%d accepted %.2f deg; rear extensions %.2f / %.2f mm\n",
            axis,sign,s.correction[axis]*180./acos(-1.),
            start.feet[2][2]-relative.feet[2][2],start.feet[3][2]-relative.feet[3][2]);
        /* Reversing the disturbance must immediately reverse the correction;
         * held unreachable demand must not leave an accumulated backlog. */
        q[axis+1]=-q[axis+1];
        double before=s.correction[axis];
        ainekio_v2_balance_hold_apply(&s,q,rates,true,.02,&nominal,
            (const double (*)[3])anchors,&previous,1000,&output);
        assert(sign*(s.correction[axis]-before)>0.);
        previous=output.frame;
        /* With no remaining error, retain the achieved extension. */
        q[0]=1.;q[axis+1]=0.;before=s.correction[axis];
        for(unsigned i=0;i<20;i++) {
            ainekio_v2_balance_hold_apply(&s,q,rates,true,.02,&nominal,
                (const double (*)[3])anchors,&previous,1000,&output);
            assert(s.correction[axis]==before);previous=output.frame;
        }
        for(unsigned i=0;i<400;i++) {
            double magnitude=fabs(s.correction[axis]);
            ainekio_v2_balance_hold_apply(&s,q,rates,false,.02,&nominal,
                (const double (*)[3])anchors,&previous,1000,&output);
            assert(fabs(s.correction[axis])<=magnitude+1e-10);previous=output.frame;
        }
        assert(fabs(s.correction[axis])<1e-7);
    }
}

static void standing_uses_existing_joint_speed(void)
{
    ainekio_v2_walk_pose_t nominal,output;
    double anchors[4][3];
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
    assert(ainekio_v2_contact_forward(&nominal,anchors,true));
    ainekio_v2_balance_t s={0};ainekio_v2_frame_t previous=nominal.frame;
    const float q[4]={(float)cos(.1),0,-(float)sin(.1),0},rate[3]={0};
    for(unsigned i=0;i<200;i++) {
        ainekio_v2_balance_hold_apply(&s,q,rate,true,.02,&nominal,
            (const double (*)[3])anchors,&previous,3,&output);
        for(unsigned j=0;j<12;j++)assert(fabs(output.frame.position[j]-previous.position[j])<=6.01);
        previous=output.frame;
    }
    assert(s.correction[1]>.02);
}

static void adjustable_response(void)
{
    ainekio_v2_walk_pose_t nominal,out;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
    const float tilt[4]={(float)cos(.0025),(float)sin(.0025),0,0},still[3]={0},level[4]={1,0,0,0},rate[3]={.01F,0,0};
    for(unsigned hold=0;hold<2;hold++) {
        ainekio_v2_balance_t base={0},strong={0},damped={0};
        ainekio_v2_balance_tuning_t t=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
        ainekio_v2_balance_configured_apply(&base,tilt,still,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
        t.strength=2;
        ainekio_v2_balance_configured_apply(&strong,tilt,still,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
        assert(base.applied_fraction==1. && strong.applied_fraction==1.);
        assert(fabs(strong.correction[0]-2.*base.correction[0])<1e-10);
        base=(ainekio_v2_balance_t){0};t=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
        ainekio_v2_balance_configured_apply(&base,level,rate,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
        t.damping=2;
        ainekio_v2_balance_configured_apply(&damped,level,rate,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
        assert(base.correction[0]<0. && fabs(damped.correction[0]-2.*base.correction[0])<1e-10);
        /* Positive user roll raises the left side; positive pitch raises nose
         * (negative Euler pitch in the right-handed x-forward/y-left frame). */
        for(unsigned axis=0;axis<2;axis++) {
            t=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
            if(axis==0)t.roll_deg=.5F;else t.pitch_deg=.5F;
            base=(ainekio_v2_balance_t){0};
            ainekio_v2_balance_configured_apply(&base,level,still,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
            assert(axis==0 ? base.correction[0]>0. : base.correction[1]<0.);
            float q[4]={(float)cos(.5*.017453292519943295/2),0,0,0};
            q[axis+1]=(axis==0?1:-1)*(float)sin(.5*.017453292519943295/2);
            base=(ainekio_v2_balance_t){0};
            ainekio_v2_balance_configured_apply(&base,q,still,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
            assert(fabs(base.correction[axis])<1e-8);
        }
        t=(ainekio_v2_balance_tuning_t){0};base=(ainekio_v2_balance_t){0};
        ainekio_v2_balance_configured_apply(&base,tilt,rate,true,.02,&nominal,NULL,&nominal.frame,1000,&out,&t,hold);
        assert(base.correction[0]==0. && base.correction[1]==0.);
    }
}


/* Exercise physical sides, not just the sign of the controller's scalar. */
static void roll_corrects_physical_sides(void)
{
    for(unsigned hold=0;hold<2;hold++)for(int polarity=-1;polarity<=1;polarity+=2)
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2) {
        ainekio_v2_walk_pose_t nominal,out,start,actual;
        double anchors[4][3];
        assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
        assert(ainekio_v2_contact_forward(&nominal,anchors,true));
        ainekio_v2_balance_t b={0};
        const ainekio_v2_balance_tuning_t t=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
        float q[4]={cosf(.05F),0,0,0},rate[3]={0};
        q[axis+1]=sign*sinf(.05F);
        ainekio_v2_balance_response_apply(&b,q,rate,true,.02,&nominal,
            (const double (*)[3])anchors,&nominal.frame,1000,&out,&t,hold,polarity);
        start=nominal;actual=out;
        memset(start.euler,0,sizeof start.euler);memset(actual.euler,0,sizeof actual.euler);
        memset(start.body,0,sizeof start.body);memset(actual.body,0,sizeof actual.body);
        assert(ainekio_v2_contact_forward(&start,anchors,false));
        assert(ainekio_v2_contact_forward(&actual,anchors,false));
        for(unsigned l=0;l<4;l++) {
            double extension=start.feet[l][2]-actual.feet[l][2];
            /* Physical FL,FR,RL,RR: reversed response extends raised side. */
            int expected=axis==0 ? (l%2 ? sign : -sign) : (l<2 ? sign : -sign);
            assert(polarity*expected*extension>0.);
        }
    }
}
static void response_polarity_preserves_reference(void)
{
    ainekio_v2_walk_pose_t nominal,out;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
    for(unsigned hold=0;hold<2;hold++) {
        ainekio_v2_balance_t a={0},b={0};
        ainekio_v2_balance_tuning_t t=AINEKIO_V2_BALANCE_TUNING_DEFAULT;
        const float level[4]={1,0,0,0},rates[3]={.01F,.01F,0},still[3]={0};
        ainekio_v2_balance_response_apply(&a,level,rates,true,.02,&nominal,NULL,
            &nominal.frame,1000,&out,&t,hold,1.);
        ainekio_v2_balance_response_apply(&b,level,rates,true,.02,&nominal,NULL,
            &nominal.frame,1000,&out,&t,hold,-1.);
        assert(a.applied_fraction==1. && b.applied_fraction==1.);
        assert(fabs(a.correction[0]+b.correction[0])<1e-10);
        assert(fabs(a.correction[1]+b.correction[1])<1e-10);
        t.roll_deg=3.;
        const float q[4]={cosf(.02617993878F),sinf(.02617993878F),0,0};
        b=(ainekio_v2_balance_t){0};
        ainekio_v2_balance_response_apply(&b,q,still,true,.02,&nominal,NULL,
            &nominal.frame,1000,&out,&t,hold,-1.);
        assert(fabs(b.correction[0])<1e-8);
        assert(b.measured[0]>.05); /* Raw reading keeps its sign. */
    }
}
static void measured_joint_tracking(void)
{
    ainekio_v2_walk_pose_t pose;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&pose));
    const ainekio_v2_frame_t target=pose.frame;
    ainekio_v2_frame_t measured=target,previous=target,out;
    ainekio_v2_balance_tracking_t t;
    ainekio_v2_balance_track(&target,&measured,&previous,.02,2000,&out,&t);
    assert(!memcmp(&out,&target,sizeof out) && !t.reduced);
    /* A persistent half-degree tracking error receives a quarter-degree trim,
     * never another quarter-degree per tick. Opposite errors are independent. */
    measured.position[1]-=50;measured.position[4]+=50;
    for(unsigned n=0;n<100;n++) {
        ainekio_v2_balance_track(&target,&measured,&previous,.02,2000,&out,&t);
        assert(!t.reduced && ainekio_v2_limits_frame(&out));
        assert(fabs(t.error_deg[1]-.5)<1e-5 && fabs(t.trim_deg[1]-.25)<1e-5);
        assert(fabs(t.trim_deg[4]+.25)<1e-5);
        previous=out;
    }
    /* One-frame actuator delay: no perpetual corrective oscillation. */
    for(unsigned n=0;n<30;n++) {
        measured=previous;
        ainekio_v2_balance_track(&target,&measured,&previous,.02,2000,&out,&t);
        previous=out;
    }
    assert(fabs(out.position[1]-target.position[1])<.01);
    /* A very large error cannot replace the valid target with an impossible
     * closure. Existing correction-only reduction reports the actual fraction. */
    measured=target;measured.position[1]-=30000;
    ainekio_v2_balance_track(&target,&measured,&target,.02,2000,&out,&t);
    assert(t.reduced && t.applied_fraction<1. && ainekio_v2_limits_frame(&out));
}

int main(void)
{
    ainekio_v2_walk_pose_t nominal,output;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&nominal));
    const float tilted[4]={(float)cos(.05),(float)sin(.05),0,0},still[3]={0};
    ainekio_v2_balance_t s={0};
    ainekio_v2_frame_t previous=nominal.frame;
    for(unsigned i=0;i<100;i++) {
        ainekio_v2_balance_apply(&s,tilted,still,true,.02,&nominal,NULL,&previous,1000,&output);
        assert(s.sensor_usable && s.correction[0]<0. && fabs(s.correction[1])<1e-9);
        for(unsigned l=0;l<4;l++)for(unsigned j=0;j<3;j++)assert(output.feet[l][j]==nominal.feet[l][j]);
        previous=output.frame;
    }
    assert(fabs(s.measured[0]-.1)<1e-6 && s.correction[0]<-.039);
    double before=fabs(s.correction[0]);
    for(unsigned i=0;i<200;i++) {
        ainekio_v2_balance_apply(&s,tilted,still,false,.02,&nominal,NULL,&previous,1000,&output);
        assert(!s.sensor_usable && fabs(s.correction[0])<=before+1e-12);
        before=fabs(s.correction[0]);previous=output.frame;
    }
    assert(before<1e-7);
    s=(ainekio_v2_balance_t){0};previous=nominal.frame;
    ainekio_v2_balance_apply(&s,tilted,still,true,.02,&nominal,NULL,&previous,.1,&output);
    assert(s.reduced && s.applied_fraction<1.);
    for(unsigned j=0;j<12;j++)assert(fabs(output.frame.position[j]-previous.position[j])<=.21);
    const float level[4]={1,0,0,0},turning[3]={0,.3,0};
    s=(ainekio_v2_balance_t){0};
    ainekio_v2_balance_apply(&s,level,turning,true,.02,&nominal,NULL,&nominal.frame,1000,&output);
    assert(s.correction[1]<0.);
    roll_corrects_physical_sides();
    response_polarity_preserves_reference();
    measured_joint_tracking();
    adjustable_response();
    standing_rejects_persistent_tilt();
    standing_extension_and_release();
    standing_uses_existing_joint_speed();
    puts("Balance: tilt direction, rate damping, stale fade, anchors and shared speed limit passed");
    return 0;
}
