#include "ainekio/v2_limits.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
static void path(const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to)
{
    ainekio_v2_frame_t lo,hi,actual,previous;double derivative[12];
    assert(ainekio_v2_transition_bounds(from,to,&lo,&hi,derivative));
    for(unsigned n=0;n<=2000;n++) {
        assert(ainekio_v2_transition(from,to,n/2000.,&actual));
        assert(ainekio_v2_limits_frame(&actual));
        for(unsigned j=0;j<12;j++) {
            assert(actual.position[j]>=lo.position[j]-.003f && actual.position[j]<=hi.position[j]+.003f);
            /* The continuous derivative bound excludes float output rounding.
             * Allow 0.0001 degree for the difference of two rounded samples. */
            if(n)assert(fabs(actual.position[j]-previous.position[j])<=derivative[j]/2000.+.01);

        }
        previous=actual;
    }
    for(unsigned j=0;j<12;j++)assert(fabs(actual.position[j]-to->position[j])<.003);
}
int main(void)
{
    ainekio_v2_frame_t center={0},stand={0},invalid={0};
    for(unsigned j=0;j<12;j++)center.position[j]=(float)(100.*ainekio_v2_center_degrees(j));
    assert(ainekio_v2_pulse_reference()==1300);
    assert(ainekio_v2_limits_frame(&center));
    invalid.position[1]=6000; /* Cannot close the actual rod/pickup triangle at crank zero. */
    assert(!ainekio_v2_limits_frame(&invalid));
    assert(!ainekio_v2_transition(&invalid,&center,.5,&stand));
    invalid.position[1]=NAN;assert(!ainekio_v2_limits_frame(&invalid));
    for(size_t i=0;i<ainekio_v2_clip_count;i++) {
        ainekio_v2_frame_t start,end;
        assert(ainekio_v2_clip_sample(i,0,&start));
        assert(ainekio_v2_clip_sample(i,ainekio_v2_clips[i].duration_us,&end));
        path(&center,&start);
        assert(ainekio_v2_limits_frame(&end));path(&end,&start);path(&end,&center);
    }
    puts("Direct linkage and continuous transition bounds cover all clip entry/exit poses.");
    return 0;
}
