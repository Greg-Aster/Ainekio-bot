#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static ainekio_command_t decode(const char *text)
{
    ainekio_control_message_t m;
    assert(ainekio_control_decode_with_walk_controls(text,strlen(text),&m)==AINEKIO_DECODE_OK);
    return m.command;
}
static void test_fast_strokes(void)
{
    double cycles[2],movement[2];
    const double strides[]={25.,100.};
    for(unsigned k=0;k<2;k++) {
        ainekio_command_t command=decode("{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":100}");
        command.data.intent.data.walk.speed_percent=strides[k];
        ainekio_v2_walk_state_t s={0};
        assert(ainekio_v2_walk_accept(&s,&command,0) && s.fast_stroke);
        double start=0.,sum=0.;unsigned samples=0;
        for(uint64_t now=20000;now<=8000000;now+=20000) {
            ainekio_v2_frame_t previous=s.pose.frame;
            assert(ainekio_v2_walk_tick(&s,now));
            if(now==4000000)start=s.phase;
            if(now>4000000) {
                double peak=0.;
                for(unsigned j=0;j<12;j++)peak=fmax(peak,fabs(s.pose.frame.position[j]-previous.position[j])/.02/100.);
                sum+=peak;samples++;
            }
        }
        cycles[k]=(s.phase-start)/4.;movement[k]=sum/samples;
        /* Short strokes remain brisk instead of scaling the movement rate
         * down with stride. Coordination and direction reversals mean a
         * whole output frame need not attain the nominal peak exactly. */
        assert(movement[k]>400. && movement[k]<600.);
        command=decode("{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"stride\":25,\"rate\":2,\"update\":1}");
        assert(ainekio_v2_walk_accept(&s,&command,8000000) && s.fast_stroke);
        assert(ainekio_v2_walk_tick(&s,8020000) && s.clock_scale>0.);
    }
    assert(cycles[0]>cycles[1]*1.5);
    assert(movement[0]>movement[1]*.8);
}
/* Exercise the semantic owner, including legacy rate requests. Low-level
 * gait_begin remains the reference-time API for geometry authoring. */
