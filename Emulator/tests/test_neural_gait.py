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
from Emulator.tests.test_neural_gait_sensors import robot_fixture


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
        async def generate(endpoint, request):
            generated.append(request)
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
    importlib.util.find_spec("mujoco")
    and importlib.util.find_spec("stable_baselines3"),
    "Use build/gait-training-env for physics and checkpoint tests",
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
            (root/'manifest.json').write_text(json.dumps(dict(schema=SCHEMA,
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
        from gateway.neural_gait.training import evaluate
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
        with patch('gateway.neural_gait.training.make_environment', side_effect=factory):
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

    def test_imitation_exploration_calibrates_bounded_endpoints_without_changing_mean(self):
        import gymnasium as gym
        import numpy as np
        import torch
        from stable_baselines3 import SAC
        from gateway.neural_gait.training import calibrate_exploration

        class Spaces(gym.Env):
            observation_space = gym.spaces.Box(-np.inf, np.inf, (OBSERVATION_SIZE,), dtype=np.float32)
            action_space = gym.spaces.Box(-1, 1, (12,), dtype=np.float32)

        model = SAC("MlpPolicy", Spaces(), policy_kwargs={"net_arch": [8, 8]},
                    seed=1, device="cpu")
        with torch.no_grad():
            model.actor.mu.weight.zero_()
            model.actor.mu.bias.zero_()
            model.actor.mu.bias[:2] = torch.tensor([4.5, -4.5])
        x = np.random.default_rng(1).normal(0, .1, (32, OBSERVATION_SIZE)).astype(np.float32)
        before = model.predict(x, deterministic=True)[0]
        labels = before.copy()
        labels[:, :2] = [1, -1]
        labels[:, 2:] += np.where(np.arange(len(x))[:, None] % 2, .01, -.01)
        state = {key: value.clone() for key, value in model.actor.state_dict().items()}
        result = calibrate_exploration(model, x, labels, seed=1, draws=64)
        np.testing.assert_array_equal(before, model.predict(x, deterministic=True)[0])
        for key, value in state.items():
            if not key.startswith("log_std."):
                self.assertTrue(torch.equal(value, model.actor.state_dict()[key]), key)
        self.assertTrue(result["deterministic_unchanged"])
        expected = np.sqrt(np.mean((labels-before)**2, axis=0))
        np.testing.assert_allclose(result["bounded_target_rms"], expected, rtol=1e-5, atol=1e-8)
        achieved = np.asarray(result["achieved_rms"])
        self.assertTrue(np.isfinite(achieved).all())
        # Exact endpoints must not create the huge noise induced by clipping
        # labels before inverse tanh. Compare in the actual action domain.
        self.assertTrue(np.all(achieved[:2] < .002))
        np.testing.assert_allclose(achieved, expected, rtol=.15, atol=1e-5)

    def test_imitation_replay_records_executed_vector_transitions_and_can_resume(self):
        import gymnasium as gym
        import numpy as np
        from stable_baselines3 import SAC
        from stable_baselines3.common.vec_env import DummyVecEnv
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import prime_imitation_replay, load_replay, save_replay

        class EndingEnv(gym.Env):
            observation_space = gym.spaces.Box(-np.inf, np.inf, (OBSERVATION_SIZE,), dtype=np.float32)
            action_space = gym.spaces.Box(-1, 1, (12,), dtype=np.float32)

            def __init__(self, index, timeout):
                self.index, self.timeout, self.records = index, timeout, []

            def observation(self):
                return np.full(OBSERVATION_SIZE, self.index*100+self.count, dtype=np.float32)

            def reset(self, *, seed=None, options=None):
                super().reset(seed=seed)
                self.count = 0
                return self.observation(), {}

            def step(self, action):
                previous = self.observation()
                self.count += 1
                observation = self.observation()
                reward = float(self.index*10+self.count)
                terminated = not self.timeout and self.count == 2
                truncated = self.timeout and self.count == 3
                self.records.append((previous, action.copy(), reward, observation, terminated, truncated))
                return observation, reward, terminated, truncated, {"fallen": terminated}

        for endings in ((True,), (False,), (False, True)):
            with self.subTest(timeouts=endings):
                children = [EndingEnv(index, timeout) for index, timeout in enumerate(endings)]
                vector_env = DummyVecEnv([lambda child=child: child for child in children])
                try:
                    model = SAC("MlpPolicy", vector_env, policy_kwargs={"net_arch": [8, 8]},
                                buffer_size=64, batch_size=2, learning_starts=0, seed=1, device="cpu")
                    config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.06)
                    metadata, arrays = prime_imitation_replay(model, config, seed=1)
                    self.assertEqual(model.num_timesteps, 0)
                    self.assertEqual(model._n_updates, 0)
                    self.assertFalse(model.actor.optimizer.state)
                    self.assertFalse(model.critic.optimizer.state)
                    count = metadata["vector_steps"]
                    self.assertEqual(metadata["workers"], len(children))
                    self.assertEqual(metadata["transitions"], count*len(children))
                    self.assertEqual(model.replay_buffer.size(), count)
                    for worker, child in enumerate(children):
                        self.assertEqual(len(child.records), count)
                        for step, (previous, action, reward, following, terminated, truncated) in enumerate(child.records):
                            np.testing.assert_array_equal(arrays["observation"][step, worker], previous)
                            np.testing.assert_array_equal(arrays["action"][step, worker], action)
                            self.assertEqual(arrays["reward"][step, worker], reward)
                            # Verify terminal_observation, not VecEnv's reset observation.
                            np.testing.assert_array_equal(arrays["next_observation"][step, worker], following)
                            np.testing.assert_array_equal(model.replay_buffer.next_observations[step, worker], following)
                            self.assertEqual(arrays["done"][step, worker], terminated or truncated)
                            self.assertEqual(arrays["timeout"][step, worker], truncated)
                            self.assertEqual(model.replay_buffer.timeouts[step, worker], truncated)
                    with tempfile.TemporaryDirectory() as directory:
                        model.save(Path(directory)/"policy.zip")
                        model.save_replay_buffer(Path(directory)/"replay.pkl")
                        restored = SAC.load(Path(directory)/"policy.zip", env=vector_env, device="cpu")
                        self.assertTrue(load_replay(restored, directory))
                        import gzip
                        legacy_bytes = (Path(directory)/"replay.pkl").read_bytes()
                        save_replay(model, directory)
                        self.assertFalse((Path(directory)/"replay.pkl").exists())
                        self.assertFalse((Path(directory)/"replay.pending.pkl.gz").exists())
                        with gzip.open(Path(directory)/"replay.pkl.gz", "rb") as stream:
                            self.assertEqual(stream.read(), legacy_bytes)
                        self.assertLess((Path(directory)/"replay.pkl.gz").stat().st_size,
                                        len(legacy_bytes))
                        self.assertTrue(load_replay(restored, directory))
                        self.assertEqual(restored.replay_buffer.buffer_size, model.replay_buffer.buffer_size)
                        self.assertEqual(restored.replay_buffer.pos, model.replay_buffer.pos)
                        self.assertEqual(restored.replay_buffer.full, model.replay_buffer.full)
                        self.assertEqual(restored.replay_buffer.n_envs, len(children))
                        for name in ("observations", "next_observations", "actions", "rewards",
                                     "dones", "timeouts"):
                            np.testing.assert_array_equal(getattr(restored.replay_buffer, name),
                                                          getattr(model.replay_buffer, name))
                        restored.learn(total_timesteps=len(children), reset_num_timesteps=False)
                        self.assertGreater(restored._n_updates, 0)
                        self.assertGreater(restored.replay_buffer.size(), count)
                finally:
                    vector_env.close()

    def test_imitation_sac_handoff_rejects_nonpositive_measured_advantage(self):
        import numpy as np
        from unittest.mock import patch
        from stable_baselines3 import SAC
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import fit_actor, prepare_imitation_sac

        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04)
        env = GaitEnvironment(config, include_assembly=False)
        try:
            model = SAC("MlpPolicy", env, policy_kwargs={"net_arch": [8, 8]}, seed=1, device="cpu")
            observation, _ = env.reset(seed=1)
            x = np.repeat(observation[None], 4, axis=0)
            y = model.predict(x, deterministic=True)[0]
            with tempfile.TemporaryDirectory() as directory, \
                 patch("gateway.neural_gait.training.load_demonstrations", return_value=(x, y, [])), \
                 patch("gateway.neural_gait.training.evaluate", return_value={
                     "mean_reward": 1000, "episodes": [{"reward": 1000, "seconds": .04}]}):
                with self.assertRaisesRegex(ValueError, "positive deterministic advantage"):
                    prepare_imitation_sac(model, [], config, Path(directory), seed=1)
                self.assertEqual(model.num_timesteps, 0)
                self.assertEqual(model._n_updates, 0)
                result = json.loads((Path(directory)/"handoff.json").read_text())
                self.assertEqual(result["state"], "not_calibrated")
                self.assertNotIn("initial_alpha", result)
            successful = SAC("MlpPolicy", env, policy_kwargs={"net_arch": [8, 8]},
                             batch_size=2, buffer_size=16, seed=1, device="cpu")
            fit_actor(successful, x, np.zeros((len(x), 12), dtype=np.float32),
                      updates=2, seed=1)
            self.assertTrue(successful.actor.optimizer.state)
            self.assertTrue(any(float(state["exp_avg"].abs().sum()) > 0
                                for state in successful.actor.optimizer.state.values()))
            before = successful.predict(x, deterministic=True)[0]
            with tempfile.TemporaryDirectory() as directory, \
                 patch("gateway.neural_gait.training.load_demonstrations", return_value=(x, before, [])), \
                 patch("gateway.neural_gait.training.evaluate", return_value={
                     "mean_reward": -1000, "episodes": [{"reward": -1000, "seconds": .04}]}):
                result = prepare_imitation_sac(successful, [], config, Path(directory), seed=1)
                self.assertEqual(result["state"], "ready")
                self.assertTrue(result["actor_optimizer_state_reset"])
                self.assertFalse(successful.actor.optimizer.state)
                expected = (.1*result["deterministic_advantage_per_transition"] /
                            abs(result["exploration"]["after"]["mean_log_prob"]))
                self.assertAlmostEqual(result["initial_alpha"], expected)
                self.assertAlmostEqual(float(successful.log_ent_coef.detach().exp()), expected, places=5)
                self.assertEqual(successful.target_entropy,
                                 result["exploration"]["after"]["sample_entropy"])
                self.assertEqual(successful.learning_starts, 0)
                np.testing.assert_array_equal(before, successful.predict(x, deterministic=True)[0])
                transitions = np.load(Path(directory)/"handoff-transitions.npz")
                np.testing.assert_array_equal(transitions["reward"],
                                              successful.replay_buffer.rewards[:2])
                self.assertEqual(successful.num_timesteps, 0)
                successful.learn(total_timesteps=2)
                self.assertGreater(successful._n_updates, 0)
        finally:
            env.close()

    def test_parallel_rollouts_have_independent_feedback_state_and_close_workers(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import training_environment
        env = training_environment(EnvironmentConfig(robot=robot_fixture()), workers=2)
        processes = env.processes[:]
        try:
            env.seed(71)
            obs = env.reset()
            self.assertEqual(obs.shape, (2, OBSERVATION_SIZE))
            actions = np.zeros((2,12), dtype=np.float32)
            actions[1,0] = .2
            for _ in range(3):
                obs, rewards, done, info = env.step(actions)
            self.assertFalse(any(row["target_rejected"] for row in info))
            self.assertGreater(np.max(np.abs(obs[0]-obs[1])), .001)
        finally:
            env.close()
        self.assertTrue(all(not process.is_alive() for process in processes))

    def test_imitation_trains_same_actor_and_records_data_provenance(self):
        import numpy as np
        from dataclasses import asdict
        from stable_baselines3 import SAC
        from gateway.neural_gait.environment import (EnvironmentConfig, GaitEnvironment,
            ENVIRONMENT_VERSION, representation_identity)
        from gateway.neural_gait.training import imitate
        config = EnvironmentConfig(robot=robot_fixture())
        env = GaitEnvironment(config, include_assembly=False)
        try:
            model = SAC("MlpPolicy", env, policy_kwargs={"net_arch":[8,8]},
                        batch_size=32, buffer_size=8, seed=2, device="cpu")
            obs,_ = env.reset(seed=1)
            x = np.repeat(obs[None], 64, axis=0)
            x[:,-12:] = np.random.default_rng(4).uniform(-.2,.2,(64,12))
            y = .1+x[:,-12:]*.2
            with tempfile.TemporaryDirectory() as root:
                path = Path(root)/"demonstration.npz"
                np.savez(path, observation=x, action=y)
                historical_config = asdict(config)
                historical_config.pop('balance_enabled')
                historical_config.pop('balance_tuning')
                path.with_suffix(".json").write_text(json.dumps(dict(schema=SCHEMA,
                    environment_version=ENVIRONMENT_VERSION, environment=historical_config,
                    representation=representation_identity())))
                result = imitate(model, [path], config, 500, 7)
                self.assertLess(result["action_rmse_after"],result["action_rmse_before"]*.3)
                self.assertEqual(result["sources"][0]["transitions"],64)
                self.assertEqual(len(result["sources"][0]["sha256"]),64)
                different = EnvironmentConfig(robot=robot_fixture(), friction=.5)
                with self.assertRaisesRegex(ValueError,"contract"):
                    imitate(model,[path],different,1,7)
                with self.assertRaisesRegex(ValueError,"contract"):
                    imitate(model,[path],EnvironmentConfig(robot=robot_fixture(),balance_enabled=True),1,7)
        finally:
            env.close()

    def test_cycle_teacher_uses_observed_predecessor_without_a_clock(self):
        import numpy as np
        from gateway.neural_gait.training import CycleExpert
        actions = np.zeros((3, 12), dtype=np.float32)
        actions[:, 0] = [-.5, 0, .5]
        expert = CycleExpert(actions)
        observation = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
        observation[-12] = -.48  # off-trajectory state closest to the first action
        np.testing.assert_array_equal(expert(observation), actions[1])
        for _ in range(5):
            observation[:100] += 1  # irrelevant sensors cannot secretly advance phase
            np.testing.assert_array_equal(expert(observation), actions[1])
        observation[-12:] = actions[1]
        np.testing.assert_array_equal(expert(observation), actions[2])
        observation[-12:] = actions[2]
        np.testing.assert_array_equal(expert(observation), actions[0])

    def test_command_cycles_choose_successors_within_the_observed_command(self):
        import numpy as np
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.training import CycleExpert
        commands = [[.015, 0, 0], [0, 0, -.12]]
        actions = np.zeros((6, 12), dtype=np.float32)
        actions[:, 0] = [0, .3, .6, 0, -.3, -.6]
        expert = CycleExpert(actions, commands=commands, cycle_rows=[[0, 3], [3, 6]])
        observation = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
        for command, start in zip(commands, (0, 3)):
            observation[COMMAND_SLICE] = command
            observation[-12:] = actions[start]
            np.testing.assert_array_equal(expert(observation), actions[start+1])
            observation[-12:] = actions[start+2]
            np.testing.assert_array_equal(expert(observation), actions[start])
        observation[COMMAND_SLICE] = [0, 0, .12]
        with self.assertRaisesRegex(ValueError, "No teacher cycle"):
            expert(observation)
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            CycleExpert(actions, commands=[commands[0]]*2, cycle_rows=[[0, 3], [3, 6]])

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

    def test_command_curriculum_archives_evaluates_and_inherits_all_commands(self):
        import numpy as np
        from dataclasses import asdict, replace
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.environment import (
            EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, representation_identity)
        from gateway.neural_gait.training import train, load_demonstrations, evaluate
        commands = [[.015, 0, 0], [0, 0, -.12]]
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04, command=commands[0])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sources = []
            for index, command in enumerate(commands):
                path = directory/f"teacher-{index}.npz"
                observation = np.zeros((3, OBSERVATION_SIZE), dtype=np.float32)
                observation[:, COMMAND_SLICE] = command
                action = np.zeros((3, 12), dtype=np.float32)
                action[:, 0] = np.array([0, .01, .02])*(1 if index == 0 else -1)
                np.savez(path, observation=observation, action=action)
                path.with_suffix(".json").write_text(json.dumps(dict(schema=SCHEMA,
                    environment_version=ENVIRONMENT_VERSION,
                    environment=asdict(replace(config, command=command)),
                    representation=representation_identity(), recommended_cycle_rows=[0, 3])))
                sources.append(path)
            with self.assertRaisesRegex(ValueError, "contract"):
                load_demonstrations(sources, config)
            x, _, provenance = load_demonstrations(sources, config, allow_command_variation=True)
            self.assertEqual([row["command"] for row in provenance], commands)
            with self.assertRaisesRegex(ValueError, "contract"):
                load_demonstrations(sources, replace(config, friction=.4), allow_command_variation=True)
            invalid = x[:3].copy()
            invalid[:, COMMAND_SLICE] = commands[1]
            np.savez(sources[0], observation=invalid, action=np.zeros((3, 12)))
            with self.assertRaisesRegex(ValueError, "disagree"):
                load_demonstrations(sources, config, allow_command_variation=True)
            with self.assertRaisesRegex(ValueError, "disagree"):
                load_demonstrations(sources[:1], config)
            np.savez(sources[0], observation=x[:3], action=np.zeros((3, 12)))
            # Exercise maintained collection, fitting, checkpoint selection and
            # continuation together; omit rendering and expensive CAD compilation.
            with patch("gateway.neural_gait.training.make_environment",
                       partial(GaitEnvironment, include_assembly=False)), \
                 patch("gateway.neural_gait.training.Progress.render_progress"), \
                 patch("gateway.neural_gait.training.Progress.finish_rendering", return_value=True):
                run = directory/"curriculum"
                train(run, 0, config, demonstrations=sources, demonstration_cycles=True,
                      imitation_updates=1, expert_mix=(0,), updates_per_round=1)
                metadata = json.loads((run/"training-data.json").read_text())
                self.assertEqual(metadata["commands"], commands)
                with np.load(run/"training-data.npz") as archive:
                    self.assertEqual(len(archive["observation"]), 8)
                    for command in commands:
                        self.assertEqual(int(np.all(archive["observation"][:, COMMAND_SLICE]
                                                   == np.float32(command), axis=1).sum()), 4)
                aggregation = json.loads((run/"aggregation.json").read_text())
                for row in aggregation["rounds"]:
                    self.assertEqual([case["command"] for case in row["collection"]], commands)
                    self.assertEqual([case["command_index"] for case in row["evaluation"]["episodes"]], [0, 1])
                following = directory/"continued"
                train(following, 0, config, initialize_from=run)
                self.assertEqual(json.loads((following/"manifest.json").read_text())["commands"], commands)
                result = json.loads((following/"evaluation.json").read_text())["candidate"]
                self.assertEqual([case["command"] for case in result["episodes"]], commands)
                self.assertAlmostEqual(result["mean_reward"], np.mean([case["reward"] for case in result["episodes"]]))
                for case in result["episodes"]:
                    intervals = case["progress_intervals"]
                    self.assertEqual(intervals[0]["start_step"], 0)
                    self.assertAlmostEqual(sum(row["seconds"] for row in intervals), case["seconds"])
                    self.assertAlmostEqual(sum(row["reward"] for row in intervals), case["reward"])
                    np.testing.assert_allclose(np.sum([row["command_reference_travel_m"]
                        for row in intervals], axis=0), case["command_reference_travel_m"])
                single = evaluate(None, config, seeds=[1])
                self.assertNotIn("command_index", single["episodes"][0])
                legacy = directory/"explicit-single-cycle"
                train(legacy, 0, config, initialize_from=run, demonstrations=sources[:1],
                      cycle_start=0, cycle_steps=3, imitation_updates=1, expert_mix=())
                self.assertEqual(json.loads((legacy/"manifest.json").read_text())["commands"], [commands[0]])
                switched = directory/"continuous-commands"
                longer = replace(config, episode_seconds=.08)
                train(switched, 0, longer, initialize_from=run, demonstrations=sources,
                      demonstration_cycles=True, imitation_updates=1, expert_mix=(),
                      command_switch_seconds=.02)
                manifest = json.loads((switched/"manifest.json").read_text())
                self.assertEqual(manifest["initialization"]["task_changes"]["episode_seconds"],
                                 {"source": .04, "target": .08})
                data = json.loads((switched/"aggregation.json").read_text())
                self.assertEqual(data["sources"][0]["source_episode_seconds"], .04)
                self.assertEqual(data["sources"][0]["training_episode_seconds"], .08)
                for initial, case in enumerate(data["rounds"][0]["collection"]):
                    self.assertEqual(case["command"], commands[initial])
                    self.assertEqual(case["command_transition_counts"], [2, 2])
                    self.assertEqual([segment["start_step"] for segment in case["command_segments"]], [0,1,2,3])
                for initial, case in enumerate(data["rounds"][0]["evaluation"]["episodes"]):
                    self.assertEqual(case["command"], commands[initial])
                    self.assertEqual([segment["command"] for segment in case["command_segments"]],
                                     [commands[(initial+i)%2] for i in range(4)])
                    self.assertAlmostEqual(sum(segment["reward"] for segment in case["command_segments"]), case["reward"])
                    self.assertEqual(sum(segment["transitions"] for segment in case["command_segments"]), 4)
                    self.assertEqual([row["command"] for row in case["progress_intervals"]],
                                     [row["command"] for row in case["command_segments"]])
                with self.assertRaisesRegex(ValueError, "Resume requires"):
                    train(directory/"invalid-horizon-resume", 0, longer, resume=run)

    def test_command_switch_collection_preserves_physics_and_updates_actor_input(self):
        import numpy as np
        from types import SimpleNamespace
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import collect_demonstration
        commands = [[.015,0,0],[0,0,-.12]]
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12)
        class ObservedEnvironment(GaitEnvironment):
            def reset(self, **kwargs):
                self.resets = getattr(self, "resets", 0)+1
                return super().reset(**kwargs)
            def set_command(self, command):
                before = (self.data.time, self.steps, self.data.qpos.copy(), self.last_action.copy())
                observation = super().set_command(command)
                self.transitions.append((before, self.data.time, self.steps,
                                         self.data.qpos.copy(), self.last_action.copy()))
                return observation
        env = ObservedEnvironment(config, include_assembly=False)
        env.transitions = []
        calls = []
        def actor(observation, deterministic=True):
            calls.append((env.steps, observation.copy()))
            return np.full(12, .002*(env.steps+1)), None
        def expert(observation):
            np.testing.assert_array_equal(observation[COMMAND_SLICE], np.float32(commands[(env.steps//2)%2]))
            return np.full(12, -.001)
        try:
            x, y, record = collect_demonstration(env, expert, SimpleNamespace(predict=actor),
                0, np.random.default_rng(1), 1, commands[0], commands=commands,
                command_switch_seconds=.04)
            self.assertEqual(env.resets, 1)
            self.assertEqual(len(env.transitions), 2)
            self.assertEqual(env.steps, 6)
            self.assertAlmostEqual(env.data.time, .12)
            for before, after_time, after_step, after_pose, after_action in env.transitions:
                self.assertEqual(before[0], after_time)
                self.assertEqual(before[1], after_step)
                np.testing.assert_array_equal(before[2], after_pose)
                np.testing.assert_array_equal(before[3], after_action)
            self.assertEqual([step for step, _ in calls], list(range(6)))
            for step, observation in calls:
                np.testing.assert_array_equal(observation[COMMAND_SLICE], np.float32(commands[(step//2)%2]))
                np.testing.assert_allclose(observation[-12:], .002*step, atol=1e-8)
            self.assertEqual(record["command_transition_counts"], [4,2])
            self.assertEqual([row["transitions"] for row in record["command_segments"]], [2,2,2])
            self.assertEqual(record["command"], commands[0])
            self.assertAlmostEqual(sum(row["reward"] for row in record["command_segments"]), record["reward"])
            np.testing.assert_allclose(np.sum([row["displacement_m"] for row in record["command_segments"]], axis=0),
                                       record["displacement_m"])
            self.assertTrue(all(row["expert_actions"] == 0 for row in record["command_segments"]))
            np.testing.assert_allclose(y, -.001)
        finally:
            env.close()

    def test_command_handoff_weights_standing_by_actual_replay_commands(self):
        import numpy as np
        from unittest.mock import patch
        from stable_baselines3 import SAC
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import prepare_imitation_sac
        commands = [[-.015, 0, 0], [0, 0, .12]]
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04)
        env = GaitEnvironment(config, include_assembly=False, commands=commands)
        try:
            model = SAC("MlpPolicy", env, policy_kwargs={"net_arch": [8, 8]},
                        batch_size=2, buffer_size=16, seed=1, device="cpu")
            x = np.array([env.reset(seed=1, options={"command": command})[0]
                          for command in commands])
            y = model.predict(x, deterministic=True)[0]
            baseline = {"episodes": [dict(command_index=index, command=command,
                                          reward=-1000*(index+1), seconds=.04)
                                     for index, command in enumerate(commands)]}
            with tempfile.TemporaryDirectory() as directory, \
                 patch("gateway.neural_gait.training.load_demonstrations", return_value=(x, y, [])), \
                 patch("gateway.neural_gait.training.evaluate", return_value=baseline) as evaluate:
                result = prepare_imitation_sac(model, [], config, directory, seed=1, commands=commands)
                counts = result["command_transition_counts"]
                self.assertEqual(sum(counts), 2)
                expected = sum(count*-500*(index+1) for index, count in enumerate(counts))/sum(counts)
                self.assertEqual(result["standing_mean_reward_per_transition"], expected)
                self.assertEqual(evaluate.call_args.kwargs["commands"], commands)
                with np.load(Path(directory)/"handoff-transitions.npz") as trace:
                    self.assertEqual(trace["command"].shape, (2, 1, 3))
                    np.testing.assert_allclose(trace["command"][:, :, :],
                                               trace["observation"][:, :, 82:85])
                self.assertEqual(model.learning_starts, 0)
                self.assertEqual(model.num_timesteps, 0)
        finally:
            env.close()

    def test_aggregation_checkpoints_keep_failed_rounds_and_publish_best_exactly(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from gateway.neural_gait.training import Progress, publish_selected
        from gateway.neural_gait.replay import versions
        from gateway.neural_gait.environment import EnvironmentConfig
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            model = SimpleNamespace(num_timesteps=0, payload=b"first")
            model.save = lambda path: Path(path).write_bytes(model.payload)
            progress = Progress(directory, 0, EnvironmentConfig())
            progress.model = model
            scores = [dict(falls=0, mean_reward=2), dict(falls=0, mean_reward=5),
                      dict(falls=1, mean_reward=100), dict(falls=0, mean_reward=1)]
            with patch("gateway.neural_gait.training.evaluate", side_effect=scores), \
                 patch.object(progress, "render_progress"):
                for round_id in range(4):
                    model.payload = f"round-{round_id}".encode()
                    progress.imitation_updates = 3000+2000*round_id
                    progress.checkpoint(aggregation_round=round_id, training_states=10*(round_id+1))
            self.assertEqual(len({row["id"] for row in progress.checkpoints}), 4)
            self.assertEqual([row["steps"] for row in progress.checkpoints], [0]*4)
            self.assertEqual([row["imitation_updates"] for row in progress.checkpoints],
                             [3000,5000,7000,9000])
            selected = publish_selected(directory, progress.checkpoints)
            self.assertEqual(selected["aggregation_round"], 1)
            self.assertEqual((directory/"policy.zip").read_bytes(), b"round-1")
            self.assertEqual(len(list((directory/"checkpoints").glob("*.zip"))), 4)
            progress._on_step()
            self.assertEqual(json.loads((directory/"progress.json").read_text())["imitation_updates"], 9000)
            (directory/"progress.json").write_text(json.dumps(dict(steps=0)))
            (directory/"evaluation.json").write_text(json.dumps(dict(candidate=selected["evaluation"])))
            replay = versions(directory, False)[0]
            self.assertEqual(replay["id"], selected["id"])
            self.assertEqual(replay["imitation_updates"], 5000)
            self.assertEqual(replay["evaluation"], scores[1])

    def test_weights_only_initialization_keeps_parameters_and_discards_learning_state(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict
        from unittest.mock import patch
        from stable_baselines3 import SAC
        from gateway.neural_gait.environment import (
            EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, GEOMETRY,
            representation_identity,
        )
        from gateway.neural_gait.training import initialize_model, new_model
        config = EnvironmentConfig(robot=robot_fixture())
        env = GaitEnvironment(config, include_assembly=False)
        try:
            source = SAC("MlpPolicy", env, policy_kwargs={"net_arch": [8, 8]},
                         learning_starts=0, batch_size=2, buffer_size=16, seed=1, device="cpu")
            source.learn(total_timesteps=4)
            self.assertTrue(source.actor.optimizer.state)
            self.assertGreater(source.replay_buffer.size(), 0)
            with tempfile.TemporaryDirectory() as root:
                path = Path(root)
                source.save(path / "policy.zip")
                # An initializer must never deserialize a source replay buffer.
                (path / "replay.pkl").write_bytes(b"incompatible old reward replay")
                (path / "progress.json").write_text(json.dumps(dict(imitation_updates=15000)))
                (path / "manifest.json").write_text(json.dumps(dict(
                    schema=SCHEMA, environment_version=5, environment=asdict(config),
                    representation=representation_identity(),
                    geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())))
                with patch.object(SAC, "load_replay_buffer", side_effect=AssertionError("old replay read")):
                    model, provenance = initialize_model(path, env, config)
                for key, value in source.actor.state_dict().items():
                    self.assertTrue(torch.equal(value, model.actor.state_dict()[key]), key)
                fresh = new_model(env, "cpu", 1, policy_kwargs=source.policy_kwargs)
                for key, value in fresh.critic.state_dict().items():
                    self.assertTrue(torch.equal(value, model.critic.state_dict()[key]), key)
                for key, value in fresh.critic_target.state_dict().items():
                    self.assertTrue(torch.equal(value, model.critic_target.state_dict()[key]), key)
                self.assertTrue(any(not torch.equal(value, model.critic.state_dict()[key])
                                    for key, value in source.critic.state_dict().items()))
                self.assertTrue(torch.equal(source.log_ent_coef, model.log_ent_coef))
                obs, _ = env.reset(seed=1)
                np.testing.assert_array_equal(source.predict(obs, deterministic=True)[0],
                                              model.predict(obs, deterministic=True)[0])
                self.assertEqual(model.policy_kwargs["net_arch"], [8, 8])
                self.assertEqual(model.num_timesteps, 0)
                self.assertEqual(model._n_updates, 0)
                self.assertEqual(model.replay_buffer.size(), 0)
                self.assertFalse(model.actor.optimizer.state)
                self.assertFalse(model.critic.optimizer.state)
                self.assertFalse(model.ent_coef_optimizer.state)
                self.assertEqual(provenance["source_rl_steps"], 4)
                self.assertEqual(provenance["source_environment_version"], 5)
                self.assertEqual(provenance["training_environment_version"], ENVIRONMENT_VERSION)
                self.assertEqual(provenance["source_imitation_updates"], 15000)
                self.assertEqual(provenance["source_checkpoint_sha256"],
                                 hashlib.sha256((path / "policy.zip").read_bytes()).hexdigest())
                model.learn(total_timesteps=2)
                self.assertEqual(model.num_timesteps, 2)
                self.assertEqual(model._n_updates, 0)  # fresh learner warmup
                self.assertEqual(model.replay_buffer.size(), 2)
                # Explicit weights-only transfer can learn a new command with
                # the existing balance owner; it must not inherit old replay.
                adapted_config = EnvironmentConfig(robot=robot_fixture(), command=[-.015,0,0],
                                                     balance_enabled=True)
                adapted_env = GaitEnvironment(adapted_config, include_assembly=False)
                try:
                    adapted, transfer = initialize_model(path, adapted_env, adapted_config)
                    for key, value in source.actor.state_dict().items():
                        self.assertTrue(torch.equal(value, adapted.actor.state_dict()[key]))
                    self.assertEqual(set(transfer['task_changes']),{'command','balance_enabled'})
                    self.assertEqual(adapted.replay_buffer.size(),0)
                    self.assertFalse(adapted.actor.optimizer.state)
                    # The train entrypoint must execute the new command, not
                    # silently inherit an old multi-command reset pool.
                    manifest_path=path/'manifest.json'
                    manifest=json.loads(manifest_path.read_text())
                    manifest['commands']=[config.command,[0,0,.12]]
                    manifest_path.write_text(json.dumps(manifest))
                    from gateway.neural_gait.training import train
                    result=dict(scope='simulation_only',episodes=[],falls=0,mean_reward=0.)
                    with patch('gateway.neural_gait.training.Progress.render_progress'), \
                         patch('gateway.neural_gait.training.Progress.finish_rendering',return_value=True), \
                         patch('gateway.neural_gait.training.evaluate',return_value=result) as evaluate:
                        train(path/'new-command',0,adapted_config,initialize_from=path)
                    self.assertTrue(evaluate.call_args_list)
                    for call in evaluate.call_args_list:
                        self.assertEqual(call.kwargs['commands'],[adapted_config.command])
                    recorded=json.loads((path/'new-command/manifest.json').read_text())
                    self.assertEqual(recorded['commands'],[adapted_config.command])
                finally:
                    adapted_env.close()
        finally:
            env.close()

    def test_weights_only_initialization_rejects_incompatible_contract_before_loading(self):
        import hashlib
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GEOMETRY, representation_identity
        from gateway.neural_gait.training import initialize_model, train
        config = EnvironmentConfig(robot=robot_fixture())
        manifest = dict(schema=SCHEMA, environment_version=6, environment=asdict(config),
                        representation=representation_identity(),
                        geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            for field, value in (("schema", "old-schema"), ("environment_version", 4),
                                 ("representation", {}), ("geometry_sha256", "different"),
                                 ("environment", asdict(EnvironmentConfig(robot=robot_fixture(), friction=.5)))):
                with self.subTest(field=field):
                    (path / "manifest.json").write_text(json.dumps(dict(manifest, **{field: value})))
                    with patch("gateway.neural_gait.training.SAC.load") as load:
                        with self.assertRaisesRegex(ValueError, "compatible"):
                            initialize_model(path, None, config)
                        load.assert_not_called()
            with self.assertRaisesRegex(ValueError, "not both"):
                train(path / "unused", 1, config, resume=path, initialize_from=path)
            self.assertFalse((path / "unused").exists())
            original = (path / "manifest.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "preserved source"):
                train(path, 1, config, initialize_from=path)
            self.assertEqual((path / "manifest.json").read_bytes(), original)

    def test_final_checkpoint_contains_final_optimizer_update(self):
        from unittest.mock import patch
        from stable_baselines3 import SAC
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import Progress
        config = EnvironmentConfig(robot=robot_fixture())
        env = GaitEnvironment(config, include_assembly=False)
        try:
            with tempfile.TemporaryDirectory() as root:
                model = SAC("MlpPolicy", env, policy_kwargs={"net_arch":[8,8]},
                            learning_starts=0, batch_size=2, buffer_size=8, device="cpu")
                progress = Progress(Path(root), 4, config, checkpoint_every=2)
                with patch("gateway.neural_gait.training.evaluate", return_value={}), \
                     patch.object(progress, "render_progress"):
                    model.learn(total_timesteps=4, callback=progress)
                    progress.checkpoint()
                saved = SAC.load(Path(root)/"checkpoints/000000004.zip", device="cpu")
                self.assertEqual([r["steps"] for r in progress.checkpoints], [0,2,4])
                for key, value in model.policy.state_dict().items():
                    self.assertTrue(value.equal(saved.policy.state_dict()[key]), key)
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
        finally:
            env.close()

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
        observed=env.set_command([-.02,0,0])
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
            heading_rad=yaw,velocity_body_m_s=[-.02,0,0],upright=1,
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
            with patch("gateway.neural_gait.server.load_policy") as load:
                runtime = Runtime(root)
                status = runtime.status()
                load.assert_not_called()
            self.assertIsNone(status["model_id"])
            self.assertIn("representation differs", status["selection_error"])
            self.assertEqual(selected.read_text(), original)
            (path / "manifest.json").write_text(
                json.dumps(
                    dict(
                        schema="ainekio-neural-gait-v1",
                        environment_version=ENVIRONMENT_VERSION,
                        environment={},
                    )
                )
            )
            with patch("gateway.neural_gait.server.load_policy") as load:
                old_schema = Runtime(root)
                load.assert_not_called()
            self.assertIsNone(old_schema.model_id)
            self.assertIn("representation differs", old_schema.selection_error)

    def test_checkpoint_server_loads_same_actions_after_restart_and_records_domain(
        self,
    ):
        import numpy as np
        from dataclasses import asdict
        from unittest.mock import patch
        from stable_baselines3 import SAC
        from gateway.neural_gait.environment import (
            EnvironmentConfig,
            GaitEnvironment,
            ENVIRONMENT_VERSION,
            representation_identity,
        )
        from gateway.neural_gait.server import Runtime

        config = EnvironmentConfig(robot=robot_fixture())
        env = GaitEnvironment(config, include_assembly=False)
        try:
            with tempfile.TemporaryDirectory() as root:
                path = Path(root) / "abc"
                path.mkdir()
                (path / "manifest.json").write_text(
                    json.dumps(
                        dict(
                            schema=SCHEMA,
                            environment=asdict(config),
                            environment_version=ENVIRONMENT_VERSION,
                            representation=representation_identity(),
                        )
                    )
                )
                (path / "environment.json").write_text(json.dumps(asdict(config)))
                # An untrained small checkpoint exercises delivery, not learning quality.
                policy = SAC(
                    "MlpPolicy",
                    env,
                    policy_kwargs={"net_arch": [8, 8]},
                    buffer_size=16,
                    device="cpu",
                )
                policy.save(path / "policy.zip")
                runtime = Runtime(root)
                self.assertIsNone(runtime.model_id)
                runtime.load("abc")
                env.reset(seed=1)
                obs = env.observation()
                first = runtime.infer(obs)
                restored = Runtime(root).infer(obs)
                np.testing.assert_array_equal(
                    first["targets_deg"], restored["targets_deg"]
                )
                manifest_path = path / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                # Reward-only revisions do not change inference or playback.
                for version in (5, 6):
                    manifest["environment_version"] = version
                    manifest_path.write_text(json.dumps(manifest))
                    runtime.load("abc")
                    np.testing.assert_array_equal(
                        first["targets_deg"], runtime.infer(obs)["targets_deg"])
                self.assertEqual(first["execution"], "preview_only")
                self.assertEqual(runtime.status()["runs"][0]["id"], "abc")
                changed_cad = dict(representation_identity(), assembly_sha256="different")
                with patch("gateway.neural_gait.server.representation_identity", return_value=changed_cad):
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
                "manifest.json": b'{"environment": {}}',
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

    def test_ppo_saturated_actions_preserve_likelihood_through_rollout_minibatches(self):
        import gymnasium as gym
        import numpy as np
        import torch
        from gateway.neural_gait.training import GaitPPOPolicy, PreciseActionRolloutBuffer

        observation_space = gym.spaces.Box(-np.inf, np.inf, (OBSERVATION_SIZE,), dtype=np.float32)
        action_space = gym.spaces.Box(-1, 1, (12,), dtype=np.float32)
        policy = GaitPPOPolicy(observation_space, action_space, lambda _: .0003,
                               net_arch=[8, 8], learned_std=True)
        with torch.no_grad():
            policy.action_net.weight.zero_()
            policy.action_net.bias.copy_(torch.tensor([9.2, -9.2]*6))
            policy.log_std.fill_(-3)
            obs = torch.zeros((4, OBSERVATION_SIZE))
            action, value, log_prob = policy(obs)
            deterministic = policy(obs, deterministic=True)[0]
        self.assertEqual(action.dtype, torch.float64)
        self.assertTrue(torch.all(action.abs() < 1))
        self.assertTrue(torch.any(action.float().abs() == 1))
        self.assertTrue(torch.isfinite(log_prob).all())
        torch.testing.assert_close(deterministic, torch.tanh(policy.action_net.bias).expand_as(deterministic),
                                   rtol=0, atol=0)
        buffer = PreciseActionRolloutBuffer(4, observation_space, action_space, device="cpu")
        for index in range(4):
            buffer.add(obs[index:index+1].numpy(), action[index:index+1].numpy(),
                       np.zeros(1), np.array([index == 0]), value[index:index+1],
                       log_prob[index:index+1])
        buffer.compute_returns_and_advantage(torch.zeros(1), np.ones(1))
        samples = next(buffer.get())
        self.assertEqual(samples.actions.dtype, torch.float64)
        _, replayed, _ = policy.evaluate_actions(samples.observations, samples.actions)
        # SB3 stores old log probabilities in float32, while the tanh inverse
        # retains the sampled action in float64. Ratios must still start at one.
        torch.testing.assert_close(replayed, samples.old_log_prob.double(), rtol=0, atol=1e-5)
        loss = -replayed.mean()
        policy.optimizer.zero_grad()
        loss.backward()
        self.assertTrue(torch.isfinite(policy.action_net.bias.grad).all())
        self.assertTrue(torch.isfinite(policy.log_std.grad).all())

    def test_policy_artifact_loader_preserves_sac_labels_and_rejects_unknown_algorithm(self):
        from unittest.mock import patch
        from gateway.neural_gait.training import load_policy
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            for algorithm in (None, "SAC", "DAgger behavior cloning of SAC actor"):
                manifest = {} if algorithm is None else {"algorithm": algorithm}
                (path/"manifest.json").write_text(json.dumps(manifest))
                with patch("gateway.neural_gait.training.SAC.load") as sac, \
                     patch("gateway.neural_gait.training.PPO.load") as ppo:
                    self.assertIs(load_policy(path), sac.return_value)
                    sac.assert_called_once_with(path/"policy.zip", device="cpu", env=None)
                    ppo.assert_not_called()
            (path/"manifest.json").write_text('{"algorithm": "unrecognized"}')
            with patch("gateway.neural_gait.training.SAC.load") as sac, \
                 patch("gateway.neural_gait.training.PPO.load") as ppo:
                with self.assertRaisesRegex(ValueError, "Unsupported.*algorithm"):
                    load_policy(path)
                sac.assert_not_called()
                ppo.assert_not_called()

    def test_ppo_action_space_exploration_escapes_saturated_means_and_restores_optimizer(self):
        import numpy as np
        import torch
        from copy import deepcopy
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import (
            GaitPPO, GaitPPOPolicy, PreciseActionRolloutBuffer, configure_action_exploration)
        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture(), episode_seconds=.08),
                              include_assembly=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=4, batch_size=4, n_epochs=1,
                       learning_rate=3e-7, rollout_buffer_class=PreciseActionRolloutBuffer,
                       policy_kwargs=dict(net_arch=[8, 8], learned_std=True), seed=1)
        model.learn(total_timesteps=8)
        policy = model.policy
        with torch.no_grad():
            policy.action_net.weight.zero_()
            policy.action_net.bias.copy_(torch.tensor([4., -4.]*6))
        observations = torch.zeros((4096, OBSERVATION_SIZE))
        before = model.predict(observations[:4].numpy(), deterministic=True)[0]
        moments = {name: deepcopy(policy.optimizer.state[parameter])
                   for name, parameter in policy.named_parameters() if parameter in policy.optimizer.state}
        weights = deepcopy(policy.state_dict())
        change = configure_action_exploration(model, [.01]*12)
        self.assertEqual(change["reset_optimizer_parameters"], ["log_std"])
        self.assertNotIn(policy.log_std, policy.optimizer.state)
        policy.configure_value_learning(3e-4)
        model.policy_kwargs["value_learning_rate"] = 3e-4
        for name, parameter in policy.named_parameters():
            if name == "log_std":
                continue
            torch.testing.assert_close(parameter, weights[name], rtol=0, atol=0)
            if name in moments:
                for key, value in moments[name].items():
                    torch.testing.assert_close(policy.optimizer.state[parameter][key], value, rtol=0, atol=0)
        np.testing.assert_allclose(model.predict(observations[:4].numpy(), deterministic=True)[0],
                                   before, rtol=0, atol=1e-7)
        with torch.no_grad():
            sampled, _, original_log_prob = policy(observations)
            executed = sampled.clamp(-1, 1)
            _, replayed, _ = policy.evaluate_actions(observations, sampled)
        self.assertTrue(torch.any(sampled.abs() > 1))
        self.assertTrue(torch.all(executed.std(0) > .004))
        self.assertTrue(torch.all((executed.abs() < .99).float().mean(0) > .12))
        torch.testing.assert_close(replayed, original_log_prob)
        self.assertLessEqual(np.max(np.abs(model.predict(observations.numpy(), deterministic=False)[0])), 1.)
        with tempfile.TemporaryDirectory() as root:
            model.save(Path(root)/"policy")
            restored = GaitPPO.load(Path(root)/"policy", env=env)
            self.assertEqual(restored.policy.action_coordinates, "action")
            self.assertEqual(restored.policy.value_learning_rate, 3e-4)
            restored.learn(total_timesteps=4, reset_num_timesteps=False)
            rates = {group["gait_role"]: group["lr"] for group in restored.policy.optimizer.param_groups}
            self.assertEqual(rates, dict(actor=3e-7, value=3e-4))
            self.assertEqual(restored.num_timesteps, 12)
            self.assertGreater(float(restored.policy.optimizer.state[restored.policy.value_net.weight]["step"]),
                               float(moments["value_net.weight"]["step"]))

    def test_training_module_cli_uses_canonical_saved_policy_classes(self):
        import os
        import subprocess
        import sys
        # -m must enter the same owner module used by saved PPO policy classes,
        # rather than configuring them through incompatible __main__ copies.
        code = """import runpy,warnings
from unittest.mock import patch
import gateway.neural_gait.training as owner
with patch.object(owner,'main') as entry, warnings.catch_warnings():
    warnings.simplefilter('ignore',RuntimeWarning)
    runpy.run_module('gateway.neural_gait.training',run_name='__main__')
    entry.assert_called_once_with()
"""
        subprocess.run([sys.executable, "-c", code], check=True,
                       env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]/"Master")),
                       capture_output=True, text=True)

    def test_ppo_command_units_preserve_function_and_transform_adam_coordinates(self):
        import numpy as np
        import torch
        from copy import deepcopy
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import GaitPPO, GaitPPOPolicy, configure_command_units
        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture(), episode_seconds=.08),
                              include_assembly=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=4, batch_size=4, n_epochs=1,
                       policy_kwargs=dict(net_arch=[8, 8], learned_std=True,
                                          action_coordinates="action", value_learning_rate=3e-4), seed=1)
        model.learn(total_timesteps=8)
        x = torch.randn(32, OBSERVATION_SIZE)
        x[:, COMMAND_SLICE] *= x.new_tensor([.03, .03, .5])
        raw = x.clone()
        policy = model.policy
        before_action = model.predict(x.numpy(), deterministic=True)[0]
        with torch.no_grad(): before_value = policy.predict_values(x)
        weights = deepcopy(policy.state_dict())
        moments = {name: deepcopy(policy.optimizer.state[parameter])
                   for name, parameter in policy.named_parameters() if parameter in policy.optimizer.state}
        units = [.03, .03, .5]
        change = configure_command_units(model, units)
        self.assertEqual(change["source"], [1., 1., 1.])
        np.testing.assert_allclose(model.predict(x.numpy(), deterministic=True)[0], before_action,
                                   rtol=0, atol=1e-6)
        with torch.no_grad(): torch.testing.assert_close(policy.predict_values(x), before_value, rtol=0, atol=1e-6)
        with torch.no_grad():
            actions, values, log_prob = policy(x, deterministic=True)
            np.testing.assert_allclose(actions.numpy(), before_action, rtol=0, atol=1e-6)
            torch.testing.assert_close(values, before_value, rtol=0, atol=1e-6)
            _, replayed, _ = policy.evaluate_actions(x, actions)
            torch.testing.assert_close(replayed, log_prob)
        torch.testing.assert_close(x, raw, rtol=0, atol=0)
        changed = {"mlp_extractor.policy_net.0.weight", "mlp_extractor.value_net.0.weight"}
        for name, parameter in policy.named_parameters():
            expected = weights[name].clone()
            if name in changed: expected[:, COMMAND_SLICE] *= expected.new_tensor(units)
            torch.testing.assert_close(parameter, expected, rtol=0, atol=0)
            for key, prior in moments.get(name, {}).items():
                expected = prior.clone()
                if name in changed and key in ("exp_avg", "exp_avg_sq", "max_exp_avg_sq"):
                    expected[:, COMMAND_SLICE] /= expected.new_tensor(units)**(1 if key == "exp_avg" else 2)
                torch.testing.assert_close(policy.optimizer.state[parameter][key], expected, rtol=0, atol=0)
        with tempfile.TemporaryDirectory() as root:
            model.save(Path(root)/"policy")
            restored = GaitPPO.load(Path(root)/"policy", env=env)
            self.assertEqual(restored.policy.command_units, units)
            np.testing.assert_allclose(restored.predict(x.numpy(), deterministic=True)[0], before_action,
                                       rtol=0, atol=1e-6)
            restored.learn(total_timesteps=4, reset_num_timesteps=False)
            self.assertEqual(restored.num_timesteps, 12)

    def test_ppo_artifact_roundtrip_preserves_full_state_and_service_inference(self):
        import hashlib
        import os
        import subprocess
        import sys
        import numpy as np
        import torch
        from dataclasses import asdict
        from stable_baselines3 import PPO
        from gateway.neural_gait.environment import (
            EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, GEOMETRY, representation_identity)
        from gateway.neural_gait.server import Runtime
        from gateway.neural_gait.training import GaitPPOPolicy, PreciseActionRolloutBuffer, load_policy

        def equal_state(first, second):
            if isinstance(first, torch.Tensor):
                torch.testing.assert_close(first, second, rtol=0, atol=0)
            elif isinstance(first, dict):
                self.assertEqual(first.keys(), second.keys())
                for key in first:
                    equal_state(first[key], second[key])
            elif isinstance(first, (list, tuple)):
                self.assertEqual(len(first), len(second))
                for left, right in zip(first, second):
                    equal_state(left, right)
            else:
                self.assertEqual(first, second)

        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.08)
        env = GaitEnvironment(config, include_assembly=False)
        try:
            for learned_std in (False, True):
                with self.subTest(learned_std=learned_std), tempfile.TemporaryDirectory() as root:
                    run = Path(root)/"abc"
                    run.mkdir()
                    model = PPO(GaitPPOPolicy, env, n_steps=4, batch_size=4, n_epochs=1,
                                rollout_buffer_class=PreciseActionRolloutBuffer,
                                policy_kwargs=dict(net_arch=[8, 8], learned_std=learned_std),
                                seed=1, device="cpu")
                    model.learn(total_timesteps=8)
                    self.assertTrue(model.policy.optimizer.state)
                    model.save(run/"policy.zip")
                    (run/"manifest.json").write_text(json.dumps(dict(algorithm="PPO", schema=SCHEMA,
                        environment=asdict(config), environment_version=ENVIRONMENT_VERSION,
                        representation=representation_identity(),
                        geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())))
                    restored = load_policy(run, env=env)
                    self.assertIsInstance(restored, PPO)
                    self.assertIsInstance(restored.rollout_buffer, PreciseActionRolloutBuffer)
                    self.assertEqual(restored.policy.log_std.requires_grad, learned_std)
                    self.assertEqual(restored.num_timesteps, model.num_timesteps)
                    self.assertEqual(restored._n_updates, model._n_updates)
                    equal_state(restored.get_parameters(), model.get_parameters())
                    state, _ = env.reset(seed=1)
                    expected = model.predict(state, deterministic=True)[0]
                    np.testing.assert_array_equal(restored.predict(state, deterministic=True)[0], expected)
                    runtime = Runtime(root)
                    runtime.load("abc")
                    result = runtime.infer(env.observation())
                    np.testing.assert_array_equal(result["action"], expected)
                    np.testing.assert_array_equal(Runtime(root).infer(env.observation())["action"], expected)
                    # A clean interpreter must resolve every saved class through
                    # maintained modules, without experiment or /tmp imports.
                    code = """import json,sys,numpy as np
from gateway.neural_gait.training import load_policy
model=load_policy(sys.argv[1])
print(json.dumps(dict(module=type(model.policy).__module__,learned=model.policy.log_std.requires_grad,
    action=model.predict(np.asarray(json.loads(sys.argv[2]),dtype=np.float32),deterministic=True)[0].tolist())))
"""
                    process_env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]/"Master"))
                    process = subprocess.run([sys.executable, "-c", code, str(run), json.dumps(state.tolist())],
                                             cwd=root, env=process_env, check=True, capture_output=True, text=True)
                    fresh = json.loads(process.stdout)
                    self.assertEqual(fresh["module"], "gateway.neural_gait.training")
                    self.assertEqual(fresh["learned"], learned_std)
                    np.testing.assert_array_equal(fresh["action"], expected)
                    restored.learn(total_timesteps=4, reset_num_timesteps=False)
                    self.assertGreater(restored.num_timesteps, model.num_timesteps)
                    self.assertGreater(restored._n_updates, model._n_updates)
        finally:
            env.close()

    def test_ppo_artifact_cannot_enter_sac_imitation(self):
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import initialize_model, train

        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/"abc"
            source.mkdir()
            (source/"manifest.json").write_text('{"algorithm": "PPO"}')
            config = EnvironmentConfig(robot=robot_fixture())
            with patch("gateway.neural_gait.training.SAC.load") as sac:
                for operation in (dict(initialize_from=source, demonstrations=["unused.npz"]),
                                  dict(resume=source, demonstrations=["unused.npz"])):
                    destination = Path(root)/"unsupported"
                    with self.assertRaisesRegex(ValueError, "cannot consume a PPO"):
                        train(destination, 4, config, **operation)
                    self.assertFalse(destination.exists())
                sac.assert_not_called()

    def test_ppo_depth_input_extension_preserves_learned_actions(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict, replace
        from stable_baselines3 import PPO
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment, GEOMETRY, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.training import GaitPPOPolicy, initialize_model
        config = EnvironmentConfig(robot=robot_fixture(),episode_seconds=.08)
        original = GaitEnvironment(config, include_assembly=False)
        extended = GaitEnvironment(replace(config,observation_schema=DEPTH_SCHEMA),include_assembly=False)
        self.addCleanup(original.close)
        self.addCleanup(extended.close)
        model = PPO(GaitPPOPolicy,original,n_steps=4,batch_size=4,n_epochs=1,
                    policy_kwargs=dict(net_arch=[8,8],learned_std=True),seed=1)
        model.learn(total_timesteps=8)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)
            model.save(path/'policy.zip')
            (path/'manifest.json').write_text(json.dumps(dict(algorithm='PPO',schema=SCHEMA,
                environment=asdict(config),environment_version=ENVIRONMENT_VERSION,
                representation=representation_identity(),geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())))
            transferred, provenance = initialize_model(path,extended,extended.config)
            self.assertTrue(provenance['critic_parameters_loaded'])
            self.assertEqual(provenance['source_rl_steps'],8)
            old,_=original.reset(seed=4)
            new,_=extended.reset(seed=4)
            from gateway.depth_motion import spatial_depth
            grid=spatial_depth(np.full((8,8),.5),[[8,0,4],[0,8,4],[0,0,1]],
                units="estimated-metres",scale_source="test",intrinsics_source="test")
            new=np.asarray(vector({**extended.observation(),"vision":dict(
                depthSpatial=grid,depth_available=True,depth_min_m=.5,age_s=.2)}),dtype=np.float32)
            np.testing.assert_allclose(model.predict(old,deterministic=True)[0],
                transferred.predict(new,deterministic=True)[0],rtol=0,atol=1e-7)
            old_value=model.policy.predict_values(torch.tensor(old).reshape(1,-1))
            new_value=transferred.policy.predict_values(torch.tensor(new).reshape(1,-1))
            torch.testing.assert_close(old_value,new_value)
            transferred.learn(total_timesteps=4)
            self.assertGreater(transferred._n_updates,0)
            from gateway.neural_gait.server import Runtime
            artifact=path/'abc'
            artifact.mkdir()
            transferred.save(artifact/'policy.zip')
            manifest=json.loads((path/'manifest.json').read_text())
            manifest.update(schema=DEPTH_SCHEMA,environment=asdict(extended.config))
            (artifact/'manifest.json').write_text(json.dumps(manifest))
            runtime=Runtime(path)
            self.assertEqual(runtime.load('abc')['schema'],DEPTH_SCHEMA)
            self.assertEqual(runtime.infer(extended.observation())['schema'],DEPTH_SCHEMA)

    def test_request_switch_preserves_physics_and_reaches_actor_before_next_action(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import CommandRequests
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
        from gateway.neural_gait.training import CommandRequests, request_interval_steps
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.4)
        commands = [[.015, 0, 0], [-.03, 0, 0]]
        body = GaitEnvironment(config, include_assembly=False)
        requests = CommandRequests(body, commands, command_switch_range=[.04, .08])
        try:
            traces = []
            for _ in range(2):
                with patch("gateway.neural_gait.training.request_interval_steps",
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

    def test_maintained_ppo_resume_preserves_optimizer_and_inherits_or_changes_requests(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict
        from functools import partial
        from unittest.mock import patch
        from stable_baselines3 import PPO
        from gateway.neural_gait.environment import (
            EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, GEOMETRY, representation_identity)
        from gateway.neural_gait.training import (
            GaitPPOPolicy, PreciseActionRolloutBuffer, load_policy, train)
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.08)
        commands = [[.015, 0, 0], [-.03, 0, 0]]
        env = GaitEnvironment(config, include_assembly=False)
        try:
            with tempfile.TemporaryDirectory() as root:
                source = Path(root)/"source"
                source.mkdir()
                model = PPO(GaitPPOPolicy, env, n_steps=4, batch_size=4, n_epochs=1,
                            rollout_buffer_class=PreciseActionRolloutBuffer,
                            policy_kwargs=dict(net_arch=[8, 8], learned_std=True), seed=1, device="cpu")
                model.learn(total_timesteps=8)
                model.save(source/"policy.zip")
                original_hash = hashlib.sha256((source/"policy.zip").read_bytes()).hexdigest()
                original_steps = max(float(row["step"]) for row in model.policy.optimizer.state.values())
                (source/"manifest.json").write_text(json.dumps(dict(algorithm="PPO", schema=SCHEMA,
                    environment=asdict(config), environment_version=ENVIRONMENT_VERSION,
                    representation=representation_identity(), geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest(),
                    commands=commands, command_switch_seconds=.04, simulation_workers=1,
                    checkpoint_every=12)))
                (source/"progress.json").write_text('{"imitation_updates": 41000}')
                model.save(source/"saved.zip")
                (source/"checkpoints.json").write_text(json.dumps([
                    dict(id="saved", policy="saved.zip", steps=8, imitation_updates=41000)]))
                with patch("gateway.neural_gait.training.make_environment",
                           partial(GaitEnvironment, include_assembly=False)), \
                     patch("gateway.neural_gait.training.Progress.render_progress"), \
                     patch("gateway.neural_gait.training.Progress.finish_rendering", return_value=True), \
                     patch("gateway.neural_gait.training.prepare_imitation_sac", side_effect=AssertionError("SAC handoff")), \
                     patch("gateway.neural_gait.training.load_replay", side_effect=AssertionError("SAC replay")), \
                     patch("gateway.neural_gait.training.save_replay", side_effect=AssertionError("SAC replay")):
                    for name, timing in (("inherited", {}), ("varied", {"command_switch_range": [.02, .04]})):
                        output = Path(root)/name
                        workers = 2 if timing else 1
                        checkpoint = "saved.zip" if timing else "policy.zip"
                        if timing:
                            (source/"progress.json").write_text('{"state":"error","error":"interrupted"}')
                            old = json.loads((source/"manifest.json").read_text())
                            old["environment_version"] = 7
                            (source/"manifest.json").write_text(json.dumps(old))
                        rate = 3e-7 if timing else None
                        train(output, 4, config, resume=source, resume_checkpoint=checkpoint,
                              workers=workers, learning_rate=rate,
                              checkpoint_every=4 if timing else None, **timing)
                        manifest = json.loads((output/"manifest.json").read_text())
                        self.assertEqual(manifest["checkpoint_every"], 4 if timing else 12)
                        self.assertEqual(manifest["resumed_checkpoint"], checkpoint)
                        self.assertEqual(json.loads((output/"progress.json").read_text())["imitation_updates"], 41000)
                        self.assertEqual(manifest["algorithm"], "PPO")
                        self.assertEqual(manifest["reward_changes"],
                                         {"from": 7, "to": ENVIRONMENT_VERSION} if timing else {})
                        self.assertEqual(manifest["ppo"]["source_steps"], 8)
                        self.assertEqual(manifest["ppo"]["source_optimizer_epochs"], model._n_updates)
                        self.assertTrue(manifest["ppo"]["learned_std"])
                        if timing:
                            self.assertIsNone(manifest["command_switch_seconds"])
                            self.assertEqual(manifest["command_switch_range"], [.02, .04])
                            self.assertEqual(manifest["task_changes"]["command_switch_seconds"],
                                             {"source": .04, "target": None})
                        else:
                            self.assertEqual(manifest["command_switch_seconds"], .04)
                            self.assertEqual(manifest["task_changes"], {})
                        checkpoints = json.loads((output/"checkpoints.json").read_text())
                        initial = load_policy(output, checkpoints[0]["policy"])
                        for key, value in model.policy.state_dict().items():
                            torch.testing.assert_close(initial.policy.state_dict()[key], value, rtol=0, atol=0)
                        for key, state in model.policy.optimizer.state_dict()["state"].items():
                            for parameter, value in state.items():
                                torch.testing.assert_close(initial.policy.optimizer.state_dict()["state"][key][parameter],
                                                           value, rtol=0, atol=0)
                        completed = load_policy(output)
                        if rate is not None:
                            self.assertEqual(manifest["optimizer_changes"]["learning_rate"]["target"], rate)
                            self.assertEqual(completed.learning_rate, rate)
                            self.assertEqual(completed.policy.optimizer.param_groups[0]["lr"], rate)
                        else:
                            self.assertNotIn("optimizer_changes", manifest)
                            self.assertEqual(completed.learning_rate, model.learning_rate)
                        self.assertEqual(completed.num_timesteps, 8+4*workers)
                        self.assertEqual(completed.n_envs, workers)
                        self.assertGreater(completed._n_updates, model._n_updates)
                        optimization=[json.loads(line) for line in
                            (output/"optimization.jsonl").read_text().splitlines()]
                        self.assertTrue(any("train/approx_kl" in row and "train/value_loss" in row
                                            for row in optimization))
                        self.assertEqual(optimization[-1]["time/total_timesteps"],completed.num_timesteps)
                        self.assertGreater(max(float(row["step"]) for row in completed.policy.optimizer.state.values()),
                                           original_steps)
                        self.assertFalse(list(output.glob("replay.pkl*")))
                        self.assertEqual(checkpoints[-1]["optimizer_update_unit"], "epochs")
                        self.assertEqual(checkpoints[-1]["optimizer_updates"], completed._n_updates)
                        self.assertTrue(all(case["command_segments"] for case in
                                            json.loads((output/"evaluation.json").read_text())["candidate"]["episodes"]))
                        final_checkpoint = load_policy(output, checkpoints[-1]["policy"])
                        for key, value in completed.policy.state_dict().items():
                            torch.testing.assert_close(final_checkpoint.policy.state_dict()[key], value, rtol=0, atol=0)
                self.assertEqual(hashlib.sha256((source/"policy.zip").read_bytes()).hexdigest(), original_hash)
        finally:
            env.close()

    def test_training_api_forwards_ppo_resume_and_requested_timing(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.server import Runtime
        config = EnvironmentConfig(robot=robot_fixture())
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/"abc"
            source.mkdir()
            (source/"manifest.json").write_text(json.dumps(dict(algorithm="PPO", environment=asdict(config),
                environment_version=7, representation=representation_identity(),
                simulation_workers=2, command_switch_range=[12, 20])))
            (source/"policy.zip").touch()
            for extra, expected in (({}, ["--command-switch-range", "12", "20"]),
                                    ({"command_switch_seconds": 16}, ["--command-switch-seconds", "16"])):
                runtime = Runtime(root)
                with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                    runtime.start_training(dict(resume="abc", steps=4, **extra))
                arguments = launch.call_args.args[0]
                self.assertEqual(arguments[arguments.index("--workers")+1], "2")
                self.assertEqual(arguments[-len(expected):], expected)
                self.assertEqual(arguments[arguments.index("--resume")+1], str(source))

            from gateway.neural_gait.contract import DEPTH_SCHEMA
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(resume="abc", steps=4, learning_rate=3e-7))
            self.assertEqual(launch.call_args.args[0][-2:], ["--learning-rate", "3e-07"])
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(resume="abc", steps=4,
                    action_noise_std=[.01]*12, value_learning_rate=3e-4))
            arguments = launch.call_args.args[0]
            offset = arguments.index("--action-noise-std")
            self.assertEqual(arguments[offset+1:offset+13], ["0.01"]*12)
            self.assertEqual(arguments[-2:], ["--value-learning-rate", "0.0003"])
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(resume="abc", steps=4, command_units=[.03, .03, .5]))
            self.assertEqual(launch.call_args.args[0][-4:], ["--command-units", "0.03", "0.03", "0.5"])
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(resume="abc", steps=4, checkpoint_every=32768))
            self.assertEqual(launch.call_args.args[0][-2:], ["--checkpoint-every", "32768"])
            extended = asdict(config)
            extended.update(observation_schema=DEPTH_SCHEMA,
                            scenarios=[dict(id="incline", slope_deg=[0, 5])])
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                result = Runtime(root).start_training(dict(initialize_from="abc",
                    environment=extended, steps=4))
            arguments = launch.call_args.args[0]
            self.assertEqual(arguments[arguments.index("--initialize-from")+1], str(source))
            self.assertNotIn("--resume", arguments)
            saved = json.loads((Path(root)/result["run_id"]/"environment.json").read_text())
            self.assertEqual(saved["observation_schema"], DEPTH_SCHEMA)
            self.assertEqual(saved["scenarios"], extended["scenarios"])
            self.assertEqual(saved["execution_backend"], "body_control")

            # Off-policy historical rewards cannot be silently reused. The
            # existing API and CLI share this distinction from fresh PPO data.
            from gateway.neural_gait.training import resume_reward_changes
            with self.assertRaisesRegex(ValueError, "replay data"):
                resume_reward_changes(dict(algorithm="SAC", environment_version=7))
            manifest = json.loads((source/"manifest.json").read_text())
            manifest["algorithm"] = "SAC"
            from gateway.neural_gait.environment import body_control_config
            manifest["environment"] = asdict(body_control_config(config))
            (source/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "replay data"):
                Runtime(root).start_training(dict(resume="abc", steps=4))

    def test_evaluation_reports_later_progress_in_complete_and_partial_seconds(self):
        import numpy as np
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import evaluate
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=2.04)
        with patch("gateway.neural_gait.training.make_environment",
                   partial(GaitEnvironment, include_assembly=False)):
            case = evaluate(None, config, seeds=[1])["episodes"][0]
        intervals = case["progress_intervals"]
        self.assertEqual([row["start_step"] for row in intervals], [0, 50, 100])
        self.assertEqual([row["end_step"] for row in intervals], [50, 100, 102])
        self.assertAlmostEqual(sum(row["seconds"] for row in intervals), case["seconds"])
        self.assertAlmostEqual(sum(row["reward"] for row in intervals), case["reward"])
        np.testing.assert_allclose(np.sum([row["command_reference_travel_m"]
            for row in intervals], axis=0), case["command_reference_travel_m"])

    def test_varied_request_replay_preserves_shared_sensor_noise_rng(self):
        import numpy as np
        from functools import partial
        from types import SimpleNamespace
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import evaluate
        from gateway.neural_gait.replay import clip

        class SensorPolicy:
            def predict(self, observation, deterministic=True):
                return np.tanh(np.resize(observation[76:79], 12))*.3, None

        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.2, imu_gyro_noise_std=.1)
        commands = [[.015, 0, 0], [-.03, 0, 0]]
        with patch("gateway.neural_gait.training.make_environment", partial(GaitEnvironment, include_assembly=False)):
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

