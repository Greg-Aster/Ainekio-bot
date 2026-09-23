#include "ainekio/pca9685.h"

#include <string.h>

#define MODE1 0x00U
#define MODE2 0x01U
#define LED0 0x06U
#define PRESCALE 0xFEU
#define AI 0x20U
#define SLEEP 0x10U
#define RESTART 0x80U

static void lock(ainekio_pca9685_t *d) { d->port.lock(d->port.context); }
static void unlock(ainekio_pca9685_t *d) { d->port.unlock(d->port.context); }

static void disable_locked(ainekio_pca9685_t *d, ainekio_pca_fault_t fault)
{
    d->port.disable_output(d->port.context, true);
    d->state.armed = false;
    ++d->state.generation;
    if (fault != AINEKIO_PCA_FAULT_NONE) {
        /* A caller's generic shutdown must not erase the bus/timing failure
         * that triggered it. A new recovery failure can replace that cause. */
        if (fault != AINEKIO_PCA_FAULT_EMERGENCY || d->state.fault == AINEKIO_PCA_FAULT_NONE)
            d->state.fault = fault;
        d->state.ready = false;
    }
    /* in_flight belongs to its original writer until that writer returns. */
}

void ainekio_pca_emergency_disable(ainekio_pca9685_t *d, ainekio_pca_fault_t reason)
{
    lock(d);
    disable_locked(d, reason == AINEKIO_PCA_FAULT_NONE ? AINEKIO_PCA_FAULT_EMERGENCY : reason);
    unlock(d);
}

void ainekio_pca_disarm(ainekio_pca9685_t *d)
{
    lock(d);
    disable_locked(d, AINEKIO_PCA_FAULT_NONE);
    unlock(d);
}

ainekio_pca_status_t ainekio_pca_status(ainekio_pca9685_t *d)
{
    lock(d);
    const ainekio_pca_status_t result = d->state;
    unlock(d);
    return result;
}

/* Only one transaction owner; the safety gate never waits for that owner. */
static ainekio_pca_result_t begin(ainekio_pca9685_t *d, uint64_t expected, bool recovery,
                                bool arm, uint64_t *generation)
{
    lock(d);
    ainekio_pca_result_t result = AINEKIO_PCA_OK;
    if (d->state.generation != expected) result = AINEKIO_PCA_STALE;
    else if (d->state.in_flight) result = AINEKIO_PCA_BUSY;
    else if (recovery && d->state.armed) result = AINEKIO_PCA_BUSY;
    else if (!recovery && (!d->state.ready || d->state.fault != AINEKIO_PCA_FAULT_NONE))
        result = AINEKIO_PCA_DISARMED;
    else if (!recovery && d->state.armed == arm) result = AINEKIO_PCA_DISARMED;
    else if (!recovery && !arm &&
             d->port.now_us(d->port.context) - d->state.last_frame_us >= AINEKIO_PCA_PROGRESS_LIMIT_US) {
        /* A resumed writer must not hide a missed deadline before the next
         * supervisor tick. Recovery always requires a separate request. */
        disable_locked(d, AINEKIO_PCA_FAULT_PROGRESS);
        result = AINEKIO_PCA_DEADLINE;
    }
    if (result == AINEKIO_PCA_OK) {
        d->state.in_flight = true;
        *generation = d->state.generation;
    }
    unlock(d);
    return result;
}

static ainekio_pca_result_t transfer(ainekio_pca9685_t *d, uint64_t generation,
                                    bool read, uint8_t reg, uint8_t *bytes, size_t count)
{
    lock(d);
    if (generation != d->state.generation) {
        unlock(d);
        return AINEKIO_PCA_STALE;
    }
    const uint64_t started = d->port.now_us(d->port.context);
    d->state.io_started_us = started;
    d->state.io_pending = true;
    unlock(d);
    const bool ok = read
        ? d->port.read(d->port.context, reg, bytes, count, 5U)
        : d->port.write(d->port.context, reg, bytes, count, 5U);
    lock(d);
    d->state.io_pending = false;
    ainekio_pca_result_t result = AINEKIO_PCA_OK;
    if (generation != d->state.generation) result = AINEKIO_PCA_STALE;
    else if (d->port.now_us(d->port.context) - started > AINEKIO_PCA_IO_BUDGET_US) {
        disable_locked(d, AINEKIO_PCA_FAULT_DEADLINE);
        result = AINEKIO_PCA_DEADLINE;
    } else if (!ok) {
        disable_locked(d, AINEKIO_PCA_FAULT_IO);
        result = AINEKIO_PCA_IO;
    }
    unlock(d);
    return result;
}

