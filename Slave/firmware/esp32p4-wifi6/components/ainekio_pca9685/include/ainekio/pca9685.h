#ifndef AINEKIO_PCA9685_H
#define AINEKIO_PCA9685_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AINEKIO_PCA_CHANNELS 16U
#define AINEKIO_PCA_BODY_CHANNELS 12U
#define AINEKIO_PCA_IO_BUDGET_US UINT64_C(5000)

typedef enum {
    AINEKIO_PCA_OK = 0,
    AINEKIO_PCA_INVALID,
    AINEKIO_PCA_IO,
    AINEKIO_PCA_BUSY,
    AINEKIO_PCA_DISARMED,
    AINEKIO_PCA_STALE,
    AINEKIO_PCA_DEADLINE,
    AINEKIO_PCA_TIMEOUT,
} ainekio_pca_result_t;

typedef enum {
    AINEKIO_PCA_BUS_OK,
    AINEKIO_PCA_BUS_ERROR,
    AINEKIO_PCA_BUS_TIMEOUT,
} ainekio_pca_bus_result_t;

typedef enum {
    AINEKIO_PCA_FAULT_NONE = 0,
    AINEKIO_PCA_FAULT_EMERGENCY,
    AINEKIO_PCA_FAULT_IO,
    AINEKIO_PCA_FAULT_DEADLINE,
    AINEKIO_PCA_FAULT_PROGRESS,
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
    ainekio_pca_bus_result_t (*write)(void *context, uint8_t reg, const uint8_t *data,
                  size_t length, uint32_t timeout_ms);
    ainekio_pca_bus_result_t (*read)(void *context, uint8_t reg, uint8_t *data,
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
    uint64_t last_io_us, max_io_us;
    uint32_t io_transfers, io_failures;
    uint32_t frames;
    ainekio_pca_fault_t fault;
    bool ready;
    bool armed;
    bool in_flight;
    bool io_pending;
} ainekio_pca_status_t;

typedef struct {
    ainekio_pca_port_t port;
    ainekio_pca_config_t config;
    ainekio_pca_status_t state;
    uint8_t prescale;
} ainekio_pca9685_t;

/* Pure timer conversion shared with offline physical replay. These routines
 * do no I/O and do not arm outputs. The oscillator is configured, not measured. */
bool ainekio_pca_config_prescale(const ainekio_pca_config_t *config, uint8_t *prescale);
uint64_t ainekio_pca_pulse_ticks(const ainekio_pca9685_t *driver, uint16_t pulse_us);
/* Body output channel 0..11; same stagger used by the frame writer. */
uint16_t ainekio_pca_channel_phase(unsigned channel);

ainekio_pca_result_t ainekio_pca_init(ainekio_pca9685_t *driver,
    const ainekio_pca_port_t *port, const ainekio_pca_config_t *config);
/* Integer pulse requests that round to 1..4095 counter ticks. These are timer
 * capabilities, not servo travel limits; zero is reserved for disabled output. */
bool ainekio_pca_pulse_bounds(const ainekio_pca9685_t *driver,
    uint16_t *minimum_us, uint16_t *maximum_us);
bool ainekio_pca_pulse_valid(const ainekio_pca9685_t *driver, uint16_t pulse_us);
/* Capture generation when authorizing work. Explicit disarm/fault invalidates even
 * work which has not entered the driver yet, including queued recovery. */
ainekio_pca_result_t ainekio_pca_recover(ainekio_pca9685_t *driver, uint64_t generation);
ainekio_pca_result_t ainekio_pca_arm(ainekio_pca9685_t *driver, uint64_t generation,
    const uint16_t pulses_us[AINEKIO_PCA_BODY_CHANNELS]);
ainekio_pca_result_t ainekio_pca_write_frame(ainekio_pca9685_t *driver, uint64_t generation,
    const uint16_t pulses_us[AINEKIO_PCA_BODY_CHANNELS]);
void ainekio_pca_emergency_disable(ainekio_pca9685_t *driver, ainekio_pca_fault_t reason);
void ainekio_pca_disarm(ainekio_pca9685_t *driver);
/* Sole output owner: release OE after a completed operation, outside a transfer.
 * This is normal idle, not cancellation: already-admitted commands retain their
 * generation and may arm outputs. Explicit disarm/fault still invalidates them. */
void ainekio_pca_idle(ainekio_pca9685_t *driver);
ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *driver);

#endif
