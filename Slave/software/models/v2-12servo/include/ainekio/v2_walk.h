#ifndef AINEKIO_V2_WALK_H
#define AINEKIO_V2_WALK_H
#include "ainekio/v2_motion.h"

/* Advanced controls retain explicit stride/cadence. Automatic Walk traverses
 * the coordinated joint path at the full nominal joint movement rate. */
typedef struct { double stride_percent, motion_rate; } ainekio_v2_walk_controls_t;
#define AINEKIO_GAIT_PROFILE_PARAMETERS 33
/* Learned Walk geometry, in physical model order RL RR FL FR. Zero is the
 * existing gait. Landings are body-frame offsets selected at liftoff; planted
 * anchors never follow subsequent body motion. No PWM or actuator timing here. */
typedef struct {
    float duty_delta, sweep_delta_mm;
    float phase_offset[4], lift_delta_mm[4], landing_mm[4][2];
    float body_mm[3][5]; /* constant, sin/cos phase, sin/cos twice phase */
} ainekio_v2_gait_profile_t;
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
    double start_x, end_x, start_y, end_y, lift, touchdown_phase, swing_span, run_shape;
    bool swinging;
} ainekio_v2_foot_state_t;
typedef struct {
    uint64_t last_us;
    uint32_t command_sequence, latest_sequence;
    double phase, body_x, body_y, body_yaw, preparation_seconds, transition_phase, transition_span, end_phase;
    double clock_scale; /* reference gait time / wall time */
    bool speed_flagged; /* no speed-limit intervention */
    bool fast_stroke; /* Semantic gaits: stride selects distance, not joint rate. */
    bool automatic_run;
    double requested_stride_percent, cycles_s, requested_cycles_s, stride_percent;
    ainekio_walk_direction_t direction;
    ainekio_gait_t gait_mode; /* command family; Walk can cross into Run */
    double run_from, run_target, run_transition_phase;
    double offset_from[4], offset_target[4];
    ainekio_v2_walk_controls_t from, target, pending;
    /* Separate operator trajectory and measured-heading correction. Radians
     * are relative to activation; six-axis yaw is not absolute odometry. */
    double heading_reference, heading_measured, heading_last_yaw, heading_error;
    double heading_integral, feedback_turn;
    bool heading_acquired, heading_active, heading_reduced;
    bool steering;
    double forward_from, forward_target, turn_from, turn_target, lateral_from, lateral_target, steering_phase;
    ainekio_v2_walk_pose_t pose;
    bool initialized, pending_update, stopping, complete, failed;
    /* Host nominal source shares this Walk's clocks, heading and lifecycle.
     * It has no procedural phase; samples refer to one fixed model frame. */
    bool host_nominal;
    /* A Walk's source is fixed. Native rollback copies must not carry an
     * additional unused host trajectory on the embedded output stack. */
    union {
        struct {
            ainekio_v2_gait_profile_t profile;
            bool profile_run; /* profile belongs to bounding Run */
            ainekio_v2_foot_state_t feet[4];
        };
        struct {
            ainekio_v2_frame_t host_reference;
            float host_twist[3], host_requested[4][3], host_applied[4][3], host_fit[4];
            double host_anchors[4][3];
            uint32_t host_sample, host_consumed_sample;
        };
    };
} ainekio_v2_walk_state_t;

extern const char ainekio_v2_walk_geometry_id[];
/* Configured command limit in degrees/second, not measured shaft capability. */
double ainekio_v2_gait_joint_speed_limit(void);
double ainekio_v2_gait_joint_speed_flag_threshold(void);
bool ainekio_v2_walk_controls(double speed_percent, ainekio_v2_walk_controls_t *out);
bool ainekio_v2_walk_controls_valid(ainekio_v2_walk_controls_t controls);
/* Profile domain: finite geometry, positive sweep, duty strictly between 0
 * and 1, nonnegative lift. This does not assert linkage or physical feasibility. */
bool ainekio_v2_gait_profile_valid(const ainekio_v2_gait_profile_t *profile);
/* Select once after begin/accept, before the first tick. Command interpolation
 * then uses the same profile; it is not a mid-swing retargeting interface. */
void ainekio_v2_walk_profile_begin(ainekio_v2_walk_state_t *state,
    const ainekio_v2_gait_profile_t *profile);
/* Operator command at the executed phase, excluding heading feedback. */
void ainekio_v2_walk_command_features(const ainekio_v2_walk_state_t *state,float values[4]);
/* Stateless reference pose, for C/Python parity and diagnostic sampling. */
bool ainekio_v2_walk_pose(double phase, ainekio_v2_walk_controls_t controls,
                         ainekio_v2_walk_pose_t *out);
