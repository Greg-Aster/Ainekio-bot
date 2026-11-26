"""Durable unit tests for redesigned V1-on-P4 protocol, kinematics, and neural pose contract."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "Master"), str(ROOT / "Slave/software"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from protocol.control_v1 import ProtocolValidationError, validate_control_message
from experiments.freestyle.neural_pose.v1_contract import (
    V1_CANONICAL_POSTURES_DEG,
    V1_CANONICAL_SUPPORT,
    V1_POSE_FEATURES,
    V1_POSE_OBS_SIZE,
    V1_POSE_SAMPLES,
    V1PoseObservationHistory,
    assemble_v1_pose_features,
    deg_to_norm,
    norm_to_deg,
    v1_pose_mirror_tables,
)


class V1P4ProtocolTests(unittest.TestCase):
    def test_v1_motion_plan_targets_validates_signed_8dof(self):
        msg = {
            "t": "motion_plan",
            "seq": 12,
            "map": 1,
            "control": "targets",
            "frames": [[60000, [-2500, 1500, -2500, 1500, 6500, -500, -500, 6500]]],
            "end": "hold",
        }
        validate_control_message(msg)
        bad_len = {**msg, "frames": [[60000, [0] * 12]]}
        with self.assertRaises(ProtocolValidationError):
            validate_control_message(bad_len)

    def test_v1_calibration_status_accepts_8_joints(self):
        msg = {
            "t": "calibration_status",
            "seq": 3,
            "dirty": False,
            "saved": True,
            "ready": True,
            "servo_profile_id": "mg90s-v1-p4",
            "provisional_us_per_degree": 11.111,
            "joints": [
                {
                    "id": i,
                    "channel": i,
                    "home_us": 1500,
                    "invert": False,
                    "home_cd": 0,
                    "recommended_home_us": 1500,
                    "recommended_home_cd": 0,
                    "us_per_degree": 11.111,
                    "pulse_us": 1500,
                }
                for i in range(8)
            ],
        }
        validate_control_message(msg)

    def test_v1_imu_joint_feedback_map1_validates(self):
        msg = {
            "t": "event",
            "name": "imu",
            "data": {
                "boot_id": 1,
                "timestamp_us": 100000,
                "age_us": 500,
                "accepted_samples": 50,
                "rejected_samples": 0,
                "gap_restarts": 0,
                "available": True,
                "fresh": True,
                "startup": False,
                "calibration_applied": True,
                "gyro_recovery": False,
                "acceleration_recovery": False,
                "accelerometer_ignored": False,
                "frame": "body_nominal",
                "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
                "acceleration_m_s2": [0.0, 0.0, 9.81],
                "angular_rate_rad_s": [0.0, 0.0, 0.0],
                "acquisition": {"io_errors": 0, "no_data_polls": 0},
                "face_token": "",
                "joint_feedback": {
                    "map": 1,
                    "device_us": 100000,
                    "scan": 5,
                    "scan_us": 420,
                    "revision": 1,
                    "enabled": True,
                    "usable_mask": 0xFF,
                    "commanded_mask": 0xFF,
                    "stalled_joints": 0,
                    "calibrated_mask": 0xFF,
                    "unavailable_mask": 0,
                    "clipped_mask": 0,
                    "below_calibration_mask": 0,
                    "above_calibration_mask": 0,
                    "sampled_us": [99500] * 8,
                    "raw_adc": [2048] * 8,
                    "signal_millivolts": [1650] * 8,
                    "filtered_model_deg": [0.0] * 8,
                    "velocity_deg_s": [0.0] * 8,
                    "commanded_model_deg": [0.0] * 8,
                },
            },
        }
        validate_control_message(msg)


class V1NeuralPoseContractTests(unittest.TestCase):
    def test_deg_norm_round_trip(self):
        for name, angles in V1_CANONICAL_POSTURES_DEG.items():
            norm = deg_to_norm(angles)
            recovered = norm_to_deg(norm)
            for a, b in zip(angles, recovered):
                self.assertAlmostEqual(a, b, places=4, msg=f"mismatch in {name}")

    def test_mirror_tables_are_exact_involution(self):
        obs_p, obs_s, act_p, act_s = v1_pose_mirror_tables()
        self.assertEqual(len(obs_p), V1_POSE_OBS_SIZE)
        self.assertEqual(len(obs_s), V1_POSE_OBS_SIZE)
        self.assertEqual(len(act_p), 8)
        self.assertEqual(len(act_s), 8)
        # Double mirror must equal identity
        for i in range(V1_POSE_OBS_SIZE):
            j = obs_p[i]
            self.assertEqual(obs_p[j], i)
            self.assertEqual(obs_s[i] * obs_s[j], 1.0)
        for i in range(8):
            j = act_p[i]
            self.assertEqual(act_p[j], i)
            self.assertEqual(act_s[i] * act_s[j], 1.0)

    def test_wave_postures_are_exact_left_right_mirrors(self):
        _, _, act_p, act_s = v1_pose_mirror_tables()
        wfr = V1_CANONICAL_POSTURES_DEG["wave_fr"]
        wfl = V1_CANONICAL_POSTURES_DEG["wave_fl"]
        mirrored = [wfr[act_p[i]] * act_s[i] for i in range(8)]
        self.assertEqual(mirrored, list(wfl))

    def test_feature_assembly_and_history_buffer(self):
        hist = V1PoseObservationHistory()
        row0 = assemble_v1_pose_features(
            measured_deg=[0.0] * 8,
            commanded_deg=[0.0] * 8,
            velocity_deg_s=[0.0] * 8,
            usable_flags=[True] * 8,
            orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
            angular_rate_rad_s=[0.0, 0.0, 0.0],
            acceleration_m_s2=[0.0, 0.0, 9.81],
            goal_joint_deg=V1_CANONICAL_POSTURES_DEG["bow"],
            leg_support=V1_CANONICAL_SUPPORT["bow"],
            speed_scale=1.0,
            previous_action=deg_to_norm([0.0] * 8),
        )
        self.assertEqual(len(row0), V1_POSE_FEATURES)
        obs = hist.push_and_project(0.0, row0)
        self.assertEqual(len(obs), V1_POSE_OBS_SIZE)
        self.assertEqual(obs[:V1_POSE_FEATURES], row0)

    def test_exported_v1_onnx_policies_if_present(self):
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError:
            self.skipTest("onnxruntime/numpy not installed in this venv")

        gait_onnx = ROOT / "build" / "neural-gait" / "v1-microduck-p4" / "policy.onnx"
        if gait_onnx.exists():
            sess = ort.InferenceSession(str(gait_onnx), providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0]
            self.assertEqual(inp.shape[-1], 304)
            out = sess.run(None, {inp.name: np.zeros((1, 304), dtype=np.float32)})[0]
            self.assertEqual(out.shape, (1, 8))
            self.assertTrue(np.all(np.isfinite(out)))
            self.assertLessEqual(float(np.max(np.abs(out))), 1.0001)

        pose_onnx = ROOT / "experiments" / "freestyle" / "artifacts" / "neural_pose_v1" / "policy.onnx"
        if pose_onnx.exists():
            sess = ort.InferenceSession(str(pose_onnx), providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0]
            self.assertEqual(inp.shape[-1], V1_POSE_OBS_SIZE)
            rng = np.random.default_rng(13)
            obs_p, obs_s, act_p, act_s = v1_pose_mirror_tables()
            for _ in range(4):
                x = rng.uniform(-0.5, 0.5, size=(1, V1_POSE_OBS_SIZE)).astype(np.float32)
                y = sess.run(None, {inp.name: x})[0]
                self.assertEqual(y.shape, (1, 8))
                self.assertTrue(np.all(np.isfinite(y)))
                xm = x[:, obs_p] * np.asarray(obs_s, dtype=np.float32)
                ym = sess.run(None, {inp.name: xm})[0]
                ym_un = ym[:, act_p] * np.asarray(act_s, dtype=np.float32)
                self.assertLess(float(np.max(np.abs(y - ym_un))), 1e-4)


if __name__ == "__main__":
    unittest.main()
