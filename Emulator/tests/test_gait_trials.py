import io
import math
import tempfile
import time
import unittest
from pathlib import Path

from gateway.gait_trials import imu_summary, record


class GaitTrialTests(unittest.TestCase):
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
