"""Exercise production ADC scheduling across flash stalls and tick wrap."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FeedbackCadenceTests(unittest.TestCase):
    def test_missed_scans_do_not_replay_and_starve_storage(self):
        source = (ROOT / "Slave/firmware/esp32p4-wifi6/main/servo_feedback.c").read_text()
        start = source.index("static void wait_for_next_scan(")
        function = source[start:source.index("\n}", start) + 2]
        harness = r'''
#include <assert.h>
#include <stdint.h>
typedef uint32_t TickType_t;
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))
static TickType_t now, blocked;
static TickType_t xTaskGetTickCount(void) { return now; }
static void vTaskDelayUntil(TickType_t *previous, TickType_t period)
{
    TickType_t target = *previous + period;
    /* The scenarios span less than half the tick counter. */
    blocked = (int32_t)(target - now) > 0 ? target - now : 0;
    now += blocked;
    *previous = target;
}
''' + function + r'''
int main(void)
{
    TickType_t phase = 0;
    /* Normal measured ~14 ms scans retain 50 Hz without accumulating drift. */
    for (unsigned i=0; i<100; ++i) {
        now += 14;
        wait_for_next_scan(&phase);
        assert(blocked == 6 && now == (i+1)*20);
    }
    /* A flash stall must not cause thousands of back-to-back ADC scans. The
     * worker becomes runnable at this first wait, within one normal period. */
    now += 35013;
    wait_for_next_scan(&phase);
    assert(blocked == 7 && now == 37020 && phase == now);
    now += 14;
    wait_for_next_scan(&phase);
    assert(blocked == 6 && now == 37040);
    /* Exact boundaries and repeated slow scans also cannot build up debt. */
    for (unsigned i=0; i<100; ++i) {
        now += 40;
        wait_for_next_scan(&phase);
        assert(blocked == 20 && phase == now);
    }
    phase = UINT32_MAX - 9;
    now = phase + 14;
    wait_for_next_scan(&phase);
    assert(blocked == 6 && now == 10 && phase == now);
    phase = UINT32_MAX - 9;
    now = phase + 35013;
    wait_for_next_scan(&phase);
    assert(blocked == 7 && now == 35010 && phase == now);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ainekio-feedback-cadence-") as directory:
            path = Path(directory)
            (path / "cadence.c").write_text(harness)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(path / "cadence.c"), "-o", str(path / "cadence")], check=True)
            subprocess.run([str(path / "cadence")], check=True)
