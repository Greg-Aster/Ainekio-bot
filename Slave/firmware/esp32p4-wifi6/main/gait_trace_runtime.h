#pragma once
#include "servo_feedback.h"
#include "esp_err.h"
typedef struct cJSON cJSON;
struct httpd_req;
void ainekio_p4_gait_trace_output(const uint16_t pulses[12],uint64_t timestamp_us,bool armed);
void ainekio_p4_gait_trace_sample(const ainekio_p4_feedback_snapshot_t *sample);
/* Authenticated maintenance owner invokes only for explicit trace operations. */
esp_err_t ainekio_p4_gait_trace_http(struct httpd_req *request,const cJSON *operation);

#include "gait_trace.h"
void ainekio_p4_gait_trace_tracking(const ainekio_gait_trace_event_t *event);
