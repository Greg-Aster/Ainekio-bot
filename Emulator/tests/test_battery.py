from __future__ import annotations

import unittest

from emulator.body.battery import BatteryMonitor, BatteryState


class BatteryMonitorTests(unittest.TestCase):
    def test_sample_sets_are_bounded_and_thresholds_need_three_readings(self) -> None:
        monitor = BatteryMonitor()

        with self.assertRaises(ValueError):
            monitor.observe([6.9] * 15)

        self.assertEqual(monitor.observe([6.9] * 16).events, ())
        self.assertEqual(monitor.observe([6.9] * 16).events, ())
        update = monitor.observe([6.9] * 16)

        self.assertEqual(update.events, ("battery_warn",))
        self.assertEqual(update.state, BatteryState.MOVE_LOCKED)
        self.assertEqual(update.volts, 6.9)

    def test_cutoff_emits_each_crossing_once_and_recovers_at_7_2(self) -> None:
        monitor = BatteryMonitor()

        for _ in range(2):
            self.assertEqual(monitor.observe_constant(6.7).events, ())
        cutoff = monitor.observe_constant(6.7)
        self.assertEqual(cutoff.events, ("battery_warn", "battery_cutoff"))
        self.assertEqual(cutoff.state, BatteryState.CUTOFF)
        self.assertEqual(monitor.observe_constant(6.7).events, ())

        self.assertEqual(monitor.observe_constant(7.2).events, ())
        self.assertEqual(monitor.observe_constant(7.2).events, ())
        recovered = monitor.observe_constant(7.2)
        self.assertEqual(recovered.events, ("brownout_recovered",))
        self.assertEqual(recovered.state, BatteryState.NORMAL)


if __name__ == "__main__":
    unittest.main()
