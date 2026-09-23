#include "ainekio/v2_limits.h"
#include "walk_data.h"
#include <math.h>

static const float radians_per_cd=0.00017453292519943296f;
static const float tau=6.2831853071795864769f;
typedef struct { float theta,delta,phi,turn,n,dn,side; } path_t;

/* P is the crank pin relative to the primary pivot O. Closure requires the
 * distance P-D to lie between |rod-pickup| and rod+pickup. For this linkage,
 * D perpendicular to O-P is feasible throughout a complete crank revolution.
 * Express carrier position by its normalized cosine inside that exact annulus,
 * instead of the former provisional angle table. */
static void pin(float theta,float *distance,float *phi)
{
    float x=V2_C_X-V2_O_X+V2_INPUT*cosf(theta);
    float z=V2_C_Z-V2_O_Z+V2_INPUT*sinf(theta);
    *distance=hypotf(x,z);*phi=atan2f(z,x);
}
static float cosine_limit(float d,bool positive)
{
    float reach=positive?fabsf(V2_ROD-V2_PICKUP):V2_ROD+V2_PICKUP;
    float c=(V2_PRIMARY*V2_PRIMARY+d*d-reach*reach)/(2.f*V2_PRIMARY*d);
    return fminf(1.f,positive?c:-c);
}
static bool coordinates(float a,float theta,float *phi,float *n,float *side)
{
    float d;pin(theta,&d,phi);
    float offset=remainderf(a-*phi,tau),c=cosf(offset);
    *side=offset<0.f?-1.f:1.f;
    float limit=cosine_limit(d,c>=0.f);
    if(!(limit>0.f))return false;
    *n=c/limit;
    return isfinite(*n)&&fabsf(*n)<1.f;
}
static bool path(float from_a,float from_t,float to_a,float to_t,path_t *p)
{
    float n1,phi1,side1;
    p->theta=V2_THETA_ZERO+from_t*radians_per_cd;
    p->delta=(to_t-from_t)*radians_per_cd;
    if(!coordinates(V2_ALPHA_ZERO+from_a*radians_per_cd,p->theta,&p->phi,&p->n,&p->side)||
       !coordinates(V2_ALPHA_ZERO+to_a*radians_per_cd,p->theta+p->delta,&phi1,&n1,&side1)||p->side!=side1)return false;
    p->dn=n1-p->n;
    float phi_end=p->phi+p->delta+remainderf(phi1-p->phi-p->delta,tau);
    float alpha=V2_ALPHA_ZERO+from_a*radians_per_cd;
    p->turn=alpha-p->phi-remainderf(alpha-p->phi,tau);
    /* Do not silently choose another revolution or disconnected branch. */
    float expected=phi_end+p->side*acosf(cosf(V2_ALPHA_ZERO+to_a*radians_per_cd-phi1))+p->turn;
    return fabsf(expected-(V2_ALPHA_ZERO+to_a*radians_per_cd))<0.00001f;
}
static float carrier(const path_t *p,float u)
{
    float d,phi;pin(p->theta+u*p->delta,&d,&phi);
    phi=p->phi+u*p->delta+remainderf(phi-p->phi-u*p->delta,tau);
    float n=p->n+u*p->dn,c=n*cosine_limit(d,n>=0.f);
    return (phi+p->side*acosf(c)+p->turn-V2_ALPHA_ZERO)/radians_per_cd;
}
bool ainekio_v2_transition(const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,
                          double progress,ainekio_v2_frame_t *out)
{
    if(!out||!isfinite(progress)||progress<0.||progress>1.||
       !ainekio_v2_limits_frame(from)||!ainekio_v2_limits_frame(to))return false;
    if(progress==0.){*out=*from;return true;}
    if(progress==1.){*out=*to;return true;}
    ainekio_v2_frame_t result=*to;
    for(unsigned l=0;l<4;l++) {
        unsigned i=3*l;path_t p;
        if(!path(from->position[i+1],from->position[i+2],to->position[i+1],to->position[i+2],&p))return false;
        for(unsigned j=0;j<3;j++)result.position[i+j]=(float)(from->position[i+j]+progress*(to->position[i+j]-from->position[i+j]));
        result.position[i+1]=carrier(&p,(float)progress);
    }
    if(!ainekio_v2_limits_frame(&result))return false;
    *out=result;return true;
}
/* Interval bounds, not sampled validation. Bound the crank-pin distance and
 * normalized cosine on each of 16 fixed intervals; acos is monotone. Analytic
 * derivative bounds also cover every interior point and clamp breakpoint. */
