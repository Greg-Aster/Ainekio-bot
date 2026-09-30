#ifndef AINEKIO_V2_WALK_H
#define AINEKIO_V2_WALK_H
#include "ainekio/v2_motion.h"

/* Requested stride/cadence; the common clock enforces the command-speed limit. */
typedef struct { double stride_percent, motion_rate; } ainekio_v2_walk_controls_t;
typedef struct {
    double phase, body[3], euler[3], feet[4][3], sole_height[4];
    double joints[4][3]; /* reference order RL, RR, FL, FR; radians */
    double run_blend; /* 0 walking, 1 bounding; zero for Crawl */
    bool grounded[4];
    ainekio_gait_t gait; /* Walk, low Crawl, paired-leg Run, or wide Crab */
    ainekio_walk_direction_t direction;
    ainekio_v2_frame_t frame; /* stable model order FL, FR, RL, RR */
} ainekio_v2_walk_pose_t;

typedef struct {
    double start_x, end_x, start_y, end_y, lift, touchdown_phase, swing_span;
    bool swinging;
} ainekio_v2_foot_state_t;
typedef struct {
    uint64_t last_us;
    uint32_t command_sequence, latest_sequence;
    double phase, body_x, body_y, body_yaw, preparation_seconds, transition_phase, transition_span, end_phase;
    double clock_scale; /* accepted gait time / wall time, in (0,1] */
    bool speed_flagged; /* once >=125%, use the rated budget for this gait run */
    ainekio_walk_direction_t direction;
    ainekio_gait_t gait_mode; /* command family; Walk can cross into Run */
    double run_from, run_target, run_transition_phase;
    double offset_from[4], offset_target[4];
    ainekio_v2_walk_controls_t from, target, pending;
    ainekio_v2_foot_state_t feet[4];
    ainekio_v2_walk_pose_t pose;
    bool initialized, pending_update, stopping, complete, failed;
} ainekio_v2_walk_state_t;

extern const char ainekio_v2_walk_geometry_id[];
/* Configured command limit in degrees/second, not measured shaft capability. */
double ainekio_v2_gait_joint_speed_limit(void);
double ainekio_v2_gait_joint_speed_flag_threshold(void);
bool ainekio_v2_walk_controls(double speed_percent, ainekio_v2_walk_controls_t *out);
bool ainekio_v2_walk_controls_valid(ainekio_v2_walk_controls_t controls);
/* Stateless reference pose, for C/Python parity and diagnostic sampling. */
bool ainekio_v2_walk_pose(double phase, ainekio_v2_walk_controls_t controls,
                         ainekio_v2_walk_pose_t *out);
bool ainekio_v2_walk_solve(ainekio_v2_walk_pose_t *pose);
/* Local clock: callers supply monotonic time, never per-servo timing. */
/* cycles == 0 runs until an explicit speed-zero update. */
bool ainekio_v2_gait_begin(ainekio_v2_walk_state_t *state,
    ainekio_walk_direction_t direction, ainekio_gait_t gait, unsigned cycles,
    ainekio_v2_walk_controls_t controls, uint64_t now_us);
bool ainekio_v2_locomotion_begin(ainekio_v2_walk_state_t *state,
    ainekio_walk_direction_t direction, bool crawl, unsigned cycles,
    ainekio_v2_walk_controls_t controls, uint64_t now_us);
bool ainekio_v2_walk_begin(ainekio_v2_walk_state_t *state, unsigned cycles,
                          ainekio_v2_walk_controls_t controls, uint64_t now_us);
bool ainekio_v2_walk_update(ainekio_v2_walk_state_t *state,
                           ainekio_v2_walk_controls_t controls);
bool ainekio_v2_walk_tick(ainekio_v2_walk_state_t *state, uint64_t now_us);
/* Call after common session/expiry admission. Updates name the original walk. */
bool ainekio_v2_walk_accept(ainekio_v2_walk_state_t *state,
                           const ainekio_command_t *command, uint64_t now_us);
#endif
