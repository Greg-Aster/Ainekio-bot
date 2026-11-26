#include "ainekio/v1_model.h"
#include <math.h>
#include <string.h>

#define DEG2RAD (3.14159265358979323846 / 180.0)
#define RAD2DEG (180.0 / 3.14159265358979323846)

const char ainekio_v1_geometry_id[] = "v1-p4-clockspring-20261121";

const ainekio_v1_joint_info_t ainekio_v1_joints[AINEKIO_V1_JOINT_COUNT] = {
    { AINEKIO_V1_J_R1, "R1", "front_right_hip",  AINEKIO_V1_LEG_FR, false, 0, -45.0f,  45.0f },
    { AINEKIO_V1_J_R2, "R2", "rear_right_hip",   AINEKIO_V1_LEG_RR, false, 1, -45.0f,  45.0f },
    { AINEKIO_V1_J_L1, "L1", "front_left_hip",   AINEKIO_V1_LEG_FL, false, 2, -45.0f,  45.0f },
    { AINEKIO_V1_J_L2, "L2", "rear_left_hip",    AINEKIO_V1_LEG_RL, false, 3, -45.0f,  45.0f },
    { AINEKIO_V1_J_R4, "R4", "rear_right_knee",  AINEKIO_V1_LEG_RR, true,  4, -15.0f, 115.0f },
    { AINEKIO_V1_J_R3, "R3", "front_right_knee", AINEKIO_V1_LEG_FR, true,  5, -15.0f, 115.0f },
    { AINEKIO_V1_J_L3, "L3", "front_left_knee",  AINEKIO_V1_LEG_FL, true,  6, -15.0f, 115.0f },
    { AINEKIO_V1_J_L4, "L4", "rear_left_knee",   AINEKIO_V1_LEG_RL, true,  7, -15.0f, 115.0f },
};

/* Exact geometry exported from v3-2.blend (scene 'v1', Robot Root body frame, mm). */
const ainekio_v1_leg_geom_t ainekio_v1_legs[AINEKIO_V1_LEG_COUNT] = {
    {
        .leg = AINEKIO_V1_LEG_FR,
        .name = "front_right",
        .hip_joint = AINEKIO_V1_J_R1,
        .knee_joint = AINEKIO_V1_J_R3,
        .neutral_yaw_deg = -45.0f,
        .hip_sign = +1.0f,
        .hip_in_body_mm = { 48.3500f, -38.5000f, 3.4750f },
        .knee_in_hip_mm = { 28.0000f,  6.7440f, 6.1000f },
        .foot_in_knee_mm = { -12.2700f, 2.6850f, -66.2400f },
        .foot_stand_body_mm = { 66.1410f, -42.9550f, -56.6650f },
    },
    {
        .leg = AINEKIO_V1_LEG_RR,
        .name = "rear_right",
        .hip_joint = AINEKIO_V1_J_R2,
        .knee_joint = AINEKIO_V1_J_R4,
        .neutral_yaw_deg = -135.0f,
        .hip_sign = +1.0f,
        .hip_in_body_mm = { -48.3500f, -38.5000f, 3.4750f },
        .knee_in_hip_mm = { 28.0000f, -6.7440f, 6.1000f },
        .foot_in_knee_mm = { -12.2700f, -2.6850f, -66.2400f },
        .foot_stand_body_mm = { -66.1400f, -42.9560f, -56.6650f },
    },
    {
        .leg = AINEKIO_V1_LEG_FL,
        .name = "front_left",
        .hip_joint = AINEKIO_V1_J_L1,
        .knee_joint = AINEKIO_V1_J_L3,
        .neutral_yaw_deg = 45.0f,
        .hip_sign = -1.0f,
        .hip_in_body_mm = { 48.3500f, 38.5000f, 3.4750f },
        .knee_in_hip_mm = { 28.0000f, -6.7440f, 6.1000f },
        .foot_in_knee_mm = { -12.2700f, -2.6850f, -66.2400f },
        .foot_stand_body_mm = { 66.1400f, 42.9560f, -56.6650f },
    },
    {
        .leg = AINEKIO_V1_LEG_RL,
        .name = "rear_left",
        .hip_joint = AINEKIO_V1_J_L2,
        .knee_joint = AINEKIO_V1_J_L4,
        .neutral_yaw_deg = 135.0f,
        .hip_sign = -1.0f,
        .hip_in_body_mm = { -48.3500f, 38.5000f, 3.4750f },
        .knee_in_hip_mm = { 28.0000f, 6.7440f, 6.1000f },
        .foot_in_knee_mm = { -12.2700f, 2.6850f, -66.2400f },
        .foot_stand_body_mm = { -66.1400f, 42.9560f, -56.6650f },
    },
};

float ainekio_v1_clamp_joint_deg(uint8_t joint_id, float deg)
{
    if (joint_id >= AINEKIO_V1_JOINT_COUNT) return 0.0f;
    if (!isfinite(deg)) return 0.0f;
    const float lo = ainekio_v1_joints[joint_id].min_deg;
    const float hi = ainekio_v1_joints[joint_id].max_deg;
    if (deg < lo) return lo;
    if (deg > hi) return hi;
    return deg;
}

void ainekio_v1_clamp_angles_deg(float angles_deg[AINEKIO_V1_JOINT_COUNT])
{
    if (!angles_deg) return;
    for (uint8_t i = 0; i < AINEKIO_V1_JOINT_COUNT; ++i)
        angles_deg[i] = ainekio_v1_clamp_joint_deg(i, angles_deg[i]);
}

