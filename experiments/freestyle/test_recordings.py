import asyncio
from pathlib import Path
import tempfile
import unittest

from experiments.freestyle.recordings import Recorder, read_records, corrected_rows
from experiments.freestyle.bridge import Bridge
from experiments.freestyle.test_program import FakeGateway, FakeTransport


class RecordingTests(unittest.TestCase):
    def test_receipts_do_not_misattribute_telemetry_or_getters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'evidence.sqlite'
            recorder = Recorder(path)
            recorder.command({'t':'motion_plan','robot_id':'r','epoch':2,'seq':10,'frames':[[1,[100]*12]]})
            recorder.command({'t':'calibration','op':'get','robot_id':'r','epoch':2,'seq':11})
            recorder.event({'t':'imu','robot_id':'r','epoch':1,'imu':{'old':True}})
            recorder.event({'t':'imu','robot_id':'r','epoch':2,'imu':{'sample':1}})
            recorder.diagnostic({'event':'command_result','command_type':'calibration','t':'done','robot_id':'r','epoch':2,'seq':11})
            recorder.event({'t':'servo_feedback','robot_id':'r','epoch':2,'data':{'sample':2}})
            recorder.diagnostic({'event':'command_result','command_type':'motion_plan','t':'done','robot_id':'r','epoch':2,'seq':10})
            recorder.diagnostic({'event':'command_result','command_type':'robot_settings','t':'done',
                                 'robot_id':'r','epoch':2,'seq':12,'wifi_password':'test-secret'})
            recorder.event({'t':'imu','robot_id':'r','epoch':2,'imu':{'idle':True}})
            recorder.close()
            rows = list(read_records(path))
            measured = [r for r in rows if r['payload'].get('t') in ('imu','servo_feedback')]
            self.assertEqual([r['sequence'] for r in measured],[10,10])
            self.assertEqual(len(rows),6)
            selected = list(read_records(path, kinds=('body_command',)))
            self.assertEqual(selected, [r for r in rows if r['kind'] == 'body_command'])
            self.assertEqual(list(read_records(path, kinds=())), [])
            self.assertEqual(list(read_records(path, 'absent-job', kinds=('body_command',))), [])
            self.assertFalse(any('wifi_password' in str(r['payload']) for r in rows))
            self.assertEqual(recorder.status()['failed'],0)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_write_failure_is_visible_and_does_not_block_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder(directory)  # A directory cannot be an SQLite file.
            recorder.record('attempt', {'request':'wave'})
            recorder.close()
            self.assertIsNotNone(recorder.status()['error'])


class RecordedBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_correction_executes_exactly_and_exports_only_after_operator_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'evidence.sqlite'
            program = [{'name':'move','arguments':{'joint':'front_right_shoulder',
                'angle_deg':20,'reference':'current','speed_pct':50}}]
            recorder = Recorder(path)
            recorder.record('generation_requested', {'generation_index':0, 'execute':True,
                'request':{'request':'wave', 'observation':{}, 'history':[]}}, robot_id='robot', job_id='original')
            review_id = recorder.record('review', {'generation_index':0, 'outcome':'partial',
                'corrected_program':program, 'training_status':'awaiting_physical_trial'},
                robot_id='robot', job_id='original')
            recorder.close()
            self.assertEqual(list(corrected_rows(path)), [])
            recorder = Recorder(path)
            async def generate(*args):
                self.fail('A correction test must execute the saved program without model generation')
            bridge = Bridge(FakeGateway(), FakeTransport(), generate, recorder=recorder)
            self.assertEqual(await bridge.corrections('other-robot'), [])
            with self.assertRaises(ValueError):
                await bridge.test_correction('other-robot', review_id)
            result = await bridge.test_correction('robot', review_id)
            identifier = result['job_id']
            await bridge.tasks[identifier]
            self.assertEqual(bridge.jobs[identifier]['state'], 'completed')
            self.assertEqual(bridge.jobs[identifier]['programs'][0]['program'], program)
            self.assertEqual(bridge.gateway.sent[0][-1][1][9], 3000)
            await asyncio.to_thread(recorder.pending.join)
            self.assertEqual(list(corrected_rows(path)), [], 'Receipts alone must not qualify a correction')
            bridge.review('robot', identifier, 'partial', 'Too brief')
            await asyncio.to_thread(recorder.pending.join)
            self.assertEqual(list(corrected_rows(path)), [])
            bridge.review('robot', identifier, 'success', 'Observed the intended wave and return')
            await bridge.close()
            await asyncio.to_thread(recorder.close)
            rows = list(corrected_rows(path))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]['physical_qualification'])
            self.assertEqual(rows[0]['execution_source']['review_id'], review_id)
            self.assertEqual(rows[0]['answers'], program)

    async def test_reviews_preserve_failures_and_only_export_executed_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'evidence.sqlite'
            recorder = Recorder(path)
            async def generate(*args):
                return {'program':[{'name':'move','arguments':{'joint':'front_right_shoulder',
                    'angle_deg':20,'reference':'current','speed_pct':50}}], 'generator':{'hash':'test'}}
            bridge = Bridge(FakeGateway(),FakeTransport(),generate,recorder=recorder)
            ids=[]
            for execute,outcome in [(False,'success'),(True,'incorrect'),(True,'success')]:
                job = await bridge.submit('robot','wave',execute)
                identifier=job['job_id']; ids.append(identifier)
                await bridge.tasks[identifier]
                bridge.review('robot',identifier,outcome,'Observed by operator')
            with self.assertRaises(ValueError):
                bridge.review('other-robot',ids[-1],'success')
            await bridge.close()
            await asyncio.to_thread(recorder.close)
            rows = list(corrected_rows(path))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['job_id'],ids[-1])
            self.assertTrue(rows[0]['physical_qualification'])
            failed = list(read_records(path,ids[1]))
            self.assertTrue(any(r['kind']=='command_receipt' for r in failed))
            self.assertTrue(any(r['kind']=='operation_completed' for r in failed))
            self.assertEqual(next(r for r in failed if r['kind']=='review')['payload']['outcome'],'incorrect')

    async def test_failed_generation_preserves_request_and_raw_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'evidence.sqlite'
            recorder=Recorder(path)
            async def generate(*args):
                error=ValueError('incomplete')
                error.evidence={'content':'[{broken'}
                raise error
            bridge=Bridge(FakeGateway(),FakeTransport(),generate,recorder=recorder)
            result=await bridge.submit('robot','wave',True)
            await bridge.tasks[result['job_id']]
            await bridge.close()
            await asyncio.to_thread(recorder.close)
            rows=list(read_records(path))
            self.assertEqual(next(r for r in rows if r['kind']=='job_error')['payload']['evidence']['content'],'[{broken')
            self.assertTrue(any(r['kind']=='generation_requested' for r in rows))
            self.assertEqual(list(corrected_rows(path)),[])

    async def test_configuration_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            bridge=Bridge(FakeGateway(),FakeTransport(),settings_path=path)
            await bridge.configure('robot','http://example',True)
            await bridge.close()
            restored=Bridge(FakeGateway(),FakeTransport(),settings_path=path)
            self.assertEqual(restored.settings['robot'],{'endpoint':'http://example','recover_events':True})
            await restored.close()
