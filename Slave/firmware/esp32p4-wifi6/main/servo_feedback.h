#pragma once
#include "servo_feedback_model.h"
#include "joint_calibration.h"
#include "esp_err.h"
struct httpd_req;

typedef struct {
    uint16_t raw[16], spread[16], valid_mask;
    int millivolts[16];
    int64_t sampled_us[16];
    uint32_t scan, scan_us, revision;
    esp_err_t error, voltage_error;
    bool initialized, saved;
    ainekio_feedback_config_t config;
} ainekio_p4_feedback_snapshot_t;

esp_err_t ainekio_p4_feedback_start(void);
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out);
bool ainekio_p4_feedback_stand_enabled(void);
bool ainekio_p4_feedback_frame(const ainekio_p4_joint_config_t *mapping,
    ainekio_v2_frame_t *frame);
/* No blocking, time cutoff, PWM writes or automatic retries of a motion.
 * A missing/newly failed reading cannot confirm physical arrival. */
bool ainekio_p4_feedback_arrived(const ainekio_p4_joint_config_t *mapping,
    const uint16_t *targets,int64_t commanded_us,uint16_t *waiting_mask);
/* Handler is called only after existing maintenance authentication. */
esp_err_t ainekio_p4_feedback_http(struct httpd_req *request);
