/* Offline library-wide pulse ranges with the installed mirrored calibration. */
#include "joint_calibration.h"
#include "ainekio/v2_motion.h"
#include "ainekio/v2_limits.h"
#include <assert.h>
#include <stdio.h>

static ainekio_p4_joint_config_t joints[12];
static unsigned minimum = 65535, maximum;
static void check(const char *name,const ainekio_v2_frame_t *frame)
{
    uint16_t pulses[12];
    assert(ainekio_p4_joint_map_frame(joints,frame,pulses));
    for(unsigned i=0;i<12;i++) {
        if(pulses[i]<400||pulses[i]>2900)fprintf(stderr,"%s joint %u: %u us\n",name,i,pulses[i]);
        assert(pulses[i]>=400&&pulses[i]<=2900);
        if(pulses[i]<minimum)minimum=pulses[i];
        if(pulses[i]>maximum)maximum=pulses[i];
    }
}
int main(void)
{
    const unsigned home[12]={1600,2444,2577,1670,856,723,1670,2444,2577,1760,856,723};
    assert(ainekio_p4_joint_defaults(joints));
    for(unsigned i=0;i<12;i++){joints[i].home_us=home[i];joints[i].invert=(i/3)%2==0;}
    for(size_t i=0;i<ainekio_v2_clip_count;i++) {
        minimum=65535;maximum=0;
        ainekio_v2_frame_t low,high,entry;
        assert(ainekio_v2_clip_bounds(i,&low,&high));
        check(ainekio_v2_clips[i].command,&low);check(ainekio_v2_clips[i].command,&high);
        printf("%s: %u-%u us\n",ainekio_v2_clips[i].command,minimum,maximum);
        assert(ainekio_v2_clip_sample(i,0,&entry));
        for(size_t from=0;from<=ainekio_v2_clip_count;from++) {
            ainekio_v2_frame_t start=entry,pose;
            if(from==ainekio_v2_clip_count)for(unsigned j=0;j<12;j++)start.position[j]=joints[j].home_cd;
            else assert(ainekio_v2_clip_sample(from,UINT64_MAX,&start));
            for(unsigned u=0;u<=1000;u++) {
                assert(ainekio_v2_transition(&start,&entry,u/1000.,&pose));
                check(ainekio_v2_clips[i].command,&pose);
            }
        }
    }
    puts("All 23 clip extrema and Home/terminal-pose entry paths fit 400-2900 us.");
}
