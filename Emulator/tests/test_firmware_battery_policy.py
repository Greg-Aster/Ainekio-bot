from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "src"
    / "runtime_service.c"
)


class FirmwareBatteryPolicyTests(unittest.TestCase):
    def test_battery_dispatch_is_warning_only(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        dispatch = source.split("static void dispatch_battery(", 1)[1].split(
            "static void dispatch_sd(", 1
        )[0]

        self.assertIn("AINEKIO_POWER_NORMAL", dispatch)
        self.assertIn("AINEKIO_EVENT_BATTERY_WARN", dispatch)
        self.assertIn("CONTROLLER ONLINE", dispatch)
        self.assertNotIn("AINEKIO_POWER_MOVE_LOCKED", dispatch)
        self.assertNotIn("AINEKIO_POWER_CUTOFF", dispatch)
        self.assertNotIn("AINEKIO_STATE_DEEP_SLEEP", dispatch)
        self.assertNotIn("AINEKIO_EVENT_BATTERY_CUTOFF", dispatch)
        self.assertNotIn("ainekio_sleep_enter", dispatch)
        self.assertNotIn("TX_CLOSE", dispatch)


if __name__ == "__main__":
    unittest.main()
