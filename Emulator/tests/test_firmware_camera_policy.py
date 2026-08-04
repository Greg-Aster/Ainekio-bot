from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAMERA_SERVICE = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "src"
    / "camera_service.c"
)


class FirmwareCameraPolicyTests(unittest.TestCase):
    def test_snapshot_profile_is_immediate_bright_and_motion_bounded(self) -> None:
        source = CAMERA_SERVICE.read_text(encoding="utf-8")

        self.assertIn("#define CAMERA_FAST_EXPOSURE_LINES 72", source)
        self.assertIn("#define CAMERA_FAST_SENSOR_GAIN 24", source)
        self.assertIn("#define CAMERA_FAST_BRIGHTNESS 1", source)
        self.assertIn("#define CAMERA_FAST_DENOISE 3", source)
        self.assertIn("#define CAMERA_FAST_SHARPNESS 0", source)

        profile = source.split(
            "static esp_err_t configure_fast_capture_profile", 1
        )[1].split("static framesize_t frame_size", 1)[0]
        expected_controls = (
            "sensor->set_aec2(sensor, 0)",
            "sensor->set_exposure_ctrl(sensor, 0)",
            "sensor->set_aec_value(sensor, CAMERA_FAST_EXPOSURE_LINES)",
            "sensor->set_gain_ctrl(sensor, 0)",
            "sensor->set_agc_gain(sensor, CAMERA_FAST_SENSOR_GAIN)",
            "sensor->set_brightness(sensor, CAMERA_FAST_BRIGHTNESS)",
            "sensor->set_denoise(sensor, CAMERA_FAST_DENOISE)",
            "sensor->set_sharpness(sensor, CAMERA_FAST_SHARPNESS)",
        )
        positions = [profile.index(control) for control in expected_controls]
        self.assertEqual(positions, sorted(positions))

        capture = source.split("static void capture_frame", 1)[1].split(
            "static void process_command", 1
        )[0]
        self.assertNotIn("vTaskDelay", capture)


if __name__ == "__main__":
    unittest.main()
