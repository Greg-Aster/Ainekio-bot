#ifndef AINEKIO_V2_LEARNING_H
#define AINEKIO_V2_LEARNING_H
#include "ainekio/v2_walk.h"
#define AINEKIO_LEARNING_TERMS 5
#define AINEKIO_LEARNING_FEEDBACK_TERMS 8
#define AINEKIO_LEARNING_COMMAND_TERMS 4
/* Two harmonics, physical model leg order, body-coordinate millimetres. */
typedef struct {
    float coefficient[4][3][AINEKIO_LEARNING_TERMS];
    /* Per leg: reference-point error xyz / 10 mm, roll/pitch target error
     * / 0.1 rad, body angular velocity xyz / 1 rad/s. Output is millimetres.
     * These are measured shaft/attitude features, never contact or force. */
    float feedback[4][3][AINEKIO_LEARNING_FEEDBACK_TERMS];
    float command[4][3][AINEKIO_LEARNING_COMMAND_TERMS]; /* forward, turn, lateral, stride; unit fractions */
    ainekio_v2_gait_profile_t gait;
} ainekio_v2_learning_model_t;
typedef struct {
    float feature[4][AINEKIO_LEARNING_FEEDBACK_TERMS];
    float command[AINEKIO_LEARNING_COMMAND_TERMS];
} ainekio_v2_learning_input_t;
typedef struct {
    float blend, applied[4][3], fit, leg_fit[4];
    float feedback_residual[4][3]; /* Last usable response, faded on sensor loss. */
} ainekio_v2_learning_state_t;
void ainekio_v2_learning_basis(double phase,double basis[AINEKIO_LEARNING_TERMS]);
void ainekio_v2_learning_features(const float error_mm[4][3],const float q[4],
    const double target_euler[2],const float angular_rate[3],ainekio_v2_learning_input_t *input);
void ainekio_v2_learning_policy_apply(ainekio_v2_learning_state_t *state,
    const ainekio_v2_learning_model_t *model,const ainekio_v2_learning_input_t *input,
    double phase,double phase_delta,bool usable,float amount,const ainekio_v2_frame_t *nominal,
    bool (*valid)(const ainekio_v2_frame_t *,void *),void *context,
    ainekio_v2_frame_t *output);
/* Legacy phase-only entry point: zero sensor contribution. */
void ainekio_v2_learning_apply(ainekio_v2_learning_state_t *state,
    const ainekio_v2_learning_model_t *model,double phase,double phase_delta,
    bool usable,float amount,const ainekio_v2_frame_t *nominal,
    bool (*valid)(const ainekio_v2_frame_t *,void *),void *context,
    ainekio_v2_frame_t *output);
#endif
