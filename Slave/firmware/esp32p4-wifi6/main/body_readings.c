#include "body_readings.h"
#include "body.h"
#include "board.h"
#include "config.h"
#include "servo_feedback.h"
#include "ainekio/v2_limits.h"
#include "esp_timer.h"
#include "cJSON.h"
#include <stdio.h>

cJSON *ainekio_p4_calibration_json(uint32_t sequence)
{
    const ainekio_p4_calibration_t state = ainekio_p4_calibration();
    const ainekio_pca_status_t output = ainekio_pca_status(ainekio_p4_output());
    uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS];
    ainekio_p4_body_pulses(pulses);
    cJSON *message = cJSON_CreateObject();
    if (!message) return NULL;
    cJSON_AddStringToObject(message, "t", "calibration_status");
    cJSON_AddNumberToObject(message, "seq", sequence);
    cJSON_AddBoolToObject(message, "dirty", state.dirty);
    cJSON_AddBoolToObject(message, "saved", state.saved);
    cJSON_AddBoolToObject(message, "profile_confirmed", state.profile_confirmed);
    cJSON_AddStringToObject(message, "servo_profile_id", ainekio_v2_servo_profile_id());
    cJSON_AddNumberToObject(message, "provisional_us_per_degree", ainekio_v2_us_per_degree());
    cJSON_AddBoolToObject(message, "shaft_travel_measured", false);
    cJSON_AddBoolToObject(message, "ready", state.valid && output.ready);
    uint16_t pulse_min, pulse_max;
    if (ainekio_pca_pulse_bounds(ainekio_p4_output(), &pulse_min, &pulse_max)) {
        cJSON_AddNumberToObject(message, "pulse_min_us", pulse_min);
        cJSON_AddNumberToObject(message, "pulse_max_us", pulse_max);
    }
    cJSON *joints = cJSON_AddArrayToObject(message, "joints");
    for (size_t i=0; i<AINEKIO_BODY_JOINT_COUNT; ++i) {
        const ainekio_p4_joint_config_t *joint = &state.joints[i];
        cJSON *entry = cJSON_CreateObject();
        if (!entry || !joints) { cJSON_Delete(entry); cJSON_Delete(message); return NULL; }
        cJSON_AddItemToArray(joints, entry);
        cJSON_AddNumberToObject(entry, "id", i);
        cJSON_AddNumberToObject(entry, "channel", joint->channel);
        cJSON_AddNumberToObject(entry, "home_us", joint->home_us);
        cJSON_AddBoolToObject(entry, "invert", joint->invert);
        cJSON_AddNumberToObject(entry, "home_cd", joint->home_cd);
        cJSON_AddNumberToObject(entry, "recommended_home_us",
            ainekio_p4_joint_recommended_home(i, joint->invert));
        cJSON_AddNumberToObject(entry, "recommended_home_cd", 100.*ainekio_v2_center_degrees(i));
        cJSON_AddNumberToObject(entry, "us_per_degree", joint->us_per_degree);
        cJSON_AddNumberToObject(entry, "pulse_us", joint->channel < 0 ? 0 : pulses[joint->channel]);
    }
    return message;
}

size_t ainekio_p4_motion_speed_json(uint32_t sequence,double rate,bool saved,
    double joint_speed,bool speed_saved,char *text,size_t capacity)
{
    return snprintf(text, capacity, "{\"t\":\"motion_speed_status\",\"seq\":%lu,\"rate\":%.9g,\"saved\":%s,\"joint_speed_limit_deg_s\":%.9g,\"joint_speed_limit_saved\":%s}",
        (unsigned long)sequence, (double)rate,
        saved ? "true" : "false",
        joint_speed, speed_saved ? "true" : "false");
}