static ainekio_pca_result_t finish(ainekio_pca9685_t *d, uint64_t generation,
                                  ainekio_pca_result_t result, bool recovery, bool arm)
{
    lock(d);
    if (result == AINEKIO_PCA_OK && generation != d->state.generation)
        result = AINEKIO_PCA_STALE;
    if (result == AINEKIO_PCA_OK && !recovery && !arm &&
        d->port.now_us(d->port.context) - d->state.last_frame_us >= AINEKIO_PCA_PROGRESS_LIMIT_US) {
        disable_locked(d, AINEKIO_PCA_FAULT_PROGRESS);
        result = AINEKIO_PCA_DEADLINE;
    }
    if (result == AINEKIO_PCA_OK) {
        if (recovery) {
            d->state.ready = true;
            d->state.fault = AINEKIO_PCA_FAULT_NONE;
        } else {
            d->state.last_frame_us = d->port.now_us(d->port.context);
            ++d->state.frames;
            if (arm) {
                d->state.armed = true;
                d->port.disable_output(d->port.context, false);
            }
        }
    }
    d->state.in_flight = false;
    unlock(d);
    return result;
}

ainekio_pca_result_t ainekio_pca_recover(ainekio_pca9685_t *d, uint64_t expected)
{
    uint64_t generation = 0;
    ainekio_pca_result_t result = begin(d, expected, true, false, &generation);
    if (result != AINEKIO_PCA_OK) return result;
    uint8_t mode = 0;
    result = transfer(d, generation, true, MODE1, &mode, 1U);
    /* EXTCLK is sticky until power-on reset/software reset. Never treat an
     * unknown external clock as the configured internal oscillator. */
    if (result == AINEKIO_PCA_OK && (mode & 0x40U)) {
        ainekio_pca_emergency_disable(d, AINEKIO_PCA_FAULT_IO);
        result = AINEKIO_PCA_IO;
    }
    uint8_t value = AI | SLEEP;
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, false, MODE1, &value, 1U);
    value = 0x04U; /* Totem pole, non-inverted, update on STOP, OE high -> low. */
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, false, MODE2, &value, 1U);
    uint8_t off[4U * AINEKIO_PCA_CHANNELS] = {0};
    for (size_t i = 0; i < AINEKIO_PCA_CHANNELS; ++i) off[4U * i + 3U] = 0x10U;
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, false, LED0, off, sizeof(off));
    value = d->prescale;
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, false, PRESCALE, &value, 1U);
    value = AI;
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, false, MODE1, &value, 1U);
    if (result == AINEKIO_PCA_OK) d->port.sleep_us(d->port.context, 500U);
    value = AI | RESTART;
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, false, MODE1, &value, 1U);
    uint8_t prescale = 0;
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, true, PRESCALE, &prescale, 1U);
    if (result == AINEKIO_PCA_OK && prescale != d->prescale) {
        ainekio_pca_emergency_disable(d, AINEKIO_PCA_FAULT_IO);
        result = AINEKIO_PCA_IO;
    }
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, true, MODE1, &mode, 1U);
    if (result == AINEKIO_PCA_OK && (mode & 0x7FU) != AI) {
        ainekio_pca_emergency_disable(d, AINEKIO_PCA_FAULT_IO);
        result = AINEKIO_PCA_IO;
    }
    if (result == AINEKIO_PCA_OK) result = transfer(d, generation, true, MODE2, &mode, 1U);
    if (result == AINEKIO_PCA_OK && mode != 0x04U) {
        ainekio_pca_emergency_disable(d, AINEKIO_PCA_FAULT_IO);
        result = AINEKIO_PCA_IO;
    }
    return finish(d, generation, result, true, false);
}

