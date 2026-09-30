from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gateway.security import RobotTokenStore
from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.control_v1 import ProtocolValidationError, validate_control_message


class RobotSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tokens.json"
        self.store = RobotTokenStore(self.path)
        self.store.set("robot", "old-token")
        self.service = GatewayService(GatewayServiceConfig(tokens=self.store.snapshot()), token_store=self.store)
        self.sent, self.published = [], []
        self.service.subscribe_commands(self.published.append)
        test = self

        class Socket:
            closed = False
            async def send(self, text):
                message = json.loads(text)
                test.sent.append(message)
                if test.reject:
                    await test.connection._handle_control({"t": "nak", "seq": message["seq"], "code": "busy"})
                    return
                await test.connection._handle_control({"t": "ack", "seq": message["seq"]})
                # ACK alone must not settle a save or claim device persistence.
                test.assertIn(message["seq"], test.connection.pending)
                await test.connection._handle_control({
                    "t": "robot_settings_status", "seq": message["seq"], "revision": 1,
                    "active_index": 0, "pending_restart": True, "setup_open": False,
                    "networks": [{"index": 0, "ssid": "Home", "endpoint": "ws://home:8790/robot", "open": False}],
                })
        self.reject = False
        self.connection = GatewayConnection(self.service, Socket(), "robot", 1,
            features=("robot_settings_v1",), model="v2-12servo")
        self.service._connections["robot"] = self.connection

    async def test_network_update_waits_for_readback_and_redacts_secrets(self):
        result = await self.service.body_robot_settings("network", {
            "revision": 0, "index": 1, "ssid": "Hotspot", "endpoint": "ws://10.42.77.1:8790/robot",
            "wifi_password": "wifi-secret",
        }, robot_id="robot")
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["networks"][0]["ssid"], "Home")  # body readback, not request echo
        self.assertEqual(self.sent[0]["wifi_password"], "wifi-secret")
        self.assertNotIn("wifi-secret", json.dumps(self.published))
        self.assertNotIn("wifi-secret", json.dumps(self.service.status()))
        self.assertFalse(self.connection.pending)

    async def test_older_firmware_rejected_before_send_or_staging(self):
        self.connection.features = ()
        with self.assertRaisesRegex(GatewayError, "firmware"):
            await self.service.body_robot_settings("security", {"revision": 0, "robot_token": "new-token"}, robot_id="robot")
        self.assertFalse(self.sent)
        self.assertFalse(RobotTokenStore(self.path).matches("robot", "new-token"))

    async def test_token_change_survives_host_restart_and_promotes_on_new_login(self):
        await self.service.body_robot_settings("security", {
            "revision": 0, "robot_token": "new-token", "setup_password": "setup-secret",
        }, robot_id="robot")
        restored = RobotTokenStore(self.path)
        self.assertTrue(restored.matches("robot", "old-token"))
        self.assertTrue(restored.matches("robot", "new-token"))
        self.assertFalse(RobotTokenStore(self.path).matches("robot", "old-token"))
        self.assertNotIn("new-token", json.dumps(self.published))
        self.assertNotIn("setup-secret", json.dumps(self.published))

    async def test_rejected_token_change_keeps_recovery_credentials_after_possible_flash_failure(self):
        self.reject = True
        with self.assertRaises(GatewayError):
            await self.service.body_robot_settings("security", {"revision": 0, "robot_token": "new-token"}, robot_id="robot")
        self.assertTrue(self.store.matches("robot", "old-token"))
        self.assertTrue(RobotTokenStore(self.path).matches("robot", "new-token"))

    async def test_ambiguous_timeout_preserves_both_tokens_for_recovery(self):
        async def drop_reply(text):
            self.sent.append(json.loads(text))
        self.connection.websocket.send = drop_reply
        async def timeout(*args, **kwargs):
            raise TimeoutError()
        with patch.object(self.connection, "wait_terminal", timeout):
            with self.assertRaisesRegex(GatewayError, "unknown"):
                await self.service.body_robot_settings("security", {"revision": 0, "robot_token": "new-token"}, robot_id="robot")
        restored = RobotTokenStore(self.path)
        self.assertTrue(restored.matches("robot", "old-token"))
        self.assertTrue(restored.matches("robot", "new-token"))
        self.assertFalse(self.connection.pending)

    def test_protocol_validates_bytes_and_wifi_requirements(self):
        base = {"t": "robot_settings", "seq": 1, "op": "network", "revision": 0,
                "index": 0, "ssid": "Home", "endpoint": "ws://home:8790/robot"}
        for password in ("", "12345678", "a" * 63, "a" * 64):
            validate_control_message({**base, "wifi_password": password})
        for fields in ({"wifi_password": "short"}, {"wifi_password": "z" * 64}, {"ssid": "é" * 17},
                       {"ssid": "bad\0ssid"}, {"endpoint": "ws://user:pass@host/robot"}, {"index": 4}):
            with self.subTest(fields=fields), self.assertRaises(ProtocolValidationError):
                validate_control_message({**base, **fields})
        with self.assertRaises(ProtocolValidationError):
            validate_control_message({"t": "robot_settings", "seq": 1, "op": "apply"})

    def test_revocation_and_failed_write_preserve_correct_credentials(self):
        self.store.stage("robot", "new-token")
        with patch("gateway.security._atomic_secure_json", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.matches("robot", "new-token")
        restored = RobotTokenStore(self.path)
        self.assertTrue(restored.matches("robot", "old-token"))
        restored.revoke("robot")
        self.assertFalse(RobotTokenStore(self.path).matches("robot", "new-token"))
