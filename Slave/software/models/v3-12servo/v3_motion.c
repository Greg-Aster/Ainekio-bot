#include "ainekio/v3_model.h"
#include <math.h>
#include <string.h>

typedef struct {
    const char *name;
    float angles_deg[AINEKIO_V3_JOINT_COUNT];
} v3_posture_t;

/* Map-2 joint order: [RL(h,a,t), RR(h,a,t), FL(h,a,t), FR(h,a,t)].
 * Positive h_deg adducts inward (symmetric on L/R); positive alpha_deg swings
 * knee forward/down; positive theta_deg swings lower leg forward/up. */
static const v3_posture_t V3_POSTURES[] = {
    {"stand",    {  0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f}},
    {"home",     {  0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f,   0.0f}},
    {"crouch",   { -4.0f, -22.0f,  28.0f,  -4.0f, -22.0f,  28.0f,  -4.0f, -22.0f,  28.0f,  -4.0f, -22.0f,  28.0f}},
    {"lay_down", { -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f}},
    {"rest",     { -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f}},
    {"sleep",    { -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f,  -8.0f, -38.0f,  46.0f}},
    {"sit",      { -4.0f, -34.0f,  42.0f,  -4.0f, -34.0f,  42.0f,   0.0f,  14.0f, -12.0f,   0.0f,  14.0f, -12.0f}},
    {"bow",      {  0.0f,  12.0f, -10.0f,   0.0f,  12.0f, -10.0f,  -4.0f, -34.0f,  42.0f,  -4.0f, -34.0f,  42.0f}},
    {"stretch",  {  0.0f, -18.0f, -24.0f,   0.0f, -18.0f, -24.0f,   0.0f,  24.0f,  28.0f,   0.0f,  24.0f,  28.0f}},
    {"wave_fr",  { -6.0f,  -8.0f,   8.0f,   4.0f, -14.0f,  16.0f,   6.0f, -12.0f,  14.0f, -12.0f,  36.0f,  42.0f}},
    {"wave_fl",  {  4.0f, -14.0f,  16.0f,  -6.0f,  -8.0f,   8.0f, -12.0f,  36.0f,  42.0f,   6.0f, -12.0f,  14.0f}},
};

bool ainekio_v3_posture_angles(
    const char *name,
    float angles_deg_out[AINEKIO_V3_JOINT_COUNT])
{
    if (!name || !angles_deg_out) return false;
    for (unsigned i = 0; i < sizeof(V3_POSTURES) / sizeof(V3_POSTURES[0]); ++i) {
        if (strcmp(name, V3_POSTURES[i].name) == 0) {
            for (unsigned j = 0; j < AINEKIO_V3_JOINT_COUNT; ++j)
                angles_deg_out[j] = ainekio_v3_clamp_joint_deg((uint8_t)j, V3_POSTURES[i].angles_deg[j]);
            return true;
        }
    }
    return false;
}

void ainekio_v3_analytic_trot(
    double phase_cycles,
    float vx_m_s,
    float vy_m_s,
    float wz_rad_s,
    float angles_deg_out[AINEKIO_V3_JOINT_COUNT])
{
    if (!angles_deg_out) return;
    const float cmd_mag = hypotf(vx_m_s, vy_m_s) + 0.18f * fabsf(wz_rad_s);
    if (cmd_mag < 0.015f) {
        for (unsigned j = 0; j < AINEKIO_V3_JOINT_COUNT; ++j) angles_deg_out[j] = 0.0f;
        return;
    }

    /* Diagonal trot pairs: Pair A = (FL, RR) phase 0.0; Pair B = (FR, RL) phase 0.5 */
    static const float LEG_PHASE[AINEKIO_V3_LEG_COUNT] = {0.5f, 0.0f, 0.0f, 0.5f};
    const float vx_norm = fmaxf(-1.0f, fminf(1.0f, vx_m_s / 0.35f));
    const float vy_norm = fmaxf(-1.0f, fminf(1.0f, vy_m_s / 0.20f));
    const float wz_norm = fmaxf(-1.0f, fminf(1.0f, wz_rad_s / 1.50f));
    const float lift_scale = fminf(1.0f, cmd_mag / 0.08f);

    for (unsigned l = 0; l < AINEKIO_V3_LEG_COUNT; ++l) {
        const ainekio_v3_leg_spec_t *leg = &ainekio_v3_legs[l];
        double p = fmod(phase_cycles + (double)LEG_PHASE[l], 1.0);
        if (p < 0.0) p += 1.0;

        float sweep = 0.0f;
        float lift_mm = 0.0f;
        if (p < 0.5) {
            const float u = (float)(p / 0.5);
            sweep = -cosf(u * 3.14159265f); /* -1 -> +1 swing forward */
            lift_mm = 26.0f * sinf(u * 3.14159265f) * lift_scale;
        } else {
            const float u = (float)((p - 0.5) / 0.5);
            sweep = 1.0f - 2.0f * u; /* +1 -> -1 stance push */
            lift_mm = 0.0f;
        }

        const float rx_leg = leg->neutral_sole_in_robot_mm[0] * 0.001f;
        const float ry_leg = leg->neutral_sole_in_robot_mm[1] * 0.001f;
        const float dx_mm = 32.0f * (vx_norm - wz_norm * ry_leg * 6.0f) * sweep;
        const float dy_mm = 24.0f * (vy_norm + wz_norm * rx_leg * 4.0f) * sweep;
        const float dz_mm = -8.0f + lift_mm; /* slight athletic crouch + swing lift */

        float h = 0.0f, a = 0.0f, t = 0.0f;
        if (!ainekio_v3_leg_ik_offset((ainekio_v3_leg_id_t)l, dx_mm, dy_mm, dz_mm, &h, &a, &t)) {
            h = 0.0f; a = 0.0f; t = 0.0f;
        }
        angles_deg_out[leg->shoulder_joint] = h;
        angles_deg_out[leg->carrier_joint] = a;
        angles_deg_out[leg->crank_joint] = t;
    }
}
