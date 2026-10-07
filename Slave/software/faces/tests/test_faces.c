#include "ainekio/face.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint16_t guarded[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT+2],reference[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT];
int main(void)
{
    for(size_t i=0;i<ainekio_face_count();++i){
        size_t resolved;assert(ainekio_face_find(ainekio_face_name(i),&resolved)&&resolved==i);
        for(unsigned t=0;t<ainekio_face_period_ms(i);t+=97){
            guarded[0]=guarded[sizeof(guarded)/sizeof(guarded[0])-1]=0xa55a;
            ainekio_face_render(i,t,false,guarded+1);
            assert(guarded[0]==0xa55a&&guarded[sizeof(guarded)/sizeof(guarded[0])-1]==0xa55a);
            unsigned lit=0;for(unsigned j=1;j<sizeof(guarded)/sizeof(guarded[0])-1;++j)lit+=guarded[j]!=0;
            assert(lit>100&&lit<AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT/2);
        }
    }
    size_t base;assert(ainekio_face_find("default",&base));
    ainekio_face_render(base,0,false,reference);
    assert(reference[83*320+108]&&reference[83*320+212]);
    assert(!reference[83*320+160]); /* the concept has no central eye/mouth */
    ainekio_face_render(base,0,true,guarded+1);assert(memcmp(reference,guarded+1,sizeof(reference)));
    size_t unused;assert(!ainekio_face_find("missing_face",&unused));
    printf("%zu wide faces: rendering, bounds, concept pupils and speech overlay passed\n",ainekio_face_count());
    return 0;
}
