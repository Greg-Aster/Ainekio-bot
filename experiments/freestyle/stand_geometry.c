/* Offline training exporter. Link the production posture/contact/mapping code;
 * never duplicate IK or silently clamp a teacher label in Python. */
#include "ainekio/v2_posture.h"
#include "joint_calibration.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

static ainekio_p4_joint_config_t mapping[12];
static double largest_fit_delta;
static bool sweep_mode;
static bool fit(ainekio_v2_frame_t *frame,void *context)
{
    (void)context;ainekio_v2_frame_t before=*frame;uint16_t pulses[12];
    if(!ainekio_p4_joint_fit_frame(mapping,frame))return false;
    for(unsigned j=0;j<12;j++)largest_fit_delta=fmax(largest_fit_delta,fabs(frame->position[j]-before.position[j])/100.);
    return ainekio_p4_joint_map_frame(mapping,frame,pulses) && ainekio_p4_joint_frame_in_travel(mapping,frame);
}
static void array(const double *values,unsigned n)
{
    putchar('[');for(unsigned i=0;i<n;i++)printf("%s%.9g",i?",":"",values[i]);putchar(']');
}
static void print_pose(const ainekio_v2_walk_pose_t *pose)
{
    double degrees[12],sole[4],feet[12];
    for(unsigned j=0;j<12;j++)degrees[j]=pose->frame.position[j]/100.;
    for(unsigned l=0;l<4;l++) {
        unsigned source=(l+2)%4;sole[l]=pose->sole_height[source];
        for(unsigned axis=0;axis<3;axis++)feet[3*l+axis]=pose->feet[source][axis];
    }
    printf("{\"model_deg\":");array(degrees,12);
    printf(",\"body_mm\":");array(pose->body,3);
    printf(",\"euler_rad\":");array(pose->euler,3);
    printf(",\"sole_height_mm\":");array(sole,4);
    printf(",\"feet_mm_flat\":");array(feet,12);
    printf("}");
}
static bool forward_frame(const ainekio_v2_posture_t *state,const ainekio_v2_frame_t *frame,
                          const double euler[3],ainekio_v2_walk_pose_t *out)
{
    ainekio_v2_frame_t wire=*frame;
    for(unsigned j=0;j<12;j++)wire.position[j]=(float)lround(wire.position[j]);
    return ainekio_v2_posture_observe(state,&wire,euler,out);
}
static void level_pair(const ainekio_v2_posture_t *level,const ainekio_v2_walk_pose_t *target,
                       const char *name,double roll,double pitch)
{
    double euler[3]={roll,pitch,0};ainekio_v2_walk_pose_t measured={0},corrected={0};
    largest_fit_delta=0.;
    bool ok=forward_frame(level,&target->frame,euler,&measured);
    corrected=measured;memset(corrected.euler,0,sizeof corrected.euler);
    ok=ok && ainekio_v2_contact_solve(&corrected,(const double (*)[3])level->anchors) && fit(&corrected.frame,NULL);
    printf("{\"kind\":\"level_pair\",\"phase\":\"%s\",\"measured\":",name);print_pose(&measured);
    printf(",\"target\":");print_pose(&corrected);
    printf(",\"valid\":%s,\"fit_delta_deg\":%.9g}\n",ok?"true":"false",largest_fit_delta);
}
static void episode(const ainekio_v2_frame_t *start,const ainekio_v2_walk_pose_t *stand,
                    const ainekio_v2_walk_pose_t *peak,const char *name,unsigned order,double roll,double pitch)
{
    double euler[3]={roll,pitch,0},at=0.;uint16_t moving=0;
    ainekio_v2_posture_t state;largest_fit_delta=0.;
    bool ok=ainekio_v2_posture_begin_ordered(&state,start,&peak->frame,euler,order);
    printf("{\"case\":\"%s-order%u-roll%.2f-pitch%.2f\",\"start_pose\":\"%s\",\"order\":%u,\"start\":",name,order,roll,pitch,name,order);
    if(ok)print_pose(&state.start);else printf("null");
    ainekio_v2_frame_t fitted=*start;uint16_t pulses[12];double fitted_degrees[12],delta[12];
    bool start_travel=ainekio_p4_joint_frame_in_travel(mapping,start);
    bool start_fit=ainekio_p4_joint_fit_frame(mapping,&fitted);
    for(unsigned j=0;j<12;j++){fitted_degrees[j]=fitted.position[j]/100.;delta[j]=(fitted.position[j]-start->position[j])/100.;}
    printf(",\"start_mapping\":{\"in_travel\":%s,\"maps\":%s,\"fit_succeeded\":%s,\"fitted_model_deg\":",start_travel?"true":"false",ainekio_p4_joint_map_frame(mapping,start,pulses)?"true":"false",start_fit?"true":"false");
    array(fitted_degrees,12);printf(",\"fit_delta_deg\":");array(delta,12);printf("}");
    printf(",\"nominal_stand\":");print_pose(stand);
    printf(",\"high_stand\":");print_pose(peak);printf(",\"stages\":[");
    unsigned index=0;double worst_forward=0.,accepted_fit_delta=0.;bool all_targets_in_travel=true;
    while(ok && at<ainekio_v2_posture_path_length()) {
        ainekio_v2_walk_pose_t previous=state.pose;
        ok=ainekio_v2_posture_next_target_mapped(&state,&at,&moving,fit,NULL);
        if(!ok)break;
        ainekio_v2_frame_t checked=state.pose.frame;
        bool checked_fit=ainekio_p4_joint_fit_frame(mapping,&checked);
        all_targets_in_travel=all_targets_in_travel && checked_fit &&
            ainekio_p4_joint_frame_in_travel(mapping,&state.pose.frame);
        for(unsigned j=0;j<12;j++)accepted_fit_delta=fmax(accepted_fit_delta,
            fabs(checked.position[j]-state.pose.frame.position[j])/100.);
        ainekio_v2_walk_pose_t actual,lagged;ainekio_v2_frame_t lag=state.pose.frame;
        for(unsigned j=0;j<12;j++)lag.position[j]=(int)lround(.5*(previous.frame.position[j]+state.pose.frame.position[j]));
        double lag_euler[3];for(unsigned a=0;a<3;a++)lag_euler[a]=.5*(previous.euler[a]+state.pose.euler[a]);
        ok=forward_frame(&state,&state.pose.frame,state.pose.euler,&actual) &&
            forward_frame(&state,&lag,lag_euler,&lagged);
        if(!ok)break;
        for(unsigned l=0;l<4;l++)for(unsigned a=0;a<2;a++)
            worst_forward=fmax(worst_forward,fabs(actual.feet[l][a]-state.pose.feet[l][a]));
        printf("%s{\"index\":%u,\"coordinate\":%.9g,\"moving_joints\":%u,\"phase\":\"%s\",\"target\":",index?",":"",index,at,moving,index<16?(const char*[]){"shift","lift","place","lower"}[index%4]:"high_stand");
        print_pose(&state.pose);printf(",\"arrived\":");print_pose(&actual);
        printf(",\"lagged\":");print_pose(&lagged);
        if(sweep_mode && index%4==2 && index<16) {
            double lowest=INFINITY;bool swept_ok=true,travel=true;
            for(unsigned sample=0;sample<=20;sample++) {
                ainekio_v2_frame_t frame=state.pose.frame;
                for(unsigned j=0;j<12;j++)frame.position[j]=(float)lround(
                    lround(previous.frame.position[j])+
                    (lround(state.pose.frame.position[j])-lround(previous.frame.position[j]))*sample/20.);
                ainekio_v2_walk_pose_t observed;
                bool valid=ainekio_v2_posture_observe(&state,&frame,state.pose.euler,&observed);
                swept_ok=swept_ok && valid;
                travel=travel && ainekio_p4_joint_frame_in_travel(mapping,&frame);
                if(valid)for(unsigned leg=0;leg<4;leg++)if(!state.pose.grounded[leg])
                    lowest=fmin(lowest,observed.sole_height[leg]-fmax(state.start.sole_height[leg],state.target.sole_height[leg]));
            }
            printf(",\"placement_sweep\":{\"samples\":21,\"native_forward_valid\":%s,\"all_in_installed_travel\":%s,\"minimum_clearance_mm\":%.9g,\"grounded_native_order\":[%s,%s,%s,%s]}",
                   swept_ok?"true":"false",travel?"true":"false",lowest,
                   state.pose.grounded[0]?"true":"false",state.pose.grounded[1]?"true":"false",
                   state.pose.grounded[2]?"true":"false",state.pose.grounded[3]?"true":"false");
        }
        printf("}");index++;
    }
    printf("],\"valid\":%s,\"completed_stages\":%u,\"fit_delta_deg\":%.9g,\"attempted_fit_delta_deg\":%.9g,\"all_targets_in_travel\":%s,\"max_forward_xy_error_mm\":%.9g}\n",ok?"true":"false",index,accepted_fit_delta,largest_fit_delta,all_targets_in_travel?"true":"false",worst_forward);
}
int main(int argc,char **argv)
{
    for(unsigned j=0;j<12;j++) {
        int channel,invert,home,cd;double scale;
        if(scanf("%d%d%d%d%lf",&channel,&invert,&home,&cd,&scale)!=5)return 2;
        mapping[j]=(ainekio_p4_joint_config_t){.channel=channel,.invert=invert,.home_us=home,.home_cd=cd,.us_per_degree=scale};
    }
    if(!ainekio_p4_joints_valid(mapping))return 3;
    bool splayed_mode=argc==2 && strcmp(argv[1],"--splayed")==0;
    bool supplied_mode=argc==2 && strcmp(argv[1],"--from-angles")==0;
    sweep_mode=splayed_mode || supplied_mode || (argc==2 && strcmp(argv[1],"--sweep")==0);
    if(argc==2 && strcmp(argv[1],"--evaluate")==0) {
        double angle,euler[3];ainekio_v2_frame_t start={0},target={0};
        while(scanf("%lf",&angle)==1) {
            start.position[0]=(float)lround(angle*100.);
            for(unsigned j=1;j<12;j++){if(scanf("%lf",&angle)!=1)return 7;start.position[j]=(float)lround(angle*100.);}
            for(unsigned a=0;a<3;a++)if(scanf("%lf",&euler[a])!=1)return 7;
            for(unsigned j=0;j<12;j++){if(scanf("%lf",&angle)!=1)return 7;target.position[j]=(float)lround(angle*100.);}
            ainekio_v2_posture_t state;ainekio_v2_walk_pose_t observed={0};
            largest_fit_delta=0.;ainekio_v2_frame_t fitted=target;
            bool mapped=fit(&fitted,NULL),travel=ainekio_p4_joint_frame_in_travel(mapping,&target);
            bool ok=ainekio_v2_posture_begin(&state,&start,&start,euler) &&
                    forward_frame(&state,&target,euler,&observed);
            printf("{\"valid\":%s,\"in_travel\":%s,\"mapped\":%s,\"fit_delta_deg\":%.9g,\"pose\":",
                   ok?"true":"false",travel?"true":"false",mapped?"true":"false",largest_fit_delta);
            if(ok)print_pose(&observed);else printf("null");printf("}\n");
        }
        return 0;
    }
    ainekio_v2_rise_t rise;if(!ainekio_v2_rise_begin(&rise))return 4;
    ainekio_v2_posture_t level;double zero[3]={0};
    if(!ainekio_v2_posture_begin(&level,&rise.stand.frame,&rise.stand.frame,zero))return 5;
    ainekio_v2_walk_pose_t stand=level.target,peak=stand;peak.body[2]+=2.;
    if(!ainekio_v2_contact_solve(&peak,(const double (*)[3])level.anchors))return 6;
    if(supplied_mode) {
        ainekio_v2_frame_t start={0};double value,euler[3];
        for(unsigned j=0;j<12;j++) {
            if(scanf("%lf",&value)!=1 || !isfinite(value))return 7;
            start.position[j]=(float)lround(value*100.);
        }
        for(unsigned axis=0;axis<3;axis++)
            if(scanf("%lf",&euler[axis])!=1 || !isfinite(euler[axis]))return 7;
        /* This exporter reconstructs roll/pitch; yaw is immaterial for these
         * level, local fixtures. Reject unsupported input instead of relabeling. */
        if(euler[2]!=0.)return 7;
        for(unsigned order=0;order<4;order++)
            episode(&start,&stand,&peak,"supplied-angles",order,euler[0],euler[1]);
        return 0;
    }
    if(splayed_mode) {
        /* Synthetic starts, not calibrated Home or measured robot poses.
         * Unlike contact-solved vertical offsets, these require real XY foot
         * repositioning. Reuse the same mapped teacher and swept FK audit. */
        const int crank_cd[]={-3200,-4041,-4800};
        for(unsigned variant=0;variant<sizeof crank_cd/sizeof crank_cd[0];variant++) {
            ainekio_v2_frame_t start={0};
            for(unsigned leg=0;leg<4;leg++) {
                start.position[leg*3+1]=117;
                start.position[leg*3+2]=(float)crank_cd[variant];
            }
            char name[40];snprintf(name,sizeof name,"splayed-crank%d",-crank_cd[variant]);
            for(unsigned order=0;order<4;order++)episode(&start,&stand,&peak,name,order,0.,0.);
        }
        return 0;
    }
    for(unsigned order=0;order<4;order++)for(unsigned tilt=0;tilt<3;tilt++) {
        if(sweep_mode && tilt)continue;
        double roll=tilt==1?.04:0.,pitch=tilt==2?-.04:0.;
        episode(&rise.crouch.frame,&stand,&peak,"crouch",order,roll,pitch);
        episode(&rise.stand.frame,&stand,&peak,"stand",order,roll,pitch);
        for(unsigned depth=5;depth<=15;depth+=5) {
            ainekio_v2_walk_pose_t lower=stand;lower.body[2]-=depth;
            char name[32];snprintf(name,sizeof name,"lower%u",depth);
            if(ainekio_v2_contact_solve(&lower,(const double (*)[3])level.anchors))
                episode(&lower.frame,&stand,&peak,name,order,roll,pitch);
        }
    }
    for(unsigned axis=0;axis<2;axis++)for(int direction=-1;direction<=1;direction+=2) {
        double roll=axis==0?direction*.04:0.,pitch=axis==1?direction*.04:0.;
        level_pair(&level,&peak,"high_stand",roll,pitch);
        level_pair(&level,&stand,"settled",roll,pitch);
    }
    return 0;
}
