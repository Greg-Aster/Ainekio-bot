"""Stanford Pupper V3 MJX 200M-step policy contract, sign conventions, and robot deployment tests."""

import json
import math
from pathlib import Path
import time
import unittest
import numpy as np

from gateway.neural_gait.contract import ObservationHistory, PROPRIO_SCHEMA, vector
from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
from gateway.neural_gait.native import BodyModel, VirtualBody
from gateway.neural_gait.pupper_mjx_actor import (
    HISTORY_DIM,
    OBSERVATION_DIM,
    PUPPER_MJX_KIND,
    PupperMjxActor,
    calibration_pulse_to_rad,
    projected_gravity_body,
    quat_rotate_inv,
    rad_to_calibration_pulse,
)
from gateway.neural_gait.server import Runtime
from gateway.neural_gait.virtual import VirtualGatewaySession


ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "build/neural-gait/pupper-mjx-200m"
POLICY_JSON = ARTIFACT_DIR / "policy_2026-11-05_20-13-42.json"
ORBAX_DIR = ARTIFACT_DIR / "201523200"
HARDWARE_JSON = ARTIFACT_DIR / "ainekio-training-hardware.json"


class PupperMjxActorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hardware = json.loads(HARDWARE_JSON.read_text())
        cls.environment = dict(
            robot=cls.hardware["robot"],
            reference_joint_deg=[0.0, 3.46, -21.63] * 4,
            target_limits_deg=[[-90.0, 90.0]] * 12,
            foot_action_scale_mm=[100.0, 100.0, 100.0],
            joint_speed_deg_s=60.0 / 0.11,
            control_hz=50,
            observation_schema=PROPRIO_SCHEMA,
        )
        cls.actor = PupperMjxActor(POLICY_JSON, environment=cls.environment)

    @classmethod
    def tearDownClass(cls):
        cls.actor.close()

    def test_sign_conventions_and_calibration_conversion(self):
        # 1. Level upright orientation -> gravity_body == [0, 0, -1]
        np.testing.assert_allclose(
            projected_gravity_body([1.0, 0.0, 0.0, 0.0]),
            np.array([0.0, 0.0, -1.0], dtype=np.float32),
            atol=1e-7,
        )

        # 2. Pitch rotation +theta about body +Y (nose down): world [0, 0, -1] -> [+sin(theta), 0, -cos(theta)]
        theta = 0.25
        q_pitch = [math.cos(theta / 2.0), 0.0, math.sin(theta / 2.0), 0.0]
        np.testing.assert_allclose(
            projected_gravity_body(q_pitch),
            np.array([math.sin(theta), 0.0, -math.cos(theta)], dtype=np.float32),
            atol=1e-6,
        )

        # 3. Roll rotation +phi about body +X (right side down): world [0, 0, -1] -> [0, -sin(phi), -cos(phi)]
        phi = -0.2
        q_roll = [math.cos(phi / 2.0), math.sin(phi / 2.0), 0.0, 0.0]
        np.testing.assert_allclose(
            projected_gravity_body(q_roll),
            np.array([0.0, -math.sin(phi), -math.cos(phi)], dtype=np.float32),
            atol=1e-6,
        )

        # 4. Agreement with gateway proprio_terms projected gravity across arbitrary 3D orientations
        rng = np.random.default_rng(7)
        for _ in range(25):
            q = rng.normal(size=4)
            q /= np.linalg.norm(q)
            obs = dict(
                schema=PROPRIO_SCHEMA,
                observation_time_s=0.02,
                joint_deg=[0.0, 3.46, -21.63] * 4,
                joint_velocity_deg_s=[0.0] * 12,
                angular_rate_rad_s=[0.1, -0.2, 0.3],
                acceleration_m_s2=[0.0, 0.0, 9.81],
                orientation_wxyz=q.tolist(),
                command=[0.15, -0.04, 0.5],
                previous_action=[0.0] * 12,
            )
            terms = ObservationHistory().project(obs)["proprio_history"][0]
            obs_36 = self.actor.single_step_observation(obs)
            np.testing.assert_allclose(obs_36[0:3], [0.1, -0.2, 0.3], atol=1e-7)
            np.testing.assert_allclose(obs_36[3:6], terms[30:33], atol=1e-6)
            np.testing.assert_allclose(obs_36[6:9], [0.15, -0.04, 0.5], atol=1e-7)
            np.testing.assert_allclose(obs_36[9:12], [0.0, 0.0, 1.0], atol=1e-7)
            np.testing.assert_allclose(obs_36[12:24], np.zeros(12), atol=1e-6)
            np.testing.assert_allclose(obs_36[24:36], np.zeros(12), atol=1e-7)

        # 5. Installed calibration (home_cd, home_us, us_per_degree, invert) <-> MuJoCo radians
        calibration = self.hardware["robot"]["calibration"]
        body = BodyModel(self.hardware["robot"])
        try:
            test_deg = np.array([5.0, 12.0, -28.0, -5.0, -8.0, -15.0, 4.0, 10.0, -25.0, -4.0, 8.0, -20.0])
            test_rad = np.deg2rad(test_deg)
            pulses = rad_to_calibration_pulse(test_rad, calibration)
            logical_rad = calibration_pulse_to_rad(pulses, calibration)
            pwm = body.pwm_output(test_deg)
            np.testing.assert_allclose(pulses, pwm["logical_pulse_us"], atol=1e-6)
            np.testing.assert_allclose(np.rad2deg(logical_rad), pwm["physical_angles"], atol=0.5)
        finally:
            body.close()

    def test_ring_buffer_mlp_speed_and_orbax_checkpoint_equivalence(self):
        # Verify Orbax checkpoint artifact metadata and RTNeural JSON layer structure
        self.assertTrue((ORBAX_DIR / "_CHECKPOINT_METADATA").is_file())
        self.assertTrue((ORBAX_DIR / "_METADATA").is_file())
        self.assertTrue((ORBAX_DIR / "commit_success.txt").is_file())
        tree_meta = json.loads((ORBAX_DIR / "_METADATA").read_text())
        for idx in range(5):
            self.assertIn(f"('1', 'params', 'hidden_{idx}', 'kernel')", tree_meta["tree_metadata"])
            self.assertIn(f"('1', 'params', 'hidden_{idx}', 'bias')", tree_meta["tree_metadata"])

        raw_policy = json.loads(POLICY_JSON.read_text())
        rng = np.random.default_rng(19)
        x_batch = rng.normal(size=(8, HISTORY_DIM)).astype(np.float32)
        actual = self.actor.forward(x_batch)

        h = x_batch.copy()
        for idx, layer in enumerate(raw_policy["layers"]):
            kernel = np.asarray(layer["weights"][0], dtype=np.float32)
            bias = np.asarray(layer["weights"][1], dtype=np.float32)
            h = h @ kernel + bias
            if idx < 4:
                self.assertEqual(layer["activation"], "elu")
                h = np.where(h > 0.0, h, np.expm1(np.minimum(h, 0.0)))
            else:
                self.assertEqual(layer["activation"], "tanh")
                h = np.tanh(h)
        np.testing.assert_allclose(actual, h, atol=1e-6)

        # Verify CPU forward pass speed (< 0.5 ms per step)
        obs_540 = x_batch[0]
        t0 = time.perf_counter()
        for _ in range(500):
            out = self.actor.forward(obs_540)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0 / 500.0
        self.assertLess(elapsed_ms, 0.5)
        self.assertEqual(out.shape, (12,))
        self.assertTrue(np.all(np.abs(out) <= 1.0))

        # Verify 15-step ring buffer shifting and zero initialization
        self.actor.reset()
        ctx = dict(gateway_instance="g1", robot_id="r1", epoch=1, walk=1)
        for step in range(3):
            obs = dict(
                angular_rate_rad_s=[float(step + 1), 0.0, 0.0],
                orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
                command=[0.15, 0.0, 0.0],
                joint_deg=[0.0, 3.46, -21.63] * 4,
                target_deg=[0.0, 3.46, -21.63] * 4,
                previous_action=[0.0] * 12 if step == 0 else [0.1] * 12,
                observation_time_s=step * 0.02,
            )
            res = self.actor.infer_observation(obs, walk_context=ctx)
            state = self.actor._state_for(ctx)
            self.assertEqual(float(state.obs_history[0]), float(step + 1))
            if step == 0:
                np.testing.assert_array_equal(state.obs_history[OBSERVATION_DIM:], np.zeros(HISTORY_DIM - OBSERVATION_DIM))
                np.testing.assert_array_equal(state.obs_history[24:36], np.zeros(12))
            else:
                self.assertEqual(float(state.obs_history[OBSERVATION_DIM]), float(step))
            np.testing.assert_allclose(state.last_action, res["raw_action"], atol=1e-7)
            self.assertTrue(np.all(res["resolved"]["leg_fit"] == 1.0))


class PupperMjxDeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_selection_and_virtual_gateway_walk(self):
        root = ARTIFACT_DIR.parent
        runtime = Runtime(root, device="cpu")
        status = runtime.load("pupper-mjx-200m")
        self.assertEqual(status["model_id"], "pupper-mjx-200m")
        self.assertEqual(status["kind"], PUPPER_MJX_KIND)

        now = 1_000_000
        pose = np.array([0.0, 3.46, -21.63] * 4)
        body = BodyModel(status["environment"]["robot"])
        executor = VirtualBody(
            body,
            pose,
            joint_speed_deg_s=60.0 / 0.11,
            motion_rate=1.0,
            balance=False,
            heading_feedback=False,
            balance_tuning=[1.0, 1.0, 0.0, 0.0],
            idle_rest_seconds=0,
        )
        session = VirtualGatewaySession(
            executor,
            status["environment"],
            lambda: now,
            {"source": "neural", "forward_m_s": 0.15, "lateral_m_s": 0.08, "yaw_rad_s": 1.0},
        )
        await session.start()
        try:
            measured = pose.copy()
            body.feedback_sample(body.raw_samples(measured), measured, body.sample_times(now / 1e6) * 1e6)
            body.imu_sample(now, [0.0, 0.0, 9.80665], [0.0, 0.0, 0.0])

            await session.start_walk({"dir": "fwd", "steps": 0, "speed": 100})
            for _ in range(15):
                output = executor.tick(now)
                now += 20_000
                measured = np.where(output["joint_enabled"], output["logical_angles"], measured)
                body.feedback_sample(body.raw_samples(measured), measured, body.sample_times(now / 1e6) * 1e6)
                body.imu_sample(now, [0.0, 0.0, 9.80665], [0.0, 0.0, 0.0])
                await session.publish(output["messages"])
                await session.telemetry()
                if session.observation_ready:
                    obs = await session.observation()
                    inferred = runtime.infer(
                        obs,
                        walk_context=dict(
                            gateway_instance="test",
                            robot_id=session.robot_id,
                            epoch=session.connection.epoch,
                            walk=session.walk,
                        ),
                    )
                    await session.action(inferred["action"])
            self.assertGreater(session.execution_info()["consumed_sample"], 0)
            self.assertGreater(float(np.max(np.abs(measured - pose))), 1.0)
            stop = await session.stop(release=True)
            await session.connection.wait_acknowledged(stop, timeout=None)
        finally:
            await session.close()
            executor.close()
            body.close()

    async def test_orbax_cpu_import_and_policy_observation_recording(self):
        import tempfile
        from gateway.neural_gait.import_pupper_mjx import import_pupper_mjx_run

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            imported = import_pupper_mjx_run(
                ORBAX_DIR,
                "pupper-mjx-imported",
                steps=201523200,
                neural_gait_dir=tmp_root,
                template_run_dir=ARTIFACT_DIR,
                select=True,
            )
            self.assertEqual(imported["run_id"], "pupper-mjx-imported")
            self.assertEqual(imported["checkpoint_id"], "step-201523200")
            self.assertTrue((tmp_root / "selected.json").is_file())

            runtime = Runtime(tmp_root, device="cpu")
            status = runtime.load("pupper-mjx-imported")
            self.assertEqual(status["model_id"], "pupper-mjx-imported")
            self.assertEqual(status["kind"], PUPPER_MJX_KIND)

            ref_actor = PupperMjxActor(POLICY_JSON, environment=status["environment"])
            try:
                rng = np.random.default_rng(101)
                x = rng.normal(size=(4, HISTORY_DIM)).astype(np.float32)
                np.testing.assert_allclose(runtime.model.forward(x), ref_actor.forward(x), atol=1e-4)
            finally:
                ref_actor.close()



if __name__ == "__main__":
    unittest.main()