static cJSON *health_json(const ainekio_p4_feedback_snapshot_t *s)
{
    ainekio_p4_feedback_health_t health;ainekio_p4_feedback_health(s,&health);
    cJSON *o=cJSON_CreateObject();if(!o)return NULL;
    cJSON_AddBoolToObject(o,"enabled",s->config.enabled);
    cJSON_AddBoolToObject(o,"usable",s->config.enabled && health.calibrated==0xfff &&
        !(health.unavailable|health.clipped|health.below_calibration|health.above_calibration));
    cJSON_AddNumberToObject(o,"scan",s->scan);
    cJSON_AddNumberToObject(o,"clock_us",esp_timer_get_time());
    cJSON_AddNumberToObject(o,"calibrated_mask",health.calibrated);
    cJSON_AddNumberToObject(o,"unavailable_mask",health.unavailable);
    cJSON_AddNumberToObject(o,"clipped_mask",health.clipped);
    cJSON_AddNumberToObject(o,"below_calibration_mask",health.below_calibration);
    cJSON_AddNumberToObject(o,"above_calibration_mask",health.above_calibration);
    cJSON_AddStringToObject(o,"adc_error",esp_err_to_name(s->error));
    cJSON_AddBoolToObject(o,"supply_voltage_available",false);
    cJSON *mv=cJSON_AddArrayToObject(o,"signal_millivolts");
    for(unsigned j=0;j<12;j++) {
        unsigned channel=s->config.joint[j].channel;
        cJSON_AddItemToArray(mv,s->config.enabled && (s->valid_mask&(1U<<channel)) &&
            s->millivolts[channel]>=0 ? cJSON_CreateNumber(s->millivolts[channel]):cJSON_CreateNull());
    }
    return o;
}
cJSON *ainekio_p4_feedback_health_json(void)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    return health_json(&s);
}
cJSON *ainekio_p4_feedback_status_json(void)
{
    ainekio_p4_feedback_snapshot_t s;ainekio_p4_feedback_snapshot(&s);
    ainekio_p4_calibration_t mapping=ainekio_p4_calibration();
    uint16_t targets[12];ainekio_p4_body_pulses(targets);
    cJSON *o=cJSON_CreateObject();if(!o)return NULL;
    cJSON_AddBoolToObject(o,"enabled",s.config.enabled);cJSON_AddBoolToObject(o,"stand_enabled",s.config.stand_enabled);
    cJSON_AddItemToObject(o,"health",health_json(&s));
    cJSON_AddBoolToObject(o,"jam_enabled",s.config.jam_enabled);
    cJSON_AddStringToObject(o,"jam_policy","recovery_first");
    cJSON_AddBoolToObject(o,"initialized",s.initialized);cJSON_AddBoolToObject(o,"saved",s.saved);
    cJSON_AddNumberToObject(o,"tolerance_us",s.config.tolerance_us);
    cJSON_AddNumberToObject(o,"arrival_tolerance_us",s.config.arrival_tolerance_us);
    cJSON_AddNumberToObject(o,"no_progress_ms",s.config.no_progress_ms);
    cJSON_AddNumberToObject(o,"progress_us",s.config.progress_us);
    cJSON_AddNumberToObject(o,"scan",s.scan);cJSON_AddNumberToObject(o,"scan_us",s.scan_us);
    cJSON_AddNumberToObject(o,"revision",s.revision);
    cJSON_AddStringToObject(o,"error",esp_err_to_name(s.error));
    cJSON_AddStringToObject(o,"voltage_error",esp_err_to_name(s.voltage_error));
    cJSON_AddNumberToObject(o,"device_us",esp_timer_get_time());
    const ainekio_p4_body_status_t motion=ainekio_p4_body_status();
    cJSON_AddBoolToObject(o,"stand_waiting",motion.servo_feedback_waiting);
    cJSON_AddNumberToObject(o,"waiting_joints",motion.servo_feedback_waiting_mask);
    cJSON_AddNumberToObject(o,"stand_progress",motion.stand_progress);
    cJSON_AddBoolToObject(o,"stand_replanning",motion.stand_replanning);
    cJSON_AddNumberToObject(o,"stand_replans",motion.stand_replans);
    cJSON_AddNumberToObject(o,"stalled_joints",motion.stalled_joints);
    cJSON_AddNumberToObject(o,"stall_clock_us",motion.stall_clock_us);
    cJSON *channels=cJSON_AddArrayToObject(o,"channels"),*joints=cJSON_AddArrayToObject(o,"joints");
    for(unsigned channel=0;channel<16;channel++) {
        bool valid=s.config.enabled&&(s.valid_mask&(1U<<channel));
        cJSON *v=cJSON_CreateObject();cJSON_AddItemToArray(channels,v);
        cJSON_AddNumberToObject(v,"channel",channel);cJSON_AddBoolToObject(v,"valid",valid);
        if(valid) {
            cJSON_AddNumberToObject(v,"raw",s.raw[channel]);
            cJSON_AddNumberToObject(v,"filtered_raw",s.filtered_raw[channel]);
            cJSON_AddNumberToObject(v,"velocity_raw_s",s.velocity_raw_s[channel]);
            cJSON_AddNumberToObject(v,"spread",s.spread[channel]);
            cJSON_AddNumberToObject(v,"sampled_us",s.sampled_us[channel]);
            cJSON_AddBoolToObject(v,"at_adc_rail",s.raw[channel]==0||s.raw[channel]==4095);
            if(s.millivolts[channel]>=0)cJSON_AddNumberToObject(v,"millivolts",s.millivolts[channel]);
        }
    }
    for(unsigned id=0;id<12;id++) {
        const ainekio_feedback_joint_t *j=&s.config.joint[id];
        const ainekio_p4_joint_config_t *m=&mapping.joints[id];
        cJSON *v=cJSON_CreateObject();cJSON_AddItemToArray(joints,v);
        cJSON_AddNumberToObject(v,"id",id);cJSON_AddNumberToObject(v,"channel",j->channel);
        cJSON_AddNumberToObject(v,"output",m->channel);
        cJSON_AddBoolToObject(v,"calibrated",ainekio_feedback_calibrated(j));
        unsigned target=m->channel<0?0:targets[m->channel];
        cJSON_AddNumberToObject(v,"command_us",target);
        cJSON *points=cJSON_AddArrayToObject(v,"points");
        for(unsigned p=0;p<3;p++) {
            if(!(j->points&(1U<<p))){cJSON_AddItemToArray(points,cJSON_CreateNull());continue;}
            cJSON *point=cJSON_CreateObject();cJSON_AddItemToArray(points,point);
            cJSON_AddNumberToObject(point,"raw",j->point[p].raw);
            cJSON_AddNumberToObject(point,"pulse_us",j->point[p].pulse_us);
        }
        double measured;bool in_range;
        if(s.config.enabled&&(s.valid_mask&(1U<<j->channel))&&
           ainekio_feedback_position(j,s.raw[j->channel],&measured,&in_range)) {
            cJSON_AddNumberToObject(v,"measured_us",measured);
            cJSON_AddBoolToObject(v,"in_calibrated_range",in_range);
            double degrees=(measured-m->home_us)/m->us_per_degree;
            cJSON_AddNumberToObject(v,"model_deg",m->home_cd/100.+(m->invert?-degrees:degrees));
            if(target)cJSON_AddNumberToObject(v,"error_us",target-measured);
            double filtered,neighbor;
            if(ainekio_feedback_position(j,s.filtered_raw[j->channel],&filtered,&in_range)&&
               ainekio_feedback_position(j,s.filtered_raw[j->channel]+1.,&neighbor,&in_range)) {
                cJSON_AddNumberToObject(v,"filtered_us",filtered);
                cJSON_AddNumberToObject(v,"velocity_us_s",(neighbor-filtered)*s.velocity_raw_s[j->channel]);
                if(target)cJSON_AddNumberToObject(v,"filtered_error_us",target-filtered);
            }
        }
    }
    return o;
}
