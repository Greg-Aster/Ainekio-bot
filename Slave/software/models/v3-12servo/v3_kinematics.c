#include "ainekio/v3_model.h"
#include <math.h>
#include <stddef.h>

static const float DEG_TO_RAD = 0.01745329251994329577f;
static const float RAD_TO_DEG = 57.2957795130823208768f;

const ainekio_v3_joint_spec_t ainekio_v3_joints[AINEKIO_V3_JOINT_COUNT] = {
    {0,  "rear_left_shoulder",   AINEKIO_V3_LEG_RL, AINEKIO_V3_AXIS_SHOULDER, -30.0f, 30.0f},
    {1,  "rear_left_carrier",    AINEKIO_V3_LEG_RL, AINEKIO_V3_AXIS_CARRIER,  -40.0f, 50.0f},
    {2,  "rear_left_crank",      AINEKIO_V3_LEG_RL, AINEKIO_V3_AXIS_CRANK,    -50.0f, 50.0f},
    {3,  "rear_right_shoulder",  AINEKIO_V3_LEG_RR, AINEKIO_V3_AXIS_SHOULDER, -30.0f, 30.0f},
    {4,  "rear_right_carrier",   AINEKIO_V3_LEG_RR, AINEKIO_V3_AXIS_CARRIER,  -40.0f, 50.0f},
    {5,  "rear_right_crank",     AINEKIO_V3_LEG_RR, AINEKIO_V3_AXIS_CRANK,    -50.0f, 50.0f},
    {6,  "front_left_shoulder",  AINEKIO_V3_LEG_FL, AINEKIO_V3_AXIS_SHOULDER, -30.0f, 30.0f},
    {7,  "front_left_carrier",   AINEKIO_V3_LEG_FL, AINEKIO_V3_AXIS_CARRIER,  -40.0f, 50.0f},
    {8,  "front_left_crank",     AINEKIO_V3_LEG_FL, AINEKIO_V3_AXIS_CRANK,    -50.0f, 50.0f},
    {9,  "front_right_shoulder", AINEKIO_V3_LEG_FR, AINEKIO_V3_AXIS_SHOULDER, -30.0f, 30.0f},
    {10, "front_right_carrier",  AINEKIO_V3_LEG_FR, AINEKIO_V3_AXIS_CARRIER,  -40.0f, 50.0f},
    {11, "front_right_crank",    AINEKIO_V3_LEG_FR, AINEKIO_V3_AXIS_CRANK,    -50.0f, 50.0f},
};

const ainekio_v3_leg_spec_t ainekio_v3_legs[AINEKIO_V3_LEG_COUNT] = {
    {
        .id = AINEKIO_V3_LEG_RL,
        .name = "rear_left",
        .shoulder_joint = 0,
        .carrier_joint = 1,
        .crank_joint = 2,
        .roll_sign = -1.0f,
        .shoulder_in_robot_mm = {-128.0f, 47.2f, 140.0f},
        .carrier_in_shoulder_mm = {36.05f, 3.66f, -19.75f},
        .crank_in_shoulder_mm = {16.0f, 3.66f, 0.25f},
        .sole_in_knee_mm = {133.3995f, 44.5f, -25.4657f},
        .neutral_sole_in_robot_mm = {-55.9487f, 95.36f, -40.9336f},
    },
    {
        .id = AINEKIO_V3_LEG_RR,
        .name = "rear_right",
        .shoulder_joint = 3,
        .carrier_joint = 4,
        .crank_joint = 5,
        .roll_sign = 1.0f,
        .shoulder_in_robot_mm = {-128.0f, -47.2f, 140.0f},
        .carrier_in_shoulder_mm = {36.05f, -3.66f, -19.75f},
        .crank_in_shoulder_mm = {16.0f, -3.66f, 0.25f},
        .sole_in_knee_mm = {133.3995f, -44.5f, -25.4657f},
        .neutral_sole_in_robot_mm = {-55.9487f, -95.36f, -40.9336f},
    },
    {
        .id = AINEKIO_V3_LEG_FL,
        .name = "front_left",
        .shoulder_joint = 6,
        .carrier_joint = 7,
        .crank_joint = 8,
        .roll_sign = -1.0f,
        .shoulder_in_robot_mm = {143.5f, 47.2f, 140.0f},
        .carrier_in_shoulder_mm = {-16.0f, 3.66f, -19.75f},
        .crank_in_shoulder_mm = {-36.05f, 3.66f, 0.25f},
        .sole_in_knee_mm = {133.3995f, 44.5f, -25.4657f},
        .neutral_sole_in_robot_mm = {163.5013f, 95.36f, -40.9336f},
    },
    {
        .id = AINEKIO_V3_LEG_FR,
        .name = "front_right",
        .shoulder_joint = 9,
        .carrier_joint = 10,
        .crank_joint = 11,
        .roll_sign = 1.0f,
        .shoulder_in_robot_mm = {143.5f, -47.2f, 140.0f},
        .carrier_in_shoulder_mm = {-16.0f, -3.66f, -19.75f},
        .crank_in_shoulder_mm = {-36.05f, -3.66f, 0.25f},
        .sole_in_knee_mm = {133.3995f, -44.5f, -25.4657f},
        .neutral_sole_in_robot_mm = {163.5013f, -95.36f, -40.9336f},
    },
};

