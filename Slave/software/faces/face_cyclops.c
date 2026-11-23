#include "ainekio/face.h"
#include <math.h>
#include <string.h>

/* V3 single-eye Cyclops optic renderer (320x170 centered in 2.8" ILI9341).
 * Matches the V3 Blender MSP2807 Cyclops Eye concept: large luminous outer
 * iris ring with 24 mechanical aperture ticks, radial iris fibers, glossy dark
 * pupil with dual specular glints, mechanical eyelid/brow shutters, twin
 * concentric flanking radar arcs, and panoramic screen-wide saccadic glances.
 * Reuses faces.def as the single authoritative expression catalog. */

enum cyclops_eye { DOT, CHEER, SAD, SLANT, RING, FLAT, HEART, STAR, CHEVRON, CROSS, SPIRAL };
enum cyclops_anim { STILL, BREATHE, BLINK, BOB, SPEAK, PULSE, TILT, LOOK, SWAY, WINK,
                    THINK, INQUIRE, ATTEND };
enum cyclops_accent { NONE, SMILE, TEAR, FROWN, OOH, SLEEP, QUESTION, ELLIPSIS,
                      FLAT_MOUTH, SPEED, BUBBLES, NOTES, BLUSH, SWEAT, ZIGZAG };
enum cyclops_color { CYAN=0x20cfff, BLUE=0x469aff, RED=0xff475d, GOLD=0xffcd48,
                     INDIGO=0x8286ff, PINK=0xff70bf, VIOLET=0xc88bff, TEAL=0x33efcb };

typedef struct {
    const char *name;
    enum cyclops_eye left, right;
    uint32_t color;
    enum cyclops_anim animation;
    enum cyclops_accent accent;
    float gaze_x, gaze_y;
    uint32_t period_ms;
} cyclops_face_t;

#define FACE(n,l,r,c,a,d,x,y,p) {#n,l,r,c,a,d,x,y,p},
static const cyclops_face_t cyclops_faces[] = {
#include "faces.def"
};
#undef FACE

static const float CYC_PI = 3.141592654F;
static const float CYC_TAU = 6.283185307F;

enum pupil_mode {
    PUPIL_NORMAL,
    PUPIL_TARGET,
    PUPIL_RING,
    PUPIL_HEART,
    PUPIL_STAR,
    PUPIL_SPIRAL,
    PUPIL_CROSS
};

enum lid_mode {
    LID_OPEN,
    LID_HAPPY,
    LID_ANGRY,
    LID_SAD,
    LID_SLEEPY,
    LID_BORED,
    LID_CURIOUS
};

typedef struct {
    float r, g, b;
} rgb_t;

static float clamp01(float v) { return v < 0.0F ? 0.0F : (v > 1.0F ? 1.0F : v); }
static float ease(float t) { t = clamp01(t); return t * t * (3.0F - 2.0F * t); }
static float smoothstep(float a, float b, float x) { return ease((x - a) / (b - a)); }

static float blink_curve(float t, float start, float end)
{
    if (t <= start || t >= end) return 1.0F;
    return ease(fabsf(2.0F * (t - start) / (end - start) - 1.0F));
}

/* Natural 16-second ambient cyclops life cycle for neutral/idle/stand/default:
 * holds calm center (so elapsed_ms=0 is hero-centered), glances crisply right
 * across the wide 320x170 viewport with autofocus dial click, blinks back to
 * center, glances far left with a slight curious double-take, scans slightly
 * up-right, and settles back to center with a natural blink. */
typedef struct { float at, pan_x, pan_y, look_x, look_y, dial, focus_dr; } glance_key_t;
static void idle_glance_motion(float u, float *pan_x, float *pan_y,
                               float *look_x, float *look_y,
                               float *dial, float *focus_dr, float *open)
{
    static const glance_key_t keys[] = {
        {0.000F,   0.0F,  0.0F,   0.0F,  0.0F,  0.00F,  0.0F},
        {0.140F,   0.0F,  0.0F,   0.0F,  0.0F,  0.02F,  0.0F},
        /* Saccade right across the wide canvas & inspect. */
        {0.185F,  34.0F, -4.0F,  11.0F, -2.5F,  0.26F,  2.8F},
        {0.255F,  34.0F, -4.0F,  11.0F, -2.5F,  0.26F, -1.6F},
        {0.310F,  32.0F, -2.5F,   9.0F, -1.5F,  0.20F,  1.8F},
        /* Return to center (paired with a natural mid-saccade blink). */
        {0.365F,   0.0F,  0.0F,   0.0F,  0.0F,  0.00F,  0.0F},
        {0.485F,   0.0F,  0.0F,   0.0F,  0.0F, -0.02F,  0.0F},
        /* Saccade far left across the wide canvas + curious up-left double-take. */
        {0.530F, -36.0F,  3.0F, -12.0F,  2.0F, -0.30F,  2.5F},
        {0.605F, -36.0F,  3.0F, -12.0F,  2.0F, -0.30F, -1.5F},
        {0.640F, -31.0F, -6.5F,  -9.0F, -4.5F, -0.18F,  3.0F},
        {0.690F, -31.0F, -6.5F,  -9.0F, -4.5F, -0.18F,  1.0F},
        /* Return center, brief upward scan, then rest at center. */
        {0.745F,   0.0F,  0.0F,   0.0F,  0.0F,  0.00F,  0.0F},
        {0.805F,  14.0F, -7.5F,   5.5F, -4.0F,  0.14F,  2.0F},
        {0.855F,  14.0F, -7.5F,   5.5F, -4.0F,  0.14F,  0.5F},
        {0.900F,   0.0F,  0.0F,   0.0F,  0.0F,  0.00F,  0.0F},
        {1.000F,   0.0F,  0.0F,   0.0F,  0.0F,  0.00F,  0.0F},
    };
    for (size_t i = 1; i < sizeof(keys) / sizeof(keys[0]); ++i) {
        if (u > keys[i].at) continue;
        const glance_key_t *a = &keys[i - 1], *b = &keys[i];
        const float s = ease((u - a->at) / (b->at - a->at));
        *pan_x += a->pan_x + (b->pan_x - a->pan_x) * s;
        *pan_y += a->pan_y + (b->pan_y - a->pan_y) * s;
        *look_x += a->look_x + (b->look_x - a->look_x) * s;
        *look_y += a->look_y + (b->look_y - a->look_y) * s;
        *dial += a->dial + (b->dial - a->dial) * s;
        *focus_dr += a->focus_dr + (b->focus_dr - a->focus_dr) * s;
        break;
    }
    /* Natural blink during return-from-right saccade and a quiet center blink near loop end. */
    const float b1 = blink_curve(u, 0.325F, 0.360F);
    const float b2 = blink_curve(u, 0.930F, 0.962F);
    *open *= fminf(b1, b2);
}

