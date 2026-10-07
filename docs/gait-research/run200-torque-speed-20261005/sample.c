#include "ainekio/v2_walk.h"
#include <stdio.h>
#include <stdlib.h>
static void emit(double time, const ainekio_v2_walk_state_t *s) {
 printf("%.9f,%.12f,%.12f,%d,%d,%.12f",time,s->phase,s->clock_scale,s->stopping,s->complete,s->pose.run_blend);
 for(unsigned j=0;j<3;j++)printf(",%.12f",s->pose.euler[j]);
 for(unsigned i=0;i<4;i++){printf(",%d",s->pose.grounded[i]);for(unsigned j=0;j<3;j++)printf(",%.12f",s->pose.joints[i][j]);}
 printf("\n");
}
int main(int argc,char **argv) {
 unsigned step=argc>1?atoi(argv[1]):1000;
 ainekio_command_t c={.kind=AINEKIO_COMMAND_INTENT,.sequence=1};c.data.intent.kind=AINEKIO_INTENT_WALK;
 c.data.intent.data.walk.direction=AINEKIO_WALK_FORWARD;c.data.intent.data.walk.gait=AINEKIO_GAIT_WALK;
 c.data.intent.data.walk.controls=1;c.data.intent.data.walk.speed_percent=200.;
 ainekio_v2_walk_state_t s={0};if(!ainekio_v2_joint_speed_set(20000)||!ainekio_v2_walk_accept(&s,&c,0))return 1;
 emit(0,&s);
 for(unsigned long long us=step;us<=24000000ULL;us+=step){
  if(!ainekio_v2_walk_tick(&s,us)){fprintf(stderr,"solve failed at %llu\n",us);return 2;}
  emit(us/1e6,&s);
  if(us==12000000ULL && !ainekio_v2_walk_update(&s,(ainekio_v2_walk_controls_t){0,1})){fprintf(stderr,"finish rejected\n");return 3;}
  if(s.complete && us>12000000ULL)return 0;
 }
 fprintf(stderr,"finish not completed\n");return 4;
}
