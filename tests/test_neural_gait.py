"""Shared sensor contract and real closed-loop simulator regression coverage."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from gateway.neural_gait.contract import (
    JOINTS,
    OBSERVATION_SIZE,
    SCHEMA,
    vector,
    foot_offsets,
)
from gateway.neural_gait.client import observation
from tests.test_neural_gait_sensors import robot_fixture


@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("scipy"),
                     "Use the native gait environment")
class VirtualGatewayTests(unittest.IsolatedAsyncioTestCase):
    """Real WebSocket/gateway/P4 executor; ideal sensors isolate transport lifecycle."""

    async def asyncSetUp(self):
        import numpy as np
        from gateway.neural_gait.native import BodyModel, VirtualBody
        from gateway.neural_gait.virtual import VirtualGatewaySession
        self.np = np
        self.now = 1000000
        self.pose = np.array([0, 3.46, -21.63]*4)
        self.body = BodyModel(robot_fixture())
        self.executor = VirtualBody(self.body, self.pose, joint_speed_deg_s=60/.11,
            motion_rate=1., balance=False, heading_feedback=False,
            balance_tuning=[1.,1.,0.,0.], idle_rest_seconds=0)
        self.environment = {"reference_joint_deg":self.pose.tolist(),
            "target_limits_deg":[[-90,90]]*12, "foot_action_scale_mm":[30,20,30]}
        self.session = VirtualGatewaySession(self.executor, self.environment, lambda:self.now,
            {"source":"neural","forward_m_s":.015,"lateral_m_s":.01,"yaw_rad_s":.12})
        await self.session.start()
        self.feed(self.pose)

    async def asyncTearDown(self):
        await self.session.close()
        self.executor.close()
        self.body.close()

    def feed(self, angles):
        self.measured = self.np.asarray(angles).copy()
        self.body.feedback_sample(self.body.raw_samples(angles), angles,
            self.body.sample_times(self.now/1e6)*1e6)
        self.body.imu_sample(self.now, [0,0,9.80665], [0,0,0])

    async def advance(self):
        output = self.executor.tick(self.now)
        self.now += 20000
        # Ideal joint following is a test fixture, not a simulated floor trial.
        self.feed(self.np.where(output["joint_enabled"], output["logical_angles"], self.measured))
        await self.session.publish(output["messages"])
        await self.session.telemetry()
        return output

    async def begin(self):
        await self.session.start_walk({"dir":"fwd","steps":0,"speed":100})
        for _ in range(10):
            await self.advance()
            if self.session.observation_ready:
                break
        self.assertTrue(self.session.observation_ready)
        return await self.session.observation()

    async def test_rendered_jpeg_uses_real_camera_transport_and_metric_owner(self):
        import asyncio
        from unittest.mock import patch
        import cv2
        calls = []
        # Only network inference is a fixture. Real framing, camera ownership,
        # timestamp association and gateway delivery execute below.
        def process(worker, robot, epoch, counter, received, jpeg, timestamp, config, attitude=None):
            calls.append((jpeg, config, attitude))
            return dict(available=False, robotId=robot, epoch=epoch, frameCounter=counter,
                receivedAtMonotonic=received, source="test-image-worker", reason="test fixture",
                depthSpatial={"available":False})
        profile = dict(resolution="VGA", capture_hz=1, max_frame_age_s=1.,
            processing=dict(mode="moge-open3d", resolution_level=0))
        with patch("gateway.depth_motion.DepthMotion.process", process):
            await self.session.enable_camera(profile)
            await self.session.telemetry()
            jpeg=cv2.imencode('.jpg', self.np.zeros((32,32,3),dtype=self.np.uint8))[1].tobytes()
            await self.session.camera_frame(dict(counter=17,jpeg=jpeg,completed_us=self.now),profile)
            async def delivered():
                while not self.session.camera.locomotion_measurement(self.session.robot_id).get('frameCurrent'):
                    await asyncio.sleep(.005)
            await asyncio.wait_for(delivered(),5)
        self.assertEqual(calls[0][0],jpeg)
        self.assertEqual(calls[0][2]['frame_completed_us'],self.now)
        self.assertEqual(calls[0][1]['mode'],'moge-open3d')
        measurement=self.session.gateway.locomotion_measurement(self.session.robot_id)
        self.assertEqual(measurement['source'],'test-image-worker')
        self.assertFalse(measurement['available'])
        self.assertNotIn('position',measurement)

    async def test_virtual_body_reconnect_preserves_camera_owner_and_retires_old_walk(self):
        from unittest.mock import AsyncMock, Mock
        camera=Mock()
        camera.configure_depth=AsyncMock()
        camera.aclose=AsyncMock()
        self.session.camera=camera
        self.session.client.environment['depth_camera']={'processing':{'mode':'moge-open3d'}}
        await self.begin()
        old_epoch=self.session.robot.epoch
        old_gateway=self.session.gateway
        # This test reuses the executor; a training environment replaces it
        # after closing the old device. Transport identity/lifecycle is real.
        await self.session.reconnect_body(self.executor)
        self.assertIs(self.session.gateway,old_gateway)
        self.assertIs(self.session.camera,camera)
        self.assertGreater(self.session.robot.epoch,old_epoch)
        self.assertIsNone(self.session.walk)
        camera.aclose.assert_not_awaited()
        camera.configure_depth.assert_awaited_once()
        self.feed(self.pose)
        await self.begin()


    async def test_real_body_control_transport_preserves_admission_consumption_and_finish(self):
        import asyncio
        from gateway.neural_gait.virtual import VirtualWalkEnded
        observed = await self.begin()
        self.assertEqual(observed["command"], [.015,0,0])
        self.assertEqual(observed["previous_action"], [0.]*12)
        admitted = await self.session.action([0.]*12)
        self.assertEqual(admitted["ack"]["t"], "ack")
        self.assertEqual(admitted["consumed_sample"], 0, "Admission is not device consumption")
        for _ in range(100):
            await self.advance()
            observed = await self.session.observation()
            if self.session.execution_info()["consumed_sample"]:
                break
            await self.session.action([0.]*12)
        self.assertGreater(self.session.execution_info()["consumed_sample"], 0)
        original = self.session.walk
        before = self.now
        await self.session.update_walk({"dir":"fwd","steps":0,"speed":50,"forward":100,"turn":20})
        updated = await self.session.observation()
        self.assertEqual(updated["command"], [.0075,0,.012])
        self.assertEqual(self.now, before, "Steering must not reset or advance simulated hardware")
        finish = await self.session.finish()
        await self.session.connection.wait_acknowledged(finish, timeout=None)
        self.assertEqual(self.session.walk, original)
        for _ in range(150):
            await self.advance()
            await asyncio.sleep(0)
            if original in self.session.connection.completed:
                break
        terminal = self.session.connection.completed[original]
        self.assertEqual(terminal["t"], "done", terminal)
        with self.assertRaises(VirtualWalkEnded) as ended:
            await self.session.observation()
        self.assertEqual(ended.exception.terminal, terminal)

    async def test_real_body_stop_release_and_reconnect_cancel_pending_policy_work(self):
        import asyncio
        from gateway.neural_gait.virtual import VirtualWalkEnded
        for release in (False,True):
            await self.begin()
            original = self.session.walk
            stop = await self.session.stop(release=release)
            await self.session.connection.wait_acknowledged(stop, timeout=None)
            # Physical output runs independently: Release disables PWM at
            # admission, then the next normal body tick emits cancellation.
            await self.advance()
            with self.assertRaises(VirtualWalkEnded) as ended:
                await asyncio.wait_for(self.session.observation(), 2)
            self.assertEqual(ended.exception.terminal["seq"], original)
            self.assertEqual(ended.exception.terminal["t"], "cancelled")
            with self.assertRaises(VirtualWalkEnded):
                _ = self.session.observation_ready
            self.assertIsNone(self.session.connection.neural_walk)
        await self.begin()
        original_connection = self.session.connection
        original = self.session.walk
        await self.session.robot.close()
        await self.session.robot.connect()
        await asyncio.sleep(0)
        self.assertNotEqual(self.session.connection.epoch, original_connection.epoch)
        self.assertIsNone(original_connection.neural_walk)
        self.assertEqual(original_connection.completed[original]["code"], "disconnect")

    async def test_start_waits_for_native_admission_before_initial_tick(self):
        import asyncio
        from unittest.mock import patch
        from gateway.neural_gait.virtual import VirtualRobot, VirtualGatewaySession
        await self.session.close()
        gate, sent = asyncio.Event(), asyncio.Event()
        receive = VirtualRobot._receive
        async def delayed(robot):
            await gate.wait()
            await receive(robot)
        self.session = VirtualGatewaySession(self.executor, self.environment, lambda:self.now,
            {"source":"neural","forward_m_s":.015,"lateral_m_s":.01,"yaw_rad_s":.12})
        async def command_sent(message):
            if message.get("name") == "walk":
                sent.set()
        self.session.gateway.subscribe_commands(command_sent)
        with patch.object(VirtualRobot, "_receive", delayed):
            await self.session.start()
        start = asyncio.create_task(self.session.start_walk({"dir":"fwd","steps":0,"speed":100}))
        try:
            await sent.wait()
            self.assertFalse(start.done(), "A transport write cannot stand in for native admission")
            self.assertEqual(self.now, 1000000)
        finally:
            gate.set()
        sequence = await start
        self.assertTrue(self.session.connection.pending[sequence].acknowledged)

    async def test_native_target_rejection_is_returned_as_actual_negative_receipt(self):
        await self.begin()
        self.session.connection.neural_walk.geometry = "wrong-geometry-fixture"
        result = await self.session.action([0.]*12)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["ack"]["t"], "nak")
        self.assertEqual(result["ack"]["seq"], result["sequence"])
        self.assertEqual(result["consumed_sample"], 0)

    async def test_failed_learner_output_requests_actual_finish_without_faking_body_terminal(self):
        import asyncio
        from gateway.neural_gait.virtual import VirtualProducerFailed
        await self.begin()
        original = self.session.walk
        with self.assertRaises(VirtualProducerFailed) as failed:
            await asyncio.wait_for(self.session.action([float("nan")]*12), 2)
        diagnostic = failed.exception.diagnostic
        self.assertEqual(diagnostic["walk"], original)
        self.assertEqual(diagnostic["event"], "neural_gait")
        finish = self.session.connection.pending[diagnostic["finish_sequence"]].command
        self.assertEqual((finish["update"], finish["speed"]), (original, 0))
        self.assertIn(original, self.session.connection.pending,
                      "A producer failure must not manufacture physical completion")


    async def test_fall_event_uses_existing_recovery_bridge_and_real_target_execution(self):
        import asyncio
        from gateway.neural_gait.virtual import VirtualWalkEnded
        generated = []
        recovery_states=[]
        async def generate(endpoint, request):
            generated.append(request)
            recovery_states.append(self.session.gateway.body_sensor_observation(self.session.robot_id)["events"])
            return {"program":[{"name":"move", "arguments":{
                "joint":"front_right_shoulder", "angle_deg":8,
                "reference":"current", "speed_pct":50}}]}
        self.assertIsNone(self.session.recovery)
        recovery = await self.session.enable_recovery("test-generator-boundary", generate=generate)
        await self.begin()
        original = self.session.walk
        initial = self.executor.tick(self.now)
        calibration = await self.session.gateway.body_calibration("get",robot_id=self.session.robot_id)
        speed = await self.session.gateway.body_motion_speed("get",robot_id=self.session.robot_id)
        feedback = self.executor.feedback(self.now)
        self.assertEqual(len(calibration["joints"]),12)
        self.assertAlmostEqual(speed["joint_speed_limit_deg_s"],60/.11,places=3)
        self.assertEqual(len(feedback["joints"]),12)
        self.assertTrue(feedback["stand_enabled"])
        self.np.testing.assert_array_equal(initial["logical_pwm_us"],self.executor.tick(self.now)["logical_pwm_us"])
        # Real estimator and BodyEvents receive a sustained sideways gravity
        # measurement. Ideal joint following here validates the recovery
        # handoff/arrival contract, not physical self-righting or ground contact.
        deadline = asyncio.get_running_loop().time()+12
        while asyncio.get_running_loop().time()<deadline:
            output = self.executor.tick(self.now)
            self.now += 20000
            self.measured = self.np.where(output["joint_enabled"],output["logical_angles"],self.measured)
            self.body.feedback_sample(self.body.raw_samples(self.measured),output["logical_angles"],
                self.body.sample_times(self.now/1e6)*1e6)
            self.body.imu_sample(self.now,[0,9.80665,0],[0,0,0])
            await self.session.publish(output["messages"])
            await self.session.telemetry()
            await asyncio.sleep(.001)
            jobs = list(recovery.jobs.values())
            if jobs and jobs[-1]["state"] in ("completed","error","superseded"):
                break
        self.assertEqual(len(generated),1, recovery.status())
        self.assertTrue(recovery_states[0]['tipped'])
        self.assertTrue(recovery_states[0]['recovering'])
        self.assertIsNone(recovery_states[0]['slip'])
        self.assertEqual(generated[0]["event"]["type"],"tipped")
        self.assertEqual(generated[0]["observation"]["action"]["seq"],original)
        job = list(recovery.jobs.values())[-1]
        self.assertEqual(job["state"],"completed",job.get("error"))
        self.assertTrue(job["receipts"])
        self.assertTrue(all(receipt["t"]=="done" and receipt.get("position_verified") is True
                            for receipt in job["receipts"]))
        self.assertEqual(self.session.connection.completed[original]["t"],"cancelled")
        self.assertIsNone(self.session.connection.neural_walk)
        with self.assertRaises(VirtualWalkEnded):
            await self.session.observation()
        self.assertGreater(self.measured[9],initial["logical_angles"][9]+5)
        self.assertTrue(self.executor.tick(self.now)["armed"])

    async def test_operator_stop_retires_inflight_real_recovery_generation(self):
        import asyncio
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(endpoint, request):
            self.assertEqual(request["event"]["type"],"tipped")
            entered.set()
            await release.wait()
            return {"program":[{"name":"move","arguments":{
                "joint":"front_right_shoulder","angle_deg":8,"reference":"current","speed_pct":50}}]}
        bridge = await self.session.enable_recovery("test-generator-boundary",generate=generate)
        commands = []
        async def record(command): commands.append(command)
        self.session.gateway.subscribe_commands(record)
        await self.begin()
        for _ in range(300):
            output = self.executor.tick(self.now)
            self.now += 20000
            self.body.feedback_sample(self.body.raw_samples(self.pose),output["logical_angles"],
                self.body.sample_times(self.now/1e6)*1e6)
            self.body.imu_sample(self.now,[0,9.80665,0],[0,0,0])
            await self.session.publish(output["messages"])
            await self.session.telemetry()
            if entered.is_set(): break
        self.assertTrue(entered.is_set(),bridge.status())
        sequence = await self.session.stop(release=True)
        await self.session.connection.wait_acknowledged(sequence,timeout=None)
        release.set()
        for _ in range(5): await self.advance()
        self.assertFalse(any(command["t"]=="motion_plan" for command in commands))
        self.assertEqual(list(bridge.jobs.values())[-1]["state"],"superseded")
        self.assertFalse(self.executor.tick(self.now)["joint_enabled"].any())


class ObservationTests(unittest.TestCase):
    def test_history_uses_device_time_and_preserves_walk_heading_across_commands(self):
        import math
        from gateway.neural_gait.contract import ObservationHistory, HISTORY_SCHEMA, HISTORY_ROW_SIZE
        source = self.source()
        environment = dict(target_limits_deg=[[-90,90]]*12, observation_schema=HISTORY_SCHEMA)
        history = ObservationHistory()
        source["feedback"]["device_us"] = 1000000
        first = observation(source, environment, [.015,0,.5], history=history)
        self.assertTrue(all(row == [0.]*HISTORY_ROW_SIZE for row in first["sensor_history"]))
        source["feedback"]["device_us"] = 1100000
        source["imu"]["orientation_wxyz"] = [math.cos(.02/2),0,0,math.sin(.02/2)]
        current = observation(source, environment, [-.03,0,0], history=history)
        self.assertAlmostEqual(current["heading_error_rad"], .05-.02)
        self.assertEqual(current["sensor_history"][0][-1], 1.)
        self.assertAlmostEqual(current["sensor_history"][0][-2], .1)
        self.assertEqual(current["sensor_history"][0][58:61], [.015,0,.5])
        # Repeating a sensor snapshot must not invent elapsed time or fill history.
        self.assertEqual(current, observation(source, environment, [-.03,0,0], history=history))
        self.assertEqual(len(history.samples), 2)
        # New walk and device clock rollback both discard the old walk history.
        fresh = observation(source, environment, [-.03,0,0], history=ObservationHistory())
        self.assertAlmostEqual(fresh["heading_error_rad"], 0.)
        source["feedback"]["device_us"] = 1
        reset = observation(source, environment, [-.03,0,0], history=history)
        self.assertTrue(all(row[-1] == 0 for row in reset["sensor_history"]))

    def test_depth_schema_preserves_existing_sensors_and_missing_depth(self):
        import numpy as np
        from gateway.depth_motion import spatial_depth
        from gateway.neural_gait.contract import DEPTH_SCHEMA, observation_size, SPATIAL_FEATURES
        source = self.source()
        environment = dict(target_limits_deg=[[-90,90]]*12)
        legacy = vector(observation(source, environment, [.08,0,0]))
        environment["observation_schema"] = DEPTH_SCHEMA
        missing = vector(observation(source, environment, [.08,0,0]))
        self.assertEqual(len(missing), observation_size(DEPTH_SCHEMA))
        self.assertEqual(missing[:136], legacy[:136])
        self.assertEqual(missing[-12:], legacy[-12:])
        self.assertEqual(missing[136:-12], [0.]*SPATIAL_FEATURES)
        depth = np.ones((8,8))
        depth[0,0] = np.nan
        grid = spatial_depth(depth, [[8,0,4],[0,8,4],[0,0,1]], units="estimated-metres",
            scale_source="test", intrinsics_source="test")
        seen = vector(observation(source, environment, [.08,0,0],
            vision=dict(depth_available=True,depthSpatial=grid,age_s=.2)))
        self.assertEqual(seen[136],0.)
        self.assertEqual(seen[137],1.)
        self.assertEqual(seen[200],0.)
        self.assertEqual(seen[201],1.)
        self.assertEqual(seen[-15:-12], [1.,0.,0.])

    def source(self):
        return dict(
            joints={
                name: dict(
                    model_deg=18.0,
                    filtered_model_deg=12.0,
                    commanded_model_deg=15.0,
                    velocity_deg_s=2.0,
                    feedback_usable=True,
                    feedback_range_deg=[-20, 100],
                )
                for name in JOINTS
            },
            imu=dict(
                orientation_wxyz=[1, 0, 0, 0],
                angular_rate_rad_s=[0, 0, 0],
                acceleration_m_s2=[0, 0, 9.81],
            ),
            feedback={},
        )

    def test_calibration_measurement_domain_does_not_rescale_policy_actions(self):
        limits = [[-90, 90]] * 12
        source = self.source()
        first = observation(source, {"target_limits_deg": limits}, [0.08, 0, 0])
        source["joints"][JOINTS[0]]["feedback_range_deg"] = [-200, 250]
        second = observation(source, {"target_limits_deg": limits}, [0.08, 0, 0])
        self.assertEqual(first, second)
        self.assertEqual(len(vector(first)), OBSERVATION_SIZE)
        self.assertEqual(foot_offsets([0] * 12, [30,20,30]), [0] * 12)

    def test_missing_feedback_is_marked_unusable_and_missing_imu_is_not_invented(self):
        source = self.source()
        source["joints"][JOINTS[0]]["filtered_model_deg"] = None
        value = observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])
        self.assertFalse(value["joint_usable"][0])
        self.assertFalse(value["vision"]["available"])
        source["imu"] = None
        with self.assertRaisesRegex(ValueError, "No IMU"):
            observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])

    def test_policy_uses_production_filtered_position_without_raw_fallback(self):
        source = self.source()
        value = observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])
        self.assertEqual(value["joint_deg"], [12.0] * 12)
        del source["joints"][JOINTS[0]]["filtered_model_deg"]
        value = observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])
        self.assertFalse(value["joint_usable"][0])
        self.assertEqual(value["joint_deg"][0], 0.0)
        self.assertEqual(source["joints"][JOINTS[0]]["model_deg"], 18.0)

    def test_sensor_ages_and_quality_preserve_per_sensor_timing_and_unknowns(self):
        source = self.source()
        source["feedback"]["device_us"] = 1000000
        source["joints"][JOINTS[0]]["sampled_us"] = 980000
        source["joints"][JOINTS[1]]["sampled_us"] = 990000
        source["joints"][JOINTS[2]]["sampled_us"] = 1000001
        source["imu"].update(
            timestamp_us=995000,
            available=True,
            fresh=True,
            startup=False,
            gyro_recovery=False,
            acceleration_recovery=False,
            calibration_applied=False,
        )
        value = observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])
        self.assertEqual(value["joint_sample_age_s"][:4], [0.02, 0.01, None, None])
        self.assertEqual(value["imu_sample_age_s"], 0.005)
        self.assertFalse(value["imu_quality"]["calibration_applied"])
        self.assertIsNone(value["imu_quality"]["accelerometer_ignored"])
        encoded = vector(value)
        self.assertEqual(encoded[96:100], [0.02, 0.01, 0.0, 0.0])
        self.assertEqual(encoded[108:112], [1.0, 1.0, 0.0, 0.0])
        self.assertEqual(encoded[120:122], [0.005, 1.0])
        self.assertEqual(encoded[127:129], [0.0, 0.0])
        self.assertEqual(encoded[134:136], [1.0, 0.0])
        source["imu"]["timestamp_us"] = 1000001
        self.assertIsNone(
            observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])[
                "imu_sample_age_s"
            ]
        )

    def test_unknown_sensor_timing_is_not_fresh_and_old_schema_cannot_be_reused(self):
        value = observation(
            self.source(), {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0]
        )
        self.assertEqual(value["joint_sample_age_s"], [None] * 12)
        self.assertIsNone(value["imu_sample_age_s"])
        self.assertTrue(all(flag is None for flag in value["imu_quality"].values()))
        self.assertEqual(vector(value)[108:136], [0.0] * 28)
        value["schema"] = "ainekio-neural-gait-v1"
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            vector(value)

    def test_nonfinite_sensor_values_are_invalid_not_motor_commands(self):
        source = self.source()
        source["joints"][JOINTS[1]]["velocity_deg_s"] = float("nan")
        with self.assertRaises(ValueError):
            observation(source, {"target_limits_deg": [[-90, 90]] * 12}, [0, 0, 0])



@unittest.skipUnless(
    importlib.util.find_spec("mujoco"),
    "Use a MuJoCo Python environment",
)
class PhysicsTests(unittest.TestCase):
    def test_compiled_cache_migrates_and_reloads_losslessly_without_recompiling(self):
        import gzip
        import hashlib
        import mujoco
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.environment import compiled_model
        xml = '<mujoco><worldbody><body><freejoint/><geom type="sphere" size=".1" mass="1"/></body></worldbody></mujoco>'
        original = mujoco.MjModel.from_xml_string(xml)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root/'build/neural-gait/compiled'
            directory.mkdir(parents=True)
            key = hashlib.sha256((mujoco.__version__+xml).encode()).hexdigest()
            raw = directory/(key+'.mjb')
            mujoco.mj_saveModel(original, str(raw))
            original_bytes = raw.read_bytes()
            with patch('gateway.neural_gait.environment.GEOMETRY',root/'a/b/c/d/geometry.json'), \
                 patch('gateway.neural_gait.environment.mujoco.MjModel.from_xml_string', side_effect=AssertionError('Unexpected recompile')):
                migrated = compiled_model(xml)
                loaded = compiled_model(xml)
            self.assertFalse(raw.exists())
            with gzip.open(directory/(key+'.mjb.gz'),'rb') as source:
                self.assertEqual(source.read(), original_bytes)
            np.testing.assert_array_equal(migrated.body_mass, original.body_mass)
            np.testing.assert_array_equal(loaded.body_inertia, original.body_inertia)

    def test_environment_restores_explicit_balance_configuration_on_reset(self):
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture(), balance_enabled=True), include_assembly=False)
        self.addCleanup(env.close)
        with patch.object(env.body_model,'balance_configure',wraps=env.body_model.balance_configure) as configure:
            env.reset(seed=1)
            env.reset(seed=2)
        self.assertEqual(configure.call_count,2)
        configure.assert_called_with(enabled=True,tuning=[1.,1.,0.,0.])
        _,_,_,_,info = env.step([0.]*12)
        self.assertIn('balance_correction_rad',info)

    def test_progress_video_includes_each_command_with_its_own_episode(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.replay import render

        commands = [[.02, 0, 0], [-.02, 0, 0], [0, 0, .12]]
        episodes = [dict(seed=seed, command=command, command_index=index)
                    for index, command in enumerate(commands) for seed in (1000, 1001, 1002)]
        checkpoints = [dict(id=str(step), steps=step, evaluation=dict(episodes=episodes))
                       for step in (0, 100)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'manifest.json').write_text(json.dumps(dict(kind='microduck-mjlab', schema=SCHEMA,
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
                environment=asdict(EnvironmentConfig(robot=robot_fixture())))))
            seen = []
            def rendered(directory, config, checkpoint, seed, *, episode):
                seen.append((checkpoint['steps'], episode['command_index'], seed, episode['command']))
                folder = directory/'clips'; folder.mkdir(exist_ok=True)
                name = f"{checkpoint['id']}-command{episode['command_index']}-trial{seed}.mp4"
                (folder/name).write_bytes(b'video fixture')
                return dict(labelled='clips/'+name)
            def concatenate(arguments, **kwargs):
                Path(arguments[-1]).write_bytes(b'concatenated video fixture')
            with patch('gateway.neural_gait.replay.versions', return_value=checkpoints), \
                 patch('gateway.neural_gait.replay.clip', side_effect=rendered), \
                 patch('gateway.neural_gait.replay.subprocess.run', side_effect=concatenate):
                render(root, progress=True)
            self.assertFalse((root/'footage.zip').exists())
            self.assertFalse((root/'footage.tmp.zip').exists())
            self.assertEqual(seen, [(step, index, seed, command)
                for step in (0,100) for index,command in enumerate(commands) for seed in (1000,1001)])
            metadata = json.loads((root/'progress-video.json').read_text())
            self.assertEqual(metadata['displayed_commands'], commands)
            self.assertEqual(len(metadata['clips']), 12)
            self.assertEqual(len({row['labelled'] for row in metadata['clips']}), 12)

    def test_transition_video_replays_evaluated_commands_without_resetting_physics(self):
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.evaluation import evaluate
        from gateway.neural_gait.replay import clip, WIDTH, HEIGHT

        commands = [[.015, 0, 0], [-.03, 0, 0]]
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12)
        class Actor:
            def __init__(self): self.commands = []
            def predict(self, observation, deterministic=True):
                command = observation[COMMAND_SLICE].copy()
                self.commands.append(command)
                return np.full(12, command[0], dtype=np.float32), None
        class Renderer:
            def __init__(self, *args, **kwargs): pass
            def update_scene(self, *args, **kwargs): pass
            def render(self): return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            def close(self): pass
        class Encoder:
            def __init__(self, path, fps):
                path.touch(); self.stdin = self
            def write(self, data): pass
            def close(self): pass
            def wait(self): return 0
            def poll(self): return 0
        factory = lambda settings, **kwargs: GaitEnvironment(settings, include_assembly=False)
        actor = Actor()
        with patch('gateway.neural_gait.evaluation.make_environment', side_effect=factory):
            evaluation = evaluate(actor, config, commands=commands, command_switch_seconds=.04)
        actor.commands.clear()
        with tempfile.TemporaryDirectory() as temporary, \
             patch('gateway.neural_gait.replay.make_environment', side_effect=factory), \
             patch('gateway.neural_gait.replay.mujoco.Renderer', Renderer), \
             patch('gateway.neural_gait.replay.encoder', Encoder):
            directory = Path(temporary)
            row = dict(id='transition', steps=0, evaluation=evaluation)
            episode = evaluation['episodes'][0]
            movie = clip(directory, config, row, 1000, model=actor, episode=episode)
            np.testing.assert_allclose(movie['ground_displacement_m'], episode['displacement_m'][:2], atol=1e-12)
            self.assertAlmostEqual(movie['heading_change_rad'], episode['heading_change_rad'])
            self.assertEqual(movie['command_segments'], episode['command_segments'])
            np.testing.assert_array_equal(actor.commands,
                np.asarray([commands[(step//2)%2] for step in range(6)], dtype=np.float32))
            actor.commands.clear()
            self.assertEqual(clip(directory, config, row, 1000, model=actor, episode=episode), movie)
            self.assertEqual(actor.commands, [])  # Matching footage is reused.


    def test_command_reset_uses_actual_observation_and_preserves_source_config(self):
        import numpy as np
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        commands = [[-.015, 0, 0], [0, 0, .12]]
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04)
        original = config.command[:]
        env = GaitEnvironment(config, include_assembly=False, commands=commands)
        try:
            seen = set()
            for seed in range(8):
                observation, info = env.reset(seed=seed)
                chosen = info["command"]
                seen.add(tuple(chosen))
                np.testing.assert_array_equal(observation[COMMAND_SLICE], np.float32(chosen))
                repeated, repeated_info = env.reset(seed=seed)
                self.assertEqual(chosen, repeated_info["command"])
                np.testing.assert_array_equal(observation, repeated)
            self.assertEqual(seen, {tuple(command) for command in commands})
            observation, _ = env.reset(seed=1, options={"command": commands[1]})
            self.assertEqual(env.config.command, commands[1])
            _, _, _, _, info = env.step(np.zeros(12))
            self.assertEqual(info["command"], commands[1])
            self.assertEqual(config.command, original)
            self.assertEqual(commands, [[-.015, 0, 0], [0, 0, .12]])
        finally:
            env.close()


    def test_reward_requires_commanded_travel_and_preserves_wrong_direction_penalty(self):
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.environment import (
            EnvironmentConfig, GaitEnvironment, movement_reward,
        )
        command = [0.08, 0, 0]
        stationary = movement_reward([0,0],0,command,1,1)
        forward = movement_reward([0.08,0],0,command,1,1)
        backward = movement_reward([-0.08,0],0,command,1,1)
        dragged = movement_reward([0.08,0],0,command,1,0.3)
        self.assertEqual(stationary,0)
        self.assertGreater(forward,dragged)
        self.assertGreater(dragged,stationary)
        self.assertLess(backward,stationary)
        self.assertEqual(movement_reward([-0.08,0],0,command,0,0),backward)

        # One-second means from the actual-assembly immediate-crawl-best30
        # simulation (body vx/vy m/s, yaw rad/s). This compact regression keeps
        # its net progress and cyclic sway without depending on retained runs.
        # It is a recorded simulation example, not physical qualification.
        measured = np.repeat(np.array([
            [-.0022936, -.0001668, .0025896],
            [-.0005479, .0032883, -.0042531],
            [.0121116, -.0107398, -.0802177],
            [.0127712, .0032540, .0279473],
            [.0095226, .0142747, .0351677],
            [.0168032, -.0111190, -.0267211],
            [.0092698, .0058404, .0180779],
            [.0069673, .0137294, .0169869],
            [.0133682, -.0144518, .0105436],
            [.0049613, .0035648, .0001936],
            [.0086938, .0129539, .0544487],
            [.0102503, -.0070844, .0701099],
        ]), 50, axis=0)
        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture(),
            episode_seconds=12), include_assembly=False)
        try:
            def replay(rows, command, end_supported=True):
                env.config.command = command
                env.reset(seed=1000)
                env.target_rejected = False
                self.assertEqual(env.steps, 0)
                rewards = []
                metrics = dict(velocity_body_m_s=[0, 0, 0], upright=1,
                    body_clearance_m=float(env.data.qpos[2]), terrain_height_m=0.,
                    ground_world_displacement_m=[0, 0], heading_rad=0,
                    contact_slip_speed_squared_m2_s2=0,
                    target_rejected=False, jammed_joints=0)
                # Exercise production reward accounting; only replace physics
                # with measured inputs, not a duplicate reward implementation.
                with patch.object(env, "_advance_physics", return_value=metrics):
                    for i, (vx, vy, yaw) in enumerate(rows):
                        metrics["velocity_body_m_s"] = [vx, vy, 0]
                        # Reconstruct horizontal world motion from the old
                        # body-frame fixture; it is not already world travel.
                        heading = metrics["heading_rad"] + yaw/env.config.control_hz
                        c, s = np.cos(heading), np.sin(heading)
                        metrics["ground_world_displacement_m"] = [
                            (c*vx-s*vy)/env.config.control_hz,
                            (s*vx+c*vy)/env.config.control_hz]
                        metrics["heading_rad"] = heading
                        env.data.sensor("gyro").data[:] = [0, 0, yaw]
                        env.data.actuator_force[:] = 0
                        if i == len(rows)-1 and not end_supported:
                            metrics["upright"] = 0
                            metrics["body_clearance_m"] = 0
                            env.data.qpos[2] = 0
                        _, reward, terminated, _, info = env._advance(np.zeros(12))
                        self.assertAlmostEqual(reward, info["travel_reward"])
                        rewards.append(reward)
                if not end_supported:
                    self.assertTrue(terminated)
                return np.array(rewards)

            for speed in (.08, .01):
                with self.subTest(speed=speed):
                    request = [speed, 0, 0]
                    rewards = replay(measured, request)
                    backwards = measured.copy()
                    backwards[:, 0] *= -1
                    self.assertLess(replay(backwards, request).mean(), 0)
                    self.assertGreater(rewards.sum(), replay(backwards, request).sum())
                    np.testing.assert_array_equal(
                        replay(np.zeros_like(measured), request), 0)
                    # Falling cannot earn positive travel credit; it does not
                    # rewrite earlier transitions' measured movement.
                    fallen = replay(measured, request, end_supported=False)
                    np.testing.assert_array_equal(fallen[:-1], rewards[:-1])
                    self.assertLessEqual(fallen[-1], 0)

            # Original failure: six seconds at the requested speed followed by
            # six stationary seconds must earn nothing after stopping. A second
            # real movement earns its own credit, including reverse requests.
            for command in ([.015, 0, 0], [-.03, 0, 0]):
                moving = np.tile(command, (300, 1))
                stopped = replay(np.concatenate([moving, np.zeros_like(moving), moving]), command)
                np.testing.assert_allclose(stopped[:300], 1)
                np.testing.assert_array_equal(stopped[300:600], 0)
                np.testing.assert_allclose(stopped[600:], 1)
                sustained = replay(np.tile(command, (900, 1)), command)
                self.assertGreater(sustained.sum(), stopped.sum())

                # Productive propulsion can include rest and faster-than-pace
                # strokes. One-second net pace matches the request; scoring
                # every20ms stroke as overspeed used to prefer no movement.
                burst_cycle=np.concatenate([np.zeros((25,3)),np.tile(2*np.asarray(command),(25,1))])
                bursts=replay(np.tile(burst_cycle,(6,1)),command)
                steady=replay(np.tile(command,(300,1)),command)
                self.assertGreater(bursts.sum(),0)
                self.assertAlmostEqual(bursts.sum(),steady.sum(),places=8)

            # Both symmetric sway and many good samples followed by one large
            # reverse sample have zero net travel. The old saturating Gaussian
            # could give the latter a positive score with per-sample scoring.
            for rows in ([[.015, 0, 0], [-.015, 0, 0]],
                         [[.015, 0, 0]]*10 + [[-.15, 0, 0]],
                         [[0, .015, 0], [0, -.015, 0]]):
                self.assertLessEqual(replay(np.array(rows), [.015, 0, 0]).sum(), 1e-12)
            np.testing.assert_allclose(
                replay(np.zeros((5, 3)), [0, 0, 0]), 1)
            self.assertLess(movement_reward([.08, 0], 0, [0, 0, 0], 1, 1), 1)
            # The same directed objective in PPO must receive the same recent
            # pace, even when exponential tracking uses instantaneous velocity.
            env.config.reward_profile = "locomotion"
            env.config.locomotion_reward_weights = {
                key: float(key == 'directed_progress') for key in env.config.locomotion_reward_weights}
            env.config.locomotion_tracking_window_s = 0.
            bursts = replay(np.tile(burst_cycle, (6, 1)), command)
            steady = replay(np.tile(command, (300, 1)), command)
            self.assertAlmostEqual(bursts.sum(), steady.sum(), places=8)
            np.testing.assert_array_equal(replay(np.zeros((50, 3)), command), 0.)
        finally:
            env.close()

    def test_locomotion_progress_and_slip_use_independent_units(self):
        from dataclasses import replace
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, locomotion_reward
        config = EnvironmentConfig(robot=robot_fixture(), reward_profile="locomotion", locomotion_slip_scale_m_s=1.0)
        def score(speed, *, slip=0., config=config):
            return locomotion_reward([speed, 0.], 0., [.08, 0., 0.], 1., 1.,
                vertical_velocity=0., angular_velocity_xy=[0., 0.],
                joint_velocity=np.zeros(12), previous_joint_velocity=np.zeros(12),
                joint_torque=np.zeros(12), action=np.zeros(12), previous_action=np.zeros(12),
                contact_slip_speed_squared=slip, config=config, progress_pace_velocity=[.08, 0., 0.])
        stopped, terms = score(0.)
        self.assertEqual(terms['directed_progress'], 0., 'Old pace cannot reward a stopped robot')
        self.assertGreater(score(.024)[0], stopped)
        self.assertLess(score(-.024)[0], stopped)
        self.assertAlmostEqual(score(.024)[1]['directed_progress'] +
                               score(-.024)[1]['directed_progress'], 0.)
        # Recorded slip of the moving baseline was multiplied by 1/.03².
        # The published .1 cost now applies to m²/s² regardless of tracking width.
        slip = .0213413
        expected = .1*slip/config.control_hz
        self.assertAlmostEqual(score(.024, slip=slip)[1]['slip'], expected)
        self.assertAlmostEqual(score(.024, slip=slip,
            config=replace(config, locomotion_tracking_width_m_s=.08))[1]['slip'], expected)
        historical = dict(config.locomotion_reward_weights)
        historical.pop('directed_progress')
        old = replace(config, locomotion_reward_weights=historical, locomotion_slip_scale_m_s=None)
        self.assertEqual(old.locomotion_reward_weights['directed_progress'], 0.)
        self.assertAlmostEqual(score(.024, slip=slip, config=old)[1]['slip'], expected/.03**2)
        # Coefficients may disable a duplicate cost; unit scales may not be zero.
        replace(config, reward_cross_track_cost=0.)
        with self.assertRaises(ValueError):
            replace(config, reward_cross_track_cost=-.1)
        with self.assertRaises(ValueError):
            replace(config, reward_velocity_scale_m_s=0.)

    def test_slow_progress_reward_is_not_dominated_by_cross_axis_yaw(self):
        import numpy as np
        from gateway.neural_gait.environment import movement_reward
        # Original failure: 2.72deg/s yaw erased all credit at15mm/s while
        # permitting twice as much yaw at30mm/s. Cross-axis cost now has its
        # own units and is identical at both requested linear speeds.
        scores = [movement_reward([speed,0],.05,[speed,0,0],1,1)
                  for speed in (.015,.03)]
        self.assertAlmostEqual(scores[0],scores[1])
        self.assertGreater(scores[0],.9)
        for command in ([.015,0,0],[-.03,0,0],[0,0,.12],[.015,0,.12]):
            def score(twist):
                return movement_reward(twist[:2],twist[2],command,1,1)
            target=np.asarray(command)
            self.assertEqual(score(np.zeros(3)),0)
            self.assertAlmostEqual(score(target),1)
            # Bursts separated by rest still make useful progress; sustained
            # target travel is best, and excess speed earns less credit.
            burst=movement_reward((2*target)[:2],(2*target)[2],command,1,1,
                                  pace_twist=target)
            self.assertGreater(.5*burst,0)
            self.assertLess(score(2*target),score(target))
            self.assertLessEqual(movement_reward([0,0],0,command,1,1,
                                                pace_twist=2*target),0)
            self.assertLess(score(-target),0)
            self.assertLessEqual((10*score(target)+score(-10*target))/11,0)
            rng=np.random.default_rng(17)
            for _ in range(10):
                samples=rng.normal(0,.1,size=(20,3))
                samples-=samples.mean(axis=0)
                self.assertLessEqual(np.mean([score(s) for s in samples]),1e-10)

    def test_command_change_preserves_physics_and_does_not_recredit_old_travel(self):
        import math
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.contract import COMMAND_SLICE
        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture()),include_assembly=False)
        self.addCleanup(env.close)
        env.reset(seed=1000)
        env.step(np.full(12,.05))
        snapshots = [value.copy() for value in (env.data.qpos,env.data.qvel,env.last_target,
                     env.last_action,env.feedback_angles,env.feedback_times,env.imu_sample)]
        time,steps,heading = env.data.time,env.steps,env.world_heading_delta
        reference_heading = env.reward_reference_heading
        observed=env.set_command([-.02,0,0])
        self.assertEqual(env.reward_reference_heading, reference_heading)
        np.testing.assert_allclose(observed[COMMAND_SLICE],[-.02,0,0])
        for prior, current in zip(snapshots,(env.data.qpos,env.data.qvel,env.last_target,
                env.last_action,env.feedback_angles,env.feedback_times,env.imu_sample)):
            np.testing.assert_array_equal(prior,current)
        self.assertEqual((env.data.time,env.steps,env.world_heading_delta),(time,steps,heading))
        env.data.actuator_force[:]=0.
        env.standing_height=float(env.data.qpos[2])
        yaw=env.reward_reference_heading
        distance=-.02/env.config.control_hz
        metrics=dict(ground_world_displacement_m=[distance*math.cos(yaw),distance*math.sin(yaw)],
            body_clearance_m=float(env.data.qpos[2]), terrain_height_m=0.,
            heading_rad=env.reward_last_heading,velocity_body_m_s=[-.02,0,0],upright=1,
            contact_slip_speed_squared_m2_s2=0.)
        with patch.object(env,'_advance_physics',return_value=metrics):
            _,reward,_,_,_=env._advance(env.last_action.copy())
        self.assertAlmostEqual(reward,1.)
        self.assertEqual(env.steps,steps+1)
        env.set_command([-.02,0,0])
        self.assertEqual(env.steps,steps+1)

    def test_reward_uses_command_reference_ground_travel_and_unwrapped_heading(self):
        import math
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment

        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture()),
                              include_assembly=False)
        try:
            def reset(command, initial_heading=0):
                env.config.command = command
                env.reset(seed=1000)
                env.target_rejected = False
                env.data.actuator_force[:] = 0
                env.reward_reference_heading = initial_heading
                env.reward_last_heading = initial_heading

            def advance(displacement, heading, body_velocity=(0, 0, 0), gyro=0):
                # Ground-truth metrics intentionally disagree with local body
                # velocity and gyroZ: neither may redefine the requested path.
                env.data.sensor("gyro").data[:] = [0, 0, gyro]
                metrics = dict(ground_world_displacement_m=displacement,
                    body_clearance_m=float(env.data.qpos[2]), terrain_height_m=0.,
                    heading_rad=heading, velocity_body_m_s=list(body_velocity),
                    upright=1, target_rejected=False, jammed_joints=0,
                    contact_slip_speed_squared_m2_s2=0)
                with patch.object(env, "_advance_physics", return_value=metrics):
                    return env._advance(np.zeros(12))

            hz = env.config.control_hz
            reset([.08, 0, 0])
            _, reward, _, _, _ = advance([0, 0], 0, (.08, 0, 1), gyro=10)
            self.assertEqual(reward, 0)  # Bobbing/gyro alias earns no ground travel.

            reset([.08, 0, 0])
            _, reward, _, _, _ = advance([0, .08/hz], math.pi/2, (.08, 0, 0))
            self.assertLess(reward, 0)
            self.assertEqual(env.reward_reference_heading, 0)
            self.assertAlmostEqual(env.world_heading_delta, math.pi/2)

            # A rotated command-start frame is valid; actual yaw changes cannot
            # rotate that frame unless the command itself requests turning.
            reset([.08, 0, 0], math.pi/2)
            _, reward, _, _, _ = advance([0, .08/hz], math.pi/2, gyro=-10)
            self.assertAlmostEqual(reward, 1)

            # Crossing +pi/-pi is a small positive turn, not a full revolution.
            initial = math.pi-.01
            reset([.08, 0, 1], initial)
            midpoint = initial+.5/hz
            _, reward, _, _, _ = advance(
                [.08*math.cos(midpoint)/hz, .08*math.sin(midpoint)/hz],
                -math.pi+.01, gyro=-100)
            self.assertAlmostEqual(reward, 1)
            self.assertAlmostEqual(env.world_heading_delta, 1/hz)
            self.assertAlmostEqual(env.reward_reference_heading, initial+1/hz)

            # A commanded arc follows the requested reference at every frame.
            # This checks accounting, not trained turning capability.
            reset([.08, 0, .5])
            rewards = []
            for step in range(100):
                midpoint = (step+.5)*.5/hz
                _, reward, _, _, _ = advance(
                    [.08*math.cos(midpoint)/hz, .08*math.sin(midpoint)/hz],
                    (step+1)*.5/hz, gyro=0)
                rewards.append(reward)
            np.testing.assert_allclose(rewards, 1, atol=1e-10)
            self.assertAlmostEqual(env.world_heading_delta, 1)
            self.assertAlmostEqual(env.reward_reference_heading, 1)
        finally:
            env.close()

    def test_cad_asset_identity_is_independent_of_rl_schema_version(self):
        from unittest.mock import patch
        from gateway.neural_gait import assembly, environment

        identity = assembly._fingerprint()
        with patch.object(environment, "ENVIRONMENT_VERSION", environment.ENVIRONMENT_VERSION + 1):
            self.assertEqual(assembly._fingerprint(), identity)

    def test_cold_cad_cache_restores_frozen_assets_without_decomposition(self):
        from unittest.mock import patch
        import zipfile
        from gateway.neural_gait import assembly

        source = assembly.SOURCE
        identity = assembly._fingerprint()
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "Slave/software/models/v2-12servo/simulation"
            snapshot.mkdir(parents=True)
            for name in ("assembly.json", "assembly.npz", "prepared.json", "prepared.zip"):
                (snapshot / name).symlink_to(source / name)
            (snapshot.parent / "geometry.json").symlink_to(source.parent / "geometry.json")
            with patch.object(assembly, "SOURCE", snapshot), patch.object(
                assembly, "ProcessPoolExecutor",
                side_effect=AssertionError("Frozen CAD must not invoke native decomposition"),
            ) as conversion:
                directory, manifest = assembly.prepare()
                conversion.assert_not_called()
            self.assertEqual(manifest["source_sha256"], identity)
            names = assembly._asset_names(manifest)
            self.assertTrue(all((directory / name).is_file() for name in names))
            with zipfile.ZipFile(source / "prepared.zip") as archive:
                self.assertEqual(manifest, json.loads(archive.read("manifest.json")))
                for name in (names[0], names[len(names) // 2], names[-1]):
                    self.assertEqual((directory / name).read_bytes(), archive.read(name))

    def test_native_baseline_preserves_reverse_update_finish_without_forward_score(
        self,
    ):
        from gateway.neural_gait.environment import GaitEnvironment, EnvironmentConfig

        # This tests the firmware/physics handoff; detailed CAD contact dynamics
        # are covered separately by the full-assembly standing test below.
        env = GaitEnvironment(
            EnvironmentConfig(robot=robot_fixture()), include_assembly=False
        )
        try:
            env.reset(seed=1)
            command = dict(
                t="intent",
                seq=1,
                name="walk",
                dir="back",
                gait="walk",
                speed=30,
                steps=0,
            )
            self.assertTrue(
                env.start_native_walk(
                    command, heading_enabled=False, balance_enabled=False
                )
            )
            for _ in range(5):
                result = env.step_native_walk()
            self.assertEqual(result["command"], command)
            self.assertNotIn("reward", result)
            self.assertNotIn("command", result["observation"])
            phase = result["frame"]["phase"]
            self.assertTrue(
                env.update_native_walk(dict(command, seq=2, update=1, speed=90))
            )
            result = env.step_native_walk()
            self.assertGreater(result["frame"]["phase"], phase)
            self.assertEqual(result["frame"]["command_sequence"], 1)
            self.assertEqual(result["command"]["speed"], 90)
            self.assertTrue(
                env.update_native_walk(dict(command, seq=3, update=1, speed=0))
            )
            result = env.step_native_walk()
            self.assertTrue(result["frame"]["stopping"])
            self.assertEqual(result["frame"]["command_sequence"], 1)
            self.assertTrue(
                all(v >= 0 for v in result["observation"]["joint_sample_age_s"])
            )
            self.assertIn("startup", result["observation"]["imu_quality"])
        finally:
            env.close()

    def test_all_mirrored_feet_match_the_existing_geometry_in_nonzero_poses(self):
        import numpy as np
        from gateway.neural_gait.environment import (
            GaitEnvironment,
            EnvironmentConfig,
            reference,
        )
        from gateway.neural_gait.contract import LEGS

        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture()), include_visuals=False)
        mechanism = reference()
        try:
            env.reset(seed=7)
            for pose in ([0, 0, 0], [10, 3.46, -21.63], [-15, -10, -50]):
                env.data.qpos[:3] = [0, 0, 0.065]
                env.set_pose(np.deg2rad(pose * 4))
                for leg, cad in zip(LEGS, ("FL", "FR", "RL", "RR")):
                    expected = (
                        mechanism.reference(cad, np.deg2rad(pose), np.zeros(3)) / 1000
                    )
                    np.testing.assert_allclose(
                        env.data.site(leg + "_reference").xpos, expected, atol=1e-9
                    )
                    np.testing.assert_allclose(
                        env.data.site(leg + "_pickup_end").xpos,
                        env.data.site(leg + "_rod_end").xpos,
                        atol=1e-9,
                    )
        finally:
            env.close()

    def test_standing_baseline_has_mass_contact_and_no_teleportation(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment

        env = GaitEnvironment(EnvironmentConfig(randomization=0, robot=robot_fixture()), include_visuals=False)
        try:
            obs, _ = env.reset(seed=1)
            self.assertEqual(obs.shape, (OBSERVATION_SIZE,))
            self.assertAlmostEqual(env.model.body_mass.sum(), 0.650)
            initial_feet = env.foot_measurements()
            self.assertFalse(any(initial_feet["contact"]))
            self.assertGreater(min(initial_feet["clearance_m"]),0)
            initial = env.data.qpos[:3].copy()
            action = env.last_action.copy()
            for _ in range(100):
                obs, reward, terminated, _, info = env.step(action)
                self.assertFalse(terminated)
            self.assertGreater(env.data.ncon, 0)
            self.assertGreater(info["upright"], 0.99)
            self.assertLess(np.linalg.norm(env.data.qpos[:2] - initial[:2]), 0.02)
            self.assertTrue(np.isfinite(obs).all())
            feet = env.foot_measurements()
            self.assertTrue(all(feet["contact"]))
            self.assertLess(max(abs(v) for v in feet["clearance_m"]), .002)
        finally:
            env.close()

    def test_incompatible_selected_checkpoint_reports_error_without_loading_policy(
        self,
    ):
        from unittest.mock import patch
        from gateway.neural_gait.environment import ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.server import Runtime

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "abc"
            path.mkdir()
            (path / "manifest.json").write_text(
                json.dumps(
                    dict(
                        kind="microduck-mjlab",
                        policy="policy.onnx",
                        schema=SCHEMA,
                        environment_version=4,
                        representation=representation_identity(),
                        environment={},
                    )
                )
            )
            selected = Path(root) / "selected.json"
            selected.write_text(json.dumps(dict(model_id="abc")))
            original = selected.read_text()
            with patch("gateway.neural_gait.microduck_actor.MicroduckActor") as load:
                runtime = Runtime(root)
                status = runtime.status()
                load.assert_not_called()
            self.assertIsNone(status["model_id"])
            self.assertIn("representation differs", status["selection_error"])
            self.assertEqual(selected.read_text(), original)
            (path / "manifest.json").write_text(
                json.dumps(
                    dict(
                        kind="microduck-mjlab",
                        policy="policy.onnx",
                        schema="ainekio-neural-gait-v1",
                        environment_version=ENVIRONMENT_VERSION,
                        environment={},
                    )
                )
            )
            with patch("gateway.neural_gait.microduck_actor.MicroduckActor") as load:
                old_schema = Runtime(root)
                load.assert_not_called()
            self.assertIsNone(old_schema.model_id)
            self.assertIn("representation differs", old_schema.selection_error)


    def test_checkpoint_server_loads_same_actions_after_restart_and_records_domain(self):
        import numpy as np
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.contract import PROPRIO_FEATURES, PROPRIO_SAMPLES, PROPRIO_SCHEMA
        from gateway.neural_gait.environment import (
            EnvironmentConfig,
            GaitEnvironment,
            ENVIRONMENT_VERSION,
            representation_identity,
        )
        from gateway.neural_gait.pupper_mjx_actor import HISTORY_DIM, PUPPER_MJX_KIND
        from gateway.neural_gait.server import Runtime

        def make_rtneural(bias_offset=0.0):
            dims = [HISTORY_DIM, 4, 4, 4, 4, 12]
            layers = []
            for idx in range(5):
                w = np.zeros((dims[idx], dims[idx + 1]), dtype=np.float32).tolist()
                b = [float(bias_offset) if idx == 4 else 0.0] * dims[idx + 1]
                layers.append({
                    "activation": "tanh" if idx == 4 else "elu",
                    "weights": [w, b],
                })
            return {
                "in_shape": [None, HISTORY_DIM],
                "layers": layers,
                "joint_lower_limits": [-1.5] * 12,
                "joint_upper_limits": [1.5] * 12,
            }

        config = EnvironmentConfig(robot=robot_fixture(), observation_schema=PROPRIO_SCHEMA)
        env = GaitEnvironment(config, include_assembly=False)
        try:
            with tempfile.TemporaryDirectory() as root:
                path = Path(root) / "abc"
                path.mkdir()
                (path / "manifest.json").write_text(
                    json.dumps(
                        dict(
                            kind=PUPPER_MJX_KIND,
                            policy="policy.json",
                            schema=PROPRIO_SCHEMA,
                            environment=asdict(config),
                            environment_version=ENVIRONMENT_VERSION,
                            representation=representation_identity(),
                        )
                    )
                )
                (path / "environment.json").write_text(json.dumps(asdict(config)))
                (path / "policy.json").write_text(json.dumps(make_rtneural(0.0)))
                runtime = Runtime(root)
                self.assertIsNone(runtime.model_id)
                runtime.load("abc")
                env.reset(seed=1)
                obs = {
                    "schema": PROPRIO_SCHEMA,
                    "proprio_history": [[0.0] * PROPRIO_FEATURES for _ in range(PROPRIO_SAMPLES)],
                    "joint_deg": [0.0, 3.46, -21.63] * 4,
                    "joint_velocity_deg_s": [0.0] * 12,
                    "joint_usable": [True] * 12,
                    "target_limits_deg": config.target_limits_deg,
                    "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
                    "angular_rate_rad_s": [0.0, 0.0, 0.0],
                    "acceleration_m_s2": [0.0, 0.0, 9.80665],
                    "command": [0.08, 0.0, 0.0],
                    "previous_action": [0.0] * 12,
                    "observation_time_s": 1.0,
                }
                first = runtime.infer(obs)
                restored = Runtime(root).infer(obs)
                np.testing.assert_array_equal(
                    first["targets_deg"], restored["targets_deg"]
                )
                checkpoint_id = "step-16"
                (path / "checkpoints").mkdir()
                (path / "checkpoints" / f"{checkpoint_id}.json").write_text(json.dumps(make_rtneural(0.0)))
                (path / "checkpoints.json").write_text(json.dumps([
                    dict(id=checkpoint_id, policy=f"checkpoints/{checkpoint_id}.json", steps=16)]))
                (path / "policy.json").write_text(json.dumps(make_rtneural(0.5)))
                runtime.load("abc", checkpoint_id)
                self.assertEqual(runtime.status(include_runs=False)["checkpoint_id"], checkpoint_id)
                selected = Runtime(root).infer(obs)
                self.assertEqual(selected["checkpoint_id"], checkpoint_id)
                np.testing.assert_array_equal(first["action"], selected["action"])
                with self.assertRaisesRegex(ValueError, "published checkpoint"):
                    runtime.load("abc", "missing")
                self.assertEqual(runtime.checkpoint_id, checkpoint_id)
                runtime.load("abc")
                self.assertFalse(np.array_equal(first["action"], runtime.infer(obs)["action"]))
                self.assertIsNone(runtime.checkpoint_id)
                (path / "policy.json").write_text(json.dumps(make_rtneural(0.0)))
                manifest_path = path / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                for version in (5, 6):
                    manifest["environment_version"] = version
                    manifest_path.write_text(json.dumps(manifest))
                    runtime.load("abc")
                    np.testing.assert_array_equal(
                        first["targets_deg"], runtime.infer(obs)["targets_deg"])
                self.assertEqual(first["execution"], "preview_only")
                self.assertEqual(runtime.status()["runs"][0]["id"], "abc")
                changed_cad = dict(representation_identity(), assembly_sha256="different")
                with patch("gateway.neural_gait.environment.representation_identity", return_value=changed_cad):
                    with self.assertRaisesRegex(ValueError, "representation differs"):
                        runtime.load("abc")
                    with self.assertRaisesRegex(ValueError, "changed environment"):
                        runtime.render("abc")
                obs["target_limits_deg"] = [[-1, 1]] * 12
                with self.assertRaisesRegex(ValueError, "domain differs"):
                    runtime.infer(obs)
                with self.assertRaises(ValueError):
                    runtime.run_path("../escape")
        finally:
            env.close()

    def test_footage_download_uses_temporary_snapshot_and_preserves_sources(self):
        import io
        import threading
        import urllib.request
        import zipfile
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        from gateway.neural_gait.server import Handler, Runtime

        with tempfile.TemporaryDirectory() as root:
            run = Path(root)/"abc"
            (run/"clips").mkdir(parents=True)
            expected = {
                "manifest.json": b'{"kind": "microduck-mjlab", "environment": {}}',
                "clips/one.mp4": b"labelled video",
                "clips/one-clean.mp4": b"clean video",
                "clips/one.json": b'{"physical_execution": false}',
                "progress-video.mp4": b"progress comparison",
                "evaluation.json": b'{"candidate": {}}',
            }
            for filename, content in expected.items():
                (run/filename).write_bytes(content)
            (run/"clips/incomplete.tmp.mp4").write_bytes(b"unfinished encoding")
            (run/"policy.zip").write_bytes(b"weights")
            (run/"replay.pkl.gz").write_bytes(b"optimizer replay")
            runtime = Runtime(root)
            self.assertTrue(runtime.status()["runs"][0]["has_footage"])
            self.assertFalse((run/"footage.zip").exists())
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.runtime = runtime
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            temporary_files = []
            original_temporary_file = tempfile.TemporaryFile

            def capture_temporary(*args, **kwargs):
                stream = original_temporary_file(*args, **kwargs)
                temporary_files.append(stream)
                return stream

            try:
                with patch("gateway.neural_gait.server.tempfile.TemporaryFile", side_effect=capture_temporary):
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{server.server_port}/footage?id=abc") as response:
                        data = response.read()
                        self.assertEqual(response.headers["Content-Type"], "application/zip")
                        self.assertEqual(int(response.headers["Content-Length"]), len(data))
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    self.assertEqual(set(archive.namelist()), set(expected))
                    for filename, content in expected.items():
                        self.assertEqual(archive.read(filename), content)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            self.assertEqual(len(temporary_files), 1)
            self.assertTrue(temporary_files[0].closed)
            self.assertFalse(list(run.glob("footage*.zip")))
            for filename, content in expected.items():
                self.assertEqual((run/filename).read_bytes(), content)


    def test_request_switch_preserves_physics_and_reaches_actor_before_next_action(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.evaluation import CommandRequests
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12)
        commands = [[.015, 0, 0], [-.03, 0, 0]]
        body = GaitEnvironment(config, include_assembly=False)
        manual = GaitEnvironment(config, include_assembly=False)
        requests = CommandRequests(body, commands, command_switch_seconds=.04)
        try:
            current, _ = requests.reset(seed=1, options={"command": commands[0]})
            manual.reset(seed=1, options={"command": commands[0]})
            for step in range(6):
                command = commands[(step//2)%2]
                np.testing.assert_array_equal(current[82:85], np.float32(command))
                action = np.full(12, .01 if command[0] > 0 else -.01)
                current, reward, done, truncated, info = requests.step(action)
                expected, expected_reward, manual_done, manual_truncated, manual_info = manual.step(action)
                self.assertEqual(info["command"], command)
                self.assertEqual(info["command"], manual_info["command"])
                self.assertEqual(reward, expected_reward)
                self.assertEqual((done, truncated), (manual_done, manual_truncated))
                # A new request changes no pose, velocity, feedback or clock.
                np.testing.assert_array_equal(body.data.qpos, manual.data.qpos)
                np.testing.assert_array_equal(body.data.qvel, manual.data.qvel)
                np.testing.assert_array_equal(body.feedback_times, manual.feedback_times)
                self.assertAlmostEqual(body.data.time, (step+1)/config.control_hz)
                if (step+1)%2 == 0 and not (done or truncated):
                    expected = manual.set_command(commands[((step+1)//2)%2])
                np.testing.assert_array_equal(current, expected)
        finally:
            body.close()
            manual.close()

    def test_random_request_timing_is_seeded_and_drawn_at_each_boundary(self):
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.evaluation import CommandRequests, request_interval_steps
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.4)
        commands = [[.015, 0, 0], [-.03, 0, 0]]
        body = GaitEnvironment(config, include_assembly=False)
        requests = CommandRequests(body, commands, command_switch_range=[.04, .08])
        try:
            traces = []
            for _ in range(2):
                with patch("gateway.neural_gait.evaluation.request_interval_steps",
                           wraps=request_interval_steps) as draw:
                    requests.reset(seed=42, options={"command": commands[0]})
                    self.assertEqual(draw.call_count, 1)
                    trace = [dict(requests.request)]
                    for step in range(20):
                        _, _, done, truncated, _ = requests.step(np.zeros(12))
                        if requests.request != trace[-1]:
                            self.assertEqual(requests.request["start_step"], step+1)
                            trace.append(dict(requests.request))
                        self.assertEqual(draw.call_count, len(trace))
                        if done or truncated:
                            break
                    traces.append(trace)
            self.assertEqual(traces[0], traces[1])
            spans = [row["scheduled_end_step"]-row["start_step"] for row in traces[0][:-1]]
            self.assertTrue(all(2 <= value <= 4 for value in spans))
            self.assertGreater(len(set(spans)), 1)
            self.assertEqual([row["command"] for row in traces[0]],
                             [commands[index%2] for index in range(len(traces[0]))])
        finally:
            body.close()


    def test_evaluation_reports_later_progress_in_complete_and_partial_seconds(self):
        import numpy as np
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.evaluation import evaluate
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=2.04)
        with patch("gateway.neural_gait.evaluation.make_environment",
                   partial(GaitEnvironment, include_assembly=False)):
            case = evaluate(None, config, seeds=[1])["episodes"][0]
        intervals = case["progress_intervals"]
        self.assertEqual([row["start_step"] for row in intervals], [0, 50, 100])
        self.assertEqual([row["end_step"] for row in intervals], [50, 100, 102])
        self.assertAlmostEqual(sum(row["seconds"] for row in intervals), case["seconds"])
        self.assertAlmostEqual(sum(row["reward"] for row in intervals), case["reward"])
        np.testing.assert_allclose(np.sum([row["command_reference_travel_m"]
            for row in intervals], axis=0), case["command_reference_travel_m"])

    def test_camera_noise_gets_multiple_evaluation_seeds_without_imu_noise(self):
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.evaluation import evaluate
        camera = dict(imageSize=[8,8], cameraMatrix=[[8,0,4],[0,8,4],[0,0,1]],
            cameraToBody=[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
            capture_hz=10, latency_s=.04, dropout_probability=0., noise_std_m=0.,
            provenance={"basis":"test optical geometry"})
        for noise in (dict(noise_std_m=.001), dict(startup_latency_s=[.04, 14.825]), dict(odometry=dict(
                position_noise_std_m=0., rotation_noise_std_rad=0., log_scale_std=.1,
                dropout_probability=0.))):
            config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04,
                observation_schema=DEPTH_SCHEMA, depth_camera={**camera, **noise})
            with patch("gateway.neural_gait.evaluation.make_environment",
                       partial(GaitEnvironment, include_assembly=False, include_visuals=False)):
                full = evaluate(None, config)
                compact = evaluate(None, config, compact=True)
            self.assertEqual([r['seed'] for r in full['episodes']], list(range(1000, 1008)))
            self.assertEqual([r['seed'] for r in compact['episodes']], [1000])

    def test_standing_baseline_reuses_only_camera_seed_variation_through_body_control(self):
        import numpy as np
        from unittest.mock import Mock, patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.connected_environment import BodyControlEnvironment
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.evaluation import evaluate

        class HeldReference:
            def predict(self, observation, deterministic=True):
                return np.zeros(12), None

        camera = dict(imageSize=[8,8], cameraMatrix=[[8,0,4],[0,8,4],[0,0,1]],
            cameraToBody=[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
            capture_hz=10, latency_s=.04, dropout_probability=.05, noise_std_m=.005,
            odometry=dict(position_noise_std_m=.002, rotation_noise_std_rad=.005,
                          log_scale_std=.15, dropout_probability=.05),
            provenance={"basis":"test optical geometry"})
        config = EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            episode_seconds=.06, observation_schema=DEPTH_SCHEMA, depth_camera=camera,
            scenarios=[{"id":"flat"}, {"id":"incline", "slope_deg":[0,2]}])
        commands = [[.015,0,0], [-.03,0,0]]
        seeds = tuple(range(1000, 1008))
        environments, reported = [], []
        def environment(*args, **kwargs):
            env = BodyControlEnvironment(*args, include_assembly=False, **kwargs)
            env.reset = Mock(wraps=env.reset)
            environments.append(env)
            return env
        with patch("gateway.neural_gait.evaluation.make_environment", side_effect=environment):
            reused = evaluate(None, config, seeds=seeds, commands=commands,
                              progress=lambda done,total: reported.append((done,total)))
            # The same held target supplied as a policy must still execute all
            # seeds. This compares reuse against independent native-body trials.
            independent = evaluate(HeldReference(), config, seeds=seeds, commands=commands)
        self.assertEqual([env.reset.call_count for env in environments], [4,32])
        self.assertEqual((reused["simulated_episodes"], reused["reused_episodes"]), (4,28))
        self.assertEqual((independent["simulated_episodes"], independent["reused_episodes"]), (32,0))
        self.assertEqual(reported, [(step,4) for step in range(5)])
        self.assertEqual([(row["command"],row["scenario_id"],row["seed"]) for row in reused["episodes"]],
            [(command,scenario,seed) for command in commands for scenario in ("flat","incline") for seed in seeds])
        for result, actual in zip(reused["episodes"], independent["episodes"]):
            self.assertEqual({key:value for key,value in result.items() if key != "reused_from_seed"}, actual)
            if result["seed"] == seeds[0]:
                self.assertNotIn("reused_from_seed", result)
            else:
                self.assertEqual(result["reused_from_seed"], seeds[0])
        # Separate report rows must not share mutable metric/interval objects.
        reused["episodes"][1]["progress_intervals"][0]["reward"] = 999
        self.assertNotEqual(reused["episodes"][0]["progress_intervals"][0]["reward"], 999)

    def test_standing_baseline_retains_seed_trials_when_executor_inputs_can_vary(self):
        from unittest.mock import Mock, patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.evaluation import evaluate
        variations = [dict(randomization=.1), dict(feedback_noise_raw_std=1.),
                      dict(imu_accel_noise_std=.01), dict(imu_gyro_noise_std=.01), {}]
        for variation in variations:
            with self.subTest(variation=variation):
                config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.06, **variation)
                env = GaitEnvironment(config, include_assembly=False, include_visuals=False)
                env.reset = Mock(wraps=env.reset)
                timing = {} if variation else dict(command_switch_range=[.02,.04])
                with patch("gateway.neural_gait.evaluation.make_environment", return_value=env):
                    result = evaluate(None, config, seeds=[1000,1001], **timing)
                self.assertEqual(env.reset.call_count, 2)
                self.assertEqual((result["simulated_episodes"], result["reused_episodes"]), (2,0))
                self.assertTrue(all("reused_from_seed" not in row for row in result["episodes"]))

    def test_varied_request_replay_preserves_shared_sensor_noise_rng(self):
        import numpy as np
        from functools import partial
        from types import SimpleNamespace
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.evaluation import evaluate
        from gateway.neural_gait.replay import clip

        class SensorPolicy:
            def predict(self, observation, deterministic=True):
                return np.tanh(np.resize(observation[76:79], 12))*.3, None

        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.2, imu_gyro_noise_std=.1)
        commands = [[.015, 0, 0], [-.03, 0, 0]]
        with patch("gateway.neural_gait.evaluation.make_environment", partial(GaitEnvironment, include_assembly=False)):
            evaluation = evaluate(SensorPolicy(), config, seeds=[1000], commands=commands,
                                  command_switch_range=[.04, .08])
        case = evaluation["episodes"][0]
        self.assertGreater(len(case["command_segments"]), 1)

        def encoder(path, fps):
            path.touch()
            return SimpleNamespace(stdin=SimpleNamespace(write=lambda data: len(data), close=lambda: None),
                                   wait=lambda: 0, poll=lambda: 0)

        renderer = SimpleNamespace(update_scene=lambda *a, **kw: None, close=lambda: None,
                                   render=lambda: np.zeros((2, 2, 3), dtype=np.uint8))
        with tempfile.TemporaryDirectory() as root, \
             patch("gateway.neural_gait.replay.make_environment", partial(GaitEnvironment, include_assembly=False)), \
             patch("gateway.neural_gait.replay.mujoco.Renderer", return_value=renderer), \
             patch("gateway.neural_gait.replay.encoder", side_effect=encoder):
            result = clip(Path(root), config, dict(id="rng", steps=0, evaluation=evaluation), 1000,
                          model=SensorPolicy(), episode=case)
            np.testing.assert_allclose(result["ground_displacement_m"], case["displacement_m"][:2], rtol=0, atol=1e-12)
            self.assertAlmostEqual(result["heading_change_rad"], case["heading_change_rad"], places=12)


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "Use a MuJoCo Python environment")
class ConnectedEnvironmentTests(unittest.TestCase):
    def test_established_imu_walk_and_camera_share_clock_without_episode_delay(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.contract import HISTORY_SCHEMA
        camera = dict(imageSize=[8,8], cameraMatrix=[[8,0,4],[0,8,4],[0,0,1]],
            cameraToBody=[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
            capture_hz=10, latency_s=.04, startup_latency_s=.08,
            dropout_probability=0., noise_std_m=0., max_frame_age_s=.2,
            provenance={"basis":"test optical geometry"})
        env = make_environment(EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            control_hz=33, physics_hz=528, episode_seconds=.5, imu_prehistory_s=4.,
            balance_enabled=True, observation_schema=HISTORY_SCHEMA, depth_camera=camera,
            scenarios=[dict(id="wall", geoms=[dict(kind="wall", position_m=[.4,0,.15],
                                                size_m=[.02,.3,.15])])]),
            include_assembly=False, include_visuals=False)
        self.addCleanup(env.close)
        env.reset(seed=4)
        first = env.gateway_observation
        self.assertFalse(first["imu_quality"]["startup"])
        self.assertTrue(first["imu_quality"]["fresh"])
        self.assertGreaterEqual(first["observation_time_s"], 4.)
        self.assertLess(env.data.time, .1)
        self.assertFalse(first["vision"]["depth_available"])
        self.assertTrue(all(0 <= age < .04 for age in first["joint_sample_age_s"]))
        before = env.session.connection.last_status["imu"]
        self.assertEqual(before["gap_restarts"], 0)
        for _ in range(7):
            _, _, terminated, _, info = env.step(np.zeros(12))
            self.assertFalse(terminated, info)
        after = env.session.connection.last_status["imu"]
        self.assertEqual(after["gap_restarts"], 0)
        self.assertGreater(after["timestamp_us"], before["timestamp_us"])
        self.assertFalse(after["startup"])
        observed = env.gateway_observation
        self.assertTrue(observed["vision"]["depth_available"])
        self.assertLess(observed["vision"]["age_s"], .2)
        self.assertAlmostEqual(env.depth_camera.next_capture-env.data.time, 4., delta=.11)
        self.assertGreaterEqual(env.depth_measurement["receivedAtMonotonic"], 4.)
        self.assertTrue(any(row[-1] for row in observed["sensor_history"]))
        for row in observed["sensor_history"]:
            if row[-1]:
                self.assertLess(row[-2], .3)


    def test_history_through_real_gateway_keeps_privileged_values_in_training_only(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.contract import HISTORY_SCHEMA, HISTORY_SIZE, HISTORY_START, vector
        commands = [[.015,0,0],[-.03,0,0]]
        env = make_environment(EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            observation_schema=HISTORY_SCHEMA, episode_seconds=.4, command=commands[0]),
            include_assembly=False, include_visuals=False, commands=commands)
        self.addCleanup(env.close)
        first, _ = env.reset(seed=4, options={"command": commands[0]})
        for _ in range(12):
            observed, reward, done, _, info = env.step(np.zeros(12))
            self.assertFalse(done, info)
            components = info["reward_components"]
            self.assertAlmostEqual(reward, components["progress"]-sum(value for name, value
                                   in components.items() if name != "progress"))
        self.assertEqual(observed.shape, (HISTORY_SIZE,))
        self.assertNotIn("training_critic", env.gateway_observation)
        self.assertGreater(env.gateway_observation["sensor_history"][0][-1], 0)
        wire = np.asarray(vector(env.gateway_observation), dtype=np.float32)
        np.testing.assert_array_equal(wire[:-5], observed[:-5])
        np.testing.assert_array_equal(wire[-5:], np.zeros(5))
        reference = env.reward_reference_heading
        state = env.session.connection.neural_walk
        history = state.observation_history
        past = list(history.samples)
        env.set_command(commands[1])
        self.assertEqual(env.reward_reference_heading, reference)
        self.assertIs(env.session.connection.neural_walk.observation_history, history)
        self.assertEqual(list(history.samples)[:-1], past[:-1])
        fresh, _ = env.reset(seed=4, options={"command": commands[0]})
        np.testing.assert_array_equal(first, fresh)

    def test_spatial_camera_reaches_policy_through_actual_gateway(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.contract import DEPTH_SCHEMA, observation_size
        profile=dict(imageSize=[8,8],cameraMatrix=[[8,0,4],[0,8,4],[0,0,1]],
            cameraToBody=[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
            capture_hz=10,latency_s=.04,dropout_probability=0,noise_std_m=0,
            provenance={"basis":"test optical geometry"},
            odometry=dict(position_noise_std_m=.001, rotation_noise_std_rad=.001,
                          log_scale_std=.05, dropout_probability=0.))
        scenarios=[dict(id="wall",geoms=[dict(kind="wall",position_m=[.4,0,.15],size_m=[.02,.3,.15])])]
        env=make_environment(EnvironmentConfig(robot=robot_fixture(),execution_backend="body_control",
            episode_seconds=.3,observation_schema=DEPTH_SCHEMA,depth_camera=profile,scenarios=scenarios),
            include_assembly=False,include_visuals=False)
        self.addCleanup(env.close)
        obs,_=env.reset(seed=1,options={"scenario":"wall"})
        for _ in range(6):
            obs,_,done,_,_=env.step(np.zeros(12))
            self.assertFalse(done)
        self.assertEqual(len(obs),observation_size(DEPTH_SCHEMA))
        observed=env.gateway_observation
        self.assertEqual(observed["schema"],DEPTH_SCHEMA)
        self.assertTrue(observed["vision"]["depth_available"])
        self.assertEqual(observed["vision"]["depthSpatial"]["frame"],"camera-optical")
        self.assertGreater(observed["vision"]["age_s"],0)
        self.assertGreater(np.count_nonzero(obs[200:264]),0)
        self.assertTrue(observed["vision"]["available"])
        self.assertFalse(observed["vision"]["metric_accuracy_verified"])
        np.testing.assert_allclose(obs[89:92], observed["vision"]["velocity_body_m_s"])

    def test_body_control_rollouts_are_deterministic_and_use_gateway_feedback(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.contract import COMMAND_SLICE
        # Reverse is -18.75% of this profile: rounding it to an integer
        # changes the requested SI velocity and invalidates teacher labels.
        commands = [[.08, 0, 0], [-.015, 0, 0]]
        env = make_environment(EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            episode_seconds=.12, command=commands[0]), include_assembly=False,
            include_visuals=False, commands=commands)
        trajectories = []
        try:
            for _ in range(2):
                observation, info = env.reset(seed=7, options={"command": commands[0]})
                self.assertEqual(info["execution_backend"], "body_control")
                self.assertEqual(info["consumed_sample"], 0)
                trace = []
                for index in range(6):
                    if index == 3:
                        before = env.data.time
                        observation = env.set_command(commands[1])
                        self.assertEqual(env.data.time, before)
                        np.testing.assert_array_equal(observation[COMMAND_SLICE], np.float32(commands[1]))
                    observation, reward, terminated, truncated, info = env.step(np.zeros(12))
                    self.assertEqual(info["ack"]["t"], "ack")
                    self.assertFalse(terminated, info)
                    self.assertEqual(truncated, index == 5)
                    self.assertGreater(info["consumed_sample"], 0)
                    feedback = env.session.connection.last_status["imu"]["joint_feedback"]
                    np.testing.assert_allclose(observation[:12],
                        np.deg2rad(feedback["filtered_model_deg"]), rtol=1e-6, atol=1e-7)
                    trace.append(np.r_[observation, reward, env.data.qpos])
                trajectories.append(trace)
            np.testing.assert_array_equal(trajectories[0], trajectories[1])
        finally:
            env.close()
        self.assertFalse(env.thread.is_alive())


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "Use a MuJoCo Python environment")
class RuntimeAndReplayTests(unittest.TestCase):
    def test_dashboard_history_keeps_trial_measurements_without_copying_time_series(self):
        from gateway.neural_gait.server import Runtime
        with tempfile.TemporaryDirectory() as root:
            run = Path(root) / "abc"
            run.mkdir()
            (run / "manifest.json").write_text('{"kind": "microduck-mjlab"}')
            (run / "environment.json").write_text("{}")
            measured = dict(mean_reward=2., falls=0, episodes=[dict(command=[.03,0,0],
                seconds=32., forward_m_s=.029, progress_intervals=[dict(reward=1.)])])
            checkpoint = run / "checkpoints.json"
            checkpoint.write_text(json.dumps([dict(id="one", evaluation=measured)]))
            evaluation = run / "evaluation.json"
            baseline = dict(measured, evaluation_purpose="source_policy_baseline",
                            checkpoint_id="initial", policy="checkpoints/initial.zip")
            evaluation.write_text(json.dumps(dict(candidate=measured, baseline=baseline)))
            originals = {path: path.read_bytes() for path in (checkpoint, evaluation)}
            status = Runtime(root).status()["runs"][0]
            for result in (status["checkpoints"][0]["evaluation"],
                           status["evaluation"]["candidate"], status["evaluation"]["baseline"]):
                self.assertEqual(result["episodes"][0]["forward_m_s"], .029)
                self.assertNotIn("progress_intervals", result["episodes"][0])
            for key in ("evaluation_purpose", "checkpoint_id", "policy"):
                self.assertEqual(status["evaluation"]["baseline"][key], baseline[key])
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)

    def test_active_metadata_does_not_scan_or_wait_for_training_history(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from unittest.mock import patch
        from gateway.neural_gait.server import Runtime
        with tempfile.TemporaryDirectory() as root:
            runtime = Runtime(root)
            runtime.model_id = "abc"
            runtime.environment = {"observation_schema": SCHEMA}
            with patch.object(Path, "glob", side_effect=AssertionError("Admission cannot scan history")):
                active = runtime.status(include_runs=False)
            self.assertEqual(active["model_id"], "abc")
            self.assertNotIn("runs", active)
            entered, release = threading.Event(), threading.Event()
            def slow_history(*args):
                entered.set()
                release.wait()
                return []
            with ThreadPoolExecutor(max_workers=2) as threads, patch.object(Path, "glob", slow_history):
                history = threads.submit(runtime.status)
                try:
                    self.assertTrue(entered.wait(2))
                    # A dashboard refresh cannot hold the model lock while
                    # another caller admits a Walk or performs inference.
                    active = threads.submit(runtime.status, include_runs=False).result(timeout=2)
                    self.assertEqual(active["model_id"], "abc")
                finally:
                    release.set()
                self.assertEqual(history.result(timeout=2)["runs"], [])


    def test_completed_video_checkpoint_survives_later_clip_failure(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.replay import render
        episode = dict(seed=1000, command=[.015,0,0])
        checkpoints = [dict(id=str(step), steps=step, evaluation=dict(episodes=[episode])) for step in [10,20]]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory/"manifest.json").write_text(json.dumps(dict(kind="microduck-mjlab", schema=SCHEMA,
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
                environment=asdict(EnvironmentConfig(robot=robot_fixture())))))
            def clipped(directory, config, checkpoint, seed, *, episode):
                if checkpoint["steps"] == 20:
                    self.assertEqual(json.loads((directory/"progress-video.json").read_text())["checkpoint_ids"], ["10"])
                    raise RuntimeError("fixture encoder failure")
                return dict(labelled="clips/first.mp4")
            def encoded(args, **kwargs):
                Path(args[-1]).write_bytes(b"published first checkpoint")
            with patch("gateway.neural_gait.replay.versions", return_value=checkpoints), \
                 patch("gateway.neural_gait.replay.clip", side_effect=clipped), \
                 patch("gateway.neural_gait.replay.subprocess.run", side_effect=encoded):
                with self.assertRaisesRegex(RuntimeError, "encoder failure"):
                    render(directory, progress=True)
            self.assertEqual((directory/"progress-video.mp4").read_bytes(), b"published first checkpoint")
            self.assertFalse((directory/"progress-video.concat.txt").exists())
            self.assertFalse((directory/"progress-video.tmp.mp4").exists())

    def test_status_sees_automatic_renderer_from_existing_artifact_lock(self):
        import fcntl
        from gateway.neural_gait.server import Runtime
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"abc"
            path.mkdir()
            (path/"manifest.json").write_text('{"kind": "microduck-mjlab"}')
            runtime = Runtime(root)
            with (path/"render.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(runtime.status()["runs"][0]["rendering"])
            self.assertFalse(runtime.status()["runs"][0]["rendering"])
            self.assertFalse(runtime.renders, "Reporting must not create another renderer manager")


    def test_per_command_results_preserve_wrong_direction_in_mixed_requests(self):
        from gateway.neural_gait.evaluation import summarize_commands
        segments = [
            dict(command=[.015,0,0], seconds=2, command_reference_travel_m=[-.004,.002], heading_change_rad=.1, reward=-4),
            dict(command=[-.03,0,0], seconds=4, command_reference_travel_m=[-.04,0], heading_change_rad=-.2, reward=20),
            dict(command=[.015,0,0], seconds=1, command_reference_travel_m=[-.002,.001], heading_change_rad=.05, reward=-2)]
        rows = summarize_commands([dict(command_segments=segments)])
        self.assertEqual(rows[0]["command"], [.015,0,0])
        self.assertEqual(rows[0]["measured_velocity_command_m_s"], [-.002,.001])
        self.assertAlmostEqual(rows[0]["measured_yaw_rate_rad_s"], .05)
        self.assertEqual(rows[0]["mean_reward_per_second"], -2)
        self.assertEqual(rows[1]["measured_velocity_command_m_s"], [-.01,0])
        self.assertIsNone(summarize_commands([dict(command=[.015,0,0],seconds=2,displacement_m=[1,0,0])]),
                          "World-frame displacement must not masquerade as command-frame progress")


    def test_automatic_comparison_uses_only_initial_and_published_matched_trial(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.replay import render
        episodes = [dict(seed=seed, command=command, command_index=index, scenario_id=scenario)
            for index, command in enumerate([[.015,0,0],[-.03,0,0]])
            for scenario in ["flat","rocks"] for seed in [1000,1001]]
        checkpoints = [dict(id=str(step), steps=step, policy=f"checkpoints/{step}.onnx",
                           evaluation=dict(episodes=episodes)) for step in [0,100,200]]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/"manifest.json").write_text(json.dumps(dict(kind="microduck-mjlab", policy="policy.onnx", schema=SCHEMA,
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
                environment=asdict(EnvironmentConfig(robot=robot_fixture())))))
            (root/"checkpoints.json").write_text(json.dumps(checkpoints))
            (root/"progress.json").write_text(json.dumps(dict(steps=200,selected_checkpoint_id="200")))
            (root/"evaluation.json").write_text(json.dumps(dict(candidate=dict(episodes=episodes))))
            seen=[]
            def clipped(directory, config, checkpoint, seed, *, episode):
                seen.append((checkpoint["id"],checkpoint["policy"],episode))
                return dict(labelled=f"clips/{checkpoint['id']}.mp4",clean=f"clips/{checkpoint['id']}-clean.mp4")
            def encoded(args, **kwargs):
                Path(args[-1]).write_bytes(b"comparison fixture")
            with patch("gateway.neural_gait.replay.clip",side_effect=clipped), \
                 patch("gateway.neural_gait.replay.subprocess.run",side_effect=encoded):
                render(root,progress=True,comparison=True)
            self.assertEqual([item[:2] for item in seen],[("0","checkpoints/0.onnx"),("200","policy.onnx")])
            self.assertEqual(seen[0][2],seen[1][2])
            self.assertEqual(seen[0][2],episodes[0])
            result=json.loads((root/"progress-video.json").read_text())
            self.assertEqual(result["footage_scope"],"initial_final_matched_trial")
            self.assertEqual(result["checkpoint_ids"],["0","200"])
            self.assertEqual(len(result["clips"]),2)
            self.assertTrue(all(item["clean"] for item in result["clips"]))

    def test_historical_clip_replay_versions_cache_without_overwriting_original(self):
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION
        from gateway.neural_gait.replay import clip, RENDER_VERSION
        config=EnvironmentConfig(robot=robot_fixture())
        episode=dict(seed=1000,command=[.015,0,0])
        checkpoint=dict(id="old",steps=0,evaluation=dict(episodes=[episode]))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/"clips").mkdir()
            (root/"manifest.json").write_text(json.dumps(dict(environment_version=ENVIRONMENT_VERSION-1)))
            original=root/"clips/old-trial1.json"
            original.write_text(json.dumps(dict(renderer_version=RENDER_VERSION,
                rollout_environment_version=ENVIRONMENT_VERSION-1)))
            original_video=root/"clips/old-trial1-clean.mp4"
            original_video.write_bytes(b"historical footage")
            original_bytes=original.read_bytes()
            current=root/f"clips/old-trial1-rollout-v{ENVIRONMENT_VERSION}.json"
            current.write_bytes(original_bytes)
            with patch("gateway.neural_gait.replay.make_environment",side_effect=RuntimeError("render required")):
                with self.assertRaisesRegex(RuntimeError,"render required"):
                    clip(root,config,checkpoint,1000,model=object(),episode=episode)
            self.assertEqual(original.read_bytes(),original_bytes)
            self.assertEqual(original_video.read_bytes(),b"historical footage")
            cached=dict(renderer_version=RENDER_VERSION,rollout_environment_version=ENVIRONMENT_VERSION,
                        training_environment_version=ENVIRONMENT_VERSION-1)
            current.write_text(json.dumps(cached))
            with patch("gateway.neural_gait.replay.make_environment") as environment:
                self.assertEqual(clip(root,config,checkpoint,1000,model=object(),episode=episode),cached)
                environment.assert_not_called()



if __name__ == "__main__":
    unittest.main()
