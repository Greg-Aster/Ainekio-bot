#include "ainekio/face.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint16_t pixels[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT];
int main(int argc,char **argv)
{
    bool cyclops=false;
    int arg=1;
    if(argc>1&&!strcmp(argv[1],"--cyclops")){cyclops=true;arg=2;}
    if(argc==arg+1&&!strcmp(argv[arg],"--list")){
        for(size_t i=0;i<ainekio_face_count();++i)printf("%s %u\n",ainekio_face_name(i),ainekio_face_period_ms(i));
        return 0;
    }
    size_t index;
    if(argc<=arg||!ainekio_face_find(argv[arg],&index))return 1;
    const uint64_t elapsed=argc>arg+1?strtoull(argv[arg+1],NULL,10):0;
    const bool talking=argc>arg+2;
    if(cyclops)ainekio_face_cyclops_render(index,elapsed,talking,pixels);
    else ainekio_face_render(index,elapsed,talking,pixels);
    printf("P6\n%d %d\n255\n",AINEKIO_FACE_WIDTH,AINEKIO_FACE_HEIGHT);
    for(size_t i=0;i<sizeof(pixels)/sizeof(pixels[0]);++i){
        unsigned p=pixels[i];unsigned char rgb[]={(p>>11)*255/31,((p>>5)&63)*255/63,(p&31)*255/31};
        fwrite(rgb,1,3,stdout);
    }
    return ferror(stdout)?1:0;
}
