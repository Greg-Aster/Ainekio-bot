"""End-to-end P4 firmware jam, I2t thermal cutoff, PCA9685 LEDn_OFF_H, deadlock bounds, and MicroDuck unsnag tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from protocol.control_v1 import validate_control_message


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "Slave" / "firmware" / "esp32p4-wifi6"


HARNESS_C = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "body.c"
#include "controller_motion.h"
#include "ainekio/control_codec.h"
#include "cJSON.h"

void ainekio_p4_log_stage(const char *stage) { assert(stage && *stage); }

static float saved_motion_rate = 1.0f;
static bool leveling_enabled = false;
static ainekio_v2_balance_tuning_t leveling_tuning = AINEKIO_V2_BALANCE_TUNING_DEFAULT;
ainekio_v2_balance_tuning_t ainekio_p4_balance_tuning(void) { return leveling_tuning; }
bool ainekio_p4_walking_feedback_enabled(void) { return false; }
bool ainekio_p4_balance_enabled(void) { return leveling_enabled; }
static ainekio_p4_imu_status_t imu_status;
ainekio_p4_imu_status_t ainekio_p4_imu_status(void) { return imu_status; }
float ainekio_p4_motion_rate(void) { return saved_motion_rate; }

struct test_queue { unsigned capacity, size, count; unsigned char data[]; };
static uint64_t clock_us;
static uint32_t rest_seconds = 180;
uint32_t ainekio_p4_idle_rest_seconds(void) { return rest_seconds; }
ainekio_p4_media_status_t ainekio_p4_media_status(void)
{ return (ainekio_p4_media_status_t){.speaker_busy = false}; }

struct test_timer { esp_timer_create_args_t args; uint64_t due; };
esp_err_t esp_timer_create(const esp_timer_create_args_t *a, esp_timer_handle_t *h)
{ *h = calloc(1, sizeof **h); (*h)->args = *a; return ESP_OK; }
esp_err_t esp_timer_start_once(esp_timer_handle_t t, uint64_t delay)
{ assert(!t->due); t->due = clock_us + delay; return ESP_OK; }
esp_err_t esp_timer_stop(esp_timer_handle_t t) { t->due = 0; return ESP_OK; }
static void rest_tick(void)
{
    if (rest_timer->due && clock_us >= rest_timer->due) {
        rest_timer->due = 0;
        rest_timer->args.callback(rest_timer->args.arg);
    }
    rest_step(clock_us);
}

QueueHandle_t xQueueCreate(unsigned n, unsigned size)
{
    QueueHandle_t q = calloc(1, sizeof(*q) + n * size);
    assert(q);
    q->capacity = n;
    q->size = size;
    return q;
}
int xQueueSend(QueueHandle_t q, const void *p, unsigned timeout)
{
    (void)timeout;
    if (q->count == q->capacity) return 0;
    memcpy(q->data + q->size * q->count++, p, q->size);
    return 1;
}
int xQueueReceive(QueueHandle_t q, void *p, unsigned timeout)
{
    if (q == results && !q->count && timeout && requests->count) {
        body_request_t request;
        assert(xQueueReceive(requests, &request, 0));
        body_result_t result = {request.serial, process_request(&request, clock_us)};
        if (result.result == ESP_OK && request.home && body.active && body.ramping) {
            body.pending_home = request.serial;
            while (body.pending_home && timeout >= 20) {
                clock_us += 20000;
                output_step(clock_us);
                timeout -= 20;
            }
        } else {
            assert(xQueueSend(results, &result, 0));
        }
    }
    if (!q->count) return 0;
    memcpy(p, q->data, q->size);
    --q->count;
    memmove(q->data, q->data + q->size, q->count * q->size);
    return 1;
}
int xQueueOverwrite(QueueHandle_t q, const void *p)
{ assert(q->capacity == 1); q->count = 0; return xQueueSend(q, p, 0); }
unsigned uxQueueSpacesAvailable(QueueHandle_t q) { return q->capacity - q->count; }
unsigned uxQueueMessagesWaiting(QueueHandle_t q) { return q->count; }
void *xSemaphoreCreateMutex(void) { return (void *)1; }
int xSemaphoreTake(void *p, unsigned t) { (void)p; (void)t; return 1; }
int xSemaphoreGive(void *p) { (void)p; return 1; }
int xTaskCreatePinnedToCore(void(*fn)(void*), const char *n, unsigned stack, void *a, unsigned pri, void *h, unsigned core)
{ (void)fn; (void)n; (void)stack; (void)a; (void)pri; (void)h; (void)core; return 1; }
void vTaskDelay(unsigned t) { clock_us += (uint64_t)t * 1000; }
int64_t esp_timer_get_time(void) { return (int64_t)clock_us; }
ainekio_p4_system_status_t ainekio_p4_system_status(void)
{ return (ainekio_p4_system_status_t){.restart_pending = false, .state = AINEKIO_STATE_IDLE}; }

/* Real PCA9685 driver wired to an in-memory I2C register bank + OE pin! */
static ainekio_pca9685_t pca_driver;
static uint8_t pca_regs[256];
static bool pca_oe_disabled = true;

static void pca_lock(void *ctx) { (void)ctx; }
static void pca_unlock(void *ctx) { (void)ctx; }
static void pca_disable_output(void *ctx, bool disable) { (void)ctx; pca_oe_disabled = disable; }
static uint64_t pca_now_us(void *ctx) { (void)ctx; return clock_us; }
static void pca_sleep_us(void *ctx, uint32_t us) { (void)ctx; clock_us += us; }
static ainekio_pca_bus_result_t pca_read(void *ctx, uint8_t reg, uint8_t *bytes, size_t count, uint32_t timeout_ms)
{
    (void)ctx; (void)timeout_ms;
    memcpy(bytes, &pca_regs[reg], count);
    return AINEKIO_PCA_BUS_OK;
}
static ainekio_pca_bus_result_t pca_write(void *ctx, uint8_t reg, const uint8_t *bytes, size_t count, uint32_t timeout_ms)
{
    (void)ctx; (void)timeout_ms;
    if (reg == 0x00U && count == 1U) {
        pca_regs[0x00U] = (uint8_t)(bytes[0] & 0x7FU);
        return AINEKIO_PCA_BUS_OK;
    }
    memcpy(&pca_regs[reg], bytes, count);
    return AINEKIO_PCA_BUS_OK;
}

ainekio_pca9685_t *ainekio_p4_output(void) { return &pca_driver; }

/* Real servo_feedback_position.c + servo_feedback_model.c wired to simulated 4th-wire ADC! */
static ainekio_p4_feedback_snapshot_t fb_state;
static ainekio_feedback_filter_t fb_filters[16];
void ainekio_p4_feedback_snapshot(ainekio_p4_feedback_snapshot_t *out) { *out = fb_state; }
bool ainekio_p4_feedback_stand_enabled(void) { return fb_state.config.enabled && fb_state.config.stand_enabled; }
bool ainekio_p4_feedback_jam_enabled(void)
{ return fb_state.config.enabled && fb_state.config.jam_enabled && fb_state.config.no_progress_ms; }

static ainekio_p4_joint_config_t mapped_joints[12];
static double plant_pulse_us[12];
static uint16_t plant_jammed_mask;

bool ainekio_p4_home_pulses(uint16_t p[12])
{
    for (unsigned i = 0; i < 12; i++) p[mapped_joints[i].channel] = mapped_joints[i].home_us;
    return true;
}
bool ainekio_p4_frame_pulses(const ainekio_v2_frame_t *f, uint16_t p[12])
{
    if (!ainekio_p4_joint_map_frame(mapped_joints, f, p)) return false;
    for (unsigned i = 0; i < 12; i++)
        if (p[i] && !ainekio_pca_pulse_valid(&pca_driver, p[i])) return false;
    return true;
}
ainekio_p4_calibration_t ainekio_p4_calibration(void)
{
    ainekio_p4_calibration_t s = {.valid = true, .saved = true, .profile_confirmed = true};
    memcpy(s.joints, mapped_joints, sizeof mapped_joints);
    return s;
}

static uint16_t raw_from_pulse(const ainekio_feedback_joint_t *joint, double pulse_us)
{
    const bool lo = pulse_us <= joint->point[1].pulse_us;
    const ainekio_feedback_point_t a = joint->point[lo ? 0 : 1];
    const ainekio_feedback_point_t b = joint->point[lo ? 1 : 2];
    const double raw = a.raw + (pulse_us - a.pulse_us) * ((double)b.raw - a.raw) / ((double)b.pulse_us - a.pulse_us);
    const double clamped = fmax(1.0, fmin(4094.0, raw));
    return (uint16_t)lround(clamped);
}

static void sample_adc(void)
{
    fb_state.valid_mask = 0xffff;
    fb_state.scan++;
    for (unsigned j = 0; j < 12; j++) {
        const unsigned ch = fb_state.config.joint[j].channel;
        const uint16_t raw = raw_from_pulse(&fb_state.config.joint[j], plant_pulse_us[j]);
        fb_state.raw[ch] = raw;
        fb_state.sampled_us[ch] = (int64_t)clock_us;
        ainekio_feedback_filter_update(&fb_filters[ch], raw, (int64_t)clock_us);
        fb_state.filtered_raw[ch] = (float)fb_filters[ch].position;
        fb_state.velocity_raw_s[ch] = (float)fb_filters[ch].velocity;
    }
}

static void step_sim(unsigned ms)
{
    assert(ms % 20 == 0);
    while (ms) {
        uint16_t cmd_pulses[12];
        ainekio_p4_body_pulses(cmd_pulses);
        for (unsigned j = 0; j < 12; j++) {
            const int out = mapped_joints[j].channel;
            if (out < 0 || !cmd_pulses[out] || (plant_jammed_mask & (1U << j))) continue;
            const double max_step = 2200.0 * 0.02;
            const double err = (double)cmd_pulses[out] - plant_pulse_us[j];
            plant_pulse_us[j] += fmax(-max_step, fmin(max_step, err));
        }
        clock_us += 20000;
        sample_adc();
        output_step(clock_us);
        rest_tick();
        ms -= 20;
    }
}

static void setup_fixture(void)
{
    free(requests); free(results); free(events);
    requests = results = events = NULL;
    body = (body_state_t){0};
    motion_status = (ainekio_p4_body_status_t){0};
    memset(commanded, 0, sizeof commanded);
    memset(pca_regs, 0, sizeof pca_regs);
    pca_oe_disabled = true;
    clock_us = 1000000;
    plant_jammed_mask = 0;
    imu_status = (ainekio_p4_imu_status_t){0};

    const ainekio_pca_port_t port = {
        .lock = pca_lock, .unlock = pca_unlock, .disable_output = pca_disable_output,
        .now_us = pca_now_us, .sleep_us = pca_sleep_us, .read = pca_read, .write = pca_write,
    };
    const ainekio_pca_config_t cfg = {.oscillator_hz = 25000000U, .frequency_hz = 50U};
    assert(ainekio_pca_init(&pca_driver, &port, &cfg) == AINEKIO_PCA_OK);

    assert(ainekio_p4_joint_defaults(mapped_joints));
    ainekio_feedback_defaults(&fb_state.config);
    fb_state.config.enabled = 1;
    fb_state.config.stand_enabled = 1;
    fb_state.config.jam_enabled = 1;
    fb_state.config.tolerance_us = 30;
    fb_state.config.arrival_tolerance_us = 35;
    fb_state.config.no_progress_ms = 1000;
    fb_state.config.progress_us = 5;
    fb_state.initialized = true;
    memset(fb_filters, 0, sizeof fb_filters);
    for (unsigned j = 0; j < 12; j++) {
        fb_state.config.joint[j] = (ainekio_feedback_joint_t){
            .channel = j, .points = 7,
            .point = {{500, 500}, {1900, 1650}, {3500, 2800}},
        };
    }
    assert(ainekio_feedback_config_valid(&fb_state.config));
    assert(ainekio_p4_body_start() == ESP_OK);

    ainekio_v2_walk_pose_t stand;
    assert(ainekio_v2_walk_pose(0, (ainekio_v2_walk_controls_t){0, 1}, &stand));
    uint16_t init_pulses[12];
    assert(ainekio_p4_frame_pulses(&stand.frame, init_pulses));
    assert(ainekio_pca_arm(&pca_driver, pca_driver.state.generation, init_pulses) == AINEKIO_PCA_OK);
    assert(!pca_oe_disabled);
    body.active = true;
    body.generation = pca_driver.state.generation;
    body.last_frame = clock_us;
    body.next_frame = clock_us + 20000;
    memcpy(body.pulses, init_pulses, sizeof init_pulses);
    for (unsigned j = 0; j < 12; j++) plant_pulse_us[j] = init_pulses[mapped_joints[j].channel];
    retain_manual_reference();
    publish(body.pulses);
    for (unsigned warm = 0; warm < 10; warm++) { clock_us += 20000; sample_adc(); }
}

int main(void)
{
    /* 1a. Zero false positives under 6.5 deg static gravity sag for 60 simulated seconds. */
    setup_fixture();
    mapped_joints[0].home_us = 1500;
    mapped_joints[0].home_cd = 0;
    mapped_joints[0].us_per_degree = 10.0f;
    body.pulses[0] = 1500;
    plant_pulse_us[0] = 1435.0; /* 6.5 deg static sag */
    plant_jammed_mask = 1U << 0;
    retain_manual_reference();
    publish(body.pulses);
    for (unsigned warm = 0; warm < 10; warm++) { clock_us += 20000; sample_adc(); }
    step_sim(60000);
    assert(body.thermal_cutoff_mask == 0);
    assert(body.feedback_thermal.thermal_load[0] == 0.0f);
    {
        ainekio_p4_body_event_t ev;
        assert(!ainekio_p4_body_event(&ev));
    }

    /* 1b. Zero false positives under oscillating 50 Hz walk_target streaming for 60 s. */
    setup_fixture();
    {
        char wire[768];
        ainekio_control_message_t msg;
        snprintf(wire, sizeof wire,
            "{\"t\":\"intent\",\"seq\":900,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":50,"
            "\"source\":\"host\",\"geometry\":\"%s\",\"reference_cd\":[0,346,-2163,0,346,-2163,0,346,-2163,0,346,-2163],"
            "\"twist\":[0.08,0,0]}",
            ainekio_v2_walk_geometry_id);
        assert(ainekio_control_decode_for_body(wire, strlen(wire), &msg) == AINEKIO_DECODE_OK);
        assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &msg.command) == ESP_OK);
        step_sim(100);
        for (unsigned tick = 0; tick < 3000; tick++) {
            const float lift = 12.0f * sinf(2.0f * 3.14159265f * 1.25f * (0.02f * (float)tick));
            snprintf(wire, sizeof wire,
                "{\"t\":\"walk_target\",\"seq\":%u,\"walk\":900,\"sample\":%u,\"geometry\":\"%s\","
                "\"feet_mm\":[0,0,%.6f,0,0,%.6f,0,0,%.6f,0,0,%.6f]}",
                10000U + tick, tick + 1U, ainekio_v2_walk_geometry_id,
                (double)lift, (double)-lift, (double)-lift, (double)lift);
            assert(ainekio_control_decode_for_body(wire, strlen(wire), &msg) == AINEKIO_DECODE_OK);
            assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &msg.command) == ESP_OK);
            step_sim(20);
        }
        assert(body.thermal_cutoff_mask == 0);
        ainekio_p4_body_event_t ev;
        while (ainekio_p4_body_event(&ev)) {
            assert(!ev.jam_observation && !ev.outputs_released);
        }
    }

    /* 2 & 3. End-stop jam outside [500, 2800] us (430 us while commanded to 320 us)
     * zeroes ONLY PCA9685 LEDn_OFF_H = 0x10 on the jammed channel while keeping
     * the other 11 channels active, aborts motion, and emits outputs_released: true. */
    setup_fixture();
    mapped_joints[0].home_us = 320;
    mapped_joints[0].home_cd = 0;
    mapped_joints[0].us_per_degree = 6.0f;
    body.pulses[0] = 320;
    plant_pulse_us[0] = 430.0;
    plant_jammed_mask = 1U << 0;
    retain_manual_reference();
    publish(body.pulses);
    for (unsigned warm = 0; warm < 10; warm++) { clock_us += 20000; sample_adc(); }

    {
        char wire[768];
        ainekio_control_message_t msg;
        snprintf(wire, sizeof wire,
            "{\"t\":\"intent\",\"seq\":901,\"name\":\"walk\",\"dir\":\"fwd\",\"steps\":0,\"speed\":50,"
            "\"source\":\"host\",\"geometry\":\"%s\",\"reference_cd\":[0,346,-2163,0,346,-2163,0,346,-2163,0,346,-2163],"
            "\"twist\":[0.08,0,0]}",
            ainekio_v2_walk_geometry_id);
        assert(ainekio_control_decode_for_body(wire, strlen(wire), &msg) == AINEKIO_DECODE_OK);
        assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &msg.command) == ESP_OK);
    }

    char nonterminal_notice[320] = {0};
    char terminal_notice[320] = {0};
    unsigned trip_ms = 0;
    while (trip_ms < 12000 && !body.thermal_cutoff_mask) {
        step_sim(20);
        trip_ms += 20;
        ainekio_p4_body_event_t ev;
        while (ainekio_p4_body_event(&ev)) {
            if (ev.jam_observation && !ev.outputs_released)
                assert(ainekio_p4_body_notice(&ev, 77, nonterminal_notice, sizeof nonterminal_notice));
            if (ev.outputs_released) {
                assert(!ev.completed && ev.result == ESP_ERR_INVALID_STATE && ev.sequence == 901);
                assert(ainekio_p4_body_notice(&ev, 77, terminal_notice, sizeof terminal_notice));
            }
        }
    }
    {
        ainekio_p4_body_event_t ev;
        while (ainekio_p4_body_event(&ev)) {
            if (ev.outputs_released) {
                assert(!ev.completed && ev.result == ESP_ERR_INVALID_STATE && ev.sequence == 901);
                assert(ainekio_p4_body_notice(&ev, 77, terminal_notice, sizeof terminal_notice));
            }
        }
    }
    assert(body.thermal_cutoff_mask == (1U << 0));
    assert(trip_ms >= 8000 && trip_ms <= 10000);
    assert(body.motion.kind == MOTION_NONE);
    assert(!pca_oe_disabled); /* PCA9685 OE stays enabled for the 11 healthy servos! */
    assert((pca_regs[0x06U + 4U * 0U + 3U] & 0x10U) == 0x10U);
    for (unsigned ch = 1; ch < 12; ch++) {
        assert((pca_regs[0x06U + 4U * ch + 3U] & 0x10U) == 0x00U);
    }
    assert(nonterminal_notice[0] != '\0');
    assert(terminal_notice[0] != '\0');

    /* 4a. Freestyle single-frame arrival wait completes within ~800 ms on a blocked joint. */
    setup_fixture();
    plant_jammed_mask = 1U << 2;
    ainekio_command_t fs1 = {.kind = AINEKIO_COMMAND_MOTION_PLAN, .sequence = 902};
    fs1.data.motion_plan = (ainekio_motion_plan_t){
        .joint_map_version = 2, .frame_count = 1, .target_control = true,
        .end = AINEKIO_MOTION_PLAN_END_HOLD,
    };
    for (unsigned j = 0; j < 12; j++)
        fs1.data.motion_plan.frames[0].targets[j] = (int32_t)lroundf(body.pose.position[j]);
    fs1.data.motion_plan.frames[0].targets[2] += 1500;
    fs1.data.motion_plan.frames[0].speed_cd_s = 60000;
    assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &fs1) == ESP_OK);
    unsigned fs1_ms = 0;
    while (fs1_ms < 2000 && body.motion.kind != MOTION_NONE) {
        step_sim(20);
        fs1_ms += 20;
    }
    assert(body.motion.kind == MOTION_NONE && fs1_ms >= 800 && fs1_ms <= 1100);

    /* 4b. Verified Stand caps at max 2 replans on a blocked joint and does not loop in stand_hold_recover. */
    setup_fixture();
    body.pulses[mapped_joints[3].channel] -= 75;
    plant_pulse_us[3] = body.pulses[mapped_joints[3].channel];
    plant_jammed_mask = 1U << 3;
    retain_manual_reference();
    publish(body.pulses);
    for (unsigned warm = 0; warm < 10; warm++) { clock_us += 20000; sample_adc(); }
    ainekio_command_t stand_blocked = {.sequence = 903, .kind = AINEKIO_COMMAND_INTENT,
        .data.intent = {.kind = AINEKIO_INTENT_STAND}};
    assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &stand_blocked) == ESP_OK);
    unsigned stand_ms = 0;
    while (stand_ms < 25000 && body.motion.kind != MOTION_NONE) {
        step_sim(20);
        stand_ms += 20;
    }
    assert(body.motion.kind == MOTION_NONE);
    assert(body.motion.posture_replans == STAND_MAX_REPLANS);
    assert(!body.stand_goal_active);
    step_sim(1000);
    assert(body.motion.kind == MOTION_NONE);

    /* 4c. Inactivity lay_down with a blocked joint never deadlocks (both with
     * jam_enabled == 0 checkpoint timeouts and jam_enabled == 1 thermal cutoff)
     * and drives PCA9685 OE high (pca_oe_disabled == true) via ainekio_pca_idle()! */
    unsigned lay_ms = 0;
    for (unsigned jam_on = 0; jam_on < 2; jam_on++) {
        setup_fixture();
        fb_state.config.jam_enabled = (uint8_t)jam_on;
        ainekio_command_t stand_cmd = {.sequence = 904 + jam_on, .kind = AINEKIO_COMMAND_INTENT,
            .data.intent = {.kind = AINEKIO_INTENT_STAND}};
        assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &stand_cmd) == ESP_OK);
        for (unsigned ms = 0; ms < 10000 && body.motion.kind != MOTION_NONE; ms += 20) step_sim(20);
        assert(body.motion.kind == MOTION_NONE);
        rest_tick();
        assert(rest_timer->due > clock_us);
        plant_jammed_mask = 1U << 4; /* Block rear-right carrier during lay_down */
        clock_us = rest_timer->due;
        rest_tick();
        assert(body.motion.kind == MOTION_CLIP && body.motion.release_on_complete);
        lay_ms = 0;
        while (lay_ms < 25000 && body.motion.kind != MOTION_NONE) {
            step_sim(20);
            lay_ms += 20;
        }
        assert(body.motion.kind == MOTION_NONE);
        assert(pca_oe_disabled && !pca_driver.state.armed);
        assert(pca_driver.state.fault == AINEKIO_PCA_FAULT_NONE);
    }

    /* 5. On-chip MicroDuck enters 1.8 s reverse unsnag after 1.8 s forward leg snag. */
    setup_fixture();
    plant_pulse_us[6] = 650.0;
    plant_jammed_mask = 1U << 6;
    for (unsigned warm = 0; warm < 10; warm++) { clock_us += 20000; sample_adc(); }
    ainekio_command_t md_walk = {.sequence = 905, .kind = AINEKIO_COMMAND_INTENT,
        .data.intent = {.kind = AINEKIO_INTENT_WALK}};
    md_walk.data.intent.data.walk.controls = 1;
    md_walk.data.intent.data.walk.speed_percent = 100;
    assert(ainekio_p4_body_execute(pca_driver.state.generation, 17, &md_walk) == ESP_OK);
    unsigned snag_ms = 0;
    while (snag_ms < 3000 && !body.microduck_unsnag_until_us) {
        step_sim(20);
        snag_ms += 20;
    }
    assert(body.microduck_unsnag_until_us > clock_us);
    assert(snag_ms >= 1760 && snag_ms <= 1900);
    assert(fabsf(body.microduck_cmd_twist[0] - (-0.45f)) < 1e-4f);
    assert(body.microduck_cmd_twist[1] == 0.0f && body.microduck_cmd_twist[2] == 0.0f);
    plant_jammed_mask = 0;
    unsigned unsnag_ms = 0;
    while (unsnag_ms < 2200 && body.microduck_unsnag_until_us > clock_us) {
        step_sim(20);
        unsnag_ms += 20;
    }
    assert(unsnag_ms >= 1780 && unsnag_ms <= 1840);
    step_sim(20);
    assert(body.microduck_unsnag_until_us == 0);
    assert(body.microduck_cmd_twist[0] > 0.05f);
    assert(body.microduck_unsnag_cooldown_until_us > clock_us);

    printf("{\"trip_ms\":%u,\"lay_ms\":%u,\"snag_ms\":%u,\"unsnag_ms\":%u,\"nonterminal\":%s,\"terminal\":%s}\n",
           trip_ms, lay_ms, snag_ms, unsnag_ms, nonterminal_notice, terminal_notice);
    return 0;
}
'''


class P4JamAndThermalIntegrationTests(unittest.TestCase):
    def test_end_to_end_pca9685_cutoff_wire_notice_and_laydown_idle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ainekio-p4-jam-thermal-") as tmp:
            work = Path(tmp)
            build_dir = work / "cmake_build"
            subprocess.run(
                [
                    "cmake",
                    "-S",
                    str(FIRMWARE / "tests"),
                    "-B",
                    str(build_dir),
                    f"-DPython3_EXECUTABLE={sys.executable}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "cmake",
                    "--build",
                    str(build_dir),
                    "--target",
                    "ainekio_v2_motion",
                    "ainekio_imu",
                    "ainekio_core",
                    "--parallel",
                    "4",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            harness_path = work / "harness.c"
            binary_path = work / "harness"
            harness_path.write_text(HARNESS_C, encoding="utf-8")
            cjson_dir = FIRMWARE / "managed_components" / "espressif__cjson" / "cJSON"
            compiled = subprocess.run(
                [
                    "cc",
                    "-std=c11",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-UNDEBUG",
                    str(harness_path),
                    str(FIRMWARE / "main" / "joint_calibration.c"),
                    str(FIRMWARE / "main" / "controller_motion.c"),
                    str(FIRMWARE / "main" / "servo_feedback_model.c"),
                    str(FIRMWARE / "main" / "servo_feedback_position.c"),
                    str(FIRMWARE / "main" / "trajectory_program.c"),
                    str(FIRMWARE / "components" / "ainekio_pca9685" / "pca9685.c"),
                    str(cjson_dir / "cJSON.c"),
                    "-I",
                    str(FIRMWARE / "tests" / "body_shim"),
                    "-I",
                    str(FIRMWARE / "main"),
                    "-I",
                    str(FIRMWARE / "components" / "ainekio_pca9685" / "include"),
                    "-I",
                    str(FIRMWARE / "components" / "ainekio_p4_media" / "include"),
                    "-I",
                    str(ROOT / "Slave" / "software" / "models" / "v2-12servo" / "include"),
                    "-I",
                    str(ROOT / "Slave" / "software" / "core" / "include"),
                    "-I",
                    str(ROOT / "Slave" / "software" / "imu" / "include"),
                    "-I",
                    str(ROOT / "Slave" / "software" / "imu" / "vendor" / "Fusion" / "Fusion"),
                    "-I",
                    str(cjson_dir),
                    str(build_dir / "v2_model" / "libainekio_v2_motion.a"),
                    str(build_dir / "imu" / "libainekio_imu.a"),
                    str(build_dir / "v2_model" / "core" / "libainekio_core.a"),
                    "-lm",
                    "-o",
                    str(binary_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run(
                [str(binary_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertGreaterEqual(payload["trip_ms"], 8000)
            self.assertLessEqual(payload["trip_ms"], 10000)
            self.assertLess(payload["lay_ms"], 20000)
            self.assertGreaterEqual(payload["snag_ms"], 1760)
            self.assertLessEqual(payload["snag_ms"], 1900)
            self.assertGreaterEqual(payload["unsnag_ms"], 1780)
            self.assertLessEqual(payload["unsnag_ms"], 1840)

            nonterminal = payload["nonterminal"]
            terminal = payload["terminal"]
            validate_control_message(nonterminal)
            validate_control_message(terminal)
            self.assertEqual(nonterminal["name"], "servo_stall")
            self.assertEqual(nonterminal["joint_mask"], 1)
            self.assertFalse(nonterminal["outputs_released"])
            self.assertEqual(terminal["name"], "servo_stall")
            self.assertEqual(terminal["seq"], 901)
            self.assertEqual(terminal["joint_mask"], 1)
            self.assertTrue(terminal["outputs_released"])


if __name__ == "__main__":
    unittest.main()
