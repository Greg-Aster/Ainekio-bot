#include "ainekio/v2_limits.h"
#include "ainekio/v2_walk.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
static void path(const ainekio_v2_frame_t *from,const ainekio_v2_frame_t *to)
{
    ainekio_v2_frame_t lo,hi,actual,previous;double derivative[12];
    assert(ainekio_v2_transition_bounds(from,to,&lo,&hi,derivative));
    for(unsigned j=0;j<12;j++)assert(isfinite(derivative[j])&&derivative[j]>=0.);
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
static void workspace_bounds(void)
{
    ainekio_v2_frame_t reference={0},pose={0};
    for(unsigned leg=0;leg<4;leg++){reference.position[3*leg+1]=346;reference.position[3*leg+2]=-2163;}
    /* Calibrated command-domain endpoints from the 2026-11-04 native trial,
     * rounded outward in centidegrees. Feedback sensor validity is separate. */
    float low[12]={-13140.01f,-3537.01f,-11138.01f,-12150.01f,-2322.01f,-11228.01f,
        -12150.01f,-3627.01f,-12218.01f,-12600.01f,-3627.01f,-12443.01f};
    float high[12]={11160.01f,17163.01f,9562.01f,12150.01f,18378.01f,9472.01f,
        12150.01f,17073.01f,8482.01f,11700.01f,17073.01f,8257.01f};
    float lower[4][3],upper[4][3],origin[4][3],feet[4][3];
    assert(ainekio_v2_feet_forward(&reference,origin)==15);
    assert(ainekio_v2_foot_offset_bounds(&reference,low,high,lower,upper));
    /* This physical native output needs 53.808mm X travel. The former 30mm
     * model action box could not express it. It is a range regression, not
     * a claim that the already-leveled pose is a nominal teaching action. */
    const float recorded[12]={-540,1053,-1229,225,-2178,-6089,-774,-1737,-12218,360,-900,-4235};
    for(unsigned j=0;j<12;j++)pose.position[j]=recorded[j];
    assert(ainekio_v2_feet_forward(&pose,feet)==15);
    assert(fabsf(feet[2][0]-origin[2][0])>53.8f);
    for(unsigned leg=0;leg<4;leg++)for(unsigned axis=0;axis<3;axis++) {
        const float offset=feet[leg][axis]-origin[leg][axis];
        assert(offset>=lower[leg][axis]&&offset<=upper[leg][axis]);
    }
    unsigned checked=0;
    /* Boundary/interior probes verify the analytic bounds; they do not define
     * them. Include shoulder extrema and broad crank/carrier combinations. */
    for(unsigned h=0;h<=12;h++)for(unsigned a=0;a<=12;a++)for(unsigned t=0;t<=12;t++) {
        const unsigned samples[3]={h,a,t};
        for(unsigned j=0;j<12;j++)pose.position[j]=low[j]+(high[j]-low[j])*samples[j%3]/12.f;
        const unsigned valid=ainekio_v2_feet_forward(&pose,feet);
        for(unsigned leg=0;leg<4;leg++)if(valid&(1U<<leg)) {
            checked++;
            for(unsigned axis=0;axis<3;axis++) {
                const float offset=feet[leg][axis]-origin[leg][axis];
                assert(offset>=lower[leg][axis]&&offset<=upper[leg][axis]);
            }
        }
    }
    assert(checked>1000);
    low[0]=NAN;assert(!ainekio_v2_foot_offset_bounds(&reference,low,high,lower,upper));
}
int main(void)
{
    workspace_bounds();
    /* Walk1325/sample376, 20261104-143818-c186b49b. Start is the last
     * recorded PWM mapped to model coordinates. Destination is reproduced
     * from that request/IMU/tuning in its balance-state neighborhood; retained
     * controller corrections were not recorded. Its front-right annulus
     * coordinate is exactly -1: FK accepts this full-extension endpoint. */
    ainekio_v2_frame_t boundary_from={0},boundary_to={0},endpoint;
    const float from[]={-846.000061F,1089.00012F,-2362.99976F,801.000061F,-431.999908F,-2686.99976F,
        297.F,-980.999939F,-4423.99951F,378.F,2124.00024F,-1768.99963F};
    const float to[]={605.384766F,-1871.05933F,-3498.12183F,-1001.1543F,-118.331665F,168.683823F,
        1508.03394F,-1043.8811F,-870.832764F,1030.36621F,6946.87549F,1211.88184F};
    for(unsigned j=0;j<12;j++){boundary_from.position[j]=from[j];boundary_to.position[j]=to[j];}
    assert(ainekio_v2_limits_frame(&boundary_from)&&ainekio_v2_limits_frame(&boundary_to));
    path(&boundary_from,&boundary_to);path(&boundary_to,&boundary_from);
    assert(ainekio_v2_transition(&boundary_from,&boundary_to,1.,&endpoint));
    for(unsigned j=0;j<12;j++)assert(endpoint.position[j]==to[j]);
    assert(ainekio_v2_transition(&boundary_to,&boundary_from,0.,&endpoint));
    for(unsigned j=0;j<12;j++)assert(endpoint.position[j]==to[j]);
    ainekio_v2_frame_t center={0},stand={0},invalid={0};
    for(unsigned j=0;j<12;j++)center.position[j]=(float)(100.*ainekio_v2_center_degrees(j));
    for(unsigned j=0;j<12;j++)assert(ainekio_v2_pulse_reference(j)==(j%3==0?1650:j%3==1?856:723));
    assert(ainekio_v2_limits_frame(&center));
    /* Compact 35/20/28/38 linkage: at carrier 120 degrees and crank zero,
     * knee-to-crank distance is 71.586 mm, beyond the 66 mm rod + pickup.
     * The old 60-degree fixture closes with this installed geometry. */
    invalid.position[1]=12000;
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