@unittest.skipUnless(importlib.util.find_spec("mujoco") and importlib.util.find_spec("stable_baselines3"),
                     "Use the gait training environment")
class ConnectedTrainingTests(unittest.TestCase):
    def test_spatial_camera_reaches_policy_through_actual_gateway(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.contract import DEPTH_SCHEMA, observation_size
        profile=dict(imageSize=[8,8],cameraMatrix=[[8,0,4],[0,8,4],[0,0,1]],
            cameraToBody=[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
            capture_hz=10,latency_s=.04,dropout_probability=0,noise_std_m=0,
            provenance={"basis":"test optical geometry"})
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

    def test_body_control_rollouts_are_deterministic_and_use_gateway_feedback(self):
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.contract import COMMAND_SLICE
        commands = [[.015, 0, 0], [-.03, 0, 0]]
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

    def test_ppo_execution_migration_preserves_historical_replay_and_rejects_old_sac_replay(self):
        from dataclasses import asdict, replace
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import resume_environment_changes
        old = EnvironmentConfig(robot=robot_fixture())
        manifest = dict(algorithm="PPO", environment=asdict(old))
        manifest["environment"].pop("execution_backend")
        self.assertEqual(EnvironmentConfig(**manifest["environment"]).execution_backend, "direct")
        connected = replace(old, execution_backend="body_control")
        self.assertEqual(resume_environment_changes(manifest, connected), {
            "execution_backend": {"from": "direct", "to": "body_control"}})
        with self.assertRaisesRegex(ValueError, "same environment"):
            resume_environment_changes({**manifest, "algorithm": "SAC"}, connected)
        with self.assertRaisesRegex(ValueError, "same environment"):
            resume_environment_changes(manifest, replace(connected, mass_kg=.9))

    def test_one_connected_training_worker_and_parent_evaluation_use_separate_executors(self):
        import numpy as np
        from stable_baselines3 import PPO
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import training_environment, evaluate
        config = EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            episode_seconds=.12, command=[.015,0,0])
        env = training_environment(config, workers=1)
        try:
            model = PPO("MlpPolicy", env, n_steps=8, batch_size=8, n_epochs=1,
                        policy_kwargs=dict(net_arch=[16,16]), device="cpu", seed=3)
            model.learn(8)
            self.assertEqual(model.num_timesteps, 8)
            self.assertEqual(model._n_updates, 1)
            reported = []
            result = evaluate(model, config, seeds=[1000], progress=lambda done, total: reported.append((done,total)))
            self.assertEqual(reported, [(0,1), (1,1)])
            row = result["episodes"][0]
            self.assertEqual(row["execution_backend"], "body_control")
            self.assertIsNone(row["body_terminal"])
            self.assertGreater(row["consumed_sample"], 0)
            self.assertTrue(np.isfinite(row["reward"]))
        finally:
            env.close()

@unittest.skipUnless(importlib.util.find_spec("stable_baselines3"), "Use the gait training environment")
class TrainingProgressTests(unittest.TestCase):
    def test_checkpoint_reports_evaluation_and_trial_progress_before_publication(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import Progress
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            model = SimpleNamespace(num_timesteps=120, _n_updates=7,
                                    save=lambda path: Path(path).write_bytes(b"checkpoint"))
            owner = Progress(directory, 100, EnvironmentConfig(robot=robot_fixture()))
            owner.model = model
            owner.start_step = 100
            def evaluated(*args, progress, **kwargs):
                status = json.loads((directory/"progress.json").read_text())
                self.assertEqual(status["state"], "evaluating")
                self.assertEqual(status["checkpoint_id"], "000000120")
                self.assertEqual(status["steps_this_run"], 20)
                self.assertFalse((directory/"checkpoints.json").exists())
                progress(1, 2)
                status = json.loads((directory/"progress.json").read_text())
                self.assertEqual((status["completed_episodes"], status["total_episodes"]), (1,2))
                self.assertTrue(kwargs["compact"])
                return dict(mean_reward=3, episodes=[])
            with patch("gateway.neural_gait.training.evaluate", side_effect=evaluated), \
                 patch.object(owner, "render_progress") as renderer:
                row = owner.checkpoint()
                renderer.assert_not_called()
            self.assertEqual(row["evaluation"]["mean_reward"], 3)
            owner.report("training")
            status = json.loads((directory/"progress.json").read_text())
            self.assertNotIn("completed_episodes", status)
            self.assertEqual(status["optimizer_updates"], 7)

    def test_completed_video_checkpoint_survives_later_clip_failure(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.replay import render
        episode = dict(seed=1000, command=[.015,0,0])
        checkpoints = [dict(id=str(step), steps=step, evaluation=dict(episodes=[episode])) for step in [10,20]]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory/"manifest.json").write_text(json.dumps(dict(schema=SCHEMA,
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
            (path/"manifest.json").write_text("{}")
            runtime = Runtime(root)
            with (path/"render.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(runtime.status()["runs"][0]["rendering"])
            self.assertFalse(runtime.status()["runs"][0]["rendering"])
            self.assertFalse(runtime.renders, "Reporting must not create another renderer manager")

    def test_coalesced_renderer_exit_does_not_claim_unpublished_footage(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import Progress
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path/"progress-video.json").write_text(json.dumps(dict(checkpoint_ids=["old"])))
            owner = Progress(path, 0, EnvironmentConfig(robot=robot_fixture()))
            owner.checkpoints = [dict(id="old"), dict(id="new")]
            owner.renderer = SimpleNamespace(wait=lambda:0, returncode=0)
            with patch.object(owner, "render_progress"):
                self.assertFalse(owner.finish_rendering())
                (path/"progress-video.json").write_text(json.dumps(dict(checkpoint_ids=["old","new"], footage_scope="initial_final_matched_trial")))
                self.assertTrue(owner.finish_rendering())

    def test_per_command_results_preserve_wrong_direction_in_mixed_requests(self):
        from gateway.neural_gait.training import summarize_commands
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

    def test_compact_checkpoint_covers_commands_without_full_seed_scenario_product(self):
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import evaluate
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.02,
            imu_gyro_noise_std=.01, scenarios=[{"id":"flat"}, {"id":"incline", "slope_deg":[0,2]}])
        commands = [[.015,0,0], [-.03,0,0]]
        with patch("gateway.neural_gait.training.make_environment",
                   partial(GaitEnvironment, include_assembly=False)):
            compact = evaluate(None, config, commands=commands, compact=True)
            full = evaluate(None, config, commands=commands)
        self.assertEqual(compact["evaluation_scope"], "compact_checkpoint")
        self.assertEqual([(e["command"],e["scenario_id"],e["seed"]) for e in compact["episodes"]],
                         [(command,"flat",1000) for command in commands])
        self.assertEqual(full["evaluation_scope"], "full_configured_suite")
        self.assertEqual(len(full["episodes"]), 2*2*8)

    def test_automatic_comparison_uses_only_initial_and_published_matched_trial(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.replay import render
        episodes = [dict(seed=seed, command=command, command_index=index, scenario_id=scenario)
            for index, command in enumerate([[.015,0,0],[-.03,0,0]])
            for scenario in ["flat","rocks"] for seed in [1000,1001]]
        checkpoints = [dict(id=str(step), steps=step, policy=f"checkpoints/{step}.zip",
                           evaluation=dict(episodes=episodes)) for step in [0,100,200]]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/"manifest.json").write_text(json.dumps(dict(schema=SCHEMA,
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
            self.assertEqual([item[:2] for item in seen],[("0","checkpoints/0.zip"),("200","policy.zip")])
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
