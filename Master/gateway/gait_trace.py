"""Download P4 device-time gait events and reconstruct observed joint tracking.

No movement commands or settings writes. Trace stop stops recording only.
"""
from __future__ import annotations
import bisect
import json
import time
import urllib.parse
from pathlib import Path


class TraceCapture:
    def __init__(self, client, robot: str, output: Path):
        self.client = client
        self.path = '/api/robot/servo-feedback?'+urllib.parse.urlencode({'robot_id': robot})
        self.output = output
        self.session = self.boot_id = None
        self.after = 0
        self.lost = 0
        self.batches = []

    def pull(self, operation='trace_read') -> bool:
        payload = {'op': operation, 'after': self.after}
        if self.session is not None:
            payload.update(session=self.session, boot_id=self.boot_id)
        requested = time.monotonic()
        with self.client.request(self.path, payload) as response:
            lines = [json.loads(line) for line in response if line.strip()]
        batch = {'request_monotonic_s': requested, 'received_monotonic_s': time.monotonic(), 'records': lines}
        # Preserve even an incomplete/mismatched response for diagnosis.
        with (self.output/'trace.jsonl').open('a') as stream:
            stream.write(json.dumps(batch)+'\n')
        if not lines or lines[0].get('schema') != 'gait_trace_v1' or 'next' not in lines[-1]:
            raise ValueError('Incomplete device trace batch')
        header, footer = lines[0], lines[-1]
        if self.session is not None and (header['session'], header['boot_id']) != (self.session, self.boot_id):
            raise ValueError('Device trace session or boot changed')
        if footer['next'] < self.after:
            raise ValueError('Device trace cursor moved backward')
        self.session, self.boot_id = header['session'], header['boot_id']
        self.after = footer['next'];self.lost += footer['lost'];self.batches.append(batch)
        return footer['more']

    def stop(self):
        more = self.pull('trace_stop')
        while more:
            more = self.pull()


def calibrated_pulse(points, raw):
    """Same piecewise calibration as firmware; sensor polarity is independent."""
    if len(points) != 3 or any(p is None for p in points):
        return None
    ascending = points[2]['raw'] > points[0]['raw']
    middle = raw <= points[1]['raw'] if ascending else raw >= points[1]['raw']
    a, b = points[0:2] if middle else points[1:3]
    if a['raw'] == b['raw']:
        return None
    return a['pulse_us']+(raw-a['raw'])*(b['pulse_us']-a['pulse_us'])/(b['raw']-a['raw'])


def reconstruct(batches: list[dict], feedback: dict) -> tuple[list[dict], dict]:
    """Join by device time, never by HTTP receipt or planned foot contact.

    A sequence gap splits the timeline: no target is carried across lost events.
    Calibration changes remain raw until the matching calibration is supplied.
    """
    from .gait_trials import JOINT_NAMES, feedback_summary
    events = {}
    incomplete = 0
    lost = 0
    for batch in batches:
        records = batch['records']
        if not records or records[0].get('schema') != 'gait_trace_v1':
            incomplete += 1;continue
        header = records[0]
        if 'next' not in records[-1]:
            incomplete += 1
        else:
            lost += records[-1]['lost']
        for event in records[1:]:
            if 'sequence' in event:
                key = (header['boot_id'], header['session'], event['sequence'])
                events[key] = event
    groups, current, last_key = [], [], None
    for key in sorted(events):
        if last_key is not None and (key[:2] != last_key[:2] or key[2] != last_key[2]+1):
            groups.append(current);current = []
        current.append((key, events[key]));last_key = key
    if current:
        groups.append(current)
    rows, unmatched, revision_mismatch = [], 0, 0
    sample_count = output_count = 0
    for segment, group in enumerate(groups):
        outputs = sorted(((e['time_us'], key[2], e) for key, e in group if e['kind'] == 'output'))
        times = [x[0] for x in outputs]
        output_count += len(outputs)
        for key, event in group:
            if event['kind'] != 'sample':
                continue
            sample_count += 1
            same_revision = event['revision'] == feedback.get('revision')
            if not same_revision:
                revision_mismatch += 1
            imu = event['imu']
            for joint in feedback.get('joints', []):
                j, c, out = joint['id'], joint['channel'], joint['output']
                stamp = event['sampled_us'][c]
                index = bisect.bisect_right(times, stamp)-1
                target = outputs[index][2] if index >= 0 else None
                if target is None:
                    unmatched += 1
                valid = bool(same_revision and joint.get('calibrated') and event['valid_mask'] & (1 << c))
                raw = calibrated_pulse(joint['points'], event['raw'][c]) if valid else None
                filtered = calibrated_pulse(joint['points'], event['filtered_raw'][c]) if valid else None
                neighbor = calibrated_pulse(joint['points'], event['filtered_raw'][c]+1) if valid else None
                command = target['pulses_us'][out] if target and target['armed'] and out >= 0 else None
                imu_valid = imu.get('available') and imu.get('fresh')
                row = {'segment': segment, 'boot_id': key[0], 'session': key[1], 'sequence': key[2],
                       'revision': event['revision'], 'scan': event['scan'], 'joint_id': j, 'joint': JOINT_NAMES[j],
                       'channel': c, 'output': out, 'valid': valid and filtered is not None,
                       'sampled_us': stamp, 'command_time_us': target['time_us'] if target else None,
                       'command_us': command, 'raw_us': raw, 'filtered_us': filtered,
                       'velocity_us_s': (neighbor-filtered)*event['velocity_raw_s'][c] if neighbor is not None else None,
                       'observed_error_us': command-filtered if command and filtered is not None else None,
                       'imu_timestamp_us': imu['timestamp_us'] if imu_valid else None,
                       'imu_offset_us': imu['timestamp_us']-stamp if imu_valid else None,
                       'imu_startup': imu.get('startup'), 'imu_recovering': imu.get('recovering'),
                       'planned_phase': event['motion']['phase'], 'walking': event['motion']['walking'],
                       'motion_observed_us': event['time_us'],
                       'command_sequence': event['motion']['command_sequence']}
                for label, field in (('q', 'orientation_wxyz'), ('gyro', 'angular_rate_rad_s')):
                    for i, value in enumerate(imu.get(field, [])):
                        row[f'imu_{label}{i}'] = value if imu_valid else None
                rows.append(row)
    summary = feedback_summary(rows)
    summary.update(output_events=output_count, sample_events=sample_count,
                   reported_lost_records=lost, incomplete_batches=incomplete,
                   samples_with_different_calibration=revision_mismatch, rows_without_preceding_target=unmatched,
                   target_sample_alignment='Preceding software output publication by device time; not a physical PWM-edge timestamp',
                   imu_alignment='Device-local IMU snapshot with original timestamp and per-channel signed offsets')
    return rows, summary