void ainekio_v1_leg_fk(ainekio_v1_leg_t leg, float hip_deg, float knee_deg, float foot_body_mm[3])
{
    if ((unsigned)leg >= AINEKIO_V1_LEG_COUNT || !foot_body_mm) return;
    const ainekio_v1_leg_geom_t *g = &ainekio_v1_legs[leg];
    /* +knee_deg lifts foot outward & up => rot_y = -knee_deg around Knee local +Y */
    const double ky = -(double)knee_deg * DEG2RAD;
    const double cky = cos(ky), sky = sin(ky);
    const double fk_x = g->foot_in_knee_mm[0];
    const double fk_y = g->foot_in_knee_mm[1];
    const double fk_z = g->foot_in_knee_mm[2];
    /* Standard right-handed Y rotation: x' = c*x + s*z, z' = -s*x + c*z */
    const double rot_x = cky * fk_x + sky * fk_z;
    const double rot_z = -sky * fk_x + cky * fk_z;
    /* Point in Hip local frame */
    const double hx = (double)g->knee_in_hip_mm[0] + rot_x;
    const double hy = (double)g->knee_in_hip_mm[1] + fk_y;
    const double hz = (double)g->knee_in_hip_mm[2] + rot_z;
    /* Hip yaw rotation around +Z: yaw = neutral_yaw + hip_sign * hip_deg */
    const double yaw = ((double)g->neutral_yaw_deg + (double)g->hip_sign * (double)hip_deg) * DEG2RAD;
    const double cy = cos(yaw), sy = sin(yaw);
    foot_body_mm[0] = (float)((double)g->hip_in_body_mm[0] + cy * hx - sy * hy);
    foot_body_mm[1] = (float)((double)g->hip_in_body_mm[1] + sy * hx + cy * hy);
    foot_body_mm[2] = (float)((double)g->hip_in_body_mm[2] + hz);
}

void ainekio_v1_leg_ik_offset(ainekio_v1_leg_t leg, const float offset_mm[3],
                              float *hip_deg_out, float *knee_deg_out)
{
    if ((unsigned)leg >= AINEKIO_V1_LEG_COUNT || !offset_mm || !hip_deg_out || !knee_deg_out) return;
    const ainekio_v1_leg_geom_t *g = &ainekio_v1_legs[leg];
    const double tx = (double)g->foot_stand_body_mm[0] + (double)offset_mm[0];
    const double ty = (double)g->foot_stand_body_mm[1] + (double)offset_mm[1];
    const double tz = (double)g->foot_stand_body_mm[2] + (double)offset_mm[2];

    /* 1. Solve knee angle from desired foot Z:
     *    tz - (hip_z + knee_in_hip_z) = rot_z = -sin(ky)*fk_x + cos(ky)*fk_z
     *    with ky = -knee_rad => sin(knee)*fk_x + cos(knee)*fk_z = dz_k */
    const double dz_k = tz - ((double)g->hip_in_body_mm[2] + (double)g->knee_in_hip_mm[2]);
    const double fk_x = g->foot_in_knee_mm[0];
    const double fk_z = g->foot_in_knee_mm[2];
    const double L = hypot(fk_x, fk_z);
    /* Write sin(k)*fk_x + cos(k)*fk_z = L * cos(k - phi), where cos(phi) = fk_z/L, sin(phi) = fk_x/L.
     * For fk_x = -12.27, fk_z = -66.24: phi = atan2(-12.27, -66.24) = -169.51 deg (or +190.49 deg).
     * At k=0: cos(-phi) = fk_z/L = -0.9833. Increasing k>0 increases dz_k toward +L! */
    const double phi = atan2(fk_x, fk_z); /* ~ -169.51 deg */
    double ratio = dz_k / L;
    if (ratio > 1.0) ratio = 1.0;
    if (ratio < -1.0) ratio = -1.0;
    /* Outward-swinging branch (k >= +10.5 deg -> lifts foot outward & up, away from chassis).
     * For zero offset, return exact standing neutral (0 deg). */
    double k_rad;
    if (fabs((double)offset_mm[2]) < 1e-4) {
        k_rad = 0.0;
    } else {
        k_rad = phi - acos(ratio);
        while (k_rad > 3.14159265358979323846) k_rad -= 2.0 * 3.14159265358979323846;
        while (k_rad < -3.14159265358979323846) k_rad += 2.0 * 3.14159265358979323846;
    }
    float knee_deg = ainekio_v1_clamp_joint_deg(g->knee_joint, (float)(k_rad * RAD2DEG));

    /* 2. Solve hip yaw angle from desired horizontal vector (tx - hip_x, ty - hip_y),
     *    accounting for the lateral foot offset hy = knee_in_hip_y + foot_in_knee_y! */
    const double ky = -(double)knee_deg * DEG2RAD;
    const double hx = (double)g->knee_in_hip_mm[0] + cos(ky) * fk_x + sin(ky) * fk_z;
    const double hy = (double)g->knee_in_hip_mm[1] + (double)g->foot_in_knee_mm[1];
    const double rx = tx - (double)g->hip_in_body_mm[0];
    const double ry = ty - (double)g->hip_in_body_mm[1];
    const double target_ang = atan2(ry, rx);
    const double local_ang = atan2(hy, hx);
    double yaw_deg = (target_ang - local_ang) * RAD2DEG;
    double delta_deg = yaw_deg - (double)g->neutral_yaw_deg;
    while (delta_deg > 180.0) delta_deg -= 360.0;
    while (delta_deg < -180.0) delta_deg += 360.0;
    float hip_deg = ainekio_v1_clamp_joint_deg(g->hip_joint, (float)((double)g->hip_sign * delta_deg));

    *hip_deg_out = hip_deg;
    *knee_deg_out = knee_deg;
}
