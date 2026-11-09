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

    async def begin(self, *, learning_trial=False):
        if learning_trial:
            self.session.walk = await self.session.connection.send_command(
                {"t":"intent", "name":"walk", "dir":"fwd", "steps":0, "speed":100},
                received_at=self.session.gateway.clock(), learning_trial=True)
            self.session.walk_connection = self.session.connection
            await self.session.connection.wait_acknowledged(self.session.walk, timeout=None)
            self.session.started_us = self.now
        else:
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

    def physical_inference(self, *, resist_cancel=False):
        """Use the existing pending inference fixture with a physical actor identity."""
        import asyncio
        from copy import deepcopy
        from gateway.neural_gait.contract import HISTORY_SCHEMA
        self.session.client.environment['observation_schema'] = HISTORY_SCHEMA
        self.inference_requests = []
        original = self.session.client.call
        async def call(path, payload=None):
            if path == '/status?history=0':
                return {**await original(path, payload), 'kind':'physical-redq'}
            self.inference_requests.append(deepcopy(payload))
            if not resist_cancel:
                return await original(path, payload)
            task = asyncio.create_task(original(path, payload))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # A remote inference can finish after its original caller retires.
                return await task
        self.session.client.call = call

    async def test_physical_trial_records_exact_inputs_and_device_consumed_action(self):
        import base64
        import zlib
        self.physical_inference()
        diagnostics = []
        self.session.gateway.subscribe_diagnostics(diagnostics.append)
        observed = await self.begin(learning_trial=True)
        state = self.session.connection.neural_walk
        request = self.inference_requests[-1]
        self.assertTrue(state.learning_trial)
        self.assertTrue(request['explore'])
        self.assertEqual(request['model_id'], state.model_id)
        self.assertEqual(request['checkpoint_id'], state.checkpoint_id)
        feedback_revision = self.session.gateway.body_sensor_observation(self.session.robot_id)['feedback']['revision']
        first_action = [.2, 0., 0.]*4
        admitted = await self.session.action(first_action)
        self.assertEqual(admitted['consumed_sample'], 0, 'Native ACK must not become a learned execution transition')
        row = next(row for row in diagnostics if row.get('event') == 'neural_gait' and 'action' in row)
        self.assertTrue(row['learning_trial'])
        self.assertEqual((row['walk'], row['revision'], row['feedback_revision']),
                         (self.session.walk, 0, feedback_revision))
        self.assertEqual(row['consumed_sample'], 0)
        self.assertIsInstance(row['observation_received_at'], (int, float))
        source = self.session.gateway.body_sensor_observation(self.session.robot_id)
        self.assertIsInstance(source['received_at'], str, 'Display receipt time remains ISO formatted')
        self.assertEqual(row['observation_received_at'], source['received_monotonic_s'])
        packed = row['policy_observation']
        self.assertEqual(packed['encoding'], 'float32-le-zlib-base64')
        self.assertEqual(packed['schema'], observed['schema'])
        self.np.testing.assert_array_equal(
            self.np.frombuffer(zlib.decompress(base64.b64decode(packed['values'])), dtype='<f4'),
            self.np.asarray(vector(observed), dtype=self.np.float32))

        for _ in range(100):
            await self.advance()
            observed = await self.session.observation()
            if observed['previous_action'] == first_action:
                break
            await self.session.action(first_action)
        self.assertEqual(observed['previous_action'], first_action)
        consumed = self.session.connection.neural_walk.consumed
        self.assertGreater(consumed, 0)
        await self.session.action([-.2, 0., 0.]*4)
        row = [row for row in diagnostics if row.get('event') == 'neural_gait' and 'action' in row][-1]
        self.assertEqual(row['consumed_sample'], consumed)
        self.assertGreater(row['sample'], consumed)
        self.np.testing.assert_array_equal(
            self.np.frombuffer(zlib.decompress(base64.b64decode(row['policy_observation']['values'])), dtype='<f4'),
            self.np.asarray(vector(observed), dtype=self.np.float32))

    async def test_physical_final_sensor_snapshot_survives_no_next_policy_target(self):
        from unittest.mock import patch
        from gateway.neural_gait.physical import measured_transition
        self.physical_inference()
        diagnostics = []
        self.session.gateway.subscribe_diagnostics(diagnostics.append)
        await self.begin(learning_trial=True)
        for _ in range(100):
            await self.session.action([.2, 0., 0.]*4)
            first = [r for r in diagnostics if r.get('event') == 'neural_gait' and 'action' in r][-1]
            await self.advance()
            if self.session.connection.neural_walk.consumed == first['sample']:
                break
            await self.session.observation()
        self.assertEqual(self.session.connection.neural_walk.consumed, first['sample'])
        # The existing body-event boundary reports a known failure on a real
        # native sensor packet; this is protocol coverage, not a physical fall.
        event = self.session.gateway.body_events.event(self.session.robot_id,
            self.session.connection.epoch, 'tipped', {'motion':{'sequence':self.session.walk}})
        with patch.object(self.session.gateway.body_events, 'observe', return_value=[event]):
            await self.advance()
        final = next(r for r in diagnostics if r.get('outcome') == 'failure')
        self.assertNotIn('action', final)
        self.assertNotIn('sample', final)
        self.assertEqual(final['consumed_sample'], first['sample'])
        self.assertEqual(final['observation_received_at'], self.now/1e6)
        self.assertEqual(final['observation_device_us'], self.now)
        self.assertEqual(final['outcome_evidence']['event_id'], event['event_id'])
        transition, evidence = measured_transition(first, final, [])
        self.assertEqual(transition[4], 0.)
        self.assertFalse(evidence['visual_complete'])
        self.assertIsNone(evidence['displacement_body_m'])
        self.assertEqual(len([r for r in diagnostics if 'action' in r]), first['sample'],
                         'Final observation recording must not generate another target')
        self.assertIsNotNone(self.session.connection.neural_walk,
                             'Recording a failure must not introduce a movement stop')
        await self.session.stop(release=True)
        self.assertEqual(diagnostics[-1]['outcome'], 'truncated')

    async def test_physical_exploration_belongs_only_to_explicit_walk(self):
        self.physical_inference()
        await self.begin(learning_trial=True)
        original = self.session.walk
        self.assertTrue(self.inference_requests[-1]['explore'])
        await self.session.update_walk({'dir':'fwd', 'steps':0, 'speed':70})
        await self.session.observation()
        self.assertEqual(self.session.connection.neural_walk.sequence, original)
        self.assertTrue(self.inference_requests[-1]['explore'], 'Steering retains the original trial owner')
        stop = await self.session.stop(release=True)
        await self.session.connection.wait_acknowledged(stop, timeout=None)
        await self.advance()
        await self.begin()
        self.assertFalse(self.session.connection.neural_walk.learning_trial)
        self.assertFalse(self.inference_requests[-1]['explore'], 'An ordinary deployed Walk is deterministic')
        self.assertNotEqual(self.session.walk, original)

    async def test_physical_trial_late_inference_and_queued_targets_cannot_outlive_owner(self):
        import asyncio
        from unittest.mock import patch
        self.physical_inference(resist_cancel=True)
        commands = []
        async def record(command):
            commands.append(command)
        self.session.gateway.subscribe_commands(record)
        for transition in ('stop', 'release', 'replacement'):
            for phase in ('inference', 'queued_target'):
                with self.subTest(transition=transition, phase=phase):
                    await self.begin(learning_trial=True)
                    original = self.session.walk
                    producer = self.session.connection.neural_walk.task
                    async def retire():
                        if transition == 'replacement':
                            return await self.session.command('walk', {'dir':'fwd', 'steps':0, 'speed':100})
                        return await self.session.stop(release=transition == 'release')
                    if phase == 'queued_target':
                        target_waiting = asyncio.Event()
                        send = self.session.connection.send_command
                        async def observed_send(command, **kwargs):
                            if command.get('t') == 'walk_target' and command.get('walk') == original:
                                target_waiting.set()
                            return await send(command, **kwargs)
                        with patch.object(self.session.connection, 'send_command', side_effect=observed_send):
                            await self.session.connection._send_lock.acquire()
                            try:
                                retiring = asyncio.create_task(retire())
                                await asyncio.sleep(0)
                                self.session.client.respond([.2, 0., 0.]*4)
                                await asyncio.wait_for(target_waiting.wait(), 2)
                                self.assertFalse(retiring.done())
                            finally:
                                self.session.connection._send_lock.release()
                            replacement = await retiring
                    else:
                        replacement = await retire()
                        self.session.client.respond([.2, 0., 0.]*4)
                    await self.session.connection.wait_acknowledged(replacement, timeout=None)
                    await self.advance()
                    await asyncio.wait_for(asyncio.gather(producer, return_exceptions=True), 2)
                    if transition == 'replacement':
                        self.assertEqual(self.session.connection.neural_walk.sequence, replacement)
                        self.assertFalse(self.session.connection.neural_walk.learning_trial)
                    else:
                        self.assertIsNone(self.session.connection.neural_walk)
                    self.assertFalse(any(row['t'] == 'walk_target' and row['walk'] == original
                                         for row in commands))
                    self.assertEqual(self.session.connection.completed[original]['t'], 'cancelled')

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
    importlib.util.find_spec("mujoco")
    and importlib.util.find_spec("stable_baselines3"),
    "Use build/gait-training-env for physics and checkpoint tests",
)
class PhysicsTests(unittest.TestCase):

    def test_geometry_action_domain_preserves_old_scales_and_expands_new_physical_runs(self):
        from dataclasses import asdict
        import numpy as np
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.native import BodyModel
        from gateway.neural_gait.physical import physical_environment
        config = EnvironmentConfig(robot=robot_fixture())
        model = BodyModel(config.robot)
        self.addCleanup(model.close)
        expected = model.foot_action_scale(config.reference_joint_deg, config.target_limits_deg)
        np.testing.assert_array_equal(config.foot_action_scale_mm, expected)
        self.assertGreater(expected[0], 53.808)
        self.assertTrue(np.isfinite(expected).all())
        old = EnvironmentConfig(robot=robot_fixture(), foot_action_scale_mm=[30.,20.,30.])
        restored = EnvironmentConfig(**asdict(old))
        self.assertEqual(restored.foot_action_scale_mm, [30.,20.,30.])
        # Creating a NEW physical learner must not inherit the old search box.
        physical = physical_environment(asdict(restored))
        np.testing.assert_array_equal(physical['foot_action_scale_mm'], expected)
        self.assertEqual(restored.foot_action_scale_mm, [30.,20.,30.])

    def test_sac_actor_transfers_to_history_ppo_and_value_warmup_preserves_it(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict, replace
        from stable_baselines3.common.logger import configure
        from gateway.neural_gait.contract import HISTORY_SCHEMA, HISTORY_START
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, GEOMETRY, representation_identity
        from gateway.neural_gait.training import (new_model, initialize_model, load_policy,
            LOCOMOTION_RECIPE, configure_action_exploration, apply_rollout_geometry, warm_start_value,
            training_recipe)
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12)
        old = GaitEnvironment(config, include_assembly=False)
        new = GaitEnvironment(replace(config, observation_schema=HISTORY_SCHEMA), include_assembly=False)
        self.addCleanup(old.close)
        self.addCleanup(new.close)
        source = new_model(old, "cpu", 1, policy_kwargs=dict(net_arch=[8, 8]))
        observed, _ = old.reset(seed=1)
        expanded, _ = new.reset(seed=1)
        expanded[136:283] = 1.
        expanded[89:96] = [1., 2., 3., 1., .5, 1., .1]
        expanded[HISTORY_START:] = 1.
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            source.save(path/"policy.zip")
            manifest = dict(algorithm="SAC", schema=SCHEMA, environment=asdict(config),
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
                geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())
            (path/"manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(training_recipe(manifest, LOCOMOTION_RECIPE, initialize_from=path), LOCOMOTION_RECIPE)
            model, provenance = initialize_model(path, new, new.config, recipe=LOCOMOTION_RECIPE)
            self.assertEqual(provenance["target_algorithm"], "PPO")
            self.assertFalse(provenance["critic_parameters_loaded"])
            np.testing.assert_allclose(source.predict(observed, deterministic=True)[0],
                model.predict(expanded, deterministic=True)[0], atol=1e-7, rtol=0)
            configure_action_exploration(model, [.03]*12)
            apply_rollout_geometry(model, 8, 8)
            model.set_logger(configure(str(path), []))
            before = {name: value.detach().clone() for name, value in model.policy.state_dict().items()}
            report = []
            result = warm_start_value(model, 16, report=report.append)
            self.assertEqual(result["steps"], 16)
            self.assertEqual(result["actor_updates"], 0)
            self.assertEqual(model.num_timesteps, 0)
            self.assertEqual(len(report), 2)
            changed = set()
            for name, value in model.policy.state_dict().items():
                if not torch.equal(before[name], value):
                    changed.add(name)
                    self.assertTrue(name.startswith(("value_net.", "mlp_extractor.value_net.")), name)
            self.assertTrue(changed)
            np.testing.assert_allclose(source.predict(observed, deterministic=True)[0],
                model.predict(expanded, deterministic=True)[0], atol=1e-7, rtol=0)
            # Newly introduced history and camera weights can learn, whereas
            # the simulator-only critic columns remain excluded from the actor.
            model.policy.optimizer.zero_grad(set_to_none=True)
            tensor = torch.tensor(expanded[None])
            model.policy.get_distribution(tensor).mode().sum().backward()
            gradient = model.policy.mlp_extractor.policy_net[0].weight.grad
            self.assertGreater(float(gradient[:, 136:283].abs().sum()), 0)
            self.assertGreater(float(gradient[:, HISTORY_START:-5].abs().sum()), 0)
            self.assertEqual(float(gradient[:, -5:].abs().sum()), 0)
            model.save(path/"policy.zip")
            manifest.update(algorithm="PPO", schema=HISTORY_SCHEMA, environment=asdict(new.config))
            (path/"manifest.json").write_text(json.dumps(manifest))
            restored = load_policy(path)
            np.testing.assert_array_equal(model.predict(expanded, deterministic=True)[0],
                restored.predict(expanded, deterministic=True)[0])

    def test_history_extension_preserves_actor_and_excludes_training_state(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict, replace
        from gateway.neural_gait.contract import DEPTH_SCHEMA, HISTORY_SCHEMA, HISTORY_SIZE, HISTORY_START
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment, GEOMETRY, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.training import (GaitPPO, GaitPPOPolicy, initialize_model,
            load_policy, configure_command_units, new_model, CycleExpert)
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12, observation_schema=DEPTH_SCHEMA)
        original = GaitEnvironment(config, include_assembly=False)
        extended = GaitEnvironment(replace(config, observation_schema=HISTORY_SCHEMA), include_assembly=False)
        self.addCleanup(original.close)
        self.addCleanup(extended.close)
        with self.assertRaisesRegex(ValueError, "asymmetric GaitPPO"):
            new_model(extended, "cpu", 1)
        model = GaitPPO(GaitPPOPolicy, original, n_steps=4, batch_size=4, n_epochs=1,
            policy_kwargs=dict(net_arch=[8,8], learned_std=True, action_coordinates="action",
                               value_learning_rate=3e-4, normalize_observations=True), seed=1)
        model.learn(total_timesteps=4)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            model.save(path/"chosen.zip")
            manifest = dict(algorithm="PPO", schema=DEPTH_SCHEMA, environment=asdict(config),
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
                geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())
            (path/"manifest.json").write_text(json.dumps(manifest))
            transferred, provenance = initialize_model(path, extended, extended.config, checkpoint="chosen.zip")
            self.assertEqual(provenance["source_checkpoint"], "chosen.zip")
            old, _ = original.reset(seed=4)
            new, _ = extended.reset(seed=4)
            self.assertEqual(len(new), HISTORY_SIZE)
            cycle = np.eye(12, dtype=np.float32)[:3]*.1
            cycled = new.copy(); cycled[283:295] = cycle[1]
            np.testing.assert_array_equal(CycleExpert(cycle)(cycled), cycle[2])
            np.testing.assert_allclose(model.predict(old, deterministic=True)[0],
                transferred.predict(new, deterministic=True)[0], atol=1e-7, rtol=0)
            # Give critic columns actual weights: the actor must still never
            # use privileged inputs, even after learning/save/reload.
            with torch.no_grad():
                transferred.policy.mlp_extractor.policy_net[0].weight[:, -5:] = 1.
                transferred.policy.mlp_extractor.value_net[0].weight[:, -5:] = 1.
            changed = new.copy(); changed[-5:] = [2,3,4,1,0]
            tensor = torch.tensor(np.stack([new, changed]))
            actions, values, _ = transferred.policy(tensor, deterministic=True)
            torch.testing.assert_close(actions[0], actions[1], rtol=0, atol=0)
            self.assertNotEqual(float(values[0].detach()), float(values[1].detach()))
            torch.testing.assert_close(transferred.policy.get_distribution(tensor).mode(), actions)
            torch.testing.assert_close(transferred.policy.predict_values(tensor), values)
            # Preconditioning all historical command columns also preserves outputs.
            tensor[:, HISTORY_START+58:HISTORY_START+61] = torch.tensor([.015,.01,.5])
            before = transferred.policy(tensor, deterministic=True)
            configure_command_units(transferred, [.03,.03,.5])
            after = transferred.policy(tensor, deterministic=True)
            torch.testing.assert_close(before[0], after[0]); torch.testing.assert_close(before[1], after[1])
            extended.reward_twists.extend([[.03,0,0]])
            with_pace = vector(extended.observation())
            self.assertEqual(with_pace[-5], 1.)
            # Full policy train/save/load retains the actor/critic separation.
            transferred.learn(total_timesteps=4)
            transferred.save(path/"policy.zip")
            manifest.update(schema=HISTORY_SCHEMA, environment=asdict(extended.config))
            (path/"manifest.json").write_text(json.dumps(manifest))
            restored = load_policy(path)
            np.testing.assert_array_equal(restored.predict(new, deterministic=True)[0],
                                          restored.predict(changed, deterministic=True)[0])
            manifest["algorithm"] = "SAC"
            (path/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "asymmetric GaitPPO"):
                load_policy(path)

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

    def test_ppo_imitation_fits_deterministic_actor_without_value_or_exploration_updates(self):
        import copy
        import gymnasium as gym
        import numpy as np
        import torch
        from gateway.neural_gait.contract import HISTORY_SIZE
        from gateway.neural_gait.training import GaitPPO, GaitPPOPolicy, fit_actor

        class Spaces(gym.Env):
            observation_space = gym.spaces.Box(-np.inf, np.inf, (HISTORY_SIZE,), dtype=np.float32)
            action_space = gym.spaces.Box(-1, 1, (12,), dtype=np.float32)

        torch.set_num_threads(1)
        x = np.random.default_rng(7).normal(0, .1, (32,HISTORY_SIZE)).astype(np.float32)
        y = np.full((len(x),12), .2, dtype=np.float32)
        for coordinates in ("latent", "action", "linear"):
            with self.subTest(coordinates=coordinates), tempfile.TemporaryDirectory() as root:
                model = GaitPPO(GaitPPOPolicy, Spaces(), n_steps=16, batch_size=16, seed=3,
                    learning_rate=.002, device="cpu", policy_kwargs=dict(net_arch=[8,8],
                        learned_std=True, log_std_init=-1., action_coordinates=coordinates,
                        normalize_observations=True, value_learning_rate=.003,
                        exploration_learning_rate=.004, command_units=[.08,.04,.5]))
                policy = model.policy
                policy.update_observation_statistics(x)
                tx = torch.as_tensor(x)
                if coordinates == "linear":
                    with torch.no_grad():
                        policy.action_net.weight.zero_()
                        policy.action_net.bias.fill_(2.)
                # Seed every Adam group, and leave stale gradients present.
                # Rehearsal must preserve these states instead of replacing the
                # optimizer or letting unused parameters drift on zero grads.
                loss = (policy.get_distribution(tx).get_actions(deterministic=True).square().mean()
                        +policy.predict_values(tx).square().mean()+policy.log_std.square().mean())
                loss.backward()
                policy.optimizer.step()
                optimizer = policy.optimizer
                groups = [(group["gait_role"], group["lr"]) for group in optimizer.param_groups]
                actor_state = optimizer.state[policy.action_net.weight]
                actor_steps = float(actor_state["step"])
                frozen = {name: parameter for name,parameter in policy.named_parameters()
                    if name == "log_std" or name.startswith(("mlp_extractor.value_net.","value_net.","vf_features_extractor."))}
                values = {name:parameter.detach().clone() for name,parameter in frozen.items()}
                states = {name:copy.deepcopy(optimizer.state[parameter]) for name,parameter in frozen.items()}
                buffers = {name:value.clone() for name,value in policy.named_buffers()}
                critic = policy.predict_values(tx).detach().clone()
                result = fit_actor(model, x, y, 60, 7)
                self.assertLess(result["action_rmse_after"], result["action_rmse_before"])
                self.assertEqual(result["loss_coordinates"], "linear_mean_before_inference_clipping"
                    if coordinates == "linear" else "bounded_actions")
                if coordinates == "linear":
                    self.assertGreater(result["action_rmse_before"], 1., "Raw saturated means must keep a corrective gradient")
                self.assertIs(policy.optimizer, optimizer)
                self.assertIs(optimizer.state[policy.action_net.weight], actor_state)
                self.assertEqual(float(actor_state["step"]), actor_steps+60)
                self.assertEqual([(group["gait_role"],group["lr"]) for group in optimizer.param_groups], groups)
                for name,parameter in frozen.items():
                    torch.testing.assert_close(parameter, values[name], rtol=0, atol=0)
                    self.assertIsNone(parameter.grad)
                    for key,value in states[name].items():
                        torch.testing.assert_close(optimizer.state[parameter][key], value, rtol=0, atol=0)
                for name,value in policy.named_buffers():
                    torch.testing.assert_close(value, buffers[name], rtol=0, atol=0)
                torch.testing.assert_close(policy.predict_values(tx), critic, rtol=0, atol=0)
                self.assertTrue(policy.log_std.requires_grad)
                expected = model.predict(x, deterministic=True)[0]
                path = Path(root)/"policy.zip"
                model.save(path)
                restored = GaitPPO.load(path, device="cpu")
                np.testing.assert_array_equal(restored.predict(x, deterministic=True)[0], expected)

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
                self.assertEqual(json.loads((run/"manifest.json").read_text())["algorithm"],
                                 "DAgger behavior cloning of SAC actor")
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
                # Moving to the real gateway/native executor transfers the actor,
                # never replay collected under the direct mathematical executor.
                from gateway.neural_gait.environment import body_control_config, make_environment
                connected_config = body_control_config(config)
                connected = make_environment(connected_config, include_assembly=False)
                try:
                    with patch.object(SAC, "load_replay_buffer", side_effect=AssertionError("old replay read")):
                        migrated, transfer = initialize_model(path, connected, connected_config)
                    np.testing.assert_array_equal(source.predict(obs, deterministic=True)[0],
                                                  migrated.predict(obs, deterministic=True)[0])
                    self.assertEqual(migrated.replay_buffer.size(), 0)
                    self.assertFalse(migrated.actor.optimizer.state)
                    self.assertEqual(transfer["execution_changes"]["execution_backend"],
                                     {"source": "direct", "target": "body_control"})
                    from dataclasses import replace
                    with self.assertRaisesRegex(ValueError, "compatible sensor/action"):
                        initialize_model(path, connected, replace(connected_config, mass_kg=.8))
                finally:
                    connected.close()
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

    def test_sac_depth_expansion_preserves_movement_and_learns_new_camera_columns(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict, replace
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, GEOMETRY, representation_identity
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.training import new_model, initialize_model, load_policy
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.08)
        old = GaitEnvironment(config, include_assembly=False)
        new = GaitEnvironment(replace(config, observation_schema=DEPTH_SCHEMA), include_assembly=False)
        self.addCleanup(old.close)
        self.addCleanup(new.close)
        source = new_model(old, "cpu", 1, policy_kwargs=dict(net_arch=[8, 8]))
        observed, _ = old.reset(seed=1)
        expanded = np.r_[observed[:-12], np.ones(new.observation_space.shape[0]-len(observed)), observed[-12:]].astype(np.float32)
        expanded[89:96] = [1., 2., 3., 1., .5, 1., .1]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            source.save(path/"policy.zip")
            manifest = dict(algorithm="SAC", schema=SCHEMA, environment=asdict(config),
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
                geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())
            (path/"manifest.json").write_text(json.dumps(manifest))
            model, provenance = initialize_model(path, new, new.config)
            np.testing.assert_allclose(source.predict(observed, deterministic=True)[0],
                                      model.predict(expanded, deterministic=True)[0], atol=1e-7)
            self.assertFalse(provenance["replay_loaded"])
            model.actor(torch.tensor(expanded[None])).sum().backward()
            self.assertGreater(float(model.actor.latent_pi[0].weight.grad[:,136:-12].abs().sum()), 0.)
            output = model.predict(expanded, deterministic=True)[0]
            model.save(path/"policy.zip")
            manifest.update(schema=DEPTH_SCHEMA, environment=asdict(new.config))
            (path/"manifest.json").write_text(json.dumps(manifest))
            np.testing.assert_array_equal(output, load_policy(path).predict(expanded, deterministic=True)[0])

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
        from gateway.neural_gait.training import locomotion_config
        config = locomotion_config(EnvironmentConfig(robot=robot_fixture()))
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
                # An immutable checkpoint remains selected across both a run's
                # later publication and a service restart.
                checkpoint_id = "000000016"
                (path / "checkpoints").mkdir()
                policy.save(path / "checkpoints" / f"{checkpoint_id}.zip")
                (path / "checkpoints.json").write_text(json.dumps([
                    dict(id=checkpoint_id, policy=f"checkpoints/{checkpoint_id}.zip", steps=16)]))
                import torch
                original_bias = policy.actor.mu.bias.detach().clone()
                with torch.no_grad():
                    policy.actor.mu.bias.add_(0.5)
                policy.save(path / "policy.zip")
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
                # Restore the original policy for the historical replay checks.
                with torch.no_grad():
                    policy.actor.mu.bias.copy_(original_bias)
                policy.save(path / "policy.zip")
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
        model = GaitPPO(GaitPPOPolicy, env, device="cpu", n_steps=4, batch_size=4, n_epochs=1,
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
        # Configure in the reverse of constructor order to exercise canonical
        # optimizer group ordering and saved moment-to-parameter identity.
        policy.configure_exploration_learning(3e-4)
        model.policy_kwargs["exploration_learning_rate"] = 3e-4
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
            self.assertEqual(restored.policy.exploration_learning_rate, 3e-4)
            restored.learn(total_timesteps=4, reset_num_timesteps=False)
            rates = {group["gait_role"]: group["lr"] for group in restored.policy.optimizer.param_groups}
            self.assertEqual(rates, dict(actor=3e-7, value=3e-4, exploration=3e-4))
            self.assertIn(restored.policy.log_std, restored.policy.optimizer.state)
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
        model = GaitPPO(GaitPPOPolicy, env, device="cpu", n_steps=4, batch_size=4, n_epochs=1,
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

    def test_ppo_aggregation_preserves_actor_identity_and_collects_every_command_scenario(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict, replace
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.contract import HISTORY_SCHEMA, COMMAND_SLICE
        from gateway.neural_gait.environment import (EnvironmentConfig, GaitEnvironment,
            ENVIRONMENT_VERSION, GEOMETRY, representation_identity)
        from gateway.neural_gait.training import (GaitPPO, GaitPPOPolicy, LOCOMOTION_RECIPE,
            fit_actor, load_policy, locomotion_config, train)
        commands = [[.03,0,0], [-.03,0,0]]
        entry = [0,3.46,-21.63]*4
        entry[0] = 5.
        config = locomotion_config(EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04,
            observation_schema=HISTORY_SCHEMA, command=commands[0],
            scenarios=[dict(id="standing"), dict(id="entry", start_joint_deg=entry)]))
        env = GaitEnvironment(config, include_assembly=False, include_visuals=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=4, batch_size=4, n_epochs=1,
            seed=7, device="cpu", policy_kwargs=dict(net_arch=[8,8],
                action_coordinates="action", learned_std=True, log_std_init=-1.))
        observation, _ = env.reset(seed=7, options={"scenario":"standing"})
        x = np.repeat(observation[None], 3, axis=0)
        actions = np.full((3,12), .01, dtype=np.float32)
        fit_actor(model, x, actions, 1, 7)
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/"source"
            source.mkdir()
            model.save(source/"policy.zip")
            original = (source/"policy.zip").read_bytes()
            metadata = dict(algorithm="PPO", recipe=LOCOMOTION_RECIPE, schema=HISTORY_SCHEMA,
                environment=asdict(config), environment_version=ENVIRONMENT_VERSION,
                representation=representation_identity(), geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())
            (source/"manifest.json").write_text(json.dumps(metadata))
            (source/"progress.json").write_text('{"imitation_updates":1}')
            demonstrations = []
            for index,command in enumerate(commands):
                path = Path(root)/f"teacher-{index}.npz"
                observations = x.copy()
                observations[:,COMMAND_SLICE] = command
                np.savez(path, observation=observations, action=actions)
                path.with_suffix(".json").write_text(json.dumps(dict(metadata,
                    environment=asdict(replace(config,command=command)), recommended_cycle_rows=[0,3])))
                demonstrations.append(path)
            optimizers, initial_steps = [], []
            def fit(resumed, *args, **kwargs):
                self.assertIsInstance(resumed, GaitPPO)
                optimizer = resumed.policy.optimizer
                optimizers.append(optimizer)
                initial_steps.append(float(optimizer.state[resumed.policy.action_net.weight]["step"]))
                return fit_actor(resumed, *args, **kwargs)
            destination = Path(root)/"aggregation"
            with patch("gateway.neural_gait.training.make_environment", partial(GaitEnvironment, include_assembly=False)), \
                 patch("gateway.neural_gait.training.fit_actor", side_effect=fit), \
                 patch("gateway.neural_gait.training.Progress.render_progress"), \
                 patch("gateway.neural_gait.training.Progress.finish_rendering", return_value=True), \
                 patch("gateway.neural_gait.training.SAC.load", side_effect=AssertionError("PPO relabelled SAC")), \
                 patch("gateway.neural_gait.training.load_replay", side_effect=AssertionError("SAC replay")), \
                 patch("gateway.neural_gait.training.save_replay", side_effect=AssertionError("SAC replay")):
                train(destination, 0, config, resume=source, demonstrations=demonstrations,
                    demonstration_cycles=True, imitation_updates=2, expert_mix=(0.,), updates_per_round=2)
            self.assertEqual(initial_steps, [1.,3.])
            self.assertIs(optimizers[0], optimizers[1])
            self.assertEqual((source/"policy.zip").read_bytes(), original)
            manifest = json.loads((destination/"manifest.json").read_text())
            self.assertEqual(manifest["algorithm"], "PPO")
            self.assertEqual(manifest["recipe"], LOCOMOTION_RECIPE)
            aggregation = json.loads((destination/"aggregation.json").read_text())
            for index,round_ in enumerate(aggregation["rounds"]):
                self.assertEqual([(row["command"],row["scenario_id"]) for row in round_["collection"]],
                    [(command,scenario) for command in commands for scenario in ("standing","entry")])
                self.assertEqual([row["expert_actions"] for row in round_["collection"]], [2 if index == 0 else 0]*4)
            self.assertEqual(aggregation["training_states"], 16)
            with np.load(destination/"training-data.npz") as data:
                self.assertEqual(len(data["observation"]), 16)
                self.assertFalse(np.array_equal(data["observation"][0], data["observation"][2]),
                                 "Scenario labels must correspond to different actual reset observations")
            selected = json.loads((destination/"selection.json").read_text())
            restored = load_policy(destination, device="cpu")
            self.assertIsInstance(restored, GaitPPO)
            self.assertEqual(restored.num_timesteps, 0)
            self.assertEqual(float(restored.policy.optimizer.state[restored.policy.action_net.weight]["step"]),
                             selected["imitation_updates"])
            for name,value in model.policy.state_dict().items():
                if name == "log_std" or name.startswith(("mlp_extractor.value_net.","value_net.")):
                    torch.testing.assert_close(restored.policy.state_dict()[name], value, rtol=0, atol=0)

    def test_ppo_plain_rehearsal_resumes_with_existing_optimizer_and_requested_rate(self):
        import hashlib
        import numpy as np
        import torch
        from dataclasses import asdict
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.contract import HISTORY_SCHEMA
        from gateway.neural_gait.environment import (EnvironmentConfig, GaitEnvironment,
            ENVIRONMENT_VERSION, GEOMETRY, representation_identity)
        from gateway.neural_gait.training import (GaitPPO, GaitPPOPolicy, LOCOMOTION_RECIPE,
            fit_actor, imitate, load_policy, locomotion_config, train)
        config = locomotion_config(EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04,
                                                     observation_schema=HISTORY_SCHEMA))
        env = GaitEnvironment(config, include_assembly=False, include_visuals=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=4, batch_size=4, n_epochs=1,
            learning_rate=.0003, seed=7, device="cpu", policy_kwargs=dict(net_arch=[8,8],
                action_coordinates="action", learned_std=True, value_learning_rate=.0001,
                exploration_learning_rate=.0002))
        observation, _ = env.reset(seed=1)
        x = np.repeat(observation[None], 16, axis=0)
        y = np.full((len(x),12), .2, dtype=np.float32)
        fit_actor(model, x, y, 1, 7)
        before = model.predict(x, deterministic=True)[0]
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/"source"
            source.mkdir()
            model.save(source/"policy.zip")
            original = (source/"policy.zip").read_bytes()
            metadata = dict(algorithm="PPO", recipe=LOCOMOTION_RECIPE, schema=HISTORY_SCHEMA,
                environment=asdict(config), environment_version=ENVIRONMENT_VERSION,
                representation=representation_identity(), geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest())
            (source/"manifest.json").write_text(json.dumps(metadata))
            (source/"progress.json").write_text('{"imitation_updates":1}')
            data = Path(root)/"demonstration.npz"
            np.savez(data, observation=x, action=y)
            data.with_suffix(".json").write_text(json.dumps(metadata))
            def rehearsal(resumed, *args, **kwargs):
                self.assertIsInstance(resumed, GaitPPO)
                optimizer = resumed.policy.optimizer
                self.assertEqual({group["gait_role"]:group["lr"] for group in optimizer.param_groups},
                                 {"actor":.001, "value":.0001, "exploration":.0002})
                state = optimizer.state[resumed.policy.action_net.weight]
                self.assertEqual(float(state["step"]), 1.)
                for key,value in model.policy.optimizer.state[model.policy.action_net.weight].items():
                    torch.testing.assert_close(state[key], value, rtol=0, atol=0)
                result = imitate(resumed, *args, **kwargs)
                self.assertIs(resumed.policy.optimizer, optimizer)
                self.assertIs(optimizer.state[resumed.policy.action_net.weight], state)
                self.assertEqual(float(state["step"]), 5.)
                return result
            destination = Path(root)/"rehearsal"
            with patch("gateway.neural_gait.training.make_environment",
                       partial(GaitEnvironment, include_assembly=False)), \
                 patch("gateway.neural_gait.training.imitate", side_effect=rehearsal) as fitted, \
                 patch("gateway.neural_gait.training.Progress.render_progress"), \
                 patch("gateway.neural_gait.training.Progress.finish_rendering", return_value=True), \
                 patch("gateway.neural_gait.training.prepare_imitation_sac", side_effect=AssertionError("SAC handoff")), \
                 patch("gateway.neural_gait.training.load_replay", side_effect=AssertionError("SAC replay")), \
                 patch("gateway.neural_gait.training.save_replay", side_effect=AssertionError("SAC replay")):
                train(destination, 0, config, resume=source, demonstrations=[data],
                      imitation_updates=4, recipe=LOCOMOTION_RECIPE, learning_rate=.001)
                fitted.assert_called_once()
            self.assertEqual((source/"policy.zip").read_bytes(), original)
            result = json.loads((destination/"imitation.json").read_text())
            self.assertLess(result["action_rmse_after"], result["action_rmse_before"])
            self.assertEqual(result["sources"][0]["transitions"], len(x))
            self.assertEqual(json.loads((destination/"manifest.json").read_text())["algorithm"], "PPO")
            self.assertEqual(json.loads((destination/"progress.json").read_text())["imitation_updates"], 5)
            evaluation = json.loads((destination/"evaluation.json").read_text())
            self.assertEqual(evaluation["baseline"]["evaluation_purpose"], "standing_baseline")
            self.assertEqual(evaluation["baseline"]["policy_kind"], "held_standing_reference")
            restored = load_policy(destination, device="cpu")
            self.assertEqual(restored.num_timesteps, 0)
            self.assertEqual(restored._n_updates, 0)
            self.assertFalse(np.array_equal(before, restored.predict(x, deterministic=True)[0]))

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
        model = PPO(GaitPPOPolicy,original,device="cpu",n_steps=4,batch_size=4,n_epochs=1,
                    policy_kwargs=dict(net_arch=[8,8],learned_std=True,normalize_observations=True),seed=1)
        model.learn(total_timesteps=8)
        observed,_=original.reset(seed=4)
        model.policy.update_observation_statistics(np.stack([observed,observed+.1]))
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
        from dataclasses import asdict, replace
        from functools import partial
        from unittest.mock import patch
        from stable_baselines3 import PPO
        from gateway.neural_gait.environment import (
            EnvironmentConfig, GaitEnvironment, ENVIRONMENT_VERSION, GEOMETRY, representation_identity)
        from gateway.neural_gait.training import (
            GaitPPOPolicy, PreciseActionRolloutBuffer, load_policy, train, evaluate)
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
                # Final weights survive an interrupted qualification even when
                # progress has lost both the imitation count and selected id.
                (source/"progress.json").write_text('{"state":"error","error":"interrupted"}')
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
                        run_config = replace(config, episode_seconds=.12) if timing else config
                        seeds = [7, 13] if timing else None
                        with patch("gateway.neural_gait.training.evaluate", wraps=evaluate) as evaluated:
                            train(output, 4, run_config, resume=source, resume_checkpoint=checkpoint,
                                  workers=workers, learning_rate=rate,
                                  checkpoint_every=4 if timing else None, evaluation_seeds=seeds, **timing)
                        manifest = json.loads((output/"manifest.json").read_text())
                        self.assertEqual(manifest["evaluation_seeds"], seeds)
                        if timing:
                            self.assertEqual(manifest["execution_changes"]["episode_seconds"],
                                             {"from":.08, "to":.12})
                            status = json.loads((output/"progress.json").read_text())
                            self.assertEqual(status["evaluation_seeds"], seeds)
                            self.assertEqual(status["evaluation"]["evaluation_seeds"], seeds)
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
                        # Final qualification compares the unchanged starting
                        # actor with the candidate in the current suite, even
                        # when this resume changes horizon/request timing/seeds.
                        baseline_call, candidate_call = evaluated.call_args_list[-2:]
                        self.assertIsNotNone(baseline_call.args[0])
                        self.assertIsNot(baseline_call.args[0], candidate_call.args[0])
                        self.assertEqual(baseline_call.args[1], run_config)
                        self.assertEqual(candidate_call.args[1], run_config)
                        for key in ("seeds", "commands", "command_switch_seconds",
                                    "command_switch_range", "compact"):
                            self.assertEqual(baseline_call.kwargs[key], candidate_call.kwargs[key])
                        self.assertFalse(baseline_call.kwargs["compact"])
                        measured = json.loads((output/"evaluation.json").read_text())
                        reference = dict(evaluation_purpose="source_policy_baseline",
                            checkpoint_id=checkpoints[0]["id"], policy=checkpoints[0]["policy"])
                        self.assertEqual(manifest["evaluation_baseline"], reference)
                        for key, value in reference.items():
                            self.assertEqual(measured["baseline"][key], value)
                        self.assertEqual(measured["baseline"]["policy_kind"], "neural_foot_offsets")
                        self.assertEqual(measured["baseline"]["evaluation_seeds"],
                                         measured["candidate"]["evaluation_seeds"])
                        for key, value in initial.policy.state_dict().items():
                            torch.testing.assert_close(baseline_call.args[0].policy.state_dict()[key],
                                                       value, rtol=0, atol=0)
                        self.assertTrue(any(not torch.equal(value, candidate_call.args[0].policy.state_dict()[key])
                                            for key, value in initial.policy.state_dict().items()))
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
            sac = Path(root)/"def"
            sac.mkdir()
            (sac/"manifest.json").write_text(json.dumps(dict(algorithm="SAC", environment=asdict(config),
                environment_version=ENVIRONMENT_VERSION, representation=representation_identity())))
            (sac/"policy.zip").touch()
            from gateway.neural_gait.training import LOCOMOTION_RECIPE
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(initialize_from="def", steps=4,
                    recipe=LOCOMOTION_RECIPE, value_warmup_steps=8, value_learning_rate=3e-4,
                    action_noise_std=[.03]*12, device="cuda", seed=22))
            arguments = launch.call_args.args[0]
            self.assertEqual(arguments[arguments.index("--value-warmup-steps")+1], "8")
            self.assertEqual(arguments[arguments.index("--recipe")+1], LOCOMOTION_RECIPE)
            self.assertEqual(arguments[arguments.index("--device")+1], "cuda")
            self.assertEqual(arguments[arguments.index("--seed")+1], "22")
            saved = json.loads(Path(arguments[arguments.index("--config")+1]).read_text())
            self.assertEqual(saved["reward_profile"], "locomotion")
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
            longer = {**asdict(config), "episode_seconds":60.}
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(resume="abc", steps=4, environment=longer,
                                                 evaluation_seeds=[1001, 1003]))
            arguments = launch.call_args.args[0]
            self.assertEqual(arguments[-3:], ["--evaluation-seeds", "1001", "1003"])
            saved = json.loads(Path(arguments[arguments.index("--config")+1]).read_text())
            self.assertEqual(saved["episode_seconds"], 60.)
            for seeds in ([], [-1], [True], [1.5]):
                with self.assertRaisesRegex(ValueError, "Evaluation seeds"):
                    Runtime(root).start_training(dict(resume="abc", steps=4, evaluation_seeds=seeds))
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                Runtime(root).start_training(dict(resume="abc", steps=4, exploration_learning_rate=3e-4))
            self.assertEqual(launch.call_args.args[0][-2:], ["--exploration-learning-rate", "0.0003"])
            extended = asdict(config)
            extended.update(observation_schema=DEPTH_SCHEMA,
                            scenarios=[dict(id="incline", slope_deg=[0, 5])])
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                (source/"chosen.zip").touch()
                result = Runtime(root).start_training(dict(initialize_from="abc",
                    initialize_checkpoint="chosen.zip", environment=extended, steps=4))
            arguments = launch.call_args.args[0]
            self.assertEqual(arguments[arguments.index("--initialize-from")+1], str(source))
            self.assertNotIn("--resume", arguments)
            self.assertEqual(arguments[-2:], ["--initialize-checkpoint", "chosen.zip"])
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

    def test_camera_noise_gets_multiple_evaluation_seeds_without_imu_noise(self):
        from functools import partial
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.training import evaluate
        camera = dict(imageSize=[8,8], cameraMatrix=[[8,0,4],[0,8,4],[0,0,1]],
            cameraToBody=[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],
            capture_hz=10, latency_s=.04, dropout_probability=0., noise_std_m=0.,
            provenance={"basis":"test optical geometry"})
        for noise in (dict(noise_std_m=.001), dict(startup_latency_s=[.04, 14.825]), dict(odometry=dict(
                position_noise_std_m=0., rotation_noise_std_rad=0., log_scale_std=.1,
                dropout_probability=0.))):
            config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.04,
                observation_schema=DEPTH_SCHEMA, depth_camera={**camera, **noise})
            with patch("gateway.neural_gait.training.make_environment",
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
        from gateway.neural_gait.training import evaluate

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
        with patch("gateway.neural_gait.training.make_environment", side_effect=environment):
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
        from gateway.neural_gait.training import evaluate
        variations = [dict(randomization=.1), dict(feedback_noise_raw_std=1.),
                      dict(imu_accel_noise_std=.01), dict(imu_gyro_noise_std=.01), {}]
        for variation in variations:
            with self.subTest(variation=variation):
                config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.06, **variation)
                env = GaitEnvironment(config, include_assembly=False, include_visuals=False)
                env.reset = Mock(wraps=env.reset)
                timing = {} if variation else dict(command_switch_range=[.02,.04])
                with patch("gateway.neural_gait.training.make_environment", return_value=env):
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

    def test_dagger_releases_collection_executor_before_checkpoint_evaluation(self):
        import numpy as np
        from dataclasses import asdict, replace
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, ENVIRONMENT_VERSION, representation_identity
        from gateway.neural_gait.contract import COMMAND_SLICE
        from gateway.neural_gait.training import train, Progress
        commands = [[.08, 0, 0], [-.015, 0, 0]]
        config = EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            episode_seconds=.08, command=commands[0],
            scenarios=[dict(id="standing"), dict(id="incline", slope_deg=[0,2])])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for index, command in enumerate(commands):
                path = root/f"teacher-{index}.npz"
                observation = np.zeros((3, OBSERVATION_SIZE), dtype=np.float32)
                observation[:, COMMAND_SLICE] = command
                np.savez(path, observation=observation, action=np.zeros((3, 12), dtype=np.float32))
                path.with_suffix(".json").write_text(json.dumps(dict(schema=SCHEMA,
                    environment_version=ENVIRONMENT_VERSION, environment=asdict(replace(config, command=command)),
                    representation=representation_identity(), recommended_cycle_rows=[0, 3])))
                sources.append(path)
            with patch.object(Progress, "render_progress"), patch.object(Progress, "finish_rendering", return_value=True):
                train(root/"run", 0, config, demonstrations=sources, demonstration_cycles=True,
                      imitation_updates=1, expert_mix=(0,), updates_per_round=1)
            progress = json.loads((root/"run/progress.json").read_text())
            self.assertEqual(progress["state"], "completed")
            rounds = json.loads((root/"run/aggregation.json").read_text())["rounds"]
            self.assertEqual(len(rounds), 2)
            for round_ in rounds:
                self.assertEqual([(case["command"],case["scenario_id"]) for case in round_["collection"]],
                    [(command,scenario) for command in commands for scenario in ("standing","incline")])
            for episode in progress["evaluation"]["episodes"]:
                self.assertEqual(episode["execution_backend"], "body_control")

    def test_locomotion_recipe_uses_body_control_and_saved_normalization(self):
        import numpy as np
        import torch
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.contract import HISTORY_SCHEMA, HISTORY_SIZE
        from gateway.neural_gait.training import (train, load_policy, Progress, LOCOMOTION_RECIPE,
            TRUST_REGION_KL)
        config = EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            observation_schema=HISTORY_SCHEMA, episode_seconds=.24, command=[.03,0,0],
            balance_enabled=True, heading_feedback_enabled=True)
        commands = [[.03,0,0],[-.03,0,0]]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"abc"
            with patch.object(Progress,"render_progress"), patch.object(Progress,"finish_rendering",return_value=True):
                train(path,48,config,workers=1,commands=commands,command_switch_seconds=.12,
                      checkpoint_every=48)
            manifest=json.loads((path/"manifest.json").read_text())
            self.assertEqual(manifest["algorithm"],"PPO")
            self.assertEqual(manifest["recipe"],LOCOMOTION_RECIPE)
            self.assertEqual(manifest["commands"],commands)
            self.assertEqual(manifest["environment"]["reward_profile"],"locomotion")
            self.assertTrue(manifest["environment"]["balance_enabled"])
            self.assertTrue(manifest["environment"]["heading_feedback_enabled"])
            model=load_policy(path)
            self.assertEqual(model.ent_coef,.01)
            # The 48-step request caps the rollout at two 24-step rollouts; the
            # recipe budget is 2048 transitions with a four-minibatch divisor.
            self.assertEqual((model.n_steps,model.batch_size),(24,6))
            self.assertEqual(model.target_kl,TRUST_REGION_KL)
            self.assertTrue(model.policy.normalize_observations)
            self.assertGreater(float(model.policy.observation_count),1)
            observed=np.zeros(HISTORY_SIZE,dtype=np.float32)
            first=model.predict(observed,deterministic=True)[0]
            changed=observed.copy();changed[-5:]=1000
            np.testing.assert_array_equal(first,model.predict(changed,deterministic=True)[0])
            original_stats=model.policy.observation_count.clone()
            model.predict(observed,deterministic=True)
            torch.testing.assert_close(original_stats,model.policy.observation_count)
            reloaded=load_policy(path)
            np.testing.assert_array_equal(first,reloaded.predict(observed,deterministic=True)[0])
            self.assertTrue(np.isfinite(first).all())
            comparison=json.loads((path/"evaluation.json").read_text())
            self.assertEqual(comparison["baseline"]["evaluation_purpose"], "standing_baseline")
            self.assertEqual(comparison["baseline"]["policy_kind"], "held_standing_reference")
            evaluation=comparison["candidate"]
            for episode in evaluation["episodes"]:
                self.assertEqual(episode["execution_backend"],"body_control")
                self.assertEqual(episode["rejected_frames"],0)
                self.assertGreater(episode["consumed_sample"],0)
                self.assertIn("tracking_linear",episode["command_segments"][0]["reward_components"])
            # Resume retains normalization, optimizer and the same recipe, with no head conversion.
            resumed=Path(temporary)/"def"
            saved_config=EnvironmentConfig(**manifest["environment"])
            with patch.object(Progress,"render_progress"), patch.object(Progress,"finish_rendering",return_value=True):
                train(resumed,24,saved_config,resume=path)
            continued=load_policy(resumed)
            self.assertEqual(continued.num_timesteps,72)
            self.assertGreater(continued._n_updates,model._n_updates)
            # The resume keeps the source moments as its starting point instead of
            # resetting them, then adds its own first-rollout refresh of 12 samples.
            self.assertGreater(float(original_stats),1)
            torch.testing.assert_close(continued.policy.observation_count,original_stats+12)

    def test_rollout_geometry_keeps_the_recipe_sample_budget_per_update(self):
        from gateway.neural_gait.training import (locomotion_rollout_geometry,
            MINIBATCH_DIVISOR, ROLLOUT_TRANSITIONS)
        # The published recipe reaches its budget through parallelism, so the
        # rollout must be sized by transition count on this host's worker count.
        for count in (1,2,4,8,16):
            n_steps,batch=locomotion_rollout_geometry(count)
            self.assertEqual(n_steps*count,ROLLOUT_TRANSITIONS)
            self.assertEqual(batch,ROLLOUT_TRANSITIONS//MINIBATCH_DIVISOR)
            self.assertGreaterEqual(n_steps*count//batch,MINIBATCH_DIVISOR)
        # A short request never collects more transitions than it asked for, and
        # keeps two rollouts so the observation-moment refresh is exercised.
        self.assertEqual(locomotion_rollout_geometry(1,48),(24,6))
        self.assertEqual(locomotion_rollout_geometry(8,64),(4,8))
        # Below two steps per worker the rollout floors at 1; the minibatch then
        # follows the buffer the workers actually fill (16), not the request.
        self.assertEqual(locomotion_rollout_geometry(16,8),(1,4))
        # A real budget leaves the recipe geometry untouched.
        self.assertEqual(locomotion_rollout_geometry(8,2097152),(256,512))

    def test_rollout_resize_keeps_discounting_and_buffer_class(self):
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import (GaitPPO, GaitPPOPolicy,
            PreciseActionRolloutBuffer, apply_rollout_geometry)
        env = GaitEnvironment(EnvironmentConfig(robot=robot_fixture(), episode_seconds=.08),
                              include_assembly=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=64, batch_size=64, n_epochs=5,
            gamma=.99, gae_lambda=.95, rollout_buffer_class=PreciseActionRolloutBuffer,
            policy_kwargs=dict(net_arch=[8,8], learned_std=True), seed=1)
        apply_rollout_geometry(model, 8, 8)
        self.assertEqual((model.n_steps,model.batch_size),(8,8))
        self.assertIsInstance(model.rollout_buffer,PreciseActionRolloutBuffer)
        self.assertEqual(model.rollout_buffer.buffer_size,8)
        # RolloutBuffer defaults gae_lambda to 1, so a resize that omitted the
        # model's own discounting would silently change the advantage estimator.
        self.assertEqual(model.rollout_buffer.gamma,.99)
        self.assertEqual(model.rollout_buffer.gae_lambda,.95)
        retained = model.rollout_buffer
        apply_rollout_geometry(model, 8, 8)
        self.assertIs(model.rollout_buffer,retained)

    def test_normalized_observation_clip_bounds_a_constant_coordinate(self):
        import numpy as np
        import torch
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import GaitPPO, GaitPPOPolicy, OBSERVATION_CLIP
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12,
                                   observation_schema=DEPTH_SCHEMA)
        env = GaitEnvironment(config, include_assembly=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=2, batch_size=2, n_epochs=1,
            policy_kwargs=dict(net_arch=[8,8], learned_std=True, action_coordinates="linear",
                               normalize_observations=True), seed=1)
        policy = model.policy
        # A coordinate that is constant under the request set (an unused command
        # axis, an absent depth grid) keeps ~zero running variance, so dividing
        # by sqrt(variance+epsilon) alone would amplify it by ~1e4.
        with torch.no_grad():
            policy.observation_mean.zero_()
            policy.observation_variance.zero_()
        observed = np.zeros(env.observation_space.shape, dtype=np.float32)
        observed[0] = 1.
        features = policy.extract_features(
            torch.as_tensor(observed[None], dtype=torch.float32, device=policy.device))
        features = features[0] if isinstance(features, tuple) else features
        self.assertLessEqual(float(features.abs().max()), OBSERVATION_CLIP)
        self.assertGreater(float(features.abs().max()), OBSERVATION_CLIP*.99)

    def test_recipe_trust_region_lets_the_configured_epochs_run(self):
        from gateway.neural_gait.contract import DEPTH_SCHEMA
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import GaitPPO, GaitPPOPolicy, TRUST_REGION_KL
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.12,
                                   observation_schema=DEPTH_SCHEMA)
        env = GaitEnvironment(config, include_assembly=False)
        self.addCleanup(env.close)
        model = GaitPPO(GaitPPOPolicy, env, n_steps=8, batch_size=8, n_epochs=5,
            learning_rate=3e-4, clip_range=.2, ent_coef=.01, target_kl=TRUST_REGION_KL,
            policy_kwargs=dict(net_arch=[8,8], learned_std=True, action_coordinates="linear",
                               normalize_observations=True), seed=1)
        model.learn(total_timesteps=32)
        rollouts = 4
        # SB3 counts completed epochs. The former 0.02 target aborted after the
        # first one, so ~1.02 epochs per rollout is the regression signature.
        self.assertGreater(model._n_updates, rollouts)

    def test_explicit_cuda_request_cannot_silently_train_on_cpu(self):
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import train
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"abc"
            with patch("gateway.neural_gait.training.torch.cuda.is_available",return_value=False):
                with self.assertRaisesRegex(RuntimeError,"CUDA training requested"):
                    train(path,24,EnvironmentConfig(robot=robot_fixture()),device="cuda")
            self.assertFalse(path.exists())

    def test_new_training_api_selects_recipe_and_keeps_requested_commands(self):
        from unittest.mock import patch
        from dataclasses import asdict
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.server import Runtime
        from gateway.neural_gait.training import LOCOMOTION_RECIPE
        with tempfile.TemporaryDirectory() as temporary:
            with patch("gateway.neural_gait.server.subprocess.Popen") as launch:
                result=Runtime(temporary).start_training(dict(steps=48,recipe=LOCOMOTION_RECIPE,
                    commands=[[.03,0,0],[0,0,.4]],
                    environment=asdict(EnvironmentConfig(robot=robot_fixture()))))
            arguments=launch.call_args.args[0]
            self.assertEqual(arguments.count("--command"),2)
            self.assertEqual(arguments[arguments.index("--recipe")+1],LOCOMOTION_RECIPE)
            saved=json.loads((Path(temporary)/result["run_id"]/"environment.json").read_text())
            self.assertEqual(saved["reward_profile"],"locomotion")
            self.assertEqual(saved["execution_backend"],"body_control")



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
        self.assertEqual(resume_environment_changes(manifest, replace(old, episode_seconds=60.)),
                         {"episode_seconds": {"from":old.episode_seconds, "to":60.}})
        with self.assertRaisesRegex(ValueError, "same environment"):
            resume_environment_changes({**manifest, "algorithm":"SAC"}, replace(old, episode_seconds=60.))
        deployed = replace(connected, control_hz=33, physics_hz=528,
                           balance_enabled=True, balance_tuning=[1,1,3,1.5928])
        changes = resume_environment_changes(manifest, deployed)
        self.assertEqual(changes["control_hz"], {"from":50,"to":33})
        self.assertEqual(changes["balance_tuning"]["to"], [1,1,3,1.5928])
        noisy = replace(deployed, feedback_noise_raw_std=30,
                        imu_accel_noise_std=.05, imu_gyro_noise_std=.004,
                        imu_prehistory_s=4.)
        changes = resume_environment_changes(manifest, noisy)
        self.assertEqual(changes["feedback_noise_raw_std"], {"from":0., "to":30})
        self.assertEqual(changes["imu_accel_noise_std"]["to"], .05)
        self.assertEqual(changes["imu_gyro_noise_std"]["to"], .004)
        self.assertEqual(changes["imu_prehistory_s"], {"from":0., "to":4.})
        with self.assertRaisesRegex(ValueError, "same environment"):
            resume_environment_changes({**manifest, "algorithm":"SAC"}, noisy)
        from copy import deepcopy
        deployed.robot = deepcopy(deployed.robot)
        deployed.robot["feedback"]["jam_enabled"] = False
        self.assertIn("robot", resume_environment_changes(manifest, deployed))
        deployed.robot["calibration"][0]["home_us"] += 1
        with self.assertRaisesRegex(ValueError, "same environment"):
            resume_environment_changes(manifest, deployed)
        with self.assertRaisesRegex(ValueError, "same environment"):
            resume_environment_changes({**manifest,"algorithm":"SAC"}, deployed)

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
    def test_policy_history_matches_publication_contents_not_latest_checkpoint(self):
        import hashlib
        from zipfile import ZipFile, ZipInfo
        from gateway.neural_gait.training import policy_imitation_updates
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)
            def saved(name, optimizer, year=2025):
                with ZipFile(run/name, "w") as archive:
                    for member, value in {"policy.pth":b"same weights",
                                          "policy.optimizer.pth":optimizer,
                                          "data":b"same RL count"}.items():
                        archive.writestr(ZipInfo(member, (year, 1, 1, 0, 0, 0)), value)
            saved("selected.zip", b"selected optimizer")
            saved("later.zip", b"later optimizer")
            saved("policy.zip", b"selected optimizer", year=2026)
            self.assertNotEqual((run/"policy.zip").read_bytes(), (run/"selected.zip").read_bytes())
            selected = dict(id="selected", policy="selected.zip", imitation_updates=41000)
            later = dict(id="later", policy="later.zip", imitation_updates=43000)
            (run/"checkpoints.json").write_text(json.dumps([selected, later]))
            (run/"manifest.json").write_text('{}')
            (run/"progress.json").write_text('{"state":"error","error":"interrupted"}')
            self.assertEqual(policy_imitation_updates(run), 41000)
            self.assertEqual(policy_imitation_updates(run, "later.zip"), 43000)
            # A stale selection cannot override the actual policy contents.
            (run/"selection.json").write_text(json.dumps(dict(later,
                policy_sha256=hashlib.sha256((run/"later.zip").read_bytes()).hexdigest())))
            self.assertEqual(policy_imitation_updates(run), 41000)
            # The published selection is authoritative even without the index.
            (run/"selection.json").write_text(json.dumps(dict(selected,
                policy_sha256=hashlib.sha256((run/"policy.zip").read_bytes()).hexdigest())))
            (run/"checkpoints.json").unlink()
            self.assertEqual(policy_imitation_updates(run), 41000)
            # Legacy metadata remains supported; never infer a count from a name.
            (run/"selection.json").unlink()
            (run/"progress.json").write_text('{"imitation_updates":123}')
            self.assertEqual(policy_imitation_updates(run), 123)

    def test_dashboard_history_keeps_trial_measurements_without_copying_time_series(self):
        from gateway.neural_gait.server import Runtime
        with tempfile.TemporaryDirectory() as root:
            run = Path(root) / "abc"
            run.mkdir()
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
        from types import SimpleNamespace
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment
        from gateway.neural_gait.training import evaluate, Progress
        config = EnvironmentConfig(robot=robot_fixture(), episode_seconds=.02,
            imu_gyro_noise_std=.01, scenarios=[{"id":"flat"}, {"id":"incline", "slope_deg":[0,2]}])
        commands = [[.015,0,0], [-.03,0,0]]
        with patch("gateway.neural_gait.training.make_environment",
                   partial(GaitEnvironment, include_assembly=False)):
            compact = evaluate(None, config, commands=commands, compact=True)
            full = evaluate(None, config, commands=commands)
            with tempfile.TemporaryDirectory() as root:
                owner = Progress(Path(root), 0, config, commands=commands, evaluation_seeds=[7, 13])
                owner.model = SimpleNamespace(num_timesteps=0)
                declared = owner.evaluate(None, "final_candidate")
                status = json.loads((Path(root)/"progress.json").read_text())
                self.assertEqual(status["evaluation_seeds"], [7, 13])
                probe = owner.evaluate(None, "checkpoint", compact=True)
                self.assertEqual(json.loads((Path(root)/"progress.json").read_text())["evaluation_seeds"], [1000])
        self.assertEqual(compact["evaluation_scope"], "compact_checkpoint")
        self.assertEqual([(e["command"],e["scenario_id"],e["seed"]) for e in compact["episodes"]],
                         [(command,"flat",1000) for command in commands])
        self.assertEqual(full["evaluation_scope"], "full_configured_suite")
        self.assertEqual(len(full["episodes"]), 2*2*8)
        self.assertEqual(full["evaluation_seeds"], list(range(1000, 1008)))
        self.assertEqual(declared["evaluation_seeds"], [7, 13])
        self.assertEqual([(e["command"], e["scenario_id"], e["seed"]) for e in declared["episodes"]],
                         [(command, scenario, seed) for command in commands
                          for scenario in ("flat", "incline") for seed in (7, 13)])
        self.assertEqual(probe["evaluation_seeds"], [1000])
        self.assertEqual(probe["episodes"], compact["episodes"])

    def test_training_cli_passes_explicit_evaluation_seeds(self):
        from dataclasses import asdict
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.training import main
        with tempfile.TemporaryDirectory() as root:
            config = Path(root)/"environment.json"
            config.write_text(json.dumps(asdict(EnvironmentConfig(robot=robot_fixture()))))
            with patch("sys.argv", ["training", "--directory", str(Path(root)/"run"),
                       "--config", str(config), "--steps", "4", "--evaluation-seeds", "7", "13"]), \
                 patch("gateway.neural_gait.training.train") as training:
                main()
            self.assertEqual(training.call_args.kwargs["evaluation_seeds"], [7, 13])

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


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is required")
class GuidedTeacherTests(unittest.TestCase):
    """Recovered guided-teacher generator: waveform fidelity and re-timing.

    Both defects below were real and were caught only by measurement, so each is
    pinned here. Waveforms are synthesized rather than read from
    build/neural-gait, which is not part of the repository.
    """

    ORDER = (0.75, 0.25, 0.5, 0.0)

    def test_reference_reconstruction_uses_recorded_cadence(self):
        import io
        import numpy as np
        from contextlib import redirect_stdout
        from gateway.neural_gait.teachers import main
        arrays = self.synthetic(self.ORDER, 10, 6, [1.]*4)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"reference.npz"
            np.savez(path, **arrays, action=np.zeros((60,12)), position_m=np.zeros((60,3)))
            path.with_suffix(".json").write_text(json.dumps(dict(
                case=dict(id="10hz-reference", period=1., order=self.ORDER),
                environment=dict(control_hz=10))))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--reference", str(path), "--verify"]), 0)
            self.assertIn("RECONSTRUCTION      : EXACT", output.getvalue())

    def test_base_config_preserves_consuming_execution_and_reward_settings(self):
        from dataclasses import asdict
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.teachers import build_config
        config = EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
            locomotion_tracking_window_s=.2, locomotion_target_air_time_s=.3)
        base = asdict(config)
        base["locomotion_reward_weights"]["feet_air_time"] = 1.
        result = asdict(build_config(base, [.034, 0, 0], 32))
        self.assertEqual(result, {**base, "command": [.034, 0, 0], "episode_seconds": 32.})

    def test_generation_records_the_selected_body_control_executor(self):
        import numpy as np
        from unittest.mock import patch
        from gateway.neural_gait.environment import EnvironmentConfig, make_environment
        from gateway.neural_gait.teachers import generate
        config = EnvironmentConfig(robot=robot_fixture(), execution_backend="body_control",
                                   episode_seconds=.4, command=[.034, 0, 0],
                                   scenarios=[dict(id="other"), dict(id="requested")])
        arrays = self.synthetic(self.ORDER, 5, 6, [1.]*4)
        case = dict(id="connected", period=.1, stride=1., lean_x=0., lean_y=1., lift=1.,
            duration_s=.4, order=self.ORDER, reference_stride=1., reference_lean_y=1.,
            reference_lift=1., waveform_reference="synthetic", seed=1, scenario_id="requested")
        def heading_fixture(*args, **kwargs):
            env = make_environment(*args, **kwargs)
            # Training demonstrations must retain the actual collision meshes,
            # even when no video is requested. The primitive-only plant used to
            # be recorded as "full CAD physics" by this producer.
            self.assertGreater(env.model.nmesh, 0)
            self.assertAlmostEqual(float(env.model.body_mass.sum()), config.mass_kg)
            step = env.step
            count = 0
            def reported_heading(action):
                nonlocal count
                result = step(action)
                count += 1
                # A fast turn crosses +/-pi without reversing direction.
                result[-1]["heading_rad"] = (2.9 + .1*count + np.pi) % (2*np.pi) - np.pi
                return result
            env.step = reported_heading
            return env
        with tempfile.TemporaryDirectory() as root:
            with patch("gateway.neural_gait.teachers.make_environment", side_effect=heading_fixture) as factory:
                result = generate(case, config, self.waveform(arrays, 5), root)
            self.assertEqual(factory.call_args.args[0].execution_backend, "body_control")
            self.assertEqual(result["environment"]["execution_backend"], "body_control")
            self.assertEqual(result["scenario_id"], "requested")
            self.assertAlmostEqual(result["yaw_change_rad"], 1.9)
            with np.load(Path(root)/"connected.npz") as data:
                self.assertEqual(len(data["observation"]), 20)
                self.assertTrue(np.isnan(data["fitted_offset_mm"]).all())
                self.assertTrue(data["truncated"][-1])
                self.assertFalse(data["truncated"][:-1].any())
                self.assertFalse(np.array_equal(data["next_observation"][-1], data["observation"][-1]))

    @staticmethod
    def synthetic(order, cycle, cycles, amplitudes):
        import numpy as np
        total = cycle*cycles
        step = np.arange(total)
        phase = (step[:, None]/cycle + np.asarray(order)[None, :]) % 1.0
        offsets = np.zeros((total, len(order), 3))
        for leg, amplitude in enumerate(amplitudes):
            wave = 2*np.pi*phase[:, leg]
            offsets[:, leg, 0] = amplitude*np.cos(wave)
            offsets[:, leg, 1] = .5*amplitude*np.sin(wave)
            offsets[:, leg, 2] = amplitude*np.maximum(0., np.sin(wave))
        ramp = np.minimum(1., step/cycle)
        return dict(requested_offset_mm=offsets*ramp[:, None, None], phase=phase)

    def waveform(self, arrays, cycle, hz=50):
        from gateway.neural_gait.teachers import steady_waveform
        return steady_waveform(arrays, self.ORDER, cycle/hz, hz)

    def test_reconstruction_reproduces_a_reference_exactly(self):
        import numpy as np
        from gateway.neural_gait.teachers import render_offsets
        arrays = self.synthetic(self.ORDER, 125, 6, [20.]*4)
        rendered = render_offsets(len(arrays["phase"]), self.waveform(arrays, 125),
                                  self.ORDER, (1., 1., 1.), 0., 125)
        # Covers the startup cycle too: the ramp is part of the recovered model,
        # and omitting it would bake a full-amplitude first cycle into a teacher.
        self.assertLess(float(np.abs(rendered-arrays["requested_offset_mm"]).max()), 1e-9)

    def test_per_leg_tables_preserve_left_right_asymmetry(self):
        import numpy as np
        from gateway.neural_gait.teachers import render_offsets
        arrays = self.synthetic(self.ORDER, 150, 5, [20., 20., 8., 8.])
        waveform = self.waveform(arrays, 150)
        rendered = render_offsets(len(arrays["phase"]), waveform, self.ORDER,
                                  (1., 1., 1.), 0., 150)
        self.assertLess(float(np.abs(rendered-arrays["requested_offset_mm"]).max()), 1e-9)
        self.assertEqual(len(waveform["tables"]), 4)
        # One pooled waveform blurred exactly this difference, and the regenerated
        # turning teachers then produced no yaw at all — negative yaw for a left
        # turn. Per-leg tables are what make an asymmetric gait survivable.
        self.assertGreater(float(np.abs(rendered[:, 0, 0]-rendered[:, 2, 0]).max()), 1.)

    def test_requested_period_retimes_the_gait(self):
        import math
        from gateway.neural_gait.teachers import render_offsets
        arrays = self.synthetic(self.ORDER, 125, 6, [20.]*4)
        waveform = self.waveform(arrays, 125)
        step = 130
        reference = render_offsets(step+1, waveform, self.ORDER, (1., 1., 1.), 0., 125)
        faster = render_offsets(step+1, waveform, self.ORDER, (1., 1., 1.), 0., 62)
        expected_reference = 20.*math.cos(2*math.pi*((step/125) % 1.))
        expected_faster = 20.*math.cos(2*math.pi*((step/62) % 1.))
        # Reading the cycle length from the waveform instead of the request made
        # --period a no-op: every candidate rendered at the reference cadence, and
        # the first sweep reported one identical speed for four different periods.
        self.assertAlmostEqual(float(reference[step, 3, 0]), expected_reference, delta=1e-6)
        self.assertAlmostEqual(float(faster[step, 3, 0]), expected_faster, delta=.5)
        self.assertGreater(abs(expected_reference-expected_faster), 1.)

    def test_action_envelope_rejects_an_unreachable_gait(self):
        from gateway.neural_gait.environment import EnvironmentConfig
        from gateway.neural_gait.teachers import generate
        arrays = self.synthetic(self.ORDER, 125, 6, [20.]*4)
        case = dict(id="too-big", period=2.5, stride=400., lean_x=0., lean_y=16.,
                    lift=25., duration_s=16., order=self.ORDER, reference_stride=40.,
                    reference_lean_y=16., reference_lift=25., waveform_reference="synthetic",
                    seed=1)
        config = EnvironmentConfig(robot=robot_fixture(), command=[.08, 0, 0],
                                   episode_seconds=16.)
        with tempfile.TemporaryDirectory() as root:
            # Rejected before any simulator is constructed, so a saturated teacher
            # cannot be recorded and then cloned against a clipped target.
            with self.assertRaisesRegex(ValueError, "foot action envelope"):
                generate(case, config, self.waveform(arrays, 125), root)

    def test_recommended_cycle_rows_select_one_steady_cycle_after_startup(self):
        from gateway.neural_gait.teachers import cycle_rows
        # These match the rows the original generator recorded for the two periods
        # its surviving demonstrations use.
        self.assertEqual(cycle_rows(2.5, 50, 800), [375, 500])
        self.assertEqual(cycle_rows(3., 50, 800), [450, 600])
        with self.assertRaises(ValueError):
            cycle_rows(2.5, 50, 400)


