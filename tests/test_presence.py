from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace
import unittest

from gateway.presence import (
    JOINTS,
    PRESENCE_OBS_SIZE,
    STAND_ANGLES_DEG,
    PresenceActor,
    PresenceController,
    PresenceObservationHistory,
    SympatheticMotionMonitor,
    assemble_presence_features,
    presence_model_footprint,
    validate_presence_settings,
)
from gateway.presence.actor import DEFAULT_ACTIVE_POLICY, _get_shared_manifold


def _quat_from_roll_pitch_deg(roll_deg: float, pitch_deg: float) -> list[float]:
    r = math.radians(roll_deg) * 0.5
    p = math.radians(pitch_deg) * 0.5
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    return [cr * cp, sr * cp, cr * sp, -sr * sp]


class FakePending:
    def __init__(self, command: dict):
        self.command = command
        self.acknowledgement = asyncio.get_running_loop().create_future()
        self.acknowledgement.set_result({"t": "ack"})
        self.future = asyncio.get_running_loop().create_future()


class FakeConnection:
    def __init__(self, seq_alloc=None):
        self.model = "v2-12servo"
        self.mode = "normal"
        self.epoch = 1
        self.neural_walk = None
        self.features = {"walk_nominal_v1", "motion_targets_v1", "face_feedback_v1"}
        self.capabilities = {"display": True, "motion": True}
        self.pending: dict[int, FakePending] = {}
        self.last_calibration = None
        self.last_status = {"imu": {"face_token": ""}, "listening_feedback": False}
        self.audio_input = {"utterance_open": False}
        self.microphone_level = 0.0
        self.websocket = SimpleNamespace(closed=False)
        self.owned_walk_seq: int | None = None
        self.sent_commands: list[dict] = []
        self._seq_alloc = seq_alloc

    def _owns_walk(self, seq: int) -> bool:
        return self.owned_walk_seq == seq

    async def send_command(self, payload: dict, received_at: float | None = None) -> int:
        seq = self._seq_alloc() if callable(self._seq_alloc) else int(payload.get("sample", 0))
        msg = {**payload, "seq": seq}
        self.sent_commands.append(msg)
        return seq


