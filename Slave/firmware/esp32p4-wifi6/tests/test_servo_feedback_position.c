#include "servo_feedback.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static ainekio_p4_feedback_snapshot_t sample;
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out){*out=sample;}
int main(void)
{
    ainekio_feedback_defaults(&sample.config);
    sample.config.enabled=sample.initialized=true;
    sample.valid_mask=0xffff;
    ainekio_p4_joint_config_t mapping[12];uint16_t targets[12],waiting;
    for(unsigned j=0;j<12;j++) {
        /* Reverse PCA order and rotate mux order independently. Alternating
         * horns and potentiometers have independently reversed directions. */
        mapping[j]=(ainekio_p4_joint_config_t){.channel=11-j,.invert=j%2,
            .home_us=1500,.home_cd=1000,.us_per_degree=10};
        unsigned c=(j+3)%16;
        sample.config.joint[j]=(ainekio_feedback_joint_t){.channel=c,.points=7,
            .point={{j%2?3500:500,500},{2000,1500},{j%2?500:3500,2500}}};
        sample.raw[c]=j%2?1850:2150;sample.sampled_us[c]=1001;
        targets[11-j]=1600;
    }
    assert(ainekio_feedback_config_valid(&sample.config));
    ainekio_v2_frame_t frame={0};
    assert(ainekio_p4_feedback_frame(mapping,&frame));
    for(unsigned j=0;j<12;j++)assert(fabs(frame.position[j]-(j%2?0:2000))<1e-6);
    assert(ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting)&&!waiting);
    /* A physically wrong target, not the command receipt, controls arrival. */
    targets[mapping[4].channel]=1700;
    assert(!ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting));assert(waiting==(1U<<4));
    sample.config.tolerance_us=100;
    assert(ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting));
    sample.config.tolerance_us=30;targets[mapping[4].channel]=1600;
    sample.sampled_us[sample.config.joint[5].channel]=1000;
    assert(!ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting));assert(waiting==(1U<<5));
    sample.sampled_us[sample.config.joint[5].channel]=1001;
    sample.valid_mask&=~(1U<<sample.config.joint[2].channel);
    assert(!ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting));assert(waiting==(1U<<2));
    assert(!ainekio_p4_feedback_frame(mapping,&frame));
    targets[mapping[2].channel]=0; /* Startup's uncommanded shoulders do not hold a fold. */
    assert(ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting));
    sample.config.enabled=false;
    assert(!ainekio_p4_feedback_arrived(mapping,targets,1000,&waiting));
    puts("Feedback arrival: independent mux/PCA mappings, reversed sensors/horns, tolerance, new samples and uncommanded outputs passed.");
}
