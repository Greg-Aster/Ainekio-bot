#include "servo_feedback.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static ainekio_p4_feedback_snapshot_t sample;
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out){*out=sample;}
static bool arrived(const ainekio_p4_joint_config_t *mapping,const uint16_t *targets,
    int64_t since,uint16_t *remaining)
{
    return ainekio_p4_feedback_check(mapping,targets,since,remaining) && !*remaining;
}
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
        sample.filtered_raw[c]=sample.raw[c];sample.velocity_raw_s[c]=30;
        targets[11-j]=1600;
    }
    assert(ainekio_feedback_config_valid(&sample.config));
    ainekio_v2_frame_t frame={0};
    assert(ainekio_p4_feedback_frame(mapping,&frame));
    for(unsigned j=0;j<12;j++)assert(fabs(frame.position[j]-(j%2?0:2000))<1e-6);
    for(unsigned j=0;j<12;j++)assert(fabs(frame.velocity[j]-200)<1e-6);
    /* Arrival and level feedback use the same filtered shaft position. Raw
     * calibration capture remains independent. */
    sample.filtered_raw[sample.config.joint[0].channel]+=15;
    assert(ainekio_p4_feedback_frame(mapping,&frame));
    assert(fabs(frame.position[0]-2100)<1e-6);
    assert(arrived(mapping,targets,1000,&waiting)&&!waiting);
    /* Verification compares measured pulse equivalents directly with each
     * output's target; mirrored model angles do not become trajectory inputs. */
    assert(ainekio_p4_feedback_check(mapping,targets,1000,&waiting));
    assert(!waiting);
    /* A physically wrong target, not the command receipt, controls arrival. */
    targets[mapping[4].channel]=1700;
    assert(ainekio_p4_feedback_check(mapping,targets,1000,&waiting));assert(waiting==(1U<<4));
    sample.config.tolerance_us=400;
    assert(!arrived(mapping,targets,1000,&waiting));
    sample.config.arrival_tolerance_us=100;
    assert(arrived(mapping,targets,1000,&waiting));
    sample.config.tolerance_us=30;sample.config.arrival_tolerance_us=30;targets[mapping[4].channel]=1600;
    sample.sampled_us[sample.config.joint[5].channel]=1000;
    assert(!arrived(mapping,targets,1000,&waiting));assert(waiting==(1U<<5));
    sample.sampled_us[sample.config.joint[5].channel]=1001;
    sample.valid_mask&=~(1U<<sample.config.joint[2].channel);
    assert(!arrived(mapping,targets,1000,&waiting));assert(waiting==(1U<<2));
    assert(!ainekio_p4_feedback_frame(mapping,&frame));
    targets[mapping[2].channel]=0; /* Startup's uncommanded shoulders do not hold a fold. */
    assert(arrived(mapping,targets,1000,&waiting));
    sample.valid_mask=0xffff;sample.config.stand_enabled=false;sample.config.jam_enabled=true;
    sample.config.no_progress_ms=1000;sample.config.progress_us=5;
    ainekio_p4_feedback_progress_t progress={0};
    for(unsigned j=0;j<12;j++)targets[mapping[j].channel]=2200;
    for(unsigned n=1;n<=120;n++) {
        for(unsigned j=0;j<12;j++) {
            unsigned c=sample.config.joint[j].channel;
            sample.sampled_us[c]=1000000+n*20000;
            /* Joint 4 is stuck with oscillating noise, joint 7 makes slow
             * steady progress; remaining joints have already reached target. */
            const double pulse=j==4 ? 1600+(n%2?2:-2) : j==7 ? 1600+n*.2 : 2200;
            sample.filtered_raw[c]=2000+(j%2?-1:1)*(pulse-1500)*1.5;
        }
        uint16_t mask=ainekio_p4_feedback_stalled(&progress,mapping,targets);
        if(n>55)assert(mask==(1U<<4));
        if(n<50)assert(!mask);
    }
    /* Jam-only mode above detects blocked travel without coordinating targets.
     * Conversely, measured coordination alone must never release outputs. */
    sample.config.jam_enabled=false;sample.config.stand_enabled=true;
    for(unsigned j=0;j<12;j++)sample.sampled_us[sample.config.joint[j].channel]+=2000000;
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    assert(!arrived(mapping,targets,1000,&waiting));
    assert(waiting&(1U<<4));
    for(unsigned j=0;j<12;j++)assert(!progress.joint[j].progress_at);
    sample.config.jam_enabled=true;
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    /* No new observation, disabled outputs and missing input cannot prove a stall. */
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    sample.valid_mask&=~(1U<<sample.config.joint[4].channel);
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    targets[mapping[4].channel]=0;
    sample.valid_mask=0xffff;
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    sample.config.no_progress_ms=0;
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    sample.config.enabled=false;
    assert(!arrived(mapping,targets,1000,&waiting));
    /* With jam protection off, there is no continuous non-progress tracking.
     * Final verification uses only arrival tolerance, independently of jam settings. */
    sample.config.enabled=sample.config.stand_enabled=true;sample.config.jam_enabled=false;
    sample.config.arrival_tolerance_us=30;sample.config.tolerance_us=400;
    sample.config.no_progress_ms=1000;progress=(ainekio_p4_feedback_progress_t){0};
    for(unsigned j=0;j<12;j++) {
        unsigned c=sample.config.joint[j].channel;
        targets[mapping[j].channel]=1800;
        sample.filtered_raw[c]=2000+(j%2?-1:1)*100*1.5; /* 1600 us, 200 us short */
    }
    for(unsigned n=0;n<=60;n++) {
        for(unsigned j=0;j<12;j++)sample.sampled_us[sample.config.joint[j].channel]=10000000+n*20000;
        assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    }
    for(unsigned j=0;j<12;j++)assert(!progress.joint[j].progress_at);
    assert(!arrived(mapping,targets,1000,&waiting));
    for(unsigned j=0;j<12;j++) {
        unsigned c=sample.config.joint[j].channel;
        sample.filtered_raw[c]=2000+(j%2?-1:1)*300*1.5;
        sample.sampled_us[c]+=20000;
    }
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    assert(arrived(mapping,targets,1000,&waiting));
    /* The same observer can consume only completed-pass observations. Its
     * no-progress window remains elapsed seconds, not a count of passes. */
    sample.config.jam_enabled=true;sample.config.no_progress_ms=3000;
    sample.config.tolerance_us=200;sample.config.progress_us=15;
    progress=(ainekio_p4_feedback_progress_t){0};
    const int64_t pass_times[]={20000000,20100000,21000000,22990000,23000000};
    for(unsigned n=0;n<5;n++) {
        for(unsigned j=0;j<12;j++) {
            const unsigned c=sample.config.joint[j].channel;
            targets[mapping[j].channel]=2200;
            const double pulse=j==4?1600:2200;
            sample.filtered_raw[c]=2000+(j%2?-1:1)*(pulse-1500)*1.5;
            sample.sampled_us[c]=pass_times[n];
        }
        const uint16_t stalled=ainekio_p4_feedback_stalled(&progress,mapping,targets);
        assert(stalled==(n==4?(1U<<4):0));
    }
    /* Recorded ground-fault shape: all signals below their captured ranges.
     * Extrapolated diagnostics remain possible, but they cannot prove a jam
     * or create a measured position for corrective control. */
    ainekio_p4_feedback_snapshot_t healthy=sample;
    for(unsigned j=0;j<12;j++) {
        unsigned c=sample.config.joint[j].channel;
        sample.raw[c]=sample.filtered_raw[c]=100;
        sample.sampled_us[c]+=4000000;
    }
    ainekio_p4_feedback_health_t health;ainekio_p4_feedback_health(&sample,&health);
    assert(health.calibrated==0xfff && health.below_calibration==0xfff);
    assert(!health.unavailable && !health.clipped && !health.above_calibration);
    assert(!ainekio_p4_feedback_frame(mapping,&frame));
    assert(!arrived(mapping,targets,1000,&waiting) && waiting==0xfff);
    assert(!ainekio_p4_feedback_stalled(&progress,mapping,targets));
    for(unsigned j=0;j<12;j++)assert(!progress.joint[j].progress_at);
    sample=healthy;
    sample.raw[sample.config.joint[0].channel]=4095;
    sample.valid_mask&=~(1U<<sample.config.joint[1].channel);
    ainekio_p4_feedback_health(&sample,&health);
    assert(health.clipped==1 && health.above_calibration==1 && health.unavailable==2);
    sample=healthy;ainekio_p4_feedback_health(&sample,&health);
    assert(!(health.unavailable|health.clipped|health.below_calibration|health.above_calibration));
    assert(ainekio_p4_feedback_frame(mapping,&frame));
    /* Reproduce the live Wave endpoint: command 500 us, raw 254 against a
     * calibration endpoint at raw 258, filtered equivalent about 495 us. */
    sample.config.arrival_tolerance_us=30;
    for(unsigned j=0;j<12;j++) {
        double pulse;bool in_range;
        assert(ainekio_feedback_position(&sample.config.joint[j],
            sample.filtered_raw[sample.config.joint[j].channel],&pulse,&in_range));
        targets[mapping[j].channel]=(uint16_t)lround(pulse);
    }
    const unsigned c=sample.config.joint[4].channel;
    sample.config.joint[4].point[0]=(ainekio_feedback_point_t){258,500};
    sample.config.joint[4].point[1]=(ainekio_feedback_point_t){1754,1650};
    sample.config.joint[4].point[2]=(ainekio_feedback_point_t){3266,2800};
    targets[mapping[4].channel]=500;
    sample.raw[c]=254;sample.filtered_raw[c]=251.180862F;
    assert(arrived(mapping,targets,1000,&waiting));
    ainekio_p4_feedback_health(&sample,&health);assert(health.below_calibration==(1U<<4));
    assert(!ainekio_p4_feedback_frame(mapping,&frame)); /* No extrapolated balance input. */
    targets[mapping[4].channel]=600;
    assert(!arrived(mapping,targets,1000,&waiting) && waiting==(1U<<4));
    targets[mapping[4].channel]=500;
    sample.raw[c]=sample.filtered_raw[c]=100;
    assert(!arrived(mapping,targets,1000,&waiting)); /* Actual target error remains. */
    sample.raw[c]=254;sample.filtered_raw[c]=251.180862F;sample.sampled_us[c]=1000;
    assert(!arrived(mapping,targets,1000,&waiting));
    sample.sampled_us[c]=1001;sample.raw[c]=0;
    assert(!arrived(mapping,targets,1000,&waiting));
    /* Both endpoints and either ADC direction have the same tolerance. */
    for(unsigned reverse=0;reverse<2;reverse++)for(unsigned upper=0;upper<2;upper++) {
        sample.config.joint[4].point[0]=(ainekio_feedback_point_t){reverse?3500:500,500};
        sample.config.joint[4].point[1]=(ainekio_feedback_point_t){2000,1500};
        sample.config.joint[4].point[2]=(ainekio_feedback_point_t){reverse?500:3500,2500};
        const int end=sample.config.joint[4].point[upper?2:0].raw;
        const int sign=end>2000?1:-1;
        targets[mapping[4].channel]=upper?2500:500;
        sample.raw[c]=end+sign*4;sample.filtered_raw[c]=end+sign*7;
        assert(arrived(mapping,targets,1000,&waiting));
    }
    puts("Feedback arrival: endpoint noise within saved tolerance, mapping, freshness, actual target errors, jam timing and signal faults passed.");
}
