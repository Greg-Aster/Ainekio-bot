from __future__ import annotations

import asyncio
import http.client
import json
import struct
import tempfile
import threading
import unittest
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from gateway.dashboard.server import start_dashboard_server
from gateway.dashboard.auth import AuditLog
from gateway.hotspot import RobotHotspot
from gateway.server.service import ActionExpiredError, GatewayError
from gateway.security import DashboardPasswordStore, RobotTokenStore
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
from protocol.joints_v1 import joint_contract


class FakeGateway:
    def __init__(self) -> None:
        self.next_sequence = 1
        self.tokens: dict[str, str] = {}
        self.calls: list[tuple[str, object]] = []
        self.frame_callbacks: list[Callable[[dict[str, object]], object]] = []

    def subscribe_frames(
        self,
        callback: Callable[[dict[str, object]], object],
    ) -> None:
        self.frame_callbacks.append(callback)

    async def status_snapshot(self) -> dict[str, object]:
        return {
            "joint_contract": joint_contract(),
            "robots": {
                "ainekio-test-01": {
                    "connected": True,
                    "connection_state": "online",
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

    async def set_speaker_volume(self, **kwargs: object) -> int:
        return self._record("speaker", kwargs)

    async def set_wake_configuration(self, **kwargs: object) -> int:
        return self._record("wake", kwargs)

    async def tts_speak(self, frames: object, **kwargs: object) -> int:
        if isinstance(frames, AsyncIterable):
            received_frames = [frame async for frame in frames]
        else:
            received_frames = list(frames)  # type: ignore[arg-type]
        return self._record("tts", (received_frames, kwargs))

    async def set_calibration_mode(self, name: str, **kwargs: object) -> int:
        return self._record("mode", (name, kwargs))

    async def set_servo(self, *args: object, **kwargs: object) -> int:
        return self._record("servo", (args, kwargs))

    async def set_servo_limits(self, *args: object, **kwargs: object) -> int:
        return self._record("limits", (args, kwargs))

    async def save_calibration(self, **kwargs: object) -> int:
        return self._record("cal_save", kwargs)

    async def body_calibration(self, operation, values=None, **kwargs):
        from Emulator.tests.test_body_calibration import calibration_status
        sequence = self._record("body_calibration", (operation, values, kwargs))
        return calibration_status(sequence)

    async def body_motion_speed(self, operation, values=None, **kwargs):
        seq = self._record("motion_speed", (operation, values, kwargs))
        return {"t":"motion_speed_status", "seq":seq, "rate":2, "saved":True,
                "joint_speed_limit_deg_s":(values or {}).get("joint_speed_limit_deg_s",545.4545),
                "joint_speed_limit_saved":operation=="save"}

    async def body_robot_settings(self, operation, values=None, **kwargs):
        sequence = self._record("robot_settings", (operation, values, kwargs))
        return {"t": "robot_settings_status", "seq": sequence, "revision": 1,
                "active_index": 0, "pending_restart": True, "setup_open": False, "networks": []}

    async def body_storage(self, operation, **kwargs):
        from Emulator.tests.test_body_storage import storage_status
        return storage_status(self._record("storage", (operation, kwargs)))

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
    async def test_speaker_volume_uses_robot_owner_and_existing_auth(self) -> None:
        status, _, _ = await self._request("POST", "/api/speaker", {"volume_percent": 37})
        self.assertEqual(status, 401)
        cookie, csrf = await self._login()
        status, _, _ = await self._request("POST", "/api/speaker", {"volume_percent": 37}, cookie=cookie)
        self.assertEqual(status, 403)
        for volume in (0, 37, 100):
            status, result, _ = await self._request("POST", "/api/speaker", {"volume_percent": volume, "robot_id": "ainekio-test-01"}, cookie=cookie, csrf=csrf)
            self.assertEqual(status, 200)
            self.assertIn("seq", result)
            self.assertEqual(self.gateway.calls[-1], ("speaker", {"volume_percent": volume, "robot_id": "ainekio-test-01"}))
        for volume in (-1, 101, True, 1.5):
            status, _, _ = await self._request("POST", "/api/speaker", {"volume_percent": volume}, cookie=cookie, csrf=csrf)
            self.assertEqual(status, 400)
        self.assertEqual(len(self.gateway.calls), 3)

    async def test_speech_output_uses_bridge_preference_and_existing_auth(self) -> None:
        preference = {"outputTarget": "local", "provider": "kokoro", "username": "owner", "speechDisabled": False}
        async def settings(target=None):
            if target is not None:
                preference["outputTarget"] = target
            return dict(preference)
        bridge = SimpleNamespace(speech_output_settings=AsyncMock(side_effect=settings))
        self.server.environment_adapter = bridge
        status, _, _ = await self._request("GET", "/api/speech-output")
        self.assertEqual(status, 401)
        cookie, csrf = await self._login()
        status, result, _ = await self._request("GET", "/api/speech-output", cookie=cookie)
        self.assertEqual((status, result["outputTarget"]), (200, "local"))
        status, _, _ = await self._request("POST", "/api/speech-output", {"outputTarget": "robot"}, cookie=cookie)
        self.assertEqual(status, 403)
        for target in ("robot", "local"):
            status, result, _ = await self._request("POST", "/api/speech-output", {"outputTarget": target}, cookie=cookie, csrf=csrf)
            self.assertEqual((status, result["outputTarget"]), (200, target))
        status, _, _ = await self._request("POST", "/api/speech-output", {"outputTarget": "invalid"}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 400)
        self.assertEqual(preference["outputTarget"], "local")
        bridge.speech_output_settings.side_effect = GatewayError("Bridge disconnected")
        status, result, _ = await self._request("GET", "/api/speech-output", cookie=cookie)
        self.assertEqual((status, result["error"]), (503, "Bridge disconnected"))
        self.assertEqual(self.gateway.calls, [], "Destination preferences must not issue robot commands")

    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.password = "operator-test-password"
        self.password_store = DashboardPasswordStore(root / "dashboard-auth.json")
        self.password_store.initialize(password=self.password)
        self.token_store = RobotTokenStore(root / "robot-tokens.json")
        self.gateway = FakeGateway()
        self.hotspot = RobotHotspot(root / ".env", enabled=False)
        self.server = start_dashboard_server(
            "127.0.0.1",
            0,
            gateway=self.gateway,  # type: ignore[arg-type]
            event_loop=asyncio.get_running_loop(),
            password_store=self.password_store,
            token_store=self.token_store,
            hotspot=self.hotspot,
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
        status, raw, response_headers = await self._raw_request(
            method,
            path,
            payload,
            cookie=cookie,
            csrf=csrf,
        )
        return status, json.loads(raw), response_headers

    async def _raw_request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        cookie: str | None = None,
        csrf: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        def perform() -> tuple[int, bytes, dict[str, str]]:
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
            return response.status, raw, response_headers

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

    async def _restart_dashboard(self) -> None:
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=2.0)
        self.server = start_dashboard_server(
            "127.0.0.1", 0, gateway=self.gateway,
            event_loop=asyncio.get_running_loop(), password_store=self.password_store,
            token_store=self.token_store,
            hotspot=self.hotspot,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    async def test_login_survives_restart_and_logout_stays_revoked(self) -> None:
        cookie, csrf = await self._login()
        await self._restart_dashboard()
        status, payload, _ = await self._request("GET", "/api/session", cookie=cookie)
        self.assertEqual((status, payload["csrf"]), (200, csrf))
        status, _, headers = await self._raw_request("GET", "/login", cookie=cookie)
        self.assertEqual((status, headers["location"]), (303, "/"))
        status, _, _ = await self._request("POST", "/api/logout", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        await self._restart_dashboard()
        status, _, _ = await self._request("GET", "/api/session", cookie=cookie)
        self.assertEqual(status, 401)

    async def test_network_toggle_uses_existing_auth_and_persists_without_robot_commands(self):
        process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
        with patch("gateway.hotspot.asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as execute:
            status, _, _ = await self._request("POST", "/api/settings/network", {"hotspot": True})
            self.assertEqual(status, 401)
            cookie, csrf = await self._login()
            status, _, _ = await self._request("POST", "/api/settings/network", {"hotspot": True}, cookie=cookie)
            self.assertEqual(status, 403)
            execute.assert_not_awaited()
            status, payload, _ = await self._request("POST", "/api/settings/network", {"hotspot": True}, cookie=cookie, csrf=csrf)
            self.assertEqual(status, 200)
            self.assertEqual(payload["host_network"], {"hotspot": True})
            self.assertEqual(self.hotspot.env_file.read_text(), "AINEKIO_HOTSPOT=1\n")
            status, snapshot, _ = await self._request("GET", "/api/status", cookie=cookie)
            self.assertEqual(snapshot["host_network"], {"hotspot": True})
            self.assertEqual(self.gateway.calls, [])
            self.assertEqual(execute.await_args.args[:4], ("systemctl", "--no-ask-password", "start", "ainekio-hotspot-dhcp.service"))

    async def test_network_service_failure_is_visible_and_preserves_saved_mode(self):
        process = SimpleNamespace(returncode=1, communicate=AsyncMock(return_value=(b"", b"Missing hotspot service")))
        cookie, csrf = await self._login()
        with patch("gateway.hotspot.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            status, payload, _ = await self._request("POST", "/api/settings/network", {"hotspot": True}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 409)
        self.assertIn("Missing hotspot service", payload["error"])
        self.assertFalse(self.hotspot.enabled)
        self.assertFalse(self.hotspot.env_file.exists())

    async def test_dashboard_error_is_saved_without_request_credentials(self) -> None:
        path = Path(self.temporary_directory.name) / "operations.jsonl"
        self.server.audit_log = AuditLog(path)

        async def reject(*_args, **_kwargs):
            raise ActionExpiredError("fresh body clock required before dispatch")

        self.gateway.queue_intent = reject
        cookie, csrf = await self._login()
        status, response, _ = await self._request("POST", "/api/intent",
            {"name": "walk", "params": {"speed": 150}, "password": "do-not-save"},
            cookie=cookie, csrf=csrf)
        self.assertEqual(status, 409)
        self.assertEqual(response["error"], "fresh body clock required before dispatch")
        saved = path.read_text()
        row = json.loads(saved.splitlines()[-1])
        self.assertEqual(row["event"], "dashboard_request_failed")
        self.assertEqual(row["path"], "/api/intent")
        self.assertEqual(row["name"], "walk")
        self.assertEqual(row["error_type"], "ActionExpiredError")
        self.assertNotIn("do-not-save", saved)

    async def test_password_change_requires_session_csrf_and_current_password(self) -> None:
        payload = {"current_password": self.password, "new_password": "new-operator-password", "confirm_password": "new-operator-password"}
        status, _, _ = await self._request("POST", "/api/settings/password", payload)
        self.assertEqual(status, 401)
        cookie, csrf = await self._login()
        status, _, _ = await self._request("POST", "/api/settings/password", payload, cookie=cookie)
        self.assertEqual(status, 403)
        for changes, expected in [
            ({"current_password": "incorrect-password"}, 403),
            ({"confirm_password": "different-password"}, 400),
            ({"new_password": None}, 400),
            ({"current_password": None}, 400),
        ]:
            status, _, _ = await self._request("POST", "/api/settings/password", {**payload, **changes}, cookie=cookie, csrf=csrf)
            self.assertEqual(status, expected)
            self.assertTrue(self.password_store.verify(self.password))

    async def test_owner_chosen_passwords_can_be_saved_and_used_after_restart(self) -> None:
        cookie, csrf = await self._login()
        current = self.password
        for password in (self.password, "a", "long" * 100, "  café 🔑  ", "", "after-blank"):
            with self.subTest(password_length=len(password)):
                status, _, _ = await self._request("POST", "/api/settings/password", {
                    "current_password": current, "new_password": password, "confirm_password": password,
                }, cookie=cookie, csrf=csrf)
                self.assertEqual(status, 200)
                await self._restart_dashboard()
                status, _, _ = await self._request("POST", "/api/login", {"password": password})
                self.assertEqual(status, 200)
                status, _, _ = await self._request("POST", "/api/login", {"password": password + "incorrect"})
                self.assertEqual(status, 401)
                current = password

    async def test_password_change_keeps_current_browser_and_revokes_others_across_restart(self) -> None:
        cookie, csrf = await self._login()
        other_cookie, _ = await self._login()
        new_password = "new-operator-password"
        status, _, _ = await self._request("POST", "/api/settings/password", {
            "current_password": self.password, "new_password": new_password, "confirm_password": new_password,
        }, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertTrue(self.password_store.verify(new_password))
        self.assertFalse(self.password_store.verify(self.password))
        entries = self.server.audit_log.entries()
        self.assertTrue(any(entry["event"] == "dashboard_password_changed" for entry in entries))
        audit = json.dumps(entries)
        self.assertNotIn(self.password, audit)
        self.assertNotIn(new_password, audit)
        self.password_store.initialize(password=self.password)
        await self._restart_dashboard()
        self.assertTrue(self.password_store.verify(new_password))
        status, payload, _ = await self._request("GET", "/api/session", cookie=cookie)
        self.assertEqual((status, payload["csrf"]), (200, csrf))
        status, _, _ = await self._request("GET", "/api/session", cookie=other_cookie)
        self.assertEqual(status, 401)
        status, _, _ = await self._request("POST", "/api/login", {"password": self.password})
        self.assertEqual(status, 401)
        status, _, _ = await self._request("POST", "/api/login", {"password": new_password})
        self.assertEqual(status, 200)

    async def test_robot_settings_requires_auth_csrf_and_explicit_restart(self):
        payload = {"op": "security", "robot_id": "ainekio-test-01", "revision": 0, "setup_password": "setup-secret"}
        status, _, _ = await self._request("POST", "/api/settings/robot", payload)
        self.assertEqual(status, 401)
        cookie, csrf = await self._login()
        status, _, _ = await self._request("POST", "/api/settings/robot", payload, cookie=cookie)
        self.assertEqual(status, 403)
        status, response, _ = await self._request("POST", "/api/settings/robot", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertTrue(response["settings"]["pending_restart"])
        self.assertNotIn("setup-secret", json.dumps(self.server.audit_log.entries()))
        restart = {"op": "apply", "robot_id": "ainekio-test-01", "revision": 1}
        status, _, _ = await self._request("POST", "/api/settings/robot", restart, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 400)
        status, _, _ = await self._request("POST", "/api/settings/robot", {**restart, "confirmed": True}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)

    async def test_joint_speed_limit_save_requires_login_and_csrf_and_returns_readback(self):
        payload={"robot_id":"ainekio-test-01","op":"save","joint_speed_limit_deg_s":900}
        status,_,_=await self._request("POST","/api/motion-speed",payload)
        self.assertEqual(status,401)
        cookie,csrf=await self._login()
        status,_,_=await self._request("POST","/api/motion-speed",payload,cookie=cookie)
        self.assertEqual(status,403)
        status,response,_=await self._request("POST","/api/motion-speed",payload,cookie=cookie,csrf=csrf)
        self.assertEqual(status,200)
        self.assertEqual(response["motion_speed"]["joint_speed_limit_deg_s"],900)
        self.assertTrue(response["motion_speed"]["joint_speed_limit_saved"])
        self.assertEqual(response["seq"],response["motion_speed"]["seq"])
        self.assertEqual(self.gateway.calls[-1],("motion_speed",("save",{"joint_speed_limit_deg_s":900},{"robot_id":"ainekio-test-01"})))

    async def test_camera_controls_forward_independent_snapshot_resolution(self):
        cookie, csrf = await self._login()
        status, _, _ = await self._request("POST", "/api/camera",
            {"robot_id": "ainekio-test-01", "on": True, "fps": 5, "res": "QVGA", "snapshot_res": "XGA"},
            cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertEqual(self.gateway.calls[-1], ("camera", {"robot_id": "ainekio-test-01", "on": True,
            "fps": 5, "resolution": "QVGA", "snapshot_resolution": "XGA"}))

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
        self.assertIn("Max-Age=2592000", cookie)
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
        self.assertEqual(
            self.gateway.calls[0],
            (
                "stop",
                {"robot_id": "ainekio-test-01", "detach": False},
            ),
        )

        status, payload, _headers = await self._request(
            "POST",
            "/api/detach",
            {"robot_id": "ainekio-test-01"},
            cookie=cookie,
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["seq"], 2)
        self.assertEqual(
            self.gateway.calls[1],
            (
                "stop",
                {"robot_id": "ainekio-test-01", "detach": True},
            ),
        )

    async def test_body_calibration_requires_operator_session_and_returns_readback(self) -> None:
        payload = {"op": "move", "id": 11, "pulse_us": 1505, "robot_id": "p4"}
        status, _, _ = await self._request("POST", "/api/calibration/body", payload)
        self.assertEqual(status, 401)
        cookie, csrf = await self._login()
        status, _, _ = await self._request("POST", "/api/calibration/body", payload, cookie=cookie)
        self.assertEqual(status, 403)
        self.assertEqual(self.gateway.calls, [])
        status, response, _ = await self._request("POST", "/api/calibration/body", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertEqual(len(response["calibration"]["joints"]), 12)
        self.assertEqual(self.gateway.calls[0], ("body_calibration", ("move", {"id": 11, "pulse_us": 1505}, {"robot_id": "p4"})))
        mapping = {"id": 7, "channel": 7, "home_us": 1505,
                   "invert": True, "home_cd": -1245, "us_per_degree": 11.111111}
        status, response, _ = await self._request("POST", "/api/calibration/body",
            {"op": "set", "robot_id": "p4", **mapping}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertEqual(self.gateway.calls[-1], ("body_calibration", ("set", mapping, {"robot_id": "p4"})))
        status, _, _ = await self._request("POST", "/api/diagnostics/output", {"op": "run"}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 400)

    async def test_storage_clear_requires_session_csrf_and_explicit_confirmation(self) -> None:
        status, _, _ = await self._request("POST", "/api/storage", {"op": "clear", "confirmed": True})
        self.assertEqual(status, 401)
        cookie, csrf = await self._login()
        status, _, _ = await self._request("POST", "/api/storage", {"op": "clear", "confirmed": True}, cookie=cookie)
        self.assertEqual(status, 403)
        status, _, _ = await self._request("POST", "/api/storage", {"op": "clear"}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 400)
        self.assertEqual(self.gateway.calls, [])
        status, response, _ = await self._request("POST", "/api/storage", {"op": "clear", "confirmed": True, "robot_id": "p4"}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertTrue(response["storage"]["mounted"])
        self.assertEqual(self.gateway.calls[0], ("storage", ("clear", {"robot_id": "p4"})))

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
        self.assertEqual(
            self.gateway.calls[-1][1],
            {"robot_id": "ainekio-test-01", "detach": True},
        )

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

    async def test_audio_adjustment_api_forwards_optional_settings(self) -> None:
        cookie, csrf = await self._login()
        for path, kind, values in (
            ("/api/microphone", "microphone", {"on": True, "gate": "wake", "gain_db": 36}),
            ("/api/wake", "wake", {"enabled": True, "model": "ainekio", "threshold": 0.4}),
        ):
            status, _, _ = await self._request("POST", path,
                {"robot_id": "ainekio-test-01", **values}, cookie=cookie, csrf=csrf)
            self.assertEqual(status, 200)
            self.assertEqual(self.gateway.calls[-1], (kind, {"robot_id": "ainekio-test-01", **values}))
        for path, values in (
            ("/api/microphone", {"on": True, "gate": "wake", "gain_db": True}),
            ("/api/wake", {"enabled": True, "model": "ainekio", "threshold": "high"}),
        ):
            status, _, _ = await self._request("POST", path, values, cookie=cookie, csrf=csrf)
            self.assertEqual(status, 400)

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

    async def test_speaker_test_accepts_bounded_variable_volume(self) -> None:
        cookie, csrf = await self._login()
        status, payload, _headers = await self._request(
            "POST",
            "/api/speaker-test",
            {
                "robot_id": "ainekio-test-01",
                "volume_percent": 25,
            },
            cookie=cookie,
            csrf=csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["seq"], 1)
        call_name, call_value = self.gateway.calls[-1]
        self.assertEqual(call_name, "tts")
        frames, kwargs = call_value
        self.assertEqual(len(frames), 100)
        self.assertEqual(kwargs, {"robot_id": "ainekio-test-01"})
        samples = struct.unpack("<320h", frames[0])
        self.assertGreater(max(abs(sample) for sample in samples), 8000)
        self.assertLessEqual(max(abs(sample) for sample in samples), 8192)

        status, _payload, _headers = await self._request(
            "POST", "/api/speaker-test",
            {"robot_id": "ainekio-test-01", "volume_percent": 100},
            cookie=cookie, csrf=csrf,
        )
        self.assertEqual(status, 200)
        full_frames, _kwargs = self.gateway.calls[-1][1]
        full_samples = struct.unpack("<320h", full_frames[0])
        self.assertEqual(max(full_samples), 32767)
        self.assertEqual(min(full_samples), -32767)

        for invalid_volume in (0, 101):
            status, invalid_payload, _headers = await self._request(
                "POST",
                "/api/speaker-test",
                {
                    "robot_id": "ainekio-test-01",
                    "volume_percent": invalid_volume,
                },
                cookie=cookie,
                csrf=csrf,
            )
            self.assertEqual(status, 400)
            self.assertIn("between 1 and 100", str(invalid_payload["error"]))

    async def test_dashboard_serves_latest_authenticated_camera_frame(self) -> None:
        status, payload, _headers = await self._request(
            "GET",
            "/api/camera/frame?robot_id=ainekio-test-01",
        )
        self.assertEqual((status, payload["error"]), (401, "authentication_required"))

        cookie, _csrf = await self._login()
        jpeg = b"\xff\xd8camera-frame\xff\xd9"
        for callback in self.gateway.frame_callbacks:
            callback(
                {
                    "robot_id": "ainekio-test-01",
                    "frame_type": CAMERA_JPEG_FRAME_TYPE,
                    "counter": 17,
                    "payload": jpeg,
                }
            )

        status, body, headers = await self._raw_request(
            "GET",
            "/api/camera/frame?robot_id=ainekio-test-01",
            cookie=cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, jpeg)
        self.assertEqual(headers["content-type"], "image/jpeg")
        self.assertEqual(headers["x-ainekio-camera-counter"], "17")
        self.assertIn("img-src 'self' blob:", headers["content-security-policy"])

    async def test_dashboard_defaults_to_physical_camera_panel(self) -> None:
        cookie, _csrf = await self._login()
        status, body, _headers = await self._raw_request("GET", "/", cookie=cookie)

        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('data-dashboard-primary="camera"', html)
        self.assertIn('data-dashboard-panel="camera"', html)
        self.assertIn('id="speaker-test-form"', html)
        self.assertIn('id="speaker-test-volume"', html)
        self.assertIn('name="volume_percent"', html)
        self.assertLess(
            html.index('id="camera-form"'),
            html.index('data-dashboard-panel="simulator"'),
        )
        self.assertIn('data-dashboard-panel="simulator"', html)
        self.assertIn('data-intent="sit">Sit · bored</button>', html)
        self.assertIn('data-emote="number_one">#1 · hydrant</button>', html)
        self.assertIn('data-emote="number_two">#2 · squat</button>', html)

        status, body, _headers = await self._raw_request(
            "GET",
            "/assets/dashboard.css",
            cookie=cookie,
        )
        self.assertEqual(status, 200)
        css = body.decode("utf-8")
        self.assertIn(".camera-frame { width: 100%; height: auto;", css)
        self.assertNotIn(".camera-frame { width: 100%; height: 100%;", css)

    async def test_dashboard_can_select_emulator_panel(self) -> None:
        cookie, _csrf = await self._login()
        self.server.primary_view = "simulator"
        status, body, _headers = await self._raw_request("GET", "/", cookie=cookie)

        self.assertEqual(status, 200)
        self.assertIn(
            'data-dashboard-primary="simulator"',
            body.decode("utf-8"),
        )

    async def test_face_library_assets_and_independent_expression_command(self) -> None:
        cookie, csrf = await self._login()
        status, body, _ = await self._raw_request("GET", "/assets/faces/catalog.json", cookie=cookie)
        self.assertEqual(status, 200)
        catalog = json.loads(body)
        names = {face["name"] for face in catalog}
        import re
        definitions = Path(__file__).resolve().parents[2] / "Slave/software/faces/faces.def"
        self.assertEqual(names, set(re.findall(r"^FACE\((\w+),", definitions.read_text(), re.MULTILINE)))
        self.assertTrue({"default", "happy", "love", "curious", "run"}.issubset(names))
        for name in names:
            for extension, signature in (("png", b"\x89PNG"), ("webp", b"RIFF")):
                status, image, _ = await self._raw_request("GET", f"/assets/faces/{name}.{extension}", cookie=cookie)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(signature))
        before = len(self.gateway.calls)
        status, result, _ = await self._request("POST", "/api/intent",
            {"robot_id": "ainekio-test-01", "name": "face", "params": {"expr": "run"}},
            cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertIn("seq", result)
        self.assertEqual(len(self.gateway.calls), before + 1)
        name, payload = self.gateway.calls[-1]
        self.assertEqual(name, "intent")
        self.assertEqual(payload[0], "face")
        self.assertEqual(payload[1], {"expr": "run"})


if __name__ == "__main__":
    unittest.main()