/* Deliberate panoramic thinking gestures across the wide screen. */
typedef struct { float at, pan_x, pan_y, look_x, look_y, tilt, squeeze; } thought_key_t;
static void thought_motion(float t, float *pan_x, float *pan_y,
                           float *look_x, float *look_y,
                           float *tilt, float *squeeze)
{
    static const thought_key_t keys[] = {
        {0.00F,   0.0F,  0.0F,   0.0F,  0.0F,  0.0F, 1.00F},
        {0.12F,  28.0F, -7.5F,  10.0F, -4.5F, -0.6F, 1.00F},
        {0.29F,  28.0F, -7.5F,  10.0F, -4.5F, -0.6F, 1.00F},
        {0.43F, -32.0F, -3.5F, -11.0F, -2.0F,  0.9F, 1.00F},
        {0.55F, -32.0F, -3.5F, -11.0F, -2.0F,  0.9F, 1.00F},
        {0.63F, -24.0F,  1.0F,  -8.0F,  0.5F,  1.0F, 0.72F},
        {0.71F, -24.0F,  1.0F,  -8.0F,  0.5F,  1.0F, 0.72F},
        {0.82F,   0.0F,  0.0F,   0.0F,  0.0F,  0.0F, 1.00F},
        {1.00F,   0.0F,  0.0F,   0.0F,  0.0F,  0.0F, 1.00F},
    };
    for (size_t i = 1; i < sizeof(keys) / sizeof(keys[0]); ++i) {
        if (t > keys[i].at) continue;
        const thought_key_t *a = &keys[i - 1], *b = &keys[i];
        const float u = ease((t - a->at) / (b->at - a->at));
        *pan_x += a->pan_x + (b->pan_x - a->pan_x) * u;
        *pan_y += a->pan_y + (b->pan_y - a->pan_y) * u;
        *look_x += a->look_x + (b->look_x - a->look_x) * u;
        *look_y += a->look_y + (b->look_y - a->look_y) * u;
        *tilt = a->tilt + (b->tilt - a->tilt) * u;
        *squeeze = a->squeeze + (b->squeeze - a->squeeze) * u;
        return;
    }
}

static rgb_t unpack_color(uint32_t hex)
{
    return (rgb_t){
        .r = (float)((hex >> 16) & 255U) / 255.0F,
        .g = (float)((hex >> 8) & 255U) / 255.0F,
        .b = (float)(hex & 255U) / 255.0F,
    };
}

static uint16_t pack_rgb565(float r, float g, float b)
{
    const unsigned ri = (unsigned)(clamp01(r) * 31.0F + 0.5F);
    const unsigned gi = (unsigned)(clamp01(g) * 63.0F + 0.5F);
    const unsigned bi = (unsigned)(clamp01(b) * 31.0F + 0.5F);
    return (uint16_t)((ri << 11) | (gi << 5) | bi);
}

/* Luminous white-cored stroke shading matching Ainekio's neon glow aesthetic. */
static void add_glow(float *ar, float *ag, float *ab, rgb_t col,
                     float edge, float halo_inv, float halo_str, float light)
{
    const float h = clamp01(1.0F - (edge > 0.0F ? edge : 0.0F) * halo_inv);
    const float cov = clamp01(0.85F - edge);
    const float core = clamp01(-edge - 0.15F) * 0.92F;
    const float g = (cov + h * h * halo_str) * light;
    const float r = col.r * g + 0.96F * core * light;
    const float gr = col.g * g + 0.98F * core * light;
    const float b = col.b * g + 0.99F * core * light;
    if (r > *ar) *ar = r;
    if (gr > *ag) *ag = gr;
    if (b > *ab) *ab = b;
}

/* Additive soft light blend for iris rays and subtle ambient glows. */
static void add_soft(float *ar, float *ag, float *ab, rgb_t col, float intensity)
{
    if (intensity <= 0.0F) return;
    *ar += col.r * intensity;
    *ag += col.g * intensity;
    *ab += col.b * intensity;
}

/* Helper to blend a glowing SDF line segment directly into RGB565 buffer
 * for auxiliary flank glyphs (Z, ?, notes, tears, blush, speed streaks). */
static void blend_pixel_565(uint16_t *pixels, int x, int y, rgb_t col,
                            float edge, float halo_w, float halo_str, float light)
{
    if (x <= 1 || x >= AINEKIO_FACE_WIDTH - 2 || y <= 1 || y >= AINEKIO_FACE_HEIGHT - 2) return;
    const float scan = (y & 1) ? 0.90F : 1.0F;
    const float h = clamp01(1.0F - (edge > 0.0F ? edge : 0.0F) / halo_w);
    const float cov = clamp01(0.85F - edge);
    const float core = clamp01(-edge - 0.15F) * 0.92F;
    const float g = (cov + h * h * halo_str) * light * scan;
    const unsigned r = (unsigned)(clamp01(col.r * g + 0.95F * core * light * scan) * 31.0F + 0.5F);
    const unsigned gr = (unsigned)(clamp01(col.g * g + 0.97F * core * light * scan) * 63.0F + 0.5F);
    const unsigned b = (unsigned)(clamp01(col.b * g + 0.99F * core * light * scan) * 31.0F + 0.5F);
    uint16_t *p = &pixels[y * AINEKIO_FACE_WIDTH + x];
    const unsigned pr = (*p >> 11) & 31U, pg = (*p >> 5) & 63U, pb = *p & 31U;
    *p = (uint16_t)(((r > pr ? r : pr) << 11) | ((gr > pg ? gr : pg) << 5) | (b > pb ? b : pb));
}

static void draw_line(uint16_t *pixels, rgb_t col, float ax, float ay,
                      float bx, float by, float radius, float halo_w, float light)
{
    const float pad = radius + halo_w;
    const float dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    const float inv_len2 = len2 > 1e-6F ? 1.0F / len2 : 0.0F;
    const float pad2 = pad * pad;
    int x0 = (int)floorf(fminf(ax, bx) - pad);
    int x1 = (int)ceilf(fmaxf(ax, bx) + pad);
    int y0 = (int)floorf(fminf(ay, by) - pad);
    int y1 = (int)ceilf(fmaxf(ay, by) + pad);
    if (x0 < 2) x0 = 2;
    if (x1 > AINEKIO_FACE_WIDTH - 3) x1 = AINEKIO_FACE_WIDTH - 3;
    if (y0 < 2) y0 = 2;
    if (y1 > AINEKIO_FACE_HEIGHT - 3) y1 = AINEKIO_FACE_HEIGHT - 3;
    for (int y = y0; y <= y1; ++y) {
        for (int x = x0; x <= x1; ++x) {
            const float u = clamp01(((x - ax) * dx + (y - ay) * dy) * inv_len2);
            const float px = (float)x - ax - u * dx;
            const float py = (float)y - ay - u * dy;
            const float d2 = px * px + py * py;
            if (d2 <= pad2) {
                blend_pixel_565(pixels, x, y, col, sqrtf(d2) - radius, halo_w, 0.28F, light);
            }
        }
    }
}

