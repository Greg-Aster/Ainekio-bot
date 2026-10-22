import io
import math
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gateway.gait_trials import imu_summary, record, feedback_rows, feedback_summary, capture_snapshot


def feedback_sample(stamp=100000, boot=1, revision=1, valid=True):
    imu = {'boot_id': boot, 'timestamp_us': stamp-1000, 'available': True, 'fresh': True,
           'orientation_wxyz': [1, 0, 0, 0], 'angular_rate_rad_s': [0, 0, 0]}
    return {'request_s': .1, 'received_s': .12, 'imu_before': imu, 'imu_after': imu,
            'feedback': {'enabled': True, 'initialized': True, 'revision': revision,
                         'scan': 5, 'device_us': stamp+2000,
                         'channels': [{'channel': 4, 'valid': valid, 'sampled_us': stamp,
                                       'spread': 10, 'at_adc_rail': False}],
                         'joints': [{'id': 0, 'channel': 4, 'output': 0, 'calibrated': True,
                                     'command_us': 1800, 'measured_us': 1700,
                                     'filtered_us': 1720, 'velocity_us_s': 200}]}}


class GaitTrialTests(unittest.TestCase):
    def test_trace_stops_while_camera_download_is_still_pending(self):
        stopped = threading.Event()
        camera_started = threading.Event()
        camera_saw_stop = []

        class Trace:
            def __init__(self, *args): self.batches = []
            def pull(self, *args): return False
            def stop(self): stopped.set()

        class Client:
            def json(self, path, payload=None):
                if path == '/api/intent':
                    assert camera_started.wait(2)
                    return {'seq': 7}
                if path == '/api/status':
                    return {'robots': {'test': {'last_terminal': {'t': 'done', 'seq': 7}}}}
                return {}

            def request(self, path):
                camera_started.set()
                camera_saw_stop.append(stopped.wait(2))
                result = io.BytesIO(b'jpeg')
                result.status = 200
                result.headers = {'X-Ainekio-Camera-Counter': '1'}
                return result

        with tempfile.TemporaryDirectory() as root, \
                patch('gateway.gait_trace.TraceCapture', Trace), \
                patch('gateway.gait_trace.reconstruct', return_value=([], {})):
            result = record(Client(), 'test', Path(root)/'trial', 10,
                            'intent', {'name': 'walk'}, device_trace=True, until_done=True)
        self.assertTrue(camera_saw_stop)
        self.assertTrue(all(camera_saw_stop))
        self.assertEqual(result['errors'], [])
        self.assertFalse(result['motion_stopped_by_recorder'])

    def test_snapshot_capture_uses_own_sequence_without_motion_commands(self):
        class Client:
            def __init__(self, origin='31'): self.writes=[]; self.origin=origin
            def json(self, path, payload=None):
                if payload is not None:
                    self.writes.append((path,payload));return {'seq':31}
                return {'robots': {'robot': {'connected':True,'epoch':4}}}
            def request(self,path,**kwargs):
                assert 'epoch=4' in path and 'request_seq=31' in path
                result=io.BytesIO(b'jpeg');result.status=200
                result.headers={'X-Ainekio-Camera-Counter':'9','X-Ainekio-Camera-Origin':'request',
                    'X-Ainekio-Camera-Origin-Id':self.origin,'X-Ainekio-Camera-Epoch':'4'}
                return result
        with tempfile.TemporaryDirectory() as root:
            client=Client();result=capture_snapshot(client,'robot',Path(root)/'capture')
            self.assertEqual(result['request_sequence'],31)
            self.assertEqual(client.writes,[('/api/snap',{'robot_id':'robot'})])
            with self.assertRaisesRegex(ValueError,'does not identify'):
                capture_snapshot(Client('32'),'robot',Path(root)/'wrong')

    def test_record_until_done_matches_own_command_without_sending_stop(self):
        class Dashboard:
            def __init__(self):
                self.writes = []
                self.reads = 0

            def json(self, path, payload=None):
                if payload is not None:
                    self.writes.append((path, payload))
                    return {'ok': True, 'seq': 7}
                self.reads += 1
                return {'robots': {'test': {'status': {}, 'last_terminal': {
                    't': 'done', 'seq': 9 if self.reads == 1 else 7}}}}

        client = Dashboard()
        with tempfile.TemporaryDirectory() as root:
            result = record(client, 'test', Path(root)/'trial', 10,
                            'intent', {'name': 'walk'}, camera_enabled=False, until_done=True)
        self.assertEqual(client.reads, 2)
        self.assertEqual(len(client.writes), 1)
        self.assertTrue(result['recording_ended_on_receipt'])
        self.assertFalse(result['motion_stopped_by_recorder'])
        self.assertEqual(result['terminal_receipt']['seq'], 7)

    def test_imu_counter_rates_include_stale_snapshots_and_separate_boots(self):
        def reading(boot, stamp, accepted, gaps, fresh=True):
            return {'imu': {'boot_id': boot, 'timestamp_us': stamp,
                            'available': True, 'fresh': fresh, 'startup': True,
                            'accepted_samples': accepted, 'rejected_samples': 0,
                            'gap_restarts': gaps}}
        a = reading(1, 1000000, 200, 10)
        b = reading(1, 3000000, 600, 12, fresh=False)
        c = reading(2, 100000, 10, 0)
        result = imu_summary([a, a, b, c])
        self.assertEqual(result['imu_startup_observations'], 2)
        first, second = result['imu_acquisition']
        self.assertEqual(first['accepted_rate_hz'], 200)
        self.assertEqual(first['gap_restarts_delta'], 2)
        self.assertIsNone(second['accepted_rate_hz'])
        bad = imu_summary([a, reading(1, 3000000, 100, 0)])['imu_acquisition'][0]
        self.assertFalse(bad['counter_sequence_monotonic'])
        self.assertIsNone(bad['accepted_rate_hz'])

    def test_feedback_deduplication_and_explicit_timing_offsets(self):
        a, b = feedback_sample(), feedback_sample(140000)
        rows = feedback_rows([a, a, b], [{'imu': a['imu_before']}, {'imu': b['imu_before']}])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['imu_offset_us'], -1000)
        self.assertEqual(rows[0]['sample_age_at_response_us'], 2000)
        self.assertEqual(rows[0]['observed_error_us'], 80)
        result = feedback_summary(rows)
        self.assertEqual(result['joints'][0]['maximum_sample_gap_us'], 40000)
        self.assertEqual(result['joints'][0]['observed_error_rms_us'], 80)
        self.assertFalse(result['contact_measured'])

    def test_feedback_reboots_and_calibration_changes_are_separate_segments(self):
        records = [feedback_sample(100000), feedback_sample(10000, boot=2),
                   feedback_sample(10000, boot=2, revision=2)]
        rows = feedback_rows(records, [{'imu': r['imu_before']} for r in records])
        self.assertEqual([r['segment'] for r in rows], [0, 1, 2])
        self.assertEqual(feedback_summary(rows)['segments'], 3)
        self.assertIsNone(feedback_summary(rows)['joints'][0]['maximum_sample_gap_us'])

    def test_ambiguous_boot_and_invalid_channels_do_not_invent_measurements(self):
        a = feedback_sample()
        a['imu_after'] = {**a['imu_after'], 'boot_id': 2}
        b = feedback_sample(120000, valid=False)
        rows = feedback_rows([a, b], [{'imu': a['imu_before']}])
        self.assertIsNone(rows[0]['imu_timestamp_us'])
        self.assertIsNone(rows[0]['boot_id_inferred'])
        self.assertIsNone(rows[1]['filtered_us'])
        self.assertIsNone(rows[1]['observed_error_us'])
        # A cached pre-reboot status cannot establish a new feedback boot.
        c = feedback_sample(10000)
        c['imu_before'] = c['imu_after'] = a['imu_before']
        self.assertIsNone(feedback_rows([c], [{'imu': a['imu_before']}])[0]['boot_id_inferred'])

    def test_passive_feedback_recording_only_reads_settings(self):
        class FakeDashboard:
            def __init__(self):
                self.operations = []
                self.count = 0

            def json(self, path, payload=None):
                self.operations.append((path, payload))
                if path.startswith('/api/robot/servo-feedback'):
                    self.count += 1
                    return feedback_sample(100000+self.count*20000)['feedback']
                if path == '/api/status':
                    return {'robots': {'test': {'status': {'imu': feedback_sample()['imu_before']}}}}
                return {}

        client = FakeDashboard()
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)/'trial'
            result = record(client, 'test', output, .08, feedback=True, camera_enabled=False)
            self.assertGreater(result['feedback_responses'], 0)
            self.assertIn('observed_error_us', (output/'joints.csv').read_text())
            self.assertTrue((output/'metadata.json').exists())
            self.assertTrue((output/'feedback.jsonl').exists())
        self.assertTrue(all(payload is None or payload.get('op') == 'get' for _, payload in client.operations))
        self.assertFalse(result['motion_stopped_by_recorder'])

    def test_distinct_fresh_device_samples_and_no_invented_distance(self):
        def sample(stamp, pitch, fresh=True):
            r = math.radians(pitch)/2
            return {'imu': {'boot_id': 1, 'timestamp_us': stamp, 'available': True,
                            'fresh': fresh, 'orientation_wxyz': [math.cos(r), 0, math.sin(r), 0],
                            'angular_rate_rad_s': [0, 1, 0],
                            'acceleration_m_s2': [0, 0, 9.81]}}
        result = imu_summary([sample(1, 0), sample(1, 0), sample(2, 10), sample(3, 90, False)])
        self.assertEqual(result['unique_fresh_imu_samples'], 2)
        self.assertAlmostEqual(result['pitch_span_deg'], 10)
        self.assertIsNone(result['distance_m'])
        self.assertIsNone(result['electrical_energy_j'])

    def test_missing_motion_samples_remain_visible_despite_fresh_flag(self):
        rows = [{'imu': {'boot_id': boot, 'timestamp_us': stamp,
                         'available': True, 'fresh': True}}
                for boot, stamp in [(1, 1000000), (1, 1100000),
                                    (1, 3100000), (2, 1000), (2, 101000)]]
        result = imu_summary(rows)
        self.assertEqual(result['maximum_imu_sample_gap_s'], 2)
        self.assertEqual(result['device_boots'], 2)

    def test_record_preserves_receipt_and_does_not_send_stop(self):
        class FakeDashboard:
            def __init__(self):
                self.writes = []
                self.counter = 0

            def json(self, path, payload=None):
                if payload is not None:
                    self.writes.append((path, payload))
                    return {'ok': True, 'seq': 7}
                return {'robots': {'test': {'connected': True, 'epoch': 1,
                                           'status': {}, 'last_terminal': {'t': 'done', 'seq': 7}}}}

            def request(self, path):
                time.sleep(.01)
                self.counter += 1
                result = io.BytesIO(b'jpeg-fixture')
                result.status = 200
                result.headers = {'X-Ainekio-Camera-Counter': str(self.counter)}
                return result

        client = FakeDashboard()
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)/'trial'
            result = record(client, 'test', output, .12, 'motion-plan', {'frames': [[40, [0]*12]], 'end': 'hold'})
            self.assertEqual(result['terminal_receipt'], {'t': 'done', 'seq': 7})
            self.assertGreater(result['camera_frames'], 0)
            self.assertTrue((output/'telemetry.jsonl').exists())
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.writes[0][0], '/api/motion-plan')
        self.assertEqual(client.writes[0][1]['robot_id'], 'test')
        self.assertFalse(result['motion_stopped_by_recorder'])


if __name__ == '__main__':
    unittest.main()
