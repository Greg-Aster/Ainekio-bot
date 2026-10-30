from __future__ import annotations

import unittest
import asyncio

from gateway.environment_adapter.server import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.translation import (
    LEGACY_ROBOT_COMMANDS,
    ROBOT_COMMAND_DESCRIPTIONS,
    SEED_EMOTES,
    SUPPORTED_ROBOT_COMMANDS,
    translate_environment_action,
    locomotion_commands,
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

    def test_every_advertised_robot_command_translates_to_firmware_protocol(self) -> None:
        for command in SUPPORTED_ROBOT_COMMANDS:
            action_type = "stop" if command == "stop" else "robotCommand"
            translated = translate_environment_action(
                {"type": action_type, "command": command}
            )
            self.assertIsNotNone(translated, command)

        rest = translate_environment_action(
            {"type": "robotCommand", "command": "rest"}
        )
        self.assertEqual((rest.kind, rest.name, rest.params), ("intent", "emote", {"asset": "rest"}))
        self.assertTrue(SEED_EMOTES.issubset(SUPPORTED_ROBOT_COMMANDS))
        self.assertTrue(
            {
                "nod", "celebrate", "stretch", "macarena", "salsa", "surprised",
                "sad", "curious", "turn_left_45", "turn_right_45",
                "turn_left_90", "turn_right_90", "turn_left_180", "turn_right_180",
                "walk_slow", "run", "number_one", "number_two",
            }.issubset(SEED_EMOTES)
        )
        self.assertIn("#1", SUPPORTED_ROBOT_COMMANDS)
        self.assertIn("#2", SUPPORTED_ROBOT_COMMANDS)
        self.assertEqual(
            set(ROBOT_COMMAND_DESCRIPTIONS),
            set(SUPPORTED_ROBOT_COMMANDS),
        )
        self.assertTrue(all(ROBOT_COMMAND_DESCRIPTIONS.values()))
        self.assertIn("45 degrees", ROBOT_COMMAND_DESCRIPTIONS["right"])
        self.assertIn("rear-leg-lift", ROBOT_COMMAND_DESCRIPTIONS["#1"])

    def test_upright_is_distinct_from_stand_and_requires_body_declaration(self) -> None:
        self.assertNotIn("upright", LEGACY_ROBOT_COMMANDS)
        self.assertNotIn("upright", SEED_EMOTES)
        self.assertIn("four feet", ROBOT_COMMAND_DESCRIPTIONS["stand"])
        for name in ("stand", "upright"):
            translated = translate_environment_action({"type": "robotCommand", "command": name})
            self.assertEqual((translated.kind, translated.name, translated.params),
                             (("intent", "stand", {}) if name == "stand" else
                              ("intent", "emote", {"asset": name})))

    def test_environment_observation_advertises_the_owned_command_catalog(self) -> None:
        adapter = EnvironmentAdapter(
            ConnectedGateway(),  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret", receipt_path=":memory:"),
        )
        self.addCleanup(adapter.receipts.close)
        capabilities = adapter._observation()["capabilities"]
        self.assertEqual(
            capabilities["robotCommands"],  # type: ignore[index]
            [name for name in LEGACY_ROBOT_COMMANDS if name not in locomotion_commands(list(LEGACY_ROBOT_COMMANDS), None)],
        )
        self.assertEqual(
            capabilities["robotCommandDescriptions"],  # type: ignore[index]
            {
                command: ROBOT_COMMAND_DESCRIPTIONS[command]
                for command in capabilities["robotCommands"]
            },
        )
        self.assertIn("captureImage", capabilities["actions"])  # type: ignore[index]

    def test_offline_observation_advertises_no_body_capabilities(self) -> None:
        adapter = EnvironmentAdapter(
            FakeGateway(),  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret", receipt_path=":memory:"),
        )
        self.addCleanup(adapter.receipts.close)

        observation = adapter._observation()
        capabilities = observation["capabilities"]
        self.assertEqual(capabilities["actions"], ["sendText"])  # type: ignore[index]
        self.assertEqual(capabilities["robotCommands"], [])  # type: ignore[index]
        self.assertEqual(capabilities["robotCommandDescriptions"], {})  # type: ignore[index]
        self.assertFalse(capabilities["movement"])  # type: ignore[index]
        self.assertFalse(capabilities["visual"])  # type: ignore[index]
        self.assertFalse(observation["state"]["body"]["authenticated"])  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
