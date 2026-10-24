/* Offline finite-gait sampling through the production V2 command parser and
 * gait clock. No transport, PWM, feedback simulation or wall-clock deadline.
 * This exporter records nominal targets, not successful physical locomotion. */
#include "ainekio/v2_walk.h"
#include "ainekio/control_codec.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: native_gait COMMAND_JSON JOINT_DEGREES_PER_SECOND\n");
        return 1;
    }
    char *end;
    float speed = strtof(argv[2], &end);
    if (end == argv[2] || *end || !isfinite(speed) || !ainekio_v2_joint_speed_set(speed))
        return 1;
    ainekio_control_message_t message;
    if (ainekio_control_decode_with_walk_controls(argv[1], strlen(argv[1]), &message) != AINEKIO_DECODE_OK)
        return 2;
    ainekio_v2_walk_state_t state = {0};
    if (!ainekio_v2_walk_accept(&state, &message.command, 0))
        return 2;
    /* An ongoing command has no final trajectory. Report that limitation to
     * the offline caller; do not invent a Stop or shorten the robot program. */
    if (message.command.data.intent.data.walk.steps == 0 && state.target.stride_percent > 0) {
        fprintf(stderr, "ongoing gait requires external termination; no finite complete replay\n");
        return 4;
    }
    for (uint64_t now = 0;; now += 20000) {
        if (!ainekio_v2_walk_tick(&state, now)) {
            fprintf(stderr, "native gait solve failed at %llu us\n", (unsigned long long)now);
            return 3;
        }
        printf("{\"time_us\":%llu,\"phase\":%.12g,\"model_deg\":[",
               (unsigned long long)now, state.phase);
        for (unsigned j = 0; j < 12; j++)
            printf("%s%.12g", j ? "," : "", state.pose.frame.position[j] / 100.);
        printf("],\"body_mm\":[%.12g,%.12g,%.12g],\"euler_rad\":[%.12g,%.12g,%.12g],\"grounded\":[",
               state.pose.body[0], state.pose.body[1], state.pose.body[2],
               state.pose.euler[0], state.pose.euler[1], state.pose.euler[2]);
        for (unsigned j = 0; j < 4; j++)
            printf("%s%s", j ? "," : "", state.pose.grounded[j] ? "true" : "false");
        printf("],\"run_blend\":%.12g,\"complete\":%s}\n",
               state.pose.run_blend, state.complete ? "true" : "false");
        if (state.complete)
            break;
    }
    return 0;
}
