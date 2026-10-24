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
    unsigned calls, fail_at, interrupt_at, slow_at, timeout_at;
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

static ainekio_pca_bus_result_t bus_call(fixture_t *f, uint32_t timeout_ms)
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
    } else f->now += 100U;
    return f->timeout_at == f->calls ? AINEKIO_PCA_BUS_TIMEOUT :
        f->fail_at == f->calls ? AINEKIO_PCA_BUS_ERROR : AINEKIO_PCA_BUS_OK;
}

static ainekio_pca_bus_result_t write_bytes(void *p, uint8_t reg, const uint8_t *bytes,
                        size_t count, uint32_t timeout_ms)
{
    fixture_t *f = p;
    assert((size_t)reg + count <= sizeof(f->registers));
    assert(f->write_count < sizeof(f->write_regs));
    f->write_regs[f->write_count] = reg;
    f->write_values[f->write_count++] = bytes[0];
    const ainekio_pca_bus_result_t result = bus_call(f, timeout_ms);
    /* Even an interrupted transaction can still touch the peripheral. */
    memcpy(f->registers + reg, bytes, result == AINEKIO_PCA_BUS_OK ? count : count / 2U);
    return result;
}
static ainekio_pca_bus_result_t read_bytes(void *p, uint8_t reg, uint8_t *bytes,
                       size_t count, uint32_t timeout_ms)
{
    fixture_t *f = p;
    const ainekio_pca_bus_result_t result = bus_call(f, timeout_ms);
    memcpy(bytes, f->registers + reg, count);
    if (reg == 0xFE && f->corrupt_readback) bytes[0] ^= 1;
    return result;
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
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    assert(!f.disabled && f.enables == 1);
    assert(f.registers[8] == (307 & 255) && f.registers[9] == 1);
    assert(f.registers[6+44] == (3754 & 255) && f.registers[6+44+1] == (3754 >> 8));
    assert(f.registers[6+44+2] == (3959 & 255) && f.registers[6+44+3] == (3959 >> 8));
    for (size_t i=12; i<16; ++i) assert(f.registers[6+4*i+3] == 0x10);
    const unsigned calls = f.calls;
    pulses[0] = UINT16_MAX;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_INVALID);
    assert(f.calls == calls);
    for(unsigned pass=0;pass<3;pass++) {
        const uint16_t widths[]={400,1500,2900};
        for(unsigned i=0;i<12;i++)pulses[i]=widths[pass];
        const unsigned before=f.calls;
        assert(ainekio_pca_write_frame(&f.driver,ainekio_pca_status(&f.driver).generation,pulses)==AINEKIO_PCA_OK);
        assert(f.calls==before+1); /* One frame transfer, no sleeps between channels. */
        unsigned previous=0;
        for(unsigned i=0;i<12;i++) {
            const unsigned reg=6+4*i;
            const unsigned on=f.registers[reg]+256U*f.registers[reg+1];
            const unsigned off=f.registers[reg+2]+256U*f.registers[reg+3];
            const unsigned width=(off+4096U-on)%4096U;
            assert(on<4096 && off<4096 && (!i || on>previous));
            if(i)assert(on-previous==341 || on-previous==342);
            /* Independently expected widths at 25MHz / (121+1). */
            assert(width==(pass==0?82U:pass==1?307U:594U));
            previous=on;
        }
        if(pass==2)assert(f.registers[6+44+3]<f.registers[6+44+1]); /* Counter wrap. */
        for(unsigned i=12;i<16;i++)assert(f.registers[6+4*i+3]==0x10);
    }
    pulses[5]=0;
    assert(ainekio_pca_write_frame(&f.driver,ainekio_pca_status(&f.driver).generation,pulses)==AINEKIO_PCA_OK);
    assert(f.registers[6+4*5+3]==0x10); /* Individual detach remains full-off. */
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

