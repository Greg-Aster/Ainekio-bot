#pragma once
/* Existing physical body read serializers, also used by the virtual HAL. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
struct cJSON;
struct cJSON *ainekio_p4_calibration_json(uint32_t sequence);
struct cJSON *ainekio_p4_feedback_status_json(void);
size_t ainekio_p4_motion_speed_json(uint32_t sequence,double rate,bool saved,
    double joint_speed,bool speed_saved,char *text,size_t capacity);
