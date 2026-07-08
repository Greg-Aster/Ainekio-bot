from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("megameal_bridge.py")
SPEC = importlib.util.spec_from_file_location("megameal_bridge", MODULE_PATH)
assert SPEC is not None
megameal_bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(megameal_bridge)


class MegamealBridgeTests(unittest.TestCase):
    def test_walk_builds_submit_motion_event(self) -> None:
        event = megameal_bridge.build_motion_event("walk", issued_at_ms=1000)

        self.assertEqual(event["schemaVersion"], 1)
        self.assertEqual(event["robot"], "ainekio-sesame")
        self.assertEqual(event["command"], "walk")
        self.assertEqual(event["issuedAtMs"], 1000)
        self.assertGreater(len(event["frames"]), 0)
        self.assertEqual(
            {frame["servo"] for frame in event["frames"]},
            {"R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4"},
        )

    def test_rejects_unsupported_command(self) -> None:
        with self.assertRaises(ValueError):
            megameal_bridge.build_motion_event("R1=180", issued_at_ms=1000)

    def test_hardware_to_megameal_angle_conversion(self) -> None:
        self.assertEqual(
            megameal_bridge.hardware_servo_angle_to_megameal("R1", 72),
            -18,
        )
        self.assertEqual(
            megameal_bridge.hardware_servo_angle_to_megameal("L1", 108),
            -18,
        )
        self.assertEqual(
            megameal_bridge.hardware_servo_angle_to_megameal("R1", 180),
            60,
        )
        self.assertEqual(
            megameal_bridge.hardware_servo_angle_to_megameal("L1", 0),
            60,
        )

    def test_controller_command_uses_existing_bridge_shape(self) -> None:
        event = megameal_bridge.build_motion_event("stand", issued_at_ms=1000)
        message = megameal_bridge.build_controller_command(
            event,
            command_id="test-command",
            issued_at_ms=1000,
            target_session_id="game-a",
        )

        self.assertEqual(message["type"], "controller:command")
        self.assertEqual(message["command"]["type"], "submitMotionEvent")
        self.assertEqual(message["command"]["id"], "test-command")
        self.assertEqual(message["command"]["issuedAt"], 1000)
        self.assertEqual(message["command"]["targetSessionId"], "game-a")
        self.assertIs(message["command"]["motionEvent"], event)


if __name__ == "__main__":
    unittest.main()