class FakePresenceGateway:
    def __init__(self):
        self.now = 100.0
        self._seq = 0
        self._cmd_subs = []
        self._evt_subs = []
        self._connections = {"p4": FakeConnection(self._next_seq)}
        self.issued: list[dict] = []
        self.tilt_roll_deg = 0.0
        self.tilt_pitch_deg = 0.0
        self.gyro_rad_s = [0.0, 0.0, 0.0]
        self.accel_m_s2 = [0.0, 0.0, 9.80665]
        self.measured_deg = list(STAND_ANGLES_DEG)
        self.commanded_deg = list(STAND_ANGLES_DEG)
        self.stalled_joints = 0
        self.speaking = (False, 0.0)
        self.ensure_normal_calls = 0
        self.body_events = SimpleNamespace(config=lambda _r: {"tip_degrees": 60.0, "tip_clear_degrees": 45.0})

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def ensure_normal_mode(self, *, robot_id: str | None = None, received_at: float | None = None) -> None:
        conn = self._connections[robot_id or "p4"]
        if conn.mode == "calibrate":
            self.ensure_normal_calls += 1
            conn.mode = "normal"

    def clock(self) -> float:
        return self.now

    def subscribe_commands(self, cb):
        self._cmd_subs.append(cb)

    def unsubscribe_commands(self, cb):
        if cb in self._cmd_subs:
            self._cmd_subs.remove(cb)

    def subscribe_events(self, cb):
        self._evt_subs.append(cb)

    def unsubscribe_events(self, cb):
        if cb in self._evt_subs:
            self._evt_subs.remove(cb)

    async def emit_event(self, event: dict):
        for cb in list(self._evt_subs):
            await cb(event)

    async def emit_external_command(self, command: dict):
        for cb in list(self._cmd_subs):
            await cb(command)

    def speech_activity(self, _robot_id: str) -> tuple[bool, float]:
        return self.speaking

    def body_sensor_observation(self, robot_id: str) -> dict:
        joints = {}
        for i, jname in enumerate(JOINTS):
            joints[jname] = {
                "filtered_model_deg": self.measured_deg[i],
                "commanded_model_deg": self.commanded_deg[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        return {
            "imu": {
                "orientation_wxyz": _quat_from_roll_pitch_deg(self.tilt_roll_deg, self.tilt_pitch_deg),
                "angular_rate_rad_s": list(self.gyro_rad_s),
                "acceleration_m_s2": list(self.accel_m_s2),
            },
            "joints": joints,
            "feedback": {"device_us": int(self.now * 1_000_000), "stalled_joints": self.stalled_joints},
        }

    async def queue_intent(self, name: str, params: dict | None = None, *, robot_id: str | None = None) -> int:
        self._seq += 1
        seq = self._seq
        cmd = {"t": "intent", "name": name, "params": params or {}, "robot_id": robot_id, "seq": seq}
        self.issued.append(cmd)
        conn = self._connections[robot_id]
        if name == "walk":
            conn.owned_walk_seq = seq
            conn.pending[seq] = FakePending(cmd)
        for cb in list(self._cmd_subs):
            await cb(cmd)
        return seq

    async def queue_motion_plan(self, frames: list, *, end: str, control: str | None = None, robot_id: str | None = None) -> int:
        self._seq += 1
        seq = self._seq
        cmd = {"t": "motion_plan", "frames": frames, "end": end, "control": control, "robot_id": robot_id, "seq": seq}
        self.issued.append(cmd)
        for cb in list(self._cmd_subs):
            await cb(cmd)
        return seq

    async def estop(self, *, robot_id: str | None = None, detach: bool = False) -> int:
        self._seq += 1
        seq = self._seq
        cmd = {"t": "stop", "detach": detach, "robot_id": robot_id, "seq": seq}
        self.issued.append(cmd)
        conn = self._connections[robot_id]
        conn.owned_walk_seq = None
        conn.pending.clear()
        for cb in list(self._cmd_subs):
            await cb(cmd)
        return seq

    async def wait_terminal(self, seq: int, *, robot_id: str, epoch: int, timeout: float = 1.0) -> dict:
        return {"t": "done", "seq": seq}


class PresenceSystemTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _get_shared_manifold(None)

    def test_footprint_and_gyro_masking_in_onnx_actor(self):
        fp = presence_model_footprint()
        self.assertTrue(fp["p4_internal_sram_fit"])
        self.assertLessEqual(fp["fp32_bytes"] + fp["scratch_bytes"], 262144)
        self.assertTrue(DEFAULT_ACTIVE_POLICY.exists(), "Active System 3 ONNX policy must exist")

        actor = PresenceActor(DEFAULT_ACTIVE_POLICY)
        hist_a = PresenceObservationHistory()
        hist_b = PresenceObservationHistory()

        feat_level = assemble_presence_features(
            measured_deg=STAND_ANGLES_DEG,
            commanded_deg=STAND_ANGLES_DEG,
            velocity_deg_s=[0.0] * 12,
            chatter_deg=[0.0] * 12,
            usable_flags=[True] * 12,
            orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
            angular_rate_rad_s=[0.0, 0.0, 0.0],
            acceleration_m_s2=[0.0, 0.0, 9.80665],
            imu_enabled=False,
        )
        feat_tilted_masked = assemble_presence_features(
            measured_deg=STAND_ANGLES_DEG,
            commanded_deg=STAND_ANGLES_DEG,
            velocity_deg_s=[0.0] * 12,
            chatter_deg=[0.0] * 12,
            usable_flags=[True] * 12,
            orientation_wxyz=_quat_from_roll_pitch_deg(42.0, -35.0),
            angular_rate_rad_s=[3.5, -2.8, 1.9],
            acceleration_m_s2=[6.0, -5.0, 2.0],
            imu_enabled=False,
        )
        self.assertEqual(feat_level, feat_tilted_masked, "Turning off self_right_enabled must stop sending gyro/IMU data to System 3")
        obs_a = hist_a.push_and_project(1.0, feat_level)
        obs_b = hist_b.push_and_project(1.0, feat_tilted_masked)
        self.assertEqual(len(obs_a), PRESENCE_OBS_SIZE)
        self.assertEqual(actor.infer(obs_a), actor.infer(obs_b))

    def test_sympathetic_motion_monitor_distinguishes_grounded_from_picked_up_and_stuck_tip(self):
        # 1. Picked up / dangling: legs execute a 16 mm pitch differential, IMU does NOT tilt sympathetically
        mon_air = SympatheticMotionMonitor()
        for idx, (t, fz) in enumerate([
            (0.00, [-68.0, -68.0, -68.0, -68.0]),
            (0.15, [-64.0, -64.0, -72.0, -72.0]),
            (0.30, [-60.0, -60.0, -76.0, -76.0]),
            (0.45, [-56.0, -56.0, -80.0, -80.0]),
        ]):
            q = list(STAND_ANGLES_DEG)
            q[2] += idx * 3.0
            q[8] -= idx * 3.0
            unsym, score, reason = mon_air.observe_stance_motion(
                now=t,
                measured_deg=q,
                measured_feet_z_mm=fz,
                orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
                angular_rate_rad_s=[0.0, 0.0, 0.0],
                acceleration_m_s2=[0.0, 0.0, 9.80665],
            )
        self.assertTrue(unsym)
        self.assertEqual(reason, "legs_moved_without_ground_reaction")
        self.assertLess(score, 0.16)

        # 2. Grounded: front leg extension (`fl_z, fr_z` more negative) raises nose (`pitch < 0` in IMU wxyz frame)
        mon_ground = SympatheticMotionMonitor()
        for idx, (t, fz, pitch) in enumerate([
            (0.00, [-68.0, -68.0, -68.0, -68.0], 0.0),
            (0.15, [-64.0, -64.0, -72.0, -72.0], -3.5),
            (0.30, [-60.0, -60.0, -76.0, -76.0], -7.0),
            (0.45, [-56.0, -56.0, -80.0, -80.0], -10.5),
        ]):
            q = list(STAND_ANGLES_DEG)
            q[2] += idx * 3.0
            q[8] -= idx * 3.0
            unsym_g, score_g, _ = mon_ground.observe_stance_motion(
                now=t,
                measured_deg=q,
                measured_feet_z_mm=fz,
                orientation_wxyz=_quat_from_roll_pitch_deg(0.0, pitch),
                angular_rate_rad_s=[0.0, -0.25, 0.0],
                acceleration_m_s2=[0.0, 0.0, 9.80665],
            )
        self.assertFalse(unsym_g)
        self.assertGreater(score_g, 0.7)

        # 3. Unrecoverable tip righting check
        mon_tip = SympatheticMotionMonitor()
        mon_tip.start_righting(10.0, 88.0)
        self.assertEqual(mon_tip.evaluate_righting(now=11.0, tilt_deg=86.0, tip_clear_degrees=45.0)[0], "in_progress")
        state, reason = mon_tip.evaluate_righting(now=13.0, tilt_deg=85.0, tip_clear_degrees=45.0)
        self.assertEqual(state, "passive")
        self.assertEqual(reason, "righting_no_sympathetic_progress")

    async def test_controller_self_rights_respects_gyro_switch_enters_passive_and_preempts(self):
        gw = FakePresenceGateway()
        ctrl = PresenceController(gw)
        try:
            # 1. With self_right_enabled=False, tipping does NOT trigger automatic stand
            ctrl.configure("p4", {**validate_presence_settings(None), "self_right_enabled": False})
            gw.tilt_roll_deg = 82.0
            await gw.emit_event({"t": "event", "robot_id": "p4", "name": "body_event", "data": {"kind": "tipped"}})
            await asyncio.sleep(0.08)
            self.assertFalse(any(c.get("name") == "stand" for c in gw.issued))

            # 2. Re-enable self_right_enabled=True -> tipped robot automatically issues `stand`,
            #    and if wedged with no sympathetic upright progress, transitions to calm passive + servo detach!
            ctrl.configure("p4", {**validate_presence_settings(None), "self_right_enabled": True, "passive_mode": "calm_then_release"})
            gw.now = 102.0
            await asyncio.sleep(0.08)
            gw.now = 102.6
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.08)
            self.assertTrue(any(c.get("name") == "stand" for c in gw.issued), "Tipped robot should attempt self-righting stand")
            self.assertEqual(ctrl.robot_status("p4")["mode"], "self_righting")

            # Advance past righting window while tilt stays stuck at 82 deg -> enters passive calm + detach!
            gw.now = 106.0
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.08)
            st_passive = ctrl.robot_status("p4")
            self.assertEqual(st_passive["mode"], "passive")
            self.assertEqual(st_passive["passive_reason"], "righting_no_sympathetic_progress")
            self.assertTrue(any(c.get("t") == "motion_plan" for c in gw.issued), "Calm pose motion_plan issued before release")
            self.assertTrue(any(c.get("t") == "stop" and c.get("detach") is True for c in gw.issued), "Servos detached in passive state")

            # 3. Any external motion command immediately preempts System 3 (`mode == 'yielded'`)
            await gw.emit_external_command({"t": "intent", "name": "walk", "robot_id": "p4", "seq": 999})
            self.assertEqual(ctrl.robot_status("p4")["mode"], "yielded")
        finally:
            await ctrl.close()

    async def test_controller_servo_release_defers_for_yoloe_person_and_releases_when_quiet(self):
        person_visible = {"visible": True}

        def fake_camera(_rid: str):
            if not person_visible["visible"]:
                return None
            return SimpleNamespace(
                received_at=gw.now,
                recognition=SimpleNamespace(
                    objects=[{"label": "person", "confidence": 0.9, "x": 0.3, "y": 0.3, "width": 0.3, "height": 0.4}]
                ),
            )

        gw = FakePresenceGateway()
        ctrl = PresenceController(gw, camera_analysis_fn=fake_camera)
        try:
            ctrl.configure("p4", {
                **validate_presence_settings(None),
                "servo_release_s": 10.0,
                "presence_defers_release": True,
            })
            gw.now = 115.0  # 15s elapsed > 10s, but YOLOE sees a person!
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.08)
            self.assertNotEqual(ctrl.robot_status("p4")["mode"], "resting_released")

            # Person leaves -> after 11s quiet inactivity, robot lays down and detaches servos
            person_visible["visible"] = False
            gw.now = 127.0
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.08)
            self.assertEqual(ctrl.robot_status("p4")["mode"], "resting_released")
            self.assertTrue(any(c.get("t") == "stop" and c.get("detach") is True for c in gw.issued))
        finally:
            await ctrl.close()

    async def test_walk_stop_resumes_conversational_presence_while_detach_latches_stopped(self):
        gw = FakePresenceGateway()
        ctrl = PresenceController(gw)
        try:
            ctrl.configure("p4", validate_presence_settings(None))
            # 1. Normal walk release (`stop` with `detach=False`) yields briefly, NOT latching stopped!
            await gw.emit_external_command({"t": "stop", "detach": False, "robot_id": "p4", "seq": 10})
            self.assertEqual(ctrl.robot_status("p4")["mode"], "yielded")

            # 2. After 1.0s settle, `vad_open` keeps servos completely quiet (no `walk_target` stream)
            #    so mechanical servo noise never holds P4's microphone VAD gate open!
            gw.now = 101.2
            await gw.emit_event({"t": "event", "robot_id": "p4", "name": "vad_open"})
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.08)
            st_listen = ctrl.robot_status("p4")
            self.assertEqual(st_listen["mode"], "standby")
            self.assertIsNone(st_listen["streaming_walk_seq"])
            conn = gw._connections["p4"]
            self.assertEqual([c for c in conn.sent_commands if c.get("t") == "walk_target"], [])

            # 3. Live TTS speech immediately wakes conversational presence with foreground `talk_happy`!
            gw.now = 103.5
            gw.speaking = (True, 0.72)
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.08)
            self.assertEqual(ctrl.robot_status("p4")["mode"], "active")
            self.assertEqual(ctrl.robot_status("p4")["active_expression"], "talk_happy")
            walk_targets = [c for c in conn.sent_commands if c.get("t") == "walk_target"]
            self.assertGreaterEqual(len(walk_targets), 1)
            talk_faces = [
                c for c in gw.issued
                if c.get("name") == "face" and (c.get("params") or {}).get("expr") == "talk_happy"
            ]
            self.assertTrue(talk_faces and talk_faces[-1]["params"].get("background") is False)

            # 4. If `vad_open` opens right after speech stops, any active `walk_target` stream closes immediately
            #    and releases its foreground face token so the microphone hears cleanly!
            gw.now = 104.0
            gw.speaking = (False, 0.0)
            await gw.emit_event({"t": "event", "robot_id": "p4", "name": "vad_open"})
            await asyncio.sleep(0.08)
            self.assertEqual(ctrl.robot_status("p4")["mode"], "standby")
            self.assertIsNone(ctrl.robot_status("p4")["streaming_walk_seq"])
            self.assertTrue(
                any(
                    c.get("name") == "face" and (c.get("params") or {}).get("release") is True
                    for c in gw.issued
                ),
                "Closing conversational walk stream on VAD open must release its foreground face token",
            )

            # 5. Deliberate servo Detach (`detach=True`) latches System 3 into `"stopped"`
            await gw.emit_external_command({"t": "stop", "detach": True, "robot_id": "p4", "seq": 12})
            self.assertEqual(ctrl.robot_status("p4")["mode"], "stopped")
        finally:
            await ctrl.close()

    async def test_support_stand_stays_passive_without_cycling_until_handled_onto_ground(self):
        gw = FakePresenceGateway()
        conn = gw._connections["p4"]
        conn.last_calibration = {"joints": {}}
        conn.last_status["output_ready"] = True
        conn.last_status["output_armed"] = False
        ctrl = PresenceController(gw)
        try:
            ctrl.configure("p4", validate_presence_settings(None))
            # 1. Cold boot with disarmed servos (`output_armed=False`): issues ONE `stand` (never `walk` while disarmed)
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.06)
            stands_boot = [c for c in gw.issued if c.get("name") == "stand"]
            walks_boot = [c for c in gw.issued if c.get("name") == "walk"]
            self.assertEqual(len(stands_boot), 1)
            self.assertEqual(len(walks_boot), 0)
            conn.last_status["output_armed"] = True

            # 2. On a stationary level support stand: legs tilt in air while IMU stays flat (0 deg) -> enters `passive` ONCE
            import torch
            manifold = _get_shared_manifold(None)
            for step in range(12):
                gw.now = 100.75 + step * 0.06
                pz = min(15.0, step * 2.2) / 42.0
                act = [0.0, 0.0, pz, 0.0, 0.0, pz, 0.0, 0.0, -pz, 0.0, 0.0, -pz]
                q_rad = manifold.continuous_decode_rad(torch.tensor([act], dtype=torch.float64))[0]
                q = [math.degrees(float(v)) for v in q_rad]
                gw.measured_deg = q
                gw.commanded_deg = q
                gw.tilt_pitch_deg = 0.0
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.02)
                if ctrl.robot_status("p4")["mode"] == "passive":
                    break

            self.assertEqual(ctrl.robot_status("p4")["mode"], "passive")
            self.assertEqual(ctrl.robot_status("p4")["passive_reason"], "legs_moved_without_ground_reaction")
            conn.last_status["output_armed"] = False
            stands_after_passive = len([c for c in gw.issued if c.get("name") == "stand"])

            # 3. Sitting untouched on the level support stand for 20 seconds: NEVER auto-stands or cycles!
            for extra_s in (1.5, 3.0, 5.0, 8.0, 14.0, 20.0):
                gw.now = 102.0 + extra_s
                gw.gyro_rad_s = [0.0, 0.0, 0.0]
                gw.accel_m_s2 = [0.0, 0.0, 9.80665]
                gw.tilt_pitch_deg = 0.0
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.02)
                self.assertEqual(ctrl.robot_status("p4")["mode"], "passive")
            self.assertEqual(len([c for c in gw.issued if c.get("name") == "stand"]), stands_after_passive)

            # 4. User lifts robot off stand (`gyro_dps ~ 57 deg/s`) and sets it level on the ground for 1.6s -> stands ONCE!
            gw.now = 123.0
            gw.gyro_rad_s = [0.0, 1.0, 0.0]
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.02)

            gw.gyro_rad_s = [0.0, 0.0, 0.0]
            gw.measured_deg = list(STAND_ANGLES_DEG)
            gw.commanded_deg = list(STAND_ANGLES_DEG)
            for dt in (0.2, 0.8, 1.4, 1.8):
                gw.now = 123.0 + dt
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.02)

            self.assertEqual(len([c for c in gw.issued if c.get("name") == "stand"]), stands_after_passive + 1)
            conn.last_status["output_armed"] = True

            # 5. Grounded on the floor during speech: nose-up leg extension produces matching negative IMU pitch -> stays active, NEVER cycles!
            gw.speaking = (True, 0.65)
            for step in range(14):
                gw.now = 125.6 + step * 0.06
                pz_mm = 14.0 * math.sin(step * 0.25)
                pz = pz_mm / 42.0
                act = [0.0, 0.0, pz, 0.0, 0.0, pz, 0.0, 0.0, -pz, 0.0, 0.0, -pz]
                q_rad = manifold.continuous_decode_rad(torch.tensor([act], dtype=torch.float64))[0]
                q = [math.degrees(float(v)) for v in q_rad]
                gw.measured_deg = q
                gw.commanded_deg = q
                # Matching grounded nose-up/down pitch (`pitch < 0` when front extends downward, `pz_mm > 0`)
                gw.tilt_pitch_deg = -math.degrees(math.atan2(2.0 * pz_mm, 124.0)) * 0.85
                gw.gyro_rad_s = [0.0, -0.15 * math.cos(step * 0.25), 0.0]
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.02)
                self.assertNotEqual(ctrl.robot_status("p4")["mode"], "passive")
            self.assertEqual(ctrl.robot_status("p4")["mode"], "active")
        finally:
            await ctrl.close()

    def test_closed_loop_offstand_and_imu_off_never_runaway_or_hit_carrier_limits(self):
        import numpy as np
        import torch
        from gateway.presence.contract import update_compliance_trim_mm

        actor = PresenceActor(DEFAULT_ACTIVE_POLICY)
        manifold = _get_shared_manifold(None)
        # Centered-shaft-head V2 calibration matching physical robot (`rear_right_carrier` floor = -41.22 deg)
        cal_specs = [
            (0, "rear_left_shoulder", 1760, False, 0),
            (1, "rear_left_carrier", 2750, True, -3087),
            (2, "rear_left_crank", 2870, True, -11768),
            (3, "rear_right_shoulder", 1650, True, 0),
            (4, "rear_right_carrier", 415, False, -3087),
            (5, "rear_right_crank", 440, False, -11768),
            (6, "front_left_shoulder", 1650, True, 0),
            (7, "front_left_carrier", 2740, True, -3087),
            (8, "front_left_crank", 2750, True, -11768),
            (9, "front_right_shoulder", 1700, False, 0),
            (10, "front_right_carrier", 560, False, -3087),
            (11, "front_right_crank", 575, False, -11768),
        ]
        cal_joints = [
            {
                "id": idx,
                "joint": name,
                "home_us": home_us,
                "pulse_us": home_us,
                "us_per_degree": 10.0,
                "invert": inv,
                "home_cd": home_cd,
            }
            for idx, name, home_us, inv, home_cd in cal_specs
        ]
        live_body = manifold.body_for_calibration(cal_joints)
        low_deg = np.rad2deg(live_body.low.detach().cpu().numpy()).reshape(12)
        high_deg = np.rad2deg(live_body.high.detach().cpu().numpy()).reshape(12)
        stand_q = torch.deg2rad(torch.tensor(STAND_ANGLES_DEG, dtype=torch.float64, device=live_body.device)).reshape(1, 4, 3)
        pts_base, _ = live_body.forward(stand_q)
        stand_feet_mm = (pts_base - live_body.origin.unsqueeze(0)).reshape(12).detach().cpu().numpy()
        pose_scale = np.array((95.0, 155.0, 180.0) * 4, dtype=np.float64)

        offstand_init_deg = [11.2, -3.8, -27.7, -5.9, 0.8, -19.5, -8.0, -2.2, -29.6, -1.2, 5.0, -13.9]
        for imu_flag in (False, True):
            hist = PresenceObservationHistory()
            prev_norm = [0.75, -0.75, 0.75] * 4
            trim_mm = [0.0] * 12
            cmd_q = torch.deg2rad(torch.tensor(offstand_init_deg, dtype=torch.float64, device=live_body.device)).reshape(1, 12)
            meas_deg = list(offstand_init_deg)
            for step in range(80):
                t_s = step * 0.05
                cmd_deg = np.rad2deg(cmd_q[0].detach().cpu().numpy()).tolist()
                feat = assemble_presence_features(
                    measured_deg=meas_deg,
                    commanded_deg=cmd_deg,
                    velocity_deg_s=[0.0] * 12,
                    chatter_deg=[0.2] * 12,
                    usable_flags=[True] * 12,
                    orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
                    angular_rate_rad_s=[0.0, 0.0, 0.0],
                    acceleration_m_s2=[0.0, 0.0, 9.80665],
                    imu_enabled=imu_flag,
                    chatter_relief_enabled=True,
                    person_yaw=-0.80,
                    person_pitch=0.35,
                    person_conf=0.95,
                    known_face=1.0,
                    motion_mag=0.5,
                    listening_active=1.0,
                    mic_rms=0.55,
                    speaking_active=0.0,
                    speech_rms=0.0,
                    boredom_level=0.0,
                    phase_rad=t_s * 2.2,
                    previous_foot_action=prev_norm,
                )
                obs_vec = hist.push_and_project(t_s, feat)
                prev_norm, foot_mm, comp_mm, expr_name, _ = actor.infer(obs_vec)
                if not imu_flag:
                    self.assertNotEqual(expr_name, "surprised", "IMU-off listening must never predict surprised")
                trim_mm = update_compliance_trim_mm(trim_mm, comp_mm, enabled=True)
                des_mm = stand_feet_mm + np.asarray(foot_mm) + np.asarray(trim_mm)
                act = np.clip(des_mm / pose_scale, -1.0, 1.0).tolist()
                cmd_q, _, _ = manifold.step_host_command(act, cmd_q, speed_scale=1.0, body=live_body)
                next_deg = np.rad2deg(cmd_q[0].detach().cpu().numpy())
                meas_deg = [0.25 * m + 0.75 * float(c) for m, c in zip(meas_deg, next_deg)]
                if step >= 15:
                    self.assertGreaterEqual(float(np.min(next_deg - low_deg)), 20.0, "Too close to low calibration limit")
                    self.assertGreaterEqual(float(np.min(high_deg - next_deg)), 20.0, "Too close to high calibration limit")
                    self.assertLessEqual(
                        float(np.max(np.abs(next_deg - np.asarray(STAND_ANGLES_DEG)))),
                        14.0,
                        "Closed-loop presence contorted legs away from standing",
                    )

    async def test_long_stream_never_evicts_walk_owner_static_vision_has_zero_motion_and_settles_to_symmetric_stand(self):
        import numpy as np

        vision_box = {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5, "label": "laptop", "t": 100.0}

        def fake_camera(_rid: str):
            return SimpleNamespace(
                received_at=vision_box["t"],
                recognition=SimpleNamespace(
                    objects=[
                        {
                            "label": vision_box["label"],
                            "confidence": 0.92,
                            "x": vision_box["x"],
                            "y": vision_box["y"],
                            "width": vision_box["w"],
                            "height": vision_box["h"],
                        }
                    ]
                ),
            )

        gw = FakePresenceGateway()
        conn = gw._connections["p4"]
        ctrl = PresenceController(gw, camera_analysis_fn=fake_camera)
        try:
            ctrl.configure("p4", validate_presence_settings(None))
            st = ctrl._state("p4")
            # 1. Static large YOLOE object (area = 0.25) across frames must produce motion_mag == 0.0
            _, _, p_conf_0, _, m0 = ctrl._extract_vision_context("p4", st, 100.0, True)
            vision_box["t"] = 100.25
            _, _, p_conf_1, _, m1 = ctrl._extract_vision_context("p4", st, 100.25, True)
            self.assertEqual(p_conf_0, 0.0)
            self.assertEqual(p_conf_1, 0.0)
            self.assertEqual(m0, 0.0)
            self.assertEqual(m1, 0.0)

            # Real movement of a person across frames produces positive motion_mag
            vision_box["label"] = "person"
            vision_box["t"] = 100.50
            ctrl._extract_vision_context("p4", st, 100.50, True)
            vision_box["x"] = 0.32
            vision_box["t"] = 100.70
            _, _, p_conf_m, _, m_move = ctrl._extract_vision_context("p4", st, 100.70, True)
            self.assertGreater(p_conf_m, 0.8)
            self.assertGreater(m_move, 0.25)

            # 2. Stream > 80 continuous `walk_target` samples (exceeding the 64-entry owned_sequences prune threshold)
            #    while speaking: `walk_seq` must NEVER be self-evicted or trigger `mode == 'yielded'`!
            gw.speaking = (True, 0.65)
            for tick in range(85):
                gw.now = 102.0 + tick * 0.30
                vision_box["t"] = gw.now
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.008)
                status = ctrl.robot_status("p4")
                self.assertNotEqual(status["mode"], "yielded", f"Self-evicted walk_seq at tick {tick}")

            walk_targets = [c for c in conn.sent_commands if c.get("t") == "walk_target"]
            self.assertGreaterEqual(len(walk_targets), 75, "Must stream well past 64-sequence pruning threshold")
            self.assertEqual(ctrl.robot_status("p4")["mode"], "active")
            self.assertIn(st.walk_seq, st.owned_sequences)

            # 3. Stop speaking and remove person -> controller smoothly returns feet to symmetric anchor before closing hold
            gw.speaking = (False, 0.0)
            vision_box["label"] = "laptop"
            for tick in range(35):
                gw.now = 130.0 + tick * 0.12
                vision_box["t"] = gw.now
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.008)
                if ctrl.robot_status("p4")["mode"] == "standby" and st.walk_seq is None:
                    break

            self.assertEqual(ctrl.robot_status("p4")["mode"], "standby")
            self.assertIsNone(st.walk_seq)
            last_target = [c for c in conn.sent_commands if c.get("t") == "walk_target"][-1]
            anchor_err_mm = float(np.max(np.abs(np.asarray(last_target["feet_mm"]) - st.anchor_feet_mm)))
            self.assertLessEqual(anchor_err_mm, 1.5, "Must settle back to symmetric anchor before locking hold")

            # 4. Resume clears a latched calibrate mode
            conn.mode = "calibrate"
            await ctrl.clear_passive("p4", stand_up=True)
            self.assertEqual(conn.mode, "normal")
            self.assertEqual(gw.ensure_normal_calls, 1)
        finally:
            await ctrl.close()

    async def test_passive_post_detach_slump_ignored_and_asymmetric_posture_reanchors_to_stand(self):
        gw = FakePresenceGateway()
        ctrl = PresenceController(gw)
        try:
            ctrl.configure("p4", validate_presence_settings(None))
            st = ctrl._state("p4")
            await ctrl._enter_passive("p4", st, "legs_moved_without_ground_reaction")
            self.assertEqual(ctrl.robot_status("p4")["mode"], "passive")
            stands_before = len([c for c in gw.issued if c.get("name") == "stand"])

            # Post-detach servo slump at +0.7s (65 deg/s gyro + 22 deg settle tilt) must NOT trigger handling/auto-stand
            gw.now = 100.7
            gw.gyro_rad_s = [0.0, 1.15, 0.0]
            gw.tilt_pitch_deg = 22.0
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.02)

            # Settle level at 22 deg after slump -> stays passive indefinitely without re-triggering stand
            gw.gyro_rad_s = [0.0, 0.0, 0.0]
            for dt in (2.2, 3.0, 4.2):
                gw.now = 100.0 + dt
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.02)
            self.assertEqual(ctrl.robot_status("p4")["mode"], "passive")
            self.assertEqual(len([c for c in gw.issued if c.get("name") == "stand"]), stands_before)

            # Clear passive with asymmetric twisted posture -> re-anchors to symmetric STAND_ANGLES_DEG
            await ctrl.clear_passive("p4", stand_up=False)
            gw.measured_deg = [-2.2, 82.0, -92.0, 2.0, 1.0, -21.0, -3.0, 2.0, -22.0, 1.0, 2.0, -21.0]
            gw.commanded_deg = list(gw.measured_deg)
            gw.tilt_pitch_deg = 0.0
            gw.now = 106.0
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.04)
            self.assertTrue(st.anchor_is_standing, "Asymmetric twisted posture must re-anchor to symmetric stand")
        finally:
            await ctrl.close()

    async def test_idle_robot_stays_completely_dormant_under_static_load_mic_noise_and_person_movement(self):
        person_box = {"x": 0.25, "t": 100.0}

        def fake_camera(_rid: str):
            return SimpleNamespace(
                received_at=person_box["t"],
                recognition=SimpleNamespace(
                    objects=[
                        {
                            "label": "person",
                            "confidence": 0.94,
                            "x": person_box["x"],
                            "y": 0.2,
                            "width": 0.35,
                            "height": 0.5,
                            "identity": {"state": "face_match", "personId": "owner-greg"},
                        }
                    ]
                ),
            )

        gw = FakePresenceGateway()
        conn = gw._connections["p4"]
        # Reproduce physical P4 standing gravity sag (~8.2 deg static error) and ambient room mic RMS
        gw.measured_deg = [
            STAND_ANGLES_DEG[0] - 6.2,
            STAND_ANGLES_DEG[1] + 8.2,
            STAND_ANGLES_DEG[2] + 3.5,
            *STAND_ANGLES_DEG[3:],
        ]
        conn.microphone_level = 0.09  # ambient noise while utterance_open is False
        ctrl = PresenceController(gw, camera_analysis_fn=fake_camera)
        try:
            ctrl.configure(
                "p4",
                {
                    **validate_presence_settings(None),
                    "self_right_enabled": False,
                    "servo_release_s": 180.0,
                    "presence_defers_release": True,
                },
            )
            for step in range(40):
                gw.now = 101.0 + step * 2.5  # 100 seconds of idle standing with person moving in frame
                person_box["t"] = gw.now
                person_box["x"] = 0.25 + 0.12 * math.sin(step * 0.6)
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.005)
                self.assertEqual(ctrl.robot_status("p4")["mode"], "standby")

            self.assertEqual([c for c in conn.sent_commands if c.get("t") == "walk_target"], [])
            self.assertEqual([c for c in gw.issued if c.get("name") in ("walk", "face")], [])
        finally:
            await ctrl.close()

    async def test_boot_reconnect_resets_release_timer_yields_to_wake_stretch_and_rest_angles_fit_pwm_limits(self):
        import numpy as np
        from gateway.presence import CALM_PASSIVE_DEG, REST_ANGLES_DEG

        # 1. Verify REST_ANGLES_DEG and CALM_PASSIVE_DEG satisfy exact linkage closure and P4 PWM bounds
        manifold = _get_shared_manifold(None)
        cal_specs = [
            (0, "rear_left_shoulder", 1760, False, 0),
            (1, "rear_left_carrier", 2750, True, -3087),
            (2, "rear_left_crank", 2870, True, -11768),
            (3, "rear_right_shoulder", 1650, True, 0),
            (4, "rear_right_carrier", 415, False, -3087),
            (5, "rear_right_crank", 440, False, -11768),
            (6, "front_left_shoulder", 1650, True, 0),
            (7, "front_left_carrier", 2740, True, -3087),
            (8, "front_left_crank", 2750, True, -11768),
            (9, "front_right_shoulder", 1700, False, 0),
            (10, "front_right_carrier", 560, False, -3087),
            (11, "front_right_crank", 575, False, -11768),
        ]
        cal_joints = [
            {
                "id": idx,
                "joint": name,
                "home_us": home_us,
                "pulse_us": home_us,
                "us_per_degree": 10.0,
                "invert": inv,
                "home_cd": home_cd,
            }
            for idx, name, home_us, inv, home_cd in cal_specs
        ]
        live_body = manifold.body_for_calibration(cal_joints)
        low_deg = np.rad2deg(live_body.low.detach().cpu().numpy()).reshape(12)
        high_deg = np.rad2deg(live_body.high.detach().cpu().numpy()).reshape(12)
        for pose_name, pose_deg in (("REST_ANGLES_DEG", REST_ANGLES_DEG), ("CALM_PASSIVE_DEG", CALM_PASSIVE_DEG)):
            arr = np.asarray(pose_deg, dtype=np.float64)
            proj, _ = manifold.project_angles_deg(pose_deg, body=live_body)
            self.assertLessEqual(
                float(np.max(np.abs(np.asarray(proj) - arr))),
                1e-3,
                f"{pose_name} must satisfy exact V2 four-bar linkage closure",
            )
            self.assertGreaterEqual(
                float(np.min(arr - low_deg)),
                18.0,
                f"{pose_name} must stay >= 18 deg above low PWM/calibration limit",
            )
            self.assertGreaterEqual(
                float(np.min(high_deg - arr)),
                18.0,
                f"{pose_name} must stay >= 18 deg below high PWM/calibration limit",
            )

        # 2. Gateway runs for 32 minutes (1920s > servo_release_s=180s) BEFORE robot powers on and connects
        freestyle_busy = {"active": False}
        gw = FakePresenceGateway()
        conn = gw._connections["p4"]
        conn.last_calibration = {"joints": cal_joints}
        conn.last_status["output_ready"] = True
        conn.last_status["output_armed"] = False
        ctrl = PresenceController(gw, freestyle_active_fn=lambda _rid: freestyle_busy["active"])
        ctrl.runtime.load()
        try:
            ctrl.configure("p4", {**validate_presence_settings(None), "servo_release_s": 180.0})
            # Simulate robot offline at gateway start, then booting 32 minutes later
            await gw.emit_event({"t": "connection", "status": "disconnected", "robot_id": "p4"})
            gw.now = 2020.0  # +1920s elapsed
            await gw.emit_event({"t": "connection", "status": "connected", "robot_id": "p4", "epoch": 1})
            self.assertEqual(ctrl.robot_status("p4")["release_idle_seconds"], 0.0)

            # Boot `wake` event arrives before EnvironmentAdapter finishes submitting Freestyle stretch
            await gw.emit_event({
                "t": "event",
                "name": "body_event",
                "robot_id": "p4",
                "epoch": 1,
                "data": {"kind": "wake", "reason": "boot"},
            })
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.06)

            # System 3 MUST NOT issue resting_release (`motion_plan` / `stop`) or a competing `stand`!
            self.assertEqual(gw.issued, [], "System 3 must yield cleanly to the boot wake/Freestyle stretch sequence")
            self.assertEqual(ctrl.robot_status("p4")["mode"], "yielded")

            # Freestyle claims and executes "Perform a whole-body stretch." over 6 seconds
            freestyle_busy["active"] = True
            for dt in (0.5, 2.0, 4.0, 6.0):
                gw.now = 2020.0 + dt
                await gw.emit_event({"t": "imu", "robot_id": "p4"})
                await asyncio.sleep(0.01)
                self.assertEqual(gw.issued, [], "System 3 must not preempt active Freestyle boot stretch")
                self.assertEqual(ctrl.robot_status("p4")["mode"], "yielded")

            # Freestyle stretch finishes with robot standing and armed -> System 3 settles into standby without fault
            freestyle_busy["active"] = False
            conn.last_status["output_armed"] = True
            gw.now = 2027.0
            await gw.emit_event({"t": "imu", "robot_id": "p4"})
            await asyncio.sleep(0.04)
            self.assertEqual(ctrl.robot_status("p4")["mode"], "standby")
            self.assertEqual(gw.issued, [])
        finally:
            await ctrl.close()


if __name__ == "__main__":
    unittest.main()
