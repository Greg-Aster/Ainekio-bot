#define _POSIX_C_SOURCE 200809L
#include "ainekio/face.h"
#include <inttypes.h>
#include <stdio.h>
#include <time.h>

/* Compare the same sampled workload across renderer builds. Desktop elapsed
 * time is not a P4 measurement; this executable never runs on the robot. */
static uint16_t pixels[AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT];
static uint64_t nanoseconds(void)
{
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC,&time);
    return (uint64_t)time.tv_sec*1000000000U+(uint64_t)time.tv_nsec;
}
int main(void)
{
    puts("face,frames,nanoseconds,checksum");
    for(size_t face=0;face<ainekio_face_count();++face){
        uint64_t elapsed[3],checksum=0;
        const uint32_t period=ainekio_face_period_ms(face);
        for(unsigned repeat=0;repeat<3;++repeat){
            const uint64_t start=nanoseconds();
            for(unsigned frame=0;frame<64;++frame){
                ainekio_face_render(face,(uint64_t)period*frame/64,frame%2!=0,pixels);
                checksum+=pixels[(frame*839)% (AINEKIO_FACE_WIDTH*AINEKIO_FACE_HEIGHT)];
            }
            elapsed[repeat]=nanoseconds()-start;
        }
        /* Median of three complete passes reduces scheduler noise. */
        if(elapsed[0]>elapsed[1]){uint64_t t=elapsed[0];elapsed[0]=elapsed[1];elapsed[1]=t;}
        if(elapsed[1]>elapsed[2]){uint64_t t=elapsed[1];elapsed[1]=elapsed[2];elapsed[2]=t;}
        if(elapsed[0]>elapsed[1])elapsed[1]=elapsed[0];
        printf("%s,64,%" PRIu64 ",%" PRIu64 "\n",
            ainekio_face_name(face),elapsed[1],checksum);
    }
    return 0;
}