static void draw_dot(uint16_t *pixels, rgb_t col, float x, float y,
                     float radius, float halo_w, float light)
{
    draw_line(pixels, col, x, y, x, y, radius, halo_w, light);
}

static void draw_arc(uint16_t *pixels, rgb_t col, float cx, float cy, float rx, float ry,
                     float a0, float a1, float radius, float halo_w, float light)
{
    const int steps = 16;
    float px = cx + rx * cosf(a0), py = cy + ry * sinf(a0);
    for (int i = 1; i <= steps; ++i) {
        const float a = a0 + (a1 - a0) * (float)i / (float)steps;
        const float nx = cx + rx * cosf(a), ny = cy + ry * sinf(a);
        draw_line(pixels, col, px, py, nx, ny, radius, halo_w, light);
        px = nx; py = ny;
    }
}

/* Signed distance to a heart centered at (0,0), radius ~scale. Negative inside. */
static float sd_heart(float x, float y, float scale)
{
    float px = fabsf(x) / scale;
    float py = (-y + 0.30F * scale) / scale;
    if (px + py > 1.0F) {
        const float dx = px - 0.25F, dy = py - 0.75F;
        return (sqrtf(dx * dx + dy * dy) - 0.35355339F) * scale;
    }
    const float dx1 = px, dy1 = py - 1.0F;
    const float m = 0.5F * fmaxf(px + py, 0.0F);
    const float dx2 = px - m, dy2 = py - m;
    const float d2 = fminf(dx1 * dx1 + dy1 * dy1, dx2 * dx2 + dy2 * dy2);
    const float sgn = (px - py) >= 0.0F ? 1.0F : -1.0F;
    return sqrtf(d2) * sgn * scale;
}

/* Signed distance to a 5-point star centered at (0,0), outer radius r_out. */
static float sd_star5(float x, float y, float r_out, float rot)
{
    const float cr = cosf(rot), sr = sinf(rot);
    const float rx = x * cr - y * sr;
    const float ry = x * sr + y * cr;
    const float d = sqrtf(rx * rx + ry * ry);
    const float ang = atan2f(ry, rx) + CYC_PI * 0.5F;
    float sector = fmodf(ang + CYC_TAU * 2.0F, CYC_TAU / 5.0F);
    if (sector > CYC_PI / 5.0F) sector = (CYC_TAU / 5.0F) - sector;
    const float r_in = r_out * 0.44F;
    const float tx = r_out, ty = 0.0F;
    const float vx = r_in * cosf(CYC_PI / 5.0F), vy = r_in * sinf(CYC_PI / 5.0F);
    const float px = d * cosf(sector), py = d * sinf(sector);
    const float ex = vx - tx, ey = vy - ty;
    const float u = clamp01(((px - tx) * ex + (py - ty) * ey) / (ex * ex + ey * ey));
    const float qx = px - (tx + u * ex), qy = py - (ty + u * ey);
    const float dist = sqrtf(qx * qx + qy * qy);
    const float cross = (px - tx) * ey - (py - ty) * ex;
    return cross >= 0.0F ? -dist : dist;
}

