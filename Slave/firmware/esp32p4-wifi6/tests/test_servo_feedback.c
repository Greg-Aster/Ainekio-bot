#include "servo_feedback_model.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void measurement_filter(void)
{
    ainekio_feedback_filter_t f={0};
    ainekio_feedback_filter_update(&f,2000,1000000);
    assert(f.position==2000 && f.velocity==0);
    double raw_energy=0.,filtered_energy=0.;
    for(unsigned n=1;n<=300;n++) {
        double raw=2000+(n%2?40:-40);
        ainekio_feedback_filter_update(&f,raw,1000000+n*20000);
        if(n>50){raw_energy+=(raw-2000)*(raw-2000);filtered_energy+=(f.position-2000)*(f.position-2000);}
    }
    assert(sqrt(filtered_energy/raw_energy)<.25);
    double held=f.position;ainekio_feedback_filter_update(&f,1000,f.sampled_us);
    assert(f.position==held);
    for(unsigned n=0;n<4;n++)ainekio_feedback_filter_update(&f,3000,f.sampled_us+20000);
    assert(f.position>2900 && f.position<=3000);
    f=(ainekio_feedback_filter_t){0};
    for(unsigned n=0;n<=50;n++) {
        double raw=500+60*n;
        ainekio_feedback_filter_update(&f,raw,1000000+n*20000);
        if(n>20)assert(raw-f.position<90);
    }
    assert(fabs(f.velocity-3000)<30);
    printf("Feedback filter: stationary noise RMS ratio %.3f; 1000-count step >90%% within 80ms; ramp lag <90 counts at 3000 counts/s.\n",sqrt(filtered_energy/raw_energy));
}

int main(void)
{
    measurement_filter();
    ainekio_feedback_config_t c;ainekio_feedback_defaults(&c);
    assert(ainekio_feedback_config_valid(&c));
    assert(!c.enabled&&!c.stand_enabled&&!c.jam_enabled);
    double pulse;bool inside;
    assert(!ainekio_feedback_position(&c.joint[0],2000,&pulse,&inside));
    for(unsigned j=0;j<12;j++) {
        c.joint[j].points=7;
        c.joint[j].point[0]=(ainekio_feedback_point_t){300,500};
        c.joint[j].point[1]=(ainekio_feedback_point_t){1800,1650};
        c.joint[j].point[2]=(ainekio_feedback_point_t){3500,2800};
    }
    assert(ainekio_feedback_position(&c.joint[0],2650,&pulse,&inside));
    assert(inside&&fabs(pulse-2225)<1e-9);
    assert(ainekio_feedback_position(&c.joint[0],3670,&pulse,&inside));
    assert(!inside&&fabs(pulse-2915)<1e-9); /* No clipping the measured range. */
    assert(!ainekio_feedback_position(&c.joint[0],NAN,&pulse,&inside));
    c.joint[1].point[0].raw=3500;c.joint[1].point[1].raw=1800;c.joint[1].point[2].raw=300;
    assert(ainekio_feedback_position(&c.joint[1],1050,&pulse,&inside));
    assert(inside&&fabs(pulse-2225)<1e-9);
    c.enabled=c.stand_enabled=1;assert(ainekio_feedback_config_valid(&c));
    ainekio_feedback_config_t old=c,decoded;
    old.version=1;
    assert(ainekio_feedback_config_decode(&old,offsetof(ainekio_feedback_config_t,no_progress_ms),&decoded));
    assert(decoded.enabled && decoded.stand_enabled && decoded.no_progress_ms==1000 && decoded.progress_us==5);
    assert(!memcmp(decoded.joint,c.joint,sizeof c.joint));
    assert(!decoded.jam_enabled); /* Version 1 did not implement jam release. */
    old=c;old.version=2;old.no_progress_ms=2000;old.progress_us=15;old.tolerance_us=400;
    /* The version-2 reserved bytes are not a jam switch. */
    old.jam_enabled=255;old.reserved=255;
    for(unsigned coordinated=0;coordinated<2;coordinated++)for(unsigned timed=0;timed<2;timed++) {
        old.stand_enabled=coordinated;old.no_progress_ms=timed?2000:0;
        assert(ainekio_feedback_config_decode(&old,offsetof(ainekio_feedback_config_t,arrival_tolerance_us),&decoded));
        assert(decoded.jam_enabled==(coordinated&&timed));
        assert(decoded.stand_enabled==coordinated && decoded.no_progress_ms==old.no_progress_ms);
        assert(decoded.tolerance_us==400 && decoded.progress_us==15);
        assert(decoded.arrival_tolerance_us==400);
        assert(!memcmp(decoded.joint,c.joint,sizeof c.joint));
    }
    old.version=1;
    assert(!ainekio_feedback_config_decode(&old,sizeof old,&decoded));
    old=c;old.version=3;old.tolerance_us=400;old.jam_enabled=1;
    assert(ainekio_feedback_config_decode(&old,offsetof(ainekio_feedback_config_t,arrival_tolerance_us),&decoded));
    assert(decoded.tolerance_us==400 && decoded.arrival_tolerance_us==400 && decoded.jam_enabled);
    c.arrival_tolerance_us=75;c.tolerance_us=400;
    assert(ainekio_feedback_config_decode(&c,sizeof c,&decoded));
    assert(!memcmp(&c,&decoded,sizeof c));
    for(unsigned coordinated=0;coordinated<2;coordinated++)for(unsigned jam=0;jam<2;jam++) {
        c.stand_enabled=coordinated;c.jam_enabled=jam;
        assert(ainekio_feedback_config_valid(&c));
        assert(ainekio_feedback_config_decode(&c,sizeof c,&decoded));
        assert(!memcmp(&c,&decoded,sizeof c));
    }
    c.stand_enabled=1;c.jam_enabled=0;
    c.joint[2].points=3;assert(!ainekio_feedback_config_valid(&c));
    c.stand_enabled=0;assert(ainekio_feedback_config_valid(&c));
    c.joint[2].points=7;c.joint[2].point[1].raw=3500;
    assert(!ainekio_feedback_config_valid(&c));
    c.joint[2]=c.joint[0];assert(!ainekio_feedback_config_valid(&c)); /* duplicate input */
    puts("Feedback calibration: increasing/decreasing sensors, piecewise conversion, extrapolation, incomplete/ambiguous mappings passed.");
}
