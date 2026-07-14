from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gateway.bridge_client import (
    GatewayBridge,
    GatewayBridgeConfig,
    MetaHumanBridgeClient,
    translate_environment_action,
)


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.transcripts: list[dict[str, object]] = []

    async def queue_intent(
        self,
        name: str,
        params: dict[str, object],
        **kwargs: object,
    ) -> int:
        self.calls.append(("intent", (name, params, kwargs)))
        return 7

    async def estop(self, **kwargs: object) -> int:
        self.calls.append(("stop", kwargs))
        return 8

    async def wait_terminal(self, sequence: int, **kwargs: object) -> dict[str, object]:
        self.calls.append(("wait", (sequence, kwargs)))
        return {"t": "done", "seq": sequence}

    async def publish_transcript(self, transcript: dict[str, object]) -> None:
        self.transcripts.append(transcript)


class FakeBridgeClient:
    def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        return {}


class GatewayBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_translation_emits_only_bounded_semantic_commands(self) -> None:
        move = translate_environment_action(
            {"type": "move", "direction": "backward", "units": 99}
        )
        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((move.kind, move.name), ("intent", "walk"))
        self.assertEqual(move.params, {"dir": "back", "steps": 10})

        emote = translate_environment_action(
            {"type": "robotCommand", "command": "wave"}
        )
        self.assertIsNotNone(emote)
        assert emote is not None
        self.assertEqual((emote.name, emote.params), ("emote", {"asset": "wave"}))

        self.assertIsNone(
            translate_environment_action(
                {"type": "robotCommand", "command": "R1=180"}
            )
        )

    async def test_bridge_rejects_stale_control_before_sequence_assignment(self) -> None:
        gateway = FakeGateway()
        bridge = GatewayBridge(
            gateway,  # type: ignore[arg-type]
            GatewayBridgeConfig(base_url="http://127.0.0.1:4321"),
            client=FakeBridgeClient(),  # type: ignore[arg-type]
            clock=lambda: 50.0,
            utcnow=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        result = await bridge.handle_action(
            {
                "id": "action-1",
                "type": "move",
                "direction": "forward",
                "createdAt": "2000-01-01T00:00:00Z",
            },
            received_at=41.25,
        )

        self.assertEqual(result["type"], "expired")
        self.assertEqual(gateway.calls, [])

    async def test_fresh_control_uses_local_monotonic_receipt(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 14, tzinfo=timezone.utc)
        bridge = GatewayBridge(
            gateway,  # type: ignore[arg-type]
            GatewayBridgeConfig(base_url="http://127.0.0.1:4321"),
            client=FakeBridgeClient(),  # type: ignore[arg-type]
            clock=lambda: 50.0,
            utcnow=lambda: now,
        )
        result = await bridge.handle_action(
            {
                "id": "action-1",
                "type": "move",
                "direction": "forward",
                "createdAt": now.isoformat(),
            },
            received_at=41.25,
        )

        self.assertEqual(result["type"], "completed")
        intent = gateway.calls[0]
        self.assertEqual(intent[0], "intent")
        _name, _params, kwargs = intent[1]  # type: ignore[misc]
        self.assertEqual(kwargs["received_at"], 41.25)

    async def test_text_is_published_without_becoming_a_body_command(self) -> None:
        gateway = FakeGateway()
        bridge = GatewayBridge(
            gateway,  # type: ignore[arg-type]
            GatewayBridgeConfig(base_url="http://127.0.0.1:4321"),
            client=FakeBridgeClient(),  # type: ignore[arg-type]
        )

        result = await bridge.handle_action(
            {"id": "text-1", "type": "sendText", "text": "hello"}
        )

        self.assertEqual(result["type"], "completed")
        self.assertEqual(gateway.calls, [])
        self.assertEqual(gateway.transcripts[0]["text"], "hello")

    def test_bridge_clients_cannot_target_robot_deployment_socket(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTP or HTTPS"):
            MetaHumanBridgeClient("ws://127.0.0.1:8790/robot")
        with self.assertRaisesRegex(ValueError, "robot endpoint"):
            MetaHumanBridgeClient("http://127.0.0.1:8790/robot")
        with self.assertRaisesRegex(ValueError, "service token"):
            MetaHumanBridgeClient("http://127.0.0.1:4321")

        legacy_cli = Path(
            "Emulator/legacy/motion/src/ainekio_motion/cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cannot attach to the robot deployment endpoint", legacy_cli)
        self.assertNotIn("gateway.server", legacy_cli)

    def test_metahuman_client_sends_service_token(self) -> None:
        client = MetaHumanBridgeClient(
            "http://127.0.0.1:4321",
            "bridge-secret",
        )
        with patch("gateway.bridge_client.client.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            client.post_json("/api/environment-bridge/observation", {"ok": True})

        outgoing = urlopen.call_args.args[0]
        self.assertEqual(outgoing.get_header("Authorization"), "Bearer bridge-secret")


if __name__ == "__main__":
    unittest.main()