void ainekio_face_cyclops_render(size_t index, uint64_t elapsed_ms, bool talking,
                                 uint16_t pixels[AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT])
{
    if (!pixels) return;
    memset(pixels, 0, AINEKIO_FACE_WIDTH * AINEKIO_FACE_HEIGHT * sizeof(*pixels));
    const size_t count = sizeof(cyclops_faces) / sizeof(cyclops_faces[0]);
    if (index >= count) return;

    const cyclops_face_t *f = &cyclops_faces[index];
    const float t = (float)(elapsed_ms % f->period_ms) / (float)f->period_ms;
    const float wave = sinf(CYC_TAU * t);
    const float cwave = cosf(CYC_TAU * t);
    const bool speaking = talking || f->animation == SPEAK;

    rgb_t col = unpack_color(f->color);
    float light = 1.0F;
    float pulse = f->animation == STILL ? 0.35F : 0.5F + 0.5F * cwave;

    /* Select cyclops pupil style & mechanical eyelid/brow shape from face semantics. */
    enum pupil_mode pmode = PUPIL_NORMAL;
    enum lid_mode lmode = LID_OPEN;
    float pupil_r = 25.0F;
    float eye_scale = 1.0F;
    float dial_angle = 0.04F * wave;
    float arc_spread = 0.0F;
    /* Separate panoramic eyeball gimbal pan (pan_x, pan_y) from internal pupil
     * gaze parallax (look_x, look_y) so the cyclops optic roams the wide 320x170 screen. */
    float pan_x = f->gaze_x * 2.20F;
    float pan_y = f->gaze_y * 0.70F;
    float look_x = f->gaze_x * 0.85F;
    float look_y = f->gaze_y * 0.55F;
    float open = 1.0F;
    float brow_tilt = 0.0F;

    if (f->left == HEART || f->right == HEART) {
        pmode = PUPIL_HEART;
        pupil_r = 28.0F + 2.5F * cwave;
        /* Gentle dreamy figure-8 drift across the wide screen. */
        const float u_love = (float)(elapsed_ms % 6400U) / 6400.0F;
        pan_x += 16.0F * sinf(CYC_TAU * u_love);
        pan_y += 4.5F * sinf(2.0F * CYC_TAU * u_love);
        look_x += 5.0F * sinf(CYC_TAU * u_love);
    } else if (f->left == STAR || f->right == STAR) {
        pmode = PUPIL_STAR;
        pupil_r = 29.0F + 2.0F * wave;
        dial_angle = CYC_TAU * t * 0.25F;
        arc_spread = 3.5F * (0.5F + 0.5F * cwave);
        const float u_exc = (float)(elapsed_ms % 3600U) / 3600.0F;
        pan_x += 20.0F * sinf(CYC_TAU * u_exc);
        look_x += 6.0F * sinf(CYC_TAU * u_exc);
    } else if (f->left == SPIRAL || f->right == SPIRAL) {
        pmode = PUPIL_SPIRAL;
        pupil_r = 26.0F;
        dial_angle = CYC_TAU * t;
        const float u_frk = (float)(elapsed_ms % 3200U) / 3200.0F;
        pan_x += 26.0F * sinf(CYC_TAU * u_frk);
        pan_y += 6.0F * sinf(3.0F * CYC_TAU * u_frk);
    } else if (f->left == CROSS || f->right == CROSS) {
        pmode = PUPIL_CROSS;
        pupil_r = 24.0F;
        light = f->animation == STILL ? 0.72F : 0.90F;
    } else if (f->left == SLANT || f->right == SLANT) {
        pmode = PUPIL_TARGET;
        lmode = LID_ANGRY;
        pupil_r = 14.5F + 1.5F * cwave;
        look_y += 7.0F;
        dial_angle = 0.08F * sinf(CYC_TAU * t * 2.0F);
        arc_spread = -3.0F + 2.5F * cwave;
        /* Predatory targeting micro-lock scan left/right. */
        const float u_ang = (float)(elapsed_ms % 4800U) / 4800.0F;
        const float snap = sinf(CYC_TAU * u_ang);
        pan_x += 9.0F * (snap * snap * snap);
        look_x += 5.0F * snap;
    } else if (f->left == RING && f->right == RING) {
        pmode = PUPIL_RING;
        eye_scale = 1.05F + 0.025F * cwave;
        pupil_r = 14.0F + 5.0F * ease(0.5F + 0.5F * cwave);
        arc_spread = 5.5F + 2.5F * cwave;
        dial_angle = -0.18F * wave;
        const float u_surp = (float)(elapsed_ms % 4000U) / 4000.0F;
        pan_x += 12.0F * sinf(CYC_TAU * u_surp);
        look_x += 6.0F * sinf(2.0F * CYC_TAU * u_surp);
    } else if (f->left == RING || f->right == RING) {
        pmode = PUPIL_RING;
        if (f->animation == ATTEND) {
            pupil_r = 27.0F + 2.0F * wave;
            dial_angle = 0.30F * wave;
            arc_spread = 2.0F + 3.0F * (0.5F + 0.5F * cwave);
        } else {
            lmode = LID_CURIOUS;
            brow_tilt = 1.0F;
            pupil_r = 23.0F + 6.0F * sinf(CYC_TAU * t);
            dial_angle = 0.35F * sinf(CYC_TAU * t) + 0.12F * sinf(CYC_TAU * t * 2.0F);
        }
    } else if (f->left == CHEER || f->right == CHEER) {
        lmode = LID_HAPPY;
        pupil_r = 28.0F;
        look_y -= 6.0F;
        arc_spread = 2.0F + 2.0F * (0.5F + 0.5F * wave);
        const float u_hap = (float)(elapsed_ms % 5400U) / 5400.0F;
        pan_x += 15.0F * sinf(CYC_TAU * u_hap);
        look_x += 5.0F * sinf(CYC_TAU * u_hap);
    } else if (f->left == SAD || f->right == SAD) {
        lmode = LID_SAD;
        pupil_r = 22.0F;
        light = 0.85F;
        arc_spread = -2.5F;
        pan_y += 5.0F;
        pan_x += 10.0F * wave;
    } else if (f->left == FLAT && f->right == FLAT) {
        if (f->accent == SLEEP || f->color == INDIGO) {
            lmode = LID_SLEEPY;
            pupil_r = 19.0F;
            light = 0.68F;
            arc_spread = -4.0F;
            pan_y += 5.0F;
            pan_x += 6.0F * wave;
        } else {
            lmode = LID_BORED;
            pupil_r = 21.0F;
            light = 0.84F;
        }
    } else if (f->left == FLAT || f->right == FLAT) {
        lmode = LID_CURIOUS;
        brow_tilt = (f->left == FLAT) ? -1.0F : 1.0F;
        pupil_r = 23.0F;
    } else if (f->left == CHEVRON || f->right == CHEVRON) {
        pmode = PUPIL_TARGET;
        pupil_r = 18.0F;
        arc_spread = 3.0F;
    }

    /* Animation kinematics taking full advantage of the wide 320x170 canvas. */
    if (f->animation == BOB) {
        pan_y += 4.5F * wave;
        look_y += 2.0F * wave;
        if (f->left == DOT && f->right == DOT) {
            /* Walking scan: gently looks left/right along travel path. */
            const float u_walk = (float)(elapsed_ms % 6000U) / 6000.0F;
            pan_x += 18.0F * sinf(CYC_TAU * u_walk);
            look_x += 7.0F * sinf(CYC_TAU * u_walk);
        }
    } else if (f->animation == SWAY) {
        pan_x += 26.0F * wave;
        look_x += 9.0F * wave;
    } else if (f->animation == LOOK) {
        /* Wide panoramic sweep left-to-right (bored / sit / crawl / point / turns). */
        const float sweep = (f->gaze_x != 0.0F) ? 10.0F : 32.0F;
        pan_x += sweep * wave;
        look_x += 10.0F * wave;
        dial_angle += 0.22F * wave;
    } else if (f->animation == TILT) {
        pan_x += 18.0F * wave;
        pan_y += 3.5F * cwave;
        look_x += 6.0F * wave;
        brow_tilt = wave;
    } else if (f->animation == BREATHE || f->animation == PULSE) {
        light *= 0.90F + 0.10F * cwave;
        pupil_r += 1.2F * cwave;
        /* Ambient living cyclops saccades on neutral/default/idle/stand/crouch. */
        if (f->animation == BREATHE && lmode == LID_OPEN && pmode == PUPIL_NORMAL && f->gaze_x == 0.0F && f->gaze_y == 0.0F) {
            const float u_idle = (float)(elapsed_ms % 16000U) / 16000.0F;
            float focus_dr = 0.0F;
            idle_glance_motion(u_idle, &pan_x, &pan_y, &look_x, &look_y, &dial_angle, &focus_dr, &open);
            pupil_r += focus_dr;
        } else if (f->animation == BREATHE && t > 0.89F && t < 0.96F) {
            open = fabsf((t - 0.925F) / 0.035F);
        }
    }

    if (f->animation == BLINK) {
        open = fabsf(2.0F * t - 1.0F);
    } else if (f->animation == WINK && t > 0.28F && t < 0.62F) {
        open = 0.14F + 0.86F * fabsf((t - 0.45F) / 0.17F);
    }

    if (f->animation == THINK) {
        float squeeze = 1.0F;
        thought_motion(t, &pan_x, &pan_y, &look_x, &look_y, &brow_tilt, &squeeze);
        open = blink_curve(t, 0.84F, 0.89F) * squeeze;
        dial_angle = CYC_TAU * t * 0.5F;
        light *= 0.93F + 0.07F * cosf(2.0F * CYC_TAU * t);
    } else if (f->animation == INQUIRE) {
        const float lean = t < 0.22F ? ease(t / 0.22F) :
                           t < 0.50F ? 1.0F :
                           t < 0.76F ? 1.0F - ease((t - 0.50F) / 0.26F) : 0.0F;
        const float side = (f->left == FLAT) ? -1.0F : 1.0F;
        pan_x += 26.0F * side * lean;
        pan_y -= 5.0F * lean;
        look_x += 9.0F * side * lean;
        look_y -= 3.0F * lean;
        brow_tilt = (brow_tilt >= 0.0F ? 1.0F : -1.0F) * (0.4F + 0.85F * lean);
        pupil_r += 3.5F * lean;
        open = blink_curve(t, 0.84F, 0.90F);
    } else if (f->animation == ATTEND) {
        pan_y -= 3.0F * (1.0F - cwave);
        light *= 0.90F + 0.10F * cwave;
    }

    /* Speaking overlay energizes halo & flanking radar arcs. */
    const float talk_phase = (float)(elapsed_ms % 1500U) * 0.022F;
    const float talk_pulse = speaking ? (0.5F + 0.5F * fabsf(sinf(talk_phase))) : 0.0F;
    if (speaking) {
        pulse = 0.55F + 0.45F * talk_pulse;
        arc_spread += 3.5F * talk_pulse;
        pupil_r += 2.2F * talk_pulse;
    }

    /* Clamp panoramic eyeball pan so outer iris + flanking arcs stay well inside 320x170. */
    if (pan_x > 38.0F) pan_x = 38.0F;
    if (pan_x < -38.0F) pan_x = -38.0F;
    if (pan_y > 10.0F) pan_y = 10.0F;
    if (pan_y < -10.0F) pan_y = -10.0F;

    /* Clamp internal pupil parallax so pupil stays cleanly inside outer iris ring. */
    const float r_outer = 61.0F * eye_scale;
    const float max_look = fmaxf(4.0F, (r_outer - pupil_r - 9.0F) * 0.82F);
    const float look_len = sqrtf(look_x * look_x + look_y * look_y);
    if (look_len > max_look) {
        const float s = max_look / look_len;
        look_x *= s;
        look_y *= s;
    }

    const float cx = 160.0F;
    const float cy = 85.0F;
    /* Eyeball dome center pans boldly across the wide screen; pupil leads with 3D parallax;
     * flanking gimbal arcs trail slightly behind for optical HUD depth! */
    const float ox = cx + pan_x;
    const float oy = cy + pan_y;
    const float px = ox + look_x;
    const float py = oy + look_y;
    const float ax = cx + pan_x * 0.72F;
    const float ay = cy + pan_y * 0.72F;

    const float halo_w = 10.5F + 3.5F * pulse;
    const float halo_inv = 1.0F / halo_w;
    const float halo_str = 0.26F + 0.12F * pulse;

    const float r_arc_in_base = 84.5F + arc_spread;
    const float r_arc_out_base = 101.0F + arc_spread * 1.25F;
    const float tick_r0 = r_outer - 12.0F;
    const float tick_r1 = r_outer - 5.2F;

    /* Specular lens glints inside standard/ring/target pupils. */
    const float g1x = px - 0.40F * pupil_r;
    const float g1y = py - 0.35F * pupil_r;
    const float g1r = fmaxf(2.4F, 0.28F * pupil_r);
    const float g2x = px + 0.34F * pupil_r;
    const float g2y = py + 0.34F * pupil_r;
    const float g2r = fmaxf(1.4F, 0.12F * pupil_r);

    /* Acoustic / focus pulse ring radius for RING mode or speaking mode. */
    const float focus_r = pupil_r + 6.0F + (r_outer - pupil_r - 14.0F) *
                          (f->animation == ATTEND ? t : (0.5F + 0.5F * sinf(CYC_TAU * t)));
    const float talk_ring_r = pupil_r + 5.0F + 6.0F * talk_pulse;
    /* Acoustic radar echo sweeping outward across flanking arcs when listening. */
    const float sonar_r = 64.0F + 56.0F * t;

    /* Single-pass analytic rendering over interior pixels (strictly preserves 1px black border). */
    const int x_min = 2;
    const int x_max = AINEKIO_FACE_WIDTH - 3;
    const int y_min = 3;
    const int y_max = AINEKIO_FACE_HEIGHT - 4;

    for (int y = y_min; y <= y_max; ++y) {
        const float fy = (float)y;
        const float dy_o = fy - oy;
        const float dy_p = fy - py;
        const float dy_a = fy - ay;
        const float dy_o2 = dy_o * dy_o;
        const float dy_p2 = dy_p * dy_p;
        const float dy_a2 = dy_a * dy_a;
        const float scan = (y & 1) ? 0.91F : 1.0F;
        /* Soft edge envelope so ambient halos fade cleanly before screen edges. */
        const float edge_y = fminf((fy - 2.0F) / 10.0F, ((float)(AINEKIO_FACE_HEIGHT - 3) - fy) / 10.0F);
        const float y_env = clamp01(edge_y);

        uint16_t *row = &pixels[y * AINEKIO_FACE_WIDTH];

        for (int x = x_min; x <= x_max; ++x) {
            const float fx = (float)x;
            const float edge_x = fminf((fx - 2.0F) / 10.0F, ((float)(AINEKIO_FACE_WIDTH - 3) - fx) / 10.0F);
            const float xy_env = y_env * clamp01(edge_x);

            float rr = 0.0F, gg = 0.0F, bb = 0.0F;

            /* 0. Subtle Fixed Panoramic Viewport Reference Ticks at far left/right edges
             * (grounds the eye's panoramic sweep inside the cast Display Bezel!). */
            if (x <= 24 || x >= AINEKIO_FACE_WIDTH - 25) {
                const float ex = (x <= 24) ? fx : ((float)(AINEKIO_FACE_WIDTH - 1) - fx);
                const float dy_c = fabsf(fy - cy);
                if (dy_c < 2.2F && ex >= 8.0F && ex <= 20.0F) {
                    const float tick_end = fmaxf(10.0F - ex, ex - 18.0F);
                    const float ref_d = fmaxf(dy_c - 0.50F, tick_end);
                    if (ref_d < 2.5F) {
                        add_glow(&rr, &gg, &bb, col, ref_d, 0.45F, 0.18F, light * 0.30F * xy_env);
                    }
                } else if (fabsf(dy_c - 28.0F) < 2.0F && ex >= 9.0F && ex <= 15.0F) {
                    const float tick_end = fmaxf(10.5F - ex, ex - 14.0F);
                    const float ref_d = fmaxf(fabsf(dy_c - 28.0F) - 0.45F, tick_end);
                    if (ref_d < 2.2F) {
                        add_glow(&rr, &gg, &bb, col, ref_d, 0.50F, 0.15F, light * 0.22F * xy_env);
                    }
                }
            }

            /* 1. Central Cyclops Eyeball (within outer glow radius). */
            const float dx_o = fx - ox;
            const float do2 = dx_o * dx_o + dy_o2;
            const float outer_lim = r_outer + halo_w + 3.0F;

            if (do2 <= outer_lim * outer_lim) {
                const float d_o = sqrtf(do2);
                const float dx_p = fx - px;
                const float d_p = sqrtf(dx_p * dx_p + dy_p2);

                /* Compute mechanical eyelid / brow contour at this column. */
                const float nx = clamp01((dx_o / r_outer) * 0.5F + 0.5F) * 2.0F - 1.0F;
                float lid_top = oy - r_outer - 12.0F;
                float lid_bot = oy + r_outer + 12.0F;

                if (lmode == LID_HAPPY) {
                    lid_bot = oy + r_outer * (0.14F + 0.62F * nx * nx);
                } else if (lmode == LID_ANGRY) {
                    lid_top = oy - 6.0F - 30.0F * fabsf(nx);
                } else if (lmode == LID_SAD) {
                    lid_top = oy - 44.0F + 28.0F * fabsf(nx);
                } else if (lmode == LID_SLEEPY) {
                    lid_top = oy - 4.0F + 5.0F * nx * nx;
                    lid_bot = oy + r_outer * 0.72F;
                } else if (lmode == LID_BORED) {
                    lid_top = oy - 13.0F;
                } else if (lmode == LID_CURIOUS) {
                    lid_top = oy - 40.0F + 16.0F * nx * brow_tilt;
                }

                if (open < 0.999F) {
                    const float half_h = (r_outer + 6.0F) * open;
                    const float b_top = oy - half_h;
                    const float b_bot = oy + half_h;
                    if (b_top > lid_top) lid_top = b_top;
                    if (b_bot < lid_bot) lid_bot = b_bot;
                }

                const float vis_top = smoothstep(lid_top - 1.6F, lid_top + 1.8F, fy);
                const float vis_bot = 1.0F - smoothstep(lid_bot - 1.8F, lid_bot + 1.6F, fy);
                const float eye_vis = vis_top * vis_bot;

                if (eye_vis > 0.004F) {
                    const float bg_glow = expf(-d_o * 0.028F) * 0.14F * light * xy_env;
                    add_soft(&rr, &gg, &bb, col, bg_glow);

                    if (d_o < r_outer + 1.5F) {
                        const float ang_o = atan2f(dy_o, dx_o);
                        const float ang_p = atan2f(dy_p, dx_p);
                        const float inside_outer = 1.0F - smoothstep(r_outer - 2.4F, r_outer + 0.5F, d_o);

                        if (pmode == PUPIL_SPIRAL) {
                            /* Seamless rotating 2-arm Archimedean spiral (integer angular harmonic). */
                            const float phase = fmodf(d_p * 0.44F - ang_p * 2.0F - CYC_TAU * t * 2.0F + 64.0F * CYC_PI, CYC_TAU);
                            const float sp_d = fabsf(phase - CYC_PI) * 2.1F;
                            add_glow(&rr, &gg, &bb, col, sp_d - 1.5F, 0.16F, 0.25F, light * inside_outer);
                        } else {
                            if (d_p > pupil_r - 2.0F) {
                                const float spokes = 0.52F + 0.48F * cosf(24.0F * (ang_p - dial_angle * 0.5F));
                                const float inner_falloff = expf(-fmaxf(0.0F, d_p - pupil_r) * 0.055F);
                                const float iris_body = (0.17F + 0.52F * inner_falloff) * spokes;
                                const float iris_fade = smoothstep(pupil_r - 1.5F, pupil_r + 1.5F, d_p);
                                add_soft(&rr, &gg, &bb, col, iris_body * iris_fade * inside_outer * light);
                            }

                            if (d_o >= tick_r0 - 2.5F && d_o <= tick_r1 + 2.5F) {
                                const float step = CYC_TAU / 24.0F;
                                float a_rel = fmodf(ang_o - dial_angle + CYC_TAU * 4.0F + step * 0.5F, step) - step * 0.5F;
                                const float arc_dist = fabsf(a_rel) * d_o;
                                const float rad_dist = fmaxf(tick_r0 - d_o, d_o - tick_r1);
                                const float tick_d = fmaxf(arc_dist - 1.05F, rad_dist);
                                if (tick_d < 4.5F) {
                                    add_glow(&rr, &gg, &bb, col, tick_d, 0.28F, 0.22F, light * 0.92F);
                                }
                            }
                        }

                        if (pmode == PUPIL_RING && d_p > pupil_r + 2.0F) {
                            const float f_edge = fabsf(d_p - focus_r) - 1.0F;
                            if (f_edge < 7.0F) {
                                const float f_str = f->animation == ATTEND ? (1.0F - t) * 0.85F : 0.65F;
                                add_glow(&rr, &gg, &bb, col, f_edge, 0.18F, 0.24F, light * f_str * inside_outer);
                            }
                        }

                        if (speaking && d_p > pupil_r + 1.0F) {
                            const float t_edge = fabsf(d_p - talk_ring_r) - 0.9F;
                            if (t_edge < 6.5F) {
                                add_glow(&rr, &gg, &bb, col, t_edge, 0.20F, 0.26F, light * (0.45F + 0.55F * talk_pulse) * inside_outer);
                            }
                        }

                        if (pmode == PUPIL_TARGET && d_p > pupil_r + 3.0F && d_p < r_outer - 14.0F) {
                            const float ch = fminf(fabsf(dx_p), fabsf(dy_p)) - 1.0F;
                            if (ch < 4.0F) {
                                add_glow(&rr, &gg, &bb, col, ch, 0.30F, 0.20F, light * 0.78F * inside_outer);
                            }
                        }

                        if (pmode != PUPIL_SPIRAL && d_p < pupil_r + 1.0F) {
                            const float cavity = 1.0F - smoothstep(pupil_r - 2.0F, pupil_r + 0.4F, d_p);
                            const float keep = 1.0F - cavity * 0.97F;
                            rr *= keep;
                            gg *= keep;
                            bb *= keep;
                        }

                        if (pmode == PUPIL_HEART) {
                            const float hd = sd_heart(dx_p, dy_p, pupil_r * 0.95F);
                            if (fabsf(hd) < 10.0F || hd < 0.0F) {
                                const float rim = fabsf(hd) - 2.0F;
                                add_glow(&rr, &gg, &bb, col, rim, 0.14F, 0.34F, light);
                                if (hd < 0.0F) add_soft(&rr, &gg, &bb, col, 0.32F * light);
                            }
                        } else if (pmode == PUPIL_STAR) {
                            const float sd = sd_star5(dx_p, dy_p, pupil_r * 1.08F, 0.45F * wave);
                            if (sd < 10.0F) {
                                const float rim = fabsf(sd) - 1.9F;
                                add_glow(&rr, &gg, &bb, col, rim, 0.15F, 0.32F, light);
                                if (sd < 0.0F) add_soft(&rr, &gg, &bb, col, 0.38F * light);
                            }
                        } else if (pmode == PUPIL_CROSS) {
                            const float s = pupil_r * 0.85F;
                            if (fabsf(dx_p) < s + 6.0F && fabsf(dy_p) < s + 6.0F) {
                                const float d1 = fabsf(dx_p - dy_p) * 0.70710678F;
                                const float d2 = fabsf(dx_p + dy_p) * 0.70710678F;
                                const float xd = fmaxf(fminf(d1, d2) - 2.4F, fmaxf(fabsf(dx_p), fabsf(dy_p)) - s);
                                if (xd < 8.0F) {
                                    add_glow(&rr, &gg, &bb, col, xd, 0.16F, 0.28F, light);
                                }
                            }
                        } else if (pmode != PUPIL_SPIRAL) {
                            const float p_ring = fabsf(d_p - pupil_r) - 1.85F;
                            if (p_ring < halo_w) {
                                add_glow(&rr, &gg, &bb, col, p_ring, halo_inv * 1.05F, halo_str * 1.25F, light);
                            }
                            const float d_g1 = sqrtf((fx - g1x) * (fx - g1x) + (fy - g1y) * (fy - g1y)) - g1r;
                            if (d_g1 < 3.5F) {
                                const float gc = clamp01(0.85F - d_g1);
                                const float gh = clamp01(1.0F - fmaxf(0.0F, d_g1) * 0.33F);
                                const float val = (gc + gh * gh * 0.25F) * light;
                                const float gr_c = 0.88F * val + col.r * 0.12F * val;
                                const float gg_c = 0.96F * val + col.g * 0.04F * val;
                                const float gb_c = 0.98F * val + col.b * 0.02F * val;
                                if (gr_c > rr) rr = gr_c;
                                if (gg_c > gg) gg = gg_c;
                                if (gb_c > bb) bb = gb_c;
                            }
                            const float d_g2 = sqrtf((fx - g2x) * (fx - g2x) + (fy - g2y) * (fy - g2y)) - g2r;
                            if (d_g2 < 2.8F) {
                                const float gc = clamp01(0.85F - d_g2);
                                const float gh = clamp01(1.0F - fmaxf(0.0F, d_g2) * 0.40F);
                                const float val = (gc + gh * gh * 0.22F) * light * 0.95F;
                                const float gr_c = 0.86F * val + col.r * 0.14F * val;
                                const float gg_c = 0.95F * val + col.g * 0.05F * val;
                                const float gb_c = 0.98F * val + col.b * 0.02F * val;
                                if (gr_c > rr) rr = gr_c;
                                if (gg_c > gg) gg = gg_c;
                                if (gb_c > bb) bb = gb_c;
                            }
                        }
                    }

                    const float o_ring = fabsf(d_o - r_outer) - 1.95F;
                    if (o_ring < halo_w) {
                        add_glow(&rr, &gg, &bb, col, o_ring, halo_inv, halo_str, light * xy_env);
                    }

                    rr *= eye_vis;
                    gg *= eye_vis;
                    bb *= eye_vis;
                }

                if (d_o <= r_outer + 2.5F) {
                    const float rim_mask = 1.0F - smoothstep(r_outer - 1.0F, r_outer + 2.5F, d_o);
                    if (lid_top > oy - r_outer + 2.0F && fabsf(fy - lid_top) < halo_w * 0.8F) {
                        const float lid_d = fabsf(fy - lid_top) - 1.55F;
                        add_glow(&rr, &gg, &bb, col, lid_d, halo_inv * 1.35F, halo_str * 0.95F, light * rim_mask);
                    }
                    if (lid_bot < oy + r_outer - 2.0F && fabsf(fy - lid_bot) < halo_w * 0.8F) {
                        const float lid_d = fabsf(fy - lid_bot) - 1.55F;
                        add_glow(&rr, &gg, &bb, col, lid_d, halo_inv * 1.35F, halo_str * 0.95F, light * rim_mask);
                    }
                }
            }

            /* 2. Twin Concentric Flanking Radar/Parenthesis Arcs with Gimbal Parallax.
             * Leading side arcs tuck slightly tighter & glow brighter; trailing side lags
             * gently behind, accentuating the cyclops eye's panoramic sweep! */
            const float dx_a = fx - ax;
            const float da2 = dx_a * dx_a + dy_a2;
            if (da2 >= (r_arc_in_base - halo_w - 10.0F) * (r_arc_in_base - halo_w - 10.0F) &&
                da2 <= (r_arc_out_base + 42.0F) * (r_arc_out_base + 42.0F)) {
                const float d_a = sqrtf(da2);
                const float adx = fabsf(dx_a);
                if (adx > 30.0F) {
                    const float ang_h = atan2f(fabsf(dy_a), adx);
                    const float side_sign = dx_a >= 0.0F ? 1.0F : -1.0F;
                    /* Positive when this arc is on the side the eye is looking toward. */
                    const float lead = clamp01((pan_x * side_sign) / 38.0F);
                    const float trail = clamp01((-pan_x * side_sign) / 38.0F);
                    const float r_arc_in = r_arc_in_base - 4.0F * lead + 3.5F * trail;
                    const float r_arc_out = r_arc_out_base - 6.0F * lead + 3.0F * trail;
                    const float side_gain = 1.0F + 0.14F * lead - 0.14F * trail;

                    float arc_mod = side_gain;
                    float arc_r_bump = 0.0F;
                    if (speaking) {
                        const float band = floorf((dy_a / 56.0F + 1.0F) * 2.5F);
                        const float eq = 0.45F + 0.55F * fabsf(sinf(talk_phase + band * 1.15F));
                        arc_mod *= 0.65F + 0.55F * eq;
                        arc_r_bump = 3.2F * eq;
                    }

                    const float a_in_lim = 0.65F + 0.05F * lead;
                    const float in_r_eff = r_arc_in + arc_r_bump * 0.55F;
                    const float d_in_r = fabsf(d_a - in_r_eff) - 2.45F;
                    const float d_in_ang = (ang_h > a_in_lim) ? (ang_h - a_in_lim) * d_a : 0.0F;
                    const float d_in = (d_in_ang > 0.0F && d_in_r > 0.0F)
                        ? sqrtf(d_in_r * d_in_r + d_in_ang * d_in_ang)
                        : fmaxf(d_in_r, d_in_ang);
                    if (d_in < halo_w) {
                        add_glow(&rr, &gg, &bb, col, d_in, halo_inv, halo_str, light * arc_mod * xy_env);
                    }

                    const float a_out_lim = 0.46F + 0.04F * lead;
                    const float out_r_eff = r_arc_out + arc_r_bump;
                    const float d_out_r = fabsf(d_a - out_r_eff) - 1.45F;
                    const float d_out_ang = (ang_h > a_out_lim) ? (ang_h - a_out_lim) * d_a : 0.0F;
                    const float d_out = (d_out_ang > 0.0F && d_out_r > 0.0F)
                        ? sqrtf(d_out_r * d_out_r + d_out_ang * d_out_ang)
                        : fmaxf(d_out_r, d_out_ang);
                    if (d_out < halo_w * 0.9F) {
                        add_glow(&rr, &gg, &bb, col, d_out, halo_inv * 1.15F, halo_str * 0.85F, light * 0.88F * arc_mod * xy_env);
                    }

                    /* Expanding acoustic sonar ripple across flanking arcs when listening. */
                    if (f->animation == ATTEND && ang_h < 0.58F) {
                        const float sr_d = fabsf(d_a - sonar_r) - 1.1F;
                        if (sr_d < 6.0F) {
                            add_glow(&rr, &gg, &bb, col, sr_d, 0.22F, 0.22F, light * (1.0F - t) * 0.72F * xy_env);
                        }
                    }

                    /* Thin horizontal outer reticle line extending from outer arcs. */
                    if (fabsf(dy_a) < 3.5F && adx >= r_arc_out + 7.0F && adx <= r_arc_out + 28.0F) {
                        const float tick_end = fmaxf((r_arc_out + 9.0F) - adx, adx - (r_arc_out + 25.0F));
                        const float ret_d = fmaxf(fabsf(dy_a) - 0.55F, tick_end);
                        if (ret_d < 3.0F) {
                            add_glow(&rr, &gg, &bb, col, ret_d, 0.40F, 0.22F, light * 0.42F * xy_env);
                        }
                    }
                }
            }

            if (rr > 0.002F || gg > 0.002F || bb > 0.002F) {
                row[x] = pack_rgb565(rr * scan, gg * scan, bb * scan);
            }
        }
    }

    /* 3. Clean Auxiliary Flank Accents (anchored in open space opposite eye pan when wide). */
    const rgb_t acc_col = (f->color == CYAN) ? unpack_color(TEAL) : col;
    const float open_side_x = (pan_x > 10.0F) ? 46.0F : 262.0F;
    switch (f->accent) {
    case NONE:
    case SMILE:
    case FROWN:
    case FLAT_MOUTH:
    case OOH:
    case ZIGZAG:
        break;
    case TEAR: {
        const rgb_t tear_c = unpack_color(CYAN);
        const float tx = ox + 42.0F;
        const float ty = oy + 36.0F + 24.0F * t;
        draw_dot(pixels, tear_c, tx, ty, 3.2F, 6.0F, 0.95F);
        draw_line(pixels, tear_c, tx, ty - 5.5F, tx, ty, 1.8F, 5.0F, 0.90F);
        break;
    }
    case SWEAT: {
        const rgb_t sw_c = unpack_color(BLUE);
        const float sx = ox + 56.0F;
        const float sy = oy - 36.0F + 12.0F * t;
        draw_dot(pixels, sw_c, sx, sy, 2.8F, 5.5F, 0.92F);
        break;
    }
    case SLEEP: {
        const float zx = 252.0F;
        const float zy = 34.0F - 4.0F * wave;
        draw_line(pixels, acc_col, zx, zy, zx + 12.0F, zy, 1.3F, 5.0F, 0.85F);
        draw_line(pixels, acc_col, zx + 12.0F, zy, zx, zy + 11.0F, 1.3F, 5.0F, 0.85F);
        draw_line(pixels, acc_col, zx, zy + 11.0F, zx + 12.0F, zy + 11.0F, 1.3F, 5.0F, 0.85F);
        const float z2y = 22.0F - 3.0F * sinf(CYC_TAU * t + CYC_PI * 0.5F);
        const float z2l = 0.45F + 0.30F * (1.0F - cwave);
        draw_line(pixels, acc_col, zx + 19.0F, z2y, zx + 27.0F, z2y, 1.0F, 4.0F, z2l);
        draw_line(pixels, acc_col, zx + 27.0F, z2y, zx + 19.0F, z2y + 7.0F, 1.0F, 4.0F, z2l);
        draw_line(pixels, acc_col, zx + 19.0F, z2y + 7.0F, zx + 27.0F, z2y + 7.0F, 1.0F, 4.0F, z2l);
        break;
    }
    case QUESTION: {
        const float qx = open_side_x;
        const float qy = f->animation == INQUIRE ? -2.5F * wave : 0.0F;
        draw_arc(pixels, acc_col, qx, 34.0F + qy, 7.5F, 6.5F, CYC_PI, CYC_TAU + 0.7F, 1.4F, 5.5F, 0.95F);
        draw_line(pixels, acc_col, qx + 6.0F, 38.0F + qy, qx, 45.0F + qy, 1.4F, 5.5F, 0.95F);
        draw_dot(pixels, acc_col, qx, 54.0F + qy, 1.8F, 5.0F, 0.95F);
        break;
    }
    case ELLIPSIS: {
        const float ex0 = (pan_x > 10.0F) ? 32.0F : 248.0F;
        const float cycles = f->animation == THINK ? 4.0F : (f->animation == ATTEND ? 2.0F : 1.0F);
        for (int i = 0; i < 3; ++i) {
            const float ep = 0.5F + 0.5F * cosf(CYC_TAU * (t * cycles - (float)i / 3.0F));
            draw_dot(pixels, acc_col, ex0 + (float)i * 13.0F, 136.0F - 2.5F * ep,
                     1.8F + 1.1F * ep, 5.0F, 0.35F + 0.65F * ep);
        }
        break;
    }
    case SPEED: {
        for (int i = 0; i < 3; ++i) {
            const float sy = 50.0F + (float)i * 35.0F;
            const float off = 6.0F * sinf(CYC_TAU * t + (float)i);
            draw_line(pixels, acc_col, 20.0F, sy, 46.0F + off, sy, 1.2F, 5.0F, 0.85F);
            draw_line(pixels, acc_col, 274.0F - off, sy, 300.0F, sy, 1.2F, 5.0F, 0.85F);
        }
        break;
    }
    case BUBBLES: {
        for (int i = 0; i < 3; ++i) {
            const float by = 132.0F - fmodf(t + (float)i * 0.33F, 1.0F) * 86.0F;
            draw_arc(pixels, acc_col, open_side_x - 10.0F + (float)i * 11.0F, by,
                     2.5F + (float)i, 2.5F + (float)i, 0.0F, CYC_TAU, 0.9F, 4.0F, 0.82F);
        }
        break;
    }
    case NOTES: {
        const float nx_b = open_side_x - 8.0F;
        const float ny = 3.0F * wave, nx_o = 2.5F * cwave;
        draw_dot(pixels, acc_col, nx_b + nx_o, 44.0F + ny, 3.0F, 5.0F, 0.92F);
        draw_line(pixels, acc_col, nx_b + 3.0F + nx_o, 44.0F + ny, nx_b + 3.0F + nx_o, 26.0F + ny, 1.2F, 4.5F, 0.92F);
        draw_line(pixels, acc_col, nx_b + 3.0F + nx_o, 26.0F + ny, nx_b + 18.0F + nx_o, 22.0F + ny, 1.2F, 4.5F, 0.92F);
        draw_line(pixels, acc_col, nx_b + 18.0F + nx_o, 22.0F + ny, nx_b + 18.0F + nx_o, 40.0F + ny, 1.2F, 4.5F, 0.92F);
        draw_dot(pixels, acc_col, nx_b + 15.0F + nx_o, 40.0F + ny, 3.0F, 5.0F, 0.92F);
        break;
    }
    case BLUSH: {
        const rgb_t blush_c = unpack_color(PINK);
        for (int i = 0; i < 3; ++i) {
            draw_line(pixels, blush_c, ox - 92.0F + (float)i * 8.0F, 128.0F,
                      ox - 96.0F + (float)i * 8.0F, 137.0F, 1.2F, 5.0F, 0.85F);
            draw_line(pixels, blush_c, ox + 76.0F + (float)i * 8.0F, 128.0F,
                      ox + 72.0F + (float)i * 8.0F, 137.0F, 1.2F, 5.0F, 0.85F);
        }
        break;
    }
    }
}