float ainekio_v3_clamp_joint_deg(uint8_t joint_id, float deg)
{
    if (joint_id >= AINEKIO_V3_JOINT_COUNT || !isfinite(deg)) return 0.0f;
    const ainekio_v3_joint_spec_t *spec = &ainekio_v3_joints[joint_id];
    if (deg < spec->min_deg) return spec->min_deg;
    if (deg > spec->max_deg) return spec->max_deg;
    return deg;
}

bool ainekio_v3_leg_fk(
    ainekio_v3_leg_id_t leg_id,
    float h_deg,
    float alpha_deg,
    float theta_deg,
    ainekio_v3_fk_result_t *out)
{
    if ((unsigned)leg_id >= AINEKIO_V3_LEG_COUNT || !out) return false;
    if (!isfinite(h_deg) || !isfinite(alpha_deg) || !isfinite(theta_deg)) return false;

    const ainekio_v3_leg_spec_t *leg = &ainekio_v3_legs[leg_id];
    const float a = AINEKIO_V3_ALPHA_ZERO_RAD + alpha_deg * DEG_TO_RAD;
    const float t = AINEKIO_V3_THETA_ZERO_RAD + theta_deg * DEG_TO_RAD;

    const float dx = leg->carrier_in_shoulder_mm[0] + AINEKIO_V3_CARRIER_MM * cosf(a);
    const float dz = leg->carrier_in_shoulder_mm[2] + AINEKIO_V3_CARRIER_MM * sinf(a);
    const float px = leg->crank_in_shoulder_mm[0] + AINEKIO_V3_CRANK_MM * cosf(t);
    const float pz = leg->crank_in_shoulder_mm[2] + AINEKIO_V3_CRANK_MM * sinf(t);

    const float wx = px - dx;
    const float wz = pz - dz;
    const float d = hypotf(wx, wz);
    if (d <= 10.5f || d >= 101.5f) return false;

    const float pk2 = AINEKIO_V3_PICKUP_MM * AINEKIO_V3_PICKUP_MM;
    const float rd2 = AINEKIO_V3_ROD_MM * AINEKIO_V3_ROD_MM;
    const float along = (pk2 - rd2 + d * d) / (2.0f * d);
    const float h2 = pk2 - along * along;
    if (h2 <= 0.0f) return false;
    const float h = sqrtf(h2);

    const float ex = dx + (along * wx - h * wz) / d;
    const float ez = dz + (along * wz + h * wx) / d;

    const float ux = (ex - dx) / AINEKIO_V3_PICKUP_MM;
    const float uz = (ez - dz) / AINEKIO_V3_PICKUP_MM;
    const float vx = (ex - px) / AINEKIO_V3_ROD_MM;
    const float vz = (ez - pz) / AINEKIO_V3_ROD_MM;
    const float sin_mu = fabsf(ux * vz - uz * vx);

    const float beta = atan2f(ez - dz, ex - dx);
    const float diff = beta - AINEKIO_V3_BETA_OFFSET_RAD;
    const float knee_rot_y = -atan2f(sinf(diff), cosf(diff));

    /* Rotate sole offset in Knee frame by rot_y(knee_rot_y) */
    const float cy = cosf(knee_rot_y);
    const float sy = sinf(knee_rot_y);
    const float sx = leg->sole_in_knee_mm[0];
    const float sy_lat = leg->sole_in_knee_mm[1];
    const float sz = leg->sole_in_knee_mm[2];

    const float fx_sh = dx + cy * sx + sy * sz;
    const float fy_sh = leg->carrier_in_shoulder_mm[1] + sy_lat;
    const float fz_sh = dz - sy * sx + cy * sz;

    /* Rotate shoulder frame by rot_x(roll_sign * h_deg) */
    const float rx = leg->roll_sign * h_deg * DEG_TO_RAD;
    const float cr = cosf(rx);
    const float sr = sinf(rx);

    const float fx_rob = leg->shoulder_in_robot_mm[0] + fx_sh;
    const float fy_rob = leg->shoulder_in_robot_mm[1] + cr * fy_sh - sr * fz_sh;
    const float fz_rob = leg->shoulder_in_robot_mm[2] + sr * fy_sh + cr * fz_sh;

    out->foot_robot_mm[0] = fx_rob;
    out->foot_robot_mm[1] = fy_rob;
    out->foot_robot_mm[2] = fz_rob;
    out->knee_shoulder_mm[0] = dx;
    out->knee_shoulder_mm[1] = leg->carrier_in_shoulder_mm[1];
    out->knee_shoulder_mm[2] = dz;
    out->knee_rot_y_rad = knee_rot_y;
    out->separation_mm = d;
    out->sin_transmission = sin_mu;
    return true;
}

