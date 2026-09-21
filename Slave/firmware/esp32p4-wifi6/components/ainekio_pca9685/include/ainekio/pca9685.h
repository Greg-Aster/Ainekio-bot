#ifndef AINEKIO_PCA9685_H
#define AINEKIO_PCA9685_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_PCA_CHANNELS 16U
#define AINEKIO_PCA_BODY_CHANNELS 12U
#define AINEKIO_PCA_IO_BUDGET_US UINT64_C(5000)
#define AINEKIO_PCA_PROGRESS_LIMIT_US UINT64_C(40000)

typedef enum {
    AINEKIO_PCA_OK = 0,
    AINEKIO_PCA_INVALID,
    AINEKIO_PCA_IO,
    AINEKIO_PCA_BUSY,
    AINEKIO_PCA_DISARMED,
    AINEKIO_PCA_STALE,
    AINEKIO_PCA_DEADLINE,
    AINEKIO_PCA_WIRING,
} ainekio_pca_result_t;

typedef enum {
    AINEKIO_PCA_FAULT_NONE = 0,
    AINEKIO_PCA_FAULT_EMERGENCY,
    AINEKIO_PCA_FAULT_IO,
    AINEKIO_PCA_FAULT_DEADLINE,
    AINEKIO_PCA_FAULT_PROGRESS,
    AINEKIO_PCA_FAULT_WIRING,
} ainekio_pca_fault_t;

/* The gate lock and OE callback MUST be bounded and independent of the bus.
 * write/read complete synchronously. An asynchronous port must drain its work
 * before returning; returning while an old write can still run is prohibited. */
typedef struct {
    void *context;
    void (*lock)(void *context);
    void (*unlock)(void *context);
    void (*disable_output)(void *context, bool disabled);
    uint64_t (*now_us)(void *context);
    void (*sleep_us)(void *context, uint32_t duration_us);
    bool (*write)(void *context, uint8_t reg, const uint8_t *data,
                  size_t length, uint32_t timeout_ms);
    bool (*read)(void *context, uint8_t reg, uint8_t *data,
                 size_t length, uint32_t timeout_ms);
} ainekio_pca_port_t;

typedef struct {
    uint32_t oscillator_hz;
    uint16_t frequency_hz;
} ainekio_pca_config_t;

typedef struct {
    uint64_t generation;
    uint64_t last_frame_us;
    uint64_t io_started_us;
    uint32_t frames;
    ainekio_pca_fault_t fault;
    bool ready;
    bool armed;
    bool in_flight;
    bool io_pending;
    bool wiring_verified;
} ainekio_pca_status_t;

typedef struct {
    ainekio_pca_port_t port;
    ainekio_pca_config_t config;
    ainekio_pca_status_t state;
    uint8_t prescale;
} ainekio_pca9685_t;

ainekio_pca_result_t ainekio_pca_init(ainekio_pca9685_t *driver,
    const ainekio_pca_port_t *port, const ainekio_pca_config_t *config);
/* Capture generation when authorizing work. A later disable invalidates even
 * work which has not entered the driver yet, including queued recovery. */
ainekio_pca_result_t ainekio_pca_recover(ainekio_pca9685_t *driver, uint64_t generation);
void ainekio_pca_verify_wiring(ainekio_pca9685_t *driver, bool verified);
ainekio_pca_result_t ainekio_pca_arm(ainekio_pca9685_t *driver, uint64_t generation,
    const uint16_t pulses_us[AINEKIO_PCA_BODY_CHANNELS]);
ainekio_pca_result_t ainekio_pca_write_frame(ainekio_pca9685_t *driver, uint64_t generation,
    const uint16_t pulses_us[AINEKIO_PCA_BODY_CHANNELS]);
void ainekio_pca_emergency_disable(ainekio_pca9685_t *driver, ainekio_pca_fault_t reason);
void ainekio_pca_disarm(ainekio_pca9685_t *driver);
void ainekio_pca_supervise(ainekio_pca9685_t *driver);
ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *driver);

#endif
