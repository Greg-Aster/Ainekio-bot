"""Unit, lifecycle, and closed-loop 50 Hz MuJoCo qualification tests for Neural Pose & Emote."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "Master"), str(ROOT / "Slave/software")):
    if p not in sys.path:
        sys.path.insert(0, p)

from experiments.freestyle.bridge import Bridge, recovery_has_motion_owner
from experiments.freestyle.neural_pose.actor import NeuralPoseActor
from experiments.freestyle.neural_pose.contract import (
    JOINTS,
    POSE_FEATURES,
    POSE_OBS_SIZE,
    POSE_FOOT_SCALE_MM,
    POSE_SCHEMA,
    PoseObservationHistory,
    assemble_pose_features,
    pose_foot_offsets,
    projected_gravity_from_wxyz,
)
from experiments.freestyle.neural_pose.executor import NeuralPoseRuntime, resolve_active_policy_path
from experiments.freestyle.neural_pose.goals import (
    STAND_ANGLES_DEG,
    PoseManifold,
    compile_goal_segments,
    usable_joint_angles_deg,
)


def _mock_folded_faulted_observation() -> dict:
    """Reproduce the exact unloaded/folded + clipped-ADC posture that broke legacy IK."""
    folded_deg = [-2.2, -44.61, -58.6, 2.1, -41.07, -55.2, -2.9, 16.8, -70.5, -0.7, 19.4, -96.7]
    faulted = {1, 4}  # Rear-left & rear-right carriers clipped at 3309 mV / 0 mV
    joints = {}
    for idx, name in enumerate(JOINTS):
        ok = idx not in faulted
        joints[name] = {
            "home_deg": STAND_ANGLES_DEG[idx],
            "model_deg": (180.0 if idx == 1 else -180.0) if not ok else folded_deg[idx],
            "filtered_model_deg": (180.0 if idx == 1 else -180.0) if not ok else folded_deg[idx],
            "commanded_model_deg": folded_deg[idx],
            "velocity_deg_s": 0.0,
            "feedback_usable": ok,
            "feedback_faults": ["clipped"] if not ok else [],
        }
    return {
        "epoch": 1,
        "model": "v2-12servo",
        "features": ["walk_nominal_v1", "motion_targets_v1", "face_feedback_v1"],
        "joints": joints,
        "joint_speed_limit_deg_s": 545.45,
        "feedback": {"device_us": 1_000_000, "scan": 1, "enabled": True, "stalled_joints": 0},
        "imu": {
            "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
            "angular_rate_rad_s": [0.0, 0.0, 0.0],
            "acceleration_m_s2": [0.0, 0.0, 9.81],
            "motion": {"sequence": 0, "nominal_sample": 0},
        },
    }


class NeuralPoseContractAndGoalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifold = PoseManifold(device="cpu")

    def test_contract_and_history_parity_with_faulted_4th_wire(self):
        # Upright wxyz=[1,0,0,0] -> projected gravity = [0, 0, -1]
        self.assertEqual(projected_gravity_from_wxyz([1.0, 0.0, 0.0, 0.0]), [0.0, 0.0, -1.0])

        usable = [True] * 12
        usable[1] = False
        usable[4] = False
        measured = [0.0] * 12
        measured[1] = 999.0  # Clipped ADC garbage must be ignored when usable=False
        measured[4] = -999.0
        commanded = list(STAND_ANGLES_DEG)
        vel = [5.0] * 12

        row = assemble_pose_features(
            measured_deg=measured,
            commanded_deg=commanded,
            velocity_deg_s=vel,
            usable_flags=usable,
            orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
            angular_rate_rad_s=[0.1, -0.1, 0.05],
            acceleration_m_s2=[0.0, 0.0, 9.81],
            goal_joint_deg=STAND_ANGLES_DEG,
            goal_foot_norm=[0.0] * 12,
            leg_support=[1.0, 1.0, 1.0, 1.0],
            speed_scale=0.8,
            previous_action=[0.0] * 12,
        )
        self.assertEqual(len(row), POSE_FEATURES)
        # Faulted joints 1 & 4 use commanded_deg (0.94 deg) and zero velocity
        self.assertAlmostEqual(row[1], math.radians(0.94), places=5)
        self.assertAlmostEqual(row[4], math.radians(0.94), places=5)
        self.assertEqual(row[12 + 1], 0.0)
        self.assertEqual(row[12 + 4], 0.0)
        self.assertEqual(row[24 + 1], 0.0)
        self.assertEqual(row[24 + 4], 0.0)
        self.assertEqual(row[24 + 0], 1.0)

        hist = PoseObservationHistory()
        vec0 = hist.push_and_project(1.00, row)
        self.assertEqual(len(vec0), POSE_OBS_SIZE)
        # Step 0 primes all 15 frames with earliest real scan
        self.assertEqual(vec0[:POSE_FEATURES], row)
        self.assertEqual(vec0[-POSE_FEATURES:], row)

        row2 = list(row)
        row2[0] = 0.25
        vec1 = hist.push_and_project(1.02, row2)
        self.assertEqual(vec1[:POSE_FEATURES], row2)
        self.assertEqual(vec1[POSE_FEATURES : 2 * POSE_FEATURES], row)

    def test_goals_compile_from_folded_faulted_posture_without_blocking(self):
        obs = _mock_folded_faulted_observation()
        angles = usable_joint_angles_deg(obs)
        self.assertAlmostEqual(angles[1], -44.61, places=2)
        self.assertAlmostEqual(angles[4], -41.07, places=2)

        # Include exact spatial `body` + `feet` + `pose` + `move` + `oscillate` + `stand`
        program = [
            {"name": "face", "arguments": {"expr": "curious"}},
            {
                "name": "body",
                "arguments": {
                    "translation_mm": [18.0, 0.0, 12.0],
                    "rotation_deg": [0.0, -4.0, 0.0],
                    "legs": ["front_right"],
                    "foot_offsets_mm": [[25.0, -10.0, 38.0]],
                    "speed_pct": 75,
                },
            },
            {
                "name": "oscillate",
                "arguments": {
                    "joints": ["front_right_shoulder"],
                    "reference": "absolute",
                    "center_deg": [0.0],
                    "amplitude_deg": [22.0],
                    "hz": 1.8,
                    "cycles": 2.0,
                    "speed_pct": 80,
                },
            },
            {
                "name": "pose",
                "arguments": {
                    "joints": ["front_right_shoulder", "front_right_carrier", "front_right_crank"],
                    "reference": "absolute",
                    "angles_deg": [0.0, 0.94, -21.25],
                    "speed_pct": 70,
                },
            },
            {
                "name": "move",
                "arguments": {
                    "joint": "front_left_carrier",
                    "reference": "absolute",
                    "angle_deg": 42.0,
                    "speed_pct": 75,
                },
            },
            {"name": "hold", "arguments": {"seconds": 0.4}},
            {"name": "stand", "arguments": {}},
        ]
        segments = compile_goal_segments(program, obs, self.manifold)
        self.assertEqual(len(segments), len(program))
        for seg in segments:
            if seg["kind"] == "pose_goal":
                self.assertEqual(len(seg["goal_deg"]), 12)
                self.assertEqual(len(seg["goal_foot_norm"]), 12)
                self.assertTrue(all(math.isfinite(v) for v in seg["goal_deg"]))
                self.assertTrue(all(-1.0 <= v <= 1.0 for v in seg["goal_foot_norm"]))

    def test_continuous_host_step_eliminates_binary_halving_cliffs_and_matches_p4_roundtrip(self):
        # Downward extension sweep crossing s ~= 0.500 (previously snapped 0.5 -> 0.25 by >20 deg)
        z_sweep = np.linspace(-0.22, -0.32, 16)
        legacy_degs = []
        cont_degs = []
        cmd_q = torch.tensor(STAND_ANGLES_DEG, dtype=torch.float64).reshape(1, 12) * (math.pi / 180.0)
        cmd_q, _ = self.manifold.body.pwm(cmd_q)

        for z_val in z_sweep:
            act = [0.0, 0.0, float(z_val)] * 4
            act_t = torch.tensor(act, dtype=torch.float64).reshape(1, 12)
            q_leg = (self.manifold.body.decode(act_t)[0] * 180.0 / math.pi).tolist()
            q_cnt = (self.manifold.continuous_decode_rad(act_t)[0] * 180.0 / math.pi).tolist()
            legacy_degs.append(q_leg)
            cont_degs.append(q_cnt)

            prev_deg = (cmd_q[0] * 180.0 / math.pi).tolist()
            cmd_q, applied_act, feet_mm = self.manifold.step_host_command(act, cmd_q, speed_scale=0.7)
            next_deg = (cmd_q[0] * 180.0 / math.pi).tolist()
            step_jump = max(abs(a - b) for a, b in zip(next_deg, prev_deg))
            self.assertLessEqual(step_jump, 7.75)
            self.assertEqual(len(applied_act), 12)
            self.assertEqual(len(feet_mm), 12)

            # Verify P4 `ainekio_v2_nominal_foot_pose` accepts `feet_mm` at fraction=1.0 with 0.0 deg error
            sent_norm = torch.tensor(feet_mm, dtype=torch.float64).reshape(1, 12) / self.manifold.body.scale.repeat(4)
            q_p4 = self.manifold.body.decode(sent_norm)
            p4_err_deg = float((q_p4 - cmd_q).abs().max().item() * 180.0 / math.pi)
            self.assertLess(p4_err_deg, 0.05)

        max_legacy_cliff = max(
            max(abs(a - b) for a, b in zip(legacy_degs[i], legacy_degs[i - 1]))
            for i in range(1, len(legacy_degs))
        )
        max_cont_step = max(
            max(abs(a - b) for a, b in zip(cont_degs[i], cont_degs[i - 1]))
            for i in range(1, len(cont_degs))
        )
        self.assertGreater(max_legacy_cliff, 18.0)
        self.assertLess(max_cont_step, 3.0)

        # Upper hip dead-zone graze (step 4..6 from live telemetry) must stay smooth without 60+ deg shoulder flip
        upper_vecs = ([0.134, 0.040, 0.553], [0.127, 0.027, 0.569], [0.152, -0.001, 0.626])
        upper_q = [
            (self.manifold.continuous_decode_rad(torch.tensor(v * 4, dtype=torch.float64).reshape(1, 12))[0] * 180.0 / math.pi).tolist()
            for v in upper_vecs
        ]
        for i in range(1, len(upper_q)):
            self.assertLess(max(abs(a - b) for a, b in zip(upper_q[i], upper_q[i - 1])), 15.0)

    def test_spatial_body_pivot_matches_authoritative_four_bar_kinematics(self):
        from experiments.freestyle.kinematics import reference, target_for_spatial

        ref_mod = reference()
        _, _, qs, _ = ref_mod.stand(ref_mod.load())
        init_deg = np.rad2deg(qs[[2, 3, 0, 1]]).reshape(-1).tolist()
        positions = {JOINTS[i]: init_deg[i] for i in range(12)}
        body_op = {
            "name": "body",
            "arguments": {
                "translation_mm": [6.0, -3.0, -5.0],
                "rotation_deg": [2.0, -3.0, 2.0],
                "legs": [],
                "foot_offsets_mm": [],
            },
        }
        ref_deg = [c / 100.0 for c in target_for_spatial(body_op, positions)]
        ours_deg = self.manifold.resolve_spatial_deg(body_op, init_deg)
        max_diff = max(abs(a - b) for a, b in zip(ref_deg, ours_deg))
        self.assertLess(max_diff, 0.05)

    def test_segment_durations_ignore_2000_deg_s_nvs_ramp_and_allow_full_servo_travel(self):
        obs = _mock_folded_faulted_observation()
        obs["joint_speed_limit_deg_s"] = 2000.0
        segs = compile_goal_segments(
            [
                {"name": "stand", "arguments": {}},
                {"name": "feet", "arguments": {"legs": ["front_right"], "offsets_mm": [[24.0, -14.0, 36.0]], "speed_pct": 75}},
            ],
            obs,
            self.manifold,
        )
        self.assertGreaterEqual(segs[0]["duration_s"], 1.75)
        self.assertGreaterEqual(segs[1]["duration_s"], 0.90)

    def test_host_step_meets_50hz_realtime_budget_and_matches_tensor_body(self):
        import time

        from experiments.freestyle.neural_pose.goals import STAND_ANGLES_DEG, _fast_numpy_body

        rng = np.random.default_rng(7)
        acts = torch.tensor(rng.uniform(-1.0, 1.0, size=(16, 12)), dtype=torch.float64)
        fb = _fast_numpy_body(self.manifold.body)
        q_init = torch.deg2rad(torch.tensor(STAND_ANGLES_DEG, dtype=torch.float64)).reshape(1, 12)
        # Warm up once
        q = q_init
        q, _, _ = self.manifold.step_host_command(acts[0], q, speed_scale=0.75)

        t0 = time.perf_counter()
        for i in range(16):
            q, _, _ = self.manifold.step_host_command(acts[i], q, speed_scale=0.75)
        mean_ms = (time.perf_counter() - t0) / 16.0 * 1000.0
        # Must stay well below 20.0 ms (50 Hz period) so the gateway WebSocket heartbeat never starves
        self.assertLess(mean_ms, 5.0)

        # Verify exact four-bar inverse/bounded parity with TensorBody
        target = self.manifold.body.origin.unsqueeze(0) + acts.reshape(16, 4, 3) * self.manifold.body.scale
        qt, vt = self.manifold.body.inverse(target)
        qn, vn = fb.inverse(target.numpy())
        self.assertTrue(np.array_equal(vt.numpy(), vn))
        self.assertLess(float(np.max(np.abs(qt.numpy()[vt.numpy()] - qn[vn]))), 1e-10)

    def test_multistep_spatial_wave_from_sitting_posture_never_resets_mid_program(self):
        from experiments.freestyle.kinematics import target_for_spatial
        from experiments.freestyle.neural_pose.goals import STAND_ANGLES_DEG

        # Exact sitting/folded start posture recorded in live job 85ed11be
        sitting_angles = [
            2.94516, -17.5064, 14.3611,
            6.17927, -11.5939, 31.6920,
            -27.6686, 14.6320, -13.9340,
            11.2241, 39.6952, 37.3274,
        ]
        obs = {
            "joint_speed_limit_deg_s": 1000.0,
            "joints": {
                j: {
                    "home_deg": 0.0,
                    "model_deg": sitting_angles[i],
                    "filtered_model_deg": sitting_angles[i],
                    "commanded_model_deg": sitting_angles[i],
                    "feedback_usable": True,
                }
                for i, j in enumerate(JOINTS)
            },
        }
        program = [
            {"name": "body", "arguments": {"translation_mm": [-10, -10, 0], "rotation_deg": [0, 0, 0], "legs": [], "foot_offsets_mm": [], "speed_pct": 75}},
            {"name": "feet", "arguments": {"legs": ["front_left"], "offsets_mm": [[26, 12, 34]], "speed_pct": 75}},
            {"name": "feet", "arguments": {"legs": ["front_left"], "offsets_mm": [[-16, 0, 14]], "speed_pct": 75}},
            {"name": "feet", "arguments": {"legs": ["front_left"], "offsets_mm": [[16, 0, -14]], "speed_pct": 75}},
            {"name": "feet", "arguments": {"legs": ["front_left"], "offsets_mm": [[-16, 0, 14]], "speed_pct": 75}},
            {"name": "feet", "arguments": {"legs": ["front_left"], "offsets_mm": [[-26, -12, -34]], "speed_pct": 75}},
            {"name": "body", "arguments": {"translation_mm": [10, 10, 0], "rotation_deg": [0, 0, 0], "legs": [], "foot_offsets_mm": [], "speed_pct": 75}},
        ]
        segs = compile_goal_segments(program, obs, self.manifold)
        self.assertEqual(len(segs), len(program))
        # First segment must allow full travel time from sitting posture (`max_delta > 45 deg` -> >= 1.75 s)
        self.assertGreaterEqual(segs[0]["duration_s"], 1.75)

        ref_pos = dict(zip(JOINTS, STAND_ANGLES_DEG))
        stance_ref = segs[0]["goal_deg"][:6] + segs[0]["goal_deg"][9:12]
        for idx, (act, seg) in enumerate(zip(program, segs)):
            ref_cd = target_for_spatial(act, ref_pos)
            ref_pos = {j: v / 100.0 for j, v in zip(JOINTS, ref_cd)}
            ref_list = [ref_pos[j] for j in JOINTS]
            max_diff = max(abs(a - b) for a, b in zip(seg["goal_deg"], ref_list))
            self.assertLess(max_diff, 0.08, f"step {idx} diverged from authoritative spatial IK by {max_diff:.4f} deg")
            if act["name"] == "feet":
                # Support legs must stay rock-steady at the shifted body stance without resetting to STAND_ANGLES_DEG
                stance_now = seg["goal_deg"][:6] + seg["goal_deg"][9:12]
                self.assertEqual(stance_now, stance_ref)

    def test_canonical_single_joint_oscillate_and_quadruped_leg_lift_support(self):
        from experiments.freestyle.freestyle_curriculum import prog_lift_leg, prog_standing_hand
        from experiments.freestyle.neural_pose.goals import STAND_ANGLES_DEG

        obs = {
            "joint_speed_limit_deg_s": 1000.0,
            "joints": {
                j: {
                    "home_deg": 0.0,
                    "model_deg": STAND_ANGLES_DEG[i],
                    "filtered_model_deg": STAND_ANGLES_DEG[i],
                    "commanded_model_deg": STAND_ANGLES_DEG[i],
                    "feedback_usable": True,
                }
                for i, j in enumerate(JOINTS)
            },
        }
        # Verify quadruped leg lifts mark only the lifted leg as free (0.0) and the 3 stance legs as grounded (1.0)
        expected_support = {
            "rear_left": [0.0, 1.0, 1.0, 1.0],
            "rear_right": [1.0, 0.0, 1.0, 1.0],
            "front_left": [1.0, 1.0, 0.0, 1.0],
            "front_right": [1.0, 1.0, 1.0, 0.0],
        }
        for leg, exp_sup in expected_support.items():
            segs = compile_goal_segments(prog_lift_leg(leg, "normal", 1.0, 65), obs, self.manifold)
            lift_seg = next(s for s in segs if s["action"]["name"] == "feet")
            self.assertEqual(lift_seg["leg_support"], exp_sup, f"wrong support mask for {leg}")

        # Verify canonical single-joint `oscillate` (`joint`, scalar `amplitude_deg`, `cycles`, `speed_pct`) compiles cleanly
        wiggle_segs = compile_goal_segments(prog_standing_hand("right", "wiggle", 1.0, 75), obs, self.manifold)
        osc_seg = next(s for s in wiggle_segs if s["kind"] == "oscillate_goal")
        self.assertEqual(osc_seg["joint_indices"], [JOINTS.index("front_right_crank")])
        self.assertEqual(osc_seg["amplitudes_deg"], [14.0])
        self.assertEqual(osc_seg["leg_support"], [1.0, 1.0, 1.0, 0.0])


class _DummyPending:
    def __init__(self, seq: int, cmd: dict):
        self.command = cmd
        self.acknowledgement = asyncio.get_running_loop().create_future()
        self.acknowledgement.set_result({"t": "ack", "seq": seq})
        self.future = asyncio.get_running_loop().create_future()
        self.producer_error = None


class _MockConnection:
    def __init__(self, gateway):
        self.gateway = gateway
        self.robot_id = "ainekio-p4-test"
        self.epoch = 1
        self.model = "v2-12servo"
        self.features = ("walk_nominal_v1", "motion_targets_v1", "face_feedback_v1")
        self.pending: dict[int, _DummyPending] = {}
        self.body_command_sequence: int | None = None
        self.body_command: dict | None = None
        self.sent: list[dict] = []
        self._next_seq = 1
        self.latest_sample = 0

    def _owns_walk(self, seq: int) -> bool:
        return self.body_command_sequence == seq

    async def send_command(self, command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
        from protocol.control_v1 import validate_control_message

        seq = self._next_seq
        self._next_seq += 1
        msg = {**dict(command), "seq": seq}
        validate_control_message(msg)
        guard = on_sequence(seq) if on_sequence is not None else None
        if guard is not None:
            async with guard:
                pass
        if msg.get("t") == "walk_target":
            self.latest_sample = int(msg["sample"])
        elif msg.get("t") in ("stop", "motion_plan") or (
            msg.get("t") == "intent" and msg.get("name") not in ("face", "say")
        ):
            self.body_command_sequence = seq
            self.body_command = dict(msg)
        self.pending[seq] = _DummyPending(seq, msg)
        self.sent.append(msg)
        for cb in list(self.gateway._command_cbs):
            res = cb({"robot_id": self.robot_id, **msg})
            if asyncio.iscoroutine(res):
                await res
        return seq


class _MockGateway:
    def __init__(self):
        self._t = 10.0
        self.conn = _MockConnection(self)
        self._connections = {self.conn.robot_id: self.conn}
        self._event_cbs = []
        self._command_cbs = []
        self.freestyle_recovery_state = None
        self.obs = _mock_folded_faulted_observation()

    def clock(self) -> float:
        self._t += 0.02
        return self._t

    def _connection(self, robot_id):
        return self.conn

    def subscribe_events(self, cb):
        self._event_cbs.append(cb)

    def unsubscribe_events(self, cb):
        if cb in self._event_cbs:
            self._event_cbs.remove(cb)

    def subscribe_commands(self, cb):
        self._command_cbs.append(cb)

    def unsubscribe_commands(self, cb):
        if cb in self._command_cbs:
            self._command_cbs.remove(cb)

    async def status_snapshot(self):
        return {
            "robots": {
                self.conn.robot_id: {
                    "connected": True,
                    "epoch": 1,
                    "model": "v2-12servo",
                    "features": list(self.conn.features),
                    "body_command": self.conn.body_command,
                    "body_command_sequence": self.conn.body_command_sequence,
                    "calibration": {
                        "joints": [
                            {
                                "id": i,
                                "home_cd": round(STAND_ANGLES_DEG[i] * 100),
                                "home_us": 1500,
                                "pulse_us": 1500,
                                "us_per_degree": 10.0,
                                "invert": False,
                            }
                            for i in range(12)
                        ]
                    },
                    "motion_speed": {"joint_speed_limit_deg_s": 545.45},
                    "status": {"imu": self.obs["imu"]},
                }
            }
        }

    def body_sensor_observation(self, robot_id: str) -> dict:
        self.obs["feedback"]["device_us"] += 20_000
        self.obs["imu"]["motion"] = {"sequence": self.conn.body_command_sequence, "nominal_sample": self.conn.latest_sample}
        return self.obs

    async def queue_intent(self, name: str, params=None, *, robot_id=None, on_sequence=None, **kw):
        cmd = {"t": "intent", "name": name, **(params or {})}
        return await self.conn.send_command(cmd, received_at=self.clock(), on_sequence=on_sequence)

    async def estop(self, *, robot_id=None, detach=False, on_sequence=None, **kw):
        cmd = {"t": "stop", **({"detach": True} if detach else {})}
        return await self.conn.send_command(cmd, received_at=self.clock(), on_sequence=on_sequence)

    async def wait_terminal(self, seq: int, *, robot_id=None, epoch=None, timeout=None):
        return {"t": "ack", "seq": seq}


class _MockTransport:
    async def request(self, robot, kind, payload):
        return {"device_us": 1_000_000, "scan_us": 1_000_000, "enabled": True, "joints": []}

    async def close(self):
        pass


class _DummyActor:
    foot_scale_mm = POSE_FOOT_SCALE_MM

    def infer_feet_mm(self, obs_vec):
        assert len(obs_vec) == POSE_OBS_SIZE
        act = [0.0] * 12
        return act, pose_foot_offsets(act, self.foot_scale_mm)


class _DummyRuntime(NeuralPoseRuntime):
    def __init__(self):
        super().__init__()
        self._m = PoseManifold(device="cpu")
        self._a = _DummyActor()

    def load(self):
        return self._a, self._m


class BridgeNeuralPoseLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_streams_50hz_targets_and_holds_final_posture(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()

        async def fake_gen(endpoint, req, **kw):
            return {
                "program": [
                    {"name": "face", "arguments": {"expr": "excited"}},
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": ["front_right_carrier", "front_right_crank"],
                            "reference": "absolute",
                            "angles_deg": [45.0, 20.0],
                            "speed_pct": 80,
                        },
                    },
                    {
                        "name": "oscillate",
                        "arguments": {
                            "joints": ["front_right_shoulder"],
                            "reference": "absolute",
                            "center_deg": [0.0],
                            "amplitude_deg": [18.0],
                            "hz": 2.0,
                            "cycles": 1.0,
                            "speed_pct": 80,
                        },
                    },
                ]
            }

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "wave front right paw", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")

            walk_starts = [c for c in gw.conn.sent if c.get("t") == "intent" and c.get("name") == "walk"]
            walk_targets = [c for c in gw.conn.sent if c.get("t") == "walk_target"]
            faces = [c for c in gw.conn.sent if c.get("t") == "intent" and c.get("name") == "face"]
            stops = [c for c in gw.conn.sent if c.get("t") == "stop"]

            self.assertEqual(len(walk_starts), 1)
            self.assertEqual(walk_starts[0]["source"], "host")
            self.assertGreaterEqual(len(walk_targets), 20)
            self.assertEqual(len(faces), 2)  # acquire + release
            self.assertEqual(len(stops), 1)  # final posture hold
            self.assertNotIn("detach", stops[0])

            # Held neural posture retains recovery ownership until an operator Stop arrives
            job = bridge.jobs[sub["job_id"]]
            snap = (await gw.status_snapshot())["robots"][gw.conn.robot_id]
            self.assertTrue(recovery_has_motion_owner(snap, job))

            # Operator manual Stop clears recovery ownership
            await gw.estop(robot_id=gw.conn.robot_id)
            snap_after = (await gw.status_snapshot())["robots"][gw.conn.robot_id]
            self.assertFalse(recovery_has_motion_owner(snap_after, job))
        finally:
            await bridge.close()

    async def test_bridge_stops_host_stream_when_midstream_error_occurs(self):
        gw = _MockGateway()

        class _ExplodingActor(_DummyActor):
            def __init__(self):
                self.calls = 0

            def infer_feet_mm(self, obs_vec):
                self.calls += 1
                if self.calls >= 2:
                    raise RuntimeError("simulated midstream policy fault")
                return super().infer_feet_mm(obs_vec)

        runtime = _DummyRuntime()
        runtime._a = _ExplodingActor()

        async def fake_gen(endpoint, req, **kw):
            return {"program": [{"name": "stand", "arguments": {}}]}

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "stand up", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "error")
            self.assertIn("simulated midstream policy fault", res["error"])
            # Must have stopped the open-ended host walk so the P4 does not stay armed at reference_cd
            self.assertIsNotNone(gw.conn.body_command)
            self.assertEqual(gw.conn.body_command["t"], "stop")
        finally:
            await bridge.close()


def run_mujoco_qualification(policy_path: Path) -> dict:
    """Evaluate the trained (512, 256, 128) policy.onnx in authoritative 500 Hz GaitEnvironment."""
    from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
    from experiments.freestyle.neural_pose.mdp import full_four_bar_qpos20
    import experiments.freestyle.freestyle_curriculum as fc

    actor = NeuralPoseActor(policy_path)
    env_json = policy_path.parent / "environment.json"
    manifold = PoseManifold(env_json, device="cpu") if env_json.exists() else PoseManifold(device="cpu")
    cfg = replace(
        EnvironmentConfig(**vars(manifold.env_config)),
        collision_profile="locomotion",
        balance_enabled=False,
        heading_feedback_enabled=False,
        control_hz=50,
        physics_hz=500,
        foot_action_scale_mm=list(POSE_FOOT_SCALE_MM),
        randomization=0.0,
    )
    sim = GaitEnvironment(cfg, include_assembly=True, include_visuals=False)
    total_mass = float(sim.model.body_subtreemass[1])
    joint_qpos_adrs = [int(sim.model.jnt_qposadr[sim.model.joint(j).id]) for j in JOINTS]
    act_ids = [int(sim.model.actuator(j).id) for j in JOINTS]

    def _run_scenario(
        name: str,
        init_deg: list[float],
        program: list[dict],
        *,
        suspended: bool = False,
        faulted_joints: set[int] = frozenset(),
        push_at_s: float | None = None,
        cmd_delay_ticks: int = 0,
        obs_delay_ticks: int = 0,
        servo_kp_scale: float = 1.0,
        adc_vel_spikes: bool = False,
    ) -> dict:
        from collections import deque

        sim.reset(seed=42)
        rng = np.random.default_rng(1234)
        base_kp = float(cfg.servo_kp) * float(servo_kp_scale)
        base_kd = float(cfg.servo_kd)
        for act_id in act_ids:
            sim.model.actuator_gainprm[act_id, 0] = base_kp
            sim.model.actuator_biasprm[act_id, 1] = -base_kp
            sim.model.actuator_biasprm[act_id, 2] = -base_kd
        init_proj_deg, init_foot = manifold.project_angles_deg(init_deg)
        q20 = full_four_bar_qpos20(
            manifold.body,
            torch.tensor(init_proj_deg, dtype=torch.float64).reshape(1, 4, 3) * (math.pi / 180.0),
        )[0].numpy()

        # Write all 20 four-bar joints into MuJoCo
        for j_i in range(1, sim.model.njnt):
            pass
        # Map 20 joints by exact joint name order in full_four_bar_qpos20
        legs = ("rear_left", "rear_right", "front_left", "front_right")
        axes5 = ("shoulder", "carrier", "pickup", "crank", "rod")
        idx20 = 0
        for leg in legs:
            for ax in axes5:
                jid = sim.model.joint(f"{leg}_{ax}").id
                sim.data.qpos[sim.model.jnt_qposadr[jid]] = float(q20[idx20])
                idx20 += 1

        pts, _ = manifold.body.forward(
            torch.tensor(init_proj_deg, dtype=torch.float64).reshape(1, 4, 3) * (math.pi / 180.0)
        )
        lowest_z_m = float(pts[0, :, 2].min().item()) * 1e-3
        sim.data.qpos[0] = 0.0
        sim.data.qpos[1] = 0.0
        sim.data.qpos[2] = 0.28 if suspended else max(0.055, -lowest_z_m + 0.018)
        sim.data.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
        sim.data.qvel[:] = 0.0
        import mujoco

        mujoco.mj_forward(sim.model, sim.data)
        sim.commanded_deg = np.asarray(init_proj_deg, dtype=np.float64)

        obs_dict = {
            "joints": {
                JOINTS[i]: {
                    "home_deg": STAND_ANGLES_DEG[i],
                    "filtered_model_deg": init_proj_deg[i],
                    "commanded_model_deg": init_proj_deg[i],
                    "feedback_usable": i not in faulted_joints,
                }
                for i in range(12)
            },
            "joint_speed_limit_deg_s": 545.45,
        }
        segments = compile_goal_segments(program, obs_dict, manifold)
        history = PoseObservationHistory()
        prev_action = list(init_foot)

        t_sim = 0.0
        pushed = False
        min_up_cos = 1.0
        seg_errors_deg = []
        hold_cmd_p2p_list = []
        hold_joint_p2p_list = []
        infer_ms = []

        init_q_rad = torch.tensor(init_proj_deg, dtype=torch.float64).reshape(1, 12) * (math.pi / 180.0)
        _, init_phys_rad = manifold.body.pwm(init_q_rad)
        init_ctrl = init_phys_rad[0].numpy().copy()
        cmd_queue = deque([init_ctrl.copy() for _ in range(cmd_delay_ticks + 1)], maxlen=cmd_delay_ticks + 1)

        filt_q_deg = np.asarray(init_proj_deg, dtype=np.float64).copy()
        init_pkt = (
            list(init_proj_deg),
            [0.0] * 12,
            list(init_proj_deg),
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 9.81],
        )
        obs_queue = deque([init_pkt for _ in range(obs_delay_ticks + 1)], maxlen=obs_delay_ticks + 1)
        held_pkt = init_pkt

        hold_goal_deg = list(init_proj_deg)
        hold_goal_foot = list(init_foot)
        hold_support = manifold.infer_leg_support(hold_goal_deg)

        import time

        for seg in segments:
            if seg["kind"] not in ("pose_goal", "oscillate_goal", "hold"):
                continue
            dur = seg["seconds"] if seg["kind"] == "hold" else seg["duration_s"]
            steps = max(1, int(round(dur * 50)))
            seg_cmd_trace = []
            seg_joint_trace = []
            for s_i in range(steps):
                t_seg = s_i * 0.02
                if seg["kind"] == "pose_goal":
                    g_deg, g_foot, sup, spd = (
                        seg["goal_deg"],
                        seg["goal_foot_norm"],
                        seg["leg_support"],
                        seg["speed_scale"],
                    )
                elif seg["kind"] == "oscillate_goal":
                    osc_dur = seg["cycles"] / seg["hz"]
                    if t_seg < osc_dur:
                        cand = list(seg["base_deg"])
                        ph = 2.0 * math.pi * seg["hz"] * t_seg
                        for j_idx, c_deg, a_deg in zip(
                            seg["joint_indices"], seg["centers_deg"], seg["amplitudes_deg"]
                        ):
                            cand[j_idx] = c_deg + a_deg * math.sin(ph)
                        g_deg, g_foot = manifold.project_angles_deg(cand)
                    else:
                        g_deg = seg["end_deg"]
                        _, g_foot = manifold.project_angles_deg(g_deg)
                    sup, spd = seg["leg_support"], seg["speed_scale"]
                else:
                    g_deg, g_foot = hold_goal_deg, hold_goal_foot
                    sup, spd = hold_support, 0.5

                # Read sensors from GaitEnvironment (with optional One-Euro filter + Wi-Fi/ADC transport delay)
                true_q_deg = [float(sim.data.qpos[a] * 180.0 / math.pi) for a in joint_qpos_adrs]
                true_v_deg = [
                    float(sim.data.qvel[sim.model.jnt_dofadr[sim.model.joint(j).id]] * 180.0 / math.pi)
                    for j in JOINTS
                ]
                if obs_delay_ticks > 0:
                    prev_filt = filt_q_deg.copy()
                    filt_q_deg = prev_filt + 0.24 * (np.asarray(true_q_deg) - prev_filt)
                    vel_est = ((filt_q_deg - prev_filt) / 0.02).tolist()
                    if adc_vel_spikes:
                        for j_i in range(12):
                            if rng.random() < 0.05:
                                vel_est[j_i] += float(rng.choice([-1.0, 1.0]) * rng.uniform(25.0, 110.0))
                    p4_cmd_now = (cmd_queue[0] * (180.0 / math.pi)).tolist()
                    obs_queue.append(
                        (
                            filt_q_deg.tolist(),
                            vel_est,
                            p4_cmd_now,
                            sim.data.qpos[3:7].tolist(),
                            sim.data.sensor("gyro").data.tolist(),
                            sim.data.sensor("accel").data.tolist(),
                        )
                    )
                    arrived = obs_queue[0]
                    if rng.random() >= 0.20:
                        held_pkt = arrived
                    q_obs, v_obs, cmd_deg, quat, gyro, accel = held_pkt
                else:
                    q_obs = true_q_deg
                    v_obs = true_v_deg
                    cmd_deg = sim.commanded_deg.tolist()
                    quat = sim.data.qpos[3:7].tolist()
                    gyro = sim.data.sensor("gyro").data.tolist()
                    accel = sim.data.sensor("accel").data.tolist()

                usable = [i not in faulted_joints for i in range(12)]
                meas = [999.0 if not usable[i] else q_obs[i] for i in range(12)]

                feat = assemble_pose_features(
                    measured_deg=meas,
                    commanded_deg=cmd_deg,
                    velocity_deg_s=v_obs,
                    usable_flags=usable,
                    orientation_wxyz=quat,
                    angular_rate_rad_s=gyro,
                    acceleration_m_s2=accel,
                    goal_joint_deg=g_deg,
                    goal_foot_norm=g_foot,
                    leg_support=sup,
                    speed_scale=spd,
                    previous_action=prev_action,
                )
                obs_1290 = history.push_and_project(t_sim + 0.02, feat)
                t0 = time.perf_counter()
                act, _ = actor.infer_feet_mm(obs_1290)
                infer_ms.append((time.perf_counter() - t0) * 1000.0)

                q_log_prev = torch.tensor(sim.commanded_deg, dtype=torch.float64).reshape(1, 12) * (math.pi / 180.0)
                q_log_next, prev_action, _ = manifold.step_host_command(act, q_log_prev, speed_scale=spd)
                _, q_phys_next = manifold.body.pwm(q_log_next)
                sim.commanded_deg = (q_log_next[0] * (180.0 / math.pi)).numpy()
                cmd_queue.append(q_phys_next[0].numpy().copy())
                ctrl_rad = cmd_queue[0]
                seg_cmd_trace.append(sim.commanded_deg.copy())
                seg_joint_trace.append(np.asarray(true_q_deg, dtype=np.float64))

                if push_at_s is not None and not pushed and t_sim >= push_at_s:
                    sim.data.qvel[0] += 0.16
                    sim.data.qvel[1] -= 0.14
                    pushed = True

                torso_id = sim.model.body("torso").id
                for _ in range(10):
                    if suspended:
                        pos = sim.data.qpos[:3]
                        vel = sim.data.qvel[:3]
                        qw, qx, qy, qz = sim.data.qpos[3:7]
                        ang_v = sim.data.qvel[3:6]
                        f = np.array(
                            [
                                22.0 * (0.0 - pos[0]) - 4.5 * vel[0],
                                22.0 * (0.0 - pos[1]) - 4.5 * vel[1],
                                total_mass * 9.81 + 45.0 * (0.28 - pos[2]) - 6.5 * vel[2],
                            ]
                        )
                        zwx = 2.0 * (qx * qz + qw * qy)
                        zwy = 2.0 * (qy * qz - qw * qx)
                        tau = np.array([0.65 * zwy, -0.65 * zwx, 0.0]) - 0.06 * ang_v
                        sim.data.xfrc_applied[torso_id, :3] = f
                        sim.data.xfrc_applied[torso_id, 3:6] = tau
                    else:
                        sim.data.xfrc_applied[torso_id, :] = 0.0

                    # Apply MG90S torque-speed envelope + position target by exact joint actuator ID
                    for c_i, j_name in enumerate(JOINTS):
                        act_id = act_ids[c_i]
                        dof = sim.model.jnt_dofadr[sim.model.joint(j_name).id]
                        v_r = sim.data.qvel[dof]
                        spd_lim = math.radians(cfg.motor_no_load_speed_deg_s)
                        lo = -cfg.torque_nm * max(0.0, min(1.0, 1.0 + v_r / spd_lim))
                        hi = cfg.torque_nm * max(0.0, min(1.0, 1.0 - v_r / spd_lim))
                        sim.model.actuator_forcerange[act_id, 0] = lo
                        sim.model.actuator_forcerange[act_id, 1] = hi
                        sim.data.ctrl[act_id] = float(ctrl_rad[c_i])
                    mujoco.mj_step(sim.model, sim.data)
                    t_sim += 0.002

                pg = projected_gravity_from_wxyz(sim.data.qpos[3:7])
                min_up_cos = min(min_up_cos, -pg[2])

            end_q_deg = [float(sim.data.qpos[a] * 180.0 / math.pi) for a in joint_qpos_adrs]
            if seg["kind"] == "pose_goal":
                target_deg = seg["goal_deg"]
                hold_goal_deg, hold_goal_foot, hold_support = (
                    seg["goal_deg"],
                    seg["goal_foot_norm"],
                    seg["leg_support"],
                )
            elif seg["kind"] == "oscillate_goal":
                target_deg = seg["end_deg"]
                _, end_foot = manifold.project_angles_deg(target_deg)
                hold_goal_deg, hold_goal_foot, hold_support = target_deg, end_foot, seg["leg_support"]
            else:
                target_deg = hold_goal_deg
            mae = sum(abs(a - b) for a, b in zip(end_q_deg, target_deg)) / 12.0
            seg_errors_deg.append(round(mae, 2))
            if seg["kind"] == "hold" and len(seg_cmd_trace) >= 20:
                tail_cmd = np.stack(seg_cmd_trace[-25:], axis=0)
                tail_jnt = np.stack(seg_joint_trace[-25:], axis=0)
                hold_cmd_p2p_list.append(float(np.max(np.ptp(tail_cmd, axis=0))))
                hold_joint_p2p_list.append(float(np.max(np.ptp(tail_jnt, axis=0))))

        return {
            "scenario": name,
            "suspended": suspended,
            "upright_min_cos": round(min_up_cos, 3),
            "fell_over": (not suspended) and (min_up_cos < 0.45),
            "segment_end_mae_deg": seg_errors_deg,
            "mean_end_mae_deg": round(sum(seg_errors_deg) / max(1, len(seg_errors_deg)), 2),
            "hold_cmd_p2p_deg": round(max(hold_cmd_p2p_list), 2) if hold_cmd_p2p_list else None,
            "hold_joint_p2p_deg": round(max(hold_joint_p2p_list), 2) if hold_joint_p2p_list else None,
            "mean_infer_ms": round(sum(infer_ms) / max(1, len(infer_ms)), 3),
        }

    try:
        folded_start = [-2.2, -44.61, -58.6, 2.1, -41.07, -55.2, -2.9, 16.8, -70.5, -0.7, 19.4, -96.7]
        results = [
            _run_scenario(
                "suspended_folded_faulted_multi_leg_choreo",
                folded_start,
                [
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "reference": "absolute",
                            "angles_deg": [0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 0.0, 44.0, 12.0],
                            "speed_pct": 80,
                        },
                    },
                    {"name": "stand", "arguments": {}},
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": ["front_left_carrier", "front_left_crank"],
                            "reference": "absolute",
                            "angles_deg": [44.0, 12.0],
                            "speed_pct": 80,
                        },
                    },
                    {
                        "name": "oscillate",
                        "arguments": {
                            "joints": ["front_left_shoulder"],
                            "reference": "absolute",
                            "center_deg": [0.0],
                            "amplitude_deg": [22.0],
                            "hz": 1.6,
                            "cycles": 2.0,
                            "speed_pct": 80,
                        },
                    },
                    {"name": "stand", "arguments": {}},
                ],
                suspended=True,
                faulted_joints={1, 4},
            ),
            _run_scenario(
                "grounded_3leg_high_wave_and_stand",
                list(STAND_ANGLES_DEG),
                [
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "reference": "absolute",
                            "angles_deg": [-4.0, -6.0, -24.0, 6.0, -4.0, -22.0, 6.0, 4.0, -22.0, 12.0, 56.0, 36.0],
                            "speed_pct": 75,
                        },
                    },
                    {
                        "name": "oscillate",
                        "arguments": {
                            "joints": ["front_right_shoulder"],
                            "reference": "absolute",
                            "center_deg": [0.0],
                            "amplitude_deg": [18.0],
                            "hz": 1.8,
                            "cycles": 2.0,
                            "speed_pct": 80,
                        },
                    },
                    {"name": "stand", "arguments": {}},
                ],
                suspended=False,
            ),
            _run_scenario(
                "grounded_seated_two_paw_mime",
                list(STAND_ANGLES_DEG),
                [
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "reference": "absolute",
                            "angles_deg": [0.0, 23.24, 7.15, 0.0, 23.24, 7.15, 8.0, 48.0, 22.0, -8.0, 48.0, 22.0],
                            "speed_pct": 70,
                        },
                    },
                    {
                        "name": "oscillate",
                        "arguments": {
                            "joints": ["front_left_crank", "front_right_crank"],
                            "reference": "absolute",
                            "center_deg": [18.0, 18.0],
                            "amplitude_deg": [20.0, -20.0],
                            "hz": 1.8,
                            "cycles": 2.0,
                            "speed_pct": 80,
                        },
                    },
                    {"name": "stand", "arguments": {}},
                ],
                suspended=False,
            ),
            _run_scenario(
                "grounded_folded_rise_and_push_recovery",
                list(fc.REST_ANGLES),
                [
                    {"name": "stand", "arguments": {}},
                    {"name": "hold", "arguments": {"seconds": 1.2}},
                ],
                suspended=False,
                push_at_s=1.0,
            ),
            _run_scenario(
                "wifi_180ms_delayed_stand_hold",
                [9.1, -25.4, -30.9, 0.8, -23.4, -17.4, 27.3, -25.6, -16.6, 2.3, 18.8, -6.9],
                [
                    {"name": "stand", "arguments": {}},
                    {"name": "hold", "arguments": {"seconds": 1.4}},
                ],
                suspended=False,
                cmd_delay_ticks=3,
                obs_delay_ticks=5,
                servo_kp_scale=1.8,
                adc_vel_spikes=True,
            ),
            _run_scenario(
                "wifi_180ms_delayed_lift_right_front_leg",
                list(STAND_ANGLES_DEG),
                [
                    {
                        "name": "body",
                        "arguments": {
                            "translation_mm": [-4.0, 8.0, 0.0],
                            "rotation_deg": [-2.0, -2.0, 0.0],
                            "legs": ["front_right"],
                            "foot_offsets_mm": [[16.0, -12.0, 44.0]],
                            "speed_pct": 75,
                        },
                    },
                    {"name": "hold", "arguments": {"seconds": 1.2}},
                    {"name": "stand", "arguments": {}},
                    {"name": "hold", "arguments": {"seconds": 1.0}},
                ],
                suspended=False,
                cmd_delay_ticks=3,
                obs_delay_ticks=5,
                servo_kp_scale=1.8,
                adc_vel_spikes=True,
            ),
        ]
        return {"policy": str(policy_path), "scenarios": results}
    finally:
        sim.close()


class ClosedLoopPolicyQualificationTests(unittest.TestCase):
    def test_active_policy_in_mujoco_if_present(self):
        import importlib.util

        policy = resolve_active_policy_path()
        if policy is None:
            self.skipTest("No active neural pose policy symlinked yet")
        # Always verify ONNX runtime load & deterministic inference in every venv (including live gateway venv)
        rt = NeuralPoseRuntime()
        loaded = rt.load()
        self.assertIsNotNone(loaded)
        actor, manifold = loaded
        act, feet_mm = actor.infer_feet_mm([0.0] * POSE_OBS_SIZE)
        self.assertEqual(len(act), 12)
        self.assertEqual(len(feet_mm), 12)
        self.assertTrue(all(isinstance(v, float) and math.isfinite(v) for v in feet_mm))
        from protocol.control_v1 import validate_control_message

        validate_control_message(
            {
                "t": "walk_target",
                "seq": 2,
                "walk": 1,
                "sample": 1,
                "geometry": manifold.geometry_id,
                "feet_mm": feet_mm,
            }
        )
        if importlib.util.find_spec("gymnasium") is None or importlib.util.find_spec("mujoco") is None:
            self.skipTest("MuJoCo physics qualification runs in microduck-training-env")
        report = run_mujoco_qualification(policy)
        for item in report["scenarios"]:
            self.assertFalse(item["fell_over"], f"Scenario {item['scenario']} tipped over: {item}")
            self.assertLess(item["mean_end_mae_deg"], 14.0, f"Scenario {item['scenario']} poor tracking: {item}")
            self.assertLess(item["mean_infer_ms"], 5.0)
            if item.get("hold_cmd_p2p_deg") is not None and "wifi_180ms_delayed" in item["scenario"]:
                self.assertLess(
                    item["hold_cmd_p2p_deg"],
                    6.0,
                    f"Scenario {item['scenario']} oscillated commands under 180 ms Wi-Fi lag: {item}",
                )
                self.assertLess(
                    item["hold_joint_p2p_deg"],
                    6.0,
                    f"Scenario {item['scenario']} oscillated joints under 180 ms Wi-Fi lag: {item}",
                )


if __name__ == "__main__":
    if "--qualify" in sys.argv:
        idx = sys.argv.index("--qualify")
        p = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else resolve_active_policy_path()
        if p is None:
            raise SystemExit("Specify a policy.onnx path")
        out = run_mujoco_qualification(p)
        print(json.dumps(out, indent=2))
    else:
        unittest.main()
