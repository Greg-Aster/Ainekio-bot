#include "gait_trace.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    ainekio_gait_trace_event_t storage[3],out;
    ainekio_gait_trace_ring_t ring={.events=storage,.capacity=3};
    assert(!ainekio_gait_trace_oldest(&ring));
    assert(!ainekio_gait_trace_read(&ring,1,&out));
    for(unsigned i=1;i<=5;i++) {
        ainekio_gait_trace_event_t e={.kind=i%2?AINEKIO_TRACE_OUTPUT:AINEKIO_TRACE_SAMPLE,.time_us=i*20000};
        if(e.kind==AINEKIO_TRACE_SAMPLE){e.sample.sampled_us[15]=e.time_us-5;e.sample.valid_mask=0xfff0;e.sample.raw[15]=i;}
        else e.output.pulses[11]=1000+i;
        ainekio_gait_trace_push(&ring,&e);
    }
    assert(ring.latest==5 && ainekio_gait_trace_oldest(&ring)==3);
    assert(!ainekio_gait_trace_read(&ring,2,&out));
    assert(!ainekio_gait_trace_read(&ring,6,&out));
    assert(ainekio_gait_trace_read(&ring,3,&out)&&out.output.pulses[11]==1003);
    assert(ainekio_gait_trace_read(&ring,4,&out)&&out.sample.sampled_us[15]==79995&&out.sample.raw[15]==4);
    assert(ainekio_gait_trace_read(&ring,5,&out)&&out.output.pulses[11]==1005);
    assert(ainekio_gait_trace_read(&ring,3,&out)); /* reads never consume */
    ring.latest=0;assert(!ainekio_gait_trace_read(&ring,3,&out));
    ainekio_gait_trace_event_t e={.kind=AINEKIO_TRACE_SAMPLE,.time_us=100000};
    ainekio_gait_trace_push(&ring,&e);assert(ainekio_gait_trace_read(&ring,1,&out)&&out.time_us==100000);
    printf("Gait journal: mixed events, retained timestamps, overwrite visibility, reread and session reset passed; event %zu bytes.\n",sizeof e);
}
