#include "ainekio/v2_walk.h"
#include "ainekio/v2_limits.h"
#include "walk_data.h"
#include <math.h>
#include <string.h>

typedef struct { float x,y,z; } vec_t;
typedef struct { vec_t h,a,b; } axes_t;
typedef struct {
    float hc,hs,dx,dz,bc,bs,lc,ls;
    vec_t reference,contact;
    axes_t ref_jac,contact_jac;
} solution_t;
static vec_t add(vec_t a,vec_t b){return (vec_t){a.x+b.x,a.y+b.y,a.z+b.z};}
static vec_t sub(vec_t a,vec_t b){return (vec_t){a.x-b.x,a.y-b.y,a.z-b.z};}
static vec_t scale(vec_t a,float s){return (vec_t){a.x*s,a.y*s,a.z*s};}
static float dot(vec_t a,vec_t b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static vec_t cross(vec_t a,vec_t b){return (vec_t){a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static vec_t transform(const vec_t r[3],vec_t v){return add(add(scale(r[0],v.x),scale(r[1],v.y)),scale(r[2],v.z));}
static vec_t inverse(const vec_t r[3],vec_t v){return (vec_t){dot(r[0],v),dot(r[1],v),dot(r[2],v)};}
static vec_t point(const float p[3]){return (vec_t){p[0],p[1],p[2]};}
static float wrap(float a){return remainderf(a,6.2831853071795864769f);}
static void rotation(const double e[3],vec_t r[3])
{
    float cx=cosf((float)e[0]),sx=sinf((float)e[0]);
    float cy=cosf((float)e[1]),sy=sinf((float)e[1]);
    float cz=cosf((float)e[2]),sz=sinf((float)e[2]);
    r[0]=(vec_t){cz*cy,sz*cy,-sy};
    r[1]=(vec_t){cz*sy*sx-sz*cx,sz*sy*sx+cz*cx,cy*sx};
    r[2]=(vec_t){cz*sy*cx+sz*sx,sz*sy*cx-cz*sx,cy*cx};
}
static vec_t lower(const solution_t *s,vec_t v)
{
    return (vec_t){s->lc*v.x-s->ls*v.z,v.y,s->ls*v.x+s->lc*v.z};
}
static void mechanism(const v2_walk_leg_t *g,const vec_t shoulder[3],const solution_t *s,vec_t r[3])
{
    r[0]=scale(shoulder[0],g->mirror);
    r[1]=add(scale(shoulder[1],s->hc),scale(shoulder[2],s->hs));
    r[2]=add(scale(shoulder[1],-s->hs),scale(shoulder[2],s->hc));
}
static float support(const v2_sole_profile_t *profile,const vec_t r[3],const solution_t *s,vec_t *contact)
{
    float best=INFINITY;
    vec_t normal={r[0].z*s->lc+r[2].z*s->ls,r[1].z,-r[0].z*s->ls+r[2].z*s->lc};
    for(unsigned i=0;i<profile->count;i++) {
        vec_t local=point(profile->points[i]);float height=dot(normal,local);
        if(height<best){best=height;*contact=local;}
    }
    return best-profile->allowance;
}
static axes_t derivatives(const v2_walk_leg_t *g,const vec_t shoulder[3],const vec_t r[3],
                          const solution_t *s,vec_t local,vec_t *world)
{
    vec_t v=lower(s,local),knee={s->dx,0,s->dz};
    vec_t offset=point(g->mechanism_translation);
    offset.y=s->hc*g->mechanism_translation[1]-s->hs*g->mechanism_translation[2];
    offset.z=s->hs*g->mechanism_translation[1]+s->hc*g->mechanism_translation[2];
    *world=add(transform(shoulder,offset),transform(r,add(knee,v)));
    return (axes_t){cross(shoulder[0],*world),
        transform(r,(vec_t){-(s->dz-V2_O_Z),0,s->dx-V2_O_X}),
        transform(r,(vec_t){-v.z,0,v.x})};
}
/* Circle intersections give shoulder/carrier/lower-link orientation directly.
 * The selected knee stays on the assembly branch nearest the preceding command.
 * There is no multidimensional numerical solver or line search. */
/* Reject impossible triangles before taking a square root. Roundoff in the
 * radicand is clamped only AFTER the independent reach inequalities passed. */
static bool circle(float d2,float radius,float other,float *along,float *height)
{
    float low=radius-other,high=radius+other;
    if(!isfinite(d2)||d2<=1e-8f||d2<low*low||d2>high*high)return false;
    *along=(radius*radius+d2-other*other)/(2.f*d2);
    *height=sqrtf(fmaxf(0.f,radius*radius/d2-(*along)*(*along)));
    return true;
}
static bool endpoint(const v2_walk_leg_t *g,const vec_t shoulder[3],vec_t target,
                     float previous_dx,float previous_dz,solution_t *s)
{
    vec_t v=inverse(shoulder,target);float y=g->mechanism_translation[1]+g->reference[1];
    float zz=v.y*v.y+v.z*v.z-y*y;if(zz<0)return false;
    float z=-sqrtf(zz),norm=v.y*v.y+v.z*v.z;if(norm<1e-8f)return false;
    s->hc=(y*v.y+z*v.z)/norm;s->hs=(y*v.z-z*v.y)/norm;
    float x=(v.x-g->mechanism_translation[0])*g->mirror-V2_O_X;
    z-=g->mechanism_translation[2]+V2_O_Z;
    float d2=x*x+z*z,L2=g->reference[0]*g->reference[0]+g->reference[2]*g->reference[2];
    float along,height;
    if(!circle(d2,V2_PRIMARY,sqrtf(L2),&along,&height))return false;
    float ax=V2_O_X+along*x-height*z,az=V2_O_Z+along*z+height*x;
    float bx=V2_O_X+along*x+height*z,bz=V2_O_Z+along*z-height*x;
    float da=(ax-previous_dx)*(ax-previous_dx)+(az-previous_dz)*(az-previous_dz);
    float db=(bx-previous_dx)*(bx-previous_dx)+(bz-previous_dz)*(bz-previous_dz);
    s->dx=da<=db?ax:bx;s->dz=da<=db?az:bz;
    float lx=x+V2_O_X-s->dx,lz=z+V2_O_Z-s->dz;
    s->lc=(lx*g->reference[0]+lz*g->reference[2])/L2;
    s->ls=(lz*g->reference[0]-lx*g->reference[2])/L2;
    s->bc=V2_BETA_C*s->lc-V2_BETA_S*s->ls;
    s->bs=V2_BETA_S*s->lc+V2_BETA_C*s->ls;
    return true;
}
static bool crank(const solution_t *s,float previous_theta,float branch,float *theta)
{
    float ex=s->dx+V2_PICKUP*s->bc,ez=s->dz+V2_PICKUP*s->bs;
    float x=ex-V2_C_X,z=ez-V2_C_Z,d2=x*x+z*z;if(d2<1e-8f)return false;
    float along,height,best=INFINITY;bool found=false;
    if(!circle(d2,V2_INPUT,V2_ROD,&along,&height))return false;
    for(unsigned i=0;i<2;i++) {
        float sign=i?1.f:-1.f,px=V2_C_X+along*x-sign*height*z,pz=V2_C_Z+along*z+sign*height*x;
        /* Retain both four-bar assembly and inverse-crank branch. Crossing
         * to the other circle root would teleport the motor angle. */
        if((x*(pz-V2_C_Z)-z*(px-V2_C_X))*branch<=0.f)continue;
        if(((px-s->dx)*(ez-s->dz)-(pz-s->dz)*(ex-s->dx))*V2_BRANCH<0.f)continue;
        float q=wrap(atan2f(pz-V2_C_Z,px-V2_C_X)-V2_THETA_ZERO);
        float distance=fabsf(wrap(q-previous_theta));
        if(distance<best){best=distance;*theta=q;found=true;}
    }
    return found;
}
static bool seed(const double q[3],solution_t *s)
{
    s->hc=cosf((float)q[0]);s->hs=sinf((float)q[0]);
    float a=V2_ALPHA_ZERO+(float)q[1],t=V2_THETA_ZERO+(float)q[2];
    s->dx=V2_O_X+V2_PRIMARY*cosf(a);s->dz=V2_O_Z+V2_PRIMARY*sinf(a);
    float x=V2_C_X+V2_INPUT*cosf(t)-s->dx,z=V2_C_Z+V2_INPUT*sinf(t)-s->dz;
    float d2=x*x+z*z;if(d2<1e-8f)return false;
    float along,height;
    if(!circle(d2,V2_PICKUP,V2_ROD,&along,&height))return false;
    height*=V2_BRANCH;
    s->bc=(along*x-height*z)/V2_PICKUP;s->bs=(along*z+height*x)/V2_PICKUP;
    s->lc=s->bc*V2_BETA_C+s->bs*V2_BETA_S;s->ls=s->bs*V2_BETA_C-s->bc*V2_BETA_S;
    return true;
}
/* Startup, entry and locomotion share the same actual four-bar closure. */
bool ainekio_v2_limits_leg(const double q[3])
{
    if(!q)return false;
    for(unsigned j=0;j<3;j++)if(!isfinite(q[j]))return false;
    solution_t s={0};return seed(q,&s);
}
bool ainekio_v2_limits_frame(const ainekio_v2_frame_t *frame)
{
    if(!frame)return false;
    for(unsigned leg=0;leg<4;leg++) {
        double q[3];for(unsigned j=0;j<3;j++)q[j]=frame->position[3*leg+j]*0.00017453292519943296;
        if(!ainekio_v2_limits_leg(q))return false;
    }
    return true;
}
bool ainekio_v2_walk_solve(ainekio_v2_walk_pose_t *p)
{
    if(!p)return false;
    for(unsigned j=0;j<3;j++)if(!isfinite(p->body[j])||!isfinite(p->euler[j]))return false;
    vec_t body[3];rotation(p->euler,body);
    double next[4][3];
    const v2_sole_profile_t *profile=p->gait==AINEKIO_GAIT_CRAWL?&v2_crawl_sole:&v2_walk_sole;
    for(unsigned leg=0;leg<4;leg++) {
        for(unsigned j=0;j<3;j++)if(!isfinite(p->joints[leg][j])||!isfinite(p->feet[leg][j]))return false;
        if(!isfinite(p->sole_height[leg]))return false;
        const v2_walk_leg_t *g=&v2_walk_legs[leg];vec_t shoulder[3],r[3];
        for(unsigned j=0;j<3;j++)shoulder[j]=scale(body[j],g->shoulder_sign[j]);
        vec_t hip=add(point(v2_walk_pivot),transform(body,sub(point(g->shoulder_translation),point(v2_walk_pivot))));
        /* Subtract unbounded world translation in double before using the FPU. */
        vec_t target={(float)(p->feet[leg][0]-p->body[0])-hip.x,(float)(p->feet[leg][1]-p->body[1])-hip.y,0};
        solution_t s={0};if(!seed(p->joints[leg],&s))return false;
        float previous_dx=s.dx,previous_dz=s.dz;
        float previous_theta=V2_THETA_ZERO+(float)p->joints[leg][2];
        float crank_branch=(s.dx+V2_PICKUP*s.bc-V2_C_X)*sinf(previous_theta)-
            (s.dz+V2_PICKUP*s.bs-V2_C_Z)*cosf(previous_theta);
        mechanism(g,shoulder,&s,r);vec_t contact;
        float sole=support(profile,r,&s,&contact);
        float z=(float)p->sole_height[leg]+transform(r,lower(&s,point(g->reference))).z-sole;
        bool accurate=false;
        /* A rocking sole changes the endpoint height. At most four direct
         * endpoint evaluations and three scalar contact corrections; no
         * adaptive iteration count, recursive contact search, or fallback IK. */
        for(unsigned pass=0;pass<4;pass++) {
            target.z=z-(float)p->body[2]-hip.z;
            if(!endpoint(g,shoulder,target,previous_dx,previous_dz,&s))return false;
            mechanism(g,shoulder,&s,r);sole=support(profile,r,&s,&contact);
            s.ref_jac=derivatives(g,shoulder,r,&s,point(g->reference),&s.reference);
            s.contact_jac=derivatives(g,shoulder,r,&s,contact,&s.contact);
            float error=(float)p->body[2]+hip.z+s.contact.z-profile->allowance-(float)p->sole_height[leg];
            if(fabsf(error)<=.0005f){accurate=true;break;}
            vec_t ca=cross(s.ref_jac.a,s.ref_jac.b),cb=cross(s.ref_jac.b,s.ref_jac.h),cc=cross(s.ref_jac.h,s.ref_jac.a);
            float determinant=dot(s.ref_jac.h,ca);
            if(fabsf(determinant)<.000001f)return false;
            float slope=(s.contact_jac.h.z*ca.z+s.contact_jac.a.z*cb.z+s.contact_jac.b.z*cc.z)/determinant;
            if(!isfinite(slope)||fabsf(slope)<.01f)return false;
            z-=error/slope;
        }
        if(!accurate)return false;
        float theta;if(!crank(&s,(float)p->joints[leg][2],crank_branch,&theta))return false;
        next[leg][0]=atan2f(s.hs,s.hc);next[leg][1]=wrap(atan2f(s.dz-V2_O_Z,s.dx-V2_O_X)-V2_ALPHA_ZERO);next[leg][2]=theta;
    }
    memcpy(p->joints,next,sizeof(next));p->frame.geometry_id=ainekio_v2_walk_geometry_id;
    for(unsigned leg=0;leg<4;leg++)for(unsigned j=0;j<3;j++)
        p->frame.position[(leg<2?leg+2:leg-2)*3+j]=(float)(p->joints[leg][j]*5729.577951308232f);
    return true;
}
