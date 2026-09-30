/* Offline command path. Input: initial JSON, then optional "milliseconds JSON"
 * updates (at most 32). Output: geometry samples. Never emits robot receipts. */
#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
int main(int argc,char **argv)
{
    unsigned milliseconds=argc>1?(unsigned)strtoul(argv[1],NULL,10):15000;
    unsigned hz=argc>2?(unsigned)strtoul(argv[2],NULL,10):100;
    if(milliseconds>120000 || (hz!=25 && hz!=50 && hz!=100 && hz!=120))return 1;
    char json[1024];ainekio_control_message_t message;ainekio_v2_walk_state_t state={0};
    if(!fgets(json,sizeof(json),stdin)||ainekio_control_decode_with_walk_controls(json,strlen(json),&message)!=AINEKIO_DECODE_OK||!ainekio_v2_walk_accept(&state,&message.command,0))return 2;
    struct {unsigned ms; ainekio_command_t command;} events[32];unsigned count=0,next=0;
    while(fgets(json,sizeof(json),stdin)) {
        if(count==32)return 4;
        char *end;unsigned long ms=strtoul(json,&end,10);
        if(end==json||ms>milliseconds||ms%10||(count&&ms<events[count-1].ms))return 4;
        if(ainekio_control_decode_with_walk_controls(end,strlen(end),&message)!=AINEKIO_DECODE_OK)return 4;
        events[count].ms=(unsigned)ms;events[count++].command=message.command;
    }
    for(unsigned sample=0;sample*1000ULL<=milliseconds*hz;sample++){
        uint64_t now=(sample*1000000ULL+hz/2)/hz; double ms=now/1000.;
        if(!ainekio_v2_walk_tick(&state,now)){fprintf(stderr,"solve failed at %.3f ms phase %.9g\n",ms,state.phase);return 3;}
        while(next<count&&events[next].ms<=ms){if(!ainekio_v2_walk_accept(&state,&events[next].command,now))return 5;next++;}
        printf("{\"ms\":%.3f,\"run_blend\":%.12g,\"phase\":%.12g,\"body\":[%.12g,%.12g,%.12g],\"euler\":[%.12g,%.12g,%.12g],\"q\":[",ms,state.pose.run_blend,state.phase,state.pose.body[0],state.pose.body[1],state.pose.body[2],state.pose.euler[0],state.pose.euler[1],state.pose.euler[2]);
        for(unsigned i=0;i<4;i++)for(unsigned j=0;j<3;j++)printf("%s%.12g",i||j?",":"",state.pose.joints[i][j]);
        printf("],\"feet\":[");for(unsigned i=0;i<4;i++)printf("%s[%.12g,%.12g,%.12g]",i?",":"",state.pose.feet[i][0],state.pose.feet[i][1],state.pose.sole_height[i]);
        printf("],\"grounded\":[");for(unsigned i=0;i<4;i++)printf("%s%s",i?",":"",state.pose.grounded[i]?"true":"false");
        printf("],\"clock_scale\":%.12g,\"complete\":%s}\n",state.clock_scale,state.complete?"true":"false");if(state.complete)break;
    }
    return 0;
}
