from __future__ import annotations

import unittest

from emulator.faults import EmulatorFaultController, FaultControlServer


class EmulatorFaultControllerTests(unittest.TestCase):
    def test_one_shot_and_persistent_faults_are_bounded(self) -> None:
        faults = EmulatorFaultController(battery_volts=8.0)
        faults.set_battery(6.9)
        faults.set_control_stall(250)
        faults.set_speaker_delay(75)
        faults.request_drop_link()
        faults.request_oversize_camera()
        faults.request_malformed_control()

        snapshot = faults.snapshot()
        self.assertEqual(snapshot.battery_volts, 6.9)
        self.assertEqual(snapshot.control_stall_ms, 250)
        self.assertEqual(snapshot.speaker_delay_ms, 75)
        self.assertTrue(faults.take_drop_link())
        self.assertFalse(faults.take_drop_link())
        self.assertTrue(faults.take_oversize_camera())
        self.assertFalse(faults.take_oversize_camera())
        self.assertTrue(faults.take_malformed_control())
        self.assertFalse(faults.take_malformed_control())

        with self.assertRaises(ValueError):
            faults.set_control_stall(30001)
        with self.assertRaises(ValueError):
            faults.set_speaker_delay(-1)
        with self.assertRaises(ValueError):
            faults.set_battery(21.0)

    def test_fault_server_refuses_non_loopback_bind(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            FaultControlServer(("0.0.0.0", 0), EmulatorFaultController())


if __name__ == "__main__":
    unittest.main()