static float wrap_rad(float a)
{
    return remainderf(a, 6.2831853071795864769f);
}

bool ainekio_v3_leg_ik_offset(
    ainekio_v3_leg_id_t leg_id,
    float dx_mm,
    float dy_mm,
    float dz_mm,
    float *h_deg_out,
    float *alpha_deg_out,
    float *theta_deg_out)
{
    if ((unsigned)leg_id >= AINEKIO_V3_LEG_COUNT || !h_deg_out || !alpha_deg_out || !theta_deg_out)
        return false;
    if (!isfinite(dx_mm) || !isfinite(dy_mm) || !isfinite(dz_mm)) return false;

    const ainekio_v3_leg_spec_t *leg = &ainekio_v3_legs[leg_id];
    const float tx = leg->neutral_sole_in_robot_mm[0] + dx_mm - leg->shoulder_in_robot_mm[0];
    const float ty = leg->neutral_sole_in_robot_mm[1] + dy_mm - leg->shoulder_in_robot_mm[1];
    const float tz = leg->neutral_sole_in_robot_mm[2] + dz_mm - leg->shoulder_in_robot_mm[2];

    /* 1. Closed-form shoulder roll h_deg from constant lateral offset y_const */
    const float y_const = leg->carrier_in_shoulder_mm[1] + leg->sole_in_knee_mm[1];
    const float r2 = ty * ty + tz * tz;
    if (r2 <= y_const * y_const + 1e-4f) return false;
    const float z_sh = -sqrtf(r2 - y_const * y_const);
    const float cr = (y_const * ty + z_sh * tz) / r2;
    const float sr = (y_const * tz - z_sh * ty) / r2;
    const float rx = atan2f(sr, cr);
    const float h_deg = ainekio_v3_clamp_joint_deg(leg->shoulder_joint, (rx * RAD_TO_DEG) / leg->roll_sign);

    /* 2. Circle intersection for Knee (D) in sagittal shoulder plane (X, Z) */
    const float ox = leg->carrier_in_shoulder_mm[0];
    const float oz = leg->carrier_in_shoulder_mm[2];
    const float sx = leg->sole_in_knee_mm[0];
    const float sz = leg->sole_in_knee_mm[2];
    const float L_foot = hypotf(sx, sz);

    const float vx = tx - ox;
    const float vz = z_sh - oz;
    const float dist = hypotf(vx, vz);
    if (dist < fabsf(AINEKIO_V3_CARRIER_MM - L_foot) + 1e-3f ||
        dist > AINEKIO_V3_CARRIER_MM + L_foot - 1e-3f)
        return false;

    const float c2 = AINEKIO_V3_CARRIER_MM * AINEKIO_V3_CARRIER_MM;
    const float f2 = L_foot * L_foot;
    const float along = (c2 - f2 + dist * dist) / (2.0f * dist);
    const float h2 = c2 - along * along;
    if (h2 < 0.0f) return false;
    const float hh = sqrtf(h2);

    /* Select backward-bent knee branch nearest CAD neutral knee */
    const float ax = ox + (along * vx - hh * vz) / dist;
    const float az = oz + (along * vz + hh * vx) / dist;
    const float bx = ox + (along * vx + hh * vz) / dist;
    const float bz = oz + (along * vz - hh * vx) / dist;
    const float neutral_kx = ox + AINEKIO_V3_CARRIER_MM * cosf(AINEKIO_V3_ALPHA_ZERO_RAD);
    const float neutral_kz = oz + AINEKIO_V3_CARRIER_MM * sinf(AINEKIO_V3_ALPHA_ZERO_RAD);
    const float da = (ax - neutral_kx) * (ax - neutral_kx) + (az - neutral_kz) * (az - neutral_kz);
    const float db = (bx - neutral_kx) * (bx - neutral_kx) + (bz - neutral_kz) * (bz - neutral_kz);
    const float kx = (da <= db) ? ax : bx;
    const float kz = (da <= db) ? az : bz;

    const float alpha_rad = wrap_rad(atan2f(kz - oz, kx - ox) - AINEKIO_V3_ALPHA_ZERO_RAD);
    const float alpha_deg = ainekio_v3_clamp_joint_deg(leg->carrier_joint, alpha_rad * RAD_TO_DEG);

    /* 3. Compute required lower-leg orientation knee_rot_y, then pickup point E */
    const float lx = tx - kx;
    const float lz = z_sh - kz;
    /* lx = cy*sx + sy*sz, lz = -sy*sx + cy*sz */
    const float cy = (lx * sx + lz * sz) / f2;
    const float sy = (lx * sz - lz * sx) / f2;
    const float knee_rot_y = atan2f(sy, cy);
    const float beta = AINEKIO_V3_BETA_OFFSET_RAD - knee_rot_y;

    const float ex = kx + AINEKIO_V3_PICKUP_MM * cosf(beta);
    const float ez = kz + AINEKIO_V3_PICKUP_MM * sinf(beta);

    /* 4. Circle intersection between Crank circle (C, r=22) and Rod circle (E, R=56) for P */
    const float cx = leg->crank_in_shoulder_mm[0];
    const float cz = leg->crank_in_shoulder_mm[2];
    const float ex_c = ex - cx;
    const float ez_c = ez - cz;
    const float dc = hypotf(ex_c, ez_c);
    const float r_crk = AINEKIO_V3_CRANK_MM;
    const float r_rod = AINEKIO_V3_ROD_MM;
    if (dc < fabsf(r_crk - r_rod) + 1e-3f || dc > r_crk + r_rod - 1e-3f) return false;

    const float ca = (r_crk * r_crk - r_rod * r_rod + dc * dc) / (2.0f * dc);
    const float ch2 = r_crk * r_crk - ca * ca;
    if (ch2 < 0.0f) return false;
    const float ch = sqrtf(ch2);

    float best_theta_deg = 0.0f;
    float best_err = 1e9f;
    bool found = false;
    for (int s = -1; s <= 1; s += 2) {
        const float px = cx + (ca * ex_c - (float)s * ch * ez_c) / dc;
        const float pz = cz + (ca * ez_c + (float)s * ch * ex_c) / dc;
        const float td = wrap_rad(atan2f(pz - cz, px - cx) - AINEKIO_V3_THETA_ZERO_RAD) * RAD_TO_DEG;
        if (td < ainekio_v3_joints[leg->crank_joint].min_deg - 1.0f ||
            td > ainekio_v3_joints[leg->crank_joint].max_deg + 1.0f)
            continue;
        /* Verify FK matches this exact assembly branch with healthy transmission angle */
        ainekio_v3_fk_result_t check;
        const float tc = ainekio_v3_clamp_joint_deg(leg->crank_joint, td);
        if (!ainekio_v3_leg_fk(leg_id, h_deg, alpha_deg, tc, &check)) continue;
        if (check.sin_transmission < 0.15f) continue;
        const float err = hypotf(
            check.foot_robot_mm[0] - (leg->neutral_sole_in_robot_mm[0] + dx_mm),
            check.foot_robot_mm[2] - (leg->neutral_sole_in_robot_mm[2] + dz_mm));
        if (err > 5.0f) continue;
        const float score = err + 0.005f * fabsf(tc);
        if (score < best_err) {
            best_err = score;
            best_theta_deg = tc;
            found = true;
        }
    }
    if (!found) return false;

    *h_deg_out = h_deg;
    *alpha_deg_out = alpha_deg;
    *theta_deg_out = best_theta_deg;
    return true;
}
