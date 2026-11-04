#include "ainekio/face.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint16_t guarded[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT+2],reference[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT];
int main(void)
{
    for(size_t i=0;i<ainekio_face_count();++i){
        size_t resolved;assert(ainekio_face_find(ainekio_face_name(i),&resolved)&&resolved==i);
        for(unsigned t=0;t<ainekio_face_period_ms(i);t+=17){
          for(unsigned talking=0;talking<2;++talking){
            guarded[0]=guarded[sizeof(guarded)/sizeof(guarded[0])-1]=0xa55a;
            ainekio_face_render(i,t,talking!=0,guarded+1);
            assert(guarded[0]==0xa55a&&guarded[sizeof(guarded)/sizeof(guarded[0])-1]==0xa55a);
            unsigned lit=0;for(unsigned j=1;j<sizeof(guarded)/sizeof(guarded[0])-1;++j)lit+=guarded[j]!=0;
            assert(lit>100&&lit<AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT/2);
            for(unsigned x=0;x<AINEKIO_FACE_WIDTH;++x){
                assert(!guarded[1+x]);
                assert(!guarded[1+(AINEKIO_FACE_HEIGHT-1)*AINEKIO_FACE_WIDTH+x]);
            }
            for(unsigned y=0;y<AINEKIO_FACE_HEIGHT;++y){
                assert(!guarded[1+y*AINEKIO_FACE_WIDTH]);
                assert(!guarded[1+y*AINEKIO_FACE_WIDTH+AINEKIO_FACE_WIDTH-1]);
            }
          }
        }
    }
    size_t base;assert(ainekio_face_find("default",&base));
    ainekio_face_render(base,0,false,reference);
    assert(reference[93*320+82]&&reference[93*320+238]);
    assert(!reference[93*320+AINEKIO_FACE_WIDTH/2]); /* no central eye/mouth */
    unsigned left=320,right=0,top=170,bottom=0;
    for(unsigned y=0;y<AINEKIO_FACE_HEIGHT;++y)
        for(unsigned x=0;x<AINEKIO_FACE_WIDTH;++x){
            if(x)assert(reference[y*AINEKIO_FACE_WIDTH+x]==reference[y*AINEKIO_FACE_WIDTH+AINEKIO_FACE_WIDTH-x]);
            if(reference[y*AINEKIO_FACE_WIDTH+x]){
                if(x<left)left=x;
                if(x>right)right=x;
                if(y<top)top=y;
                if(y>bottom)bottom=y;
            }
        }
    /* Retain the approved width/height and move the complete face down 10 px. */
    assert(left<12&&right>308&&left==AINEKIO_FACE_WIDTH-right);
    assert(top==46&&bottom==146);
    ainekio_face_render(base,0,false,guarded+1);
    assert(!memcmp(reference,guarded+1,sizeof(reference)));
    ainekio_face_render(base,0,true,guarded+1);assert(memcmp(reference,guarded+1,sizeof(reference)));
    size_t unused;assert(!ainekio_face_find("missing_face",&unused));
    printf("%zu wide faces: full-panel centering, size, animated glow clearance and speech overlay passed\n",ainekio_face_count());
    return 0;
}
