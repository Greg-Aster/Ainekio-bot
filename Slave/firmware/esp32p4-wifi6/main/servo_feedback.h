#pragma once
#include "servo_feedback_model.h"
#include "joint_calibration.h"
#include "esp_err.h"
struct httpd_req;

typedef struct {
    uint16_t raw[16], spread[16], valid_mask;
    float filtered_raw[16], velocity_raw_s[16];
    int millivolts[16];
    int64_t sampled_us[16];
    uint32_t scan, scan_us, revision;
    esp_err_t error, voltage_error;
    bool initialized, saved;
    ainekio_feedback_config_t config;
} ainekio_p4_feedback_snapshot_t;

typedef struct {
    uint16_t calibrated, unavailable, clipped, below_calibration, above_calibration;
} ainekio_p4_feedback_health_t;
/* Confidence in measured positions, not a commanded travel limit or a
 * measurement of the servo power rail. */
void ainekio_p4_feedback_health(const ainekio_p4_feedback_snapshot_t *sample,
    ainekio_p4_feedback_health_t *health);
/* Transport view of one completed acquisition scan, in stable model-joint
 * order. Usability is the same as feedback_frame; missing values are not zero
 * positions. This observes outputs, and never drives or verifies a motion. */
typedef struct {
    ainekio_v2_frame_t measured, commanded;
    int64_t sampled_us[12];
    uint64_t device_us;
    uint32_t scan, scan_us, revision;
    uint16_t usable_mask, commanded_mask, stalled_joints;
    bool enabled;
    ainekio_p4_feedback_health_t health;
} ainekio_p4_feedback_observation_t;
void ainekio_p4_feedback_observe(const ainekio_p4_feedback_snapshot_t *sample,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets,
    ainekio_p4_feedback_observation_t *out);
struct cJSON;
struct cJSON *ainekio_p4_feedback_health_json(void);

esp_err_t ainekio_p4_feedback_start(void);
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out);
bool ainekio_p4_feedback_stand_enabled(void);
bool ainekio_p4_feedback_jam_enabled(void);
bool ainekio_p4_feedback_frame(const ainekio_p4_joint_config_t *mapping,
    ainekio_v2_frame_t *frame);
/* Final-pass observation of remaining goal error, in calibrated pulse units.
 * False means no complete post-write observation yet, not physical failure. */
bool ainekio_p4_feedback_check(const ainekio_p4_joint_config_t *mapping,
    const uint16_t *targets,int64_t commanded_us,uint16_t *remaining);
/* Jam observations only; sequence verification does not use this timer.
 * Each joint reports once until measured progress/arrival starts a new episode. */
typedef struct {
    struct { double best; int direction; int64_t sampled_us, progress_at; bool reported; } joint[12];
} ainekio_p4_feedback_progress_t;
uint16_t ainekio_p4_feedback_stalled(ainekio_p4_feedback_progress_t *progress,
    const ainekio_p4_joint_config_t *mapping,const uint16_t *targets);
/* Handler is called only after existing maintenance authentication. */
esp_err_t ainekio_p4_feedback_http(struct httpd_req *request);