class NativeDemonstrationTests(unittest.TestCase):
    def test_full_cycle_labels_use_native_calibration_fit_before_foot_encoding(self):
        from types import SimpleNamespace
        import numpy as np
        from gateway.neural_gait.native import BodyModel, derive_foot_action_scale
        from gateway.neural_gait.server import Runtime
        from gateway.neural_gait.contract import PENDING_SCHEMA, ObservationHistory
        robot = robot_fixture()
        # Synthetic horn offsets make the rear-right native swing cross the
        # installed PWM limits. These are fixture values, not captured hardware.
        robot['calibration'][4]['home_us'] = 565
        robot['calibration'][5]['home_us'] = 1900
        reference = [0, 3.46, -21.63] * 4
        limits = [[-180, 180]] * 12
        environment = dict(robot=robot, reference_joint_deg=reference,
            target_limits_deg=limits, foot_action_scale_mm=derive_foot_action_scale(robot, reference, limits),
            joint_speed_deg_s=60/.11, observation_schema=PENDING_SCHEMA)
        direct = BodyModel(robot)
        self.addCleanup(direct.close)
        direct.walk_configure(speed_deg_s=60/.11, heading_enabled=False, balance_enabled=False)
        command = dict(t='intent', name='walk', dir='fwd', steps=0, speed=100)
        self.assertTrue(direct.walk_accept({**command, 'seq':1}, 1000000))
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(directory)
            self.addCleanup(runtime.collection_end, 'robot', 'first')
            runtime.kind, runtime.model_id, runtime.checkpoint_id = 'physical-redq', 'abc', 'checkpoint'
            runtime.environment = environment
            runtime.model = SimpleNamespace(metadata={'pending_input_dim':14})
            source = ObservationTests().source()
            for name, angle in zip(JOINTS, reference):
                source['joints'][name]['commanded_model_deg'] = angle
            history = ObservationHistory()
            fitted_count = 0
            for step in range(661):
                now = 1000000 + round(step * 1000000 / 33)
                source['feedback']['device_us'] = now
                current = observation(source, environment, [.05,0,0], history=history, pending_actions=[])
                request = dict(source='native-c',robot_id='robot',owner='first',device_us=now,
                    command=command,gateway_instance='gateway',epoch=1,walk=1)
                actual = runtime.infer(current,explore=True,demonstration=request)
                expected = direct.walk_tick(now,reference)
                raw, target = expected['nominal_angles'], expected['balanced_angles']
                fitted_count += int(np.max(np.abs(raw-target)) > .01)
                np.testing.assert_array_equal(actual['demonstration']['nominal_joint_deg'],raw)
                np.testing.assert_array_equal(actual['demonstration']['target_joint_deg'],target)
                # Offline label correction must select the fitted goal, not
                # the separately ramped and PWM-quantized execution frame.
                np.testing.assert_array_equal(direct.target(raw,reference,60/.11,1.)[1],target)
                offsets = np.asarray(actual['requested_foot_offset_mm']).reshape(4,3)
                decoded = direct.foot_target(offsets,reference,target,60/.11,1.)
                self.assertEqual(decoded['fit'],1.)
                np.testing.assert_allclose(decoded['nominal_goal_angles'],target,atol=.001)
            self.assertGreater(fitted_count,0)

    def test_real_observation_clock_native_targets_updates_and_owner_cleanup(self):
        from types import SimpleNamespace
        import numpy as np
        from gateway.neural_gait.native import BodyModel, derive_foot_action_scale
        from gateway.neural_gait.server import Runtime
        from gateway.neural_gait.contract import PENDING_SCHEMA, ObservationHistory
        robot = robot_fixture()
        reference = [0, 3.46, -21.63] * 4
        limits = [[-90, 90]] * 12
        environment = dict(robot=robot, reference_joint_deg=reference,
            target_limits_deg=limits, foot_action_scale_mm=derive_foot_action_scale(robot, reference, limits),
            joint_speed_deg_s=60/.11, observation_schema=PENDING_SCHEMA)
        direct = BodyModel(robot)
        self.addCleanup(direct.close)
        direct.walk_configure(speed_deg_s=60/.11, heading_enabled=False, balance_enabled=False)
        command = dict(t='intent', name='walk', dir='fwd', steps=0, speed=100)
        self.assertTrue(direct.walk_accept({**command, 'seq':1}, 1000000))
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(directory)
            runtime.kind, runtime.model_id, runtime.checkpoint_id = 'physical-redq', 'abc', 'checkpoint'
            runtime.environment = environment
            runtime.model = SimpleNamespace(metadata={'pending_input_dim':14})
            source = ObservationTests().source()
            for name, angle in zip(JOINTS, reference):
                source['joints'][name]['commanded_model_deg'] = angle
            history = ObservationHistory()
            requests = []
            for now in (1000000, 1017000, 1081000, 1200000, 1430000, 1800000):
                source['feedback']['device_us'] = now
                current = observation(source, environment, [.05,0,0], history=history, pending_actions=[])
                request = dict(source='native-c',robot_id='robot',owner='first',device_us=now,command=command, gateway_instance='gateway',epoch=1,walk=1)
                actual = runtime.infer(current, explore=True, model_id='abc',checkpoint_id='checkpoint',demonstration=request)
                expected = direct.walk_tick(now, reference)
                np.testing.assert_array_equal(actual['demonstration']['nominal_joint_deg'],expected['nominal_angles'])
                self.assertEqual(actual['demonstration']['phase'], expected['phase'])
                self.assertEqual(actual['demonstration']['device_us'], now)
                self.assertFalse(actual['demonstration']['heading_enabled'])
                self.assertFalse(actual['demonstration']['balance_enabled'])
                self.assertFalse(actual['exploration'])
                offsets = np.asarray(actual['requested_foot_offset_mm']).reshape(4,3)
                fitted = direct.foot_target(offsets,reference,expected['balanced_angles'],60/.11,1.)
                np.testing.assert_allclose(fitted['nominal_goal_angles'],expected['balanced_angles'],atol=.03)
                np.testing.assert_array_equal(actual['demonstration']['target_joint_deg'],expected['balanced_angles'])
                self.assertEqual(actual['demonstration']['label_contract'],'native-c-calibrated-target-v1')
                requests.append(actual)
            self.assertGreater(np.ptp([x['demonstration']['phase']for x in requests]),0)
            command = {**command,'speed':50,'forward':-100,'turn':0}
            direct.walk_accept({**command,'seq':2,'update':1},1800000)
            request['command'] = command
            actual = runtime.infer(current, explore=True,demonstration=request)
            np.testing.assert_array_equal(actual['demonstration']['nominal_joint_deg'],direct.walk_tick(1800000,reference)['nominal_angles'])
            old_native = runtime.demonstrations['robot']['native']
            old_request = dict(request)
            request.update(owner='replacement',walk=2)
            runtime.infer(current, explore=True,demonstration=request)
            self.assertIsNone(old_native.state)
            replacement = runtime.demonstrations['robot']['native']
            with self.assertRaisesRegex(ValueError,'retired Walk'):
                runtime.infer(current,explore=True,demonstration=old_request)
            self.assertIs(runtime.demonstrations['robot']['native'],replacement)
            self.assertFalse(runtime.collection_end('robot','first')['retired'])
            self.assertTrue(runtime.collection_end('robot','replacement')['retired'])
            self.assertIsNone(runtime.demonstrations['robot']['native'])
            with self.assertRaisesRegex(ValueError,'retired Walk'):
                runtime.infer(current,explore=True,demonstration=request)
            with self.assertRaisesRegex(ValueError,'explicit collection'):
                runtime.infer(current,demonstration=request)

    def test_imitation_training_uses_existing_subprocess_lifecycle(self):
        from unittest.mock import patch
        from gateway.neural_gait.server import Runtime
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'abc';path.mkdir()
            (path/'manifest.json').write_text(json.dumps({'kind':'physical-redq'}))
            runtime=Runtime(directory)
            with patch('gateway.neural_gait.server.subprocess.Popen') as popen:
                runtime.physical_train(dict(model_id='abc',updates=10,recordings=['/actual'],method='imitation'))
                command=popen.call_args.args[0]
                self.assertIn('--imitate',command)
                self.assertNotIn('--fit-all',command)
                self.assertEqual(command[command.index('--recordings')+1],'/actual')
                runtime.physical_train(dict(model_id='abc',updates=10,recordings=['/actual'],
                    method='imitation',fit_all=True))
                self.assertIn('--fit-all',popen.call_args.args[0])
                self.assertIn('--imitate',popen.call_args.args[0])
                for invalid in ('true',1,None):
                    with self.assertRaisesRegex(ValueError,'must be a boolean'):
                        runtime.physical_train(dict(model_id='abc',updates=10,recordings=['/actual'],
                            method='imitation',fit_all=invalid))
                with self.assertRaisesRegex(ValueError,'only to imitation'):
                    runtime.physical_train(dict(model_id='abc',updates=10,recordings=['/actual'],fit_all=True))
                self.assertEqual(popen.call_count,2)

    def test_legacy_physical_creation_uses_existing_training_process(self):
        from unittest.mock import patch
        from gateway.neural_gait.server import Runtime
        from Emulator.tests.test_physical_gait import environment
        with tempfile.TemporaryDirectory() as root:
            runtime = Runtime(root)
            with patch('gateway.neural_gait.server.subprocess.Popen') as popen:
                result = runtime.physical_create(dict(environment=environment()))
                command = popen.call_args.args[0]
                self.assertEqual(command[command.index('--algorithm')+1], 'REDQ')
                self.assertFalse(result['movement_started'])
                self.assertIsNone(runtime.model_id)