static void test_failed_frame_and_delayed_progress(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    uint16_t pulses[12] = {1500};
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    f.fail_at = f.calls + 1;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_IO);
    assert(f.disabled && ainekio_pca_status(&f.driver).frames == 1);
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_DISARMED);
    f.fail_at = 0;
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_OK);
    assert(ainekio_pca_arm(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    f.now += 1000000;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_OK);
    assert(!f.disabled && ainekio_pca_status(&f.driver).fault == AINEKIO_PCA_FAULT_NONE);
}

static void test_slow_transfer_timeout_and_explicit_stop(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    uint16_t pulses[12] = {1500};
    f.slow_at = f.calls + 1;
    const uint64_t generation = ainekio_pca_status(&f.driver).generation;
    assert(ainekio_pca_arm(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
    assert(!f.disabled && f.enables == 1);
    assert(ainekio_pca_status(&f.driver).fault == AINEKIO_PCA_FAULT_NONE);
    const ainekio_pca_status_t measured = ainekio_pca_status(&f.driver);
    assert(measured.last_io_us == 6000U && measured.max_io_us == 6000U);
    assert(measured.io_transfers == f.calls && measured.io_failures == 0U);
    f.slow_at = 0;
    f.timeout_at = f.calls + 1;
    assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_TIMEOUT);
    const ainekio_pca_status_t timed_out = ainekio_pca_status(&f.driver);
    assert(!f.disabled && timed_out.armed && timed_out.generation == generation);
    assert(timed_out.frames == measured.frames && timed_out.last_frame_us == measured.last_frame_us);
    assert(timed_out.io_failures == 1 && !timed_out.in_flight);
    assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
    f.interrupt_at = f.calls + 1;
    assert(ainekio_pca_write_frame(&f.driver, ainekio_pca_status(&f.driver).generation, pulses) == AINEKIO_PCA_STALE);
    assert(f.disabled && ainekio_pca_status(&f.driver).frames == 2);
}

static void test_shutdown_preserves_fault_cause(void)
{
    for (unsigned fault=AINEKIO_PCA_FAULT_IO; fault<=AINEKIO_PCA_FAULT_PROGRESS; ++fault) {
        fixture_t f = {0};
        assert(initialize(&f) == AINEKIO_PCA_OK);
        ainekio_pca_emergency_disable(&f.driver, (ainekio_pca_fault_t)fault);
        const uint64_t generation = ainekio_pca_status(&f.driver).generation;
        ainekio_pca_emergency_disable(&f.driver, AINEKIO_PCA_FAULT_EMERGENCY);
        const ainekio_pca_status_t status = ainekio_pca_status(&f.driver);
        assert(status.fault == (ainekio_pca_fault_t)fault && status.generation > generation && f.disabled);
        assert(ainekio_pca_recover(&f.driver, status.generation) == AINEKIO_PCA_OK);
        assert(ainekio_pca_status(&f.driver).fault == AINEKIO_PCA_FAULT_NONE);
    }
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    ainekio_pca_emergency_disable(&f.driver, AINEKIO_PCA_FAULT_EMERGENCY);
    f.fail_at = f.calls + 1;
    assert(ainekio_pca_recover(&f.driver, ainekio_pca_status(&f.driver).generation) == AINEKIO_PCA_IO);
    assert(ainekio_pca_status(&f.driver).fault == AINEKIO_PCA_FAULT_IO);
}

static void test_late_writer_resumes(void)
{
    const uint64_t gaps[] = {39950, 40000, 40001, 1000000, 60000000};
    for (unsigned i = 0; i < sizeof(gaps)/sizeof(gaps[0]); ++i) {
        fixture_t f = {0};
        assert(initialize(&f) == AINEKIO_PCA_OK);
        uint16_t pulses[12] = {1500};
        const uint64_t generation = ainekio_pca_status(&f.driver).generation;
        assert(ainekio_pca_arm(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
        const ainekio_pca_status_t before = ainekio_pca_status(&f.driver);
        const unsigned calls = f.calls;
        f.now = before.last_frame_us + gaps[i];
        assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
        const ainekio_pca_status_t after = ainekio_pca_status(&f.driver);
        assert(!f.disabled && after.fault == AINEKIO_PCA_FAULT_NONE);
        assert(after.frames == before.frames + 1 && after.last_frame_us == f.now);
        assert(after.generation == generation && f.calls == calls + 1 && !after.in_flight);
    }
}

static void test_hardware_pulse_bounds(void)
{
    fixture_t f = {0};
    assert(initialize(&f) == AINEKIO_PCA_OK);
    uint16_t minimum, maximum;
    assert(ainekio_pca_pulse_bounds(&f.driver, &minimum, &maximum));
    assert(minimum == 3 && maximum == 19986);
    uint16_t pulses[12] = {3000};
    const uint64_t generation = ainekio_pca_status(&f.driver).generation;
    assert(ainekio_pca_arm(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
    assert((f.registers[8] | (f.registers[9] << 8U)) == 615);
    pulses[0] = minimum;
    assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
    assert(f.registers[8] == 1 && f.registers[9] == 0);
    pulses[0] = maximum;
    assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_OK);
    assert(f.registers[8] == 255 && f.registers[9] == 15);
    const unsigned before = f.calls;
    pulses[0] = maximum + 1;
    assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_INVALID);
    pulses[0] = minimum - 1;
    assert(ainekio_pca_write_frame(&f.driver, generation, pulses) == AINEKIO_PCA_INVALID);
    assert(f.calls == before && !f.disabled);
    const uint32_t oscillators[] = {25000000, 26000000, 1000000};
    const uint8_t prescales[] = {3, 121, 255};
    for (size_t o=0; o<3; ++o) for (size_t p=0; p<3; ++p) {
        f.driver.config.oscillator_hz = oscillators[o];
        f.driver.prescale = prescales[p];
        assert(ainekio_pca_pulse_bounds(&f.driver, &minimum, &maximum));
        for (uint32_t pulse=0; pulse<=UINT16_MAX; ++pulse)
            assert(ainekio_pca_pulse_valid(&f.driver, (uint16_t)pulse) ==
                   (pulse >= minimum && pulse <= maximum));
    }
    f.driver.config.oscillator_hz = 0;
    assert(!ainekio_pca_pulse_bounds(&f.driver, &minimum, &maximum));
    assert(!ainekio_pca_pulse_valid(&f.driver, 1500));
}

static void test_idle_release_keeps_admitted_commands(void)
{
    fixture_t f={0};assert(initialize(&f)==AINEKIO_PCA_OK);
    const uint64_t admitted=ainekio_pca_status(&f.driver).generation;
    uint16_t pulses[12]={1500};
    assert(ainekio_pca_arm(&f.driver,admitted,pulses)==AINEKIO_PCA_OK);
    ainekio_pca_idle(&f.driver);
    const ainekio_pca_status_t idle=ainekio_pca_status(&f.driver);
    assert(f.disabled && !idle.armed && idle.ready && idle.generation==admitted);
    assert(ainekio_pca_arm(&f.driver,admitted,pulses)==AINEKIO_PCA_OK);
    assert(!f.disabled && ainekio_pca_status(&f.driver).armed);
    ainekio_pca_disarm(&f.driver);
    assert(ainekio_pca_arm(&f.driver,admitted,pulses)==AINEKIO_PCA_STALE);
}

int main(void)
{
    test_idle_release_keeps_admitted_commands();
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
    test_failed_frame_and_delayed_progress();
    test_slow_transfer_timeout_and_explicit_stop();
    test_shutdown_preserves_fault_cause();
    test_late_writer_resumes();
    test_hardware_pulse_bounds();
    puts("PCA9685: initialization, frames, failures, generation races, recovery, timeout and delayed-resumption tests passed");
    return 0;
}
