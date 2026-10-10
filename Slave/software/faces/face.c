#include "ainekio/face.h"
#include <math.h>
#include <string.h>

enum eye { DOT, CHEER, SAD, SLANT, RING, FLAT, HEART, STAR, CHEVRON, CROSS, SPIRAL };
enum animation { STILL, BREATHE, BLINK, BOB, SPEAK, PULSE, TILT, LOOK, SWAY, WINK,
                 THINK, INQUIRE, ATTEND };
enum accent { NONE, SMILE, TEAR, FROWN, OOH, SLEEP, SPARK, QUESTION, ELLIPSIS,
              FLAT_MOUTH, SPEED, BUBBLES, NOTES, BLUSH, SWEAT, ZIGZAG, CONFETTI };
enum color { CYAN=0x16dfff, BLUE=0x469aff, RED=0xff475d, GOLD=0xffcd48,
             INDIGO=0x8286ff, PINK=0xff70bf, VIOLET=0xc88bff, TEAL=0x33efcb };
typedef struct {
    const char *name;
    enum eye left, right;
    uint32_t color;
    enum animation animation;
    enum accent accent;
    float gaze_x, gaze_y;
    uint32_t period_ms;
} face_t;
#define FACE(n,l,r,c,a,d,x,y,p) {#n,l,r,c,a,d,x,y,p},
static const face_t faces[] = {
#include "faces.def"
};
#undef FACE

size_t ainekio_face_count(void) { return sizeof(faces)/sizeof(faces[0]); }
const char *ainekio_face_name(size_t i) { return i<ainekio_face_count() ? faces[i].name : NULL; }
uint32_t ainekio_face_period_ms(size_t i) { return i<ainekio_face_count() ? faces[i].period_ms : 0; }
bool ainekio_face_find(const char *name, size_t *index)
{
    if (!name || !index) return false;
    for (size_t i=0;i<ainekio_face_count();++i)
        if (!strcmp(name,faces[i].name)) { *index=i; return true; }
    return false;
}

/* Soft luminous strokes: colored halo, saturated edge and pale hot core.
 * Bounding boxes keep work proportional to the drawing, not panel area times
 * primitive count. Each stroke uses maximum blending so joints do not flare.
 * Halo width/strength are sampled once per face, never per pixel. No blur pass
 * or additional framebuffer is needed. */
typedef struct {
    uint16_t *pixels;
    uint32_t color;
    float light, halo_width, halo_inverse, halo_strength;
} canvas_t;
static void halo(canvas_t *c,float pulse)
{
    c->halo_width=12+4*pulse;
    c->halo_inverse=1/c->halo_width;
    c->halo_strength=.22F+.12F*pulse;
}
/* Geometry and color inputs here are finite. Inline clamps avoid repeated
 * libm calls in the inner pixel loop, especially on the microcontroller. */
