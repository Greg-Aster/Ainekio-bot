from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from gateway.security import DashboardPasswordStore, RobotTokenStore


class GatewaySecurityTests(unittest.TestCase):
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

    def test_invalid_store_fails_closed(self) -> None:
        path = self.root / "robot-tokens.json"
        path.write_text('{"schema_version":1,"tokens":{"robot":42}}', encoding="utf-8")
        os.chmod(path, 0o600)

        with self.assertRaisesRegex(RuntimeError, "invalid entry"):
            RobotTokenStore(path)


if __name__ == "__main__":
    unittest.main()
