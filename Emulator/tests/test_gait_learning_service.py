import asyncio
import copy
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock, AsyncMock

from gateway.gait_learning import policy_seed
from gateway.gait_optimizer import candidate, context, DEFAULT_RADII, DEFAULT_WEIGHTS, measured_score, compare, project_candidate
from gateway.gait_learning_service import GaitLearningService, TraceSessionChanged, RobotLearningTransport
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


class ObjectiveTests(unittest.TestCase):
    def test_sparse_feedback_owns_and_closes_each_connection(self):
        async def check():
            gateway=Mock();gateway.maintenance_address=AsyncMock(return_value='robot')
            tokens=Mock();tokens.snapshot.return_value={'body':'token'}
            transport=RobotLearningTransport(gateway,tokens,persistent=False)
            with patch('gateway.gait_learning_service.http.client.HTTPConnection') as factory:
                connection=factory.return_value
                connection.getresponse.return_value.status=200
                connection.getresponse.return_value.read.return_value=b'{"joints":[]}'
                await transport.request('body','servo-feedback',None)
                await transport.request('body','servo-feedback',None)
                self.assertEqual(factory.call_count,2)
                self.assertEqual(connection.close.call_count,2)
                self.assertFalse(transport.sessions)
        asyncio.run(check())

    def test_transport_reuses_socket_and_does_not_retry_failed_requests(self):
        transport = RobotLearningTransport(None,None)
        session = dict(lock=threading.Lock(),address=None,connection=None)
        with patch("gateway.gait_learning_service.http.client.HTTPConnection") as factory:
            connection=factory.return_value
            response=connection.getresponse.return_value
            response.status=200
            response.read.return_value=b'{"next":1}\n'
            for _ in range(3):
                transport._persistent_request(session,"robot","token","servo-feedback",{"op":"trace_read"})
            self.assertEqual(factory.call_count,1)
            self.assertEqual(connection.request.call_count,3)
            connection.close.assert_not_called()
            connection.request.side_effect=OSError("disconnected")
            with self.assertRaisesRegex(OSError,"disconnected"):
                transport._persistent_request(session,"robot","token","gait-learning",{"op":"install"})
            self.assertEqual(connection.request.call_count,4)
            connection.close.assert_called_once()
            self.assertIsNone(session["connection"])

    def test_trace_session_conflict_is_distinct_from_other_http_errors(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 409
        with patch("gateway.gait_learning_service.http.client.HTTPConnection", return_value=connection):
            response.read.return_value = b'{"error":"Trace session changed"}'
            with self.assertRaises(TraceSessionChanged):
                RobotLearningTransport._request("robot", "token", "servo-feedback",
                    {"op": "trace_read", "boot_id": 1, "session": 1, "after": 100})
            response.read.return_value = b'{"error":"Trace cursor is ahead of recording"}'
            with self.assertRaises(ValueError) as error:
                RobotLearningTransport._request("robot", "token", "servo-feedback", {"op": "trace_read", "after": 100})
            self.assertNotIsInstance(error.exception, TraceSessionChanged)
        self.assertEqual(connection.close.call_count, 2)

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
        self.commands, self.events, self.frames = [], [], []
    def subscribe_commands(self, fn): self.commands.append(fn)
    def subscribe_events(self, fn): self.events.append(fn)
    def subscribe_frames(self, fn): self.frames.append(fn)
    async def body_calibration(self, op, values, robot_id=None):
        assert op == "get"
        return {"robot_id": robot_id, "joints": []}


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


if __name__ == "__main__":
    unittest.main()
