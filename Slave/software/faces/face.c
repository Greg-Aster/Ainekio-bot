#include "ainekio/face.h"
#include <math.h>
#include <string.h>

enum eye { DOT, CHEER, SAD, SLANT, RING, FLAT, HEART, STAR, CHEVRON, CROSS, SPIRAL };
enum animation { STILL, BREATHE, BLINK, BOB, SPEAK, PULSE, TILT, LOOK, SWAY, WINK };
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
 * primitive count. Each stroke uses maximum blending so joints do not flare. */
typedef struct { uint16_t *pixels; uint32_t color; float light; } canvas_t;
static void pixel(canvas_t *c,int x,int y,float distance,float radius)
{
    float edge=distance-radius;
    float halo=fmaxf(0.F,1.F-fmaxf(0.F,edge)/8.F);
    float coverage=fminf(1.F,fmaxf(0.F,.8F-edge));
    float core=fminf(1.F,fmaxf(0.F,-edge-1.F))*.85F;
    float glow=(coverage+halo*halo*.18F)*c->light;
    unsigned r=(unsigned)fminf(255,((c->color>>16)&255)*glow+180*core);
    unsigned g=(unsigned)fminf(255,((c->color>>8)&255)*glow+180*core);
    unsigned b=(unsigned)fminf(255,(c->color&255)*glow+180*core);
    uint16_t *p=&c->pixels[y*AINEKIO_FACE_WIDTH+x];
    r=fmaxf(r>>3,(*p>>11)&31); g=fmaxf(g>>2,(*p>>5)&63); b=fmaxf(b>>3,*p&31);
    *p=(uint16_t)((r<<11)|(g<<5)|b);
}
static void line(canvas_t *c,float ax,float ay,float bx,float by,float width)
{
    float radius=width*.5F, pad=radius+8,dx=bx-ax,dy=by-ay,length=dx*dx+dy*dy;
    int x0=(int)fmaxf(0,floorf(fminf(ax,bx)-pad)),x1=(int)fminf(319,ceilf(fmaxf(ax,bx)+pad));
    int y0=(int)fmaxf(0,floorf(fminf(ay,by)-pad)),y1=(int)fminf(169,ceilf(fmaxf(ay,by)+pad));
    for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){
        float u=length>0 ? fminf(1,fmaxf(0,((x-ax)*dx+(y-ay)*dy)/length)) : 0;
        float px=x-ax-u*dx,py=y-ay-u*dy;
        pixel(c,x,y,sqrtf(px*px+py*py),radius);
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

void ainekio_face_render(size_t index,uint64_t elapsed_ms,bool talking,
                        uint16_t pixels[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT])
{
    if(!pixels)return;
    memset(pixels,0,AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT*sizeof(*pixels));
    if(index>=ainekio_face_count())return;
    const face_t *f=&faces[index];
    const float pi=3.141592654F,t=(float)(elapsed_ms%f->period_ms)/f->period_ms;
    const float wave=sinf(2*pi*t);
    canvas_t c={pixels,f->color,1};
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
    /* Parenthesis-shaped side lights are the recurring visual identity. */
    arc(&c,94+gx*.25F,83+gy*.25F,39,40,pi*.78F,pi*1.22F,4.5F);
    arc(&c,226+gx*.25F,83+gy*.25F,39,40,-pi*.22F,pi*.22F,4.5F);
    arc(&c,89,78,45,35,pi*1.04F,pi*1.23F,2);
    arc(&c,231,78,45,35,-pi*.23F,-pi*.04F,2);
    eye(&c,f->left,108+gx,83+gy-tilt,1,open);
    eye(&c,f->right,212+gx,83+gy+tilt,-1,right_open);
    canvas_t a=c;a.color=f->color==CYAN?TEAL:f->color;
    switch(f->accent){
    case NONE:break;
    case SMILE:arc(&a,160,111,16,10,.15F,pi-.15F,2.5F);break;
    case FROWN:arc(&a,160,126,14,8,pi,2*pi,2.5F);break;
    case FLAT_MOUTH:line(&a,150,120,170,120,2.5F);break;
    case OOH:arc(&a,160,120,6,9,0,2*pi,2.5F);break;
    case TEAR: a.color=CYAN;dot(&a,229,103+15*t,3.5F);line(&a,229,99+15*t,229,103+15*t,3);break;
    case SWEAT:a.color=BLUE;dot(&a,240,53+8*t,3);break;
    case SLEEP:line(&a,155,120,166,120,2);line(&a,166,120,155,130,2);line(&a,155,130,166,130,2);break;
    case SPARK:spark(&a,145,44,3+2*t);spark(&a,249,116,4-2*t);break;
    case QUESTION:arc(&a,161,49,7,6,pi,2*pi+.7F,2.5F);line(&a,166,53,160,59,2.5F);dot(&a,160,68,1.6F);break;
    case ELLIPSIS:for(int i=0;i<3;++i){a.light=.4F+.6F*(fmodf(t*3,3)>=i);dot(&a,148+i*12,122,2);}break;
    case SPEED:for(int i=0;i<3;++i){line(&a,19,66+i*17,33+5*wave,66+i*17,2);line(&a,287-5*wave,66+i*17,301,66+i*17,2);}break;
    case BUBBLES:for(int i=0;i<3;++i)arc(&a,151+i*12,135-fmodf(t+i*.3F,1)*30,3+i,3+i,0,2*pi,1.5F);break;
    case NOTES:dot(&a,153,126,3);line(&a,156,126,156,110,2);line(&a,156,110,171,106,2);line(&a,171,106,171,122,2);dot(&a,168,122,3);break;
    case BLUSH:a.color=PINK;for(int i=0;i<3;++i){line(&a,91+i*6,111,88+i*6,118,2);line(&a,219+i*6,111,216+i*6,118,2);}break;
    case ZIGZAG:for(int i=0;i<4;++i)line(&a,143+i*9,121+(i%2)*5,152+i*9,126-(i%2)*5,2.5F);break;
    case CONFETTI:for(int i=0;i<6;++i){a.color=i%2?PINK:TEAL;spark(&a,70+i*36,25+fmodf(t+i*.17F,1)*14,2.5F);}break;
    }
    if(talking||f->animation==SPEAK){
        for(int i=0;i<5;++i){float h=2+6*fabsf(sinf((float)(elapsed_ms%1500)*.025F+i*.8F));
            line(&c,144+i*8,139-h,144+i*8,139+h,3);}
    }
}
