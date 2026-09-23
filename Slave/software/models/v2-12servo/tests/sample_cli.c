#include "ainekio/v2_walk.h"
#include <stdio.h>
int main(void)
{
    double phase,stride,rate;
    while(scanf("%lf %lf %lf",&phase,&stride,&rate)==3){
        ainekio_v2_walk_pose_t pose;
        if(!ainekio_v2_walk_pose(phase,(ainekio_v2_walk_controls_t){stride,rate},&pose))return 1;
        printf("[");for(unsigned j=0;j<12;j++)printf("%s%.12g",j?",":"",pose.frame.position[j]);puts("]");
    }
    return 0;
}
