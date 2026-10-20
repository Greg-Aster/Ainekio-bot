#pragma once

#include "ainekio/config_store.h"
#include "ainekio/protocol.h"
#include "ainekio/v2_balance.h"
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
/* Joint speed in degrees/second; storage writes require disabled output. */
bool ainekio_p4_joint_speed_saved(void);
esp_err_t ainekio_p4_joint_speed_save(float limit);
/* Named-motion playback multiplier. Storage writes require disabled output. */
float ainekio_p4_motion_rate(void);
bool ainekio_p4_motion_rate_saved(void);
esp_err_t ainekio_p4_motion_rate_save(float rate);
/* Independent saved feedback selection; changing it does not stop motion. */
bool ainekio_p4_balance_enabled(void);
bool ainekio_p4_balance_saved(void);
esp_err_t ainekio_p4_balance_save(bool enabled);
ainekio_v2_balance_tuning_t ainekio_p4_balance_tuning(void);
bool ainekio_p4_balance_tuning_saved(void);
esp_err_t ainekio_p4_balance_configure(bool enabled,const ainekio_v2_balance_tuning_t *tuning);
/* Inactivity before normal lay-down; zero disables automatic rest. */
uint32_t ainekio_p4_idle_rest_seconds(void);
bool ainekio_p4_idle_rest_saved(void);
esp_err_t ainekio_p4_idle_rest_save(uint32_t seconds);
int ainekio_p4_config_command(int argc, char **argv);
