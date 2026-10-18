#include "servo_feedback_model.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

int main(void)
{
    ainekio_feedback_config_t c;ainekio_feedback_defaults(&c);
    assert(ainekio_feedback_config_valid(&c));
    assert(!c.enabled&&!c.stand_enabled);
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
    c.joint[2].points=3;assert(!ainekio_feedback_config_valid(&c));
    c.stand_enabled=0;assert(ainekio_feedback_config_valid(&c));
    c.joint[2].points=7;c.joint[2].point[1].raw=3500;
    assert(!ainekio_feedback_config_valid(&c));
    c.joint[2]=c.joint[0];assert(!ainekio_feedback_config_valid(&c)); /* duplicate input */
    puts("Feedback calibration: increasing/decreasing sensors, piecewise conversion, extrapolation, incomplete/ambiguous mappings passed.");
}
