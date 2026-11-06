import asyncio
import copy
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import unittest
import cbor2
from unittest.mock import patch, Mock, AsyncMock

from gateway.plugins import CameraFramePlugin, _CameraInput
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig
from gateway.gait_learning import policy_seed
from gateway.gait_optimizer import candidate, context, DEFAULT_RADII, DEFAULT_WEIGHTS, measured_score, compare, project_candidate
from gateway.gait_learning_service import GaitLearningService
from gateway.robot_learning_transport import TraceSessionChanged, RobotLearningTransport, decode_trace_response
from gateway.gait_training import profile_signature
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
from test_gait_learning import policy_recording


def pose(t, x=0., y=0., heading=0.):
    return dict(available=True, frameId=str(t), receivedAtMonotonic=t, epoch=1,
                calibrationId="calibrated", referenceId="floor",
                position=dict(xMetres=x, yMetres=y, zMetres=0., headingDegrees=heading))


def samples(command):
    return [dict(host_monotonic_s=t, command=command, tilt=[0., 0.],
                 angular=[0., 0., 0.], error=[0.]*12, acceleration_deviation=[0.],
                 reference_twist=[command[0]*.2, 0., command[1]*math.pi/8]) for t in (0., 1., 2.)]


class GaitStorageTests(unittest.TestCase):
    def test_atomic_failures_preserve_saved_state_and_remove_only_their_own_temporary_file(self):
        from contextlib import nullcontext
        import stat
        from gateway.gait_learning_service import atomic_json

        for failure in ("serialization", "fsync", "replace"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                destination = root/"training.json"
                destination.write_text('{"previous":"complete"}')
                original = destination.read_bytes()
                unrelated = root/"training.json.another-owner.tmp"
                unrelated.write_text("another operation's temporary file")
                value = {"candidate": float("nan") if failure == "serialization" else [1, 2, 3]}
                operation = (nullcontext() if failure == "serialization" else
                    patch("gateway.gait_learning_service.os.fsync", side_effect=OSError("Fixture sync failed"))
                    if failure == "fsync" else patch.object(Path, "replace", side_effect=OSError("Fixture replace failed")))
                with operation, self.assertRaises(ValueError if failure == "serialization" else OSError):
                    atomic_json(destination, value)
                self.assertEqual(destination.read_bytes(), original)
                self.assertEqual(unrelated.read_text(), "another operation's temporary file")
                self.assertEqual(sorted(p.name for p in root.iterdir()),
                                 [destination.name, unrelated.name])
                atomic_json(destination, {"candidate": [1, 2, 3]})
                self.assertEqual(json.loads(destination.read_text()), {"candidate": [1, 2, 3]})
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
                self.assertEqual(sorted(p.name for p in root.iterdir()),
                                 [destination.name, unrelated.name])

    def test_concurrent_configuration_keeps_latest_settings_without_holding_body_commands(self):
        from gateway.gait_learning_service import atomic_json

        async def check():
            class Socket:
                closed = False
                def __init__(self): self.messages = []
                async def send(self, raw): self.messages.append(json.loads(raw))

            gateway = GatewayService(GatewayServiceConfig(tokens={}), clock=lambda: 100.)
            socket = Socket()
            connection = GatewayConnection(gateway, socket, "robot", 1)
            gateway._connections["robot"] = connection
            with tempfile.TemporaryDirectory() as directory:
                service = GaitLearningService(gateway, Transport(), lambda _: {}, Path(directory))
                started, release = asyncio.Event(), asyncio.Event()
                tasks = []
                async def save(fn, path, value):
                    self.assertIs(fn, atomic_json)
                    if value["robot"]["window_cycles"] == 5:
                        started.set()
                        await release.wait()
                    fn(path, value)
                with patch("gateway.gait_learning_service.asyncio.to_thread", new=save):
                    try:
                        tasks.append(asyncio.create_task(service.configure("robot", {"window_cycles": 5})))
                        await started.wait()
                        tasks.append(asyncio.create_task(service.configure("robot", {"window_cycles": 6})))
                        await asyncio.sleep(0)  # Let the second request attempt its existing save.
                        await connection.send_command({"t": "stop"}, received_at=100.)
                        self.assertEqual(socket.messages[-1]["t"], "stop",
                                         "Settings persistence cannot hold independent body command admission")
                        release.set()
                        await asyncio.gather(*tasks)
                        self.assertEqual(service.settings["robot"]["window_cycles"], 6)
                        self.assertEqual(json.loads(service.settings_path.read_text())["robot"]["window_cycles"], 6)
                    finally:
                        release.set()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        connection.cancel_pending()
                        await service.close()
        asyncio.run(check())

    def test_cancelled_configuration_cannot_outlive_and_overwrite_a_newer_save(self):
        from gateway.gait_learning_service import atomic_json

        async def check():
            with tempfile.TemporaryDirectory() as directory:
                service = GaitLearningService(Gateway(), Transport(), lambda _: {}, Path(directory))
                started, release = asyncio.Event(), asyncio.Event()
                requests, workers = [], []
                async def save(fn, path, value):
                    self.assertIs(fn, atomic_json)
                    async def disk():
                        if value["robot"]["window_cycles"] == 5:
                            started.set()
                            await release.wait()
                        fn(path, value)
                    # A dispatched disk worker survives cancellation of its
                    # waiter, as a real asyncio.to_thread filesystem call does.
                    worker = asyncio.create_task(disk()); workers.append(worker)
                    return await asyncio.shield(worker)
                with patch("gateway.gait_learning_service.asyncio.to_thread", new=save):
                    try:
                        first = asyncio.create_task(service.configure("robot", {"window_cycles": 5}))
                        requests.append(first)
                        await started.wait()
                        first.cancel(); await asyncio.sleep(0); first.cancel()
                        await asyncio.wait([first], timeout=.01)
                        second = asyncio.create_task(service.configure("robot", {"window_cycles": 6}))
                        requests.append(second)
                        await asyncio.wait([second], timeout=.01)
                        release.set()
                        results = await asyncio.gather(*requests, return_exceptions=True)
                        await asyncio.gather(*workers)
                        self.assertIsInstance(results[0], asyncio.CancelledError)
                        self.assertFalse(isinstance(results[1], BaseException))
                        self.assertEqual(service.settings["robot"]["window_cycles"], 6)
                        self.assertEqual(json.loads(service.settings_path.read_text())["robot"]["window_cycles"], 6)
                    finally:
                        release.set()
                        await asyncio.gather(*requests, return_exceptions=True)
                        await asyncio.gather(*workers, return_exceptions=True)
                        await service.close()
        asyncio.run(check())

    def test_failed_configuration_does_not_publish_unpersisted_learning_settings(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                service = GaitLearningService(Gateway(), Transport(), lambda _: {}, Path(directory))
                async def run(fn, *args): return fn(*args)
                with patch("gateway.gait_learning_service.asyncio.to_thread", new=run):
                    try:
                        await service.configure("robot", {"learning": False})
                        before = copy.deepcopy(service.settings)
                        saved = service.settings_path.read_bytes()
                        with patch("gateway.gait_learning_service.atomic_json", side_effect=OSError("Fixture settings disk failed")):
                            with self.assertRaisesRegex(OSError, "Fixture settings disk failed"):
                                await service.configure("robot", {"learning": True})
                        self.assertEqual(service.settings, before,
                                         "A failed settings command must not enable learning in memory")
                        self.assertEqual(service.settings_path.read_bytes(), saved)
                        self.assertFalse(service.tasks)
                    finally:
                        await service.close()
        asyncio.run(check())

    def test_robot_http_failure_keeps_the_complete_diagnostic_and_closes_the_socket(self):
        detail = "Firmware diagnostic start\n" + "measurement αβ\n"*80 + "Root cause at end: calibration write failed"
        with patch("gateway.robot_learning_transport.http.client.HTTPConnection") as factory:
            connection = factory.return_value
            connection.getresponse.return_value.status = 500
            connection.getresponse.return_value.read.return_value = detail.encode()
            with self.assertRaises(ValueError) as caught:
                RobotLearningTransport._request("fixture.invalid", "fixture-token", "gait-learning", {"op": "read"})
            self.assertEqual(str(caught.exception), "Robot gait-learning: HTTP 500: " + detail)
            connection.request.assert_called_once()
            connection.close.assert_called_once()


class ObjectiveTests(unittest.TestCase):
    def test_cbor_trace_preserves_records_and_rejects_truncated_tail(self):
        records = [{"schema": "gait_trace_v1", "boot_id": 4294967295},
                   {"kind": "imu", "time_us": 9007199254740991,
                    "imu": {"angular_rate_rad_s": [math.nextafter(.1, 1), -2.5, None]}},
                   {"next": 19, "lost": 0, "more": False}]
        wire = b''.join(cbor2.dumps(record) for record in records)
        self.assertEqual(decode_trace_response(wire, 'application/cbor-seq'), records)
        with self.assertRaisesRegex(ValueError, 'Incomplete or invalid'):
            decode_trace_response(wire[:-1], 'application/cbor-seq')

    def test_transport_decodes_binary_trace_and_legacy_ndjson(self):
        records = [{"schema": "gait_trace_v1"}, {"next": 1}]
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        for content_type, wire in (
                ('application/cbor-seq', b''.join(cbor2.dumps(row) for row in records)),
                ('application/x-ndjson', b'\n'.join(json.dumps(row).encode() for row in records))):
            with self.subTest(content_type=content_type):
                response.getheader.return_value = content_type
                response.read.return_value = wire
                with patch('gateway.robot_learning_transport.http.client.HTTPConnection', return_value=connection):
                    self.assertEqual(RobotLearningTransport._request('robot', 'token', 'servo-feedback',
                        {'op': 'trace_read'}), records)
        self.assertEqual(connection.close.call_count, 2)

    def test_sparse_feedback_owns_and_closes_each_connection(self):
        async def check():
            gateway=Mock();gateway.maintenance_address=AsyncMock(return_value='robot')
            tokens=Mock();tokens.snapshot.return_value={'body':'token'}
            transport=RobotLearningTransport(gateway,tokens)
            with patch('gateway.robot_learning_transport.http.client.HTTPConnection') as factory:
                connection=factory.return_value
                connection.getresponse.return_value.status=200
                connection.getresponse.return_value.read.return_value=b'{"joints":[]}'
                await transport.request('body','servo-feedback',None)
                await transport.request('body','servo-feedback',None)
                self.assertEqual(factory.call_count,2)
                self.assertEqual(connection.close.call_count,2)
                self.assertEqual(connection.request.call_args.args[3]['Connection'], 'close')
                self.assertEqual(set(transport.locks), {'body'})
        asyncio.run(check())

    def test_trace_transport_releases_each_socket_and_does_not_retry_failed_requests(self):
        transport = RobotLearningTransport(None,None)
        lock = threading.Lock()
        with patch("gateway.robot_learning_transport.http.client.HTTPConnection") as factory:
            connection=factory.return_value
            response=connection.getresponse.return_value
            response.status=200
            response.getheader.return_value='application/x-ndjson'
            response.read.return_value=b'{"next":1}\n'
            for _ in range(3):
                transport._serialized_request(lock,"robot","token","servo-feedback",{"op":"trace_read"})
            self.assertEqual(factory.call_count,3)
            self.assertEqual(connection.request.call_count,3)
            self.assertEqual(connection.close.call_count,3)
            connection.request.side_effect=OSError("disconnected")
            with self.assertRaisesRegex(OSError,"disconnected"):
                transport._serialized_request(lock,"robot","token","gait-learning",{"op":"install"})
            self.assertEqual(connection.request.call_count,4)
            self.assertEqual(connection.close.call_count,4)

    def test_trace_session_conflict_is_distinct_from_other_http_errors(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 409
        with patch("gateway.robot_learning_transport.http.client.HTTPConnection", return_value=connection):
            response.read.return_value = b'{"error":"Trace session changed"}'
            with self.assertRaises(TraceSessionChanged):
                RobotLearningTransport._request("robot", "token", "servo-feedback",
                    {"op": "trace_read", "boot_id": 1, "session": 1, "after": 100})
            response.read.return_value = b'{"error":"Trace cursor is ahead of recording"}'
            with self.assertRaises(ValueError) as error:
                RobotLearningTransport._request("robot", "token", "servo-feedback", {"op": "trace_read", "after": 100})
            self.assertNotIsInstance(error.exception, TraceSessionChanged)
        self.assertEqual(connection.close.call_count, 2)

    def test_cancelled_trace_worker_finishes_before_stop_and_transport_close(self):
        async def check():
            started, release = threading.Event(), threading.Event()
            order = []
            gateway = Mock(); gateway.maintenance_address = AsyncMock(side_effect=lambda robot: robot)
            tokens = Mock(); tokens.snapshot.return_value = {'body': 'token', 'other': 'token'}
            transport = RobotLearningTransport(gateway, tokens)
            def connection(address, port, timeout):
                conn = Mock(); response = conn.getresponse.return_value
                response.status = 200; response.getheader.return_value = 'application/x-ndjson'
                def request(method, path, payload, headers):
                    conn.operation = json.loads(payload)['op']
                    order.append((address, conn.operation))
                def read():
                    if address == 'body' and conn.operation == 'trace_read':
                        started.set()
                        if not release.wait(5): raise RuntimeError('Fixture worker was not released')
                    return b'{"next":1}\n'
                conn.request.side_effect = request; response.read.side_effect = read
                conn.close.side_effect = lambda: order.append((address, 'closed'))
                return conn
            with patch('gateway.robot_learning_transport.http.client.HTTPConnection', side_effect=connection):
                reading = asyncio.create_task(transport.request('body', 'servo-feedback', {'op': 'trace_read'}))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    reading.cancel()
                    with self.assertRaises(asyncio.CancelledError): await reading
                    stopping = asyncio.create_task(transport.request('body', 'servo-feedback', {'op': 'trace_stop'}))
                    closing = asyncio.create_task(transport.close())
                    await transport.request('other', 'servo-feedback', {'op': 'trace_read'})
                    self.assertNotIn(('body', 'trace_stop'), order)
                    self.assertFalse(closing.done())
                finally:
                    release.set()
                await asyncio.wait_for(asyncio.gather(stopping, closing), 2)
                self.assertLess(order.index(('body', 'closed')), order.index(('body', 'trace_stop')))
                self.assertEqual(order.count(('body', 'closed')), 2)
        asyncio.run(check())

    def test_depth_provenance_survives_reward_calculation(self):
        poses = [{**pose(t, x=t*.1), "source": "moge2-open3d-odometry",
                  "scaleSource": "learned-metric-estimate", "metricAccuracyVerified": False,
                  "coordinateOrigin": "camera"} for t in (0., 2.)]
        result = measured_score(samples([1, 0, 0, 1]), poses)
        self.assertEqual(result["distance_scale_source"], "learned-metric-estimate")
        self.assertFalse(result["distance_accuracy_verified"])
        self.assertEqual(result["coordinate_origin"], "camera")
        self.assertEqual(result["camera_context"][2], "calibrated")

    def test_signed_backwards_and_both_turns(self):
        forward = measured_score(samples([1, 0, 0, 1]), [pose(0), pose(2, x=.4)])
        backward = measured_score(samples([-1, 0, 0, 1]), [pose(0), pose(2, x=-.4)])
        self.assertEqual(forward["score"], backward["score"])
        wrong = measured_score(samples([-1, 0, 0, 1]), [pose(0), pose(2, x=.4)])
        self.assertLess(wrong["score"], 0)
        left = measured_score(samples([0, 1, 0, 1]), [pose(0), pose(2, heading=45)])
        right = measured_score(samples([0, -1, 0, 1]), [pose(0), pose(2, heading=-45)])
        self.assertEqual(left["score"], right["score"])
        self.assertGreater(left["score"], 0)
        self.assertEqual(context([-1, 0, 0, 1]), "backward")
        self.assertEqual(context([0, -1, 0, 1]), "turning")
        self.assertEqual(context([1, 0, 0, 1], "run"), "run")
        self.assertIsNone(context([1, 0, 0, 1], "crawl"))
        self.assertIsNone(context([1, 0, 0, 1], "crab"))

    def test_missing_or_changed_camera_reference_is_unknown(self):
        for poses in ([], [pose(0)], [pose(0), {**pose(2), "calibrationId": "changed"}],
                      [pose(0), {**pose(1), "available": False}, pose(2, x=10)]):
            with self.assertRaises(ValueError):
                measured_score(samples([1, 0, 0, 1]), poses)

    def test_world_motion_projects_into_body_heading(self):
        score = measured_score(samples([1, 0, 0, 1]), [pose(0, heading=90), pose(2, y=.4, heading=90)])
        self.assertAlmostEqual(score["metrics"]["progress_m_s"], .2)
        self.assertAlmostEqual(score["metrics"]["lateral_m_s"], 0)

    def test_quiet_stillness_and_excess_spin_do_not_win(self):
        noisy = samples([1, 0, 0, 1])
        for sample in noisy:
            sample["error"] = [20.]*12
            sample["angular"] = [2., 2., 2.]
        moving = measured_score(noisy, [pose(0), pose(2, x=.1)])
        still = measured_score(samples([1, 0, 0, 1]), [pose(0), pose(2)])
        self.assertGreater(moving["score"], still["score"])
        on_target = measured_score(samples([0,1,0,1]), [pose(0), pose(2,heading=45)])
        overspin = measured_score(samples([0,1,0,1]), [pose(0), pose(2,heading=90)])
        self.assertGreater(on_target["score"], overspin["score"])
        self.assertEqual(compare([-.1, -.1], [0., 0.])["decision"], "not_demonstrated")

    def test_candidate_coordinated_geometry_and_repeated_evidence(self):
        base = policy_seed(policy_recording(), gait=True)["model"]
        revised = candidate(base, [1.]*len(DEFAULT_RADII), DEFAULT_RADII)
        self.assertEqual(base["gait_profile"], [0.]*33)
        self.assertAlmostEqual(revised["gait_profile"][1], 8.)
        self.assertEqual(revised["gait_profile"][6:10], [4.]*4)
        self.assertEqual(revised["gait_profile"][2:6], [0.]*4)
        self.assertEqual(revised["pulse_max_us"], base["pulse_max_us"])
        self.assertEqual(compare([1.], [2.])["decision"], "collecting_repeats")
        self.assertEqual(compare([1., 1.01], [1.1, 1.11])["decision"], "improved")
        self.assertEqual(compare([1., 1.5], [1.1, 1.11])["decision"], "not_demonstrated")


class Gateway:
    def __init__(self):
        self.commands, self.events, self.frames, self.diagnostics = [], [], [], []
        self.balance_reads = []
    def status(self):
        return {"robots": {"robot": {"epoch": 1, "features": ["walk_nominal_v1", "balance_control_v1"],
            "motion_speed": {"joint_speed_limit_deg_s": 545.45},
            "balance_settings": None, "walking_source": {"source": "native"},
            "unrelated_private_data": "do-not-record"}}}
    def subscribe_commands(self, fn): self.commands.append(fn)
    def subscribe_events(self, fn): self.events.append(fn)
    def subscribe_frames(self, fn): self.frames.append(fn)
    def subscribe_diagnostics(self, fn): self.diagnostics.append(fn)
    def unsubscribe_diagnostics(self, fn): self.diagnostics.remove(fn)
    async def body_calibration(self, op, values, robot_id=None):
        assert op == "get"
        return {"robot_id": robot_id, "joints": []}
    async def body_balance(self, op, *, robot_id=None):
        self.balance_reads.append((op, robot_id))
        assert op == "get"
        return {"enabled": True, "strength": 1., "damping": 1., "roll_deg": 3., "pitch_deg": 1.5928}


class Transport:
    def __init__(self):
        self.calls, self.active, self.session = [], False, 0
    async def request(self, robot, endpoint, payload):
        self.calls.append((robot, endpoint, copy.deepcopy(payload)))
        if payload is None:
            return {"test_metadata": endpoint}
        op = payload["op"]
        if endpoint == "gait-learning":
            return {"model_schema": "gait_learning_v4", "model_id": "", "enabled": False}
        if op == "trace_start":
            self.active = True
            self.session += 1
        elif op == "trace_stop":
            self.active = False
        return [{"schema": "gait_trace_v1", "geometry": "test-geometry", "boot_id": 1,
                 "session": self.session, "active": self.active},
                {"next": 0, "lost": 0, "more": False}]


def make_gait_service(directory, close=None):
    transport = Transport()
    transport.request = AsyncMock(side_effect=AssertionError("No external requests in lifecycle fixture"))
    transport.close = AsyncMock(side_effect=close)
    service = GaitLearningService(Gateway(), transport,
        Mock(side_effect=AssertionError("No sensor processing in lifecycle fixture")), directory,
        optimizer=Mock(side_effect=AssertionError("No training in lifecycle fixture")))
    return service, transport


async def assert_writer_finished(test, service):
    test.assertTrue(service.writer.done())
    test.assertFalse(service.writer.cancelled())
    test.assertIsNone(service.writer.exception())
    test.assertIsNone(service.writer.result())
    test.assertTrue(service.writes.empty())
    await asyncio.wait_for(service.writes.join(), 1)


class CloseLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def finish_fixture(self, service, *waiters):
        # Emergency cleanup follows assertions; it is never lifecycle proof.
        await asyncio.gather(*waiters, return_exceptions=True)
        owner = getattr(service, "_close_task", None)
        if owner is not None:
            await asyncio.gather(owner, return_exceptions=True)
        if service.writer is not None:
            if not service.writer.done():
                service.writes.put_nowait(None)
            await asyncio.gather(service.writer, return_exceptions=True)

    def enqueue_records(self, service, directory):
        path = directory/"recording.jsonl"
        records = [{"sample": 1}, {"sample": 2}]
        for record in records:
            service._enqueue(path, record)
        return path, records

    async def test_owned_close_task_cancellation_retains_waiter_cancellation_separately(self):
        for cancel_waiter in (False, True):
            with self.subTest(cancel_waiter=cancel_waiter), tempfile.TemporaryDirectory() as directory:
                entered, release = asyncio.Event(), asyncio.Event()
                owned_cancel = asyncio.CancelledError("Fixture owned close cancellation")
                async def close_transport():
                    entered.set()
                    await release.wait()
                    raise owned_cancel
                service, transport = make_gait_service(Path(directory), close_transport)
                await service.start()
                path, records = self.enqueue_records(service, Path(directory))
                waiter = asyncio.create_task(service.close())
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    if cancel_waiter:
                        waiter.cancel("Fixture close waiter cancellation")
                        await asyncio.sleep(0)
                        self.assertFalse(waiter.done())
                    release.set()
                    # Observe completion without consuming the Task's first
                    # cancellation result before the caller sees it.
                    await asyncio.wait_for(asyncio.wait({waiter}), 1)
                    with self.assertRaises(asyncio.CancelledError) as caught:
                        await waiter
                    if cancel_waiter:
                        self.assertEqual(caught.exception.args, ("Fixture close waiter cancellation",))
                        self.assertIs(caught.exception.__cause__, owned_cancel)
                    else:
                        self.assertEqual(caught.exception.args, owned_cancel.args)
                        self.assertIsNone(caught.exception.__cause__)
                    self.assertTrue(service._close_task.cancelled())
                    owner = service._close_task
                    with self.assertRaises(asyncio.CancelledError):
                        await service.close()
                    self.assertIs(service._close_task, owner)
                    transport.close.assert_awaited_once()
                    transport.request.assert_not_awaited()
                    await assert_writer_finished(self, service)
                    self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], records)
                finally:
                    release.set()
                    await self.finish_fixture(service, waiter)

    async def test_concurrent_callers_wait_for_one_cleanup_and_successful_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entered, release = asyncio.Event(), asyncio.Event()
            async def close():
                entered.set()
                await release.wait()
            service, transport = make_gait_service(root, close)
            await service.start()
            path, records = self.enqueue_records(service, root)
            first = asyncio.create_task(service.close())
            second = None
            try:
                await asyncio.wait_for(entered.wait(), 1)
                second = asyncio.create_task(service.close())
                await asyncio.sleep(0)
                self.assertFalse(first.done())
                self.assertFalse(second.done())
                self.assertFalse(service.writer.done())
                release.set()
                self.assertEqual(await asyncio.gather(first, second), [None, None])
                await assert_writer_finished(self, service)
                self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], records)
                self.assertIsNone(await service.close())
                transport.close.assert_awaited_once()
                transport.request.assert_not_awaited()
            finally:
                release.set()
                await self.finish_fixture(service, *[task for task in (first, second) if task])

    async def test_repeatedly_cancelled_waiter_drains_cleanup_and_preserves_its_result(self):
        for fail in (False, True):
            with self.subTest(transport_failure=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                entered, release = asyncio.Event(), asyncio.Event()
                failure = OSError("Fixture transport cleanup failed")
                async def close():
                    entered.set()
                    await release.wait()
                    if fail:
                        raise failure
                service, transport = make_gait_service(root, close)
                await service.start()
                path, records = self.enqueue_records(service, root)
                waiter = asyncio.create_task(service.close())
                observer = None
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    waiter.cancel()
                    await asyncio.sleep(0)
                    waiter.cancel()
                    await asyncio.sleep(0)
                    observer = asyncio.create_task(service.close())
                    await asyncio.sleep(0)
                    self.assertFalse(waiter.done())
                    self.assertFalse(observer.done())
                    self.assertFalse(service.writer.done())
                    release.set()
                    with self.assertRaises(asyncio.CancelledError) as cancelled:
                        await waiter
                    self.assertTrue(waiter.cancelled())
                    if fail:
                        self.assertIs(cancelled.exception.__cause__, failure)
                        with self.assertRaises(OSError) as observed:
                            await observer
                        self.assertIs(observed.exception, failure)
                        with self.assertRaises(OSError) as repeated:
                            await service.close()
                        self.assertIs(repeated.exception, failure)
                    else:
                        self.assertIsNone(await observer)
                        self.assertIsNone(await service.close())
                    await assert_writer_finished(self, service)
                    self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], records)
                    transport.close.assert_awaited_once()
                    transport.request.assert_not_awaited()
                finally:
                    release.set()
                    await self.finish_fixture(service, *[task for task in (waiter, observer) if task])

    async def test_transport_failure_still_drains_writes_and_is_retained_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failure = OSError("Fixture transport cleanup failed")
            async def close():
                raise failure
            service, transport = make_gait_service(root, close)
            await service.start()
            path, records = self.enqueue_records(service, root)
            waiters = [asyncio.create_task(service.close()) for _ in range(2)]
            try:
                results = await asyncio.gather(*waiters, return_exceptions=True)
                await assert_writer_finished(self, service)
                self.assertTrue(all(result is failure for result in results))
                self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], records)
                with self.assertRaises(OSError) as repeated:
                    await service.close()
                self.assertIs(repeated.exception, failure)
                transport.close.assert_awaited_once()
                transport.request.assert_not_awaited()
            finally:
                await self.finish_fixture(service, *waiters)

    async def test_successful_repeat_and_partial_start_cleanup(self):
        for stage in ("before_start", "started", "corrupt_bank"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if stage == "corrupt_bank":
                    (root/"settings.json").write_text(json.dumps({
                        "fixture-robot": {"logging": False, "learning": False}}))
                    bank = root/hashlib.sha256(b"fixture-robot").hexdigest()[:20]
                    bank.mkdir()
                    (bank/"training.json").write_text('{"broken":')
                service, transport = make_gait_service(root)
                try:
                    if stage == "corrupt_bank":
                        pending = {"other": ({"id": "retained"}, True)}
                        service._runtime("fixture-robot")["pending"] = pending
                        with self.assertRaises(json.JSONDecodeError):
                            await service.start()
                        self.assertIs(service._runtime("fixture-robot")["pending"], pending)
                    elif stage == "started":
                        await service.start()
                    await service.close()
                    await service.close()
                    if service.writer is not None:
                        await assert_writer_finished(self, service)
                    transport.close.assert_awaited_once()
                    transport.request.assert_not_awaited()
                    self.assertFalse(service.tasks)
                    self.assertFalse(service.workers)
                finally:
                    await self.finish_fixture(service)

    async def test_failed_writer_is_reported_without_discarding_pending_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service, transport = make_gait_service(root)
            await service.start()
            failure = RuntimeError("Fixture storage worker failed")
            pending = {"sample": "still queued"}
            try:
                with patch.object(service, "_write", side_effect=failure):
                    service._enqueue(root/"failed.jsonl", {"sample": "failed dispatch"})
                    service._enqueue(root/"pending.jsonl", pending)
                    with self.assertRaisesRegex(RuntimeError, "Fixture storage worker failed"):
                        await asyncio.wait_for(asyncio.shield(service.writer), 1)
                with self.assertRaises(RuntimeError) as caught:
                    await asyncio.wait_for(service.close(), 1)
                self.assertIs(caught.exception, failure)
                self.assertEqual(list(service.writes._queue), [(root/"pending.jsonl", pending, False)])
                self.assertFalse((root/"pending.jsonl").exists())
                with self.assertRaises(RuntimeError) as repeated:
                    await service.close()
                self.assertIs(repeated.exception, failure)
                transport.close.assert_awaited_once()
                transport.request.assert_not_awaited()
            finally:
                await self.finish_fixture(service)

    async def test_unstarted_writer_with_pending_records_reports_failure_without_discard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service, transport = make_gait_service(root)
            pending = {"sample": "not started"}
            service._enqueue(root/"pending.jsonl", pending)
            with self.assertRaisesRegex(RuntimeError, "pending recording writes") as caught:
                await asyncio.wait_for(service.close(), 1)
            self.assertEqual(list(service.writes._queue), [(root/"pending.jsonl", pending, False)])
            with self.assertRaises(RuntimeError) as repeated:
                await service.close()
            self.assertIs(repeated.exception, caught.exception)
            transport.close.assert_awaited_once()
            transport.request.assert_not_awaited()

    async def test_entrypoint_cancellation_waits_for_gait_cleanup_before_dependencies(self):
        from test_gateway_security import GatewayStartupTests
        import gateway.server.__main__ as gateway_main

        fixture_owner = GatewayStartupTests()
        with tempfile.TemporaryDirectory() as directory:
            with fixture_owner.startup_fixture(Path(directory), real_gait=True) as f:
                entered, release = asyncio.Event(), asyncio.Event()
                async def close():
                    entered.set()
                    await release.wait()
                f.transport.close.side_effect = close
                owner = asyncio.create_task(gateway_main._run_production(f.args))
                observer = None
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    owner.cancel()
                    await asyncio.sleep(0)
                    owner.cancel()
                    await asyncio.sleep(0)
                    observer = asyncio.create_task(f.gait.close())
                    await asyncio.sleep(0)
                    self.assertFalse(owner.done())
                    self.assertFalse(observer.done())
                    f.gateway.close.assert_not_awaited()
                    f.camera.aclose.assert_not_awaited()
                    self.assertFalse(f.gait.writer.done())
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await owner
                    self.assertTrue(owner.cancelled())
                    self.assertIsNone(await observer)
                    await assert_writer_finished(self, f.gait)
                    f.transport.close.assert_awaited_once()
                    f.transport.request.assert_not_awaited()
                    f.gateway.close.assert_awaited_once()
                    f.camera.aclose.assert_awaited_once()
                finally:
                    release.set()
                    await self.finish_fixture(f.gait, *[task for task in (owner, observer) if task])


class RecorderReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gateway, self.transport = Gateway(), Transport()
        self.transport.close = AsyncMock()
        self.depth_error = self.stop_error = self.drain_error = None
        self.stop_entered, self.release_stop = asyncio.Event(), asyncio.Event()
        self.release_stop.set()
        self.started = asyncio.Event()
        self.more_after_stop = False
        self.body = self.gateway.status()["robots"]["robot"]
        self.body["active_walk"] = {"name": "walk", "seq": 1}
        self.gateway.status = lambda: {"robots": {"robot": self.body}}
        self.depth_calls = []

        async def depth(robot, consumer, enabled, *, wait_for_measurement):
            self.depth_calls.append((robot, consumer, enabled, wait_for_measurement))
            if not enabled and self.depth_error:
                raise self.depth_error  # Synchronous submission fault, not a native worker result.

        original = self.transport.request
        async def request(robot, endpoint, payload):
            if payload:
                self.assertEqual(endpoint, "servo-feedback")
                self.assertIn(payload["op"], {"trace_start", "trace_read", "trace_stop"})
                if payload.get("session") is not None and payload["session"] != self.transport.session:
                    self.transport.calls.append((robot, endpoint, copy.deepcopy(payload)))
                    raise TraceSessionChanged("Device trace session changed")
                if payload["op"] == "trace_stop":
                    self.stop_entered.set()
                    await self.release_stop.wait()
                    if self.stop_error:
                        self.transport.calls.append((robot, endpoint, copy.deepcopy(payload)))
                        raise self.stop_error
                elif (payload["op"] == "trace_read" and self.stop_entered.is_set()
                        and not self.transport.active and self.drain_error):
                    self.transport.calls.append((robot, endpoint, copy.deepcopy(payload)))
                    raise self.drain_error
            result = await original(robot, endpoint, payload)
            if payload and payload["op"] == "trace_stop" and getattr(self, "stop_active_reply", False):
                result[0]["active"] = True
            if payload and payload["op"] == "trace_stop" and self.more_after_stop:
                result.insert(1, {"kind": "event", "time_us": 123, "fixture": "last owned sample"})
                result[-1].update(next=1, more=True)
            if payload and payload["op"] in {"trace_start", "trace_read"} and self.transport.active:
                self.started.set()
            return result
        self.transport.request = request
        self.service = GaitLearningService(self.gateway, self.transport,
            lambda _: {"available": False, "reason": "Fixture"}, Path(self.temp.name),
            depth_demand=depth,
            optimizer=Mock(side_effect=AssertionError("No training in release fixture")))
        await self.service.start()
        self.addAsyncCleanup(self.finish_fixture)

    async def finish_fixture(self):
        # Emergency cleanup follows assertions and is not used as completion proof.
        self.release_stop.set()
        await asyncio.gather(self.service.close(), return_exceptions=True)

    async def enable(self):
        self.started.clear()
        await self.service.configure("robot", {"logging": True, "learning": False})
        await asyncio.wait_for(self.started.wait(), 1)
        return self.service.tasks["robot"], self.service._runtime("robot")["recording"]

    def stop_calls(self):
        return [p for _, _, p in self.transport.calls if p and p["op"] == "trace_stop"]

    async def events(self, recording):
        await asyncio.wait_for(self.service.writes.join(), 1)
        path = recording/"events.jsonl"
        rows = [json.loads(row)["value"] for row in path.read_text().splitlines()]
        return [row for row in rows if row["t"] == "recording_cleanup"]

    async def assert_failed(self, task, recording, stages, acknowledged, drained):
        with self.assertRaises(ExceptionGroup) as caught:
            await asyncio.wait_for(asyncio.shield(task), 1)
        status = self.service.status("robot")
        self.assertEqual(status["state"], "recording_unavailable")
        for stage, detail in stages:
            self.assertIn(detail, status["error"])
        event = (await self.events(recording))[-1]
        self.assertEqual((event["boot_id"], event["session"]), (1, 1))
        self.assertEqual(event["trace_stop_acknowledged"], acknowledged)
        self.assertEqual(event["trace_drained"], drained)
        self.assertEqual([(e["stage"], e["error"]) for e in event["errors"]], stages)
        self.assertIsInstance(status["error"], str)
        json.dumps(status)  # Public status must remain JSON-safe despite the retained cleanup result.
        return caught.exception

    async def assert_close_failure(self, error):
        for _ in range(2):
            with self.assertRaises(ExceptionGroup) as caught:
                await asyncio.wait_for(self.service.close(), 1)
            self.assertIs(caught.exception, error)
        self.transport.close.assert_awaited_once()
        self.assertTrue(self.service.writer.done())
        self.assertFalse(self.service.writer.cancelled())
        self.assertIsNone(self.service.writer.exception())
        self.assertTrue(self.service.writes.empty())
        self.service.optimizer.assert_not_called()

    async def test_depth_submission_failure_still_stops_and_drains_without_reenable(self):
        self.depth_error = RuntimeError("Fixture depth-release submission failed")
        self.release_stop.clear()
        task, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        # Bound the wait so the old depth-first finally cannot hang this fixture.
        for _ in range(100):
            if task.done() or self.stop_entered.is_set(): break
            await asyncio.sleep(.01)
        self.assertTrue(self.stop_entered.is_set(), "Depth failure skipped owned trace_stop")
        await self.service.configure("robot", {"logging": True})
        self.release_stop.set()
        error = await self.assert_failed(task, recording,
            [("depth_release", str(self.depth_error))], True, True)
        self.assertEqual(self.stop_calls(), [{"op": "trace_stop", "after": 0, "boot_id": 1, "session": 1}])
        self.assertFalse(self.transport.active)
        self.assertFalse(self.service._runtime("robot")["owned"])
        self.assertIs(self.service.tasks["robot"], task)
        await self.assert_close_failure(error)

    async def test_stop_failure_retains_owned_identity_and_error_when_logging_is_disabled(self):
        self.service.depth_demand = None
        self.stop_error = OSError("Fixture trace_stop connection failed")
        task, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        error = await self.assert_failed(task, recording, [("trace_stop", str(self.stop_error))], False, False)
        self.assertTrue(self.transport.active)
        self.assertTrue(self.service._runtime("robot")["owned"])
        await self.assert_close_failure(error)
        self.assertEqual(len(self.stop_calls()), 1)

    async def test_recording_restart_retains_failed_stop_owner_and_finishes_same_trace(self):
        self.stop_error = OSError("Fixture trace_stop connection failed")
        first, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        await self.assert_failed(first, recording, [("trace_stop", str(self.stop_error))], False, False)
        self.stop_error = None
        before = len(self.transport.calls)
        second, restarted = await self.enable()
        self.assertIsNot(first, second)
        self.assertNotEqual(recording, restarted)
        trace_calls = [payload for _, _, payload in self.transport.calls[before:] if payload]
        self.assertEqual(trace_calls[0], {"op": "trace_read", "after": 0, "boot_id": 1, "session": 1})
        self.assertTrue(self.service._runtime("robot")["owned"])
        await self.service.configure("robot", {"logging": False})
        await asyncio.wait_for(asyncio.shield(second), 1)
        event = (await self.events(restarted))[-1]
        self.assertTrue(event["trace_stop_acknowledged"])
        self.assertTrue(event["trace_drained"])
        self.assertEqual((event["boot_id"], event["session"]), (1, 1))
        self.assertEqual([call["session"] for call in self.stop_calls()], [1, 1])
        self.assertEqual(sum(bool(p and p["op"] == "trace_start") for _, _, p in self.transport.calls), 1)
        self.assertTrue((restarted/"metadata.jsonl").exists())
        self.assertFalse(self.transport.active)
        self.assertFalse(self.service._runtime("robot")["owned"])
        await self.service.close()

    async def test_recording_restart_never_adopts_replacement_of_failed_stop_session(self):
        self.stop_error = OSError("Fixture trace_stop connection failed")
        first, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        await self.assert_failed(first, recording, [("trace_stop", str(self.stop_error))], False, False)
        self.stop_error = None
        self.transport.session = 99
        before = len(self.transport.calls)
        second, restarted = await self.enable()
        trace_calls = [payload for _, _, payload in self.transport.calls[before:] if payload]
        self.assertEqual(trace_calls[0]["session"], 1, "First read remains fenced to the original owner")
        self.assertFalse(self.service._runtime("robot")["owned"])
        await self.service.configure("robot", {"logging": False})
        await asyncio.wait_for(asyncio.shield(second), 1)
        self.assertEqual([call["session"] for call in self.stop_calls()], [1])
        self.assertTrue(self.transport.active)
        event = (await self.events(restarted))[-1]
        self.assertEqual(event["session"], 99)
        self.assertIsNone(event["trace_stop_acknowledged"])
        await self.service.close()

    async def test_combined_independent_failures_are_persisted_and_visible(self):
        self.depth_error = RuntimeError("Fixture depth-release submission failed")
        self.stop_error = OSError("Fixture trace_stop connection failed")
        task, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        error = await self.assert_failed(task, recording,
            [("depth_release", str(self.depth_error)), ("trace_stop", str(self.stop_error))], False, False)
        self.assertEqual(error.exceptions, (self.depth_error, self.stop_error))
        await self.assert_close_failure(error)
        self.assertEqual(len(self.stop_calls()), 1)

    async def test_drain_failure_keeps_acknowledged_stop_and_partial_recording_distinct(self):
        self.more_after_stop = True
        self.drain_error = OSError("Fixture trace drain failed")
        task, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        error = await self.assert_failed(task, recording, [("trace_drain", str(self.drain_error))], True, False)
        self.assertFalse(self.transport.active)
        self.assertFalse(self.service._runtime("robot")["owned"])
        trace = [json.loads(row) for row in (recording/"trace.jsonl").read_text().splitlines()]
        self.assertTrue(any(any(r.get("fixture") == "last owned sample" for r in b["records"]) for b in trace))
        self.assertEqual(self.transport.calls[-1][2], {"op": "trace_read", "after": 1, "boot_id": 1, "session": 1})
        await self.assert_close_failure(error)

    async def test_unowned_session_is_not_stopped(self):
        self.transport.active, self.transport.session = True, 17
        task, recording = await self.enable()
        self.assertFalse(self.service._runtime("robot")["owned"])
        await self.service.configure("robot", {"logging": False})
        await asyncio.wait_for(asyncio.shield(task), 1)
        self.assertFalse(self.stop_calls())
        event = (await self.events(recording))[-1]
        self.assertEqual(event["session"], 17)
        self.assertIsNone(event["trace_stop_acknowledged"])
        self.assertTrue(self.transport.active)
        await self.service.close()

    async def test_replacement_racing_stop_never_stops_new_session(self):
        task, recording = await self.enable()
        self.transport.session = 99
        await self.service.configure("robot", {"logging": False})
        error = await self.assert_failed(task, recording,
            [("trace_stop", "Device trace session changed")], False, False)
        self.assertEqual(self.stop_calls()[0]["session"], 1)
        self.assertEqual(len(self.stop_calls()), 1)
        self.assertTrue(self.transport.active)
        self.assertFalse(self.service._runtime("robot")["owned"])
        await self.assert_close_failure(error)


    async def test_repeated_recorder_and_close_waiter_cancellation_drain_and_report_failure(self):
        self.depth_error = RuntimeError("Fixture depth-release submission failed")
        task, recording = await self.enable()
        self.release_stop.clear()
        owner = asyncio.create_task(self.service.close())
        observer = None
        try:
            for _ in range(100):
                if task.done() or self.stop_entered.is_set(): break
                await asyncio.sleep(.01)
            self.assertTrue(self.stop_entered.is_set())
            task.cancel()
            task.cancel()
            owner.cancel()
            await asyncio.sleep(0)
            owner.cancel()
            observer = asyncio.create_task(self.service.close())
            await asyncio.sleep(0)
            self.assertFalse(owner.done())
            self.assertFalse(observer.done())
            self.transport.close.assert_not_awaited()
            self.assertFalse(self.service.writer.done())
            self.release_stop.set()
            with self.assertRaises(asyncio.CancelledError) as cancelled:
                await owner
            self.assertTrue(owner.cancelled())
            with self.assertRaises(ExceptionGroup) as failed:
                await observer
            self.assertIs(cancelled.exception.__cause__, failed.exception)
            self.assertTrue(task.cancelled())
            self.assertIn(str(self.depth_error), self.service.status("robot")["error"])
            event = (await self.events(recording))[-1]
            self.assertTrue(event["trace_stop_acknowledged"])
            self.assertTrue(event["trace_drained"])
            await self.assert_close_failure(failed.exception)
        finally:
            self.release_stop.set()
            await asyncio.gather(owner, *([observer] if observer else []), return_exceptions=True)


    async def check_owned_release_cancellation(self, initial_cancellation):
        owned_cancel = asyncio.CancelledError("Fixture owned trace-stop cancellation")
        self.stop_error = owned_cancel
        task, _ = await self.enable()
        self.release_stop.clear()
        try:
            if initial_cancellation is None:
                await self.service.configure("robot", {"logging": False})
            else:
                task.cancel(initial_cancellation)
            await asyncio.wait_for(self.stop_entered.wait(), 1)
            self.release_stop.set()
            await asyncio.wait_for(asyncio.wait({task}), 1)
            with self.assertRaises(asyncio.CancelledError) as caught:
                await task
            self.assertTrue(task.cancelled())
            self.assertEqual(caught.exception.args, ())
            self.assertIs(caught.exception.__cause__, owned_cancel)
            self.assertEqual(len(self.stop_calls()), 1)
            # This injected owned-task cancellation is propagation evidence,
            # not an acknowledged device stop or a cleanup recovery claim.
        finally:
            self.release_stop.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_owned_release_task_cancellation_remains_recorder_cancellation(self):
        await self.check_owned_release_cancellation(None)

    async def test_owned_release_cancellation_preserves_existing_initial_cancel_outcome(self):
        await self.check_owned_release_cancellation("Fixture initial recorder cancellation")

    async def test_observed_replacement_is_not_stopped(self):
        task, recording = await self.enable()
        self.transport.session = 17
        for _ in range(100):
            r = self.service._runtime("robot")
            if r["session"] == 17 and not r["owned"]: break
            await asyncio.sleep(.01)
        self.assertEqual(r["session"], 17)
        self.assertFalse(r["owned"])
        await self.service.configure("robot", {"logging": False})
        await asyncio.wait_for(asyncio.shield(task), 1)
        self.assertFalse(self.stop_calls())
        self.assertTrue(self.transport.active)
        self.assertIsNone((await self.events(recording))[-1]["trace_stop_acknowledged"])
        await self.service.close()

    async def test_active_stop_reply_is_not_claimed_as_acknowledged(self):
        self.stop_active_reply = True
        task, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        error = await self.assert_failed(task, recording,
            [("trace_stop", "Trace stop did not acknowledge the owned inactive session")], False, False)
        self.assertTrue(self.service._runtime("robot")["owned"])
        await self.assert_close_failure(error)
        self.assertEqual(len(self.stop_calls()), 1)

    async def test_repeated_recorder_cancel_finishes_release_before_cancellation(self):
        task, recording = await self.enable()
        self.release_stop.clear()
        try:
            task.cancel()
            await asyncio.wait_for(self.stop_entered.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.release_stop.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(task.cancelled())
            self.assertFalse(self.transport.active)
            self.assertIsNone(self.service.status("robot")["error"])
            self.assertTrue((await self.events(recording))[-1]["trace_drained"])
            await self.service.close()
            self.assertFalse(self.service.writer.cancelled())
            self.assertIsNone(self.service.writer.exception())
        finally:
            self.release_stop.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_transport_failure_keeps_recorder_error_context_and_writer_release(self):
        self.stop_error = OSError("Fixture trace_stop connection failed")
        task, recording = await self.enable()
        await self.service.configure("robot", {"logging": False})
        error = await self.assert_failed(task, recording, [("trace_stop", str(self.stop_error))], False, False)
        transport_error = RuntimeError("Fixture transport close failed")
        self.transport.close.side_effect = transport_error
        for _ in range(2):
            with self.assertRaises(RuntimeError) as failed:
                await self.service.close()
            self.assertIs(failed.exception, transport_error)
            self.assertIs(failed.exception.__context__, error)
        self.transport.close.assert_awaited_once()
        self.assertTrue(self.service.writer.done())
        self.assertFalse(self.service.writer.cancelled())
        self.assertIsNone(self.service.writer.exception())
        self.assertTrue(self.service.writes.empty())
        self.assertEqual(len(self.stop_calls()), 1)


    async def test_entrypoint_cancellation_keeps_dependencies_until_recorder_failure_is_reported(self):
        from test_gateway_security import GatewayStartupTests
        import gateway.server.__main__ as gateway_main

        with tempfile.TemporaryDirectory() as directory:
            with GatewayStartupTests().startup_fixture(Path(directory), real_gait=True, stop_at_serve=False) as f:
                f.gateway.status = self.gateway.status
                f.gateway.body_calibration = self.gateway.body_calibration
                f.gateway.body_balance = self.gateway.body_balance
                f.transport.request.side_effect = self.transport.request
                f.camera.depth_demand.side_effect = self.service.depth_demand
                self.depth_error = RuntimeError("Fixture depth-release submission failed")
                self.release_stop.clear()
                owner = asyncio.create_task(gateway_main._run_production(f.args))
                observer = None
                try:
                    await asyncio.wait_for(f.listening.wait(), 1)
                    f.gait.optimizer = Mock(side_effect=AssertionError("No training in entrypoint fixture"))
                    await f.gait.configure("robot", {"logging": True, "learning": False})
                    await asyncio.wait_for(self.started.wait(), 1)
                    recording = f.gait._runtime("robot")["recording"]
                    owner.cancel()
                    await asyncio.wait_for(self.stop_entered.wait(), 1)
                    owner.cancel()
                    await asyncio.sleep(0)
                    owner.cancel()
                    observer = asyncio.create_task(f.gait.close())
                    await asyncio.sleep(0)
                    self.assertFalse(owner.done())
                    self.assertFalse(observer.done())
                    f.gateway.close.assert_not_awaited()
                    f.camera.aclose.assert_not_awaited()
                    f.transport.close.assert_not_awaited()
                    self.release_stop.set()
                    with self.assertRaises(asyncio.CancelledError) as cancelled:
                        await owner
                    with self.assertRaises(ExceptionGroup) as failed:
                        await observer
                    self.assertIs(cancelled.exception.__cause__, failed.exception)
                    self.assertTrue(owner.cancelled())
                    self.assertTrue(f.gait.writer.done())
                    self.assertFalse(f.gait.writer.cancelled())
                    self.assertIsNone(f.gait.writer.exception())
                    rows = [json.loads(row)["value"] for row in (recording/"events.jsonl").read_text().splitlines()]
                    cleanup = next(row for row in rows if row["t"] == "recording_cleanup")
                    self.assertEqual(cleanup["errors"][0]["error"], str(self.depth_error))
                    f.transport.close.assert_awaited_once()
                    f.gateway.close.assert_awaited_once()
                    f.camera.aclose.assert_awaited_once()
                    f.gait.optimizer.assert_not_called()
                finally:
                    self.release_stop.set()
                    await asyncio.gather(owner, *([observer] if observer else []), return_exceptions=True)
                    await asyncio.gather(f.gait.close(), return_exceptions=True)


class BankRestorationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.services = []
        self.banks = {
            "walk": {"converged": False, "incumbent": {"id": "walk-incumbent"},
                     "candidate": {"id": "walk-candidate"}},
            "run": {"converged": True, "incumbent": {"id": "run-incumbent"},
                    "candidate": {"id": "run-candidate"}},
        }

    async def asyncTearDown(self):
        # Emergency release is not used as a successful-cleanup assertion.
        await asyncio.gather(*(s.close() for s in self.services), return_exceptions=True)

    def make_service(self, name, settings=None, bank=None):
        root = Path(self.temp.name)/name
        root.mkdir()
        (root/"settings.json").write_text(json.dumps({"robot": settings or {"logging": False, "learning": False}}))
        service, _ = make_gait_service(root)
        self.services.append(service)
        path = service._runtime("robot")["root"]/"training.json"
        if bank is not None:
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(bank))
        return service, path

    async def finish(self, service):
        await service.close()
        await assert_writer_finished(self, service)
        service.transport.close.assert_awaited_once()
        service.transport.request.assert_not_awaited()
        service.optimizer.assert_not_called()

    def expected_pending(self):
        return {"walk": (self.banks["walk"]["candidate"], False),
                "run": (self.banks["run"]["incumbent"], False)}

    async def record_without_external_work(self, service):
        # Exercise the real recorder's loading before its existing closed-loop
        # check, preserving pending models without activating or analysing them.
        service.closed = True
        task = service.tasks["robot"] = asyncio.create_task(service._record("robot"))
        await task

    async def test_startup_loads_flags_off_logging_only_and_learning_restoration(self):
        for logging, learning in ((False, False), (True, False), (False, True)):
            with self.subTest(logging=logging, learning=learning):
                service, _ = self.make_service(str((logging, learning)),
                    {"logging": logging, "learning": learning}, self.banks)
                r = service._runtime("robot")
                retained = ({"id": "unrelated pending"}, True)
                r["pending"]["other"] = retained
                await service.start()
                # start() creates the recorder but does not await its body.
                self.assertEqual(r["banks"], self.banks)
                self.assertEqual(r["pending"], {"other": retained, **(self.expected_pending() if learning else {})})
                self.assertEqual("robot" in service.tasks, logging or learning)
                await self.finish(service)

    async def test_recorder_fallback_restores_only_when_learning_is_enabled(self):
        for learning in (False, True):
            with self.subTest(learning=learning):
                service, path = self.make_service("fallback-"+str(learning))
                await service.start()
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(self.banks))
                service.settings["robot"] = {"logging": False, "learning": learning}
                retained = ({"id": "unrelated pending"}, True)
                service._runtime("robot")["pending"]["other"] = retained
                await self.record_without_external_work(service)
                self.assertEqual(service._runtime("robot")["banks"], self.banks)
                self.assertEqual(service._runtime("robot")["pending"],
                    {"other": retained, **(self.expected_pending() if learning else {})})
                await self.finish(service)

    async def test_populated_recorder_banks_and_pending_survive_corrupt_disk_bank(self):
        service, path = self.make_service("populated")
        await service.start()
        path.parent.mkdir(parents=True)
        path.write_text('{"corrupt":')
        live = {"existing": {"unique": "not replaced"}}
        pending = {"walk": ({"id": "already pending"}, True)}
        r = service._runtime("robot")
        r.update(banks=live, pending=pending)
        service.settings["robot"]["learning"] = True
        await self.record_without_external_work(service)
        self.assertIs(r["banks"], live)
        self.assertIs(r["pending"], pending)
        await self.finish(service)

    async def test_missing_bank_preserves_empty_banks_and_pending(self):
        service, path = self.make_service("missing")
        pending = {"walk": ({"id": "existing pending"}, True)}
        r = service._runtime("robot")
        r["pending"] = pending
        await service.start()
        self.assertFalse(path.exists())
        self.assertFalse(r["banks"])
        await self.record_without_external_work(service)
        self.assertFalse(r["banks"])
        self.assertIs(r["pending"], pending)
        await self.finish(service)

    async def test_corrupt_recorder_bank_preserves_pending_and_close_failure(self):
        service, path = self.make_service("corrupt-recorder")
        await service.start()
        path.parent.mkdir(parents=True)
        path.write_text('{"corrupt":')
        pending = {"other": ({"id": "retained"}, True)}
        service._runtime("robot")["pending"] = pending
        with self.assertRaises(json.JSONDecodeError) as original:
            await self.record_without_external_work(service)
        self.assertIs(service._runtime("robot")["pending"], pending)
        with self.assertRaises(json.JSONDecodeError) as closed:
            await service.close()
        self.assertIs(closed.exception, original.exception)
        await assert_writer_finished(self, service)
        service.transport.close.assert_awaited_once()
        service.transport.request.assert_not_awaited()
        service.optimizer.assert_not_called()

    async def replace_settings_during_read(self, service, path, operation, replacement):
        entered, release = threading.Event(), threading.Event()
        original = Path.read_text
        read_threads = []
        def read(current, *args, **kwargs):
            if current == path:
                read_threads.append(threading.get_ident())
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("Fixture bank read was not released")
            return original(current, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            task = asyncio.create_task(operation)
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                service.settings["robot"] = replacement
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
            await task
        self.assertTrue(read_threads)
        self.assertNotEqual(read_threads[0], threading.get_ident())

    async def test_startup_reads_captured_settings_after_threaded_bank_read(self):
        for initial in (False, True):
            with self.subTest(initial=initial):
                service, path = self.make_service("startup-timing-"+str(initial),
                    {"logging": False, "learning": initial}, self.banks)
                # The existing closed-loop condition suppresses downstream model
                # activation if the captured startup policy creates a recorder.
                service.closed = True
                await self.replace_settings_during_read(service, path, service.start(),
                    {"logging": False, "learning": not initial})
                self.assertEqual(service._runtime("robot")["pending"], self.expected_pending() if initial else {})
                self.assertEqual("robot" in service.tasks, initial)
                await self.finish(service)

    async def test_recorder_reads_current_settings_after_threaded_bank_read(self):
        for initial in (False, True):
            with self.subTest(initial=initial):
                service, path = self.make_service("recorder-timing-"+str(initial))
                await service.start()
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(self.banks))
                service.settings["robot"] = {"logging": False, "learning": initial}
                service.closed = True
                await self.replace_settings_during_read(service, path, service._record("robot"),
                    {"logging": False, "learning": not initial})
                self.assertEqual(service._runtime("robot")["pending"], self.expected_pending() if not initial else {})
                await self.finish(service)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gateway, self.transport = Gateway(), Transport()
        self.optimizer_calls = []
        def optimizer(observations, seed=0):
            self.optimizer_calls.append((observations, seed))
            return [.1]*len(DEFAULT_RADII)
        self.service = GaitLearningService(self.gateway, self.transport,
            lambda _: {"available": False, "reason": "No calibration"},
            Path(self.temp.name), optimizer=optimizer,
            projector=lambda base,x,radii,joints,gait,conditions:
                (candidate(base,x,radii),x,{"scale":1., "conditions":len(conditions)}))
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.close()
        self.temp.cleanup()

    async def test_history_is_read_only_and_keeps_robot_contexts_separate(self):
        r = self.service._runtime("robot")
        r["root"].mkdir(parents=True)
        archived = {"observations": [{"score": -.1}], "history": []}
        (r["root"]/"previous-contexts.jsonl").write_text(json.dumps({"gait":"walk", "bank":archived})+"\n")
        r["banks"] = {"walk": {"observations": [{"score": .2, "recorded_at": 123}], "history": []}}
        before = copy.deepcopy(r["banks"])
        result = await self.service.history("robot")
        self.assertEqual([c["current"] for c in result["contexts"]], [False, True])
        self.assertNotIn("recorded_at", result["contexts"][0]["bank"]["observations"][0])
        self.assertEqual(result["contexts"][1]["bank"]["observations"][0]["recorded_at"],123)
        result["contexts"][1]["bank"]["observations"].clear()
        self.assertEqual(r["banks"], before)
        self.assertEqual((await self.service.history("different-robot"))["contexts"], [])
        self.assertFalse(self.transport.calls)
        self.assertFalse(self.optimizer_calls)

    async def test_history_reads_saved_data_when_recording_is_off(self):
        r = self.service._runtime("robot")
        r["root"].mkdir(parents=True)
        bank = {"observations": [{"score": .3}], "history": []}
        (r["root"]/"training.json").write_text(json.dumps({"run":bank}))
        result = await self.service.history("robot")
        self.assertEqual(result["contexts"], [{"gait":"run","current":True,"bank":bank}])
        self.assertFalse(r["banks"])
        self.assertFalse(self.transport.calls)

    async def test_device_restart_reacquires_trace_without_old_cursor_or_window(self):
        original = self.transport.request
        restarted = asyncio.Event()
        resumed = asyncio.Event()
        async def request(robot, endpoint, payload):
            if payload and payload["op"] == "trace_read" and payload.get("after") == 100:
                self.assertEqual((payload["boot_id"], payload["session"]), (1, 1))
                restarted.set()
                raise TraceSessionChanged("Device trace session changed")
            result = await original(robot, endpoint, payload)
            if payload and payload["op"] == "trace_start":
                result[-1]["next"] = 100
            if restarted.is_set() and payload and payload["op"] == "trace_read":
                self.assertEqual(payload["after"], 0)
                self.assertNotIn("session", payload)
                r = self.service._runtime(robot)
                self.assertIsNone(r["window"])
                self.assertFalse(r["owned"])
                self.assertEqual(r["poses"], [])
                result[0]["boot_id"] = 2
                resumed.set()
                # Finish after this batch, without adding motion authority.
                self.service.settings[robot]["logging"] = False
            return result
        self.transport.request = request
        await self.service.configure("robot", {"logging": True})
        await asyncio.wait_for(resumed.wait(), 2)
        await self.service.tasks["robot"]
        self.assertFalse(any(p and p["op"] == "trace_stop" for _, _, p in self.transport.calls))
        self.assertEqual(self.service._runtime("robot")["boot"], 2)
        self.assertEqual(sum(e == "firmware" for _, e, _ in self.transport.calls), 2)

    async def test_http_reconnect_preserves_window_until_device_reports_loss(self):
        original = self.transport.request
        reads = 0
        window = {"recorded": "partial cycle"}
        async def request(robot, endpoint, payload):
            nonlocal reads
            if payload and payload["op"] == "trace_read":
                reads += 1
                if reads == 2:
                    raise OSError("peer closed HTTP socket")
                if reads == 3:
                    self.assertEqual(payload["after"],100)
                    self.assertIs(self.service._runtime(robot)["window"],window)
                    self.service.settings[robot]["logging"] = False
                return [{"schema":"gait_trace_v1","boot_id":1,"session":1,"active":True},
                        {"next":100,"lost":0,"more":True}]
            return await original(robot,endpoint,payload)
        async def consume(robot,batch):
            self.service._runtime(robot)["window"] = window
        self.transport.request = request
        self.service._consume = consume
        await self.service.configure("robot",{"logging":True})
        await self.service.tasks["robot"]
        self.assertEqual(reads,3)

    async def test_persistent_recording_without_browser_and_no_motion_authority(self):
        self.assertEqual(self.transport.calls, [])
        await self.service.configure("robot", {"logging": True})
        await asyncio.sleep(.03)
        self.gateway.commands[0]({"robot_id": "robot", "seq": 3, "t": "intent", "name": "walk"})
        self.gateway.frames[0]({"robot_id": "robot", "frame_type": CAMERA_JPEG_FRAME_TYPE,
                               "counter": 1, "epoch": 1, "payload": b"jpeg-test"})
        await self.service.writes.join()
        folder = Path(self.service.status("robot")["recording"])
        self.assertTrue((folder/"trace.jsonl").exists())
        metadata = json.loads((folder/"metadata.jsonl").read_text().splitlines()[0])
        self.assertIsNone(self.gateway.status()["robots"]["robot"]["balance_settings"])
        self.assertEqual(self.gateway.balance_reads, [("get", "robot")])
        self.assertEqual(metadata["execution_settings"]["balance_settings"],
                         {"enabled": True, "strength": 1., "damping": 1., "roll_deg": 3., "pitch_deg": 1.5928})
        self.assertEqual(metadata["execution_settings"]["motion_speed"], {"joint_speed_limit_deg_s": 545.45})
        self.assertNotIn("unrelated_private_data", metadata["execution_settings"])
        self.assertTrue((folder/"commands.jsonl").exists())
        self.assertEqual(len(list((folder/"camera").glob("*.jpg"))), 1)
        persisted = json.loads((Path(self.temp.name)/"settings.json").read_text())
        self.assertTrue(persisted["robot"]["logging"])
        self.assertEqual(self.optimizer_calls, [])
        self.assertTrue(all(endpoint == "servo-feedback" or payload is None for _, endpoint, payload in self.transport.calls))
        await self.service.configure("robot", {"logging": False})
        await asyncio.sleep(.15)
        self.assertEqual(self.service.status("robot")["state"], "off")
        self.assertEqual(self.transport.calls[-1][2]["op"], "trace_stop")

    async def test_unavailable_balance_readback_is_explicit_and_does_not_stop_recording(self):
        self.gateway.body_balance = AsyncMock(side_effect=RuntimeError("self-leveling readback timed out"))
        await self.service.configure("robot", {"logging": True})
        await asyncio.sleep(.03)
        await self.service.writes.join()
        folder = Path(self.service.status("robot")["recording"])
        settings = json.loads((folder/"metadata.jsonl").read_text().splitlines()[0])["execution_settings"]
        self.assertIsNone(settings["balance_settings"])
        self.assertEqual(settings["balance_settings_error"], "self-leveling readback timed out")
        self.assertTrue((folder/"trace.jsonl").exists())
        self.assertEqual(self.service.status("robot")["state"], "logging")
        self.gateway.body_balance.assert_awaited_once_with("get", robot_id="robot")

    async def test_balance_changes_are_recorded_from_acknowledged_command_results(self):
        # This readback is not published as a normal gateway event. Exercise the
        # actual terminal owner so the recorder cannot depend on a fictitious one.
        owner = GatewayService(GatewayServiceConfig(tokens={}))
        connection = GatewayConnection(owner, Mock(closed=False, send=AsyncMock()), "robot", 7)
        connection.model = "v2-12servo"
        connection.features = {"balance_control_v1", "balance_tuning_v1"}
        owner._connections["robot"] = connection
        owner.subscribe_diagnostics(self.service.diagnostic)
        folder = Path(self.temp.name)/"balance-trial"
        self.service.settings["robot"] = {"logging": True, "learning": False}
        self.service._runtime("robot")["recording"] = folder
        try:
            seq = await connection.send_command({"t": "balance", "op": "save", "enabled": True,
                "strength": 1., "damping": 1., "roll_deg": 3., "pitch_deg": 1.5928}, received_at=owner.clock())
            readback = {"t": "balance_status", "seq": seq, "enabled": True, "saved": True,
                "active": False, "walking_enabled": True, "walking_saved": True,
                "strength": 1., "damping": 1., "roll_deg": 3., "pitch_deg": 1.5928,
                "tuning_saved": True, "unrelated_private_data": "do-not-record"}
            await connection._handle_control(readback)
            await self.service.writes.join()
            self.assertFalse((folder/"events.jsonl").exists(), "Unacknowledged settings are not applied evidence")
            await connection._handle_control({"t": "ack", "seq": seq})
            await connection._handle_control(readback)
            readback["roll_deg"] = 999
            await self.service.writes.join()
            rows = [json.loads(line) for line in (folder/"events.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertGreater(rows[0]["host_monotonic_s"], 0)
            self.assertEqual(rows[0]["value"], {
                "event": "command_result", "robot_id": "robot", "epoch": 7,
                "seq": seq, "command_type": "balance", "op": "save", "t": "balance_status",
                "enabled": True, "saved": True, "active": False, "walking_enabled": True,
                "walking_saved": True, "strength": 1., "damping": 1., "roll_deg": 3.,
                "pitch_deg": 1.5928, "tuning_saved": True})
        finally:
            connection.cancel_pending()
            owner.unsubscribe_diagnostics(self.service.diagnostic)

    async def test_motion_terminals_preserve_finish_release_and_failures_after_disconnect(self):
        owner = GatewayService(GatewayServiceConfig(tokens={}))
        connection = GatewayConnection(owner, Mock(closed=False, send=AsyncMock()), "robot", 7)
        connection.model = "v2-12servo"
        connection.features = {"walk_controls_v2", "body_commands_v1"}
        connection.capabilities = {"motion": True, "commands": ["walk", "stop"]}
        owner._connections["robot"] = connection
        owner.subscribe_diagnostics(self.service.diagnostic)
        folder = Path(self.temp.name)/"motion-terminals"
        self.service.settings["robot"] = {"logging": True, "learning": False}
        self.service._runtime("robot")["recording"] = folder
        try:
            walk = await connection.send_command({"t": "intent", "name": "walk", "dir": "fwd", "steps": 0}, received_at=owner.clock())
            await connection._handle_control({"t": "ack", "seq": walk})
            await self.service.writes.join()
            self.assertFalse((folder/"events.jsonl").exists(), "Walk acknowledgement is not completion")
            finish = await connection.send_command({"t": "intent", "name": "walk", "dir": "fwd",
                "speed": 0, "steps": 0, "update": walk}, received_at=owner.clock())
            await connection._handle_control({"t": "ack", "seq": finish})
            await connection._handle_control({"t": "done", "seq": walk})
            release = await connection.send_command({"t": "stop", "detach": True}, received_at=owner.clock())
            await connection._handle_control({"t": "ack", "seq": release, "unrelated_private_data": "do-not-record"})
            failed = await connection.send_command({"t": "intent", "name": "walk", "dir": "fwd", "steps": 0}, received_at=owner.clock())
            await connection._handle_control({"t": "nak", "seq": failed, "code": "output_unavailable"})
            disconnected = await connection.send_command({"t": "intent", "name": "walk", "dir": "fwd", "steps": 0}, received_at=owner.clock())
            connection.cancel_pending("disconnect")
            owner._connections.clear()
            await self.service.writes.join()
            rows = [json.loads(line)["value"] for line in (folder/"events.jsonl").read_text().splitlines()]
            self.assertEqual([(r["seq"], r["t"]) for r in rows],
                [(finish, "ack"), (walk, "done"), (release, "ack"), (failed, "nak"), (disconnected, "cancelled")])
            self.assertEqual(rows[0]["update"], walk)
            self.assertTrue(rows[2]["detach"])
            self.assertEqual(rows[3]["code"], "output_unavailable")
            self.assertEqual(rows[4]["code"], "disconnect")
            self.assertTrue(all(r["epoch"] == 7 and r["robot_id"] == "robot" for r in rows))
            self.assertNotIn("do-not-record", (folder/"events.jsonl").read_text())
        finally:
            connection.cancel_pending()
            owner.unsubscribe_diagnostics(self.service.diagnostic)

    async def test_walk_target_receipts_are_saved_without_claiming_consumption(self):
        owner = GatewayService(GatewayServiceConfig(tokens={}))
        connection = GatewayConnection(owner, Mock(closed=False, send=AsyncMock()), "robot", 7)
        connection.model = "v2-12servo"
        connection.features = {"walk_nominal_v1", "walk_controls_v2", "body_commands_v1"}
        connection.capabilities = {"motion": True, "commands": ["walk", "stop"]}
        owner._connections["robot"] = connection
        owner.subscribe_diagnostics(self.service.diagnostic)
        folder = Path(self.temp.name)/"target-receipts"
        self.service.settings["robot"] = {"logging": True, "learning": False}
        self.service._runtime("robot")["recording"] = folder
        try:
            walk = await connection.send_command({"t": "intent", "name": "walk", "dir": "fwd",
                "steps": 0, "source": "host", "geometry": "fixture", "reference_cd": [0.]*12,
                "twist": [.08, 0., 0.]}, received_at=owner.clock())
            await connection._handle_control({"t": "ack", "seq": walk})
            for sample, result in ((11, "ack"), (12, "nak")):
                seq = await connection.send_command({"t": "walk_target", "walk": walk,
                    "sample": sample, "geometry": "fixture", "feet_mm": [0., 0., -50.]*4}, received_at=owner.clock())
                await connection._handle_control({"t": result, "seq": seq,
                    **({"code": "stale_walk"} if result == "nak" else {}),
                    "unrelated_private_data": "do-not-record"})
            await self.service.writes.join()
            rows = [json.loads(line)["value"] for line in (folder/"events.jsonl").read_text().splitlines()]
            self.assertEqual([(r["command_type"], r["walk"], r["sample"], r["t"]) for r in rows],
                [("walk_target", walk, 11, "ack"), ("walk_target", walk, 12, "nak")])
            self.assertTrue(all(r["robot_id"] == "robot" and r["epoch"] == 7 for r in rows))
            self.assertEqual(rows[1]["code"], "stale_walk")
            self.assertNotIn("consumed_sample", rows[0])
            self.assertNotIn("do-not-record", (folder/"events.jsonl").read_text())
        finally:
            connection.cancel_pending()
            owner.unsubscribe_diagnostics(self.service.diagnostic)

    async def test_neural_trial_preserves_requested_consumed_and_fault_evidence(self):
        self.service.settings["robot"] = {"logging": True, "learning": False}
        folder = Path(self.temp.name)/"physical-trial"
        self.service._runtime("robot")["recording"] = folder
        start = {"t": "intent", "robot_id": "robot", "epoch": 3, "seq": 41,
                 "name": "walk", "source": "host", "geometry": "measured-v2",
                 "reference_cd": [0]*12, "twist": [.015, 0, 0], "token": "not-recorded"}
        target = {"t": "walk_target", "robot_id": "robot", "epoch": 3, "seq": 42,
                  "walk": 41, "sample": 7, "geometry": "measured-v2", "feet_mm": [1]*12}
        self.gateway.commands[0](start)
        self.gateway.commands[0](target)
        diagnostic = {"event": "neural_gait", "robot_id": "robot", "epoch": 3,
                      "walk": 41, "sample": 7, "model_id": "candidate", "action": [.1]*12,
                      "checkpoint_id": "000065536-imitation000560000",
                      "requested_foot_offset_mm": [1]*12, "observation_device_us": 100000,
                      "scan": 12, "consumed_sample": 6,
                      "orientation_reference_yaw_rad": 1.2, "orientation_reference_sign": -1,
                      "learning_trial": True, "revision": 2, "feedback_revision": 54,
                      "demonstration": {"source":"native-c", "phase":.2},
                      "policy_observation": {"schema": "ainekio-neural-gait-v5-history",
                          "encoding": "float32-le-zlib-base64", "values": "recorded-input-fixture"},
                      "inference_elapsed_s": .003, "token": "not-recorded"}
        self.gateway.diagnostics[0](diagnostic)
        original_observation = copy.deepcopy(diagnostic["policy_observation"])
        diagnostic["action"][0] = 999  # Async storage retains the inference as observed.
        diagnostic["policy_observation"]["values"] = "later-input-must-not-overwrite"
        self.gateway.diagnostics[0]({"event": "unrelated", "robot_id": "robot", "token": "secret"})
        failed = {"event": "neural_gait", "robot_id": "robot", "epoch": 3,
                  "walk": 41, "model_id": "candidate", "error": "Inference unavailable",
                  "finish_sequence": 44}
        self.gateway.diagnostics[0](failed)
        final = {"event":"neural_gait", "robot_id":"robot", "epoch":3, "walk":41,
                 "model_id":"candidate", "consumed_sample":7, "outcome":"failure",
                 "outcome_evidence":{"kind":"tipped", "event_id":"fall-1"},
                 "policy_observation":copy.deepcopy(original_observation)}
        self.gateway.diagnostics[0](final)
        consumed = {"t": "imu", "robot_id": "robot", "epoch": 3,
                    "imu": {"motion": {"seq": 41, "walk_source": "host", "nominal_sample": 7,
                                       "sampled_us": 120000}, "joint_feedback": {"scan": 13}}}
        fault = {"t": "event", "name": "body_event", "robot_id": "robot", "epoch": 3,
                 "data": {"kind": "servo_stall", "command_sequence": 41, "joint_mask": 1}}
        rejected = {"t": "nak", "robot_id": "robot", "epoch": 3, "seq": 43, "code": "owner"}
        cancelled = {"t": "cancelled", "robot_id": "robot", "epoch": 3, "seq": 41, "code": "stop"}
        for event in (consumed, fault, rejected, cancelled):
            self.gateway.events[0](event)
        await self.service.writes.join()
        rows = lambda name: [json.loads(line)["value"] for line in (folder/name).read_text().splitlines()]
        commands, neural, events = rows("commands.jsonl"), rows("neural.jsonl"), rows("events.jsonl")
        self.assertEqual(commands[0], {k: v for k, v in start.items() if k != "token"})
        self.assertEqual(commands[1], target)
        self.assertEqual(len(neural), 3)
        self.assertEqual(neural[0]["action"], [.1]*12)
        self.assertEqual(neural[0]["checkpoint_id"], "000065536-imitation000560000")
        self.assertEqual(neural[0]["consumed_sample"], 6)
        self.assertTrue(neural[0]["learning_trial"])
        self.assertEqual((neural[0]["revision"], neural[0]["feedback_revision"]), (2, 54))
        self.assertEqual(neural[0]["policy_observation"], original_observation)
        self.assertEqual(neural[0]["demonstration"], {"source":"native-c", "phase":.2})
        self.assertEqual(neural[0]["orientation_reference_yaw_rad"], 1.2)
        self.assertEqual(neural[0]["orientation_reference_sign"], -1)
        self.assertEqual(neural[1], failed)
        self.assertEqual(neural[2], final)
        self.assertNotIn("token", neural[0])
        self.assertEqual(events, [consumed, fault, rejected, cancelled])
        self.assertEqual(neural[0]["sample"], events[0]["imu"]["motion"]["nominal_sample"])
        self.assertFalse(self.transport.calls)
        self.assertFalse(self.optimizer_calls)
        await self.service.close()
        self.assertEqual(self.gateway.diagnostics, [])

    async def test_ordinary_walk_windows_score_all_directions_without_moving_robot(self):
        self.service.settings["robot"] = dict(logging=True, learning=False, window_cycles=1,
                                             weights=DEFAULT_WEIGHTS.copy())
        r = self.service._runtime("robot")
        r["latest_imu"] = [0., 0., 9.80665]
        r["recording"] = r["root"]/"test-recording"
        for category, gait, command in (("forward", "walk", [1,0,0,1]),
                ("backward", "walk", [-1,0,0,1]), ("turning", "walk", [0,1,0,1]),
                ("run", "run", [1,0,0,1])):
            batch = policy_recording()[0]
            model = policy_seed([batch], gait=True)["model"]
            for i, e in enumerate(batch["records"][1:-1]):
                e["time_us"] = 1000000+i*20000
                e["policy"].update(gait=gait, command=command,
                    cycles_s=i*.1, requested_rate=2.,
                    reference_twist_m_s_rad_s=[0., 0., 0.],
                    profile_signature=profile_signature(model["gait_profile"]))
            batch.update(request_monotonic_s=5, received_monotonic_s=5)
            r["poses"] = [pose(1), pose(2, x=.2), pose(3, x=.4), pose(4, x=.6), pose(5, x=.8)]
            r["window"] = None
            await self.service._consume("robot", batch)
            self.assertGreater(r["coverage"][category], 0)
        await self.service.writes.join()
        self.assertTrue(all(endpoint == "gait-learning" and p["op"] == "read" for _,endpoint,p in self.transport.calls))
        windows = [json.loads(line) for line in (r["recording"]/"windows.jsonl").read_text().splitlines()]
        self.assertEqual({w["category"] for w in windows}, set(("forward", "backward", "turning", "run")))
        self.assertTrue(all("score" in w for w in windows))
        self.assertTrue(all(w["key"][10] == 2 for w in windows))

    async def test_missing_distance_never_promotes_tracking_only_improvement(self):
        self.service.settings["robot"] = dict(logging=True, learning=True, window_cycles=1,
            weights=DEFAULT_WEIGHTS.copy())
        r = self.service._runtime("robot");r["recording"] = r["root"]/"no-distance"
        batch = policy_recording()[0]
        for i, e in enumerate(batch["records"][1:-1]):
            e["time_us"] = 1000000+i*20000
            e["policy"]["profile_signature"] = profile_signature([0.]*33)
        batch.update(request_monotonic_s=5, received_monotonic_s=5)
        await self.service._consume("robot", batch)
        await self.service.writes.join()
        self.assertFalse(r["banks"])
        self.assertFalse(self.transport.calls)
        window = json.loads((r["recording"]/"windows.jsonl").read_text().splitlines()[0])
        self.assertIn("Metric camera", window["unscored_reason"])

    async def test_partial_observations_keep_cycle_window_and_backlog_uses_live_clock(self):
        self.service.settings["robot"] = dict(logging=True, learning=False, window_cycles=1,
                                             weights=DEFAULT_WEIGHTS.copy())
        r = self.service._runtime("robot")
        r["latest_imu"] = [0., 0., 9.80665]
        r["recording"] = r["root"]/"partial-observations"
        self.service._observation = AsyncMock()
        batch = policy_recording()[0]
        for i, e in enumerate(batch["records"][1:-1]):
            e["time_us"] = 1000000+i*20000
            e["policy"].update(requested_rate=2., reference_twist_m_s_rad_s=[.2,0,0],
                               profile_signature=profile_signature([0.]*33), model_active=True)
            if i%3 == 1:
                e["valid_mask"] = 7
                e["policy"]["usable"] = False
                e["policy"]["model_active"] = False
                for leg in e["legs"]:
                    leg["measured_mm"] = [10000.]*3  # Must never enter the objective.
        batch.update(request_monotonic_s=500., received_monotonic_s=501.,
                     clock_anchor={"device_s":10., "received_monotonic_s":110., "epoch":1})
        r["poses"] = [pose(101+i*.1, x=i*.02) for i in range(41)]
        await self.service._consume("robot", batch)
        result = self.service._observation.await_args.args[2]
        self.assertEqual(result["alignment"], "live-status receipt")
        self.assertGreater(result["unavailable_tracking_observations"], 0)
        self.assertGreater(result["model_active_observations"], 0)
        self.assertLess(result["model_active_observations"], result["tracking_observations"])
        self.assertTrue(result["key"][9])
        self.assertLess(result["metrics"]["tracking_rms_mm"], 5)
        self.assertAlmostEqual(result["metrics"]["progress_m_s"], .2)

    async def test_clock_anchor_tracks_status_and_is_cleared_on_reconnect(self):
        r = self.service._runtime("robot")
        with patch("gateway.gait_learning_service.time.monotonic", return_value=100.):
            self.service.event({"t":"status", "robot_id":"robot", "epoch":1, "clock_ms":1000})
        self.assertEqual(r["clock_anchor"], {"device_s":1., "received_monotonic_s":100., "epoch":1})
        self.service.event({"t":"connection", "status":"connected", "robot_id":"robot", "epoch":2})
        self.assertIsNone(r["clock_anchor"])

    async def test_camera_history_uses_frame_event_not_dashboard_expiry(self):
        self.service.settings["robot"] = dict(logging=True, learning=False)
        r = self.service._runtime("robot")
        r["recording"] = r["root"]/"camera-history"
        first = pose(1., x=.1)
        failed = {**pose(2.), "available":False, "position":None, "reason":"fit failed"}
        for p in (first, failed):
            self.service.event(dict(t="locomotion_measurement",robot_id="robot",measurement=p))
        self.service.measurement = lambda robot: {**first, "available":False, "reason":"expired"}
        self.assertEqual(r["poses"], [first, failed])
        await self.service.writes.join()
        stored = [json.loads(l)["value"] for l in (r["recording"]/"poses.jsonl").read_text().splitlines()]
        self.assertEqual(stored, [first, failed])

    async def test_analysis_waits_for_backward_turning_and_keeps_run_separate(self):
        await self.service.configure("robot", {"learning": True})
        model = policy_seed(policy_recording(), gait=True)["model"]
        r = self.service._runtime("robot")
        bank = dict(incumbent=model, centre=model, candidate=model, coordinates=[0.]*len(DEFAULT_RADII),
                    generation=0, plateau=0, history=[], observations=[])
        r["banks"]["walk"] = bank
        for category in ("forward", "backward"):
            bank["observations"] += [dict(x=[0.]*len(DEFAULT_RADII), score=.1, category=category, maneuver=category, condition=category, model_id=model["id"])]*2
        await self.service._analyze("robot")
        self.assertFalse(self.optimizer_calls)
        for maneuver in ("turn_left", "turn_right"):
            bank["observations"] += [dict(x=[0.]*len(DEFAULT_RADII), score=.1, category="turning", maneuver=maneuver, condition=maneuver, model_id=model["id"])]*2
        await self.service._analyze("robot")
        self.assertEqual(len(self.optimizer_calls), 1)
        self.assertNotEqual(bank["candidate"]["id"], model["id"])
        await self.service._apply_pending("robot")
        installs = [p for _, endpoint, p in self.transport.calls if endpoint == "gait-learning" and p and p["op"] == "install"]
        self.assertEqual(installs[-1]["gait"], "walk")
        self.assertFalse(installs[-1]["persist"])
        await self.service.configure("robot", {"learning": False})
        if "walk" in r["pending"]:
            self.assertEqual(r["pending"]["walk"], (model, True))
        else:
            # The asynchronous recorder may already have sent the restore.
            installs = [p for _, endpoint, p in self.transport.calls
                        if endpoint == "gait-learning" and p and p["op"] == "install"]
            self.assertEqual(installs[-1]["model"], model)
            self.assertTrue(installs[-1]["persist"])
        observed = copy.deepcopy(bank["observations"])
        await self.service.configure("robot", {"learning": True})
        self.assertEqual(bank["observations"], observed)

    async def test_manual_analysis_with_learning_off_does_not_install(self):
        await self.service.configure("robot", {"logging": False})
        model = policy_seed(policy_recording(), gait=True)["model"]
        bank = dict(incumbent=model, centre=model, candidate=model, coordinates=[0.]*len(DEFAULT_RADII),
                    generation=0, plateau=0, history=[], observations=[])
        for maneuver in ("forward", "backward", "turn_left", "turn_right"):
            bank["observations"].append(dict(x=[0.]*len(DEFAULT_RADII), score=.1, maneuver=maneuver))
        self.service._runtime("robot")["banks"]["walk"] = bank
        await self.service._analyze("robot", manual=True)
        self.assertIn("proposal", bank)
        self.assertFalse(self.transport.calls)
        self.assertIn("no model was installed", self.service.status("robot")["analysis_note"])

    async def test_promotion_plateau_freeze_and_history_restore(self):
        self.service.settings["robot"] = dict(logging=False, learning=True, window_cycles=4,
            radii=DEFAULT_RADII.copy(), weights=DEFAULT_WEIGHTS.copy(), minimum_improvement=.02, plateau_rounds=1)
        model = policy_seed(policy_recording(), gait=True)["model"]
        bank = dict(incumbent=model, centre=model, candidate=model, coordinates=[0.]*len(DEFAULT_RADII),
                    generation=0, plateau=0, history=[], observations=[])
        r = self.service._runtime("robot");r["banks"]["walk"] = bank
        def observations(selected, x, score):
            return [dict(x=list(x),score=score+i*.001,model_id=selected["id"],maneuver=m,
                category=m,condition=m) for m in ("forward","backward","turn_left","turn_right") for i in range(2)]
        bank["observations"] = observations(model,[0.]*len(DEFAULT_RADII),.1)
        await self.service._analyze("robot")
        first = bank["candidate"]
        bank["observations"] += observations(first,bank["coordinates"],.15)
        await self.service._analyze("robot")
        self.assertEqual(bank["incumbent"]["id"], first["id"])
        self.assertTrue(bank["history"][-1]["promoted"])
        self.assertTrue(any(p.get("persist") and p.get("model", {}).get("id") == first["id"] for _,_,p in self.transport.calls))
        bank["candidate_method"] = "bayesian"  # exercise post-bootstrap plateau
        bank["observations"] += observations(bank["candidate"],bank["coordinates"],.05)
        await self.service._analyze("robot")
        self.assertTrue(bank["converged"])
        self.assertTrue(self.service.settings["robot"]["learning"])  # Run has not been evaluated
        self.assertEqual(r["pending"]["walk"], (first, True))
        r["banks"]["run"] = {**copy.deepcopy(bank), "converged": True}
        await self.service._analyze("robot")
        self.assertFalse(self.service.settings["robot"]["learning"])
        persisted = json.loads((r["root"]/"training.json").read_text())
        self.assertEqual(persisted["walk"]["incumbent"]["id"],first["id"])
        await self.service.restore("robot","walk",model["id"])
        # The initial model remains available through the saved search history.
        self.assertEqual(r["banks"]["walk"]["incumbent"]["id"],model["id"])
        self.assertEqual(r["banks"]["walk"]["candidate"]["id"],model["id"])
        self.assertEqual(r["banks"]["walk"]["centre"]["id"],model["id"])


class CandidateProjectionTests(unittest.TestCase):
    def test_reduces_only_proposed_delta_and_uses_run_command(self):
        from types import SimpleNamespace
        base = policy_seed(policy_recording(), gait=True)["model"]
        joints = [dict(id=i,channel=i,invert=False,home_us=1650,home_cd=0,us_per_degree=10) for i in range(12)]
        calls = []
        def preview(argv, **kwargs):
            calls.append(json.loads(argv[-1]))
            # Simulated solver accepts no more than half this proposed sweep.
            weights = list(map(float, kwargs["input"].splitlines()[12].split()))
            return SimpleNamespace(returncode=0 if weights[205]-base["gait_profile"][1] <= 4. else 4, stderr="")
        with patch("subprocess.run", side_effect=preview):
            model,x,fit = project_candidate(base,[1.]*len(DEFAULT_RADII),DEFAULT_RADII,
                joints,"run",[json.dumps([[1,0,0,1],2])])
        self.assertEqual(fit["scale"],.5)
        self.assertEqual(x,[.5]*len(DEFAULT_RADII))
        self.assertAlmostEqual(model["gait_profile"][1]-base["gait_profile"][1],4)
        self.assertTrue(all(c["gait"] == "run" for c in calls))
        self.assertEqual(base["gait_profile"],[0.]*33)


class RecordingDepthTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the production camera/recorder handoff with real recording files."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gateway = Gateway()
        self.gateway.instance_id = "recording-depth-test"
        self.gateway.configure_camera_attitude_history = Mock()
        self.gateway.camera_frame_attitude = Mock(return_value={"available":False})
        self.gateway.unsubscribe_frames = self.gateway.frames.remove
        self.gateway.clock = time.monotonic
        self.body = {"epoch": 1, "connection_state": "online", "active_walk": None}
        self.gateway.status = lambda: {"robots": {"robot": self.body}}
        async def publish(event):
            for callback in self.gateway.events:
                callback(event)
        self.gateway._publish_event = publish
        self.camera = CameraFramePlugin(self.gateway, None, max_frame_age_s=30)
        self.addAsyncCleanup(self.camera.aclose)
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.fail_depth = False
        loop = asyncio.get_running_loop()
        def process(robot, epoch, counter, received, payload, stamp, config, attitude=None):
            loop.call_soon_threadsafe(self.entered.set)
            if not self.release.wait(10):
                raise AssertionError("Test did not release depth inference")
            if self.fail_depth:
                raise ValueError("Depth fixture failed")
            return {"available": True, "robotId": robot, "epoch": epoch,
                "receivedAtMonotonic": received, "observedAt": stamp,
                "referenceId": "navigation-reference", "position": {"xMetres": 0., "yMetres": 0.}}
        self.depth = Mock(process=Mock(side_effect=process))
        self.camera._depth_motion = self.depth
        self.camera._depth_settings["robot"] = {"mode": "moge-open3d"}
        self.camera._metric_frames["robot"] = (_CameraInput("robot", 1, 1, time.monotonic(), b"fixture"),
            datetime.now(timezone.utc).isoformat())
        self.transport = Transport()
        self.started = asyncio.Event()
        original = self.transport.request
        async def request(robot, endpoint, payload):
            result = await original(robot, endpoint, payload)
            if payload and payload["op"] in {"trace_start", "trace_read"} and self.transport.active:
                result.insert(1, {"kind": "sample", "time_us": 1,
                    "joint_position_cd": [0]*12, "joint_target_cd": [0]*12,
                    "pulse_us": [1500]*12, "imu": {"available": False}})
                self.started.set()
            return result
        self.transport.request = request
        self.service = GaitLearningService(self.gateway, self.transport, self.camera.locomotion_measurement,
            Path(self.temp.name), depth_demand=self.camera.depth_demand)
        self.addAsyncCleanup(self.service.close)
        # Release first even when a baseline assertion fails, so cleanup cannot
        # conceal the failure by hanging behind the deliberately held model.
        self.addCleanup(self.release.set)
        await self.service.start()

    async def test_stationary_logging_does_not_request_depth(self):
        await self.service.configure("robot", {"logging": True})
        await asyncio.wait_for(self.started.wait(), 1)
        await self.service.writes.join()
        self.assertNotIn("gait-learning:robot", self.camera._metric_consumers)
        self.depth.process.assert_not_called()
        recording = self.service._runtime("robot")["recording"]
        self.assertTrue((recording/"trace.jsonl").is_file())
        await self.disable()

    async def test_gait_receipts_release_depth_while_logging_stays_enabled(self):
        owner = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        connection = GatewayConnection(owner, Mock(closed=False, send=AsyncMock()), "robot", 1)
        owner._connections["robot"] = connection
        self.gateway.status = owner.status
        self.release.set()
        await self.service.configure("robot", {"logging": True})
        await asyncio.wait_for(self.started.wait(), 1)
        self.assertFalse(self.camera._metric_consumers)
        with patch("gateway.plugins.DepthMotion", return_value=self.depth):
            for outcome in ("done", "cancelled", "nak", "disconnect"):
                seq = await connection.send_command(
                    {"t": "intent", "name": "walk", "dir": "fwd", "steps": 2},
                    received_at=owner.clock())
                self.started.clear()
                await asyncio.wait_for(self.started.wait(), 1)
                await self.camera._metric_queue.join()
                self.assertIn("gait-learning:robot", self.camera._metric_consumers)
                if outcome == "disconnect":
                    connection.cancel_pending("disconnect")
                    owner._connections.pop("robot")
                else:
                    await connection._handle_control({"t": "ack", "seq": seq})
                    await connection._handle_control({"t": outcome, "seq": seq})
                self.started.clear()
                await asyncio.wait_for(self.started.wait(), 1)
                await asyncio.get_running_loop().run_in_executor(self.camera._metric_executor, lambda: None)
                self.assertNotIn("gait-learning:robot", self.camera._metric_consumers)
                self.assertIsNone(self.camera._depth_motion)
                self.assertTrue(self.service.settings["robot"]["logging"])
                self.assertFalse(self.service.tasks["robot"].done())
        self.assertEqual(self.depth.close.call_count, 4)
        await self.disable()

    async def test_learning_alone_does_not_request_depth_without_a_gait(self):
        await self.service.configure("robot", {"learning": True})
        await asyncio.wait_for(self.started.wait(), 1)
        self.assertNotIn("gait-learning:robot", self.camera._metric_consumers)
        self.depth.process.assert_not_called()
        await self.service.configure("robot", {"learning": False})
        await asyncio.wait_for(asyncio.shield(self.service.tasks["robot"]), 1)

    async def test_restored_logging_stays_passive_until_a_gait_is_active(self):
        await self.service.configure("robot", {"logging": True})
        await asyncio.wait_for(self.started.wait(), 1)
        await self.service.close()
        self.started.clear()
        self.service = GaitLearningService(self.gateway, self.transport, self.camera.locomotion_measurement,
            Path(self.temp.name), depth_demand=self.camera.depth_demand)
        self.addAsyncCleanup(self.service.close)
        await self.service.start()
        await asyncio.wait_for(self.started.wait(), 1)
        self.assertTrue(self.service.settings["robot"]["logging"])
        self.assertNotIn("gait-learning:robot", self.camera._metric_consumers)
        self.depth.process.assert_not_called()
        await self.disable()

    async def enable(self):
        self.body["active_walk"] = {"t": "intent", "name": "walk", "seq": 1}
        self.started.clear()
        await self.service.configure("robot", {"logging": True})
        await asyncio.wait_for(self.started.wait(), 1)
        await asyncio.wait_for(self.entered.wait(), 1)
        self.assertFalse(self.release.is_set())
        await self.service.writes.join()
        recording = self.service._runtime("robot")["recording"]
        rows = [json.loads(row) for row in (recording/"trace.jsonl").read_text().splitlines()]
        self.assertTrue(any(len(row["records"]) > 2 for row in rows))
        return recording

    async def disable(self):
        task = self.service.tasks["robot"]
        await self.service.configure("robot", {"logging": False})
        await asyncio.wait_for(asyncio.shield(task), 1)
        await self.service.writes.join()
        self.assertNotIn("gait-learning:robot", self.camera._metric_consumers)
        self.assertFalse(self.transport.active)
        self.assertEqual(self.service.status("robot")["state"], "off")
        self.assertTrue(self.service.writes.empty())
        self.assertLessEqual({payload["op"] for _, _, payload in self.transport.calls if payload},
                            {"trace_start", "trace_read", "trace_stop"})

    async def test_cold_depth_does_not_block_trace_or_recording_shutdown(self):
        await self.enable()
        await self.disable()
        self.depth.close.assert_not_called()
        self.release.set()
        await self.camera.aclose()
        self.depth.close.assert_called_once()
        self.assertNotIn("robot", self.camera._metric_latest)

    async def test_busy_navigation_keeps_its_reference_through_repeated_recordings(self):
        navigation = asyncio.create_task(self.camera.depth_demand("robot", "navigation", True))
        await asyncio.wait_for(self.entered.wait(), 1)
        recordings = []
        for _ in range(3):
            recordings.append(await self.enable())
            await self.disable()
            self.assertEqual(self.camera._metric_consumers, {"navigation": "robot"})
            self.assertFalse(navigation.done())
            self.depth.reset.assert_not_called()
            self.depth.close.assert_not_called()
        self.assertEqual(len(set(recordings)), 3)
        self.release.set()
        result = await asyncio.wait_for(navigation, 1)
        self.assertTrue(result["measurement"]["available"])
        self.assertEqual(result["measurement"]["referenceId"], "navigation-reference")
        self.depth.reset.assert_not_called()
        self.depth.close.assert_not_called()
        await self.camera.depth_demand("robot", "navigation", False)
        self.depth.close.assert_called_once()

    async def test_depth_failure_remains_visible_and_trace_continues(self):
        self.fail_depth = True
        recording = await self.enable()
        self.release.set()
        with self.assertLogs("gateway.plugins", level="WARNING"):
            await self.camera._metric_queue.join()
        measurement = self.camera.locomotion_measurement("robot")
        self.assertFalse(measurement["available"])
        self.assertEqual(measurement["reason"], "Depth fixture failed")
        self.assertTrue(self.transport.active)
        self.assertFalse(self.service.tasks["robot"].done())
        await self.disable()
        self.assertTrue((recording/"trace.jsonl").is_file())

    async def test_service_close_cancels_recording_without_waiting_for_depth(self):
        await self.enable()
        await asyncio.wait_for(self.service.close(), 1)
        self.assertTrue(self.service.tasks["robot"].done())
        self.assertNotIn("gait-learning:robot", self.camera._metric_consumers)
        self.assertFalse(self.transport.active)
        self.assertTrue(self.service.writes.empty())
        self.depth.close.assert_not_called()
        self.release.set()
        await self.camera.aclose()
        self.depth.close.assert_called_once()

    async def test_enable_while_previous_trace_stops_starts_the_next_recording(self):
        first = await self.enable()
        stop_entered, finish_stop = asyncio.Event(), asyncio.Event()
        original = self.transport.request
        async def request(robot, endpoint, payload):
            if payload and payload["op"] == "trace_stop":
                stop_entered.set()
                await finish_stop.wait()
            return await original(robot, endpoint, payload)
        self.transport.request = request
        self.addCleanup(finish_stop.set)
        previous = self.service.tasks["robot"]
        await self.service.configure("robot", {"logging": False})
        await asyncio.wait_for(stop_entered.wait(), 1)
        self.started.clear()
        await self.service.configure("robot", {"logging": True})
        finish_stop.set()
        await asyncio.wait_for(asyncio.shield(previous), 1)
        await asyncio.wait_for(self.started.wait(), 1)
        self.assertIsNot(self.service.tasks["robot"], previous)
        self.assertNotEqual(first, self.service._runtime("robot")["recording"])
        self.assertIn("gait-learning:robot", self.camera._metric_consumers)
        await self.service.writes.join()
        cleanup = [json.loads(line)["value"] for line in (first/"events.jsonl").read_text().splitlines()]
        self.assertTrue(next(event for event in cleanup if event["t"] == "recording_cleanup")["trace_drained"])
        await self.disable()  # Also asserts inactive trace and released depth demand.
        await self.service.close()
        await assert_writer_finished(self, self.service)
        self.assertIsNone(self.service.status("robot")["error"])


if __name__ == "__main__":
    unittest.main()
