import json
import threading
import unittest
from pathlib import Path
from urllib import request

from emulator.backends.sesame_shim import (
    MotionHub,
    MotionResult,
    SimulatorShimClient,
    SimulatorShimServer,
)


class SesameShimTests(unittest.TestCase):
    def test_browser_joint_mapping_matches_sesame_servo_setter_contract(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "sesame-robot-sim"
            / "app"
            / "ainekio-shim.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "Object.freeze([1, 2, 3, 4, 5, 6, 7, 8])",
            source,
        )
        self.assertIn("targets[jointId] * Math.PI / 180", source)
        self.assertNotIn("const jointState = runtime.hybrid.joint_q()", source)

    def test_does_not_replay_payload_to_late_subscriber(self) -> None:
        hub = MotionHub()
        payload = {"command": "walk", "frames": [1, 2, 3]}

        subscribers = hub.publish(payload)
        subscriber = hub.subscribe()

        self.assertEqual(subscribers, 0)
        self.assertTrue(subscriber.empty())

    def test_delivery_is_bounded_and_latest_wins(self) -> None:
        hub = MotionHub()
        subscriber = hub.subscribe()

        hub.publish({"command": "walk"})
        hub.publish({"command": "stand"})

        self.assertEqual(subscriber.qsize(), 1)
        self.assertEqual(subscriber.get_nowait(), {"command": "stand"})

    def test_stop_preempts_queued_movement(self) -> None:
        hub = MotionHub()
        subscriber = hub.subscribe()

        hub.publish({"command": "walk"})
        hub.publish({"command": "stop"})

        self.assertEqual(subscriber.qsize(), 1)
        self.assertEqual(subscriber.get_nowait(), {"command": "stop"})

    def test_publication_waits_for_matching_renderer_result(self) -> None:
        hub = MotionHub()
        subscriber = hub.subscribe()
        completed: list[tuple[int, MotionResult | None]] = []

        publisher = threading.Thread(
            target=lambda: completed.append(
                hub.publish_and_wait(
                    {"actionId": "session-1:7", "command": "walk"},
                    timeout_s=1.0,
                )
            )
        )
        publisher.start()
        self.assertEqual(subscriber.get(timeout=1.0)["command"], "walk")
        self.assertTrue(
            hub.report_result(
                "session-1:7",
                MotionResult(status="accepted", detail="sent to UART"),
            )
        )
        publisher.join(timeout=1.0)

        self.assertFalse(publisher.is_alive())
        self.assertEqual(completed, [(1, MotionResult("accepted", "sent to UART"))])

    def test_publication_without_renderer_is_unavailable(self) -> None:
        hub = MotionHub()

        subscribers, result = hub.publish_and_wait(
            {"actionId": "session-1:8", "command": "stand"},
            timeout_s=1.0,
        )

        self.assertEqual(subscribers, 0)
        self.assertIsNone(result)
        self.assertFalse(
            hub.report_result("session-1:8", MotionResult(status="accepted"))
        )

    def test_invalid_or_stale_renderer_result_is_rejected(self) -> None:
        hub = MotionHub()

        self.assertFalse(
            hub.report_result("missing", MotionResult(status="accepted"))
        )
        self.assertFalse(
            hub.report_result("missing", MotionResult(status="invalid"))
        )


class SesameShimHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = SimulatorShimServer(("127.0.0.1", 0))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        self.client = SimulatorShimClient(self.base_url, timeout_s=1.0)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=1.0)

    def test_http_motion_completes_only_after_browser_result(self) -> None:
        subscriber = self.server.hub.subscribe()
        completed: list[MotionResult] = []
        failures: list[Exception] = []
        payload = {
            "actionId": "session-2:9",
            "sessionId": "session-2",
            "command": "walk",
            "frames": [],
        }

        def publish() -> None:
            try:
                completed.append(self.client.publish_motion(payload))
            except Exception as exc:
                failures.append(exc)

        publisher = threading.Thread(target=publish)
        publisher.start()
        self.assertEqual(subscriber.get(timeout=1.0)["actionId"], "session-2:9")

        result_body = json.dumps(
            {
                "actionId": "session-2:9",
                "status": "accepted",
                "detail": "command sent to Sesame UART",
            }
        ).encode("utf-8")
        result_request = request.Request(
            f"{self.base_url}/result",
            data=result_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(result_request, timeout=1.0) as response:
            self.assertEqual(json.loads(response.read()), {"ok": True})

        publisher.join(timeout=1.0)
        self.assertFalse(publisher.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(
            completed,
            [MotionResult("accepted", "command sent to Sesame UART")],
        )

    def test_http_motion_completes_headlessly_when_no_renderer_is_connected(self) -> None:
        result = self.client.publish_motion(
            {
                "actionId": "session-2:10",
                "sessionId": "session-2",
                "command": "stand",
                "frames": [],
            }
        )

        self.assertEqual(
            result,
            MotionResult("accepted", "headless execution; no renderer subscriber"),
        )


if __name__ == "__main__":
    unittest.main()