ainekio_pca_result_t ainekio_pca_init(ainekio_pca9685_t *d,
    const ainekio_pca_port_t *port, const ainekio_pca_config_t *config)
{
    if (!d || !port || !config || !port->lock || !port->unlock || !port->disable_output ||
        !port->now_us || !port->sleep_us || !port->read || !port->write)
        return AINEKIO_PCA_INVALID;
    *d = (ainekio_pca9685_t){.port = *port, .config = *config};
    port->disable_output(port->context, true);
    if (config->frequency_hz == 0 || config->oscillator_hz == 0) return AINEKIO_PCA_INVALID;
    const uint64_t divisor = UINT64_C(4096) * config->frequency_hz;
    const uint64_t divider = ((uint64_t)config->oscillator_hz + divisor / 2U) / divisor;
    if (divider < 4U || divider > 256U) return AINEKIO_PCA_INVALID;
    d->prescale = (uint8_t)(divider - 1U);
    return ainekio_pca_recover(d, 0);
}

static uint64_t pulse_ticks(const ainekio_pca9685_t *d, uint16_t pulse_us)
{
    const uint64_t denominator = UINT64_C(1000000) * (d->prescale + 1U);
    return ((uint64_t)pulse_us * d->config.oscillator_hz + denominator / 2U) / denominator;
}

bool ainekio_pca_pulse_bounds(const ainekio_pca9685_t *d,
    uint16_t *minimum_us, uint16_t *maximum_us)
{
    if (!d || !minimum_us || !maximum_us || !d->config.oscillator_hz) return false;
    const uint64_t denominator = UINT64_C(1000000) * (d->prescale + 1U);
    const uint64_t oscillator = d->config.oscillator_hz;
    const uint64_t minimum = (denominator - denominator / 2U + oscillator - 1U) / oscillator;
    uint64_t maximum = (UINT64_C(4096) * denominator - denominator / 2U - 1U) / oscillator;
    if (maximum > UINT16_MAX) maximum = UINT16_MAX;
    if (minimum > maximum) return false;
    *minimum_us = (uint16_t)minimum;
    *maximum_us = (uint16_t)maximum;
    return true;
}

bool ainekio_pca_pulse_valid(const ainekio_pca9685_t *d, uint16_t pulse_us)
{
    if (!d || !pulse_us || !d->config.oscillator_hz) return false;
    const uint64_t ticks = pulse_ticks(d, pulse_us);
    return ticks > 0 && ticks < 4096U;
}

static ainekio_pca_result_t frame(ainekio_pca9685_t *d, uint64_t expected,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS], bool arm)
{
    if (!pulses) return AINEKIO_PCA_INVALID;
    uint8_t bytes[4U * AINEKIO_PCA_CHANNELS] = {0};
    for (size_t i = 0; i < AINEKIO_PCA_CHANNELS; ++i) {
        if (i >= AINEKIO_PCA_BODY_CHANNELS || pulses[i] == 0) {
            bytes[4U * i + 3U] = 0x10U;
            continue;
        }
        const uint64_t ticks = pulse_ticks(d, pulses[i]);
        if (ticks == 0 || ticks >= 4096U) return AINEKIO_PCA_INVALID;
        bytes[4U * i + 2U] = (uint8_t)ticks;
        bytes[4U * i + 3U] = (uint8_t)(ticks >> 8U);
    }
    uint64_t generation = 0;
    ainekio_pca_result_t result = begin(d, expected, false, arm, &generation);
    if (result != AINEKIO_PCA_OK) return result;
    result = transfer(d, generation, false, LED0, bytes, sizeof(bytes));
    return finish(d, generation, result, false, arm);
}

ainekio_pca_result_t ainekio_pca_arm(ainekio_pca9685_t *d, uint64_t generation,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]) { return frame(d, generation, pulses, true); }

ainekio_pca_result_t ainekio_pca_write_frame(ainekio_pca9685_t *d, uint64_t generation,
    const uint16_t pulses[AINEKIO_PCA_BODY_CHANNELS]) { return frame(d, generation, pulses, false); }

void ainekio_pca_supervise(ainekio_pca9685_t *d)
{
    lock(d);
    const uint64_t now = d->port.now_us(d->port.context);
    if (d->state.io_pending && d->state.fault == AINEKIO_PCA_FAULT_NONE &&
        now - d->state.io_started_us >= AINEKIO_PCA_IO_BUDGET_US)
        disable_locked(d, AINEKIO_PCA_FAULT_DEADLINE);
    else if (d->state.armed && now - d->state.last_frame_us >= AINEKIO_PCA_PROGRESS_LIMIT_US)
        disable_locked(d, AINEKIO_PCA_FAULT_PROGRESS);
    unlock(d);
}
