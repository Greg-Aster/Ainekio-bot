/* Host-only linkage regression checks; no data or calculations enter firmware. */
#ifndef V2_TEST_LEVERAGE_CHECKS_H
#define V2_TEST_LEVERAGE_CHECKS_H
#include "walk_data.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static double leverage_min[2][2]={{180,180},{180,180}};
static double leverage_clearance=INFINITY;
static unsigned leverage_poses;
static void leverage_leg(const double q[3],bool grounded,double branch[2])
{
    double a=V2_ALPHA_ZERO+q[1],t=V2_THETA_ZERO+q[2];
    double dx=V2_O_X+V2_PRIMARY*cos(a),dz=V2_O_Z+V2_PRIMARY*sin(a);
    double px=V2_C_X+V2_INPUT*cos(t),pz=V2_C_Z+V2_INPUT*sin(t);
    double wx=px-dx,wz=pz-dz,d=hypot(wx,wz);
    assert(isfinite(d)&&d>fabs(V2_ROD-V2_PICKUP)&&d<V2_ROD+V2_PICKUP);
    double along=(V2_PICKUP*V2_PICKUP-V2_ROD*V2_ROD+d*d)/(2*d);
    double h=V2_BRANCH*sqrt(V2_PICKUP*V2_PICKUP-along*along);
    double ex=dx+(along*wx-h*wz)/d,ez=dz+(along*wz+h*wx)/d;
    double rx=ex-px,rz=ez-pz;
    double ox=ex-dx,oz=ez-dz,cx=px-V2_C_X,cz=pz-V2_C_Z;
    branch[0]=wx*oz-wz*ox;branch[1]=(ex-V2_C_X)*cz-(ez-V2_C_Z)*cx;
    double output=acos(fmin(1.,fabs(rx*ox+rz*oz)/(V2_ROD*V2_PICKUP)))*57.29577951308232;
    double input=acos(fmin(1.,fabs(rx*cx+rz*cz)/(V2_ROD*V2_INPUT)))*57.29577951308232;
    unsigned state=grounded?0:1;
    leverage_min[state][0]=fmin(leverage_min[state][0],output);
    leverage_min[state][1]=fmin(leverage_min[state][1],input);
    leverage_clearance=fmin(leverage_clearance,V2_ROD+V2_PICKUP-d);
    /* Regression floors across all supported gaits, not measured torque limits.
     * Crawl folds more tightly; zero acute angle would also be a folded toggle. */
    assert(output >= (grounded ? V2_CHECK_STANCE_OUTPUT_MIN_DEG : V2_CHECK_SWING_OUTPUT_MIN_DEG));
    assert(input >= (grounded ? V2_CHECK_STANCE_INPUT_MIN_DEG : V2_CHECK_SWING_INPUT_MIN_DEG));
    assert(V2_ROD+V2_PICKUP-d >= V2_CHECK_STRAIGHTENING_CLEARANCE_MIN_MM);
    leverage_poses++;
}
static void leverage_step(const ainekio_v2_walk_pose_t *old,const ainekio_v2_walk_pose_t *pose)
{
    for(unsigned leg=0;leg<4;leg++) {
        double previous[2],current[2],middle[2],q[3];
        leverage_leg(old->joints[leg],old->grounded[leg],previous);
        leverage_leg(pose->joints[leg],pose->grounded[leg],current);
        for(unsigned j=0;j<3;j++)q[j]=(old->joints[leg][j]+pose->joints[leg][j])*.5;
        leverage_leg(q,old->grounded[leg]||pose->grounded[leg],middle);
        for(unsigned j=0;j<2;j++)assert(previous[j]*current[j]>0&&previous[j]*middle[j]>0);
    }
}
static void leverage_report(void)
{
    printf("Leverage: %u leg poses; stance output/input %.6f/%.6f deg; swing %.6f/%.6f deg; straightening clearance %.6f mm.\n",
        leverage_poses,leverage_min[0][0],leverage_min[0][1],leverage_min[1][0],leverage_min[1][1],leverage_clearance);
}
#endif
