#ifndef AINEKIO_CONFIG_SCHEMA_H
#define AINEKIO_CONFIG_SCHEMA_H

#include <stdint.h>

#define AINEKIO_NVS_SCHEMA_VERSION UINT32_C(1)

/*
 * The inactive slot is staging. After validation, one metadata commit bumps
 * schema_ver and switches active_slot; an interrupted stage leaves the old slot
 * selected.
 */
#define AINEKIO_NVS_NAMESPACE_META "ainekio_meta"
#define AINEKIO_NVS_NAMESPACE_CONFIG_A "config_a"
#define AINEKIO_NVS_NAMESPACE_CONFIG_B "config_b"
#define AINEKIO_NVS_NAMESPACE_CALIBRATION "robot_cal"
#define AINEKIO_NVS_NAMESPACE_POSES "robot_poses"
#define AINEKIO_NVS_NAMESPACE_PREFERENCES "robot_prefs"

#define AINEKIO_NVS_KEY_SCHEMA_VERSION "schema_ver"
#define AINEKIO_NVS_KEY_ACTIVE_SLOT "active_slot"
#define AINEKIO_NVS_KEY_SETUP_HASH "setup_hash"

#define AINEKIO_NVS_KEY_GENERATION "generation"
#define AINEKIO_NVS_KEY_COMPLETE "complete"
#define AINEKIO_NVS_KEY_WIFI_SSID "wifi_ssid"
#define AINEKIO_NVS_KEY_WIFI_PSK "wifi_psk"
#define AINEKIO_NVS_KEY_ENDPOINT_URL "endpoint_url"
#define AINEKIO_NVS_KEY_ROBOT_ID "robot_id"
#define AINEKIO_NVS_KEY_ROBOT_TOKEN "robot_token"

#define AINEKIO_NVS_KEY_SERVO_CALIBRATION "servo_cal_v1"
#define AINEKIO_NVS_KEY_NAMED_POSES "named_pose_v1"
#define AINEKIO_NVS_KEY_DEFAULT_PROFILE "profile"
#define AINEKIO_NVS_KEY_ADC_FACTOR "adc_factor"

typedef enum {
    AINEKIO_CONFIG_SLOT_NONE = 0,
    AINEKIO_CONFIG_SLOT_A = 1,
    AINEKIO_CONFIG_SLOT_B = 2,
} ainekio_config_slot_t;

#endif
