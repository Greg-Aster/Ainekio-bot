"""Host simulator bindings exercise the production P4 sensing/calibration code.

Synthetic electrical curves below are test fixtures, not installed robot facts.
The private captured calibration stays in the simulation run configuration.
"""

import importlib.util
import math
import unittest


def robot_fixture():
    home = [0, 3.46, -21.63] * 4
    return {
        "calibration": [
            dict(
                id=j,
                channel=j,
                invert=bool(j % 2),
                home_us=1650,
                home_cd=round(home[j] * 100),
                us_per_degree=10.0,
            )
            for j in range(12)
        ],
        "feedback": dict(
            enabled=True,
            stand_enabled=True,
            jam_enabled=True,
            tolerance_us=200,
            arrival_tolerance_us=30,
            no_progress_ms=3000,
            progress_us=15,
            scan_us=16000,
            sample_age_from_last_channel_us=[11000 - j * 1000 for j in range(12)],
            joints=[
                dict(
                    id=j,
                    channel=j + 4,
                    points=[
                        dict(raw=raw, pulse_us=pulse)
                        for raw, pulse in ((300, 500), (1650, 1650), (3000, 2800))
                    ],
                )
                for j in range(12)
            ],
        ),
    }


@unittest.skipUnless(
    importlib.util.find_spec("numpy") and importlib.util.find_spec("scipy"),
    "Use the gait-training environment for native model bindings",
)
class NativeSensorTests(unittest.TestCase):
    def test_neural_foot_targets_reuse_estimated_balance_and_reset_cleanly(self):
        np = self.np
        offsets = np.zeros((4,3))
        plain = self.body.foot_target(offsets,self.pose,self.pose,60/.11,.02)
        self.body.balance_configure(enabled=True)
        for now in range(1000,4000000,5000):
            self.body.imu_sample(now,[0,9.80665*math.sin(.15),9.80665*math.cos(.15)],[0,0,0])
        corrected = self.body.foot_target(offsets,self.pose,self.pose,60/.11,.02,now_us=3996000)
        self.assertTrue(corrected['balance_usable'])
        self.assertGreater(np.max(np.abs(corrected['goal_angles']-plain['goal_angles'])),.01)
        np.testing.assert_array_equal(corrected['nominal_goal_angles'],plain['goal_angles'])
        stale = self.body.foot_target(offsets,self.pose,corrected['ramped_angles'],60/.11,.02,now_us=4996000)
        self.assertFalse(stale['balance_usable'])
        self.body.balance_configure(enabled=False)
        disabled = self.body.foot_target(offsets,self.pose,self.pose,60/.11,.02,now_us=4996000)
        np.testing.assert_array_equal(disabled['ramped_angles'],plain['ramped_angles'])
        self.body.reset()
        reset = self.body.foot_target(offsets,self.pose,self.pose,60/.11,.02)
        np.testing.assert_array_equal(reset['goal_angles'],plain['goal_angles'])

    def setUp(self):
        import numpy as np
        from gateway.neural_gait.native import BodyModel

        self.np = np
        self.robot = robot_fixture()
        self.body = BodyModel(self.robot)
        self.pose = np.array([0, 3.46, -21.63] * 4)
        self.addCleanup(self.body.close)

    def sample(self, raw=None, target=None, timestamp=20000):
        np = self.np
        return self.body.feedback_sample(
            np.ones(12) * 1650 if raw is None else raw,
            self.pose if target is None else target,
            np.ones(12) * timestamp,
        )

    def test_all_three_capture_bits_initialize_and_endpoint_probe_does_not_invalidate_position(
        self,
    ):
        np = self.np
        target = self.pose + np.array([(-1 if j % 2 else 1) * 115 for j in range(12)])
        angles, velocity, usable, jam = self.sample(
            raw=np.ones(12) * 3000, target=target
        )
        np.testing.assert_allclose(angles, target, atol=1e-5)
        self.assertTrue(usable.all())
        self.assertEqual(jam, 0)
        self.assertTrue(self.body.arrival(target, 19999)["arrived"])

    def test_missing_or_outside_calibration_is_not_usable_and_health_is_retained(self):
        np = self.np
        raw = np.ones(12) * 1650
        raw[0] = np.nan
        raw[1] = 4095
        raw[2] = 100
        _, _, usable, jam = self.sample(raw=raw)
        self.assertFalse(usable[:3].any())
        self.assertTrue(usable[3:].all())
        self.assertEqual(jam, 0)
        status = self.body.arrival(self.pose, 0)
        self.assertEqual(status["unavailable_mask"], 1)
        self.assertEqual(status["clipped_mask"], 2)
        self.assertEqual(status["below_calibration_mask"] & 4, 4)
        self.assertFalse(status["observed"])
        self.assertFalse(status["arrived"])

    def test_arrival_requires_new_samples_and_reuses_endpoint_noise_tolerance(self):
        np = self.np
        target = self.pose.copy()
        target[0] += 115
        raw = np.ones(12) * 1650
        raw[0] = (
            3001  # Outside captured endpoint, but within configured endpoint-arrival tolerance.
        )
        _, _, usable, _ = self.sample(raw=raw, target=target, timestamp=20000)
        self.assertFalse(usable[0])
        self.assertFalse(self.body.arrival(target, 20000)["arrived"])
        self.assertTrue(self.body.arrival(target, 19999)["arrived"])

    def test_jam_requires_actual_no_progress_and_reports_once_until_new_episode(self):
        target = self.pose.copy()
        target[0] += 30
        self.assertEqual(self.sample(target=target, timestamp=20000)[3], 0)
        self.assertEqual(self.sample(target=target, timestamp=3019999)[3], 0)
        self.assertEqual(self.sample(target=target, timestamp=3020000)[3], 1)
        self.assertEqual(self.sample(target=target, timestamp=6020000)[3], 0)
        self.assertEqual(self.sample(target=self.pose, timestamp=6040000)[3], 0)
        self.assertEqual(self.sample(target=target, timestamp=6060000)[3], 0)
        self.assertEqual(self.sample(target=target, timestamp=9060000)[3], 1)

    def test_imu_register_quantization_saturation_and_range_rejection(self):
        np = self.np
        unit = float(np.float32(0.000488) * np.float32(9.80665))
        sample = self.body.imu_sample(
            1000, [1.4 * unit, -1.6 * unit, 1000.0], [0, 0, 0]
        )
        np.testing.assert_allclose(
            sample[4:7], np.array([1, -2, 32767]) * unit, rtol=1e-7
        )
        self.assertLess(sample[6], 16 * 9.80665)
        self.assertEqual(self.body.imu_status(1000)["timestamp_us"], 1000)
        # Full register rails exceed the gyro's configured physical range.
        # Preserve the real estimator rejection instead of claiming a new sample.
        rejected = self.body.imu_sample(2000, [0, 0, 9.80665], [1000.0, 0, 0])
        self.assertEqual(self.body.imu_status(2000)["timestamp_us"], 1000)
        np.testing.assert_array_equal(rejected[4:10], sample[4:10])

    def test_imu_quality_is_read_from_estimator_at_observation_time(self):
        absent = self.body.imu_status(1000)
        self.assertFalse(absent["quality"]["available"])
        self.assertFalse(absent["quality"]["fresh"])
        self.assertIsNone(absent["timestamp_us"])
        self.assertIsNone(absent["sample_age_s"])
        self.assertTrue(absent["quality"]["calibration_applied"])
        self.body.imu_sample(1000, [0, 0, 9.80665], [0, 0, 0])
        current = self.body.imu_status(1100)
        self.assertTrue(current["quality"]["available"])
        self.assertTrue(current["quality"]["fresh"])
        self.assertTrue(current["quality"]["startup"])
        self.assertEqual(current["timestamp_us"], 1000)
        self.assertAlmostEqual(current["sample_age_s"], 0.0001)
        self.assertFalse(self.body.imu_status(2000000)["quality"]["fresh"])
        self.assertIsNone(self.body.imu_status(999)["sample_age_s"])

    def test_staggered_samples_use_recorded_channel_ages(self):
        self.np.testing.assert_allclose(
            self.body.sample_times(0.02),
            [0.009 + j * 0.001 for j in range(12)],
            atol=1e-12,
        )

    def test_filter_tracks_measured_shaft_not_command_and_inversion_changes_velocity_sign(
        self,
    ):
        np = self.np
        self.sample(timestamp=20000)
        raw = np.ones(12) * 1750
        measured, velocity, usable, _ = self.sample(raw=raw, timestamp=40000)
        self.assertTrue(usable.all())
        self.assertGreater(measured[0], self.pose[0])
        self.assertLess(measured[0], self.pose[0] + 100 * 1150 / 1350 / 10)
        self.assertLess(measured[1], self.pose[1])
        self.assertGreater(velocity[0], 0)
        self.assertLess(velocity[1], 0)

    def test_imu_body_attitude_comes_from_production_sensor_estimator(self):
        np = self.np
        angle = math.radians(30)
        for n in range(100):
            obs = self.body.imu_sample(
                1 + n * 1e6 / 208,
                [0, 9.80665 * math.sin(angle), 9.80665 * math.cos(angle)],
                [0, 0, 0],
            )
        w, x, y, z = obs[:4]
        measured = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        self.assertLess(
            abs(measured - angle), 0.001
        )  # <0.06 degree after estimator startup samples.
        self.assertEqual(obs[10], 1)
        lsb = float(np.float32(0.000488) * np.float32(9.80665))
        expected = (
            np.rint(np.array([0, 9.80665 * 0.5, 9.80665 * math.cos(angle)]) / lsb) * lsb
        )
        np.testing.assert_allclose(obs[4:7], expected, atol=1e-5)

    def test_zero_foot_offsets_keep_standing_reference_and_ramp_unchanged(self):
        result = self.body.foot_target(
            self.np.zeros((4, 3)), self.pose, self.pose, 60 / 0.11, 0.02
        )
        self.assertIsNotNone(result)
        for key in ("goal_angles", "ramped_angles", "fitted_reference_angles"):
            self.np.testing.assert_allclose(result[key], self.pose, atol=1e-6)
        self.np.testing.assert_array_equal(
            result["applied_offset_mm"], self.np.zeros((4, 3))
        )
        self.np.testing.assert_array_equal(result["leg_fit"], self.np.ones(4))
        self.assertEqual(result["fit"], 1.0)

    def test_random_foot_actions_produce_viable_nonzero_targets_with_real_ramping(self):
        np = self.np
        rng = np.random.default_rng(42)
        for _ in range(32):
            offsets = rng.uniform(-1, 1, (4, 3)) * [30, 20, 30]
            result = self.body.foot_target(
                offsets, self.pose, self.pose, 60 / 0.11, 0.02
            )
            self.assertIsNotNone(result)
            self.assertIsNotNone(self.body.pwm_output(result["ramped_angles"]))
            self.assertGreater(
                float(np.abs(result["goal_angles"] - self.pose).max()), 0.05
            )
            self.assertGreater(
                float(np.abs(result["ramped_angles"] - self.pose).max()), 0.05
            )
            self.assertLessEqual(
                float(np.abs(result["ramped_angles"] - self.pose).max()),
                60 / 0.11 * 0.02 + 0.051,
            )
            self.assertTrue(((result["leg_fit"] >= 0) & (result["leg_fit"] <= 1)).all())
            np.testing.assert_allclose(
                result["applied_offset_mm"],
                offsets * result["leg_fit"][:, None],
                atol=1e-5,
            )

    def test_foot_offset_fitting_respects_existing_calibrated_command_bounds(self):
        from gateway.neural_gait.native import BodyModel

        np = self.np
        rng = np.random.default_rng(17)
        for home in (500, 2800):
            robot = robot_fixture()
            for joint in robot["calibration"]:
                if joint["id"] % 3:
                    joint["home_us"] = home
            body = BodyModel(robot)
            self.addCleanup(body.close)
            reductions = 0
            for _ in range(16):
                offsets = rng.uniform(-1, 1, (4, 3)) * [30, 20, 30]
                result = body.foot_target(
                    offsets, self.pose, self.pose, 60 / 0.11, 0.02
                )
                self.assertIsNotNone(result)
                reductions += int(result["fit"] < 1)
                for key in ("goal_angles", "ramped_angles"):
                    electrical = body.pwm_output(result[key])
                    self.assertIsNotNone(electrical)
                    pulse = electrical["logical_pulse_us"].reshape(4, 3)[:, 1:]
                    self.assertTrue((pulse >= 500).all())
                    self.assertTrue((pulse <= 2800).all())
            self.assertGreater(reductions, 0)

    def test_pwm_quantization_and_phases_follow_timer_and_output_channel_mapping(self):
        from gateway.neural_gait.native import BodyModel

        np = self.np
        robot = robot_fixture()
        for joint in robot["calibration"]:
            joint["channel"] = 11 - joint["id"]
        body = BodyModel(robot)
        self.addCleanup(body.close)
        result = body.pwm_output(self.pose)
        self.assertEqual(result["prescale"], 121)
        self.assertEqual(result["tick_us"], 4.88)
        self.assertAlmostEqual(result["period_s"], 0.01998848)
        np.testing.assert_array_equal(result["logical_pulse_us"], np.full(12, 1650))
        np.testing.assert_allclose(result["physical_pulse_us"], np.full(12, 338 * 4.88))
        delta = np.array(
            [(-1 if j % 2 else 1) * (338 * 4.88 - 1650) / 10 for j in range(12)]
        )
        np.testing.assert_allclose(result["physical_angles"], self.pose + delta)
        expected = np.array([(4096 * (11 - j) // 12) * 4.88 / 1e6 for j in range(12)])
        np.testing.assert_allclose(result["phase_offset_s"], expected, atol=1e-15)
        self.assertTrue(result["enabled"].all())
        changed = body.pwm_output(self.pose, oscillator_hz=26000000, frequency_hz=50)
        self.assertEqual(changed["prescale"], 126)
        self.assertAlmostEqual(changed["tick_us"], 127 / 26)
        self.assertNotEqual(
            changed["physical_pulse_us"][0], result["physical_pulse_us"][0]
        )

    def test_target_ramp_uses_shared_coordinated_speed_and_integer_pwm_mapping(self):
        target = self.pose.copy()
        target[0] += 30
        target[3] -= 15
        result = self.body.target(target, self.pose, 60 / 0.11, 0.02)
        self.assertIsNotNone(result)
        applied, goal = result
        # The shoulder changes leave planar closure unchanged. A 20 ms ramp
        # advances the largest request at advertised speed; the other follows
        # the same interpolation and 1 us electrical quantization.
        self.assertAlmostEqual(applied[0] - self.pose[0], 10.9, places=4)
        self.assertAlmostEqual(applied[3] - self.pose[3], -5.5, places=4)
        self.np.testing.assert_allclose(goal, target, atol=1e-4)


@unittest.skipUnless(
    importlib.util.find_spec("numpy") and importlib.util.find_spec("scipy"),
    "Use the gait-training environment for native model bindings",
)
class NativeWalkTests(unittest.TestCase):
    setUp = NativeSensorTests.setUp

    @classmethod
    def setUpClass(cls):
        import subprocess
        from gateway.neural_gait.native import ROOT, library

        library()
        cls.build = ROOT / "build/neural-gait/native"
        subprocess.run(
            [
                "cmake",
                "--build",
                str(cls.build),
                "--target",
                "v2_walk_command",
                "-j",
                "4",
            ],
            capture_output=True,
            check=True,
        )

    def command(self, **changes):
        return dict(
            dict(
                t="intent",
                seq=1,
                name="walk",
                dir="fwd",
                gait="walk",
                steps=0,
                speed=50,
            ),
            **changes
        )

    def configure(self, **changes):
        self.body.walk_configure(
            **dict(
                dict(
                    speed_deg_s=60 / 0.11, heading_enabled=False, balance_enabled=False
                ),
                **changes
            )
        )

    def test_all_walk_families_match_existing_command_executable(self):
        import json
        import subprocess

        np = self.np
        cases = [
            dict(),
            dict(dir="back"),
            dict(dir="turn_l"),
            dict(dir="turn_r"),
            dict(gait="run", speed=140),
            dict(speed=10),
            dict(speed=90),
            dict(gait="crawl"),
            dict(gait="crab", dir="side_l"),
            dict(forward=60, turn=30, lateral=0),
            dict(stride=70, rate=1),
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.configure()
                command = self.command(**changes)
                if "stride" in changes:
                    command.pop("speed")
                output = subprocess.run(
                    [
                        str(self.build / "motion/v2_walk_command"),
                        "200",
                        "50",
                        str(60 / 0.11),
                    ],
                    input=json.dumps(command) + "\n",
                    text=True,
                    capture_output=True,
                    check=True,
                )
                rows = [json.loads(line) for line in output.stdout.splitlines()]
                self.assertTrue(self.body.walk_accept(command, 0))
                previous = self.pose
                for row in rows:
                    result = self.body.walk_tick(round(row["ms"] * 1000), previous)
                    self.assertIsNotNone(result)
                    previous = result["mapped_angles"]
                    source_q = np.asarray(row["q"]).reshape(4, 3)
                    expected = source_q[[2, 3, 0, 1]].reshape(-1) * 180 / np.pi
                    np.testing.assert_allclose(
                        result["nominal_angles"], expected, atol=0.011
                    )
                    self.assertAlmostEqual(result["phase"], row["phase"], places=9)
                    self.assertAlmostEqual(
                        result["run_blend"], row["run_blend"], places=9
                    )
                    np.testing.assert_array_equal(
                        result["predicted_grounded"],
                        np.array(row["grounded"])[[2, 3, 0, 1]],
                    )
                    np.testing.assert_allclose(
                        result["applied_angles"], result["balanced_angles"]
                    )
                    self.assertEqual(result["complete"], row["complete"])

    def test_update_and_finish_keep_original_sequence_and_clock(self):
        self.configure()
        self.assertTrue(self.body.walk_accept(self.command(), 0))
        result = self.body.walk_tick(0, self.pose)
        for now in range(20000, 220000, 20000):
            result = self.body.walk_tick(now, result["mapped_angles"])
        phase = result["phase"]
        self.assertTrue(
            self.body.walk_accept(self.command(seq=2, update=1, speed=90), 205000)
        )
        result = self.body.walk_tick(220000, result["mapped_angles"])
        self.assertEqual(result["command_sequence"], 1)
        self.assertEqual(result["latest_sequence"], 2)
        self.assertGreater(result["phase"], phase)
        self.assertEqual(result["last_us"], 220000)
        self.assertTrue(
            self.body.walk_accept(self.command(seq=3, update=1, speed=0), 225000)
        )
        for now in range(240000, 10000001, 20000):
            result = self.body.walk_tick(now, result["mapped_angles"])
            self.assertIsNotNone(result)
            if result["complete"]:
                break
        self.assertTrue(result["complete"])
        self.assertTrue(result["predicted_grounded"].all())
        self.assertEqual(result["command_sequence"], 1)
        self.assertEqual(result["latest_sequence"], 3)

    def test_leveling_uses_estimator_and_fades_when_stale(self):
        np = self.np
        self.configure(balance_enabled=True, heading_enabled=True)
        roll = 0.15
        for now in range(1000, 4000000, 5000):
            self.body.imu_sample(
                now, [0, 9.80665 * math.sin(roll), 9.80665 * math.cos(roll)], [0, 0, 0]
            )
        self.assertTrue(self.body.walk_accept(self.command(), 3996000))
        result = self.body.walk_tick(4016000, self.pose)
        self.assertTrue(result["imu_usable"])
        self.assertTrue(result["balance_usable"])
        self.assertGreater(
            float(np.abs(result["balanced_angles"] - result["nominal_angles"]).max()),
            0.01,
        )
        result = self.body.walk_tick(5016000, result["mapped_angles"])
        self.assertFalse(result["imu_usable"])
        self.assertFalse(result["balance_usable"])
        self.assertGreater(result["phase"], 0)

    def test_optional_zero_policy_does_not_change_baseline(self):
        self.configure(model=self.np.zeros(237))
        self.assertTrue(self.body.walk_accept(self.command(), 0))
        result = self.body.walk_tick(0, self.pose)
        for now in range(20000, 200001, 20000):
            result = self.body.walk_tick(
                now,
                result["mapped_angles"],
                learning_input=self.np.zeros((4, 8)),
                learning_usable=True,
            )
        self.np.testing.assert_array_equal(
            result["applied_angles"], result["balanced_angles"]
        )
        self.assertGreater(result["learning_blend"], 0)


@unittest.skipUnless(
    importlib.util.find_spec("mujoco") and importlib.util.find_spec("gymnasium"),
    "Use the gait-training environment for contact measurements",
)
class ContactSlipMeasurementTests(unittest.TestCase):
    """Synthetic rigid-body fixture; no private device data or CAD preparation."""

    def setUp(self):
        from types import SimpleNamespace
        import mujoco
        import numpy as np
        from gateway.neural_gait.contract import LEGS
        from gateway.neural_gait.environment import GaitEnvironment

        self.mj, self.np = mujoco, np
        bodies = "".join(
            f'<body name="{leg}_pickup_body" pos="{(i % 2)*.3} {(i // 2)*.3} .03" '
            'euler=".2 -.15 .3"><freejoint/><geom type="box" size=".04 .03 .05" '
            'mass=".1625"/></body>' for i, leg in enumerate(LEGS)
        )
        model = mujoco.MjModel.from_xml_string(
            '<mujoco><compiler angle="radian"/><option gravity="0 0 -9.81"/>'
            '<worldbody><geom name="floor" type="plane" size="2 2 .1"/>'
            + bodies + '<body name="not_a_foot" pos=".8 0 .03"><freejoint/>'
            '<geom type="box" size=".04 .03 .05" mass=".2"/></body>'
            '</worldbody></mujoco>'
        )
        self.env = GaitEnvironment.__new__(GaitEnvironment)
        self.env.model = model
        self.env.data = mujoco.MjData(model)
        self.env.config = SimpleNamespace(mass_kg=.65)
        self.feet = {model.body(leg+"_pickup_body").id for leg in LEGS}
        mujoco.mj_forward(model, self.env.data)

    def reference_cost(self):
        """Independent per-contact point Jacobian, without body-origin reuse."""
        e, np, mj = self.env, self.np, self.mj
        jac = np.zeros((3, e.model.nv))
        force = np.zeros(6)
        total = 0.0
        for index, contact in enumerate(e.data.contact[:e.data.ncon]):
            floor = e.model.geom("floor").id
            other = contact.geom1 if contact.geom2 == floor else (
                contact.geom2 if contact.geom1 == floor else None)
            if other is None:
                continue
            body = int(e.model.geom_bodyid[other])
            if body not in self.feet:
                continue
            mj.mj_contactForce(e.model, e.data, index, force)
            if force[0] > 0:
                mj.mj_jac(e.model, e.data, jac, None, contact.pos, body)
                velocity = jac @ e.data.qvel
                total += force[0] * float(velocity[:2] @ velocity[:2])
        return total / (mj.mj_getTotalmass(e.model) * np.linalg.norm(e.model.opt.gravity))

    def test_body_origin_velocity_matches_point_jacobian_for_translating_rotating_feet(self):
        e, np = self.env, self.np
        e.data.qvel[:] = np.linspace(-.8, 1.1, e.model.nv)
        self.mj.mj_forward(e.model, e.data)
        expected = self.reference_cost()
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(e._contact_slip_speed_squared(), expected, places=12)
        # Cached Jacobian buffers must follow the current velocities, not the
        # first sample; the score remains a squared-speed measurement.
        e.data.qvel *= -.3
        self.mj.mj_forward(e.model, e.data)
        self.assertAlmostEqual(e._contact_slip_speed_squared(), self.reference_cost(), places=12)
        # Domain randomization changes the model mass between resets. Cached
        # geometry/Jacobian buffers must not cache nominal body-weight load.
        e.model.body_mass[:] *= 1.7
        e.model.body_inertia[:] *= 1.7
        self.mj.mj_setConst(e.model, e.data)
        self.mj.mj_forward(e.model, e.data)
        self.assertAlmostEqual(e._contact_slip_speed_squared(), self.reference_cost(), places=12)

    def test_loaded_stationary_feet_have_zero_slip(self):
        self.assertGreater(self.env.data.ncon, 0)
        self.assertEqual(self.env._contact_slip_speed_squared(), 0)

    def test_airborne_feet_and_nonfoot_floor_contact_do_not_add_slip(self):
        e = self.env
        for body in self.feet:
            joint = e.model.body_jntadr[body]
            e.data.qpos[e.model.jnt_qposadr[joint]+2] = 1
        e.data.qvel[:] = 1
        self.mj.mj_forward(e.model, e.data)
        self.assertGreater(e.data.ncon, 0)  # Only the unrelated body touches.
        self.assertEqual(e._contact_slip_speed_squared(), 0)
        other = e.model.body("not_a_foot").id
        e.data.qpos[e.model.jnt_qposadr[e.model.body_jntadr[other]]+2] = 1
        self.mj.mj_forward(e.model, e.data)
        self.assertEqual(e.data.ncon, 0)
        self.assertEqual(e._contact_slip_speed_squared(), 0)


@unittest.skipUnless(
    importlib.util.find_spec("mujoco") and importlib.util.find_spec("stable_baselines3"),
    "Use the gait-training environment for evaluator measurements",
)
class EvaluationMeasurementTests(unittest.TestCase):
    def test_evaluator_keeps_frames_distinct_and_unwraps_world_heading(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import numpy as np
        from gateway.neural_gait.training import evaluate

        class MeasuredEpisode:
            def __init__(self):
                angle = np.deg2rad(170)
                rotation = np.array([[np.cos(angle), -np.sin(angle), 0],
                                     [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
                self.model = SimpleNamespace(body=lambda name: SimpleNamespace(id=0))
                self.data = SimpleNamespace(qpos=np.zeros(15), xmat=rotation.reshape(1, 9))
                self.qadr = np.arange(3, 15)
                self.last_target = self.last_action = np.zeros(12)
                self.steps = 0
                self.closed = False

            def reset(self, seed, options=None):
                return np.zeros(148), {}

            def step(self, action):
                self.steps += 1
                self.last_target = np.full(12, self.steps)
                self.data.qpos[:3] += [.1, .2, 0]
                self.data.qpos[self.qadr] = np.deg2rad(self.last_target-2.5)
                info = dict(upright=.99, velocity_body_m_s=[1, 2, 3],
                    velocity_command_m_s=[.2, .1], heading_rad=np.deg2rad(-180+self.steps*10),
                    contact_slip_speed_squared_m2_s2=.01 if self.steps == 1 else .03,
                    foot_fit=[.5, 1, 1, 1] if self.steps == 2 else [1]*4,
                    jammed_joints=int(self.steps == 2), target_rejected=False, fallen=False,
                    travel_reward=.5)
                return np.zeros(148), 1., False, self.steps == 2, info

            def foot_measurements(self):
                return dict(contact=[True, False, True, False], clearance_m=[0, .02, 0, .03])

            def close(self):
                self.closed = True

        episode = MeasuredEpisode()
        config = SimpleNamespace(control_hz=2, episode_seconds=1, command=[.08, 0, 0],
                                 execution_backend="kinematic", foot_action_scale_mm=[30,20,30])
        episode.config = config
        with patch("gateway.neural_gait.training.make_environment", return_value=episode):
            result = evaluate(None, config, seeds=(1,))
        row = result["episodes"][0]
        self.assertTrue(episode.closed)
        np.testing.assert_allclose(row["displacement_m"], [.2, .4, 0])
        np.testing.assert_allclose(row["body_frame_travel_m"], [1, 2, 3])
        np.testing.assert_allclose(row["command_reference_travel_m"], [.2, .1])
        self.assertAlmostEqual(row["world_heading_unwrapped_rad"], np.deg2rad(200))
        self.assertAlmostEqual(row["heading_change_rad"], np.deg2rad(30))
        self.assertAlmostEqual(row["maximum_heading_deviation_rad"], np.deg2rad(30))
        self.assertAlmostEqual(row["mean_contact_slip_speed_squared_m2_s2"], .02)
        self.assertAlmostEqual(row["maximum_joint_tracking_error_deg"], 2.5)
        self.assertEqual(row["motion_metric_means"]["requested_foot_step_squared_mm2"], 0)
        self.assertEqual(row["motion_metric_means"]["target_step_squared_deg2"], 1)
        self.assertEqual(row["motion_metric_means"]["target_acceleration_squared_deg2_s4"], 8)
        self.assertEqual(row["fit_reduced_frames"], 1)
        self.assertEqual(row["jam_frames"], 1)
        self.assertEqual(row["mean_total_reward_per_step"], 1.)
        self.assertEqual(row["mean_travel_reward_per_step"], .5)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(importlib.util.find_spec("numpy"), "Use gait-training environment")
class VirtualBodySensorTests(unittest.TestCase):
    """Real body executor, ADC filter, position owner and PCA register writes."""

    def setUp(self):
        import numpy as np
        from gateway.neural_gait.native import BodyModel, VirtualBody
        self.np = np
        robot = robot_fixture()
        robot["feedback"]["stand_enabled"] = True
        # Exercise model-joint / PWM-channel distinction, including inversion.
        for m in robot["calibration"]:
            m["channel"] = (m["id"] + 5) % 12
        self.body = BodyModel(robot)
        self.pose = np.array([0, 3.46, -21.63] * 4)
        self.executor = VirtualBody(self.body, self.pose, joint_speed_deg_s=60/.11,
                                    balance=False, heading_feedback=False)
        self.addCleanup(self.body.close)
        self.addCleanup(self.executor.close)
        self.now = 0
        self.seq = 0
        self.executor.reset(0, 1)
        self.assertEqual(self.executor.receive(dict(t="welcome", ver=1, epoch=1,
            profile="home", command_deadline_v1=True), 1, 0), [])
        self.geometry = "compact-35-20-28-38-55-visible-20261005"

    def send(self, **command):
        self.seq += 1
        return self.executor.receive(dict(seq=self.seq, epoch=1,
            deadline_ms=self.now//1000+10000, **command), 1, self.now)

    def step(self, *, track=True, heartbeat=True):
        self.now += 20000
        self.body.feedback_sample(self.body.raw_samples(self.pose), self.pose,
                                  self.np.ones(12)*self.now)
        for timestamp in range(self.now-15000, self.now+1, 5000):
            self.body.imu_sample(timestamp, [0, 0, 9.80665], [0, 0, 0])
        output = self.executor.tick(self.now)
        if track:
            self.pose = output["physical_angles"]
        if heartbeat and self.now % 1000000 == 0:
            self.executor.receive(dict(t="ping"), 1, self.now)
        return output

    def start(self):
        result = self.send(t="intent", name="walk", dir="fwd", steps=0, speed=30,
            source="host", geometry=self.geometry, reference_cd=[0,346,-2163]*4,
            twist=[.08,0,0])
        self.assertEqual(result, [dict(t="ack",seq=1)])
        return self.seq

    def target(self, owner, sample, lift=20):
        return self.send(t="walk_target", walk=owner, sample=sample,
            geometry=self.geometry, feet_mm=[0,0,0,0,0,0,0,0,lift,0,0,0])

    def test_actual_pwm_bus_matches_pure_conversion_with_nonidentity_channels(self):
        expected = self.body.pwm_output(self.pose)
        actual = self.executor.tick(0)
        self.np.testing.assert_allclose(actual["logical_angles"], self.pose, atol=.00001)
        self.np.testing.assert_allclose(actual["physical_angles"], expected["physical_angles"], atol=.00001)
        self.np.testing.assert_allclose(actual["physical_pulse_us"], expected["physical_pulse_us"], atol=.00001)
        self.assertTrue(actual["joint_enabled"].all())
        with self.assertRaisesRegex(RuntimeError, "Close the virtual"):
            self.body.reset()

    def test_telemetry_uses_actual_filtered_feedback_without_actuating(self):
        owner = self.start()
        before = self.step()
        packet = self.executor.telemetry(self.now)
        data = packet["data"]
        self.assertEqual(data["motion"]["sequence"], owner)
        self.assertEqual(data["motion"]["nominal_sample"], 0)
        self.assertEqual(data["motion"]["walk_source"], "host")
        feedback = data["joint_feedback"]
        self.assertEqual(feedback["usable_mask"], 4095)
        self.assertEqual(feedback["sampled_us"], [self.now]*12)
        self.np.testing.assert_allclose(feedback["filtered_model_deg"], [0,3.46,-21.63]*4, atol=.2)
        self.executor.telemetry(self.now)
        after = self.executor.tick(self.now)
        self.np.testing.assert_array_equal(before["logical_pwm_us"], after["logical_pwm_us"])
        self.assertEqual(before["output_generation"], after["output_generation"])
        self.assertEqual(before["execution"], after["execution"])

    def test_finish_stays_owned_until_real_feedback_arrives_and_reports_jam(self):
        owner = self.start()
        self.assertEqual(self.target(owner, 1), [dict(t="ack",seq=2)])
        for _ in range(100): self.step()
        self.assertEqual(self.send(t="intent", name="walk", dir="fwd", steps=0,
            speed=0, source="host", update=owner, twist=[0,0,0]), [dict(t="ack",seq=3)])
        stalled = []
        for _ in range(200): stalled.extend(self.step(track=False)["messages"])
        self.assertFalse(any(m["t"]=="done" for m in stalled))
        self.assertTrue(any(m.get("name")=="servo_stall" and m["seq"]==owner for m in stalled))
        self.assertEqual(self.executor.telemetry(self.now)["data"]["motion"]["sequence"],owner)
        terminal = []
        for _ in range(400):
            terminal.extend(self.step()["messages"])
            if any(m["t"]=="done" for m in terminal): break
        self.assertIn(dict(t="done",seq=owner,position_verified=True,target_adjusted_joints=0),terminal)
        self.assertEqual(self.target(owner,2)[0]["t"],"nak")

    def test_release_retires_owner_and_duplicate_release_still_disables(self):
        owner=self.start();self.target(owner,1);self.step()
        self.assertEqual(self.send(t="stop",detach=True),[dict(t="ack",seq=3)])
        result=self.step()
        self.assertFalse(result["joint_enabled"].any())
        self.assertEqual(self.executor.telemetry(self.now)["data"]["joint_feedback"]["commanded_mask"],0)
        self.assertIn(dict(t="cancelled",seq=owner,code="stop"),result["messages"])
        generation=result["output_generation"]
        duplicate=dict(t="stop",detach=True,seq=3,epoch=1,deadline_ms=10000)
        self.assertEqual(self.executor.receive(duplicate,1,self.now)[0]["code"],"stale")
        self.assertGreater(self.executor.tick(self.now)["output_generation"],generation)
        self.assertEqual(self.target(owner,2)[0]["t"],"nak")
        self.assertFalse(self.executor.tick(self.now)["joint_enabled"].any())


    def test_silent_connection_uses_existing_supervisor_finish(self):
        owner = self.start()
        self.target(owner, 1)
        for _ in range(300):
            self.step(heartbeat=False)
        self.assertEqual(self.target(owner, 2)[0]["code"], "stale")
        # Connection loss ends continuous Walk locally, preserving supported
        # landing and powered final pose. It does not fabricate a remote receipt.
        for _ in range(300):
            self.step(heartbeat=False)
        self.assertEqual(self.executor.telemetry(self.now)["data"]["motion"]["phase"], "hold")
        self.assertTrue(self.executor.tick(self.now)["joint_enabled"].all())

    def test_reconnect_retains_body_fault_notice_without_routing_old_terminal(self):
        owner=self.start();self.target(owner,1)
        for _ in range(100):self.step()
        self.executor.connection_lost(1)
        for _ in range(200):
            self.assertEqual(self.step(track=False,heartbeat=False)["messages"],[])
        self.executor.reset(self.now,2)
        notices=self.executor.receive(dict(t="welcome",ver=1,epoch=2,
            profile="home",command_deadline_v1=True),2,self.now)
        self.assertTrue(any(m.get("name")=="servo_stall" and m["seq"]==owner for m in notices))
        self.assertFalse(any(m["t"] in {"done","cancelled"} for m in notices))
        old=self.executor.receive(dict(t="walk_target",seq=5,epoch=1,deadline_ms=20000,
            walk=owner,sample=2,geometry=self.geometry,feet_mm=[0]*12),1,self.now)
        self.assertEqual(old[0]["code"],"stale")


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "Use gait-training environment")
class TerrainScenarioTests(unittest.TestCase):
    """Explicit robot-scale scenes; no installed-room/material claims."""

    def environment(self, scenarios):
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        env=GaitEnvironment(EnvironmentConfig(robot=robot_fixture(),scenarios=scenarios),
                            include_assembly=False,include_visuals=False)
        self.addCleanup(env.close)
        return env

    def test_empty_scenarios_keep_original_flat_xml_and_randomization_draws(self):
        from gateway.neural_gait.environment import EnvironmentConfig,build_xml
        import xml.etree.ElementTree as ET
        import numpy as np
        config=EnvironmentConfig(robot=robot_fixture())
        root=ET.fromstring(build_xml(config,include_assembly=False,include_visuals=False))
        world=root.find("worldbody")
        self.assertEqual([g.attrib for g in world.findall("geom")],[dict(
            name="floor",type="plane",size="3 3 .05",rgba=".3 .35 .4 1")])
        env=self.environment([]);env.reset(seed=123)
        expected=np.random.default_rng(123)
        expected.uniform(1,1);expected.uniform(1,1)
        # Sensor acquisition consumes twelve ADC and two three-axis noise draws.
        expected.normal(0,0,3);expected.normal(0,0,3);expected.normal(0,0,12)
        self.assertEqual(env.np_random.bit_generator.state,expected.bit_generator.state)
        self.assertEqual(env.scenario_id,"flat")
        np.testing.assert_array_equal(env.model.geom_quat[env.model.geom("floor").id],[1,0,0,0])

    def test_seeded_selection_activates_only_named_terrain_and_preserves_friction(self):
        import numpy as np
        scenes=[dict(id="rock",geoms=[dict(kind="rock",position_m=[.18,0,.01],size_m=[.02,.03,.015])]),
                dict(id="slip",geoms=[dict(kind="friction_patch",position_m=[.2,0,.002],
                    size_m=[.06,.05,.002],friction=.12)])]
        env=self.environment(scenes)
        _,first=env.reset(seed=31)
        _,again=env.reset(seed=31)
        self.assertEqual(first["scenario_id"],again["scenario_id"])
        _,info=env.reset(seed=31,options={"scenario":"slip"})
        self.assertEqual(info["scenario_id"],"slip")
        rock=env.model.geom("terrain_0_0").id;patch=env.model.geom("terrain_1_0").id
        self.assertFalse(env._terrain_mask()[rock]);self.assertTrue(env._terrain_mask()[patch])
        self.assertEqual(env.model.geom_contype[rock],0)
        self.assertAlmostEqual(env.model.geom_friction[patch,0],.12)
        self.assertAlmostEqual(env.model.geom_size[patch,2]*2,.004)
        _,_,_,_,step=env.step(np.zeros(12));self.assertEqual(step["scenario_id"],"slip")

    def test_rotated_start_is_nonpenetrating_against_slope_and_robot_sized_block(self):
        import mujoco
        import numpy as np
        from scipy.spatial.transform import Rotation
        env=self.environment([dict(id="fall",slope_deg=[5,8],start_rpy_deg=[75,10,0],
            geoms=[dict(kind="block",position_m=[0,.02,.012],size_m=[.035,.04,.012]),
                   dict(kind="wall",position_m=[.3,0,.06],size_m=[.008,.15,.06])])])
        env.reset(seed=2)
        expected=Rotation.from_euler("xyz",[75,10,0],degrees=True).as_matrix()
        np.testing.assert_allclose(env.data.xmat[env.model.body("torso").id].reshape(3,3),expected,atol=1e-12)
        floor=env.model.geom("floor").id
        np.testing.assert_allclose(env.data.geom_xmat[floor].reshape(3,3),
            Rotation.from_euler("xy",[5,8],degrees=True).as_matrix(),atol=1e-12)
        robot=np.flatnonzero((env.model.geom_bodyid!=0)&
            ((env.model.geom_contype!=0)|(env.model.geom_conaffinity!=0)))
        minimum=min(mujoco.mj_geomDistance(env.model,env.data,int(g),int(t),1e6,None)
                    for g in robot for t in np.flatnonzero(env._terrain_mask()))
        self.assertGreaterEqual(minimum,.001-1e-8)
        self.assertTrue(np.isfinite(env.foot_measurements()["clearance_m"]).all())

    def test_finite_off_grid_push_applies_configured_impulse_then_clears(self):
        import mujoco
        import numpy as np
        from gateway.neural_gait.environment import GaitEnvironment
        env=GaitEnvironment.__new__(GaitEnvironment)
        env.model=mujoco.MjModel.from_xml_string('<mujoco><option timestep=".002" gravity="0 0 0"/>'
            '<worldbody><body name="torso" pos="0 0 1"><freejoint/><geom type="sphere" size=".04" mass=".65"/>'
            '</body></worldbody></mujoco>')
        env.data=mujoco.MjData(env.model)
        env.scenario=dict(pushes=[dict(start_s=.003,duration_s=.015,force_n=[.5,0,0])])
        impulse=np.zeros(3)
        for _ in range(20):
            env._apply_scenario_pushes()
            impulse+=env.data.xfrc_applied[1,:3]*env.model.opt.timestep
            mujoco.mj_step(env.model,env.data)
        np.testing.assert_allclose(impulse,[.0075,0,0],atol=1e-15)
        self.assertAlmostEqual(env.data.qvel[0],.0075/.65,places=12)
        np.testing.assert_array_equal(env.data.xfrc_applied[1],np.zeros(6))

    def test_slip_uses_actual_sloped_terrain_contact_tangent(self):
        import mujoco
        import numpy as np
        from types import SimpleNamespace
        from gateway.neural_gait.contract import LEGS
        from gateway.neural_gait.environment import GaitEnvironment
        bodies="".join(f'<body name="{leg}_pickup_body" pos="{i*.2} 0 {-i*.2*.3+.02}">'
            '<freejoint/><geom type="sphere" size=".04" mass=".1625"/></body>' for i,leg in enumerate(LEGS))
        env=GaitEnvironment.__new__(GaitEnvironment)
        env.model=mujoco.MjModel.from_xml_string('<mujoco><compiler angle="radian"/><worldbody>'
            '<geom name="floor" type="plane" size="2 2 .1" euler="0 .291456794 0"/>'+bodies+'</worldbody></mujoco>')
        env.data=mujoco.MjData(env.model);env.config=SimpleNamespace(scenarios=[dict(id="slope")])
        normal=np.array([.3,0,1])/np.sqrt(1.09)
        for i in range(4):env.data.qvel[i*6:i*6+3]=normal
        mujoco.mj_forward(env.model,env.data)
        self.assertGreater(env.data.ncon,0)
        self.assertLess(env._contact_slip_speed_squared(),1e-15)
        env.data.qvel[0:3]=[0,1,0];mujoco.mj_forward(env.model,env.data)
        expected=0.;force=np.zeros(6);jac=np.zeros((3,env.model.nv))
        for i,c in enumerate(env.data.contact[:env.data.ncon]):
            other=c.geom2 if c.geom1==0 else c.geom1
            mujoco.mj_contactForce(env.model,env.data,i,force)
            mujoco.mj_jac(env.model,env.data,jac,None,c.pos,int(env.model.geom_bodyid[other]))
            velocity=jac@env.data.qvel; n=c.frame[:3];tangent=velocity-np.dot(velocity,n)*n
            expected+=max(0.,force[0])*np.dot(tangent,tangent)
        expected/=mujoco.mj_getTotalmass(env.model)*np.linalg.norm(env.model.opt.gravity)
        self.assertGreater(expected,0.)
        self.assertAlmostEqual(env._contact_slip_speed_squared(),expected,places=12)

    def test_active_block_is_in_collision_tree_and_boot_clearance_uses_its_top(self):
        import mujoco
        import numpy as np
        env=self.environment([dict(id="platform",geoms=[dict(kind="block",
            position_m=[0,0,.01],size_m=[.25,.25,.01])]),dict(id="empty")])
        env.reset(seed=4,options={"scenario":"platform"})
        block=env.model.geom("terrain_0_0").id
        measured=env.foot_measurements()
        self.assertLessEqual(min(measured["clearance_lower_bound_m"]),.001+1e-6)
        for value,valid in zip(measured["clearance_m"],measured["clearance_valid"]):
            if valid:self.assertAlmostEqual(value,.001,places=6)
        self.assertAlmostEqual(env.terrain_height(0,0),.02,places=10)
        self.assertFalse(any(measured["contact"]))
        env.data.qpos[2]-=.002;mujoco.mj_forward(env.model,env.data)
        self.assertTrue(any(block in (c.geom1,c.geom2) for c in env.data.contact[:env.data.ncon]))
        measured=env.foot_measurements()
        self.assertLess(min(measured["clearance_m"]),0)
        self.assertTrue(any(measured["contact"]))
        env.reset(seed=4,options={"scenario":"empty"})
        env.data.qpos[2]-=.002;mujoco.mj_forward(env.model,env.data)
        self.assertFalse(any(block in (c.geom1,c.geom2) for c in env.data.contact[:env.data.ncon]))
        self.assertAlmostEqual(min(env.foot_measurements()["clearance_m"]),-.001,places=5)

    def test_contradicted_zero_distance_is_labelled_bound_not_contact(self):
        import mujoco
        from unittest.mock import patch
        env=self.environment([dict(id="platform",geoms=[dict(kind="block",
            position_m=[0,0,.01],size_m=[.25,.25,.01])])])
        env.reset(seed=4);env.data.qpos[2]+=.15;mujoco.mj_forward(env.model,env.data)
        block=env.model.geom("terrain_0_0").id
        original=mujoco.mj_geomDistance
        def query(model,data,a,b,maximum,segment):
            return 0. if block in (a,b) else original(model,data,a,b,maximum,segment)
        with patch("gateway.neural_gait.environment.mujoco.mj_geomDistance",side_effect=query):
            measured=env.foot_measurements()
        self.assertFalse(any(measured["clearance_valid"]))
        self.assertFalse(any(measured["contact"]))
        self.assertTrue(all(value>0 for value in measured["clearance_lower_bound_m"]))

    def test_fallen_spawn_keeps_upright_height_reference_and_elevated_height_is_relative(self):
        import numpy as np
        env=self.environment([dict(id="upright"),dict(id="side",start_rpy_deg=[90,0,0]),
            dict(id="elevated",geoms=[dict(kind="block",position_m=[0,0,.02],size_m=[.25,.25,.02])])])
        env.reset(seed=1,options={"scenario":"upright"});standing=env.standing_height
        env.reset(seed=1,options={"scenario":"side"})
        self.assertAlmostEqual(env.standing_height,standing,places=10)
        env.reset(seed=1,options={"scenario":"elevated"})
        self.assertAlmostEqual(env.standing_height,standing,places=10)
        env.target_rejected=False
        metrics=env._advance_physics()
        self.assertAlmostEqual(metrics["terrain_height_m"],.04,places=10)
        self.assertAlmostEqual(metrics["body_clearance_m"],env.data.qpos[2]-.04,places=10)

    def test_far_terrain_is_pruned_without_distance_queries_or_skipping_measurements(self):
        import mujoco
        import numpy as np
        from unittest.mock import patch
        env=self.environment([dict(id="far",slope_deg=[0,5],geoms=[
            dict(kind="rock",position_m=[2,0,.02],size_m=[.03,.02,.02]),
            dict(kind="wall",position_m=[3,0,.1],size_m=[.01,.2,.1])])])
        env.reset(seed=5)
        # Full cached boot vertices still measure every requested frame; no
        # distant convex query can beat the exact plane-support minimum.
        with patch("gateway.neural_gait.environment.mujoco.mj_geomDistance",
                   side_effect=AssertionError("Distant terrain must be pruned")):
            airborne=env.foot_measurements()
            env.data.qpos[2]-=.002;mujoco.mj_forward(env.model,env.data)
            touching=env.foot_measurements()
        self.assertTrue(all(airborne["clearance_valid"]))
        self.assertTrue(all(touching["clearance_valid"]))
        self.assertTrue(any(touching["contact"]))
        np.testing.assert_allclose(np.array(airborne["clearance_m"])-touching["clearance_m"],
            .002*np.cos(np.deg2rad(5)),atol=1e-9)


@unittest.skipUnless(
    importlib.util.find_spec("mujoco") and importlib.util.find_spec("numpy"),
    "Use the gait-training environment for locomotion rewards",
)
class LocomotionRewardTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig
        self.np = np
        self.config = EnvironmentConfig(robot=robot_fixture(), reward_profile="locomotion")

    def score(self, command, measured, **changes):
        from gateway.neural_gait.environment import locomotion_reward
        zeros = self.np.zeros(12)
        arguments = dict(vertical_velocity=0., angular_velocity_xy=[0., 0.],
            joint_velocity=zeros, previous_joint_velocity=zeros, joint_torque=zeros,
            action=zeros, previous_action=zeros, contact_slip_speed_squared=0.,
            config=self.config)
        arguments.update(changes)
        return locomotion_reward(measured[:2], measured[2], command, 1., 1., **arguments)

    def test_small_speed_and_turn_tracking_distinguish_rest_and_wrong_direction(self):
        for requested in ([.015, 0, 0], [.03, 0, 0], [-.03, 0, 0], [0, 0, .5]):
            correct, terms = self.score(requested, requested)
            stationary, _ = self.score(requested, [0, 0, 0])
            wrong, _ = self.score(requested, [-value for value in requested])
            self.assertGreater(correct, stationary)
            self.assertGreater(stationary, wrong)
            self.assertAlmostEqual(correct*self.config.control_hz, 1.5)
            self.assertEqual(terms["joint_acceleration"], 0.)
        # At 15 mm/s, rest earns 77.9% of perfect linear tracking, not the
        # near-perfect 99.91% caused by copying Go1's dimensional bandwidth.
        _, stationary = self.score([.015, 0, 0], [0, 0, 0])
        self.assertAlmostEqual(stationary["tracking_linear"]*self.config.control_hz,
                               math.exp(-.25))
        stopped, _ = self.score([0, 0, 0], [0, 0, 0])
        moving, _ = self.score([0, 0, 0], [.03, 0, 0])
        self.assertGreater(stopped, moving)

    def test_actual_joint_acceleration_and_slip_cost_without_target_changes(self):
        np = self.np
        command = [.03, 0, 0]
        smooth, smooth_terms = self.score(command, command,
            joint_velocity=np.ones(12), previous_joint_velocity=np.ones(12))
        jerky, jerky_terms = self.score(command, command,
            joint_velocity=np.ones(12), previous_joint_velocity=-np.ones(12))
        self.assertLess(jerky, smooth)
        self.assertEqual(smooth_terms["joint_acceleration"], 0.)
        self.assertEqual(jerky_terms["action_change"], 0.)
        expected = 12*(2*self.config.control_hz)**2*2.5e-7/self.config.control_hz
        self.assertAlmostEqual(smooth-jerky, expected)
        sliding, _ = self.score(command, command,
            joint_velocity=np.ones(12), previous_joint_velocity=np.ones(12),
            contact_slip_speed_squared=.03**2)
        self.assertAlmostEqual(smooth-sliding, .1/self.config.control_hz)

    def test_reward_profile_serializes_and_historical_reward_stays_legacy(self):
        from dataclasses import asdict
        import json
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        restored = EnvironmentConfig(**json.loads(json.dumps(asdict(self.config))))
        self.assertEqual(restored.reward_profile, "locomotion")
        self.assertEqual(restored.locomotion_reward_weights, self.config.locomotion_reward_weights)
        old = asdict(self.config)
        for field in ("reward_profile", "locomotion_tracking_width_m_s",
                      "locomotion_tracking_width_rad_s", "locomotion_reward_weights"):
            old.pop(field)
        historical = EnvironmentConfig(**old)
        self.assertEqual(historical.reward_profile, "legacy")
        env = GaitEnvironment(historical)
        self.addCleanup(env.close)
        env.reset(seed=3)
        _, reward, _, _, info = env.step(self.np.zeros(12))
        parts = info["reward_components"]
        self.assertEqual(set(parts), {"progress", "overspeed", "cross_track",
                                     "slip", "effort", "action_change"})
        self.assertAlmostEqual(reward, parts["progress"]-sum(
            value for key, value in parts.items() if key != "progress"))

    def test_native_targets_use_measured_interval_acceleration_and_reset(self):
        from dataclasses import replace
        from unittest.mock import patch
        from gateway.neural_gait import environment
        np = self.np
        env = environment.make_environment(replace(self.config, execution_backend="body_control"),
            include_assembly=False, include_visuals=False)
        self.addCleanup(env.close)
        for _ in range(2):
            env.reset(seed=4)
            initial = env.data.qvel[env.vadr].copy()
            with patch.object(environment, "locomotion_reward",
                              wraps=environment.locomotion_reward) as score:
                action = np.array([.1, 0., .15]*4)
                observation, reward, terminated, _, info = env.step(action)
                self.assertFalse(terminated, info)
                self.assertEqual(info["execution_backend"], "body_control")
                self.assertEqual(info["ack"]["t"], "ack")
                self.assertEqual(info["consumed_sample"], 1)
                self.assertNotEqual(reward, 0.)
                supplied = score.call_args.kwargs
                np.testing.assert_array_equal(supplied["previous_joint_velocity"], initial)
                np.testing.assert_array_equal(supplied["joint_velocity"], env.data.qvel[env.vadr])
                self.assertAlmostEqual(reward, sum(value if key.startswith("tracking_") else -value
                    for key, value in info["reward_components"].items()))
                feedback = env.session.connection.last_status["imu"]["joint_feedback"]
                np.testing.assert_allclose(observation[:12],
                    np.deg2rad(feedback["filtered_model_deg"]), rtol=1e-6, atol=1e-7)
            # A prior episode's velocity must not enter the next episode.
            env.data.qvel[env.vadr] = 7.
