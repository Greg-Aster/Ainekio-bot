/* Offline trial export: retain the production walking path, change only swing
 * sole height, and solve using the current robot geometry. JSONL model angles
 * are centidegrees in physical joint order; this tool never contacts a robot. */
#include "ainekio/v2_walk.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    if(argc<2 || argc>4) {fprintf(stderr,"usage: export_freestyle LIFT_MULTIPLIER [REAR_SWING_X_MM [single-cycle]]\n");return 1;}
    char *end;
    double lift=strtod(argv[1],&end);
    if(end==argv[1] || *end || !isfinite(lift))return 1;
    double swing_x=0.;
    if(argc>=3){swing_x=strtod(argv[2],&end);if(end==argv[2] || *end || !isfinite(swing_x))return 1;}
    bool single_cycle=argc==4;
    if(single_cycle && strcmp(argv[3],"single-cycle"))return 1;
    ainekio_v2_walk_state_t state={0};
    ainekio_command_t command={.kind=AINEKIO_COMMAND_INTENT,.sequence=1,
        .data.intent={.kind=AINEKIO_INTENT_WALK,
            .data.walk={.direction=AINEKIO_WALK_FORWARD,.gait=AINEKIO_GAIT_WALK,.steps=2,.controls=1,.speed_percent=100}}};
    if(!ainekio_v2_walk_accept(&state,&command,0))return 2;
    for(uint64_t now=0;;now+=20000) {
        if(!ainekio_v2_walk_tick(&state,now))return 3;
        if(single_cycle && state.phase<2.)continue;
        bool finish=state.complete || (single_cycle && state.phase>=3.);
        ainekio_v2_walk_pose_t pose=state.pose;
        for(unsigned leg=0;leg<4;leg++) {
            /* Offset only the airborne return, tapering to zero at contact. */
            double arch=state.feet[leg].lift>0.?pose.sole_height[leg]/state.feet[leg].lift:0.;
            /* Source indices 2/3 map to physical rear model joints 0..5. */
            if(leg>=2 && !pose.grounded[leg] && !(single_cycle && finish))pose.feet[leg][0]+=swing_x*arch;
            pose.sole_height[leg]*=lift;
            /* Finish the short comparison with all modeled soles planted,
             * without appending Home or Stand. */
            if(single_cycle && finish){pose.sole_height[leg]=0.;pose.grounded[leg]=true;}
        }
        if((lift!=1. || swing_x!=0. || (single_cycle && finish)) && !ainekio_v2_walk_solve(&pose)) {
            fprintf(stderr,"lift solve failed at %llu us\n",(unsigned long long)now);return 4;
        }
        printf("{\"ms\":%llu,\"phase\":%.9g,\"targets\":[",(unsigned long long)(now/1000),state.phase);
        for(unsigned j=0;j<12;j++)printf("%s%.9g",j?",":"",pose.frame.position[j]);
        printf("],\"body\":[%.9g,%.9g,%.9g],\"euler\":[%.9g,%.9g,%.9g],\"lift_mm\":[",pose.body[0],pose.body[1],pose.body[2],pose.euler[0],pose.euler[1],pose.euler[2]);
        for(unsigned leg=0;leg<4;leg++)printf("%s%.9g",leg?",":"",pose.sole_height[leg]);
        printf("],\"grounded\":[");
        for(unsigned leg=0;leg<4;leg++)printf("%s%s",leg?",":"",pose.grounded[leg]?"true":"false");
        printf("],\"complete\":%s}\n",finish?"true":"false");
        if(finish)break;
    }
    return 0;
}
