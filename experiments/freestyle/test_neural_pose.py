"""Unit, lifecycle, and closed-loop 50 Hz MuJoCo qualification tests for Neural Pose & Emote."""
from __future__ import annotations

import asyncio
import copy
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
    pose_mirror_tables,
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

    def test_pose_mirror_tables_match_four_bar_sagittal_reflection(self):
        obs_p, obs_s, act_p, act_s = pose_mirror_tables()
        self.assertEqual(len(obs_p), POSE_OBS_SIZE)
        self.assertEqual(len(obs_s), POSE_OBS_SIZE)
        self.assertEqual(len(act_p), 12)
        self.assertEqual(len(act_s), 12)
        # Involution: mirroring twice returns the exact original observation and action
        rng = np.random.default_rng(17)
        x = rng.standard_normal(POSE_OBS_SIZE)
        x_m = x[obs_p] * np.asarray(obs_s)
        np.testing.assert_allclose(x_m[obs_p] * np.asarray(obs_s), x, atol=1e-7)

        # Asymmetric 4-leg pose mirrors RL<->RR and FL<->FR with dy negated in foot_norm
        asym_deg = [12.0, 20.0, -10.0, -5.0, -8.0, -25.0, 18.0, 50.0, 30.0, -7.0, 10.0, -15.0]
        q_a, f_a = self.manifold.project_angles_deg(asym_deg)
        mir_deg = q_a[3:6] + q_a[0:3] + q_a[9:12] + q_a[6:9]
        _, f_b = self.manifold.project_angles_deg(mir_deg)
        f_a_mir = (np.asarray(f_a)[act_p] * np.asarray(act_s)).tolist()
        for a, b in zip(f_b, f_a_mir):
            self.assertAlmostEqual(a, b, places=4)

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
        self.assertGreaterEqual(segs[1]["duration_s"], 0.32)
        self.assertLess(segs[1]["duration_s"], 0.90)

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

    async def test_early_settle_tolerates_stance_balance_residual_and_adc_velocity_noise(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)
        lift_op = {
            "name": "feet",
            "arguments": {"legs": ["front_right"], "offsets_mm": [[20.0, -22.0, 56.0]], "speed_pct": 35},
        }
        goal_deg, _ = manifold.project_angles_deg(manifold.resolve_spatial_deg(lift_op, stand_proj))

        # Standing start with usable feedback across all 12 joints
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": stand_proj[i],
                "filtered_model_deg": stand_proj[i],
                "commanded_model_deg": stand_proj[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.02, -0.01, 0.01]

        tick_counter = {"n": 0}
        orig_obs = gw.body_sensor_observation

        def live_obs(robot_id: str) -> dict:
            obs = orig_obs(robot_id)
            tick_counter["n"] += 1
            # Converge lifted FR leg within 2.5 deg and hold 9.5 deg active balance residual on stance legs,
            # plus a synthetic 38 deg/s ADC mux velocity spike that previously blocked early-settle.
            frac = min(1.0, tick_counter["n"] / 8.0)
            for i, j in enumerate(JOINTS):
                leg_is_fr = (i // 3) == 1
                settled_target = goal_deg[i] + (2.2 if leg_is_fr else (9.5 if i % 3 == 2 else -4.0))
                val = stand_proj[i] + frac * (settled_target - stand_proj[i])
                obs["joints"][j]["filtered_model_deg"] = val
                obs["joints"][j]["model_deg"] = val
                obs["joints"][j]["velocity_deg_s"] = 38.0 if i == 0 else 4.0
            return obs

        gw.body_sensor_observation = live_obs

        async def fake_gen(endpoint, req, **kw):
            return {"program": [lift_op]}

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "lift right paw slowly", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            walk_targets = [c for c in gw.conn.sent if c.get("t") == "walk_target"]
            # Without early-settle, speed_pct=35 on ~57 deg crank travel waits ~0.90s (~45+ ticks);
            # with early-settle once converged (~0.38s), it finishes well under 30 ticks.
            self.assertLess(len(walk_targets), 30)
            self.assertGreaterEqual(len(walk_targets), 12)
        finally:
            await bridge.close()

    async def test_stand_arms_disarmed_faulted_body_and_waits_for_tight_symmetric_settle(self):
        gw = _MockGateway()
        gw.conn.last_status = {"output_armed": False, "output_fault": 1, "output_ready": False}
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)

        # Start asymmetric (`front_left_crank = -31.5` vs `front_right_crank = -13.9`, ~10.3 deg max error)
        asym_start = [11.2, -3.8, -27.7, -5.9, 0.8, -19.5, -8.0, -2.2, -31.5, -1.2, 5.0, -13.9]
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": asym_start[i],
                "filtered_model_deg": asym_start[i],
                "commanded_model_deg": asym_start[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.02, -0.01, 0.01]

        tick_counter = {"n": 0}
        orig_obs = gw.body_sensor_observation

        def live_obs(robot_id: str) -> dict:
            obs = orig_obs(robot_id)
            tick_counter["n"] += 1
            # Stay at ~10.2 deg error (which prematurely passed the old <= 13 deg check) until call 14,
            # then settle symmetrically within 1.5 deg of STAND_ANGLES_DEG.
            for i, j in enumerate(JOINTS):
                val = asym_start[i] if tick_counter["n"] < 14 else stand_proj[i] + (1.5 if i % 2 == 0 else -1.5)
                obs["joints"][j]["filtered_model_deg"] = val
                obs["joints"][j]["model_deg"] = val
            return obs

        gw.body_sensor_observation = live_obs

        async def fake_gen(endpoint, req, **kw):
            return {"program": [{"name": "stand", "arguments": {}}]}

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "stand", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            intents = [c["name"] for c in gw.conn.sent if c.get("t") == "intent"]
            self.assertEqual(intents[:2], ["stand", "walk"], "Disarmed/faulted body must arm via stand before walk stream")
            final_errs = [
                abs(gw.obs["joints"][j]["filtered_model_deg"] - stand_proj[i])
                for i, j in enumerate(JOINTS)
            ]
            self.assertLessEqual(max(final_errs), 5.0, "Stand must not exit prematurely while asymmetric error > 5 deg")
        finally:
            await bridge.close()

    async def test_stand_pose_after_stretch_waits_for_command_and_shoulder_convergence_before_stop(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, stand_foot = manifold.project_angles_deg(STAND_ANGLES_DEG)
        skewed_cmd = [7.65, -1.35, -21.11, -1.89, 3.42, -22.19, 0.90, 1.35, -21.20, -3.78, 6.75, -19.40]
        _, skewed_foot = manifold.project_angles_deg(skewed_cmd)
        stretched_start = [4.57, -12.17, -21.09, -9.33, -7.35, -20.28, -5.06, 93.55, 56.34, 2.38, 96.97, 56.19]

        class _TransientShoulderSkewActor(_DummyActor):
            def __init__(self):
                self.calls = 0

            def infer_feet_mm(self, obs_vec):
                assert len(obs_vec) == POSE_OBS_SIZE
                self.calls += 1
                # Reproduce 18:31 telemetry: policy holds +7.65 deg RL_shoulder command through 0.56 s (28 ticks)
                # before converging cleanly to stand_foot.
                act = list(skewed_foot if self.calls <= 28 else stand_foot)
                return act, pose_foot_offsets(act, self.foot_scale_mm)

        runtime._a = _TransientShoulderSkewActor()
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": stretched_start[i],
                "filtered_model_deg": stretched_start[i],
                "commanded_model_deg": stretched_start[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.01, -0.01, 0.01]
        gw.clock = lambda: gw._t
        orig_send = gw.conn.send_command
        phys_deg = list(stretched_start)

        async def sim_send_command(command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
            seq = await orig_send(command, received_at=received_at, on_sequence=on_sequence, **kwargs)
            if command.get("t") == "walk_target":
                gw._t += 0.020
                gw.obs["feedback"]["device_us"] += 20_000
                sent_norm = (
                    torch.tensor(command["feet_mm"], dtype=torch.float64).reshape(1, 12)
                    / manifold.body.scale.repeat(4)
                )
                cmd_deg = (manifold.body.decode(sent_norm)[0] * 180.0 / math.pi).tolist()
                for idx_j, name_j in enumerate(JOINTS):
                    prev_v = phys_deg[idx_j]
                    step = max(-8.0, min(8.0, cmd_deg[idx_j] - prev_v))
                    new_v = prev_v + step
                    phys_deg[idx_j] = new_v
                    gw.obs["joints"][name_j]["filtered_model_deg"] = new_v
                    gw.obs["joints"][name_j]["model_deg"] = new_v
                    gw.obs["joints"][name_j]["commanded_model_deg"] = cmd_deg[idx_j]
                    gw.obs["joints"][name_j]["velocity_deg_s"] = (new_v - prev_v) / 0.020
            return seq

        gw.conn.send_command = sim_send_command
        gw.body_sensor_observation = lambda robot_id: gw.obs

        async def fake_gen(endpoint, req, **kw):
            return {
                "program": [
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "reference": "absolute",
                            "angles_deg": list(STAND_ANGLES_DEG),
                            "speed_pct": 50,
                        },
                    },
                    {"name": "face", "arguments": {"expr": "stand"}},
                ]
            }

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "return to stand pose", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            # Must NOT freeze via `stop` while RL_shoulder command is still +7.65 deg at 0.52 s
            self.assertGreater(runtime._a.calls, 30)
            self.assertLessEqual(abs(gw.obs["joints"]["rear_left_shoulder"]["commanded_model_deg"]), 3.5)
            self.assertLessEqual(abs(gw.obs["joints"]["rear_left_shoulder"]["filtered_model_deg"]), 3.5)
            final_errs = [abs(phys_deg[i] - stand_proj[i]) for i in range(12)]
            self.assertLessEqual(max(final_errs), 5.0)
        finally:
            await bridge.close()

    async def test_blocked_joint_recoils_in_280ms_finishes_sequence_and_returns_to_ready_without_llm_retry(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)

        class _GoalTrackingActor(_DummyActor):
            def infer_feet_mm(self, obs_vec):
                assert len(obs_vec) == POSE_OBS_SIZE
                act = list(obs_vec[57:69])
                return act, pose_foot_offsets(act, self.foot_scale_mm)

        runtime._a = _GoalTrackingActor()

        # Seed standing posture with usable 4th-wire feedback on all 12 joints
        phys_deg = list(stand_proj)
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": phys_deg[i],
                "filtered_model_deg": phys_deg[i],
                "commanded_model_deg": phys_deg[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.01, -0.01, 0.01]

        # Pace clock strictly at 20 ms per 50 Hz host sample and simulate servo tracking + obstacles:
        # - front_right_carrier (idx 10) physically blocked at <= 15.0 deg (jams mid-program segment 0)
        # - front_left_carrier (idx 7) physically blocked at <= 12.0 deg (jams final segment 2)
        obstacles_max_deg = {10: 15.0, 7: 12.0}
        fr_carrier_trace: list[float] = []
        fl_carrier_trace: list[float] = []
        rl_shoulder_trace: list[float] = []

        gw.clock = lambda: gw._t
        orig_send = gw.conn.send_command

        async def sim_send_command(command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
            seq = await orig_send(command, received_at=received_at, on_sequence=on_sequence, **kwargs)
            if command.get("t") == "walk_target":
                gw._t += 0.020
                gw.obs["feedback"]["device_us"] += 20_000
                sent_norm = (
                    torch.tensor(command["feet_mm"], dtype=torch.float64).reshape(1, 12)
                    / manifold.body.scale.repeat(4)
                )
                cmd_deg = (manifold.body.decode(sent_norm)[0] * 180.0 / math.pi).tolist()
                for idx_j, name_j in enumerate(JOINTS):
                    prev_v = phys_deg[idx_j]
                    desired_v = cmd_deg[idx_j]
                    if idx_j in obstacles_max_deg:
                        desired_v = min(desired_v, obstacles_max_deg[idx_j])
                    # Servo slews toward desired_v up to 8 deg/tick
                    step = max(-8.0, min(8.0, desired_v - prev_v))
                    new_v = prev_v + step
                    phys_deg[idx_j] = new_v
                    gw.obs["joints"][name_j]["filtered_model_deg"] = new_v
                    gw.obs["joints"][name_j]["model_deg"] = new_v
                    gw.obs["joints"][name_j]["commanded_model_deg"] = cmd_deg[idx_j]
                    gw.obs["joints"][name_j]["velocity_deg_s"] = (new_v - prev_v) / 0.020
                fr_carrier_trace.append(phys_deg[10])
                fl_carrier_trace.append(phys_deg[7])
                rl_shoulder_trace.append(phys_deg[0])
            return seq

        gw.conn.send_command = sim_send_command
        gw.body_sensor_observation = lambda robot_id: gw.obs

        gen_calls: list[dict] = []

        async def fake_gen(endpoint, req, **kw):
            gen_calls.append(req)
            return {
                "program": [
                    {
                        "name": "move",
                        "arguments": {
                            "joint": "front_right_carrier",
                            "reference": "absolute",
                            "angle_deg": 35.0,
                            "speed_pct": 60,
                        },
                    },
                    {
                        "name": "move",
                        "arguments": {
                            "joint": "rear_left_shoulder",
                            "reference": "absolute",
                            "angle_deg": 12.0,
                            "speed_pct": 75,
                        },
                    },
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": ["rear_left_shoulder", "front_left_carrier"],
                            "reference": "absolute",
                            "angles_deg": [0.0, 32.0],
                            "speed_pct": 60,
                        },
                    },
                ]
            }

        class _ListRecorder:
            def __init__(self):
                self.events = []

            def status(self):
                return {"enabled": True}

            def record(self, kind, payload, **meta):
                self.events.append((kind, payload))

        rec = _ListRecorder()
        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, recorder=rec, neural_pose_runtime=runtime)
        try:
            await bridge.configure(gw.conn.robot_id, "http://127.0.0.1:8794", True)
            sub = await bridge.submit(gw.conn.robot_id, "lift right paw, sway, lift left paw", execute=True)
            # Even if P4 emits a non-releasing servo_stall notice, Bridge must NOT invoke LLM recovery
            await bridge.event(
                {
                    "robot_id": gw.conn.robot_id,
                    "epoch": 1,
                    "name": "body_event",
                    "data": {"kind": "servo_stall", "outputs_released": False, "joints": [{"id": 10}]},
                }
            )
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            self.assertEqual(len(gen_calls), 1, "Must never call freestyle-0.8b LLM for single-limb obstacle contact")

            recoils = [payload for kind, payload in rec.events if kind == "joint_recoil"]
            self.assertEqual(recoils, [], "Executor must never mutate cmd_q_rad or later segment goals via hardcoded joint_recoil")

            # Verify executor did NOT hijack/mutate goal_deg prematurely mid-segment
            first_hit_15 = next(i for i, v in enumerate(fr_carrier_trace) if abs(v - 15.0) < 0.05)
            self.assertGreaterEqual(len(fr_carrier_trace) - first_hit_15, 16)

            # Verify middle unblocked segment (rear_left_shoulder -> 12 deg) and final return (0 deg) executed cleanly
            self.assertGreater(max(rl_shoulder_trace), 10.5)
            self.assertLessEqual(abs(rl_shoulder_trace[-1]), 1.5)

            # Verify final-pose stall settled safely (~10.0 deg) without forcing an unwanted return to STAND_ANGLES_DEG
            ready_events = [kind for kind, _ in rec.events if kind in ("return_to_ready_started", "return_to_ready_completed")]
            self.assertEqual(ready_events, [])
            stops = [c for c in gw.conn.sent if c.get("t") == "stop"]
            self.assertEqual(len(stops), 1)
            self.assertNotIn("detach", stops[0])
        finally:
            await bridge.close()

    async def test_released_servo_stall_aborts_active_neural_pose_job_with_failed_error(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        entered = asyncio.Event()
        orig_obs = gw.body_sensor_observation

        def slow_obs(robot_id: str) -> dict:
            obs = orig_obs(robot_id)
            if gw.conn.latest_sample >= 2:
                entered.set()
            return obs

        gw.body_sensor_observation = slow_obs

        async def fake_gen(endpoint, req, **kw):
            return {"program": [{"name": "hold", "arguments": {"seconds": 5.0}}]}

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "long hold", execute=True)
            await asyncio.wait_for(entered.wait(), timeout=2.0)
            await bridge.event(
                {
                    "robot_id": gw.conn.robot_id,
                    "epoch": 1,
                    "name": "body_event",
                    "data": {
                        "kind": "servo_stall",
                        "outputs_released": True,
                        "command_sequence": gw.conn.body_command_sequence,
                        "joints": [{"id": 10, "name": "front_right_carrier"}],
                    },
                }
            )
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "error")
            self.assertIn("servo_stall", res["error"])
            self.assertTrue(res["error_evidence"]["outputs_released"])
        finally:
            await bridge.close()

    async def test_adaptive_neural_unloading_runs_uninterrupted_without_hardcoded_stand_handoff(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, stand_foot = manifold.project_angles_deg(STAND_ANGLES_DEG)
        splayed_start = [-38.0, 16.0, 12.0, 2.0, -22.0, -18.0, -3.0, 18.0, -14.0, -14.0, 0.0, -28.0]

        class _AdaptiveMicrostepActor(_DummyActor):
            def __init__(self):
                self.calls = 0

            def infer_feet_mm(self, obs_vec):
                assert len(obs_vec) == POSE_OBS_SIZE
                self.calls += 1
                # Simulate neural micro-step: first 24 ticks (0.48s > old 0.28s cutoff) lift Z on rear_left,
                # then swing to stand_foot.
                if self.calls <= 24:
                    lift_act = list(stand_foot)
                    lift_act[1] = 0.42
                    lift_act[2] = 0.28
                    return lift_act, pose_foot_offsets(lift_act, self.foot_scale_mm)
                return list(stand_foot), pose_foot_offsets(stand_foot, self.foot_scale_mm)

        runtime._a = _AdaptiveMicrostepActor()
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": splayed_start[i],
                "filtered_model_deg": splayed_start[i],
                "commanded_model_deg": splayed_start[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.clock = lambda: gw._t
        orig_send = gw.conn.send_command
        phys_deg = list(splayed_start)
        tick_n = {"n": 0}

        async def sim_send_command(command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
            seq = await orig_send(command, received_at=received_at, on_sequence=on_sequence, **kwargs)
            if command.get("t") == "walk_target":
                gw._t += 0.020
                gw.obs["feedback"]["device_us"] += 20_000
                tick_n["n"] += 1
                sent_norm = (
                    torch.tensor(command["feet_mm"], dtype=torch.float64).reshape(1, 12)
                    / manifold.body.scale.repeat(4)
                )
                cmd_deg = (manifold.body.decode(sent_norm)[0] * 180.0 / math.pi).tolist()
                for idx_j, name_j in enumerate(JOINTS):
                    prev_v = phys_deg[idx_j]
                    # Shoulder stays snagged at -38 deg for first 20 ticks (0.40s) until foot unloads Z, then tracks cleanly
                    if idx_j == 0 and tick_n["n"] <= 20:
                        new_v = -38.0
                    else:
                        step = max(-8.0, min(8.0, cmd_deg[idx_j] - prev_v))
                        new_v = prev_v + step
                    phys_deg[idx_j] = new_v
                    gw.obs["joints"][name_j]["filtered_model_deg"] = new_v
                    gw.obs["joints"][name_j]["model_deg"] = new_v
                    gw.obs["joints"][name_j]["commanded_model_deg"] = cmd_deg[idx_j]
                    gw.obs["joints"][name_j]["velocity_deg_s"] = (new_v - prev_v) / 0.020
            return seq

        gw.conn.send_command = sim_send_command
        gw.body_sensor_observation = lambda robot_id: gw.obs

        async def fake_gen(endpoint, req, **kw):
            return {
                "program": [
                    {"name": "body", "arguments": {"translation_mm": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "legs": [], "foot_offsets_mm": [], "speed_pct": 65}},
                    {"name": "face", "arguments": {"expr": "stand"}},
                ]
            }

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "center smoothly", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            stand_intents = [c for c in gw.conn.sent if c.get("t") == "intent" and c.get("name") == "stand"]
            self.assertEqual(stand_intents, [], "Must never interrupt 50 Hz neural policy with hardcoded stand intent")
            self.assertLessEqual(abs(gw.obs["joints"]["rear_left_shoulder"]["filtered_model_deg"] - stand_proj[0]), 3.5)
        finally:
            await bridge.close()

    async def test_stance_deflection_completes_program_without_synthetic_jam_or_replan(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": stand_proj[i],
                "filtered_model_deg": stand_proj[i],
                "commanded_model_deg": stand_proj[i],
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.01, -0.01, 0.01]
        gw.clock = lambda: gw._t
        orig_send = gw.conn.send_command

        async def sim_send_command(command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
            seq = await orig_send(command, received_at=received_at, on_sequence=on_sequence, **kwargs)
            if command.get("t") == "walk_target":
                gw._t += 0.020
                gw.obs["feedback"]["device_us"] += 20_000
                sent_norm = (
                    torch.tensor(command["feet_mm"], dtype=torch.float64).reshape(1, 12)
                    / manifold.body.scale.repeat(4)
                )
                cmd_deg = (manifold.body.decode(sent_norm)[0] * 180.0 / math.pi).tolist()
                for idx_j, name_j in enumerate(JOINTS):
                    # Deflect rear_left_shoulder and rear_right leg under static carpet friction
                    if idx_j in (0, 4, 5):
                        new_v = -18.5 if idx_j == 0 else STAND_ANGLES_DEG[idx_j]
                    else:
                        new_v = cmd_deg[idx_j]
                    prev_v = gw.obs["joints"][name_j]["filtered_model_deg"]
                    gw.obs["joints"][name_j]["filtered_model_deg"] = new_v
                    gw.obs["joints"][name_j]["model_deg"] = new_v
                    gw.obs["joints"][name_j]["commanded_model_deg"] = cmd_deg[idx_j]
                    gw.obs["joints"][name_j]["velocity_deg_s"] = (new_v - prev_v) / 0.020
            return seq

        gw.conn.send_command = sim_send_command
        gw.body_sensor_observation = lambda robot_id: gw.obs

        gen_requests = []

        async def fake_gen(endpoint, req, **kw):
            gen_requests.append(copy.deepcopy(req))
            return {
                "program": [
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "reference": "absolute",
                            "angles_deg": [0.0, -21.8, 19.98] * 4,
                            "speed_pct": 60,
                        },
                    },
                    {"name": "hold", "arguments": {"seconds": 0.4}},
                ]
            }

        class _GoalTrackingActor(_DummyActor):
            def infer_feet_mm(self, obs_vec):
                assert len(obs_vec) == POSE_OBS_SIZE
                goal_norm = list(obs_vec[57:69])
                return goal_norm, pose_foot_offsets(goal_norm, self.foot_scale_mm)

        runtime._a = _GoalTrackingActor()
        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            await bridge.configure(gw.conn.robot_id, "http://127.0.0.1:8794", False)
            sub = await bridge.submit(gw.conn.robot_id, "rest down", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            self.assertIsNone(res.get("error"))
            self.assertEqual(len(gen_requests), 1, "Must complete program directly without synthetic stance_transition_jam replan")
        finally:
            await bridge.close()

    async def test_adc_jitter_on_pinned_shoulder_recoils_cleanly_before_hold_and_refreshes_post_stand_start(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)

        # Cold-boot disarmed state with splayed RL shoulder (-32.75 deg) before native `stand` arms servos
        gw.conn.last_status = {"output_armed": False, "output_fault": 0, "imu": gw.obs["imu"]}
        phys_deg = list(stand_proj)
        phys_deg[0] = -32.75
        phys_deg[2] = 55.72
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": phys_deg[i],
                "filtered_model_deg": phys_deg[i],
                "commanded_model_deg": None,
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.01, -0.01, 0.01]
        gw.clock = lambda: gw._t
        orig_send = gw.conn.send_command
        tick_counter = {"n": 0}
        hold_rl_cmds: list[float] = []

        async def sim_send_command(command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
            seq = await orig_send(command, received_at=received_at, on_sequence=on_sequence, **kwargs)
            if (
                command.get("t") == "intent"
                and command.get("name") == "walk"
                and not gw.conn.last_status["output_armed"]
                and abs(phys_deg[2]) > 45.0
            ):
                # Mirror P4 body.c:1164 rejecting cold-boot walk when crank (+55.72 deg) is folded outside walk entry limits
                fut = asyncio.get_running_loop().create_future()
                fut.set_result({"t": "rejected", "seq": seq, "code": "reference"})
                gw.conn.pending[seq].acknowledgement = fut
                return seq
            if command.get("t") == "intent" and command.get("name") == "stand":
                # Native `stand` arms servos and settles RL shoulder at -16.45 deg under floor friction
                gw.conn.last_status["output_armed"] = True
                for i, j in enumerate(JOINTS):
                    phys_deg[i] = -16.45 if i == 0 else stand_proj[i]
                    gw.obs["joints"][j]["filtered_model_deg"] = phys_deg[i]
                    gw.obs["joints"][j]["model_deg"] = phys_deg[i]
                    gw.obs["joints"][j]["commanded_model_deg"] = phys_deg[i]
            elif command.get("t") == "walk_target":
                gw._t += 0.020
                gw.obs["feedback"]["device_us"] += 20_000
                tick_counter["n"] += 1
                sent_norm = (
                    torch.tensor(command["feet_mm"], dtype=torch.float64).reshape(1, 12)
                    / manifold.body.scale.repeat(4)
                )
                cmd_deg = (manifold.body.decode(sent_norm)[0] * 180.0 / math.pi).tolist()
                hold_rl_cmds.append(cmd_deg[0])
                for idx_j, name_j in enumerate(JOINTS):
                    prev_v = phys_deg[idx_j]
                    if idx_j == 0:
                        # Simulate carpet/load sag: RL shoulder settles 15 deg below cmd_deg with finite slew + ADC ripple
                        jitter = 0.25 if (tick_counter["n"] % 2 == 0) else -0.25
                        sag_target = cmd_deg[0] - 15.0
                        step0 = 0.0 if tick_counter["n"] == 1 else max(-4.0, min(4.0, sag_target - prev_v))
                        new_v = prev_v + step0 + (0.0 if tick_counter["n"] == 1 else jitter)
                    else:
                        step = max(-8.0, min(8.0, cmd_deg[idx_j] - prev_v))
                        new_v = prev_v + step
                    phys_deg[idx_j] = new_v
                    gw.obs["joints"][name_j]["filtered_model_deg"] = new_v
                    gw.obs["joints"][name_j]["model_deg"] = new_v
                    gw.obs["joints"][name_j]["commanded_model_deg"] = cmd_deg[idx_j]
                    gw.obs["joints"][name_j]["velocity_deg_s"] = (new_v - prev_v) / 0.020
            return seq

        gw.conn.send_command = sim_send_command
        gw.body_sensor_observation = lambda robot_id: gw.obs

        class _GoalTrackingActor(_DummyActor):
            def infer_feet_mm(self, obs_vec):
                assert len(obs_vec) == POSE_OBS_SIZE
                goal_norm = list(obs_vec[57:69])
                return goal_norm, pose_foot_offsets(goal_norm, self.foot_scale_mm)

        runtime._a = _GoalTrackingActor()

        async def fake_gen(endpoint, req, **kw):
            return {
                "program": [
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "angles_deg": list(STAND_ANGLES_DEG),
                            "reference": "absolute",
                            "speed_pct": 60,
                        },
                    },
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "angles_deg": [0.0, -16.0, -22.0, 0.0, -16.0, -22.0, 0.0, 40.0, 46.0, 0.0, 40.0, 46.0],
                            "reference": "absolute",
                            "speed_pct": 50,
                        },
                    },
                    {"name": "hold", "arguments": {"seconds": 0.4}},
                    {
                        "name": "pose",
                        "arguments": {
                            "joints": list(JOINTS),
                            "angles_deg": list(STAND_ANGLES_DEG),
                            "reference": "absolute",
                            "speed_pct": 60,
                        },
                    },
                    {"name": "hold", "arguments": {"seconds": 0.4}},
                ]
            }

        recorded_events: list[tuple[str, dict]] = []
        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        orig_record = bridge.record

        def spy_record(job, kind, payload, **kw):
            recorded_events.append((kind, payload))
            return orig_record(job, kind, payload, **kw)

        bridge.record = spy_record
        try:
            sub = await bridge.submit(gw.conn.robot_id, "Perform a whole-body stretch.", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            preps = [p for k, p in recorded_events if k == "motion_prepared"]
            self.assertAlmostEqual(
                preps[0]["start"]["rear_left_shoulder"],
                -16.45,
                delta=0.5,
                msg="motion_prepared start must reflect refreshed post-stand posture rather than stale cold-boot -32.75 deg",
            )
            # Across all 3 pose segments and 2 holds under 15 deg load sag, target and cmd_q_rad must NEVER ratchet negative!
            for p in preps:
                self.assertAlmostEqual(p["target"]["rear_left_shoulder"], 0.0, delta=0.5)
            recoils = [p for k, p in recorded_events if k == "joint_recoil"]
            self.assertEqual(recoils, [])
            self.assertGreaterEqual(
                min(hold_rl_cmds[-20:]),
                -1.5,
                msg="RL shoulder command must stay at commanded 0 deg target rather than ratcheting negative across segments",
            )
        finally:
            await bridge.close()

    async def test_cold_boot_in_range_arms_directly_into_50hz_neural_stream_without_legacy_stand(self):
        gw = _MockGateway()
        runtime = _DummyRuntime()
        manifold = runtime._m
        stand_proj, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)
        gw.conn.last_status = {"output_armed": False, "output_fault": 0, "imu": gw.obs["imu"]}
        phys_deg = list(stand_proj)
        phys_deg[0] = -16.3
        for i, j in enumerate(JOINTS):
            gw.obs["joints"][j] = {
                "home_deg": STAND_ANGLES_DEG[i],
                "model_deg": phys_deg[i],
                "filtered_model_deg": phys_deg[i],
                "commanded_model_deg": None,
                "velocity_deg_s": 0.0,
                "feedback_usable": True,
            }
        gw.obs["imu"]["angular_rate_rad_s"] = [0.01, -0.01, 0.01]
        gw.clock = lambda: gw._t
        orig_send = gw.conn.send_command

        async def sim_send_command(command: dict, *, received_at: float, on_sequence=None, **kwargs) -> int:
            seq = await orig_send(command, received_at=received_at, on_sequence=on_sequence, **kwargs)
            if command.get("t") == "intent" and command.get("name") == "walk":
                gw.conn.last_status["output_armed"] = True
            elif command.get("t") == "walk_target":
                gw._t += 0.020
                gw.obs["feedback"]["device_us"] += 20_000
                sent_norm = (
                    torch.tensor(command["feet_mm"], dtype=torch.float64).reshape(1, 12)
                    / manifold.body.scale.repeat(4)
                )
                cmd_deg = (manifold.body.decode(sent_norm)[0] * 180.0 / math.pi).tolist()
                for idx_j, name_j in enumerate(JOINTS):
                    prev_v = phys_deg[idx_j]
                    new_v = prev_v + max(-6.0, min(6.0, cmd_deg[idx_j] - prev_v))
                    phys_deg[idx_j] = new_v
                    gw.obs["joints"][name_j]["filtered_model_deg"] = new_v
                    gw.obs["joints"][name_j]["model_deg"] = new_v
                    gw.obs["joints"][name_j]["commanded_model_deg"] = cmd_deg[idx_j]
                    gw.obs["joints"][name_j]["velocity_deg_s"] = (new_v - prev_v) / 0.020
            return seq

        gw.conn.send_command = sim_send_command
        gw.body_sensor_observation = lambda robot_id: gw.obs

        class _GoalTrackingActor(_DummyActor):
            def infer_feet_mm(self, obs_vec):
                goal_norm = list(obs_vec[57:69])
                return goal_norm, pose_foot_offsets(goal_norm, self.foot_scale_mm)

        runtime._a = _GoalTrackingActor()

        async def fake_gen(endpoint, req, **kw):
            return {"program": [{"name": "stand", "arguments": {}}]}

        bridge = Bridge(gw, _MockTransport(), generate=fake_gen, neural_pose_runtime=runtime)
        try:
            sub = await bridge.submit(gw.conn.robot_id, "stand up", execute=True)
            res = await bridge.result(sub["job_id"])
            self.assertEqual(res["state"], "completed")
            stand_intents = [c for c in gw.conn.sent if c.get("t") == "intent" and c.get("name") == "stand"]
            self.assertEqual(stand_intents, [], "Cold boot in walk-entry range must arm directly into 50 Hz neural stream")
            self.assertLessEqual(abs(phys_deg[0] - stand_proj[0]), 2.0)
        finally:
            await bridge.close()

    def test_overhead_118deg_carrier_singularity_returns_smoothly_to_stand(self):
        """Regression for [0, 118, 55] deg overhead stretch crossing concave 4-bar toggle boundary on return to stand."""
        manifold = PoseManifold(device="cpu")
        cal_joints = [
            {"id": 0, "channel": 0, "home_us": 1760, "invert": False, "home_cd": 0, "us_per_degree": 11.111111},
            {"id": 1, "channel": 1, "home_us": 2750, "invert": True, "home_cd": -3087, "us_per_degree": 11.111111},
            {"id": 2, "channel": 2, "home_us": 2870, "invert": True, "home_cd": -11768, "us_per_degree": 11.111111},
            {"id": 3, "channel": 3, "home_us": 1650, "invert": True, "home_cd": 0, "us_per_degree": 11.111111},
            {"id": 4, "channel": 4, "home_us": 415, "invert": False, "home_cd": -3087, "us_per_degree": 11.111111},
            {"id": 5, "channel": 5, "home_us": 440, "invert": False, "home_cd": -11768, "us_per_degree": 11.111111},
            {"id": 6, "channel": 6, "home_us": 1650, "invert": True, "home_cd": 0, "us_per_degree": 11.111111},
            {"id": 7, "channel": 7, "home_us": 2740, "invert": True, "home_cd": -3087, "us_per_degree": 11.111111},
            {"id": 8, "channel": 8, "home_us": 2750, "invert": True, "home_cd": -11768, "us_per_degree": 11.111111},
            {"id": 9, "channel": 9, "home_us": 1700, "invert": False, "home_cd": 0, "us_per_degree": 11.111111},
            {"id": 10, "channel": 10, "home_us": 560, "invert": False, "home_cd": -3087, "us_per_degree": 11.111111},
            {"id": 11, "channel": 11, "home_us": 575, "invert": False, "home_cd": -11768, "us_per_degree": 11.111111},
        ]
        live_body = manifold.body_for_calibration(cal_joints)
        stand_proj, stand_foot = manifold.project_angles_deg(STAND_ANGLES_DEG, body=live_body)

        # 1. Direct step_host_command from [0, 118, 55] deg on all 4 legs -> stand_foot
        q_rad = torch.tensor([[0.0, 118.0, 55.0] * 4], dtype=torch.float64) * (math.pi / 180.0)
        prev_deg = [0.0, 118.0, 55.0] * 4
        max_single_step_deg = 0.0
        for _ in range(30):
            q_rad, _, _ = manifold.step_host_command(stand_foot, q_rad, speed_scale=0.5, body=live_body)
            cur_deg = [v * 180.0 / math.pi for v in q_rad[0].tolist()]
            max_single_step_deg = max(max_single_step_deg, max(abs(a - b) for a, b in zip(cur_deg, prev_deg)))
            prev_deg = cur_deg
        self.assertLessEqual(max_single_step_deg, 7.5, "Manifold step out of +118 deg must respect motor slew rate")
        for i in range(12):
            self.assertAlmostEqual(prev_deg[i], stand_proj[i], delta=1.0)

        # 2. Full closed-loop NeuralPoseActor trajectory from stretch [0, -16, -22, ..., 0, 118, 55] -> STAND_ANGLES
        policy_path = resolve_active_policy_path()
        if policy_path is not None and policy_path.exists():
            actor = NeuralPoseActor(policy_path)
            hist = PoseObservationHistory()
            q_cur = [-0.2, -16.0, -19.8, 0.5, -16.0, -20.2, -1.6, 118.0, 55.0, -1.3, 118.0, 55.0]
            q_cmd_rad = torch.tensor([q_cur], dtype=torch.float64) * (math.pi / 180.0)
            prev_act = [0.0] * 12
            for tick in range(70):
                cmd_deg = [v * 180.0 / math.pi for v in q_cmd_rad[0].tolist()]
                feat = assemble_pose_features(
                    measured_deg=q_cur,
                    commanded_deg=cmd_deg,
                    velocity_deg_s=[0.0] * 12,
                    usable_flags=[True] * 12,
                    orientation_wxyz=[0.997, 0.062, 0.008, -0.042],
                    angular_rate_rad_s=[0.0, 0.0, 0.0],
                    acceleration_m_s2=[-0.14, 1.68, 9.46],
                    goal_joint_deg=stand_proj,
                    goal_foot_norm=stand_foot,
                    leg_support=[1.0, 1.0, 1.0, 1.0],
                    speed_scale=0.5,
                    previous_action=prev_act,
                )
                act, _ = actor.infer_feet_mm(hist.push_and_project(tick * 0.02, feat))
                q_cmd_rad, prev_act, _ = manifold.step_host_command(act, q_cmd_rad, speed_scale=0.5, body=live_body)
                new_cmd = [v * 180.0 / math.pi for v in q_cmd_rad[0].tolist()]
                for j in range(12):
                    q_cur[j] += max(-6.0, min(6.0, new_cmd[j] - q_cur[j]))
            final_cmd = [v * 180.0 / math.pi for v in q_cmd_rad[0].tolist()]
            self.assertLessEqual(abs(final_cmd[7] - stand_proj[7]), 12.0, f"FL carrier stayed stuck at {final_cmd[7]}")
            self.assertLessEqual(abs(final_cmd[10] - stand_proj[10]), 12.0, f"FR carrier stayed stuck at {final_cmd[10]}")


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
        carpet_snag_k_n_m: float = 0.0,
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
        init_q_rad = torch.tensor(init_proj_deg, dtype=torch.float64).reshape(1, 12) * (math.pi / 180.0)
        _, init_phys_rad = manifold.body.pwm(init_q_rad)
        init_ctrl = init_phys_rad[0].numpy().copy()
        if carpet_snag_k_n_m > 0.0 and not suspended:
            # Let all feet settle firmly onto the z=0 floor under gravity before starting the snag scenario
            for _ in range(120):
                for c_i in range(12):
                    sim.data.ctrl[act_ids[c_i]] = float(init_ctrl[c_i])
                mujoco.mj_step(sim.model, sim.data)
            init_proj_deg = [float(sim.data.qpos[a] * 180.0 / math.pi) for a in joint_qpos_adrs]
            init_proj_deg, init_foot = manifold.project_angles_deg(init_proj_deg)
            init_q_rad = torch.tensor(init_proj_deg, dtype=torch.float64).reshape(1, 12) * (math.pi / 180.0)
            _, init_phys_rad = manifold.body.pwm(init_q_rad)
            init_ctrl = init_phys_rad[0].numpy().copy()
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

        cmd_queue = deque([init_ctrl.copy() for _ in range(cmd_delay_ticks + 1)], maxlen=cmd_delay_ticks + 1)

        filt_q_deg = np.asarray(init_proj_deg, dtype=np.float64).copy()
        init_pkt = (
            list(init_proj_deg),
            [0.0] * 12,
            list(init_proj_deg),
            sim.data.qpos[3:7].tolist(),
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
                pickup_body_ids = [int(sim.model.body(f"{l}_pickup_body").id) for l in legs]
                foot_site_ids = [int(sim.model.site(f"{l}_reference").id) for l in legs]
                # Track RL foot vertical clearance in true MuJoCo world-frame Z (mm above grounded floor contact Z)
                cur_rl_z_mm = float(sim.data.site_xpos[foot_site_ids[0], 2] * 1000.0)
                rl_sh_jid = int(sim.model.joint("rear_left_shoulder").id)
                if s_i == 0 and t_sim == 0.0:
                    floor_rl_z_mm = cur_rl_z_mm
                    max_rl_lift_mm = 0.0
                    orig_rl_sh_limited = int(sim.model.jnt_limited[rl_sh_jid])
                    orig_rl_sh_range = sim.model.jnt_range[rl_sh_jid].copy()
                    rl_carpet_locked = bool(carpet_snag_k_n_m > 0.0)
                    rl_carpet_grounded_once = False
                    if rl_carpet_locked:
                        # Unilateral carpet-pile shoulder lock at -36 deg until rear_left foot lifts >= 6 mm clear of floor
                        sim.model.jnt_limited[rl_sh_jid] = 1
                        sim.model.jnt_range[rl_sh_jid] = [math.radians(-70.0), math.radians(-36.0)]
                if rl_carpet_grounded_once or carpet_snag_k_n_m <= 0.0:
                    max_rl_lift_mm = max(max_rl_lift_mm, cur_rl_z_mm - floor_rl_z_mm)

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
                        rl_pb = pickup_body_ids[0]
                        sub_rl_z_mm = float(sim.data.site_xpos[foot_site_ids[0], 2] * 1000.0)
                        in_floor_contact = any(
                            int(sim.model.geom_bodyid[sim.data.contact[c_idx].geom1]) == rl_pb
                            or int(sim.model.geom_bodyid[sim.data.contact[c_idx].geom2]) == rl_pb
                            for c_idx in range(int(sim.data.ncon))
                        )
                        if in_floor_contact:
                            rl_carpet_grounded_once = True
                            floor_rl_z_mm = min(floor_rl_z_mm, sub_rl_z_mm)
                        elif rl_carpet_grounded_once:
                            max_rl_lift_mm = max(max_rl_lift_mm, sub_rl_z_mm - floor_rl_z_mm)
                            if rl_carpet_locked and (sub_rl_z_mm - floor_rl_z_mm) >= 6.0:
                                rl_carpet_locked = False
                                sim.model.jnt_limited[rl_sh_jid] = orig_rl_sh_limited
                                sim.model.jnt_range[rl_sh_jid] = orig_rl_sh_range

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

        sim.model.jnt_limited[int(sim.model.joint("rear_left_shoulder").id)] = orig_rl_sh_limited
        sim.model.jnt_range[int(sim.model.joint("rear_left_shoulder").id)] = orig_rl_sh_range
        return {
            "scenario": name,
            "suspended": suspended,
            "upright_min_cos": round(min_up_cos, 3),
            "fell_over": (not suspended) and (min_up_cos < 0.45),
            "segment_end_mae_deg": seg_errors_deg,
            "mean_end_mae_deg": round(sum(seg_errors_deg) / max(1, len(seg_errors_deg)), 2),
            "hold_cmd_p2p_deg": round(max(hold_cmd_p2p_list), 2) if hold_cmd_p2p_list else None,
            "hold_joint_p2p_deg": round(max(hold_joint_p2p_list), 2) if hold_joint_p2p_list else None,
            "max_rl_lift_mm": round(float(max_rl_lift_mm), 2),
            "rl_shoulder_end_deg": round(float(end_q_deg[0]), 2),
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
            _run_scenario(
                "splayed_carpet_snag_microstep_recovery",
                [-40.91, 7.01, -19.84, -12.44, 7.71, -21.42, -12.37, -0.78, -20.25, -17.82, 5.15, -21.68],
                [
                    {
                        "name": "body",
                        "arguments": {
                            "translation_mm": [-10.0, 10.0, 0.0],
                            "rotation_deg": [0.0, 0.0, 0.0],
                            "legs": [],
                            "foot_offsets_mm": [],
                            "speed_pct": 75,
                        },
                    },
                    {
                        "name": "feet",
                        "arguments": {
                            "legs": ["front_right"],
                            "offsets_mm": [[22.0, -14.0, 42.0]],
                            "speed_pct": 70,
                        },
                    },
                    {"name": "stand", "arguments": {}},
                    {"name": "hold", "arguments": {"seconds": 1.0}},
                ],
                suspended=False,
                cmd_delay_ticks=2,
                obs_delay_ticks=4,
                carpet_snag_k_n_m=360.0,
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
            if item["scenario"] == "splayed_carpet_snag_microstep_recovery":
                self.assertGreaterEqual(
                    item["max_rl_lift_mm"],
                    6.0,
                    f"Splayed carpet-snag recovery must unload/lift rear_left foot >= 6 mm clear of carpet pile: {item}",
                )
                self.assertLessEqual(
                    abs(item["rl_shoulder_end_deg"]),
                    6.0,
                    f"Splayed carpet-snag recovery must unlock rear_left_shoulder from -36 deg to stand: {item}",
                )
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
