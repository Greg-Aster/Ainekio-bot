from __future__ import annotations

import asyncio
import json
import struct
import unittest
from collections.abc import Mapping
from time import monotonic

import websockets

from emulator.body import BodySession, PortableCore
from emulator.body.client import BodyClientConfig, HandshakeRejected, ProtocolV1BodyClient
from gateway.server.service import (
    ActionExpiredError,
    GatewayError,
    GatewayClock,
    GatewayConnection,
    GatewayService,
    GatewayServiceConfig,
    RobotOfflineError,
)
from gateway.plugins import AudioTranscriptPlugin, CameraFramePlugin
from emulator.body.media import FixtureCameraSource, QueueMicrophoneSource
from Emulator.tests.support import build_core_library


class ImmediateMotionBackend:
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        return None

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


class GatewayServiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def test_gateway_api_tracks_command_lifecycle(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            sequence = await service.queue_intent("stand")
            terminal = await service.wait_terminal(sequence)

            self.assertEqual(sequence, 1)
            self.assertEqual(terminal, {"t": "done", "seq": 1})
            self.assertEqual(service.terminals[-1]["epoch"], 1)

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_freshness_is_checked_before_sequence_assignment(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                max_action_age_ms=100,
            )
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            with self.assertRaises(ActionExpiredError):
                await service.queue_intent("stand", received_at=monotonic() - 1.0)

            sequence = await service.set_profile("tether")
            terminal = await service.wait_terminal(sequence)
            self.assertEqual(sequence, 1)
            self.assertEqual(terminal, {"t": "ack", "seq": 1})

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_gateway_persists_disabled_wake_configuration_on_body(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            sequence = await service.set_wake_configuration(
                enabled=False,
                model="ainekio",
            )
            self.assertEqual(
                await service.wait_terminal(sequence),
                {"t": "ack", "seq": sequence},
            )
            self.assertEqual(
                session.wake_settings,
                {"enabled": False, "model": "ainekio", "ready": False},
            )

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_tts_api_preserves_start_frames_end_order(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            start_sequence = await service.tts_speak([bytes(640), bytes(640)])
            terminal = await service.wait_terminal(start_sequence)

            self.assertEqual(start_sequence, 1)
            self.assertEqual(terminal, {"t": "done", "seq": 1})
            self.assertEqual(service.terminals[-1]["seq"], 1)

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_wrong_token_and_offline_actions_are_rejected(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "correct-token"})
        )
        with self.assertRaises(RobotOfflineError):
            await service.queue_intent("stand")

        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="wrong-token",
                ),
                session,
            )
            with self.assertRaises(HandshakeRejected):
                await client.run_once()

        core.close()

    async def test_duplicate_connection_cancels_old_epoch_and_closes_4000(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/robot"
            first = await websockets.connect(uri, ping_interval=None)
            await first.send(
                json.dumps(
                    {
                        "t": "hello",
                        "ver": 1,
                        "fw": "test",
                        "id": "ainekio-test-01",
                        "auth": "test-token",
                    }
                )
            )
            self.assertEqual(json.loads(await first.recv())["epoch"], 1)
            sequence = await service.queue_intent("stand")
            command = json.loads(await first.recv())
            self.assertEqual(command["seq"], sequence)
            await first.send(json.dumps({"t": "ack", "seq": sequence}))

            second = await websockets.connect(uri, ping_interval=None)
            await second.send(
                json.dumps(
                    {
                        "t": "hello",
                        "ver": 1,
                        "fw": "test",
                        "id": "ainekio-test-01",
                        "auth": "test-token",
                    }
                )
            )
            self.assertEqual(json.loads(await second.recv())["epoch"], 2)
            await first.wait_closed()

            self.assertEqual(first.close_code, 4000)
            self.assertEqual(
                service.terminals[-1]["result"],
                {"t": "cancelled", "seq": sequence, "code": "reconnect"},
            )
            await second.close()

    async def test_token_revocation_closes_active_socket_and_rejects_reconnect(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/robot"
            socket = await websockets.connect(uri, ping_interval=None)
            hello = {
                "t": "hello",
                "ver": 1,
                "fw": "test",
                "id": "ainekio-test-01",
                "auth": "test-token",
            }
            await socket.send(json.dumps(hello))
            await socket.recv()

            await service.revoke_token("ainekio-test-01")
            await socket.wait_closed()
            self.assertEqual(socket.close_code, 4001)

            rejected = await websockets.connect(uri, ping_interval=None)
            await rejected.send(json.dumps(hello))
            self.assertEqual(json.loads(await rejected.recv()), {"t": "err", "code": "auth"})
            await rejected.wait_closed()
            self.assertEqual(rejected.close_code, 4001)

    async def test_vad_pcm_reaches_stubbed_transcriber(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        transcript_ready = asyncio.Event()
        transcripts: list[dict[str, object]] = []

        def receive_transcript(transcript: dict[str, object]) -> None:
            transcripts.append(transcript)
            transcript_ready.set()

        service.subscribe_transcripts(receive_transcript)
        AudioTranscriptPlugin(service, lambda _payload: "fixture transcript")
        microphone = QueueMicrophoneSource(
            [struct.pack("<320h", *([1200] * 320))]
        )
        core = PortableCore(self.library_path)
        session = BodySession(
            core,
            ImmediateMotionBackend(),
            microphone_source=microphone,
        )

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")
            sequence = await service.set_microphone(on=True, gate="vad")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": sequence})
            await asyncio.wait_for(transcript_ready.wait(), timeout=2.0)

            self.assertEqual(transcripts[0]["text"], "fixture transcript")
            self.assertEqual(transcripts[0]["counter"], 0)
            await service.revoke_token("ainekio-test-01")
            await client_task
        core.close()

    async def test_camera_frame_reaches_camera_plugin(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        frame_ready = asyncio.Event()
        payloads: list[bytes] = []

        def consume(payload: bytes) -> None:
            payloads.append(payload)
            frame_ready.set()

        CameraFramePlugin(service, consume)
        camera = FixtureCameraSource(b"\xff\xd8fixture\xff\xd9")
        core = PortableCore(self.library_path)
        session = BodySession(
            core,
            ImmediateMotionBackend(),
            camera_source=camera,
        )
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")
            sequence = await service.set_camera(on=True, fps=5, resolution="VGA")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": sequence})
            await asyncio.wait_for(frame_ready.wait(), timeout=2.0)

            self.assertEqual(payloads, [b"\xff\xd8fixture\xff\xd9"])
            await service.revoke_token("ainekio-test-01")
            await client_task
        core.close()

    async def test_gateway_refuses_out_of_profile_media_before_assigning_sequence(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                profile="tether",
            )
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            with self.assertRaises(GatewayError):
                await service.set_camera(on=True, fps=1, resolution="QVGA")
            with self.assertRaises(GatewayError):
                await service.set_microphone(on=True, gate="open")
            self.assertEqual(service.status()["robots"]["ainekio-test-01"]["next_sequence"], 1)

            sequence = await service.set_camera(on=True, fps=0, resolution="QVGA")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": 1})
            await service.revoke_token("ainekio-test-01")
            await client_task
        core.close()

    async def test_wall_clock_jump_does_not_change_monotonic_freshness(self) -> None:
        class Socket:
            closed = False

            def __init__(self) -> None:
                self.sent: list[object] = []

            async def send(self, payload: object) -> None:
                self.sent.append(payload)

        now = [10.0]
        clock = GatewayClock(
            monotonic_clock=lambda: now[0],
            wall_clock=lambda: 1000.0,
        )
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                max_action_age_ms=100,
            ),
            clock_source=clock,
        )
        connection = GatewayConnection(service, Socket(), "ainekio-test-01", 1)
        service._connections["ainekio-test-01"] = connection

        service.jump_wall_clock(86400.0)
        self.assertEqual(clock.wall_time(), 87400.0)
        self.assertEqual(
            await service.queue_intent("stand", received_at=10.0),
            1,
        )

        now[0] = 10.2
        with self.assertRaises(ActionExpiredError):
            await service.queue_intent("stand", received_at=10.0)


if __name__ == "__main__":
    unittest.main()
