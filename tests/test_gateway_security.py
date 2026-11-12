from __future__ import annotations

import asyncio
import errno
import gc
import hashlib
import json
import logging
import os
import stat
import tempfile
import unittest
import warnings
from contextlib import ExitStack, contextmanager
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
    @contextmanager
    def startup_fixture(self, root, *, token="", failure=None,
                        cleanup_failure=None, stop_at_serve=True):
        events = []

        def step(name):
            events.append(name)
            if name in (failure, cleanup_failure):
                raise RuntimeError("Fixture failure: " + name)

        def factory(name, value):
            def create(*args, **kwargs):
                step(name)
                return value
            return Mock(side_effect=create)

        def action(name):
            return Mock(side_effect=lambda *args, **kwargs: step(name))

        def async_action(name):
            return AsyncMock(side_effect=lambda *args, **kwargs: step(name))

        gateway = Mock(close=async_action("gateway.close"))
        dashboard = SimpleNamespace(
            control_settings={"recognition": False},
            serve_forever=Mock(side_effect=AssertionError("Fake HTTP thread must not execute")),
            restore_camera=Mock(side_effect=AssertionError("No body events expected in startup fixture")),
            start_freestyle=action("freestyle.start"),
            close_freestyle=async_action("freestyle.close"),
            host_audio=SimpleNamespace(close=async_action("audio.close")),
            shutdown=action("http.shutdown"), server_close=action("http.close"),
        )
        thread = SimpleNamespace(start=action("http.start"), join=action("http.join"))
        camera = Mock(restore_ground_plane=async_action("camera.ground"),
            restore_depth=async_action("camera.depth"), aclose=async_action("camera.close"))
        adapter = Mock(handler=async_action("environment.handle"))
        socket = Mock(close=async_action("route.close"),
            remote_address=("127.0.0.1", 12345), request_headers={})
        established = SimpleNamespace(open=True, closed=False,
            close=async_action("socket.close"))
        handshake = SimpleNamespace(open=False, closed=False,
            transport=SimpleNamespace(close=action("handshake.close")))
        server = SimpleNamespace(websockets=[established, handshake],
            close=action("ws.close"), wait_closed=async_action("ws.wait_closed"))
        previous_signal = object()
        stop = []
        listening = asyncio.Event()

        def install_signal(number, handler):
            if handler is previous_signal:
                step("signal.restore")
            else:
                step("signal.install")
                stop.append(handler)
            return previous_signal

        async def serve(route, *args, **kwargs):
            step("ws.bind")
            await route(socket, "/environment")
            # Invoke only the captured callback, never a real OS signal.
            listening.set()
            if stop_at_serve:
                stop[0](gateway_main.signal.SIGTERM, None)
            return server

        fixture = SimpleNamespace(events=events, gateway=gateway, dashboard=dashboard,
            thread=thread, camera=camera,
            adapter=adapter, socket=socket, server=server,
            established=established, handshake=handshake, listening=listening)

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,
                {"AINEKIO_ENVIRONMENT_ADAPTER_TOKEN": token}, clear=True))
            fixture.args = gateway_main._parser().parse_args(
                ["--data-dir", str(root/"gateway-state")])
            stack.enter_context(patch.object(gateway_main, "GatewayService",
                factory("gateway.create", gateway)))
            stack.enter_context(patch.object(gateway_main, "DashboardPasswordStore"))
            stack.enter_context(patch.object(gateway_main, "RobotTokenStore"))
            stack.enter_context(patch.object(gateway_main, "AuditLog"))
            stack.enter_context(patch.object(gateway_main, "RobotHotspot",
                return_value=SimpleNamespace(start=async_action("hotspot.start"))))
            stack.enter_context(patch.object(gateway_main, "start_dashboard_server",
                factory("dashboard.create", dashboard)))
            stack.enter_context(patch.object(gateway_main, "CameraFramePlugin",
                factory("camera.create", camera)))
            fixture.adapter_factory = stack.enter_context(patch.object(
                gateway_main, "EnvironmentAdapter", return_value=adapter))
            # Keep global threading and asyncio.to_thread real for dashboard shutdown's thread dispatch.
            stack.enter_context(patch.object(gateway_main, "threading",
                SimpleNamespace(Thread=Mock(return_value=thread))))
            stack.enter_context(patch.object(gateway_main.signal, "signal",
                side_effect=install_signal))
            stack.enter_context(patch.object(gateway_main, "serve", serve))
            stack.enter_context(patch.object(gateway_main, "_print_gateway_addresses"))
            yield fixture

    async def test_body_control_startup_with_and_without_environment_adapter(self):
        for token in ("", "fixture-adapter-token"):
            with self.subTest(adapter_enabled=bool(token)), tempfile.TemporaryDirectory() as directory:
                with self.startup_fixture(Path(directory), token=token) as f:
                    await gateway_main._run_production(f.args)
                    self.assertIs(f.dashboard.camera_recognition, f.camera)
                    self.assertIs(f.gateway.locomotion_measurement, f.camera.locomotion_measurement)
                    self.assertIs(f.gateway.depth_demand, f.camera.depth_demand)
                    f.camera.restore_ground_plane.assert_awaited_once_with({})
                    f.camera.restore_depth.assert_awaited_once_with({})
                    f.gateway.close.assert_awaited_once()
                    f.camera.aclose.assert_awaited_once()
                    f.dashboard.close_freestyle.assert_awaited_once()
                    f.dashboard.host_audio.close.assert_awaited_once()
                    f.server.wait_closed.assert_awaited_once()
                    f.established.close.assert_awaited_once_with(1001, "gateway stopped")
                    f.handshake.transport.close.assert_called_once()
                    f.thread.join.assert_called_once_with(timeout=2.0)
                    self.assertLess(f.events.index("http.shutdown"), f.events.index("gateway.close"))
                    self.assertLess(f.events.index("http.close"), f.events.index("gateway.close"))
                    for event in ("gateway.close", "socket.close", "handshake.close"):
                        self.assertLess(f.events.index(event), f.events.index("ws.wait_closed"))
                    self.assertLess(f.events.index("ws.wait_closed"), f.events.index("camera.close"))
                    if token:
                        f.adapter_factory.assert_called_once()
                        f.adapter.handler.assert_awaited_once_with(f.socket)
                        f.socket.close.assert_not_awaited()
                        self.assertIs(f.adapter.camera_capture, f.camera.capture)
                        self.assertIs(f.adapter.selected_ground_range, f.camera.selected_ground_range)
                        self.assertIs(f.adapter.depth_demand, f.camera.depth_demand)
                    else:
                        f.adapter_factory.assert_not_called()
                        f.socket.close.assert_awaited_once_with(code=1008,
                            reason="wrong or unavailable endpoint")

    async def test_entrypoint_cancellation_releases_acquired_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.startup_fixture(Path(directory), stop_at_serve=False) as f:
                task = asyncio.create_task(gateway_main._run_production(f.args))
                try:
                    await asyncio.wait_for(f.listening.wait(), 1)
                    # The serve fake has returned; the owner is awaiting its stop future.
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertTrue(task.cancelled())
                    f.server.close.assert_called_once()
                    f.gateway.close.assert_awaited_once()
                    f.established.close.assert_awaited_once_with(1001, "gateway stopped")
                    f.handshake.transport.close.assert_called_once()
                    f.server.wait_closed.assert_awaited_once()
                    f.dashboard.shutdown.assert_called_once()
                    f.dashboard.server_close.assert_called_once()
                    f.thread.join.assert_called_once_with(timeout=2.0)
                    self.assertEqual(f.events.count("signal.restore"), 1)
                    f.dashboard.close_freestyle.assert_awaited_once()
                    f.camera.aclose.assert_awaited_once()
                    f.dashboard.host_audio.close.assert_awaited_once()
                    self.assertLess(f.events.index("http.shutdown"), f.events.index("gateway.close"))
                    self.assertLess(f.events.index("ws.wait_closed"), f.events.index("camera.close"))
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def check_startup_failures(self, cases):
        for failure, dashboard, thread, camera, signal in cases:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                with self.startup_fixture(Path(directory), failure=failure) as f:
                    with self.assertRaisesRegex(RuntimeError, "Fixture failure: " + failure):
                        await gateway_main._run_production(f.args)
                    self.assertEqual(f.gateway.close.await_count, 0 if failure == "gateway.create" else 1)
                    self.assertEqual(f.dashboard.close_freestyle.await_count, int(dashboard))
                    self.assertEqual(f.dashboard.host_audio.close.await_count, int(dashboard))
                    self.assertEqual(f.dashboard.server_close.call_count, int(dashboard))
                    self.assertEqual(f.dashboard.shutdown.call_count, int(thread))
                    self.assertEqual(f.thread.join.call_count, int(thread))
                    self.assertEqual(f.camera.aclose.await_count, int(camera))
                    self.assertEqual(f.events.count("signal.restore"), int(signal))
                    f.server.wait_closed.assert_not_awaited()

    async def test_early_startup_failures_release_acquired_resources(self):
        # failure, dashboard returned, HTTP started, camera returned, signal installed
        await self.check_startup_failures([
            ("gateway.create", False, False, False, False),
            ("dashboard.create", False, False, False, False),
            ("freestyle.start", True, False, False, False),
            ("http.start", True, False, False, False),
            ("camera.create", True, True, False, False),
            ("camera.ground", True, True, True, False),
            ("camera.depth", True, True, True, False),
        ])

    async def test_late_startup_failures_release_acquired_resources(self):
        await self.check_startup_failures([
            ("signal.install", True, True, True, False),
            ("hotspot.start", True, True, True, True),
            ("ws.bind", True, True, True, True),
        ])

    async def test_failed_camera_close_preserves_other_releases_and_error_context(self):
        for startup_failure in (None, "ws.bind"):
            with self.subTest(startup_failure=startup_failure), tempfile.TemporaryDirectory() as directory:
                with self.startup_fixture(Path(directory), failure=startup_failure,
                        cleanup_failure="camera.close") as f:
                    with self.assertRaisesRegex(RuntimeError, "Fixture failure: camera.close") as caught:
                        await gateway_main._run_production(f.args)
                    f.gateway.close.assert_awaited_once()
                    f.camera.aclose.assert_awaited_once()
                    f.dashboard.close_freestyle.assert_awaited_once()
                    f.dashboard.host_audio.close.assert_awaited_once()
                    f.dashboard.shutdown.assert_called_once()
                    f.dashboard.server_close.assert_called_once()
                    f.thread.join.assert_called_once_with(timeout=2.0)
                    self.assertEqual(f.events.count("signal.restore"), 1)
                    if startup_failure:
                        self.assertIsInstance(caught.exception.__context__, RuntimeError)
                        self.assertEqual(str(caught.exception.__context__), "Fixture failure: ws.bind")
                    else:
                        f.server.close.assert_called_once()
                        f.server.wait_closed.assert_awaited_once()
                        f.established.close.assert_awaited_once()
                        f.handshake.transport.close.assert_called_once()

    async def test_handshake_close_failure_attempts_all_socket_orders_without_orphans(self):
        for order in permutations(("established", "failing", "remaining")):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as directory:
                with self.startup_fixture(Path(directory), cleanup_failure="handshake.close") as f:
                    remaining = SimpleNamespace(open=False, closed=False,
                        transport=SimpleNamespace(close=Mock()))
                    sockets = {"established": f.established,
                               "failing": f.handshake, "remaining": remaining}
                    f.server.websockets = tuple(sockets[name] for name in order)
                    with warnings.catch_warnings(record=True) as emitted:
                        warnings.simplefilter("always", RuntimeWarning)
                        with self.assertRaisesRegex(RuntimeError, "Fixture failure: handshake.close"):
                            await gateway_main._run_production(f.args)
                        gc.collect()
                        f.established.close.assert_awaited_once_with(1001, "gateway stopped")
                        f.handshake.transport.close.assert_called_once()
                        remaining.transport.close.assert_called_once()
                        f.server.wait_closed.assert_awaited_once()
                        f.camera.aclose.assert_awaited_once()
                        self.assertFalse([warning for warning in emitted
                            if issubclass(warning.category, RuntimeWarning)
                            and "was never awaited" in str(warning.message)])

    async def test_socket_cleanup_drains_concurrent_closes_and_reports_each_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.startup_fixture(Path(directory), cleanup_failure="handshake.close") as f:
                entered = [asyncio.Event(), asyncio.Event()]
                release = asyncio.Event()

                async def close_first(*args):
                    entered[0].set()
                    await release.wait()

                async def close_second(*args):
                    entered[1].set()
                    await release.wait()
                    raise OSError("Fixture established release failed")

                f.established.close.side_effect = close_first
                other = SimpleNamespace(open=True, closed=False,
                    close=AsyncMock(side_effect=close_second))
                f.server.websockets = (f.handshake, f.established, other)
                task = asyncio.create_task(gateway_main._run_production(f.args))
                try:
                    # Both closes must enter before either can finish.
                    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 1)
                    f.server.wait_closed.assert_not_awaited()
                    f.camera.aclose.assert_not_awaited()
                    release.set()
                    with self.assertRaises(ExceptionGroup) as caught:
                        await task
                    self.assertEqual({str(error) for error in caught.exception.exceptions}, {
                        "Fixture failure: handshake.close", "Fixture established release failed"})
                    self.assertEqual(len(caught.exception.exceptions), 2)
                    f.established.close.assert_awaited_once_with(1001, "gateway stopped")
                    other.close.assert_awaited_once_with(1001, "gateway stopped")
                    f.handshake.transport.close.assert_called_once()
                    f.server.wait_closed.assert_awaited_once()
                    f.camera.aclose.assert_awaited_once()
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_cleanup_errors_do_not_skip_independent_finalizers(self):
        for failure in ("http.shutdown", "http.close", "http.join", "ws.close",
                        "gateway.close", "socket.close", "ws.wait_closed",
                        "signal.restore", "freestyle.close", "camera.close"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                with self.startup_fixture(Path(directory), cleanup_failure=failure) as f:
                    with self.assertRaisesRegex(RuntimeError, "Fixture failure: " + failure):
                        await gateway_main._run_production(f.args)
                    for event in ("http.shutdown", "http.close", "http.join", "ws.close",
                                  "gateway.close", "socket.close", "handshake.close",
                                  "ws.wait_closed", "signal.restore", "freestyle.close",
                                  "camera.close", "audio.close"):
                        self.assertEqual(f.events.count(event), 1, event)

if __name__ == "__main__":
    unittest.main()
