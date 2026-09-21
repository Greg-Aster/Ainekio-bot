#include "ainekio/pca9685.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    ainekio_pca9685_t driver;
    uint8_t registers[256];
    uint8_t write_regs[64];
    uint8_t write_values[64];
    size_t write_count;
    uint64_t now;
    unsigned calls, fail_at, interrupt_at, slow_at;
    unsigned enables, lock_depth;
    bool disabled;
    bool corrupt_readback;
    ainekio_pca_result_t recovery_while_outstanding;
    ainekio_pca_result_t arm_while_outstanding;
} fixture_t;

static void enter(void *p) { fixture_t *f = p; assert(f->lock_depth++ == 0); }
static void leave(void *p) { fixture_t *f = p; assert(--f->lock_depth == 0); }
static void disable(void *p, bool disabled)
{
    fixture_t *f = p;
    f->disabled = disabled;
    if (!disabled) {
        assert(f->lock_depth == 1);
        ++f->enables;
    }
}
static uint64_t now(void *p) { return ((fixture_t *)p)->now; }
static void delay(void *p, uint32_t us) { ((fixture_t *)p)->now += us; }

static bool bus_call(fixture_t *f, uint32_t timeout_ms)
{
    assert(f->lock_depth == 0); /* GPIO gate lock cannot span I2C. */
    assert(timeout_ms == 5U);
    ++f->calls;
    if (f->interrupt_at == f->calls) {
        uint16_t pulses[12] = {1500};
        ainekio_pca_emergency_disable(&f->driver, AINEKIO_PCA_FAULT_EMERGENCY);
        assert(f->disabled);
        f->recovery_while_outstanding = ainekio_pca_recover(&f->driver, ainekio_pca_status(&f->driver).generation);
        f->arm_while_outstanding = ainekio_pca_arm(&f->driver, ainekio_pca_status(&f->driver).generation, pulses);
    }
    if (f->slow_at == f->calls) {
        f->now += 6000U;
        ainekio_pca_supervise(&f->driver);
    } else f->now += 100U;
    return f->fail_at != f->calls;
}

static bool write_bytes(void *p, uint8_t reg, const uint8_t *bytes,
                        size_t count, uint32_t timeout_ms)
{
    fixture_t *f = p;
    assert((size_t)reg + count <= sizeof(f->registers));
    assert(f->write_count < sizeof(f->write_regs));
    f->write_regs[f->write_count] = reg;
    f->write_values[f->write_count++] = bytes[0];
    const bool ok = bus_call(f, timeout_ms);
    /* Even an interrupted transaction can still touch the peripheral. */
    memcpy(f->registers + reg, bytes, ok ? count : count / 2U);
    return ok;
}
static bool read_bytes(void *p, uint8_t reg, uint8_t *bytes,
                       size_t count, uint32_t timeout_ms)
{
    fixture_t *f = p;
    const bool ok = bus_call(f, timeout_ms);
    memcpy(bytes, f->registers + reg, count);
    if (reg == 0xFE && f->corrupt_readback) bytes[0] ^= 1;
    return ok;
}

static ainekio_pca_result_t initialize(fixture_t *f)
{
    const ainekio_pca_port_t port = {
        .context=f, .lock=enter, .unlock=leave, .disable_output=disable,
        .now_us=now, .sleep_us=delay, .read=read_bytes, .write=write_bytes,
    };
    const ainekio_pca_config_t config = {.oscillator_hz=25000000, .frequency_hz=50};
    return ainekio_pca_init(&f->driver, &port, &config);
}

static void test_initialization_and_frame(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    assert(f.disabled && f.enables == 0);
    const uint8_t regs[] = {0x00, 0x01, 0x06, 0xFE, 0x00, 0x00};
    const uint8_t values[] = {0x30, 0x04, 0x00, 121, 0x20, 0xA0};
    assert(f.write_count == sizeof(regs));
    assert(memcmp(f.write_regs, regs, sizeof(regs)) == 0);
    assert(memcmp(f.write_values, values, sizeof(values)) == 0);
    for (size_t i=0; i<16; ++i) assert(f.registers[6+4*i+3] == 0x10);
    uint16_t pulses[12] = {1500};
    pulses[11] = 1000;
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_WIRING);
    ainekio_pca_verify_wiring(&f.driver, true);
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    assert(!f.disabled && f.enables == 1);
    assert(f.registers[8] == (307 & 255) && f.registers[9] == 1);
    assert(f.registers[6+44+2] == 205 && f.registers[6+44+3] == 0);
    for (size_t i=12; i<16; ++i) assert(f.registers[6+4*i+3] == 0x10);
    const unsigned calls = f.calls;
    pulses[0] = UINT16_MAX;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_INVALID);
    assert(f.calls == calls);
    ainekio_pca_disarm(&f.driver);
    assert(f.disabled && !ainekio_pca_status(&f.driver).armed);
}

