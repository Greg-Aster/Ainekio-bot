from __future__ import annotations

import asyncio
import json
import threading
import unittest

from gateway.plugins import CameraAnalysis, CameraFramePlugin
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MAX_JPEG_BYTES, MIC_PCM_FRAME_TYPE


class Socket:
    closed = False


class CameraPerceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_image_keeps_dated_recognition_after_live_expiry(self):
        import base64
        from datetime import datetime, timedelta, timezone
        from gateway.perception import RecognitionResult, RecognizedObject

        class BridgeSocket:
            closed = False

            def __init__(self):
                self.sent = []

            async def send(self, raw):
                self.sent.append(json.loads(raw))

        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        identity = {"state": "face_match", "personId": "fixture-person", "name": "Fixture Person",
                    "trackId": "fixture-track", "faceAgeMs": 0, "similarity": .8}

        async def recognize(jpeg):
            calls.append(jpeg)
            if jpeg == b"new-frame":
                started.set()
                await release.wait()
            return RecognitionResult("fixture", "fixture", "one face match",
                (RecognizedObject("person", .9, (.1, .1, .5, .8), identity),), ())

        camera = self.plugin(recognize)
        adapter = EnvironmentAdapter(self.gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"),
            utcnow=lambda: datetime(2026, 10, 26, tzinfo=timezone.utc) + timedelta(seconds=self.now - 10))
        self.addCleanup(adapter.receipts.close)
        socket = BridgeSocket()
        adapter._websocket = socket
        adapter.camera_analysis = camera.latest_analysis
        await self.frame(9, payload=b"analyzed-frame")
        await camera._queue.join()
        self.now += 1.4
        self.assertIsNone(camera.recognition_status()["observation"], "Live status must still report expiry")

        async def read(request_id):
            await adapter._read_camera_visual({"version": 1, "requestId": request_id,
                "sessionId": adapter.config.session_id})
            return socket.sent[-1]["visual"]

        try:
            for request_id in ("first", "repeat"):
                visual = await read(request_id)
                self.assertEqual(visual["metadata"]["recognition"]["objects"][0]["identity"], identity)
                self.assertEqual(visual["metadata"]["recognition"]["frameCounter"], 9)
                self.assertEqual(visual["metadata"]["recognition"]["observedAt"], visual["timestamp"])
                self.assertEqual(visual["timestamp"], "2026-10-26T00:00:00+00:00")
                self.assertEqual(base64.b64decode(visual["dataUrl"].split(",")[1]), b"analyzed-frame")

            await self.frame(10, payload=b"new-frame")
            await started.wait()
            visual = await read("during-next-inference")
            self.assertEqual(visual["metadata"]["counter"], 9, "An unfinished frame cannot replace the analyzed pair")
            self.assertFalse(release.is_set(), "Cached reads do not wait for another inference")
            release.set()
            await camera._queue.join()
            visual = await read("next-pair")
            self.assertEqual(visual["metadata"]["counter"], 10)
            self.assertEqual(visual["metadata"]["recognition"]["frameCounter"], 10)
            self.assertEqual(base64.b64decode(visual["dataUrl"].split(",")[1]), b"new-frame")
            self.assertEqual(calls, [b"analyzed-frame", b"new-frame"])
            camera.set_enabled(False)
            self.assertNotIn("recognition", (await read("disabled"))["metadata"])
            self.gateway._connections["robot"].epoch = 2
            self.assertIsNone(await read("reconnected"), "Previous-session pixels must not cross reconnects")
        finally:
            release.set()

    async def test_requested_frame_keeps_its_recognition_while_preview_advances(self):
        from gateway.perception import RecognitionResult
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def consume(jpeg):
            calls.append(jpeg)
            if jpeg == b"1":
                started.set()
                await release.wait()
            return RecognitionResult("fixture", "fixture", jpeg.decode(), (), ())
        plugin = self.plugin(consume)
        await self.frame(1)
        await started.wait()
        frame = {"robot_id": "robot", "epoch": 1, "counter": 2,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": b"2", "received_at": self.now}
        result = plugin.capture(frame)
        await self.gateway._publish_frame(frame)
        await self.frame(3)
        await self.frame(4)
        self.assertFalse(result.done())
        release.set()
        analysis = await asyncio.wait_for(result, 1)
        await plugin._queue.join()
        self.assertEqual(calls, [b"1", b"2", b"4"])
        self.assertEqual((analysis.counter, analysis.jpeg, analysis.result.summary), (2, b"2", "2"))
        self.assertEqual(plugin.current_analysis().counter, 4)

    async def test_capture_joins_the_same_inference_even_after_frame_admission(self):
        from gateway.perception import RecognitionResult
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def consume(jpeg):
            calls.append(jpeg)
            started.set()
            await release.wait()
            return RecognitionResult("fixture", "fixture", "one frame", (), ())
        plugin = self.plugin(consume)
        frame = {"robot_id": "robot", "epoch": 1, "counter": 5,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": b"5", "received_at": self.now}
        await self.gateway._publish_frame(frame)
        await started.wait()
        result = plugin.capture(frame)
        release.set()
        self.assertEqual((await result).counter, 5)
        self.assertEqual(calls, [b"5"])

    async def test_capture_reports_failure_and_owner_close_without_losing_the_image(self):
        def broken(jpeg):
            raise ValueError("fixture recognition failure")
        plugin = self.plugin(broken)
        frame = {"robot_id": "robot", "epoch": 1, "counter": 6,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": b"6", "received_at": self.now}
        analysis = await plugin.capture(frame)
        self.assertEqual(analysis.jpeg, b"6")
        self.assertIn("fixture recognition failure", analysis.error)
        plugin.set_enabled(False)
        self.assertIsNone(plugin.capture({**frame, "counter": 7}))
        plugin.set_enabled(True)
        result = plugin.capture({k: v for k, v in {**frame, "counter": 8}.items() if not k.startswith("_")})
        await plugin.aclose()
        self.assertIn("closed", (await result).error)
        self.assertEqual(plugin._inflight, {})

    async def test_capture_finishes_with_its_dated_evidence_or_explicit_source_change(self):
        from gateway.perception import RecognitionResult
        for disconnected in (False, True):
            started, release = asyncio.Event(), asyncio.Event()
            async def consume(jpeg):
                started.set()
                await release.wait()
                return RecognitionResult("fixture", "fixture", "a person", (), ())
            plugin = self.plugin(consume)
            frame = {"robot_id": "robot", "epoch": self.gateway._connections["robot"].epoch, "counter": 9,
                "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": b"9", "received_at": self.now}
            pending = plugin.capture(frame)
            await started.wait()
            self.now += 2
            if disconnected:
                self.gateway._connections["robot"].epoch += 1
            release.set()
            result = await asyncio.wait_for(pending, 1)
            self.assertEqual(result.received_at, frame["received_at"])
            self.assertEqual(result.jpeg, b"9")
            if disconnected:
                self.assertIn("source changed", result.error)
            else:
                self.assertEqual(result.result.summary, "a person")
                self.assertIsNone(result.error)
                self.assertIsNone(plugin.current_analysis(), "An analyzed still does not renew live freshness")
                self.assertIs(plugin.latest_analysis(), result, "The dated still retains its own recognition")
                self.assertEqual(plugin.fresh_results, 0)
            self.assertEqual(plugin._inflight, {})

    async def test_prompt_configuration_shares_inference_executor_and_replaces_accepted_generation(self):
        from gateway.perception import RecognitionResult
        started, release = threading.Event(), threading.Event()
        calls, commits = [], []
        class Backend:
            query = None
            def __call__(self, jpeg):
                calls.append(("frame", jpeg, threading.get_ident()))
                if jpeg == b"1":
                    started.set(); release.wait(2)
                return RecognitionResult("fixture", "fixture", "", (), (), self.query)
            def configure_vision(self, request):
                calls.append(("configure", request, threading.get_ident()))
                self.query = request["requestId"]
                return {"queryId": self.query}
            def finalize_frame(self, result, source, counter, received_at):
                commits.append(counter)
                return result
        plugin = self.plugin(Backend())
        await self.frame(1)
        await asyncio.to_thread(started.wait, 1)
        configuration = asyncio.create_task(plugin.configure_vision({"operation": "search", "requestId": "keys"}))
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(await configuration, {"queryId": "keys"})
        await plugin._queue.join()
        self.assertEqual(commits, [], "inference begun before a target change cannot commit afterward")
        await self.frame(2)
        await plugin._queue.join()
        self.assertEqual(plugin.recognition_status()["observation"]["queryId"], "keys")
        self.assertEqual(commits, [2])
        self.assertEqual(len({call[2] for call in calls}), 1, "configuration must not create a second model worker")

    async def test_identity_commits_only_fresh_current_generation_on_existing_camera_worker(self):
        started, release = threading.Event(), threading.Event()
        commits = []
        class Backend:
            def __call__(self, jpeg):
                started.set()
                release.wait(2)
                return jpeg

            def finalize_frame(self, result, source, counter, received_at):
                commits.append((result, source, counter, received_at))
                from gateway.perception import RecognitionResult
                return RecognitionResult("fixture", "fixture", "", (), ())

        plugin = self.plugin(Backend())
        await self.frame(1)
        await asyncio.to_thread(started.wait, 1)
        plugin.set_enabled(False)
        plugin.set_enabled(True)
        release.set()
        await asyncio.wait_for(plugin._queue.join(), 2)
        self.assertEqual(commits, [], "discarded native inference must not update identity tracks")
        await self.frame(2)
        await asyncio.wait_for(plugin._queue.join(), 2)
        self.assertEqual(commits[0][1:], (("robot", 1, 2), 2, 10.0))
        self.assertEqual(plugin.recognition_status()["observation"]["frameCounter"], 2)
        self.now += 2
        self.assertIsNone(plugin.recognition_status()["observation"], "stale names must disappear from the UI")

    async def test_generic_recognition_retains_exact_image_and_complete_source_without_face_backend(self):
        from gateway.perception import RecognitionResult, RecognizedObject
        result = RecognitionResult("fixture", "objects", "Keys on a table",
            (RecognizedObject("keys", .8, (.2, .3, .1, .05)),), ())
        plugin = self.plugin(lambda jpeg: result)
        await self.frame(9)
        await plugin._queue.join()
        analysis = plugin.current_analysis("robot")
        self.assertEqual(analysis.jpeg, b"9")
        observation = plugin.recognition_status()["observation"]
        self.assertEqual((observation["robotId"], observation["epoch"], observation["frameCounter"]), ("robot", 1, 9))
        self.assertEqual(observation["gatewayInstance"], self.gateway.instance_id)
        self.assertEqual(observation["objects"][0]["label"], "keys")
        self.assertFalse(plugin.identity_status()["configured"])
        self.assertIsNone(plugin.current_analysis("other"))
        self.gateway._connections["robot"].epoch = 2
        self.assertIsNone(plugin.current_analysis("robot"), "a new session cannot borrow previous boxes or pixels")

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

    async def test_local_video_and_correlated_remote_still_share_camera_transport(self) -> None:
        class BridgeSocket:
            closed = False

            def __init__(self):
                self.sent = []

            async def send(self, raw):
                self.sent.append(json.loads(raw))

        adapter = EnvironmentAdapter(self.gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        bridge = BridgeSocket()
        adapter._websocket = bridge
        local_frames = []

        async def consume(payload):
            local_frames.append(payload)

        plugin = self.plugin(consume)
        adapter.locomotion_measurement = plugin.locomotion_measurement
        await self.gateway._publish_event({"t": "cam_meta", "robot_id": "robot", "epoch": 1,
            "res": "QVGA", "fps": 5, "counter_base": 1})
        await self.frame(1)
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertTrue(bridge.sent)
        for message in bridge.sent:
            self.assertEqual(message["type"], "environment.telemetry", "preview pixels must remain outside the remote snapshot path")
            camera = message["telemetry"]["locomotionMeasurement"]["camera"]
            self.assertTrue(camera["available"])
            self.assertEqual(camera["frameCounter"], 1)
            self.assertNotIn("jpeg", json.dumps(message))
        # Earlier P4 metadata carried preview FPS on its explicitly tagged still.
        await self.gateway._publish_event({"t": "cam_meta", "robot_id": "robot", "epoch": 1,
            "res": "XGA", "fps": 5, "counter_base": 2, "origin": "audio", "origin_id": 73})
        await self.frame(2)
        await asyncio.wait_for(plugin._queue.join(), 1)
        await self.frame(3)
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertEqual(local_frames, [b"1", b"2", b"3"])
        observations = [message["observation"] for message in bridge.sent if message["type"] == "environment.observation"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["visual"]["metadata"]["counter"], 2)
        self.assertIn("audioUtteranceId", observations[0]["visual"]["metadata"])

    async def test_requested_and_action_stills_use_origin_even_when_preview_is_enabled(self) -> None:
        adapter = EnvironmentAdapter(self.gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        for origin in ("request", "action"):
            action_id = "capture-" + origin
            result = asyncio.get_running_loop().create_future()
            adapter._pending_action_visuals[action_id] = result
            adapter._robot_action_contexts[("robot", 1, 77)] = {"actionId": action_id}
            await self.gateway._publish_event({"t": "cam_meta", "robot_id": "robot", "epoch": 1,
                "res": "VGA", "fps": 5, "counter_base": 4, "origin": origin, "origin_id": 77})
            await self.frame(4)
            visual = await asyncio.wait_for(result, 1)
            self.assertEqual(visual["metadata"]["actionId"], action_id)

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
        processed, observed, failures = [], [], []

        async def consume(payload):
            processed.append(payload)
            if payload == b"1":
                raise ValueError("fixture inference failure")
            return "candidate"

        async def observe(analysis):
            if analysis.error is not None:
                failures.append(analysis)
                return
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
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].counter, 1)
        self.assertIsNone(failures[0].result)
        self.assertIn("fixture inference failure", failures[0].error)
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

    async def test_metrics_distinguish_processing_throughput_from_fresh_publication(self) -> None:
        observed = []

        async def consume(payload):
            self.now += 0.25 if payload == b"1" else 1.1
            return "candidate"

        plugin = self.plugin(consume, observe=observed.append)
        await self.frame(1)
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertAlmostEqual(observed[0].processing["inferenceMs"], 250)
        self.assertAlmostEqual(observed[0].processing["observationAgeMs"], 250)
        await self.frame(2)
        await asyncio.wait_for(plugin._queue.join(), 1)
        metrics = plugin.metrics()
        self.assertEqual(len(observed), 1, "Expired inference cannot publish an observation")
        self.assertEqual((metrics["receivedFrames"], metrics["processedFrames"], metrics["freshResults"]), (2, 2, 1))
        self.assertEqual(metrics["staleFrames"], 1)
        self.assertAlmostEqual(metrics["observationAgeMs"], 1350)
        self.assertAlmostEqual(metrics["processedFps"], 2 / 1.35)
        self.assertAlmostEqual(metrics["freshFps"], 1 / 1.35)
        self.assertEqual(metrics["queueDepth"], 0)

    async def test_switch_off_discards_queued_and_inflight_results_even_after_reenable(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()
        observed, processed = [], []
        async def consume(payload):
            processed.append(payload)
            if payload == b"1":
                started.set()
                await release.wait()
            return payload
        plugin = self.plugin(consume, observe=observed.append)
        await self.frame(1)
        await asyncio.wait_for(started.wait(), 1)
        await self.frame(2)
        plugin.set_enabled(False)
        await self.frame(3)
        self.assertEqual(plugin.metrics()["queueDepth"], 0)
        plugin.set_enabled(True)
        await self.frame(4)
        release.set()
        await asyncio.wait_for(plugin._queue.join(), 1)
        self.assertEqual(processed, [b"1", b"4"])
        self.assertEqual([event.counter for event in observed], [4])
