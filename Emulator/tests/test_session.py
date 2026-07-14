from __future__ import annotations

import asyncio
import unittest
from collections.abc import Mapping

from emulator.body import BodySession, PortableCore
from Emulator.tests.support import build_core_library


class ControlledMotionBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.messages: list[dict[str, object]] = []
        self.failure: Exception | None = None
        self.stop_failure: Exception | None = None
        self.stop_release: asyncio.Event | None = None

    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        self.messages.append(dict(message))
        self.started.set()
        if self.failure is not None:
            raise self.failure
        await self.release.wait()

    async def stop(self, sequence: int, *, session_id: str) -> None:
        self.messages.append({"t": "stop", "seq": sequence})
        if self.stop_failure is not None:
            raise self.stop_failure
        if self.stop_release is not None:
            await self.stop_release.wait()


class BodySessionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def asyncSetUp(self) -> None:
        self.core = PortableCore(self.library_path)
        self.backend = ControlledMotionBackend()
        self.session = BodySession(self.core, self.backend)
        self.messages: list[dict[str, object]] = []
        await self.session.begin({"t": "welcome", "ver": 1, "epoch": 9, "profile": "home"})

    async def asyncTearDown(self) -> None:
        await self.session.close()
        self.core.close()

    async def emit(self, message: dict[str, object]) -> None:
        self.messages.append(message)

    async def test_movement_acks_then_completes(self) -> None:
        self.backend.release.set()

        await self.session.handle({"t": "intent", "seq": 1, "name": "stand"}, self.emit)
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [{"t": "ack", "seq": 1}, {"t": "done", "seq": 1}],
        )
        self.assertEqual(self.backend.messages[0]["name"], "stand")

    async def test_stop_cancels_active_movement_and_detaches(self) -> None:
        walk = {"t": "intent", "seq": 1, "name": "walk", "dir": "fwd", "steps": 10}
        await self.session.handle(walk, self.emit)
        await self.backend.started.wait()

        await self.session.handle({"t": "stop", "seq": 2}, self.emit)

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "cancelled", "seq": 1, "code": "stop"},
            ],
        )
        self.assertFalse(self.core.servos_attached)
        self.assertIsNone(self.session.active_sequence)
        self.assertEqual(self.backend.messages[-1], {"t": "stop", "seq": 2})

    async def test_renderer_failure_never_reports_done(self) -> None:
        self.backend.failure = RuntimeError("renderer unavailable")

        await self.session.handle({"t": "intent", "seq": 1, "name": "stand"}, self.emit)
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "cancelled", "seq": 1, "code": "overflow"},
            ],
        )
        self.assertNotIn({"t": "done", "seq": 1}, self.messages)

    async def test_renderer_failure_cannot_block_or_reject_stop(self) -> None:
        self.backend.stop_failure = RuntimeError("renderer unavailable")

        await self.session.handle({"t": "stop", "seq": 1}, self.emit)

        self.assertEqual(self.messages, [{"t": "ack", "seq": 1}])
        self.assertFalse(self.core.servos_attached)

    async def test_renderer_timeout_cannot_block_stop(self) -> None:
        self.backend.stop_release = asyncio.Event()

        await asyncio.wait_for(
            self.session.handle({"t": "stop", "seq": 1}, self.emit),
            timeout=0.2,
        )

        self.assertEqual(self.messages, [{"t": "ack", "seq": 1}])
        self.assertFalse(self.core.servos_attached)

    async def test_unavailable_capability_is_bounded_and_claims_sequence(self) -> None:
        await self.session.handle(
            {"t": "cam", "seq": 3, "on": True, "fps": 5, "res": "VGA"},
            self.emit,
        )
        await self.session.handle({"t": "intent", "seq": 3, "name": "stand"}, self.emit)

        self.assertEqual(self.messages[0]["code"], "busy")
        self.assertEqual(self.messages[1], {"t": "nak", "seq": 3, "code": "stale"})

    async def test_unknown_intent_returns_unknown_without_execution(self) -> None:
        await self.session.handle({"t": "intent", "seq": 1, "name": "jump"}, self.emit)

        self.assertEqual(self.messages, [{"t": "nak", "seq": 1, "code": "unknown"}])
        self.assertEqual(self.backend.messages, [])


if __name__ == "__main__":
    unittest.main()
