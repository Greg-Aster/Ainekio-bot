from __future__ import annotations

import asyncio
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from gateway.dashboard.server import start_dashboard_server
from gateway.security import DashboardPasswordStore, RobotTokenStore
from protocol.joints_v1 import joint_contract


class FakeGateway:
    def __init__(self) -> None:
        self.next_sequence = 1
        self.tokens: dict[str, str] = {}
        self.calls: list[tuple[str, object]] = []

    async def status_snapshot(self) -> dict[str, object]:
        return {
            "joint_contract": joint_contract(),
            "robots": {
                "ainekio-test-01": {
                    "connected": True,
                    "epoch": 3,
                    "next_sequence": self.next_sequence,
                    "pending": 0,
                    "status": {
                        "t": "status",
                        "vbat": 4.1,
                        "rssi": -42,
                        "state": "active",
                        "uptime": 30,
                        "heap": 100000,
                        "sd": True,
                        "cam_drops": 0,
                        "spk_underruns": 0,
                        "mic_drops": 0,
                        "wake_enabled": False,
                        "wake_model": "ainekio",
                        "wake_ready": False,
                        "face": "default",
                    },
                }
            }
        }

    async def queue_intent(self, name: str, params: object = None, **kwargs: object) -> int:
        return self._record("intent", (name, params, kwargs))

    async def estop(self, **kwargs: object) -> int:
        return self._record("stop", kwargs)

    async def set_profile(self, name: str, **kwargs: object) -> int:
        return self._record("profile", (name, kwargs))

    async def set_state(self, name: str, sleep_s: int | None, **kwargs: object) -> int:
        return self._record("state", (name, sleep_s, kwargs))

    async def request_snap(self, **kwargs: object) -> int:
        return self._record("snap", kwargs)

    async def set_camera(self, **kwargs: object) -> int:
        return self._record("camera", kwargs)

    async def set_microphone(self, **kwargs: object) -> int:
        return self._record("microphone", kwargs)

    async def set_wake_configuration(self, **kwargs: object) -> int:
        return self._record("wake", kwargs)

    async def tts_speak(self, frames: object, **kwargs: object) -> int:
        return self._record("tts", (list(frames), kwargs))

    async def set_calibration_mode(self, name: str, **kwargs: object) -> int:
        return self._record("mode", (name, kwargs))

    async def set_servo(self, *args: object, **kwargs: object) -> int:
        return self._record("servo", (args, kwargs))

    async def set_servo_limits(self, *args: object, **kwargs: object) -> int:
        return self._record("limits", (args, kwargs))

    async def save_calibration(self, **kwargs: object) -> int:
        return self._record("cal_save", kwargs)

    async def revoke_token(self, robot_id: str) -> None:
        self.tokens.pop(robot_id, None)
        self.calls.append(("revoke_token", robot_id))

    def set_token(self, robot_id: str, token: str) -> None:
        self.tokens[robot_id] = token

    def _record(self, name: str, value: object) -> int:
        sequence = self.next_sequence
        self.next_sequence += 1
        self.calls.append((name, value))
        return sequence


class GatewayDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.password = "operator-test-password"
        self.password_store = DashboardPasswordStore(root / "dashboard-auth.json")
        self.password_store.initialize(password=self.password)
        self.token_store = RobotTokenStore(root / "robot-tokens.json")
        self.gateway = FakeGateway()
        self.server = start_dashboard_server(
            "127.0.0.1",
            0,
            gateway=self.gateway,  # type: ignore[arg-type]
            event_loop=asyncio.get_running_loop(),
            password_store=self.password_store,
            token_store=self.token_store,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    async def asyncTearDown(self) -> None:
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=2.0)
        self.temporary_directory.cleanup()

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        cookie: str | None = None,
        csrf: str | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        def perform() -> tuple[int, dict[str, object], dict[str, str]]:
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            headers: dict[str, str] = {}
            body = None
            if payload is not None:
                body = json.dumps(payload)
                headers["Content-Type"] = "application/json"
            if cookie:
                headers["Cookie"] = cookie
            if csrf:
                headers["X-Ainekio-CSRF"] = csrf
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            connection.close()
            return response.status, json.loads(raw), response_headers

        return await asyncio.to_thread(perform)

    async def _login(self) -> tuple[str, str]:
        status, payload, headers = await self._request(
            "POST",
            "/api/login",
            {"password": self.password},
        )
        self.assertEqual(status, 200)
        cookie = headers["set-cookie"].split(";", 1)[0]
        return cookie, str(payload["csrf"])

    async def test_login_sets_bounded_hardened_session_cookie(self) -> None:
        status, payload, headers = await self._request(
            "POST",
            "/api/login",
            {"password": self.password},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["csrf"])
        cookie = headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Max-Age=28800", cookie)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-frame-options"], "DENY")

    async def test_session_and_csrf_are_required_for_commands(self) -> None:
        status, payload, _headers = await self._request("POST", "/api/stop", {})
        self.assertEqual((status, payload["error"]), (401, "authentication_required"))

        cookie, csrf = await self._login()
        status, payload, _headers = await self._request(
            "POST",
            "/api/stop",
            {},
            cookie=cookie,
        )
        self.assertEqual((status, payload["error"]), (403, "csrf"))

        status, payload, _headers = await self._request(
            "POST",
            "/api/stop",
            {"robot_id": "ainekio-test-01"},
            cookie=cookie,
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["seq"], 1)
        self.assertEqual(self.gateway.calls[0][0], "stop")

    async def test_login_is_rate_limited_after_five_failures(self) -> None:
        for _ in range(5):
            status, _payload, _headers = await self._request(
                "POST",
                "/api/login",
                {"password": "incorrect-password"},
            )
            self.assertEqual(status, 401)

        status, payload, _headers = await self._request(
            "POST",
            "/api/login",
            {"password": self.password},
        )
        self.assertEqual((status, payload["error"]), (429, "rate_limited"))

    async def test_generated_robot_token_is_returned_once_and_persisted(self) -> None:
        cookie, csrf = await self._login()
        status, payload, _headers = await self._request(
            "POST",
            "/api/tokens/generate",
            {"robot_id": "new-body"},
            cookie=cookie,
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        token = str(payload["token"])
        self.assertEqual(self.token_store.snapshot(), {"new-body": token})

        await asyncio.sleep(0)
        self.assertEqual(self.gateway.tokens, {"new-body": token})
        status, status_payload, _headers = await self._request(
            "GET",
            "/api/status",
            cookie=cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(status_payload["token_robot_ids"], ["new-body"])
        self.assertNotIn(token, json.dumps(status_payload))

    async def test_calibration_diagnostics_use_named_joints_and_calibration_messages(self) -> None:
        cookie, csrf = await self._login()

        for path, payload in (
            ("/api/calibration/mode", {"mode": "calibrate"}),
            ("/api/calibration/servo", {"id": 4, "deg": 93.5, "ms": 400}),
            (
                "/api/calibration/limits",
                {"id": 4, "min": 20.0, "center": 91.0, "max": 160.0, "invert": True},
            ),
            ("/api/calibration/neutral", {}),
            ("/api/calibration/save", {}),
            ("/api/calibration/detach", {}),
        ):
            status, _payload, _headers = await self._request(
                "POST",
                path,
                {**payload, "robot_id": "ainekio-test-01"},
                cookie=cookie,
                csrf=csrf,
            )
            self.assertEqual(status, 200, path)

        call_names = [name for name, _value in self.gateway.calls]
        self.assertEqual(call_names.count("servo"), 9)
        self.assertIn("mode", call_names)
        self.assertIn("limits", call_names)
        self.assertIn("cal_save", call_names)
        self.assertEqual(call_names[-1], "stop")

        status, payload, _headers = await self._request(
            "GET",
            "/api/status",
            cookie=cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            [joint["label"] for joint in payload["joint_contract"]["joints"]],
            ["R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4"],
        )

    async def test_wake_configuration_api_requires_auth_and_forwards_model(self) -> None:
        cookie, csrf = await self._login()
        status, payload, _headers = await self._request(
            "POST",
            "/api/wake",
            {
                "robot_id": "ainekio-test-01",
                "enabled": False,
                "model": "ainekio",
            },
            cookie=cookie,
            csrf=csrf,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["seq"], 1)
        self.assertEqual(
            self.gateway.calls[-1],
            (
                "wake",
                {
                    "enabled": False,
                    "model": "ainekio",
                    "robot_id": "ainekio-test-01",
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
