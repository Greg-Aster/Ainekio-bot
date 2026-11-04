#include "trajectory_program.h"
#include "cJSON.h"
#include "ainekio/v2_walk.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static bool number(const cJSON *item,double *value)
{ if(!cJSON_IsNumber(item) || !isfinite(item->valuedouble))return false;*value=item->valuedouble;return true; }
static bool vector(const cJSON *item,float *out,unsigned count)
{
    if(!cJSON_IsArray(item) || cJSON_GetArraySize(item)!=(int)count)return false;
    for(unsigned i=0;i<count;i++) {
        double value;if(!number(cJSON_GetArrayItem(item,i),&value))return false;
        out[i]=(float)value;if(!isfinite(out[i]))return false;
    }
    return true;
}
static void *array(int count,size_t width)
{ return count>0 && (size_t)count<=SIZE_MAX/width ? calloc((size_t)count,width):NULL; }

void ainekio_p4_curve_free(ainekio_p4_curve_program_t *program)
{
    if(!program)return;
    free((void *)program->track.knots);free((void *)program->track.positions);
    free((void *)program->track.velocities);free((void *)program->clock.knots);
    free((void *)program->clock.targets);free((void *)program->attitude.knots);
    free((void *)program->attitude.up);free(program);
}

ainekio_p4_curve_program_t *ainekio_p4_curve_parse(const cJSON *root,esp_err_t *error)
{
    if(error)*error=ESP_ERR_INVALID_ARG;
    const cJSON *id=cJSON_GetObjectItemCaseSensitive(root,"id"),
        *value=cJSON_GetObjectItemCaseSensitive(root,"curve");
    if(!cJSON_IsString(id) || !id->valuestring[0] || strlen(id->valuestring)>32 || !cJSON_IsObject(value))return NULL;
    ainekio_p4_curve_program_t *p=calloc(1,sizeof(*p));
    if(!p){if(error)*error=ESP_ERR_NO_MEM;return NULL;}
    strcpy(p->token,id->valuestring);
    const cJSON *times=cJSON_GetObjectItemCaseSensitive(value,"times"),
        *positions=cJSON_GetObjectItemCaseSensitive(value,"positions"),
        *velocities=cJSON_GetObjectItemCaseSensitive(value,"velocities"),
        *clock=cJSON_GetObjectItemCaseSensitive(value,"clock"),
        *targets=cJSON_GetObjectItemCaseSensitive(value,"checkpoints");
    const int n=cJSON_GetArraySize(times),nc=cJSON_GetArraySize(clock),nt=cJSON_GetArraySize(targets);
    if(!cJSON_IsArray(times)||!cJSON_IsArray(positions)||!cJSON_IsArray(velocities)||
       !cJSON_IsArray(clock)||!cJSON_IsArray(targets)||n<2||nc<2||nt<2||
       cJSON_GetArraySize(positions)!=n||cJSON_GetArraySize(velocities)!=n)goto invalid;
    double *knots=array(n,sizeof(*knots)),*checkpoints=array(nt,sizeof(*checkpoints));
    float (*q)[12]=array(n,sizeof(*q)),(*v)[12]=array(n,sizeof(*v));
    ainekio_v2_clip_clock_knot_t *c=array(nc,sizeof(*c));
    p->track.knots=knots;p->track.positions=q;p->track.velocities=v;
    p->clock.knots=c;p->clock.targets=checkpoints;
    if(!knots||!q||!v||!c||!checkpoints){if(error)*error=ESP_ERR_NO_MEM;goto invalid;}
    for(int i=0;i<n;i++)if(!number(cJSON_GetArrayItem(times,i),&knots[i])||
       (i?knots[i]<=knots[i-1]:knots[i]!=0.)||
       !vector(cJSON_GetArrayItem(positions,i),q[i],12)||!vector(cJSON_GetArrayItem(velocities,i),v[i],12))goto invalid;
    if(knots[n-1]*1e6>=UINT64_MAX)goto invalid;
    for(int i=0;i<nc;i++) {
        const cJSON *row=cJSON_GetArrayItem(clock,i);double values[5];
        if(!cJSON_IsArray(row)||cJSON_GetArraySize(row)!=5)goto invalid;
        for(int j=0;j<5;j++)if(!number(cJSON_GetArrayItem(row,j),&values[j]))goto invalid;
        if(values[0]<0.||values[0]>knots[n-1]||values[1]<0.||values[2]<0.||
           values[3]<0.||values[3]>=n-1||floor(values[3])!=values[3]||
           values[4]<0.||values[4]>=12||floor(values[4])!=values[4]||
           (i&&(values[0]<c[i-1].tick||values[1]<c[i-1].travel_degrees||values[2]<c[i-1].hold_seconds)))goto invalid;
        c[i]=(ainekio_v2_clip_clock_knot_t){values[0],values[1],values[2],(uint32_t)values[3],(uint8_t)values[4]};
    }
    if(c[0].tick!=0.||c[0].travel_degrees!=0.||c[0].hold_seconds!=0.||c[nc-1].tick!=knots[n-1])goto invalid;
    for(int i=0;i<nt;i++) {
        if(!number(cJSON_GetArrayItem(targets,i),&checkpoints[i])||checkpoints[i]<0.||
           checkpoints[i]>knots[n-1]||(i&&checkpoints[i]<=checkpoints[i-1]))goto invalid;
        bool found=false;for(int j=0;j<nc;j++)if(c[j].tick==checkpoints[i]){found=true;break;}
        if(!found)goto invalid;
    }
    if(checkpoints[0]!=0.||checkpoints[nt-1]!=knots[n-1]||
       !number(cJSON_GetObjectItemCaseSensitive(value,"speed_deg_s"),&p->speed_degrees_s)||p->speed_degrees_s<=0.)goto invalid;
    double taper;if(!number(cJSON_GetObjectItemCaseSensitive(value,"taper"),&taper)||taper<0.||taper>c[nc-1].travel_degrees)goto invalid;
    const cJSON *attitude=cJSON_GetObjectItemCaseSensitive(value,"expected_up");
    const int na=cJSON_GetArraySize(attitude);
    if(attitude && !cJSON_IsArray(attitude))goto invalid;
    if(na) {
        if(na<2)goto invalid;
        double *t=array(na,sizeof(*t));float (*up)[3]=array(na,sizeof(*up));
        p->attitude.knots=t;p->attitude.up=up;p->attitude.count=(size_t)na;
        if(!t||!up){if(error)*error=ESP_ERR_NO_MEM;goto invalid;}
        for(int i=0;i<na;i++) {
            const cJSON *row=cJSON_GetArrayItem(attitude,i),*vector=cJSON_GetArrayItem(row,1);
            if(!cJSON_IsArray(row)||cJSON_GetArraySize(row)!=2||!cJSON_IsArray(vector)||cJSON_GetArraySize(vector)!=3||
               !number(cJSON_GetArrayItem(row,0),&t[i])||t[i]<0.||t[i]>knots[n-1]||(i&&t[i]<=t[i-1]))goto invalid;
            double v3[3],scale=0.;
            for(unsigned j=0;j<3;j++){if(!number(cJSON_GetArrayItem(vector,j),&v3[j]))goto invalid;scale=fmax(scale,fabs(v3[j]));}
            if(!scale)goto invalid;
            double length=0.;for(unsigned j=0;j<3;j++){v3[j]/=scale;length+=v3[j]*v3[j];}
            length=sqrt(length);for(unsigned j=0;j<3;j++)up[i][j]=(float)(v3[j]/length);
        }
        if(t[0]!=0.||t[na-1]!=knots[n-1])goto invalid;
    }
    p->track.count=(size_t)n;p->track.active_end_us=(uint64_t)round(knots[n-1]*1e6);
    p->track.minimum=p->minimum;p->track.maximum=p->maximum;
    p->clock.count=(size_t)nc;p->clock.target_count=(size_t)nt;
    p->curve=(ainekio_v2_curve_t){.track=&p->track,.clock=&p->clock,.sample_hz=1.,.taper_degrees=taper,
        .duration_us=p->track.active_end_us,.geometry_id=ainekio_v2_walk_geometry_id,
        .attitude=na?&p->attitude:NULL};
    ainekio_v2_frame_t minimum,maximum;
    if(!ainekio_v2_curve_bounds(&p->curve,&minimum,&maximum))goto invalid;
    memcpy(p->minimum,minimum.position,sizeof p->minimum);memcpy(p->maximum,maximum.position,sizeof p->maximum);
    if(error)*error=ESP_OK;
    return p;
invalid:
    ainekio_p4_curve_free(p);return NULL;
}
