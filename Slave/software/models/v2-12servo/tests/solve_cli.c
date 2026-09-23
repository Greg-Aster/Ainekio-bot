#include "ainekio/v2_walk.h"
#include <stdio.h>
int main(void)
{
    ainekio_v2_walk_pose_t pose={0};unsigned count=0;
    while(scanf("%lf",&pose.body[0])==1){
        for(unsigned k=1;k<3;k++)if(scanf("%lf",&pose.body[k])!=1)return 1;
        for(unsigned k=0;k<3;k++)if(scanf("%lf",&pose.euler[k])!=1)return 1;
        for(unsigned i=0;i<4;i++)for(unsigned k=0;k<3;k++)if(scanf("%lf",&pose.feet[i][k])!=1)return 1;
        for(unsigned i=0;i<4;i++)if(scanf("%lf",&pose.sole_height[i])!=1)return 1;
        if(!ainekio_v2_walk_solve(&pose)){fprintf(stderr,"pose %u failed\n",count);return 2;}
        printf("[");for(unsigned i=0;i<4;i++)for(unsigned j=0;j<3;j++)printf("%s%.15g",i||j?",":"",pose.joints[i][j]);puts("]");count++;
    }
    return 0;
}