bool ainekio_v2_walk_solve(ainekio_v2_walk_pose_t *pose);
/* Convert model-order centidegrees to source-leg radians and copy the frame.
 * Retains body/euler/contact fields; contact_forward initializes anchors. */
void ainekio_v2_pose_from_frame(ainekio_v2_walk_pose_t *pose,
    const ainekio_v2_frame_t *frame);
/* Fixed material point on each lower leg, in body coordinates (mm), model
 * joint order. This is inferred geometry, not measured ground contact. */
unsigned ainekio_v2_feet_forward(const ainekio_v2_frame_t *frame, float feet[4][3]);
/* Analytic containing box for body-axis foot offsets from reference, across
 * the supplied model-joint ranges. All feasible four-bar poses are included;
 * box corners need not be reachable. Existing IK/branch and calibrated pulse
 * mapping still determine which requested targets can execute. */
bool ainekio_v2_foot_offset_bounds(const ainekio_v2_frame_t *reference,
    const float lower_cd[12], const float upper_cd[12],
    float lower_mm[4][3], float upper_mm[4][3]);
/* Task-space residual through the same fixed-shaft linkage and assembly branch.
 * Does not change the gait clock, nominal state, calibration or servo mapping. */
bool ainekio_v2_feet_offset(const ainekio_v2_frame_t *nominal,
    const float delta[4][3], ainekio_v2_frame_t *out);
/* Joint-bounded Cartesian IK for the two linkage actuators. Shoulder targets
 * stay unchanged. Already feasible frames pass through exactly. */
bool ainekio_v2_feet_bounded(ainekio_v2_frame_t *frame,
    const float lower_cd[12], const float upper_cd[12]);
/* Apply desired body-coordinate foot offsets through the existing per-leg
 * IK/fit search. No phase, sensor policy, model coefficients or timing here.
 * Offset arrays use physical model leg order. Returns minimum accepted fit. */
float ainekio_v2_learning_offsets_apply(const float desired[4][3],
    const ainekio_v2_frame_t *nominal,bool (*valid)(const ainekio_v2_frame_t *,void *),
    void *context,ainekio_v2_frame_t *output,float applied[4][3],float leg_fit[4]);
/* Resolve an absolute foot target relative to an explicit fixed reference,
 * then construct its modeled material-point anchors for heading/balance.
 * The optional calibration projection preserves the Cartesian target as far
 * as calibrated joint travel permits, before scalar IK fallback. Applied
 * offsets report the resolved FK; leg_fit reports the attempted scalar,
 * so 1 does not imply the calibration projection left the target unchanged.
 * Residual corrections retain their separate scalar-only behavior. */
bool ainekio_v2_nominal_foot_pose(const ainekio_v2_frame_t *reference,
    const float desired[4][3],bool (*valid)(const ainekio_v2_frame_t *,void *),
    bool (*project)(ainekio_v2_frame_t *,void *),
    void *context,ainekio_v2_walk_pose_t *pose,double anchors[4][3],
    float applied[4][3],float leg_fit[4]);
/* Material-point anchors for contact-aware posture transitions. Source leg
 * order, local sole coordinates. Forward chooses lowest sole points when
 * choose_contacts is true; otherwise evaluates the supplied material points.
 * These are modeled contacts, never measured foot contact. */
bool ainekio_v2_contact_forward(ainekio_v2_walk_pose_t *pose,
    double local_points[4][3], bool choose_contacts);
bool ainekio_v2_contact_solve(ainekio_v2_walk_pose_t *pose,
    const double local_points[4][3]);
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
/* Heading correction shares the existing steering range, not the servo clock.
 * Optional validator checks the candidate against the owning body's calibrated
 * pulse mapping. Failure removes only the added correction, never the request. */
bool ainekio_v2_walk_feedback_tick(ainekio_v2_walk_state_t *state,
    uint64_t now_us, bool enabled, bool usable, double yaw_rad,
    bool (*valid)(const ainekio_v2_frame_t *, void *), void *context);
/* Observe the same relative IMU yaw and integrate an explicitly supplied
 * operator reference delta from the native phase-integrated curve. Host neural
 * walking supplies its own yaw correction in foot targets. */
void ainekio_v2_walk_heading_observe(ainekio_v2_walk_state_t *state,
    bool enabled,bool usable,double yaw_rad,double reference_delta_rad);
/* Call after common session/expiry admission. Updates name the original walk. */
bool ainekio_v2_walk_accept(ainekio_v2_walk_state_t *state,
                           const ainekio_command_t *command, uint64_t now_us);
#endif
