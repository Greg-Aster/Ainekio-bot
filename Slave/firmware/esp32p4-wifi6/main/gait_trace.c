#include "gait_trace.h"
void ainekio_gait_trace_push(ainekio_gait_trace_ring_t *r,const ainekio_gait_trace_event_t *e)
{
    r->events[r->latest%r->capacity]=*e;
    ++r->latest;
}
uint64_t ainekio_gait_trace_oldest(const ainekio_gait_trace_ring_t *r)
{
    return r->latest ? (r->latest>r->capacity?r->latest-r->capacity+1:1) : 0;
}
bool ainekio_gait_trace_read(const ainekio_gait_trace_ring_t *r,uint64_t n,ainekio_gait_trace_event_t *e)
{
    if(!n||n>r->latest||n<ainekio_gait_trace_oldest(r))return false;
    *e=r->events[(n-1)%r->capacity];return true;
}
