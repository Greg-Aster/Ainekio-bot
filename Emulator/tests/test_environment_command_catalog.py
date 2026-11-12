from __future__ import annotations

import asyncio
import unittest

from gateway.environment_adapter.server import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.translation import (
    locomotion_commands,
    translate_environment_action,
)


class FakeGateway:
    instance_id = "fixture-gateway"

    def subscribe_events(self, _callback: object) -> None:
        return None

    def subscribe_external_speech(self, callback):
        pass

    def subscribe_frames(self, _callback: object) -> None:
        return None

    def subscribe_transcripts(self, _callback: object) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {}


class ConnectedGateway(FakeGateway):
    def status(self) -> dict[str, object]:
        return {
            "robots": {
                "test-body": {
                    "connected": True,
                    "heartbeat_age_ms": 25,
                    "features": [],
                    "status": {"camera_ready": True},
                }
            }
        }


class EnvironmentCommandCatalogTests(unittest.TestCase):
    def test_send_text_preserves_the_complete_message_through_gateway_delivery(self) -> None:
        class TranscriptGateway(FakeGateway):
            def __init__(self):
                self.transcripts = []

            async def publish_transcript(self, value):
                self.transcripts.append(value)

        gateway = TranscriptGateway()
        adapter = EnvironmentAdapter(gateway,
            EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        for index, text in enumerate(("hello", "x"*4096, "x"*4096+"retain this ending", "🌍\n"*10000+"final instruction")):
            with self.subTest(characters=len(text)):
                result = asyncio.run(adapter.handle_action({"id":f"text-{index}", "type":"sendText", "text":text}))
                self.assertEqual(result["type"], "completed")
                self.assertEqual(gateway.transcripts[-1]["text"], text)
                self.assertEqual(gateway.transcripts[-1]["source"], "environment_adapter")
                self.assertEqual(len(gateway.transcripts), index+1)
                self.assertEqual(result["actionId"], f"text-{index}")

    def test_legacy_robot_command_and_motion_plan_are_absent_and_rejected(self) -> None:
        adapter = EnvironmentAdapter(
            ConnectedGateway(),  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret", receipt_path=":memory:"),
        )
        self.addCleanup(adapter.receipts.close)
        capabilities = adapter._observation()["capabilities"]
        self.assertNotIn("robotCommands", capabilities)  # type: ignore[arg-type]
        self.assertNotIn("robotCommandDescriptions", capabilities)  # type: ignore[arg-type]
        self.assertNotIn("robotCommand", capabilities["actions"])  # type: ignore[index]
        self.assertNotIn("robotMotionPlan", capabilities["actions"])  # type: ignore[index]
        self.assertIn("requestMotion", capabilities["actions"])  # type: ignore[index]
        self.assertIn("captureImage", capabilities["actions"])  # type: ignore[index]
        self.assertEqual(locomotion_commands(["stand", "walk", "run", "crawl", "crab", "stop"], "v2-12servo"),
                         ["walk", "run", "crawl", "crab"])

        for legacy_action in (
            {"id": "legacy-cmd", "type": "robotCommand", "command": "wave"},
            {"id": "legacy-plan", "type": "robotMotionPlan", "frames": [], "endPose": "hold"},
        ):
            self.assertIsNone(translate_environment_action(legacy_action))
            result = asyncio.run(adapter.handle_action(legacy_action))
            self.assertEqual(result["type"], "rejected")
            self.assertEqual(result["message"], f"unsupported_action:{legacy_action['type']}")

    def test_offline_observation_advertises_no_body_capabilities(self) -> None:
        adapter = EnvironmentAdapter(
            FakeGateway(),  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret", receipt_path=":memory:"),
        )
        self.addCleanup(adapter.receipts.close)

        observation = adapter._observation()
        capabilities = observation["capabilities"]
        self.assertEqual(capabilities["actions"], ["sendText"])  # type: ignore[index]
        self.assertNotIn("robotCommands", capabilities)  # type: ignore[arg-type]
        self.assertNotIn("robotCommandDescriptions", capabilities)  # type: ignore[arg-type]
        self.assertFalse(capabilities["movement"])  # type: ignore[index]
        self.assertFalse(capabilities["visual"])  # type: ignore[index]
        self.assertFalse(observation["state"]["body"]["authenticated"])  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
