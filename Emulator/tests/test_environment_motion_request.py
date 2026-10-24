"""Description-based motion uses the configured Body Control owner; no hardware."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.server.service import GatewayService
from experiments.freestyle.bridge import Bridge
from experiments.freestyle.test_program import FakeGateway, FakeTransport


class MotionGateway(FakeGateway):
    instance_id = 'fixture-gateway'
    request_motion = GatewayService.request_motion

    def __init__(self):
        super().__init__()
        self.motion_systems = {'robot': 'freestyle'}
        self.motion_done = asyncio.Event()

    def subscribe_external_speech(self, callback):
        pass

    def subscribe_frames(self, callback):
        pass

    def subscribe_transcripts(self, callback):
        pass

    def _connection(self, robot):
        return SimpleNamespace(robot_id=robot or 'robot')

    def status(self):
        return {'robots': {'robot': {'connected': True, 'epoch': 1, 'model': 'v2-12servo',
            'features': ['body_commands_v1'], 'status': {}, 'capabilities': {'motion': True, 'commands': ['wave', 'stop']}}}}

    async def wait_terminal(self, seq, **kwargs):
        await self.motion_done.wait()
        return {'t': 'done', 'seq': seq}

    async def estop(self, **kwargs):
        self.seq += 1
        if kwargs.get('on_sequence'):
            kwargs['on_sequence'](self.seq)
        self.sent.append('stop')
        self.motion_done.set()
        for callback in self.commands:
            await callback({'t': 'stop', 'robot_id': 'robot', 'seq': self.seq})
        return self.seq


class MotionRequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gateway = MotionGateway()
        self.generated = []
        async def generate(endpoint, request):
            self.generated.append(request)
            return {'program': [{'name': 'move', 'arguments': {
                'joint': 'front_right_shoulder', 'angle_deg': 15, 'reference': 'current', 'speed_pct': 50}}]}
        self.bridge = Bridge(self.gateway, FakeTransport(), generate)
        self.gateway.freestyle_motion = self.bridge.submit
        self.gateway.freestyle_result = self.bridge.result
        self.gateway.freestyle_cancel = self.bridge.cancel
        self.adapter = EnvironmentAdapter(self.gateway, EnvironmentAdapterConfig(token='fixture', receipt_path=':memory:'))
        self.action = {'id': 'right-front-leg', 'type': 'requestMotion', 'description': 'Raise the right front leg.',
            'sessionId': 'fixture', 'bodyLease': {'bodyId': 'robot', 'executionId': 'execution', 'generation': 1}}
        self.adapter.receipts.receive(self.action, self.adapter._feedback(self.action['id'], 'accepted', 'accepted'))

    async def asyncTearDown(self):
        await self.bridge.close()
        self.adapter.receipts.close()

    async def dispatched(self):
        task = asyncio.create_task(self.adapter.handle_action(self.action))
        for _ in range(100):
            if self.gateway.sent:
                return task
            await asyncio.sleep(.001)
        self.fail(f'description did not reach the body-owned executor: {task.result() if task.done() else self.bridge.status()}')

    async def test_description_and_actual_completion_cross_the_bridge(self):
        task = await self.dispatched()
        self.assertFalse(task.done(), 'Submission is not physical completion')
        self.assertEqual(self.generated[0]['request'], self.action['description'])
        self.assertEqual(len(self.gateway.sent[0][0][1]), 12)
        row = self.adapter.receipts.action(self.action['id'])
        wire = json.loads(row['wire'])
        self.assertEqual(wire['jobId'], self.action['id'])
        self.gateway.motion_done.set()
        result = await task
        self.assertEqual(result['type'], 'completed')
        self.assertEqual(result['data']['motionSystem'], 'freestyle')
        self.assertEqual(result['data']['actionResults'][0]['t'], 'done')
        self.assertEqual(result['data']['interpretationBody'][-1], self.gateway.seq)
        replay = await self.adapter._resume_action_receipt(row)
        self.assertEqual(replay["type"], result["type"])
        self.assertEqual(replay["data"], result["data"])
        self.assertEqual(len(self.generated), 1, 'Reconnect follows the job instead of generating again')

    async def test_cancellation_uses_original_job_after_selection_changes(self):
        task = await self.dispatched()
        self.gateway.motion_systems['robot'] = 'library'
        self.adapter._send_feedback = AsyncMock(side_effect=lambda value: value)
        self.adapter._send_observation = AsyncMock()
        await self.adapter._cancel_action({'actionId': self.action['id'], 'cancellationId': 'cancel',
            'bodyLease': self.action['bodyLease']})
        result = await task
        self.assertEqual(result['type'], 'cancelled')
        self.assertIn('stop', self.gateway.sent)
        self.assertEqual(len(self.generated), 1)

    async def test_old_cancellation_does_not_stop_replacement_motion(self):
        original = await self.dispatched()
        replacement = await self.bridge.submit('robot', 'Lower the leg.', True)
        old_result = await self.bridge.cancel(self.action['id'])
        self.assertEqual(old_result['state'], 'superseded')
        self.assertNotIn('stop', self.gateway.sent)
        self.gateway.motion_done.set()
        self.assertEqual((await self.bridge.result(replacement['job_id']))['state'], 'completed')
        self.assertEqual((await original)['type'], 'cancelled')

    async def test_gateway_restart_preserves_unknown_effect_without_replaying_motion(self):
        task = await self.dispatched()
        row = self.adapter.receipts.action(self.action['id'])
        self.gateway.instance_id = 'replacement-gateway'
        result = await self.adapter._resume_action_receipt(row)
        self.assertEqual(result['type'], 'outcome_unknown')
        self.assertTrue(result['data']['executionEnded'])
        self.assertEqual(len(self.generated), 1)
        self.gateway.motion_done.set()
        await task

    async def test_failed_generation_reports_failure_not_success_or_library_fallback(self):
        async def fail(*args):
            raise RuntimeError('fixture inference failed')
        self.bridge.generate = fail
        result = await self.adapter.handle_action(self.action)
        self.assertEqual(result['type'], 'failed')
        self.assertIn('fixture inference failed', result['message'])
        self.assertFalse(self.gateway.sent)

    async def test_capabilities_follow_the_configured_system(self):
        freestyle = self.adapter._observation()['capabilities']
        self.assertIn('requestMotion', freestyle['actions'])
        self.assertNotIn('robotCommand', freestyle['actions'])
        self.assertNotIn('robotMotionPlan', freestyle['actions'])
        self.gateway.motion_systems['robot'] = 'library'
        library = self.adapter._observation()['capabilities']
        self.assertIn('robotCommand', library['actions'])
        self.assertNotIn('requestMotion', library['actions'])

    async def test_selection_change_publishes_current_capabilities_only_for_selected_robot(self):
        observations = []
        async def send():
            observations.append(self.adapter._observation())
        self.adapter._send_observation = send
        await self.adapter._handle_gateway_event({'t': 'motion_system', 'robot_id': 'another'})
        self.assertEqual(observations, [])
        await self.adapter._handle_gateway_event({'t': 'motion_system', 'robot_id': 'robot'})
        self.assertIn('requestMotion', observations[-1]['capabilities']['actions'])
        self.gateway.motion_systems['robot'] = 'library'
        await self.adapter._handle_gateway_event({'t': 'motion_system', 'robot_id': 'robot'})
        self.assertIn('robotCommand', observations[-1]['capabilities']['actions'])
        self.assertNotIn('requestMotion', observations[-1]['capabilities']['actions'])

    async def test_lost_receipt_preserves_unknown_physical_outcome_and_ends_job(self):
        async def lost(*args, **kwargs):
            await self.gateway.motion_done.wait()
            raise RuntimeError('body connection lost')
        self.gateway.wait_terminal = lost
        task = await self.dispatched()
        self.gateway.motion_done.set()
        result = await task
        self.assertEqual(result['type'], 'outcome_unknown')
        self.assertTrue(result['data']['executionEnded'])
        self.assertEqual(result['data']['actionResults'], [])

    async def test_recorded_body_rejection_is_a_known_failure(self):
        async def rejected(seq, **kwargs):
            return {'t': 'err', 'seq': seq, 'error': 'fixture rejection'}
        self.gateway.wait_terminal = rejected
        result = await self.adapter.handle_action(self.action)
        self.assertEqual(result['type'], 'failed')
        self.assertEqual(result['data']['actionResults'][0]['t'], 'err')

    async def test_cancel_before_generation_starts_returns_terminal_job(self):
        job = await self.bridge.submit('robot', 'raise leg', True)
        result = await self.bridge.cancel(job['job_id'])
        self.assertEqual(result['state'], 'superseded')
        self.assertFalse(self.gateway.sent)
