"""Durable unit tests for V3-on-P4 (v3-12servo) protocol, gateway routing, and neural pose contract."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "Master"), str(ROOT / "Slave/software"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from protocol.control_v1 import validate_control_message
from experiments.freestyle.neural_pose.v3_contract import (
    V3_CANONICAL_POSTURES_DEG,
    V3_CANONICAL_SUPPORT,
    V3_POSE_FEATURES,
    V3_POSE_OBS_SIZE,
    V3PoseObservationHistory,
    assemble_v3_pose_features,
    deg_to_norm,
    norm_to_deg,
    v3_pose_mirror_tables,
)


class V3P4ProtocolTests(unittest.TestCase):
    def test_v3_motion_plan_targets_map2_validates(self):
        msg = {
            "t": "motion_plan",
            "seq": 21,
            "map": 2,
            "control": "targets",
            "frames": [[80000, [-400, -2200, 2800] * 4]],
            "end": "hold",
        }
        validate_control_message(msg)

    def test_v3_calibration_status_12_joints_ds3225pro(self):
        msg = {
            "t": "calibration_status",
            "seq": 4,
            "dirty": False,
            "saved": True,
            "ready": True,
            "servo_profile_id": "ds3225pro-270-v3-p4",
            "provisional_us_per_degree": 7.4074,
            "joints": [
                {
                    "id": i,
                    "channel": i,
                    "home_us": 1500,
                    "invert": False,
                    "home_cd": 0,
                    "recommended_home_us": 1500,
                    "recommended_home_cd": 0,
                    "us_per_degree": 7.4074,
                    "pulse_us": 1500,
                }
                for i in range(12)
            ],
        }
        validate_control_message(msg)

    def test_v3_gateway_is_p4_body_and_capabilities(self):
        try:
            from gateway.body_capabilities import expression_library
        except ImportError:
            self.skipTest("gateway package unavailable in this venv")

        exprs = expression_library({"model": "v3-12servo", "features": ["face_feedback_v1"], "capabilities": {"display": True}})
        self.assertTrue(exprs)


class V3NeuralPoseContractTests(unittest.TestCase):
    def test_deg_norm_round_trip(self):
        for name, angles in V3_CANONICAL_POSTURES_DEG.items():
            norm = deg_to_norm(angles)
            recovered = norm_to_deg(norm)
            for a, b in zip(angles, recovered):
                self.assertAlmostEqual(a, b, places=4, msg=f"mismatch in {name}")

    def test_mirror_tables_are_exact_involution(self):
        obs_p, obs_s, act_p, act_s = v3_pose_mirror_tables()
        self.assertEqual(len(obs_p), V3_POSE_OBS_SIZE)
        self.assertEqual(len(obs_s), V3_POSE_OBS_SIZE)
        self.assertEqual(len(act_p), 12)
        self.assertEqual(len(act_s), 12)
        for i in range(V3_POSE_OBS_SIZE):
            j = obs_p[i]
            self.assertEqual(obs_p[j], i)
            self.assertEqual(obs_s[i] * obs_s[j], 1.0)
        for i in range(12):
            j = act_p[i]
            self.assertEqual(act_p[j], i)
            self.assertEqual(act_s[i] * act_s[j], 1.0)

    def test_wave_postures_are_exact_left_right_mirrors(self):
        _, _, act_p, act_s = v3_pose_mirror_tables()
        wfr = V3_CANONICAL_POSTURES_DEG["wave_fr"]
        wfl = V3_CANONICAL_POSTURES_DEG["wave_fl"]
        mirrored = [wfr[act_p[i]] * act_s[i] for i in range(12)]
        self.assertEqual(mirrored, list(wfl))

    def test_feature_assembly_and_history_buffer(self):
        hist = V3PoseObservationHistory()
        row0 = assemble_v3_pose_features(
            measured_deg=[0.0] * 12,
            commanded_deg=[0.0] * 12,
            velocity_deg_s=[0.0] * 12,
            usable_flags=[True] * 12,
            orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
            angular_rate_rad_s=[0.0, 0.0, 0.0],
            acceleration_m_s2=[0.0, 0.0, 9.81],
            goal_joint_deg=V3_CANONICAL_POSTURES_DEG["bow"],
            leg_support=V3_CANONICAL_SUPPORT["bow"],
            speed_scale=1.0,
            previous_action=deg_to_norm([0.0] * 12),
        )
        self.assertEqual(len(row0), V3_POSE_FEATURES)
        obs = hist.push_and_project(0.0, row0)
        self.assertEqual(len(obs), V3_POSE_OBS_SIZE)
        self.assertEqual(obs[:V3_POSE_FEATURES], row0)

    def test_exported_v3_onnx_policies_if_present(self):
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError:
            self.skipTest("onnxruntime/numpy not installed in this venv")

        gait_onnx = ROOT / "build" / "neural-gait" / "v3-microduck-p4" / "policy.onnx"
        if gait_onnx.exists():
            sess = ort.InferenceSession(str(gait_onnx), providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0]
            self.assertEqual(inp.shape[-1], 600)
            out = sess.run(None, {inp.name: np.zeros((1, 600), dtype=np.float32)})[0]
            self.assertEqual(out.shape, (1, 12))
            self.assertTrue(np.all(np.isfinite(out)))
            self.assertLessEqual(float(np.max(np.abs(out))), 1.0001)

        pose_onnx = ROOT / "experiments" / "freestyle" / "artifacts" / "neural_pose_v3" / "policy.onnx"
        if pose_onnx.exists():
            sess = ort.InferenceSession(str(pose_onnx), providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0]
            self.assertEqual(inp.shape[-1], V3_POSE_OBS_SIZE)
            rng = np.random.default_rng(17)
            obs_p, obs_s, act_p, act_s = v3_pose_mirror_tables()
            for _ in range(4):
                x = rng.uniform(-0.5, 0.5, size=(1, V3_POSE_OBS_SIZE)).astype(np.float32)
                y = sess.run(None, {inp.name: x})[0]
                self.assertEqual(y.shape, (1, 12))
                self.assertTrue(np.all(np.isfinite(y)))
                xm = x[:, obs_p] * np.asarray(obs_s, dtype=np.float32)
                ym = sess.run(None, {inp.name: xm})[0]
                ym_un = ym[:, act_p] * np.asarray(act_s, dtype=np.float32)
                self.assertLess(float(np.max(np.abs(y - ym_un))), 1e-4)


if __name__ == "__main__":
    unittest.main()
