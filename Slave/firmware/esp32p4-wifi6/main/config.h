#pragma once

#include "ainekio/config_store.h"
#include "ainekio/protocol.h"
#include "esp_err.h"
#include "joint_calibration.h"
#include "robot_settings.h"

const ainekio_p4_robot_settings_t *ainekio_p4_boot_settings(void);
ainekio_p4_robot_settings_t ainekio_p4_saved_settings(void);
esp_err_t ainekio_p4_settings_change(const ainekio_robot_settings_command_t *command);

esp_err_t ainekio_p4_config_init(void);
const ainekio_config_record_t *ainekio_p4_config(void);
/* Boot identity is immutable. Successful writes take effect after restart. */
esp_err_t ainekio_p4_config_save_record(const ainekio_config_record_t *record);
esp_err_t ainekio_p4_config_reset_network(void);

typedef struct {
    ainekio_p4_joint_config_t joints[AINEKIO_BODY_JOINT_COUNT];
    bool valid, dirty, saved, profile_confirmed;
} ainekio_p4_calibration_t;

ainekio_p4_calibration_t ainekio_p4_calibration(void);
esp_err_t ainekio_p4_calibration_stage(uint8_t id, const ainekio_p4_joint_config_t *joint);
/* The output owner must disable PWM before committing flash. Saving never
 * restarts or re-arms a servo; Home/Move explicitly resumes outputs. */
esp_err_t ainekio_p4_calibration_save(void);
bool ainekio_p4_home_pulses(uint16_t pulses[AINEKIO_BODY_JOINT_COUNT]);
bool ainekio_p4_frame_pulses(const ainekio_v2_frame_t *frame,
                           uint16_t pulses[AINEKIO_BODY_JOINT_COUNT]);
/* Named-motion speed, in thousandths. Storage writes require disabled output. */
float ainekio_p4_motion_rate(void);
bool ainekio_p4_motion_rate_saved(void);
esp_err_t ainekio_p4_motion_rate_save(float rate);
int ainekio_p4_config_command(int argc, char **argv);