static void limit_bounds(float dlo,float dhi,bool positive,float *low,float *high,float *derivative)
{
    float a=cosine_limit(dlo,positive),b=cosine_limit(dhi,positive);
    *low=fminf(a,b);*high=fmaxf(a,b);*derivative=0.f;
    float reach=positive?fabsf(V2_ROD-V2_PICKUP):V2_ROD+V2_PICKUP;
    float threshold=positive?V2_PRIMARY-reach:reach-V2_PRIMARY;
    if(dhi<=threshold)return;
    float start=fmaxf(dlo,threshold);
    float k=V2_PRIMARY*V2_PRIMARY-reach*reach;
    float da=fabsf(1.f-k/(start*start))/(2.f*V2_PRIMARY);
    float db=fabsf(1.f-k/(dhi*dhi))/(2.f*V2_PRIMARY);
    *derivative=fmaxf(da,db);
    if(positive&&k>0.f) {
        float stationary=sqrtf(k);
        if(stationary>dlo&&stationary<dhi)*low=fminf(*low,cosine_limit(stationary,true));
    }
}
bool ainekio_v2_transition_bounds(const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to,
    ainekio_v2_frame_t *minimum,ainekio_v2_frame_t *maximum,double max_derivative_cd[12])
{
    if(!minimum||!maximum||!max_derivative_cd||!ainekio_v2_limits_frame(from)||!ainekio_v2_limits_frame(to))return false;
    *minimum=*maximum=*to;
    for(unsigned i=0;i<12;i++) {
        minimum->position[i]=fminf(from->position[i],to->position[i]);
        maximum->position[i]=fmaxf(from->position[i],to->position[i]);
        max_derivative_cd[i]=fabs(to->position[i]-from->position[i]);
    }
    float base=hypotf(V2_C_X-V2_O_X,V2_C_Z-V2_O_Z);
    if(!(V2_INPUT>base))return false;
    for(unsigned l=0;l<4;l++) {
        unsigned a=3*l+1,t=a+1;path_t p;
        if(!path(from->position[a],from->position[t],to->position[a],to->position[t],&p))return false;
        for(unsigned step=0;step<16;step++) {
            float lo=step/16.f,hi=(step+1)/16.f,mid=(lo+hi)*.5f,d,phi;
            pin(p.theta+mid*p.delta,&d,&phi);
            float radius=V2_INPUT*fabsf(p.delta)/32.f;
            float dlo=fmaxf(V2_INPUT-base,d-radius),dhi=fminf(V2_INPUT+base,d+radius);
            float nlo=fminf(p.n+lo*p.dn,p.n+hi*p.dn),nhi=fmaxf(p.n+lo*p.dn,p.n+hi*p.dn);
            float cmin=1.f,cmax=-1.f,gmax=0.f,dg=0.f;
            for(unsigned positive=0;positive<2;positive++) {
                float nl=positive?fmaxf(0.f,nlo):nlo,nh=positive?nhi:fminf(0.f,nhi);
                if(nl>nh)continue;
                float gl,gh,derivative;limit_bounds(dlo,dhi,positive,&gl,&gh,&derivative);
                cmin=fminf(cmin,fminf(nl*gl,nl*gh));cmax=fmaxf(cmax,fmaxf(nh*gl,nh*gh));
                gmax=fmaxf(gmax,gh);dg=fmaxf(dg,derivative);
            }
            float cabs=fmaxf(fabsf(cmin),fabsf(cmax));
            if(!(cabs<1.f))return false;
            float philo,dummy,phihi;pin(p.theta+lo*p.delta,&dummy,&philo);pin(p.theta+hi*p.delta,&dummy,&phihi);
            philo=p.phi+lo*p.delta+remainderf(philo-p.phi-lo*p.delta,tau);
            phihi=p.phi+hi*p.delta+remainderf(phihi-p.phi-hi*p.delta,tau);
            float amin=fminf(philo,phihi)+(p.side>0.f?acosf(cmax):-acosf(cmin))+p.turn-V2_ALPHA_ZERO;
            float amax=fmaxf(philo,phihi)+(p.side>0.f?acosf(cmin):-acosf(cmax))+p.turn-V2_ALPHA_ZERO;
            minimum->position[a]=fminf(minimum->position[a],(amin-.000002f)/radians_per_cd);
            maximum->position[a]=fmaxf(maximum->position[a],(amax+.000002f)/radians_per_cd);
            float nmax=fmaxf(fabsf(nlo),fabsf(nhi));
            float derivative=V2_INPUT/dlo*fabsf(p.delta)+
                (fabsf(p.dn)*gmax+nmax*dg*V2_INPUT*fabsf(p.delta))/sqrtf(1.f-cabs*cabs);
            max_derivative_cd[a]=fmax(max_derivative_cd[a],(derivative+.00001f)/radians_per_cd);
        }
    }
    return true;
}
