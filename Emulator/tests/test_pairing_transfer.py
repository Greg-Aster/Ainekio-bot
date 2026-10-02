from __future__ import annotations

import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from gateway.security import (DashboardPasswordStore, RobotTokenStore, check_pairing,
                              export_pairing, import_pairing, _atomic_secure_json)


class PairingTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first, self.second = self.root / "first", self.root / "second"
        self.bundle = self.root / "pairing.json"
        RobotTokenStore(self.first / "robot-tokens.json").set("robot", "shared-robot-token")
        DashboardPasswordStore(self.first / "dashboard-auth.json").set_password("same-password")

    def test_credentials_transfer_without_sessions_receipts_or_host_configuration(self):
        for name in ("dashboard-sessions.json", "environment-actions.sqlite", "operations.jsonl", ".env"):
            (self.first / name).write_text("machine-local private state")
        export_pairing(self.first, self.bundle)
        self.assertEqual(stat.S_IMODE(self.bundle.stat().st_mode), 0o600)
        self.assertNotIn("same-password", self.bundle.read_text())
        self.assertNotIn("machine-local", self.bundle.read_text())
        import_pairing(self.second, self.bundle)
        self.assertEqual({p.name for p in self.second.iterdir()}, {"robot-tokens.json", "dashboard-auth.json"})
        self.assertTrue(RobotTokenStore(self.second / "robot-tokens.json").matches("robot", "shared-robot-token"))
        self.assertTrue(DashboardPasswordStore(self.second / "dashboard-auth.json").verify("same-password"))
        for path in self.second.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        check_pairing(self.second, "robot", "")

    def test_repeated_import_preserves_existing_browser_sessions(self):
        export_pairing(self.first, self.bundle)
        import_pairing(self.second, self.bundle)
        sessions = self.second / "dashboard-sessions.json"
        sessions.write_text("existing local session")
        before = (self.second / "dashboard-auth.json").stat().st_mtime_ns
        import_pairing(self.second, self.bundle)
        self.assertEqual(before, (self.second / "dashboard-auth.json").stat().st_mtime_ns)
        self.assertEqual(sessions.read_text(), "existing local session")

    def test_pending_pairing_rotation_survives_transfer(self):
        RobotTokenStore(self.first / "robot-tokens.json").stage("robot", "new-token")
        export_pairing(self.first, self.bundle)
        import_pairing(self.second, self.bundle)
        store = RobotTokenStore(self.second / "robot-tokens.json")
        self.assertTrue(store.matches("robot", "shared-robot-token"))
        self.assertTrue(store.matches("robot", "new-token"))
        self.assertFalse(RobotTokenStore(self.second / "robot-tokens.json").matches("robot", "shared-robot-token"))

    def test_conflicting_credentials_do_not_overwrite_or_partially_import(self):
        export_pairing(self.first, self.bundle)
        DashboardPasswordStore(self.second / "dashboard-auth.json").set_password("different-password")
        with self.assertRaisesRegex(ValueError, "preserved"):
            import_pairing(self.second, self.bundle)
        self.assertFalse((self.second / "robot-tokens.json").exists())
        self.assertTrue(DashboardPasswordStore(self.second / "dashboard-auth.json").verify("different-password"))

    def test_invalid_password_or_robot_record_is_rejected_before_any_write(self):
        export_pairing(self.first, self.bundle)
        original = json.loads(self.bundle.read_text())
        for key, bad in (("dashboard_auth", {}), ("robot_tokens", {"schema_version": 1,"tokens":{"robot":42}}),
                         ("robot_tokens", {"schema_version":1,"tokens":{}}), ("kind", "other")):
            self.bundle.write_text(json.dumps({**original, key: bad}))
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                import_pairing(self.second, self.bundle)
            self.assertFalse(self.second.exists())

    def test_insecure_or_oversized_bundle_is_rejected(self):
        export_pairing(self.first, self.bundle)
        self.bundle.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "owner-only"):
            import_pairing(self.second, self.bundle)
        self.bundle.chmod(0o600)
        self.bundle.write_bytes(b" " * (64 * 1024 + 1))
        with self.assertRaisesRegex(RuntimeError, "size limit"):
            import_pairing(self.second, self.bundle)
        self.assertFalse(self.second.exists())

    def test_export_preserves_existing_file_and_rejects_symlink(self):
        self.bundle.write_text("existing file")
        with self.assertRaises(FileExistsError):
            export_pairing(self.first, self.bundle)
        self.assertEqual(self.bundle.read_text(), "existing file")
        link = self.root / "link.json"
        link.symlink_to(self.bundle)
        with self.assertRaises(FileExistsError):
            export_pairing(self.first, link)
        self.assertEqual(self.bundle.read_text(), "existing file")

    def test_partial_filesystem_failure_returns_error_and_same_import_can_finish(self):
        export_pairing(self.first, self.bundle)
        def fail_password(path, value, **kwargs):
            if path.name == "dashboard-auth.json":
                raise OSError("simulated disk failure")
            _atomic_secure_json(path, value, **kwargs)
        with patch("gateway.security._atomic_secure_json", side_effect=fail_password):
            with self.assertRaisesRegex(OSError, "disk failure"):
                import_pairing(self.second, self.bundle)
        self.assertTrue((self.second / "robot-tokens.json").exists())
        self.assertFalse((self.second / "dashboard-auth.json").exists())
        import_pairing(self.second, self.bundle)
        self.assertTrue(DashboardPasswordStore(self.second / "dashboard-auth.json").verify("same-password"))

    def test_empty_store_fails_read_only_preflight(self):
        with self.assertRaisesRegex(ValueError, "No saved robot pairing"):
            check_pairing(self.second, "robot", "")
        self.assertFalse(self.second.exists())
