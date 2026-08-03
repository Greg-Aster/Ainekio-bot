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

    def test_explicit_password_replaces_existing_verifier(self) -> None:
        path = self.root / "dashboard-auth.json"
        store = DashboardPasswordStore(path)
        old_password = "old-dashboard-password"
        new_password = "new-dashboard-password"

        store.initialize(password=old_password)
        self.assertEqual(store.initialize(password=new_password), new_password)
        self.assertFalse(store.verify(old_password))
        self.assertTrue(store.verify(new_password))

    def test_invalid_store_fails_closed(self) -> None:
        path = self.root / "robot-tokens.json"
        path.write_text('{"schema_version":1,"tokens":{"robot":42}}', encoding="utf-8")
        os.chmod(path, 0o600)

        with self.assertRaisesRegex(RuntimeError, "invalid entry"):
            RobotTokenStore(path)


if __name__ == "__main__":
    unittest.main()
