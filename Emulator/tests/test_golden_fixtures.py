from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from emulator.body import BodySession, PortableCore
from protocol.control_v1 import validate_control_message
from Emulator.tests.support import ROOT, build_core_library


_BRAIN_TO_BODY = frozenset(
    {
        "intent",
        "stop",
        "tts",
        "cam",
        "snap",
        "mic",
        "wake",
        "profile",
        "state",
        "ping",
        "mode",
        "servo",
        "limits",
        "pose_save",
        "cal_save",
    }
)


class ImmediateMotionBackend:
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        return None

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


def _fixture(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


class GoldenFixtureConsumptionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def test_emulator_consumes_every_brain_to_body_valid_fixture(self) -> None:
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        await session.begin({"t": "welcome", "ver": 1, "epoch": 20, "profile": "home"})
        emitted: list[dict[str, object]] = []

        async def emit(message: dict[str, object]) -> None:
            validate_control_message(message)
            emitted.append(message)

        cases = _fixture(
            ROOT / "Slave" / "software" / "protocol" / "fixtures" / "control-valid-v1.json"
        )
        commands = [case["message"] for case in cases if case["message"].get("t") in _BRAIN_TO_BODY]
        for command in commands:
            before = len(emitted)
            await session.handle(command, emit)
            await session.wait_until_idle()
            self.assertGreater(len(emitted), before, msg=str(command))

        await session.close()
        core.close()

    async def test_emulator_rejects_every_invalid_fixture_without_execution(self) -> None:
        cases = _fixture(
            ROOT / "Slave" / "software" / "protocol" / "fixtures" / "control-invalid-v1.json"
        )
        for case in cases:
            core = PortableCore(self.library_path)
            session = BodySession(core, ImmediateMotionBackend())
            await session.begin({"t": "welcome", "ver": 1, "epoch": 21, "profile": "home"})
            emitted: list[dict[str, object]] = []

            async def emit(message: dict[str, object]) -> None:
                validate_control_message(message)
                emitted.append(message)

            await session.handle(case["message"], emit)
            self.assertEqual(emitted[0]["t"], "nak", msg=case["name"])
            await session.close()
            core.close()


if __name__ == "__main__":
    unittest.main()
