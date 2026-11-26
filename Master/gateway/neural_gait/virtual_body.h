#pragma once
#include "config.h"
#include "ainekio/p4_imu.h"

/* Private bridge to the existing modeled acquisition state. No second sensor
 * filter, calibration mapper or attitude estimator lives in the virtual port. */
void simulation_p4_activate(void *state);
void simulation_p4_mapping(void *state, ainekio_p4_calibration_t *out);
void simulation_p4_imu(void *state, uint64_t now_us, ainekio_p4_imu_status_t *out);

int virtual_body_reset(void *sensor, const double *reference_deg,
    const double *settings, uint64_t now_us);
void virtual_body_close(void);
int virtual_body_tick(uint64_t now_us, double *output);
size_t virtual_body_telemetry(uint64_t now_us, char *text, size_t capacity);

void virtual_body_open(uint64_t connection, uint64_t now_us);
void virtual_body_connection_lost(uint64_t connection);
size_t virtual_body_hello(const char *id, const char *token, uint64_t now_us,
    char *text, size_t capacity);
size_t virtual_body_receive(const char *wire, uint64_t connection, uint64_t now_us,
    char *text, size_t capacity);
size_t virtual_body_events(char *text, size_t capacity);

size_t virtual_body_feedback(uint64_t now_us, char *text, size_t capacity);

/* Full-parity P4 simulator extensions: preserve minimal training contract by
 * default until virtual_body_set_full_parity(1) is enabled. */
void virtual_body_set_full_parity(int enabled);
void virtual_body_set_face_style(int style);
void virtual_body_set_media_state(int camera_ready, int microphone_ready,
    int speaker_ready, int wake_ready, int display_ready, int capturing,
    int speaker_busy, int external_speech, float mic_rms, float mic_peak,
    float battery_voltage);
size_t virtual_body_status(uint64_t now_us, char *text, size_t capacity);
size_t virtual_body_heartbeat(uint64_t now_us, int pong, char *text, size_t capacity);
size_t virtual_body_feedback_health(uint64_t now_us, char *text, size_t capacity);
size_t virtual_body_media_actions(char *text, size_t capacity);
size_t virtual_body_mic_gate(uint64_t now_us, int open, int wake_word,
    char *text, size_t capacity);
size_t virtual_body_mic_frame(uint64_t now_us, const uint8_t *pcm, size_t pcm_len,
    uint8_t *packet_out, size_t packet_cap);
size_t virtual_body_camera_frame(uint64_t now_us, int origin, uint32_t origin_id,
    const char *res_name, uint64_t frame_completed_us, uint32_t boot_id,
    const uint8_t *jpeg, size_t jpeg_len, char *meta_out, size_t meta_cap,
    uint8_t *packet_out, size_t packet_cap, char *done_out, size_t done_cap);
int virtual_body_face_frame(uint64_t now_ms, int talking, int capturing,
    uint8_t *rgba_out, char *name_out, size_t name_cap,
    char *token_out, size_t token_cap);
