from __future__ import annotations

import unittest

from gateway.environment_adapter.server import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.translation import (
    SEED_EMOTES,
    SUPPORTED_ROBOT_COMMANDS,
    translate_environment_action,
)


class FakeGateway:
    def subscribe_events(self, _callback: object) -> None:
        return None

    def subscribe_frames(self, _callback: object) -> None:
        return None

    def subscribe_transcripts(self, _callback: object) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {}


class EnvironmentCommandCatalogTests(unittest.TestCase):
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

    def test_environment_observation_advertises_the_owned_command_catalog(self) -> None:
        adapter = EnvironmentAdapter(
            FakeGateway(),  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        capabilities = adapter._observation()["capabilities"]
        self.assertEqual(
            capabilities["robotCommands"],  # type: ignore[index]
            list(SUPPORTED_ROBOT_COMMANDS),
        )


if __name__ == "__main__":
    unittest.main()
