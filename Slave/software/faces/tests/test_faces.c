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

    /* V3 single-eye Cyclops renderer contract: all 59 faces, border clearance,
     * central iris/pupil/glint anatomy, expression distinctness, and vocal modulation. */
    for(size_t i=0;i<ainekio_face_count();++i){
        const uint32_t period=ainekio_face_period_ms(i);
        for(unsigned step=0;step<4;++step){
            const uint64_t t=(uint64_t)period*step/4U;
            for(unsigned talking=0;talking<2;++talking){
                guarded[0]=guarded[sizeof(guarded)/sizeof(guarded[0])-1]=0xa55a;
                ainekio_face_cyclops_render(i,t,talking!=0,guarded+1);
                assert(guarded[0]==0xa55a&&guarded[sizeof(guarded)/sizeof(guarded[0])-1]==0xa55a);
                unsigned lit=0;for(unsigned j=1;j<sizeof(guarded)/sizeof(guarded[0])-1;++j)lit+=guarded[j]!=0;
                assert(lit>1000&&lit<AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT*3/4);
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
    ainekio_face_cyclops_render(base,0,false,reference);
    /* Outer iris ring at center top/bottom and inner pupil ring around center must be lit. */
    assert(reference[(85-61)*320+160]&&reference[(85+61)*320+160]);
    assert(reference[85*320+(160-26)]&&reference[85*320+(160+26)]);
    /* Flanking radar arcs on both left and right sides must be lit. */
    assert(reference[85*320+(160-85)]&&reference[85*320+(160+85)]);
    /* Determinism and vocal modulation check. */
    ainekio_face_cyclops_render(base,0,false,guarded+1);
    assert(!memcmp(reference,guarded+1,sizeof(reference)));
    ainekio_face_cyclops_render(base,0,true,guarded+1);
    assert(memcmp(reference,guarded+1,sizeof(reference)));
    /* Idle cyclops glance cycle: verify right glance (~3.5s) and left glance (~9.0s)
     * shift lit mass across the panoramic canvas while preserving clean borders. */
    static uint16_t glance_r[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT],glance_l[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT];
    ainekio_face_cyclops_render(base,3500,false,glance_r);
    ainekio_face_cyclops_render(base,9000,false,glance_l);
    double sum_r=0,cnt_r=0,sum_l=0,cnt_l=0;
    for(unsigned y=0;y<AINEKIO_FACE_HEIGHT;++y)
        for(unsigned x=0;x<AINEKIO_FACE_WIDTH;++x){
            if(x==0||x==AINEKIO_FACE_WIDTH-1||y==0||y==AINEKIO_FACE_HEIGHT-1){
                assert(!glance_r[y*AINEKIO_FACE_WIDTH+x]&&!glance_l[y*AINEKIO_FACE_WIDTH+x]);
            }
            if(glance_r[y*AINEKIO_FACE_WIDTH+x]){sum_r+=x;cnt_r+=1;}
            if(glance_l[y*AINEKIO_FACE_WIDTH+x]){sum_l+=x;cnt_l+=1;}
        }
    assert(cnt_r>1000&&cnt_l>1000);
    assert(sum_r/cnt_r>175.0&&sum_l/cnt_l<145.0);
    /* Distinct expressions must produce distinct frames. */
    const char *distinct[]={"happy","angry","surprised","love","sleepy","sad","excited","curious","freaky","dead"};
    for(size_t k=0;k<sizeof(distinct)/sizeof(distinct[0]);++k){
        size_t idx;assert(ainekio_face_find(distinct[k],&idx));
        ainekio_face_cyclops_render(idx,250,false,guarded+1);
        assert(memcmp(reference,guarded+1,sizeof(reference)));
    }
    printf("%zu V3 cyclops faces: ring/arc geometry, border clearance, expressions and speech overlay passed\n",ainekio_face_count());
    return 0;
}
