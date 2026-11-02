from __future__ import annotations

import errno
import json
import logging
import os
import stat
import tempfile
import unittest
from pathlib import Path

import gateway.server.__main__ as gateway_main
from gateway.security import DashboardPasswordStore, RobotTokenStore
from gateway.dashboard.auth import DashboardSessions, SESSION_TTL_SECONDS
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE


class GatewaySecurityTests(unittest.TestCase):
    def test_expected_websocket_network_loss_is_logged_without_traceback(self) -> None:
        error = OSError(errno.EHOSTUNREACH, "No route to host")
        record = logging.LogRecord(
            "websockets.server",
            logging.ERROR,
            __file__,
            1,
            "data transfer failed",
            (),
            (OSError, error, None),
        )

        self.assertTrue(
            gateway_main.ConciseWebSocketDisconnectFilter().filter(record)
        )
        self.assertEqual(
            record.getMessage(),
            "WebSocket peer disconnected: [Errno 113] No route to host",
        )
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIsNone(record.exc_info)

    def test_unexpected_websocket_error_keeps_diagnostic_traceback(self) -> None:
        error = RuntimeError("unexpected failure")
        exc_info = (RuntimeError, error, None)
        record = logging.LogRecord(
            "websockets.server",
            logging.ERROR,
            __file__,
            1,
            "data transfer failed",
            (),
            exc_info,
        )

        self.assertTrue(
            gateway_main.ConciseWebSocketDisconnectFilter().filter(record)
        )
        self.assertEqual(record.msg, "data transfer failed")
        self.assertIs(record.exc_info, exc_info)

    def test_microphone_frame_audit_is_rate_limited_per_robot_epoch(self) -> None:
        class RecordingAuditLog:
            def __init__(self) -> None:
                self.entries: list[tuple[str, dict[str, object]]] = []

            def record(self, event: str, **details: object) -> None:
                self.entries.append((event, details))

        now = 10.0
        log = RecordingAuditLog()
        audit = gateway_main.MicrophoneFrameAudit(  # type: ignore[arg-type]
            log,
            clock=lambda: now,
        )
        microphone = {
            "robot_id": "ainekio-test-01",
            "epoch": 3,
            "frame_type": MIC_PCM_FRAME_TYPE,
            "counter": 1,
        }

        audit.record(microphone)
        now = 10.02
        audit.record({**microphone, "counter": 2})
        now = 11.0
        audit.record({**microphone, "counter": 50})
        audit.record(
            {
                **microphone,
                "epoch": 4,
                "counter": 51,
            }
        )
        audit.record(
            {
                **microphone,
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 52,
            }
        )

        self.assertEqual(
            [details["counter"] for _, details in log.entries],
            [1, 50, 51, 52],
        )

    def test_audit_allows_only_secret_free_heartbeat_diagnostics(self) -> None:
        self.assertEqual(
            gateway_main._audit_fields(
                {
                    "robot_id": "ainekio-test-01",
                    "control_frames_received": 3,
                    "json_pings_sent": 4,
                    "last_control_type": "pong",
                    "auth": "secret-robot-token",
                }
            ),
            {
                "robot_id": "ainekio-test-01",
                "control_frames_received": 3,
                "json_pings_sent": 4,
                "last_control_type": "pong",
            },
        )

    def test_environment_peer_must_be_loopback(self) -> None:
        class Peer:
            def __init__(self, host: str) -> None:
                self.remote_address = (host, 12345)

        self.assertTrue(gateway_main._peer_is_loopback(Peer("127.0.0.1")))
        self.assertTrue(gateway_main._peer_is_loopback(Peer("::1")))
        self.assertFalse(gateway_main._peer_is_loopback(Peer("192.168.0.20")))
        self.assertFalse(gateway_main._peer_is_loopback(object()))

        relay = Peer("127.0.0.1")
        relay.request_headers = {"CF-Ray": "test"}
        self.assertTrue(gateway_main._request_uses_relay(relay))
        self.assertEqual(gateway_main._robot_transport(relay), "relay")

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_robot_tokens_persist_in_owner_only_file(self) -> None:
        path = self.root / "robot-tokens.json"
        store = RobotTokenStore(path)
        token = store.generate("ainekio-test-01")

        self.assertEqual(RobotTokenStore(path).snapshot(), {"ainekio-test-01": token})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

        store.revoke("ainekio-test-01")
        self.assertEqual(RobotTokenStore(path).snapshot(), {})

    def test_dashboard_file_contains_verifier_not_plaintext(self) -> None:
        path = self.root / "dashboard-auth.json"
        password = "a-correct-horse-password"
        store = DashboardPasswordStore(path)
        store.initialize(password=password)

        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn(password, path.read_text(encoding="utf-8"))
        self.assertEqual(record["algorithm"], "pbkdf2-sha256")
        self.assertTrue(store.verify(password))
        self.assertFalse(store.verify("wrong-password-value"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_missing_password_store_requires_tty_or_explicit_password(self) -> None:
        path = self.root / "dashboard-auth.json"
        store = DashboardPasswordStore(path)

        with self.assertRaisesRegex(RuntimeError, "interactive TTY"):
            store.initialize()

    def test_explicit_password_change_replaces_existing_verifier(self) -> None:
        path = self.root / "dashboard-auth.json"
        store = DashboardPasswordStore(path)
        old_password = "old-dashboard-password"
        new_password = "new-dashboard-password"

        store.initialize(password=old_password)
        store.set_password(new_password)
        self.assertFalse(store.verify(old_password))
        self.assertTrue(store.verify(new_password))
        store.initialize(password=old_password)
        self.assertTrue(store.verify(new_password), "A stale startup variable must not undo a UI password change")

    def test_saved_password_and_revision_survive_normal_startup(self) -> None:
        store = DashboardPasswordStore(self.root / "dashboard-auth.json")
        store.initialize(password="stable-dashboard-password")
        original = store.path.read_bytes()
        self.assertIsNone(store.initialize())
        store.initialize(password="stable-dashboard-password")
        self.assertEqual(store.path.read_bytes(), original)

    def test_sessions_survive_restart_but_not_logout_expiry_or_password_change(self) -> None:
        store = DashboardPasswordStore(self.root / "dashboard-auth.json")
        store.initialize(password="stable-dashboard-password")
        path = self.root / "dashboard-sessions.json"
        now = 1000.0

        def reload_sessions() -> DashboardSessions:
            return DashboardSessions(path=path, password_revision=store.revision(), clock=lambda: now)

        sessions = reload_sessions()
        token, session = sessions.create()
        self.assertNotIn(token, path.read_text())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(reload_sessions().get(token), session)
        sessions.revoke(token)
        self.assertIsNone(reload_sessions().get(token))

        token, _ = sessions.create()
        now += SESSION_TTL_SECONDS
        self.assertIsNone(reload_sessions().get(token))
        sessions = reload_sessions()
        token, _ = sessions.create()
        store.set_password("changed-dashboard-password")
        self.assertIsNone(reload_sessions().get(token))

    def test_session_store_is_bounded_and_rejects_malformed_entries(self) -> None:
        from gateway.dashboard.auth import MAX_SESSIONS
        path = self.root / "dashboard-sessions.json"
        sessions = DashboardSessions(path=path, password_revision="test")
        old_token, _ = sessions.create()
        for _ in range(MAX_SESSIONS):
            sessions.create()
        self.assertIsNone(sessions.get(old_token))
        record = json.loads(path.read_text())
        self.assertEqual(len(record["sessions"]), MAX_SESSIONS)
        next(iter(record["sessions"].values()))["expires_at"] = "invalid"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(RuntimeError, "invalid entry"):
            DashboardSessions(path=path, password_revision="test")

    def test_invalid_store_fails_closed(self) -> None:
        path = self.root / "robot-tokens.json"
        path.write_text('{"schema_version":1,"tokens":{"robot":42}}', encoding="utf-8")
        os.chmod(path, 0o600)

        with self.assertRaisesRegex(RuntimeError, "invalid entry"):
            RobotTokenStore(path)


class GatewayStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_body_control_startup_with_and_without_environment_adapter(self):
        from contextlib import ExitStack, asynccontextmanager
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch

        for token in ("", "fixture-adapter-token"):
            with self.subTest(adapter_enabled=bool(token)), tempfile.TemporaryDirectory() as directory:
                service = Mock()
                service.close = AsyncMock()
                dashboard = Mock(control_settings={"recognition": False})
                dashboard.close_freestyle = AsyncMock()
                dashboard.host_audio.close = AsyncMock()
                camera = Mock()
                camera.restore_ground_plane = AsyncMock()
                camera.restore_depth = AsyncMock()
                camera.aclose = AsyncMock()
                hotspot = Mock(start=AsyncMock())
                gait = Mock(start=AsyncMock(), close=AsyncMock())
                adapter = Mock(handler=AsyncMock())
                server = SimpleNamespace(websockets=[], close=Mock())
                socket = Mock(close=AsyncMock(), remote_address=("127.0.0.1", 12345), request_headers={})

                with ExitStack() as stack:
                    stack.enter_context(patch.dict(os.environ, {
                        "AINEKIO_ENVIRONMENT_ADAPTER_TOKEN": token,
                    }, clear=True))
                    args = gateway_main._parser().parse_args(["--data-dir", directory])
                    stack.enter_context(patch.object(gateway_main, "GatewayService", return_value=service))
                    stack.enter_context(patch.object(gateway_main, "DashboardPasswordStore"))
                    stack.enter_context(patch.object(gateway_main, "RobotTokenStore"))
                    stack.enter_context(patch.object(gateway_main, "AuditLog"))
                    stack.enter_context(patch.object(gateway_main, "RobotHotspot", return_value=hotspot))
                    stack.enter_context(patch.object(gateway_main, "start_dashboard_server", return_value=dashboard))
                    stack.enter_context(patch.object(gateway_main, "CameraFramePlugin", return_value=camera))
                    adapter_factory = stack.enter_context(patch.object(gateway_main, "EnvironmentAdapter", return_value=adapter))
                    stack.enter_context(patch("gateway.gait_learning_service.GaitLearningService", return_value=gait))
                    stack.enter_context(patch("gateway.gait_learning_service.RobotLearningTransport"))
                    stack.enter_context(patch.object(gateway_main, "threading", SimpleNamespace(Thread=Mock())))
                    signals = stack.enter_context(patch.object(gateway_main.signal, "signal"))
                    stack.enter_context(patch.object(gateway_main.asyncio, "to_thread", AsyncMock(side_effect=lambda fn: fn())))
                    stack.enter_context(patch.object(gateway_main, "_print_gateway_addresses"))

                    @asynccontextmanager
                    async def serve(route, *args, **kwargs):
                        await route(socket, "/environment")
                        # Exercise the existing graceful-shutdown path without
                        # opening sockets, starting services, or sending signals.
                        signals.call_args_list[0].args[1](gateway_main.signal.SIGTERM, None)
                        yield server

                    stack.enter_context(patch.object(gateway_main, "serve", serve))
                    await gateway_main._run_production(args)

                self.assertIs(dashboard.camera_recognition, camera)
                self.assertIs(service.locomotion_measurement, camera.locomotion_measurement)
                self.assertIs(service.depth_demand, camera.depth_demand)
                camera.restore_ground_plane.assert_awaited_once_with({})
                camera.restore_depth.assert_awaited_once_with({})
                camera.aclose.assert_awaited_once()
                dashboard.close_freestyle.assert_awaited_once()
                if token:
                    adapter_factory.assert_called_once()
                    adapter.handler.assert_awaited_once_with(socket)
                    socket.close.assert_not_awaited()
                    self.assertIs(adapter.camera_capture, camera.capture)
                    self.assertIs(adapter.selected_ground_range, camera.selected_ground_range)
                    self.assertIs(adapter.depth_demand, camera.depth_demand)
                else:
                    adapter_factory.assert_not_called()
                    socket.close.assert_awaited_once_with(code=1008, reason="wrong or unavailable endpoint")


if __name__ == "__main__":
    unittest.main()
