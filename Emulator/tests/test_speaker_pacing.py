"""Cached PCM must fit the body's bounded playback queue, including cancellation."""
from __future__ import annotations
import asyncio
import json
import unittest
from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig


class SpeakerPacingTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, *, cancel_after=None):
        class Socket:
            closed = False
            def __init__(self):
                self.frame_times = []
                self.controls = []
            async def send(inner, payload):
                if isinstance(payload, bytes):
                    inner.frame_times.append(asyncio.get_running_loop().time())
                    if cancel_after and len(inner.frame_times) == cancel_after:
                        await connection._handle_control({"t": "cancelled", "seq": 1, "code": "stop"})
                else:
                    message = json.loads(payload)
                    inner.controls.append(message)
                    await connection._handle_control({"t": "ack", "seq": message["seq"]})
        service = GatewayService(GatewayServiceConfig(tokens={"p4": "test"}), clock=lambda: 100.0)
        socket = Socket()
        connection = GatewayConnection(service, socket, "p4", 1)
        service._connections["p4"] = connection
        return connection, socket

    async def test_multi_second_cached_pcm_is_paced_on_real_monotonic_clock(self):
        connection, socket = self.connection()
        await connection.send_tts([bytes(640)] * 110, received_at=100.0)
        self.assertEqual(len(socket.frame_times), 110)
        self.assertGreaterEqual(socket.frame_times[-1] - socket.frame_times[0], 2.07)
        self.assertGreaterEqual(socket.frame_times[5] - socket.frame_times[0], 0.014)
        self.assertEqual([message["op"] for message in socket.controls], ["start", "end"])

    async def test_midstream_cancel_stops_frames_without_sending_end(self):
        connection, socket = self.connection(cancel_after=7)
        with self.assertRaisesRegex(GatewayError, "cancelled"):
            await connection.send_tts([bytes(640)] * 150, received_at=100.0)
        self.assertEqual(len(socket.frame_times), 7)
        self.assertEqual([message["op"] for message in socket.controls], ["start"])

    async def test_slow_async_source_cannot_trigger_unbounded_catch_up_burst(self):
        connection, socket = self.connection()
        async def source():
            for _ in range(5):
                yield bytes(640)
            await asyncio.sleep(0.25)
            for _ in range(15):
                yield bytes(640)
        await connection.send_tts(source(), received_at=100.0)
        self.assertGreaterEqual(socket.frame_times[10] - socket.frame_times[5], 0.014)
        self.assertGreaterEqual(socket.frame_times[-1] - socket.frame_times[5], 0.19)

    async def test_failed_pcm_producer_cancels_device_stream(self):
        connection, socket = self.connection()
        def source():
            yield bytes(640)
            raise ValueError("synthesis failed")
        with self.assertRaisesRegex(ValueError, "synthesis failed"):
            await connection.send_tts(source(), received_at=100.0)
        self.assertEqual([message["op"] for message in socket.controls], ["start", "cancel"])
        self.assertEqual(len(socket.frame_times), 1)

    async def test_caller_cancel_stops_sender_and_cancels_device_stream(self):
        connection, socket = self.connection()
        task = asyncio.create_task(connection.send_tts([bytes(640)] * 150, received_at=100.0))
        while len(socket.frame_times) < 6:
            await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual([message["op"] for message in socket.controls], ["start", "cancel"])
        self.assertLessEqual(len(socket.frame_times), 7)
