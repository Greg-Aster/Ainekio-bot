import io
import json
import tempfile
import unittest
from pathlib import Path
from gateway.gait_trace import TraceCapture, reconstruct
from gateway.gait_trials import record

FEEDBACK = {'revision': 1, 'joints': [
    {'id': 0, 'channel': 4, 'output': 0, 'calibrated': True,
     'points': [{'raw': 100, 'pulse_us': 500}, {'raw': 1000, 'pulse_us': 1500}, {'raw': 2000, 'pulse_us': 2500}]},
    {'id': 1, 'channel': 5, 'output': 1, 'calibrated': True,
     'points': [{'raw': 2000, 'pulse_us': 500}, {'raw': 1000, 'pulse_us': 1500}, {'raw': 100, 'pulse_us': 2500}]}]}

def output(seq, stamp, pulse=1500):
    return {'sequence': seq, 'kind': 'output', 'time_us': stamp, 'pulses_us': [pulse]*12, 'armed': True}

def sample(seq, stamp, revision=1):
    return {'sequence': seq, 'kind': 'sample', 'time_us': stamp+10, 'sampled_us': [stamp]*16,
            'revision': revision, 'scan': seq, 'valid_mask': 0xffff,
            'raw': [1000]*16, 'filtered_raw': [1000]*16, 'velocity_raw_s': [100]*16,
            'imu': {'available': True, 'fresh': True, 'timestamp_us': stamp+2,
                    'orientation_wxyz': [1, 0, 0, 0], 'angular_rate_rad_s': [0, 0, 0]},
            'motion': {'phase': .25, 'walking': True, 'command_sequence': 7}}

def batch(events, session=1, boot=2, lost=0, more=False):
    return {'records': [{'schema': 'gait_trace_v1', 'session': session, 'boot_id': boot}]+events+
            [{'next': events[-1]['sequence'] if events else 0, 'lost': lost, 'more': more}]}

class TraceTests(unittest.TestCase):
    def test_target_matches_each_channel_time_not_scan_or_network_time(self):
        s = sample(3, 150)
        s['sampled_us'][5] = 210
        rows, summary = reconstruct([batch([output(1,100), output(2,200,1800), s])], FEEDBACK)
        self.assertEqual([r['command_us'] for r in rows], [1500,1800])
        self.assertEqual([r['command_time_us'] for r in rows], [100,200])
        self.assertEqual([r['imu_offset_us'] for r in rows], [2,-58])
        self.assertGreater(rows[0]['velocity_us_s'],0)
        self.assertLess(rows[1]['velocity_us_s'],0)
        self.assertEqual(summary['rows_without_preceding_target'],0)

    def test_lost_records_do_not_reuse_a_target_across_the_gap(self):
        a = batch([output(1,100),sample(2,150)])
        b = batch([sample(4,250)],lost=1)
        rows, summary = reconstruct([a,b,a],FEEDBACK)
        self.assertEqual(len(rows),4) # retry deduplicates sequence events
        self.assertIsNone(rows[-1]['command_us'])
        self.assertEqual(summary['reported_lost_records'],1)
        self.assertEqual(summary['segments'],2)

    def test_calibration_and_session_changes_are_not_silently_merged(self):
        rows, summary = reconstruct([batch([output(1,100),sample(2,200,2)]),
                                     batch([sample(1,300)],session=2)],FEEDBACK)
        self.assertFalse(rows[0]['valid'])
        self.assertIsNone(rows[0]['filtered_us'])
        self.assertIsNone(rows[-1]['command_us'])
        self.assertEqual(summary['samples_with_different_calibration'],1)

    def test_capture_drains_stop_and_never_sends_motion(self):
        class Fake:
            def __init__(self): self.operations=[]
            def request(self,path,payload):
                self.operations.append(payload)
                op=payload['op']
                data = batch([output(1,100)]) if op=='trace_start' else (
                    batch([sample(2,200)],more=True) if op=='trace_stop' else batch([sample(3,300)]))
                return io.BytesIO(('\n'.join(json.dumps(x) for x in data['records'])+'\n').encode())
        client=Fake()
        with tempfile.TemporaryDirectory() as temp:
            capture=TraceCapture(client,'robot',Path(temp));capture.pull('trace_start');capture.stop()
            self.assertEqual(capture.after,3)
            self.assertEqual(len((Path(temp)/'trace.jsonl').read_text().splitlines()),3)
        self.assertEqual([x['op'] for x in client.operations],['trace_start','trace_stop','trace_read'])
        self.assertEqual(client.operations[1]['session'],1)
        self.assertEqual(client.operations[1]['boot_id'],2)

    def test_incomplete_batch_keeps_previous_cursor(self):
        class Fake:
            def request(self,*args): return io.BytesIO(b'{"schema":"gait_trace_v1","session":1,"boot_id":2}\n')
        with tempfile.TemporaryDirectory() as temp:
            capture=TraceCapture(Fake(),'robot',Path(temp))
            with self.assertRaisesRegex(ValueError,'Incomplete'): capture.pull('trace_start')
            self.assertEqual(capture.after,0)

    def test_recorder_device_mode_writes_dataset_and_stops_recording_only(self):
        class Fake:
            def __init__(self):self.operations=[];self.seq=0
            def json(self,path,payload=None):
                if path.startswith('/api/robot/servo-feedback'):return FEEDBACK
                if path=='/api/status':return {'robots':{'robot':{'status':{}}}}
                return {}
            def request(self,path,payload):
                self.operations.append(payload['op']);self.seq+=1
                e=output(self.seq,100) if self.seq==1 else sample(self.seq,100+self.seq*20000)
                return io.BytesIO(('\n'.join(json.dumps(x) for x in batch([e])['records'])+'\n').encode())
        client=Fake()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'trial'
            result=record(client,'robot',p,.12,camera_enabled=False,device_trace=True)
            self.assertGreater(result['feedback']['sample_events'],0)
            self.assertIn('command_time_us',(p/'joints.csv').read_text())
            self.assertEqual(result['errors'],[])
        self.assertEqual(client.operations[-1],'trace_stop')
        self.assertNotIn('intent',client.operations)

if __name__=='__main__':unittest.main()
