#include "ainekio/v2_motion.h"
#include <inttypes.h>
#include <stdio.h>

int main(void)
{
    uint64_t time;
    unsigned cycles;
    while (scanf("%u %" SCNu64, &cycles, &time)==2) {
        ainekio_v2_frame_t frame;
        if (cycles > 10 || !ainekio_v2_walk_sample(cycles,time,&frame)) return 1;
        printf("[");
        for (unsigned joint=0; joint<12; ++joint) printf("%s%.9g",joint ? "," : "",frame.position[joint]);
        puts("]");
    }
    return 0;
}
