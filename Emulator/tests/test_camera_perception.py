from __future__ import annotations

import asyncio
import threading
import unittest

from gateway.plugins import CameraAnalysis, CameraFramePlugin
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MAX_JPEG_BYTES, MIC_PCM_FRAME_TYPE


class Socket:
    closed = False


class CameraPerceptionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 10.0
        self.gateway = GatewayService(
            GatewayServiceConfig(tokens={"robot": "test-token"}), clock=lambda: self.now,
        )
        self.gateway._connections["robot"] = GatewayConnection(self.gateway, Socket(), "robot", 1)

    def plugin(self, consume, **kwargs) -> CameraFramePlugin:
        plugin = CameraFramePlugin(self.gateway, consume, **kwargs)
        self.addAsyncCleanup(plugin.aclose)
        return plugin

    async def frame(self, frame_counter: int, **overrides) -> None:
        await self.gateway._publish_frame({
            "robot_id": "robot", "epoch": 1, "counter": frame_counter,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": str(frame_counter).encode(),
            "received_at": self.now, **overrides,
        })

    async def test_keeps_newest_waiting_frame_and_correlates_backend_output(self) -> None:
        started, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        processed, observations = [], []

        async def consume(payload):
            processed.append(payload)
            if payload == b"1":
                started.set()
                await release.wait()
            return {"description": "keys on table", "source": "replay"}

        async def observe(analysis):
            observations.append(analysis)
            if analysis.counter == 3:
                done.set()

        plugin = self.plugin(consume, observe=observe)
        await self.frame(1)
        await asyncio.wait_for(started.wait(), 1)
        await self.frame(2)
        await self.frame(3)
        release.set()
        await asyncio.wait_for(done.wait(), 1)
        self.assertEqual(processed, [b"1", b"3"])
        self.assertEqual(plugin.dropped_frames, 1)
        self.assertEqual([(item.robot_id, item.epoch, item.counter) for item in observations],
                         [("robot", 1, 1), ("robot", 1, 3)])
        self.assertIsInstance(observations[0], CameraAnalysis)
        self.assertEqual(observations[0].received_at, 10.0)
        self.assertEqual(observations[0].result["description"], "keys on table")

    async def test_synchronous_inference_does_not_block_receive_or_other_subscribers(self) -> None:
        started, release = threading.Event(), threading.Event()
        done = asyncio.Event()
        received, worker_threads = [], []
        event_loop_thread = threading.get_ident()

        def consume(payload):
            worker_threads.append(threading.get_ident())
            started.set()
            if not release.wait(2):
                raise TimeoutError("test inference was not released")
            return "keys"

        async def observe(analysis):
            done.set()

        async def subscriber(frame):
            received.append(frame["counter"])

        self.plugin(consume, observe=observe)
        self.gateway.subscribe_frames(subscriber)
        try:
            await asyncio.wait_for(self.frame(1), 1)
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            await asyncio.wait_for(self.frame(2), 1)
            self.assertEqual(received, [1, 2])
            self.assertNotEqual(worker_threads[0], event_loop_thread)
        finally:
            release.set()
        await asyncio.wait_for(done.wait(), 1)

    async def test_discards_expired_and_future_frames_before_inference(self) -> None:
        processed = []

        async def consume(payload):
            processed.append(payload)

        plugin = self.plugin(consume)
        for timestamp in (8.0, 11.0):
            await self.frame(1, received_at=timestamp)
            await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertEqual(processed, [])
        self.assertEqual(plugin.stale_frames, 2)

    async def test_discards_result_that_ages_during_inference(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()
        observations = []

        async def consume(payload):
            started.set()
            await release.wait()
            return "keys"

        plugin = self.plugin(consume, observe=observations.append)
        await self.frame(1)
        await asyncio.wait_for(started.wait(), 1)
        self.now += 1.1
        release.set()
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertEqual(observations, [])
        self.assertEqual(plugin.stale_frames, 1)

    async def test_old_session_result_cannot_be_applied_to_reconnected_robot(self) -> None:
        started, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        observations = []

        async def consume(payload):
            if payload == b"1":
                started.set()
                await release.wait()
            return "candidate"

        async def observe(analysis):
            observations.append(analysis)
            done.set()

        plugin = self.plugin(consume, observe=observe)
        await self.frame(1)
        await asyncio.wait_for(started.wait(), 1)
        self.gateway._connections["robot"] = GatewayConnection(self.gateway, Socket(), "robot", 2)
        await self.frame(2, epoch=2)
        release.set()
        await asyncio.wait_for(done.wait(), 1)
        self.assertEqual([(item.epoch, item.counter) for item in observations], [(2, 2)])
        self.assertEqual(plugin.stale_frames, 1)

    async def test_disconnected_or_stale_connection_does_not_receive_results(self) -> None:
        processed = []

        async def consume(payload):
            processed.append(payload)

        plugin = self.plugin(consume, max_frame_age_s=10)
        self.now += 4.0  # Gateway control heartbeat is stale even though image is fresh.
        await self.frame(1)
        await asyncio.wait_for(plugin._queue.join(), 1)
        del self.gateway._connections["robot"]
        await self.frame(2)
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertEqual(processed, [])
        self.assertEqual(plugin.stale_frames, 2)

    async def test_failed_inference_or_observer_does_not_kill_next_frame(self) -> None:
        processed, observed = [], []

        async def consume(payload):
            processed.append(payload)
            if payload == b"1":
                raise ValueError("fixture inference failure")
            return "candidate"

        async def observe(analysis):
            if analysis.counter == 2:
                raise RuntimeError("fixture observer failure")
            observed.append(analysis.counter)

        plugin = self.plugin(consume, observe=observe)
        with self.assertLogs("gateway.plugins", level="WARNING"):
            for counter in (1, 2):
                await self.frame(counter)
                await asyncio.wait_for(plugin._queue.join(), 1)
        await self.frame(3)
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertEqual(processed, [b"1", b"2", b"3"])
        self.assertEqual(observed, [3])
        self.assertEqual(plugin.errors, 2)

    async def test_close_unsubscribes_discards_results_and_joins_native_worker(self) -> None:
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        observations, processed = [], []

        def consume(payload):
            processed.append(payload)
            started.set()
            release.wait(2)
            finished.set()
            return "candidate"

        plugin = self.plugin(consume, observe=observations.append)
        await self.frame(1)
        self.assertTrue(await asyncio.to_thread(started.wait, 1))
        closing = asyncio.create_task(plugin.aclose())
        try:
            await asyncio.sleep(0)
            await self.frame(2)
            self.assertNotIn(plugin._handle_frame, self.gateway._frame_callbacks)
            self.assertFalse(closing.done())
            closing.cancel()  # Caller cancellation must not abandon shutdown.
            await asyncio.gather(closing, return_exceptions=True)
        finally:
            release.set()
        await asyncio.wait_for(plugin.aclose(), 1)
        self.assertTrue(finished.is_set())
        self.assertEqual(processed, [b"1"])
        self.assertEqual(observations, [])

    async def test_invalid_frames_and_other_robots_do_not_start_processing(self) -> None:
        plugin = self.plugin(lambda payload: self.fail("unexpected inference"), robot_id="robot")
        for overrides in (
            {"frame_type": MIC_PCM_FRAME_TYPE}, {"robot_id": "other"}, {"epoch": True},
            {"counter": -1}, {"payload": b"x" * (MAX_JPEG_BYTES + 1)},
            {"received_at": float("nan")}, {"received_at": True},
        ):
            await self.frame(1, **overrides)
        self.assertIsNone(plugin._worker)

    def test_freshness_limit_must_be_positive_and_finite(self) -> None:
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                CameraFramePlugin(self.gateway, lambda payload: None, max_frame_age_s=value)
