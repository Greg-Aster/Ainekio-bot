#include "ainekio/face.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint16_t pixels[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT];
int main(int argc,char **argv)
{
    if(argc==2&&!strcmp(argv[1],"--list")){
        for(size_t i=0;i<ainekio_face_count();++i)printf("%s %u\n",ainekio_face_name(i),ainekio_face_period_ms(i));
        return 0;
    }
    size_t index;
    if(argc<2||!ainekio_face_find(argv[1],&index))return 1;
    ainekio_face_render(index,argc>2?strtoull(argv[2],NULL,10):0,argc>3,pixels);
    printf("P6\n%d %d\n255\n",AINEKIO_FACE_WIDTH,AINEKIO_FACE_HEIGHT);
    for(size_t i=0;i<sizeof(pixels)/sizeof(pixels[0]);++i){
        unsigned p=pixels[i];unsigned char rgb[]={(p>>11)*255/31,((p>>5)&63)*255/63,(p&31)*255/31};
        fwrite(rgb,1,3,stdout);
    }
    return ferror(stdout)?1:0;
}
