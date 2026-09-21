#include "ainekio/v2_motion.h"
#include <inttypes.h>
#include <stdio.h>

int main(void)
{
    uint64_t time;
    char command[AINEKIO_ASSET_NAME_MAX + 1U];
    while (scanf("%32s %" SCNu64, command, &time) == 2) {
        size_t index;
        ainekio_v2_frame_t frame;
        if (!ainekio_v2_clip_find(command, &index) || !ainekio_v2_clip_sample(index, time, &frame)) return 1;
        printf("{");
        const char *names[] = {"position", "velocity", "acceleration"};
        const float *vectors[] = {frame.position, frame.velocity, frame.acceleration};
        for (size_t k = 0; k < 3; ++k) {
            printf("%s\"%s\":[", k ? "," : "", names[k]);
            for (size_t j = 0; j < 12; ++j) printf("%s%.9g", j ? "," : "", vectors[k][j]);
            printf("]");
        }
        printf(",\"complete\":%s}\n", frame.phase == AINEKIO_V2_COMPLETE ? "true" : "false");
    }
    return 0;
}