static float unit(float value) { return value<0 ? 0 : value>1 ? 1 : value; }
static unsigned channel(float value) { return value>255 ? 255 : (unsigned)value; }
static void pixel(canvas_t *c,int x,int y,float distance,float radius)
{
    float edge=distance-radius;
    float halo=unit(1.F-(edge>0 ? edge : 0)*c->halo_inverse);
    float coverage=unit(.8F-edge);
    float core=unit(-edge-1.F)*.85F;
    float glow=(coverage+halo*halo*c->halo_strength)*c->light;
    unsigned r=channel(((c->color>>16)&255)*glow+180*core)>>3;
    unsigned g=channel(((c->color>>8)&255)*glow+180*core)>>2;
    unsigned b=channel((c->color&255)*glow+180*core)>>3;
    uint16_t *p=&c->pixels[y*AINEKIO_FACE_WIDTH+x];
    unsigned previous_r=(*p>>11)&31,previous_g=(*p>>5)&63,previous_b=*p&31;
    r=r>previous_r ? r : previous_r;
    g=g>previous_g ? g : previous_g;
    b=b>previous_b ? b : previous_b;
    *p=(uint16_t)((r<<11)|(g<<5)|b);
}
static void line(canvas_t *c,float ax,float ay,float bx,float by,float width)
{
    float radius=width*.5F, pad=radius+c->halo_width,dx=bx-ax,dy=by-ay,length=dx*dx+dy*dy;
    const float inverse_length=length>0 ? 1/length : 0;
    const float extent_squared=pad*pad;
    int x0=(int)fmaxf(0,floorf(fminf(ax,bx)-pad)),x1=(int)fminf(319,ceilf(fmaxf(ax,bx)+pad));
    int y0=(int)fmaxf(0,floorf(fminf(ay,by)-pad)),y1=(int)fminf(169,ceilf(fmaxf(ay,by)+pad));
    for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){
        float u=unit(((x-ax)*dx+(y-ay)*dy)*inverse_length);
        float px=x-ax-u*dx,py=y-ay-u*dy;
        const float distance_squared=px*px+py*py;
        if(distance_squared<=extent_squared)
            pixel(c,x,y,sqrtf(distance_squared),radius);
    }
}
static void dot(canvas_t *c,float x,float y,float radius) { line(c,x,y,x,y,2*radius); }
static void arc(canvas_t *c,float x,float y,float rx,float ry,float start,float end,float width)
{
    float px=x+rx*cosf(start),py=y+ry*sinf(start);
    const int steps=20;
    for(int i=1;i<=steps;++i){
        float a=start+(end-start)*i/steps,nx=x+rx*cosf(a),ny=y+ry*sinf(a);
        line(c,px,py,nx,ny,width);px=nx;py=ny;
    }
}
static void eye(canvas_t *c,enum eye type,float x,float y,float side,float open)
{
    const float pi=3.141592654F;
    if(open<.15F){line(c,x-9,y,x+9,y,3);return;}
    switch(type){
    case DOT: dot(c,x,y,5.2F*open);break;
    case FLAT: line(c,x-12,y,x+12,y,4);break;
    case CHEER: arc(c,x,y+6,15,15*open,pi,2*pi,4);break;
    case SAD: arc(c,x,y+14,16,16*open,pi*1.12F,pi*1.88F,3.8F);
        dot(c,x,y+5,3);break;
    case SLANT: line(c,x-15,y-7*side,x+15,y+7*side,5);
        line(c,x-10,y+8,x+10,y+8,3);break;
    case RING: arc(c,x,y,12,16*open,0,2*pi,3.8F);break;
    case CHEVRON: line(c,x-12*side,y-12*open,x+5*side,y,4);
        line(c,x+5*side,y,x-12*side,y+12*open,4);break;
    case CROSS: line(c,x-10,y-11*open,x+10,y+11*open,4);
        line(c,x+10,y-11*open,x-10,y+11*open,4);break;
    case HEART: {
        float px=x,py=y-5;
        for(int i=1;i<=48;++i){float t=2*pi*i/48,st=sinf(t);
            float nx=x+15*st*st*st,ny=y-(13*cosf(t)-5*cosf(2*t)-2*cosf(3*t)-cosf(4*t))*open;
            line(c,px,py,nx,ny,4);px=nx;py=ny;}
        break;}
    case STAR: {
        float px=x,py=y-18*open;
        for(int i=1;i<=10;++i){float a=-pi/2+pi*i/5,r=i%2?7:18;
            float nx=x+r*cosf(a),ny=y+r*sinf(a)*open;
            line(c,px,py,nx,ny,3.5F);px=nx;py=ny;}
        break;}
    case SPIRAL: {
        float px=x,py=y;
        for(int i=1;i<=48;++i){float a=i*pi/12,r=i*.3F;
            float nx=x+r*cosf(a),ny=y+r*sinf(a)*open;
            line(c,px,py,nx,ny,3);px=nx;py=ny;}
        break;}
    }
}
static void spark(canvas_t *c,float x,float y,float size)
{line(c,x-size,y,x+size,y,2);line(c,x,y-size,x,y+size,2);}

static float ease(float t) { return t*t*(3-2*t); }
static float blink(float t,float start,float end)
{
    if(t<=start||t>=end)return 1;
    return ease(fabsf(2*(t-start)/(end-start)-1));
}

/* Pauses between glances make thinking read as a gesture rather than a
 * perpetual eye oscillation. Matching endpoints keep the loop continuous.
 * Pure sampling also preserves seek/replay and motion cue timing. */