static void test_each_initialization_failure(void)
{
    fixture_t baseline = {0};
    assert(initialize(&baseline) == AINEKIO_PCA_OK);
    for (unsigned call=1; call<=baseline.calls; ++call) {
        fixture_t f = {.fail_at=call};
        assert(initialize(&f) == AINEKIO_PCA_IO);
        assert(f.disabled && f.enables == 0);
        const ainekio_pca_status_t s = ainekio_pca_status(&f.driver);
        assert(!s.ready && !s.armed && !s.in_flight && s.fault == AINEKIO_PCA_FAULT_IO);
    }
    fixture_t corrupt = {.corrupt_readback=true};
    assert(initialize(&corrupt) == AINEKIO_PCA_IO);
    assert(corrupt.disabled);
}

static void test_disable_during_arm_and_recovery(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    ainekio_pca_verify_wiring(&f.driver, true);
    uint16_t pulses[12] = {1500};
    f.interrupt_at = f.calls + 1;
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_STALE);
    assert(f.recovery_while_outstanding == AINEKIO_PCA_BUSY);
    assert(f.arm_while_outstanding == AINEKIO_PCA_BUSY);
    assert(f.disabled && f.enables == 0);
    assert(ainekio_pca_status(&f.driver).frames == 0);
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_DISARMED);
    /* Recovery itself can be interrupted; its late success cannot clear a latch. */
    f.interrupt_at = f.calls + 3;
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_STALE);
    assert(!ainekio_pca_status(&f.driver).ready && f.disabled);
    f.interrupt_at = 0;
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_OK);
    assert(f.disabled && f.enables == 0);
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    assert(f.enables == 1);
}

static void test_failed_frame_and_progress_deadline(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    ainekio_pca_verify_wiring(&f.driver, true);
    uint16_t pulses[12] = {1500};
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    f.fail_at = f.calls + 1;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_IO);
    assert(f.disabled && ainekio_pca_status(&f.driver).frames == 1);
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_DISARMED);
    f.fail_at = 0;
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_OK);
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    f.now = ainekio_pca_status(&f.driver).last_frame_us + 39999;
    ainekio_pca_supervise(&f.driver);
    assert(!f.disabled);
    ++f.now;
    ainekio_pca_supervise(&f.driver);
    assert(f.disabled && ainekio_pca_status(&f.driver).fault == AINEKIO_PCA_FAULT_PROGRESS);
}

static void test_hung_transfer_and_stale_frame(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    ainekio_pca_verify_wiring(&f.driver, true);
    uint16_t pulses[12] = {1500};
    f.slow_at = f.calls + 1;
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_STALE);
    assert(f.disabled && f.enables == 0);
    assert(ainekio_pca_status(&f.driver).fault == AINEKIO_PCA_FAULT_DEADLINE);
    f.slow_at = 0;
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_OK);
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    f.interrupt_at = f.calls + 1;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_STALE);
    assert(f.disabled && ainekio_pca_status(&f.driver).frames == 1);
}

static void test_late_writer_cannot_hide_missed_progress(void)
{
    for (unsigned during_transfer = 0; during_transfer < 2; ++during_transfer) {
        fixture_t f = {0};
        assert(initialize(&f) == AINEKIO_PCA_OK);
        ainekio_pca_verify_wiring(&f.driver, true);
        uint16_t pulses[12] = {1500};
        const uint64_t generation = ainekio_pca_status(&f.driver).generation;
        assert(ainekio_pca_arm(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
        const ainekio_pca_status_t before = ainekio_pca_status(&f.driver);
        const unsigned calls = f.calls;
        /* Do not run the supervisor: a writer resuming between guard ticks
         * must detect both an already missed deadline and one crossed in I2C. */
        f.now = before.last_frame_us + AINEKIO_PCA_PROGRESS_LIMIT_US - (during_transfer ? 50U : 0U);
        assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_DEADLINE);
        const ainekio_pca_status_t after = ainekio_pca_status(&f.driver);
        assert(f.disabled && after.fault == AINEKIO_PCA_FAULT_PROGRESS);
        assert(after.frames == before.frames && after.last_frame_us == before.last_frame_us);
        assert(f.calls == calls + during_transfer);
        assert(!after.in_flight);
        assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_STALE);
    }
}

int main(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    const uint64_t queued = ainekio_pca_status(&f.driver).generation;
    ainekio_pca_emergency_disable(&f.driver, AINEKIO_PCA_FAULT_EMERGENCY);
    const unsigned before = f.calls;
    assert(ainekio_pca_recover(&f.driver, queued) == AINEKIO_PCA_STALE);
    uint16_t pulses[12] = {1500};
    assert(ainekio_pca_arm(&f.driver, queued, pulses) == AINEKIO_PCA_STALE);
    assert(f.calls == before && f.disabled); /* Queued work cannot start after disable. */
    f.registers[0] = 0x40; /* Unknown sticky external clock requires power/reset repair. */
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_IO);
    assert(f.disabled && !ainekio_pca_status(&f.driver).ready);
    test_initialization_and_frame();
    test_each_initialization_failure();
    test_disable_during_arm_and_recovery();
    test_failed_frame_and_progress_deadline();
    test_hung_transfer_and_stale_frame();
    test_late_writer_cannot_hide_missed_progress();
    puts("PCA9685: initialization, frames, failures, generation races, recovery and deadline tests passed");
    return 0;
}
