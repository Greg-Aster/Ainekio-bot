#include "ainekio/v1_model.h"
#include <math.h>
#include <string.h>

#define TWO_PI (2.0 * 3.14159265358979323846)

bool ainekio_v1_posture_angles(const char *name, float out_deg[AINEKIO_V1_JOINT_COUNT])
{
    if (!name || !out_deg) return false;
    memset(out_deg, 0, sizeof(float) * AINEKIO_V1_JOINT_COUNT);

    if (strcmp(name, "stand") == 0 || strcmp(name, "home") == 0 || strcmp(name, "neutral") == 0) {
        /* 0 deg across all 8 joints = standing neutral pose from v3-2.blend */
        return true;
    }
    if (strcmp(name, "crouch") == 0) {
        out_deg[AINEKIO_V1_J_R3] = 28.0f;
        out_deg[AINEKIO_V1_J_L3] = 28.0f;
        out_deg[AINEKIO_V1_J_R4] = 28.0f;
        out_deg[AINEKIO_V1_J_L4] = 28.0f;
        return true;
    }
    if (strcmp(name, "lay_down") == 0 || strcmp(name, "rest") == 0 || strcmp(name, "sleep") == 0) {
        /* Splay knees high so belly rests cleanly on ground */
        out_deg[AINEKIO_V1_J_R1] = 10.0f;
        out_deg[AINEKIO_V1_J_L1] = 10.0f;
        out_deg[AINEKIO_V1_J_R2] = -10.0f;
        out_deg[AINEKIO_V1_J_L2] = -10.0f;
        out_deg[AINEKIO_V1_J_R3] = 75.0f;
        out_deg[AINEKIO_V1_J_L3] = 75.0f;
        out_deg[AINEKIO_V1_J_R4] = 75.0f;
        out_deg[AINEKIO_V1_J_L4] = 75.0f;
        return true;
    }
    if (strcmp(name, "sit") == 0) {
        /* Rear knees tucked down low, front legs extended tall */
        out_deg[AINEKIO_V1_J_R1] = 8.0f;
        out_deg[AINEKIO_V1_J_L1] = 8.0f;
        out_deg[AINEKIO_V1_J_R2] = -15.0f;
        out_deg[AINEKIO_V1_J_L2] = -15.0f;
        out_deg[AINEKIO_V1_J_R3] = -8.0f;
        out_deg[AINEKIO_V1_J_L3] = -8.0f;
        out_deg[AINEKIO_V1_J_R4] = 58.0f;
        out_deg[AINEKIO_V1_J_L4] = 58.0f;
        return true;
    }
    if (strcmp(name, "bow") == 0 || strcmp(name, "play_bow") == 0) {
        /* Front crouched low, rear tall */
        out_deg[AINEKIO_V1_J_R1] = 15.0f;
        out_deg[AINEKIO_V1_J_L1] = 15.0f;
        out_deg[AINEKIO_V1_J_R3] = 55.0f;
        out_deg[AINEKIO_V1_J_L3] = 55.0f;
        out_deg[AINEKIO_V1_J_R4] = -5.0f;
        out_deg[AINEKIO_V1_J_L4] = -5.0f;
        return true;
    }
    if (strcmp(name, "stretch") == 0) {
        out_deg[AINEKIO_V1_J_R1] = 20.0f;
        out_deg[AINEKIO_V1_J_L1] = 20.0f;
        out_deg[AINEKIO_V1_J_R2] = -20.0f;
        out_deg[AINEKIO_V1_J_L2] = -20.0f;
        out_deg[AINEKIO_V1_J_R3] = 35.0f;
        out_deg[AINEKIO_V1_J_L3] = 35.0f;
        out_deg[AINEKIO_V1_J_R4] = 10.0f;
        out_deg[AINEKIO_V1_J_L4] = 10.0f;
        return true;
    }
    if (strcmp(name, "wave") == 0) {
        /* Raise front-right leg high while stabilizing on the other 3 legs */
        out_deg[AINEKIO_V1_J_R1] = 32.0f;
        out_deg[AINEKIO_V1_J_R3] = 95.0f;
        out_deg[AINEKIO_V1_J_L1] = -8.0f;
        out_deg[AINEKIO_V1_J_L3] = 10.0f;
        out_deg[AINEKIO_V1_J_R2] = 10.0f;
        out_deg[AINEKIO_V1_J_R4] = 20.0f;
        out_deg[AINEKIO_V1_J_L2] = -6.0f;
        out_deg[AINEKIO_V1_J_L4] = 15.0f;
        return true;
    }
    return false;
}

void ainekio_v1_walk_sample(double phase_0_1, float vx_norm, float vy_norm, float wz_norm,
                            float stride_scale, float out_deg[AINEKIO_V1_JOINT_COUNT])
{
    if (!out_deg) return;
    double p = fmod(phase_0_1, 1.0);
    if (p < 0.0) p += 1.0;
    if (stride_scale < 0.0f) stride_scale = 0.0f;
    if (stride_scale > 1.5f) stride_scale = 1.5f;

    /* Diagonal trot phase offsets: (FR + RL) = 0.0, (FL + RR) = 0.5 */
    static const double leg_phase_off[AINEKIO_V1_LEG_COUNT] = { 0.0, 0.5, 0.5, 0.0 };
    const float cmd_mag = fminf(1.0f, hypotf(hypotf(vx_norm, vy_norm), fabsf(wz_norm)));
    const float hip_amp_deg = 22.0f * stride_scale;
    const float lift_deg = 26.0f * (0.25f + 0.75f * cmd_mag) * fminf(1.0f, stride_scale);
    const float stance_knee_deg = 6.0f; /* Slight compliant stance crouch */

    for (unsigned i = 0; i < AINEKIO_V1_LEG_COUNT; ++i) {
        const ainekio_v1_leg_geom_t *g = &ainekio_v1_legs[i];
        double lp = fmod(p + leg_phase_off[i], 1.0);
        const bool is_left = (i == AINEKIO_V1_LEG_FL || i == AINEKIO_V1_LEG_RL);
        const bool is_front = (i == AINEKIO_V1_LEG_FR || i == AINEKIO_V1_LEG_FL);

        /* Combine forward (vx), yaw turn (wz: +wz turns CCW => right fwd, left back),
         * and subtle lateral (vy) stride projection onto hip yaw sweep. */
        float dir = vx_norm + (is_left ? -wz_norm : wz_norm)
                    + 0.45f * vy_norm * ((is_front ^ is_left) ? -1.0f : 1.0f);
        if (dir > 1.0f) dir = 1.0f;
        if (dir < -1.0f) dir = -1.0f;

        float hip = 0.0f;
        float knee = stance_knee_deg;
        if (lp < 0.5) {
            /* Swing half-cycle [0.0 .. 0.5): lift foot cleanly and swing forward */
            const double s = lp / 0.5;
            hip = (float)(-cos(3.14159265358979323846 * s) * (double)(hip_amp_deg * dir));
            knee = stance_knee_deg + (float)(sin(3.14159265358979323846 * s) * (double)lift_deg);
        } else {
            /* Stance half-cycle [0.5 .. 1.0): push body forward smoothly */
            const double s = (lp - 0.5) / 0.5;
            hip = (float)(cos(3.14159265358979323846 * s) * (double)(hip_amp_deg * dir));
            knee = stance_knee_deg;
        }
        out_deg[g->hip_joint] = ainekio_v1_clamp_joint_deg(g->hip_joint, hip);
        out_deg[g->knee_joint] = ainekio_v1_clamp_joint_deg(g->knee_joint, knee);
    }
}
