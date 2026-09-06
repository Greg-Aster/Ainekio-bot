from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOTION_SERVICE = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "src"
    / "motion_service.c"
)


class FirmwareMotionPolicyTests(unittest.TestCase):
    def test_non_detaching_stop_recovers_to_stand(self) -> None:
        source = MOTION_SERVICE.read_text(encoding="utf-8")
        stop = source.split("static void perform_stop", 1)[1].split(
            "static esp_err_t run_feedback", 1
        )[0]

        self.assertIn(
            "run_fallback(service, AINEKIO_FALLBACK_STAND)", stop
        )
        self.assertNotIn("AINEKIO_FALLBACK_NEUTRAL", stop)
        self.assertIn("ainekio_servo_detach_all(service->servos)", stop)

    def test_explicit_neutral_remains_distinct_from_stand(self) -> None:
        source = MOTION_SERVICE.read_text(encoding="utf-8")
        execute_job = source.split("static esp_err_t execute_job", 1)[1].split(
            "static void motion_task", 1
        )[0]

        self.assertIn(
            "job->kind == AINEKIO_MOTION_JOB_NEUTRAL", execute_job
        )
        self.assertIn(
            "run_fallback(service, AINEKIO_FALLBACK_NEUTRAL)", execute_job
        )


if __name__ == "__main__":
    unittest.main()