typedef struct { float at,x,y,tilt,right_open; } thought_key_t;
static void thought(float t,float *x,float *y,float *tilt,float *right_open)
{
    static const thought_key_t keys[]={
        {0,0,0,0,1}, {.12F,6,-5,-2,1}, {.28F,6,-5,-2,1},
        {.42F,-12,-2,3,1}, {.53F,-12,-2,3,1},
        {.61F,-9,0,4,.4F}, {.68F,-9,0,4,.4F},
        {.78F,0,0,0,1}, {1,0,0,0,1},
    };
    for(size_t i=1;i<sizeof(keys)/sizeof(keys[0]);++i){
        if(t>keys[i].at)continue;
        const thought_key_t *a=&keys[i-1],*b=&keys[i];
        const float u=ease((t-a->at)/(b->at-a->at));
        *x+=a->x+(b->x-a->x)*u; *y+=a->y+(b->y-a->y)*u;
        *tilt=a->tilt+(b->tilt-a->tilt)*u;
        *right_open=a->right_open+(b->right_open-a->right_open)*u;
        return;
    }
}

void ainekio_face_render(size_t index,uint64_t elapsed_ms,bool talking,
                        uint16_t pixels[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT])
{
    if(!pixels)return;
    memset(pixels,0,AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT*sizeof(*pixels));
    if(index>=ainekio_face_count())return;
    const face_t *f=&faces[index];
    const float pi=3.141592654F,t=(float)(elapsed_ms%f->period_ms)/f->period_ms;
    const float wave=sinf(2*pi*t);
    canvas_t c={.pixels=pixels,.color=f->color,.light=1};
    const float halo_cycles=f->animation==THINK ? 2 : 1;
    const float halo_phase=2*pi*t*halo_cycles;
    /* Still faces stay still. Other expressions inherit their own cadence;
     * Thinking gently passes the pulse from the left lights to the right. */
    halo(&c,f->animation==STILL ? .35F : .5F+.5F*cosf(halo_phase));
    float gx=f->gaze_x,gy=f->gaze_y,tilt=0,open=1,right_open=1;
    if(f->animation==BOB)gy+=3*wave;
    if(f->animation==SWAY)gx+=7*wave;
    if(f->animation==LOOK)gx+=4*wave;
    if(f->animation==TILT)tilt=5*wave;
    if(f->animation==BREATHE||f->animation==PULSE)c.light=.92F+.08F*cosf(2*pi*t);
    if(f->animation==BLINK)open=fabsf(2*t-1);
    else if(f->animation==BREATHE&&t>.89F&&t<.96F)open=fabsf((t-.925F)/.035F);
    right_open=open;
    if(f->animation==WINK&&t>.3F&&t<.6F)right_open=fabsf((t-.45F)/.15F);
    if(f->animation==THINK){
        thought(t,&gx,&gy,&tilt,&right_open);
        open=blink(t,.84F,.89F);right_open*=open;
        c.light=.94F+.06F*cosf(4*pi*t);
    }
    if(f->animation==INQUIRE){
        /* Look, hold the question, then settle; the ring eye opens wider. */
        const float lean=t<.22F ? ease(t/.22F) : t<.5F ? 1 :
                         t<.76F ? 1-ease((t-.5F)/.26F) : 0;
        gx+=5*lean;gy-=2*lean;tilt=5*lean;
        open=(1+.12F*lean)*blink(t,.84F,.90F);right_open=blink(t,.84F,.90F);
    }
    if(f->animation==ATTEND){
        /* An attentive pulse is distinct from the thinking gaze. This is
         * animation, not a representation of microphone signal amplitude. */
        gy-=1.5F*(1-cosf(2*pi*t));
        open=1+.08F*wave;right_open=1;
        c.light=.88F+.12F*cosf(2*pi*t);
    }
    /* Parenthesis-shaped side lights are the recurring visual identity. */
    canvas_t right=c;
    if(f->animation==THINK)halo(&right,.5F+.5F*cosf(halo_phase-pi/2));
    arc(&c,94+gx*.25F,83+gy*.25F,39,40,pi*.78F,pi*1.22F,4.5F);
    arc(&right,226+gx*.25F,83+gy*.25F,39,40,-pi*.22F,pi*.22F,4.5F);
    arc(&c,89,78,45,35,pi*1.04F,pi*1.23F,2);
    arc(&right,231,78,45,35,-pi*.23F,-pi*.04F,2);
    eye(&c,f->left,108+gx,83+gy-tilt,1,open);
    eye(&right,f->right,212+gx,83+gy+tilt,-1,right_open);
    canvas_t a=c;a.color=f->color==CYAN?TEAL:f->color;
    /* Small symbols and speech bars keep a tighter halo for separation. */
    a.halo_width*=.75F;a.halo_inverse=1/a.halo_width;a.halo_strength*=.8F;
    switch(f->accent){
    case NONE:break;
    case SMILE:arc(&a,160,111,16,10,.15F,pi-.15F,2.5F);break;
    case FROWN:arc(&a,160,126,14,8,pi,2*pi,2.5F);break;
    case FLAT_MOUTH:line(&a,150,120,170,120,2.5F);break;
    case OOH:arc(&a,160,120,6,9,0,2*pi,2.5F);break;
    case TEAR: a.color=CYAN;dot(&a,229,103+15*t,3.5F);line(&a,229,99+15*t,229,103+15*t,3);break;
    case SWEAT:a.color=BLUE;dot(&a,240,53+8*t,3);break;
    case SLEEP:{
        float y=120-3*wave;
        line(&a,155,y,166,y,2);line(&a,166,y,155,y+10,2);line(&a,155,y+10,166,y+10,2);
        /* A smaller answering Z rises and settles with the breath. */
        a.light=.45F+.25F*(1-cosf(2*pi*t));y=108-3*sinf(2*pi*t+pi/2);
        line(&a,178,y,184,y,1.5F);line(&a,184,y,178,y+6,1.5F);line(&a,178,y+6,184,y+6,1.5F);break;}
    case SPARK:spark(&a,145,44,3.5F+1.5F*wave);spark(&a,249,116,3.5F-1.5F*wave);break;
    case QUESTION:{
        float y=f->animation==INQUIRE ? -2*wave : 0;
        arc(&a,161,49+y,7,6,pi,2*pi+.7F,2.5F);line(&a,166,53+y,160,59+y,2.5F);dot(&a,160,68+y,1.6F);break;}
    case ELLIPSIS:for(int i=0;i<3;++i){
        const float cycles=f->animation==THINK ? 4 : f->animation==ATTEND ? 2 : 1;
        const float pulse=.5F+.5F*cosf(2*pi*(t*cycles-i/3.F));
        a.light=.3F+.7F*pulse;dot(&a,146+i*14,122-2*pulse,2+1.2F*pulse);
        }break;
    case SPEED:for(int i=0;i<3;++i){line(&a,19,66+i*17,33+5*wave,66+i*17,2);line(&a,287-5*wave,66+i*17,301,66+i*17,2);}break;
    case BUBBLES:for(int i=0;i<3;++i)arc(&a,151+i*12,135-fmodf(t+i*.3F,1)*30,3+i,3+i,0,2*pi,1.5F);break;
    case NOTES:{
        float y=2*wave,x=2*cosf(2*pi*t);
        dot(&a,153+x,126+y,3);line(&a,156+x,126+y,156+x,110+y,2);
        line(&a,156+x,110+y,171+x,106+y,2);line(&a,171+x,106+y,171+x,122+y,2);
        dot(&a,168+x,122+y,3);break;}
    case BLUSH:a.color=PINK;for(int i=0;i<3;++i){line(&a,91+i*6,111,88+i*6,118,2);line(&a,219+i*6,111,216+i*6,118,2);}break;
    case ZIGZAG:for(int i=0;i<4;++i)line(&a,143+i*9,121+(i%2)*5,152+i*9,126-(i%2)*5,2.5F);break;
    case CONFETTI:for(int i=0;i<6;++i){a.color=i%2?PINK:TEAL;spark(&a,70+i*36,25+fmodf(t+i*.17F,1)*14,2.5F);}break;
    }
    if(talking||f->animation==SPEAK){
        canvas_t voice=c;voice.halo_width=8;voice.halo_inverse=1.F/8;voice.halo_strength=.18F;
        for(int i=0;i<5;++i){float h=2+6*fabsf(sinf((float)(elapsed_ms%1500)*.025F+i*.8F));
            line(&voice,144+i*8,139-h,144+i*8,139+h,3);}
    }
}
