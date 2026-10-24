"""Persistent, optional host gait recorder and learning lifecycle.

The gateway owns this service, not the browser. It observes ordinary motion;
it never queues walking, Stop, Home, servo angles, or a robot reset. Blocking
network, storage and optimizer work runs outside the gateway event loop.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import time
import threading
from uuid import uuid4
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE

from .gait_learning import policy_seed
from .gait_optimizer import (DEFAULT_RADII, DEFAULT_WEIGHTS, PRIORITIES, candidate,
                             compare, context, measured_score, propose_worker, project_candidate)
from .gait_training import profile_signature


def default_directory():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home()/".local/state"))/"ainekio"/"gait-learning"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name+"."+uuid4().hex+".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def optimizer_observations(bank, required):
    grouped = {}
    for observation in bank["observations"]:
        key = tuple(observation["x"])
        grouped.setdefault(key, {}).setdefault(observation["maneuver"], []).append(observation["score"])
    return [{"x": list(key), "score": sum(sum(values[c])/len(values[c]) for c in required)/len(required)}
            for key, values in grouped.items() if all(c in values for c in required)]


class TraceSessionChanged(ValueError):
    """The device restarted or another trace_start replaced this recording."""


class RobotLearningTransport:
    """Use the gateway's authenticated LAN robot and token, never user URLs."""
    def __init__(self, gateway, tokens, *, persistent=True):
        self.gateway, self.tokens = gateway, tokens
        self.persistent = persistent
        self.sessions = {}

    async def request(self, robot, endpoint, payload):
        address = await self.gateway.maintenance_address(robot)
        token = self.tokens.snapshot()[robot]
        if not self.persistent:
            # Inference may outlast the robot's HTTP idle connection. Sparse
            # observations own a fresh socket; streamed traces retain reuse.
            return await asyncio.to_thread(self._request, address, token, endpoint, payload)
        session = self.sessions.setdefault(robot, {"lock": threading.Lock(), "address": None, "connection": None})
        return await asyncio.to_thread(self._persistent_request, session, address, token, endpoint, payload)

    def _persistent_request(self, session, address, token, endpoint, payload):
        # HTTP/1.1 request/response pairs on one socket must be serialized.
        # This lock belongs only to this robot's measurement/model HTTP stream;
        # semantic commands, camera and other robots use their existing owners.
        with session["lock"]:
            if session["address"] != address or session["connection"] is None:
                if session["connection"] is not None:
                    session["connection"].close()
                session.update(address=address, connection=http.client.HTTPConnection(address, 80, timeout=30))
            try:
                return self._request(address, token, endpoint, payload, session["connection"])
            except Exception:
                session["connection"].close()
                session["connection"] = None
                raise  # Existing caller reports failure; no request is replayed here.

    async def close(self):
        def close_sessions():
            for session in self.sessions.values():
                with session["lock"]:
                    if session["connection"] is not None:
                        session["connection"].close()
                        session["connection"] = None
        await asyncio.to_thread(close_sessions)

    @staticmethod
    def _request(address, token, endpoint, payload, connection=None):
        owned = connection is None
        if owned:
            connection = http.client.HTTPConnection(address, 80, timeout=30)
        try:
            connection.request("POST" if payload is not None else "GET", "/api/"+endpoint,
                               json.dumps(payload) if payload is not None else None,
                               {"Authorization": "Bearer "+token, "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read().decode()
            if response.status != 200:
                if response.status == 409 and (payload or {}).get("op", "").startswith("trace_"):
                    if json.loads(data).get("error") == "Trace session changed":
                        raise TraceSessionChanged("Device trace session changed")
                raise ValueError(f"Robot {endpoint}: HTTP {response.status}: {data[:300]}")
            if (payload or {}).get("op", "").startswith("trace_"):
                return [json.loads(line) for line in data.splitlines() if line.strip()]
            return json.loads(data)
        finally:
            if owned:
                connection.close()


class GaitLearningService:
    def __init__(self, gateway, transport, measurement, directory=None, optimizer=propose_worker,
                 projector=project_candidate, depth_demand=None):
        self.gateway, self.transport, self.measurement = gateway, transport, measurement
        self.depth_demand = depth_demand
        self.directory = Path(directory) if directory else default_directory()
        self.settings_path = self.directory/"settings.json"
        self.settings = json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {}
        self.optimizer = optimizer
        self.projector = projector
        self.tasks, self.workers, self.runtime = {}, {}, {}
        self.writes = asyncio.Queue()
        self.writer = None
        self.closed = False
        gateway.subscribe_commands(self.command)
        gateway.subscribe_events(self.event)
        gateway.subscribe_frames(self.frame)

    async def start(self):
        self.writer = asyncio.create_task(self._write_loop(), name="gait-storage")
        for robot, settings in self.settings.items():
            r = self._runtime(robot)
            path = r["root"]/"training.json"
            if path.exists():
                r["banks"] = await asyncio.to_thread(lambda p=path: json.loads(p.read_text()))
                if settings.get("learning"):
                    for gait, bank in r["banks"].items():
                        r["pending"][gait] = (bank["incumbent"] if bank.get("converged") else bank["candidate"], False)
            if settings.get("logging") or settings.get("learning"):
                self._start_robot(robot)

    def _runtime(self, robot):
        if robot not in self.runtime:
            key = hashlib.sha256(robot.encode()).hexdigest()[:20]
            root = self.directory/key
            self.runtime[robot] = dict(root=root, recording=None, state="off", error=None,
                analysis_error=None, storage_error=None, analysis_note=None,
                latest_imu=None, clock_anchor=None,
                records=0, lost=0, windows=0, coverage={p: 0 for p in PRIORITIES},
                poses=[], window=None, banks={}, after=0, boot=None, session=None,
                owned=False, pending={}, measurements_reason=None)
        return self.runtime[robot]

    def _start_robot(self, robot):
        if robot not in self.tasks or self.tasks[robot].done():
            self.tasks[robot] = asyncio.create_task(self._record(robot), name="gait-record-"+robot)

    async def configure(self, robot, changes):
        allowed = {"logging", "learning", "window_cycles", "radii", "weights", "plateau_rounds", "minimum_improvement"}
        if set(changes)-allowed:
            raise ValueError("Unknown gait-learning setting")
        settings = {**self.settings.get(robot, {
            "logging": False, "learning": False, "window_cycles": 4,
            "radii": DEFAULT_RADII.copy(), "weights": DEFAULT_WEIGHTS.copy(),
            "plateau_rounds": 5, "minimum_improvement": .02}), **changes}
        for k in ("logging", "learning"):
            if type(settings[k]) is not bool:
                raise ValueError(k+" must be a boolean")
        for k in ("window_cycles", "plateau_rounds"):
            if type(settings[k]) is not int or settings[k] < 1:
                raise ValueError(k+" must be a positive integer")
        if not math.isfinite(settings["minimum_improvement"]) or settings["minimum_improvement"] < 0:
            raise ValueError("minimum_improvement must be nonnegative")
        for key, defaults in (("radii", DEFAULT_RADII), ("weights", DEFAULT_WEIGHTS)):
            if set(settings[key]) != set(defaults) or any(not math.isfinite(v) for v in settings[key].values()):
                raise ValueError("Invalid "+key)
        if any(v < 0 for v in settings["radii"].values()):
            raise ValueError("Exploration radii must be nonnegative")
        if settings["learning"] and not any(settings["radii"].values()):
            raise ValueError("Learning needs at least one nonzero exploration radius")
        old = self.settings.get(robot, {})
        self.settings[robot] = settings
        await asyncio.to_thread(atomic_json, self.settings_path, copy.deepcopy(self.settings))
        r = self._runtime(robot)
        if settings["learning"] and (
                settings["radii"] != old.get("radii", settings["radii"]) or
                settings["weights"] != old.get("weights", settings["weights"])):
            for gait, bank in r["banks"].items():
                self._enqueue(r["root"]/"previous-contexts.jsonl", {
                    "gait": gait, "bank": copy.deepcopy(bank), "recorded_at": time.time(),
                    "reason": "Learning settings changed"})
                bank.update(converged=False, plateau=0, centre=bank["incumbent"],
                            candidate=bank["incumbent"], coordinates=[0.]*len(DEFAULT_RADII), observations=[])
                r["pending"][gait] = (bank["incumbent"], False)
        elif settings["learning"] and not old.get("learning"):
            for gait, bank in r["banks"].items():
                bank.update(converged=False, plateau=0)
                r["pending"][gait] = (bank["incumbent"], False)
        if old.get("learning") and not settings["learning"]:
            for gait, bank in r["banks"].items():
                bank["candidate"] = bank["incumbent"]
                bank["coordinates"] = [0.]*len(DEFAULT_RADII)
                r["pending"][gait] = (bank["incumbent"], True)
        if r["banks"]:
            await asyncio.to_thread(atomic_json, r["root"]/"training.json", copy.deepcopy(r["banks"]))
        if settings["logging"] or settings["learning"] or r["pending"]:
            self._start_robot(robot)
        return self.status(robot)

    def status(self, robot):
        r = self._runtime(robot)
        return dict(settings=copy.deepcopy(self.settings.get(robot, {"logging": False, "learning": False})),
            state=r["state"], error="; ".join(str(v) for v in (r["error"], r["analysis_error"], r["storage_error"]) if v) or None,
            records=r["records"], lost_records=r["lost"],
            windows=r["windows"], coverage=r["coverage"].copy(), directory=str(r["root"]),
            recording=str(r["recording"]) if r["recording"] else None,
            measurement_reason=r["measurements_reason"],
            analysis_note=r["analysis_note"],
            analysis_running=robot in self.workers and not self.workers[robot].done(),
            pending_gaits=list(r["pending"]),
            banks={g: {"incumbent": b["incumbent"]["id"], "candidate": b.get("candidate", {}).get("id"),
                "proposal": b.get("proposal", {}).get("id"),
                "generation": b["generation"], "plateau_rounds": b["plateau"],
                "converged": b.get("converged", False), "fitting": b.get("last_fitting"),
                "history": ([{"model": {"id": b["initial"]["id"]}, "promoted": True, "source": "initial"}] if b.get("initial") else [])+
                    [{**{k:v for k,v in h.items() if k != "model"}, "model": {"id": h["model"]["id"]}} for h in b["history"]],
                "observations": len(b["observations"])} for g, b in r["banks"].items()})

    def _enqueue(self, path, value, binary=False):
        self.writes.put_nowait((path, value, binary))

    async def history(self, robot):
        """Read-only history; no robot requests, analysis or policy installation."""
        r = self._runtime(robot)
        current = copy.deepcopy(r["banks"])
        def read():
            contexts = []
            path = r["root"]/"previous-contexts.jsonl"
            if path.exists():
                with path.open() as stream:
                    for line in stream:
                        if line.strip():
                            entry = json.loads(line)
                            contexts.append(dict(gait=entry["gait"], current=False, bank=entry["bank"],
                                reason=entry.get("reason"), recorded_at=entry.get("recorded_at")))
            banks = current
            saved = r["root"]/"training.json"
            if not banks and saved.exists():
                banks = json.loads(saved.read_text())
            contexts.extend(dict(gait=gait, current=True, bank=bank) for gait, bank in banks.items())
            return dict(robot_id=robot, generated_at=time.time(), contexts=contexts)
        return await asyncio.to_thread(read)

    async def _write_loop(self):
        while True:
            item = await self.writes.get()
            try:
                if item is None:
                    return
                await asyncio.to_thread(self._write, *item)
            except (OSError, ValueError, TypeError) as error:
                for r in self.runtime.values():
                    r["storage_error"] = "Recording storage: "+str(error)
            finally:
                self.writes.task_done()

    @staticmethod
    def _write(path, value, binary):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("wb" if binary else "a") as stream:
            os.chmod(path, 0o600)
            stream.write(value if binary else json.dumps(value, allow_nan=False)+"\n")

    def _observe(self, robot, kind, value):
        if self.closed:
            return
        r = self.runtime.get(robot)
        settings = self.settings.get(robot, {})
        if r and r["recording"] and (settings.get("logging") or settings.get("learning")):
            self._enqueue(r["recording"]/(kind+".jsonl"),
                          {"host_monotonic_s": time.monotonic(), "value": value})

    def command(self, command):
        robot = command.get("robot_id")
        if robot in self.runtime:
            # Do not persist arbitrary settings payloads or credentials.
            keep = {k: command[k] for k in ("t", "robot_id", "epoch", "seq", "name", "dir",
                "gait", "speed", "stride", "rate", "forward", "turn", "lateral", "steps", "update") if k in command}
            self._observe(robot, "commands", keep)

    def event(self, event):
        r = self.runtime.get(event.get("robot_id"))
        if r is not None:
            if event.get("t") == "connection" and event.get("status") == "connected":
                r["clock_anchor"] = None
            if event.get("t") == "status" and isinstance(event.get("clock_ms"), (int, float)):
                r["clock_anchor"] = {"device_s": event["clock_ms"]/1000.,
                    "received_monotonic_s": time.monotonic(), "epoch": event.get("epoch")}
            if event.get("t") == "locomotion_measurement" and r["recording"]:
                # Archive the measured frame once, at its original timestamp.
                # Dashboard freshness is about using a frame *now*; a later
                # expired copy must not invalidate its historical observation.
                pose = {k: v for k, v in event["measurement"].items() if k != "depthPreview"}
                self._observe(event["robot_id"], "poses", pose)
                r["poses"].append(pose)
                r["poses"] = r["poses"][-2048:]
        if event.get("t") in ("imu", "ack", "done", "error", "connection", "locomotion_measurement"):
            self._observe(event.get("robot_id"), "events", event)

    def frame(self, frame):
        if self.closed:
            return
        robot = frame.get("robot_id")
        r = self.runtime.get(robot)
        if not r or not r["recording"] or not (self.settings.get(robot, {}).get("logging") or self.settings.get(robot, {}).get("learning")):
            return
        if frame.get("frame_type") != CAMERA_JPEG_FRAME_TYPE:
            return
        payload = frame.get("payload")
        if not isinstance(payload, bytes):
            return
        name = f'{frame.get("epoch", 0)}-{frame.get("counter", 0)}-{time.monotonic_ns()}.jpg'
        self._enqueue(r["recording"]/"camera"/name, payload, True)
        self._observe(robot, "camera", {k: v for k, v in frame.items() if k != "payload"} | {"file": "camera/"+name})

    async def _record(self, robot):
        r = self._runtime(robot)
        r.update(after=0, boot=None, session=None, owned=False, window=None, poses=[], latest_imu=None)
        r["recording"] = r["root"]/("recordings/"+time.strftime("%Y%m%d-%H%M%S")+"-"+uuid4().hex[:8])
        state_path = r["root"]/"training.json"
        if not r["banks"] and state_path.exists():
            r["banks"] = await asyncio.to_thread(lambda: json.loads(state_path.read_text()))
            if self.settings.get(robot, {}).get("learning"):
                for gait, bank in r["banks"].items():
                    r["pending"][gait] = (bank["incumbent"] if bank.get("converged") else bank["candidate"], False)
        try:
            if self.depth_demand is not None:
                await self.depth_demand(robot, f"gait-learning:{robot}", True)
            while not self.closed:
                settings = self.settings.get(robot, {})
                if not (settings.get("logging") or settings.get("learning")) and not r["pending"]:
                    break
                try:
                    await self._apply_pending(robot)
                    if r["session"] is None:
                        metadata = {
                            "calibration": await self.gateway.body_calibration("get", {}, robot_id=robot),
                            "feedback": await self.transport.request(robot, "servo-feedback", None),
                            "learning": await self.transport.request(robot, "gait-learning", None),
                            "firmware": await self.transport.request(robot, "firmware", None),
                        }
                        self._enqueue(r["recording"]/"metadata.jsonl", metadata)
                    started = time.monotonic()
                    payload = {"op": "trace_read", "after": r["after"]}
                    if r["session"]:
                        payload.update(boot_id=r["boot"], session=r["session"])
                    records = await self.transport.request(robot, "servo-feedback", payload)
                    ended = time.monotonic()
                    header, footer = records[0], records[-1]
                    if header.get("schema") != "gait_trace_v1" or "next" not in footer:
                        raise ValueError("Incomplete trace response")
                    identity = (header["boot_id"], header["session"])
                    if identity != (r["boot"], r["session"]):
                        r.update(boot=identity[0], session=identity[1], after=0, window=None, latest_imu=None, owned=False)
                    if not header["active"]:
                        if not (settings.get("logging") or settings.get("learning")):
                            break
                        records = await self.transport.request(robot, "servo-feedback", {"op": "trace_start", "after": 0})
                        r["owned"] = True
                        r.update(after=0, boot=records[0]["boot_id"], session=records[0]["session"], window=None)
                        header, footer = records[0], records[-1]
                    batch = dict(request_monotonic_s=started, received_monotonic_s=ended, records=records,
                                 clock_anchor=copy.deepcopy(r["clock_anchor"]))
                    self._enqueue(r["recording"]/"trace.jsonl", batch)
                    r["records"] += len(records)-2
                    r["lost"] += footer.get("lost", 0)
                    r["after"] = footer["next"]
                    pose = self.measurement(robot)
                    r["measurements_reason"] = pose.get("reason") if not pose.get("available") else None
                    await self._consume(robot, batch)
                    r["state"] = "learning" if settings.get("learning") else "logging"
                    r["error"] = None
                    if not footer.get("more"):
                        await asyncio.sleep(.1)  # sensor drain cadence, never a motion wait
                except TraceSessionChanged as error:
                    self._observe(robot, "events", {"t": "trace_session_changed",
                        "boot_id": r["boot"], "session": r["session"], "reason": str(error)})
                    # A cursor belongs to one device boot/trace session. Reacquire
                    # metadata and the new stream; never join training windows
                    # across that boundary or stop a session we no longer own.
                    r.update(after=0, boot=None, session=None, owned=False,
                             window=None, latest_imu=None, poses=[])
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                    # The device cursor, not an HTTP connection, owns sample
                    # continuity. The next footer reports any actual loss;
                    # reconnecting to drain retained records is not a gap.
                    r["error"], r["state"] = str(error), "recording_unavailable"
                    await asyncio.sleep(1)
        finally:
            if r["owned"]:
                try:
                    records = await self.transport.request(robot, "servo-feedback", {"op": "trace_stop", "after": r["after"],
                        "boot_id": r["boot"], "session": r["session"]})
                    while True:
                        self._enqueue(r["recording"]/"trace.jsonl", {"records": records})
                        if not records[-1].get("more"):
                            break
                        records = await self.transport.request(robot, "servo-feedback", {"op": "trace_read", "after": records[-1]["next"],
                            "boot_id": r["boot"], "session": r["session"]})
                except (OSError, ValueError, RuntimeError):
                    pass
            r.update(state="off", owned=False, window=None)
            if self.depth_demand is not None:
                await self.depth_demand(robot, f"gait-learning:{robot}", False)

    async def _consume(self, robot, batch):
        r = self._runtime(robot)
        header, footer = batch["records"][0], batch["records"][-1]
        if footer.get("lost"):
            r["window"], r["latest_imu"] = None, None
            return
        events = batch["records"][1:-1]
        latest = max((e.get("time_us", 0) for e in events), default=0)
        if not latest:
            return
        # Receipt alignment is explicitly approximate until exposure/device
        # clock synchronization is provided by the camera owner.
        offset = (batch["request_monotonic_s"]+batch["received_monotonic_s"])/2-latest/1e6
        anchor = batch.get("clock_anchor")
        if anchor is not None:
            # HTTP batches can contain seconds of queued history. Align the
            # device clock using the independent live status receipt, not the
            # newest old record in this batch. Receipt latency remains unknown.
            offset = anchor["received_monotonic_s"]-anchor["device_s"]
        for e in events:
            if e.get("kind") == "sample":
                imu = e.get("imu", {})
                r["latest_imu"] = imu.get("acceleration_m_s2") if (
                    imu.get("available") and imu.get("fresh") and imu.get("calibration_applied") and
                    not imu.get("startup") and not imu.get("recovering")) else None
            p = e.get("policy", {})
            if e.get("kind") != "tracking":
                continue
            gait = p.get("gait", "walk")
            category = context(p.get("command", [0, 0, 0, 0]), gait)
            if not p.get("eligible") or category is None or p["phase"] < 2:
                r["window"] = None
                continue
            key = (header["boot_id"], header["session"], e["command_sequence"],
                   p["gait_signature"], p["profile_signature"], category, tuple(round(v, 6) for v in p["command"]),
                   p.get("model_id"), p.get("model_amount"), p.get("model_active"), p.get("requested_rate"))
            # Availability is a per-sample outcome, not a different installed
            # policy. Transient feedback loss must not restart every window.
            identity = key[:9]+key[10:]
            previous_key = r["window"]["key"] if r["window"] else None
            if previous_key is None or previous_key[:9]+previous_key[10:] != identity:
                r["window"] = dict(key=key, phase=p["phase"], samples=[], batches=[], gait=gait, category=category,
                                   observed=0, unavailable=0, model_active_observations=0)
            w = r["window"]
            w["observed"] += 1
            if p.get("model_active"):
                w["model_active_observations"] += 1
                w["key"] = w["key"][:9]+(True,)+w["key"][10:]
            if not p.get("usable") or e.get("valid_mask") != 15:
                # A missed observation is not a new command or gait cycle.
                # Keep the window; missing values never become zero error.
                w["unavailable"] += 1
                continue
            features = p["features"]
            errors = [a+c-b for leg in e["legs"] for a, b, c in
                      zip(leg["target_mm"], leg["measured_mm"], leg["correction_mm"])]
            w["samples"].append(dict(host_monotonic_s=e["time_us"]/1e6+offset, command=p["command"],
                                      tilt=[v*.1 for v in features[3:5]], angular=features[5:8], error=errors,
                                      reference_twist=p.get("reference_twist_m_s_rad_s"),
                                      acceleration_deviation=[math.sqrt(sum(v*v for v in r["latest_imu"]))-9.80665] if
                                      r["latest_imu"] and all(isinstance(v, (float, int)) and math.isfinite(v) for v in r["latest_imu"]) else []))
            w["batches"].append({"records": [header, e, {"next": e["sequence"], "lost": 0}]})
            if p["phase"]-w["phase"] >= self.settings[robot]["window_cycles"]:
                r["window"] = None
                r["windows"] += 1
                r["coverage"][category] += 1
                result = {"category": category, "gait": gait, "key": w["key"],
                          "alignment": "live-status receipt" if anchor is not None else "trace-receipt approximate",
                          "exposure_synchronized": False,
                          "tracking_observations": w["observed"],
                          "unavailable_tracking_observations": w["unavailable"],
                          "model_active_observations": w["model_active_observations"],
                          "network_round_trip_s": batch["received_monotonic_s"]-batch["request_monotonic_s"]}
                try:
                    result.update(measured_score(w["samples"], r["poses"], self.settings[robot]["weights"]))
                except ValueError as error:
                    result["unscored_reason"] = str(error)
                self._enqueue(r["recording"]/"windows.jsonl", result)
                if "score" in result:
                    await self._observation(robot, w, result)

    async def _observation(self, robot, window, result):
        r = self._runtime(robot)
        gait = window["gait"]
        if gait in r["banks"] and (
                r["banks"][gait]["incumbent"]["signature"] != result["key"][3] or
                r["banks"][gait].get("camera_context") != result.get("camera_context")):
            self._enqueue(r["root"]/"previous-contexts.jsonl", {"gait": gait, "bank": copy.deepcopy(r["banks"][gait])})
            del r["banks"][gait]
        if gait not in r["banks"]:
            seed = policy_seed(window["batches"], gait=True)["model"]
            # A new trace seeds the actual calibration context. Existing model
            # export is used if present, so learning never silently zeroes it.
            status = await self.transport.request(robot, "gait-learning", {"op": "read", "gait": gait})
            if status.get("model_schema") == "gait_learning_v4" and status.get("model_id") and status.get("enabled") and status.get("model_signature") == seed["signature"]:
                for field in ("coefficients", "feedback_coefficients", "command_coefficients", "gait_profile", "pulse_min_us", "pulse_max_us"):
                    seed[field] = status[field]
                # Preserve the effective residual gain at the seed. Profile
                # geometry is independent of the correction-amount setting.
                for field in ("coefficients", "feedback_coefficients", "command_coefficients"):
                    seed[field] = [x*status["amount"] for x in seed[field]]
                from .gait_learning import model_identity
                seed["id"] = model_identity(seed)
            r["banks"][gait] = dict(initial=seed, incumbent=seed, centre=seed, generation=0, plateau=0, history=[],
                                   observations=[], candidate=seed, coordinates=[0.]*len(DEFAULT_RADII),
                                   camera_context=result.get("camera_context"),
                                   seed_identity=list(result["key"][7:10]))
        bank = r["banks"][gait]
        selected = bank["candidate"]
        is_seed = selected["id"] == bank["centre"]["id"] and bank["generation"] == 0
        identity_matches = (result["key"][7] == selected["id"] and result["key"][8] == 1 and result["key"][9]) or (
            is_seed and list(result["key"][7:10]) == bank.get("seed_identity"))
        if result["key"][3] != selected["signature"] or result["key"][4] != profile_signature(selected["gait_profile"]) or (
                not identity_matches):
            r["measurements_reason"] = "Selected gait profile differs from learning candidate"
            return
        bank["observations"].append({"recorded_at": time.time(), "generation": bank["generation"],
            "x": bank["coordinates"], "score": result["score"],
            "category": result["category"], "model_id": selected["id"], "recording": str(r["recording"]),
            "condition": json.dumps([result["key"][6], result["key"][10]]),
            "maneuver": ("turn_left" if result["key"][6][1] > 0 else "turn_right") if result["category"] == "turning" else result["category"],
            "metrics": result["metrics"]})
        await asyncio.to_thread(atomic_json, r["root"]/"training.json", copy.deepcopy(r["banks"]))
        if self.settings[robot]["learning"]:
            self.analyze(robot, manual=False)

    def analyze(self, robot, *, manual=True):
        if robot not in self.workers or self.workers[robot].done():
            self.workers[robot] = asyncio.create_task(self._analyze(robot, manual=manual), name="gait-analysis-"+robot)
        return {"queued": True}

    async def _analyze(self, robot, *, manual=False):
        r = self._runtime(robot)
        r["analysis_error"] = None
        r["analysis_note"] = None
        try:
            if manual and not self.settings.get(robot, {}).get("learning"):
                if not r["banks"]:
                    r["analysis_note"] = "No scored motion windows. Enable logging; metric motion and calibrated feedback are needed for scoring."
                for gait, bank in list(r["banks"].items()):
                    required = ["run"] if gait == "run" else ["forward", "backward", "turn_left", "turn_right"]
                    rows = optimizer_observations(bank, required)
                    if not rows:
                        r["analysis_note"] = "Collecting forward, backward and both turning directions for analysis."
                        continue
                    x = await asyncio.to_thread(self.optimizer, rows, seed=bank["generation"])
                    bank["proposal"] = candidate(bank["centre"], x, self.settings[robot]["radii"])
                    r["analysis_note"] = "Analysis complete. Proposal saved on this host; learning is off and no model was installed."
                await asyncio.to_thread(atomic_json, r["root"]/"training.json", copy.deepcopy(r["banks"]))
                return
            for gait, bank in list(r["banks"].items()):
                bank.setdefault("initial", copy.deepcopy(bank["centre"]))
                if not self.settings.get(robot, {}).get("learning") and not manual:
                    break
                if bank.get("converged"):
                    continue
                required = ["run"] if gait == "run" else ["forward", "backward", "turn_left", "turn_right"]
                selected = bank["candidate"]
                current = {c: [o["score"] for o in bank["observations"] if o["maneuver"] == c and o["model_id"] == selected["id"]] for c in required}
                if any(len(v) < 2 for v in current.values()):
                    r["analysis_note"] = "Collecting repeat observations of "+", ".join(c for c,v in current.items() if len(v)<2)
                    continue
                if selected["id"] != bank["incumbent"]["id"]:
                    conditions = {o["condition"] for o in bank["observations"] if o["model_id"] == selected["id"]}
                    comparisons, reference, covered = {}, {}, set()
                    for condition in conditions:
                        ref = [o["score"] for o in bank["observations"] if o["condition"] == condition and o["model_id"] == bank["incumbent"]["id"]]
                        challenge = [o for o in bank["observations"] if o["condition"] == condition and o["model_id"] == selected["id"]]
                        if len(ref) < 2 or len(challenge) < 2:
                            continue
                        reference[condition] = ref
                        comparisons[condition] = compare(ref, [o["score"] for o in challenge])
                        covered.add(challenge[0]["maneuver"])
                    if not set(required).issubset(covered):
                        r["analysis_note"] = "Collecting matching direction, stride and cadence comparisons"
                        continue
                    # No one-command win is described as improving all walking.
                    minimum = self.settings[robot]["minimum_improvement"]
                    wins = all(v["decision"] == "improved" and v["gain"] >
                               minimum*max(abs(sum(reference[c])/len(reference[c])), 1e-9)
                               for c, v in comparisons.items())
                    bank["history"].append(dict(model=selected, comparisons=comparisons, promoted=wins,
                        recorded_at=time.time(), generation=bank["generation"],
                        reference_model_id=bank["incumbent"]["id"]))
                    if wins:
                        bank["incumbent"] = selected
                        bank["plateau"] = 0
                        await self.transport.request(robot, "gait-learning", {"op": "install", "model": selected, "gait": gait, "persist": True})
                        previous_coordinates = bank["coordinates"]
                        bank["centre"] = selected
                        bank["coordinates"] = [0.]*len(DEFAULT_RADII)
                        # Recenter on the demonstrated improvement, expressing
                        # prior evaluations in the new coordinates rather than
                        # discarding physical evidence or restarting the GP.
                        bank["observations"] = [{**o, "x": [a-b for a,b in zip(o["x"], previous_coordinates)]}
                                                for o in bank["observations"]]
                    else:
                        bank["plateau"] = bank["plateau"]+1 if bank.get("candidate_method") == "bayesian" else 0
                    bank["generation"] += 1
                if bank["plateau"] >= self.settings[robot]["plateau_rounds"]:
                    bank["converged"] = True
                    r["pending"][gait] = (bank["incumbent"], True)
                    continue
                # Equal context weighting; do not let mostly forward operation
                # swamp backward and turning observations.
                observations = optimizer_observations(bank, required)
                bank["candidate_method"] = "bayesian" if len(observations) >= len(DEFAULT_RADII)+1 else "space_filling"
                x = await asyncio.to_thread(self.optimizer, observations, seed=bank["generation"])
                if not self.settings.get(robot, {}).get("learning"):
                    if manual:
                        bank["proposal"] = candidate(bank["centre"], x, self.settings[robot]["radii"])
                    continue
                calibration = await self.gateway.body_calibration("get", {}, robot_id=robot)
                model, x, fitting = await asyncio.to_thread(self.projector, bank["centre"], x,
                    self.settings[robot]["radii"], calibration["joints"], gait,
                    [o["condition"] for o in bank["observations"]])
                if not self.settings.get(robot, {}).get("learning"):
                    continue
                bank["last_fitting"] = fitting
                if model["id"] == bank["centre"]["id"]:
                    r["analysis_note"] = "Proposed change has no feasible delta at the recorded commands; resampling."
                    bank["generation"] += 1
                    continue
                bank["candidate"] = model
                bank["coordinates"] = x
                r["pending"][gait] = (bank["candidate"], False)
            if all(r["banks"].get(g, {}).get("converged") for g in ("walk", "run")):
                await self.configure(robot, {"learning": False})
            await asyncio.to_thread(atomic_json, r["root"]/"training.json", copy.deepcopy(r["banks"]))
        except (ImportError, ValueError, RuntimeError, OSError) as error:
            r["analysis_error"] = "Learning analysis: "+str(error)

    async def _apply_pending(self, robot):
        r = self._runtime(robot)
        for gait, (model, persist) in list(r["pending"].items()):
            await self.transport.request(robot, "gait-learning", {"op": "install", "model": model, "gait": gait, "persist": persist})
            await self.transport.request(robot, "gait-learning", {"op": "configure", "enabled": True, "amount": 1., "gait": gait, "persist": persist})
            if r["pending"].get(gait) == (model, persist):
                del r["pending"][gait]

    async def restore(self, robot, gait, model_id):
        r = self._runtime(robot)
        bank = r["banks"][gait]
        models = [bank["incumbent"], bank["centre"], bank.get("initial", bank["centre"])]+[h["model"] for h in bank["history"]]
        model = next((m for m in models if m["id"] == model_id), None)
        if model is None:
            raise ValueError("Model is not in this robot's saved learning history")
        self._enqueue(r["root"]/"previous-contexts.jsonl", {
            "gait": gait, "bank": copy.deepcopy(bank), "recorded_at": time.time(),
            "reason": "Saved model restored"})
        await self.configure(robot, {"learning": False})
        bank.update(incumbent=model, centre=model, candidate=model,
                    coordinates=[0.]*len(DEFAULT_RADII), observations=[], generation=0, plateau=0)
        r["pending"][gait] = (model, True)
        await asyncio.to_thread(atomic_json, r["root"]/"training.json", copy.deepcopy(r["banks"]))
        self._start_robot(robot)
        return self.status(robot)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for task in self.tasks.values():
            task.cancel()
        for task in self.workers.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        await asyncio.gather(*self.workers.values(), return_exceptions=True)
        close_transport = getattr(self.transport, "close", None)
        if close_transport is not None:
            await close_transport()
        await self.writes.join()
        if self.writer:
            self.writes.put_nowait(None)
            await self.writer
