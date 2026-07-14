import unittest

from ainekio_motion.commands import translate_environment_action
from ainekio_motion.sequences import SequenceEngine
from ainekio_motion.simulator_shim import build_motion_payload


class SimulatorShimTests(unittest.TestCase):
    def test_build_motion_payload_uses_ainekio_schema(self) -> None:
        command = translate_environment_action(
            {"type": "robotCommand", "command": "walk", "simulatorCommand": "run walk", "units": 5},
            issued_at_ms=1000,
        )
        self.assertIsNotNone(command)
        frames = SequenceEngine().render(command)

        payload = build_motion_payload(
            action_id="action-1",
            session_id="ainekio-sim-1",
            command=command,
            frames=frames,
        )

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["source"], "ainekio-adapter")
        self.assertEqual(payload["actionId"], "action-1")
        self.assertEqual(payload["sessionId"], "ainekio-sim-1")
        self.assertEqual(payload["command"], "walk")
        self.assertEqual(payload["simulatorCommand"], "run walk")
        self.assertEqual(payload["units"], 5)
        self.assertEqual(payload["rootMotion"]["forward"], 1.0)
        self.assertGreater(len(payload["frames"]), 0)

if __name__ == "__main__":
    unittest.main()