static void test_all_fast_gaits(void)
{
    const char *gaits[]={"walk","run","crawl","crab"};
    const char *dirs[]={"fwd","back","turn_l","turn_r","side_l","side_r"};
    char wire[256];
    for(unsigned g=0;g<4;g++)for(unsigned d=0;d<(g==3?6:4);d++) {
        ainekio_v2_walk_state_t slow={0},fast={0};
        snprintf(wire,sizeof(wire),"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"gait\":\"%s\",\"dir\":\"%s\",\"steps\":0,\"stride\":100,\"rate\":0.25}",gaits[g],dirs[d]);
        ainekio_command_t command=decode(wire);
        assert(ainekio_v2_walk_accept(&slow,&command,0)&&slow.fast_stroke);
        command.data.intent.data.walk.motion_rate=3.;
        assert(ainekio_v2_walk_accept(&fast,&command,0)&&fast.fast_stroke);
        bool retimed=false;
        for(uint64_t now=20000;now<=8000000;now+=20000) {
            assert(ainekio_v2_walk_tick(&slow,now));
            assert(ainekio_v2_walk_tick(&fast,now));
            assert(slow.phase==fast.phase);
            for(unsigned j=0;j<12;j++)assert(slow.pose.frame.position[j]==fast.pose.frame.position[j]);
            retimed|=fabs(slow.clock_scale-1.)>.1;
        }
        assert(retimed&&slow.phase>2.);
        snprintf(wire,sizeof(wire),"{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"gait\":\"%s\",\"dir\":\"%s\",\"steps\":0,\"speed\":0,\"update\":1}",gaits[g],dirs[d]);
        command=decode(wire);
        assert(ainekio_v2_walk_accept(&slow,&command,8000000)&&slow.fast_stroke);
        for(uint64_t now=8020000;!slow.complete;now+=20000) {
            assert(now<40000000&&ainekio_v2_walk_tick(&slow,now));
        }
        for(unsigned leg=0;leg<4;leg++)assert(slow.pose.grounded[leg]);
    }
    /* Automatic selection must retain an effective stride control throughout
     * 1–100, including Crawl/Crab's formerly saturated 50–100 range. */
    for(unsigned g=0;g<4;g++) {
        double previous=0.;
        for(unsigned speed=1;speed<=100;speed++) {
            snprintf(wire,sizeof(wire),"{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"gait\":\"%s\",\"dir\":\"fwd\",\"steps\":0,\"speed\":%u}",gaits[g],speed);
            ainekio_command_t command=decode(wire);ainekio_v2_walk_state_t state={0};
            assert(ainekio_v2_walk_accept(&state,&command,0)&&state.fast_stroke);
            assert(state.requested_stride_percent>previous);
            previous=state.requested_stride_percent;
        }
    }
}
static void test_upright_walk_reach(void)
{
    double previous_span=0.;
    for(unsigned speed=1;speed<=100;speed++) {
        ainekio_command_t c=decode("{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":100}");
        c.data.intent.data.walk.speed_percent=speed;
        ainekio_v2_walk_state_t s={0};assert(ainekio_v2_walk_accept(&s,&c,0));
        const double origin=s.pose.feet[1][0];
        double low=INFINITY,high=-INFINITY,lift=0.,body_low=INFINITY,body_high=-INFINITY;
        /* Resolve geometric extrema independently of the 50 Hz hardware sampling. */
        for(uint64_t now=1000;s.phase<8.;now+=1000) {
            assert(now<60000000&&ainekio_v2_walk_tick(&s,now));
            assert(s.preparation_seconds==0. && s.fast_stroke && s.clock_scale>0.);
            if(s.phase>=2.)assert(fabs(s.stride_percent-speed)<1e-6);
            if(s.phase>=6.) {
                unsigned contacts=0;for(unsigned leg=0;leg<4;leg++)contacts+=s.pose.grounded[leg];
                assert(contacts>=3);
                double x=s.pose.feet[1][0]-s.body_x-origin;
                low=fmin(low,x);high=fmax(high,x);lift=fmax(lift,s.pose.sole_height[1]);
                body_low=fmin(body_low,s.pose.body[2]);body_high=fmax(body_high,s.pose.body[2]);
            }
        }
        double span=high-low;
        assert(span>previous_span);previous_span=span;
        if(fabs(lift-(6.+4.*speed/100.))>=.1)fprintf(stderr,"Walk lift speed=%u measured=%g expected=%g phase=%g\n",speed,lift,6.+4.*speed/100.,s.phase);
        assert(fabs(lift-(6.+4.*speed/100.))<.1);
        /* Reindexed crank path is about 61.95 mm at full stride.
         * Measure against commanded body travel, excluding support transfer. */
        assert(fabs(span-61.94505422059417*speed/100.)<.5);
        if(speed==100) {
            assert(low < -53. && high < 9. && high > 7.);
            assert(body_high-body_low>6.5);
        }

    }
}
int main(void)
{
    test_fast_strokes();
    test_all_fast_gaits();
    test_upright_walk_reach();
    ainekio_v2_walk_controls_t c;
    ainekio_v2_walk_pose_t stand;
    assert(ainekio_v2_walk_pose(0,(ainekio_v2_walk_controls_t){0,1},&stand));
    assert(stand.body[2]==-2.); /* Named Stand retains its reviewed height. */
    assert(ainekio_v2_walk_controls(25,&c)&&fabs(c.stride_percent-25)<1e-9&&c.motion_rate==2.);
    assert(ainekio_v2_walk_controls(50,&c)&&fabs(c.stride_percent-50)<1e-9&&c.motion_rate==2.);
    assert(ainekio_v2_walk_controls(75,&c)&&fabs(c.stride_percent-75)<1e-9&&c.motion_rate==2.);
    assert(ainekio_v2_walk_controls(100,&c)&&fabs(c.stride_percent-100)<1e-9&&c.motion_rate==2);
    assert(!ainekio_v2_walk_controls(NAN,&c));assert(!ainekio_v2_walk_controls(101,&c));
    assert(!ainekio_v2_walk_hardware_qualified);
    assert(!strcmp(ainekio_v2_joints[0].name,"rear_left_shoulder"));
    assert(!strcmp(ainekio_v2_joints[11].name,"front_right_crank"));
    ainekio_control_message_t message;
    const char *extended="{\"t\":\"intent\",\"seq\":1,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":3,\"speed\":100}";
    assert(ainekio_control_decode(extended,strlen(extended),&message)!=AINEKIO_DECODE_OK);
    ainekio_command_t command=decode(extended);ainekio_v2_walk_state_t s={0};
    assert(ainekio_v2_walk_accept(&s,&command,0));assert(!ainekio_v2_walk_accept(&s,&command,0));
    double drift=0,max_step=0;bool updated=false;
    for(unsigned t=10000;t<=30000000;t+=10000) {
        ainekio_v2_walk_pose_t old=s.pose;
        assert(ainekio_v2_walk_tick(&s,t));
        assert(s.phase>=old.phase);
        for(unsigned i=0;i<4;i++) {
            if(old.grounded[i]&&s.pose.grounded[i])drift=fmax(drift,fabs(old.feet[i][0]-s.pose.feet[i][0]));
            for(unsigned j=0;j<3;j++)max_step=fmax(max_step,fabs(old.joints[i][j]-s.pose.joints[i][j]));
        }
        if(t==350000){
            command=decode("{\"t\":\"intent\",\"seq\":2,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":1,\"speed\":25,\"update\":99}");
            assert(!ainekio_v2_walk_accept(&s,&command,t));command.data.intent.data.walk.update_sequence=1;
            double phase=s.phase,end=s.end_phase,x=s.body_x;
            assert(ainekio_v2_walk_accept(&s,&command,t));assert(s.phase==phase&&s.end_phase==end&&s.body_x==x);
            assert(!ainekio_v2_walk_accept(&s,&command,t));updated=true;
        }
        if(s.complete)break;
    }
    assert(updated&&s.complete&&drift<1e-10&&max_step<.3);
    for(unsigned i=0;i<4;i++)assert(s.pose.grounded[i]&&s.pose.sole_height[i]==0);
    for(unsigned j=0;j<12;j++)assert(s.pose.frame.velocity[j]==0&&s.pose.frame.acceleration[j]==0);
    assert(ainekio_v2_walk_begin(&s,3,(ainekio_v2_walk_controls_t){100,1},0));
    assert(ainekio_v2_walk_tick(&s,40001)&&!s.failed);
    assert(ainekio_v2_walk_tick(&s,1040001)&&!s.failed);
    /* Reversal while ramping keeps current parameters; latest target wins. */
    for(unsigned speed=0;speed<=100;speed+=25){
        assert(ainekio_v2_walk_controls(speed,&c));assert(ainekio_v2_walk_begin(&s,1,c,0));
        for(unsigned t=10000;t<=30000000&&!s.complete;t+=10000)assert(ainekio_v2_walk_tick(&s,t));
        assert(s.complete);
    }
    printf("Automatic/manual walking, planted anchors, active-command updates, finish and stale-clock rejection passed; max joint step %.6g rad.\n",max_step);
    return 0;
}
