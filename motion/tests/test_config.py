import unittest
from pathlib import Path

from ainekio_motion.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_example_config_without_hardcoded_bridge_destination(self) -> None:
        config = load_config(Path(__file__).parents[1] / "config.example.json")

        self.assertEqual(config.backend.active, "virtual")
        self.assertFalse(config.backend.hardware_enabled)
        self.assertTrue(config.bridge.url.startswith("ws://"))
        self.assertEqual(config.safety.motor_stagger_ms, 20)


if __name__ == "__main__":
    unittest.main()
