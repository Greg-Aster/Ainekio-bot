"""Record supervised gait trials through the existing authenticated dashboard.

Recording duration only controls this recorder; it never stops robot motion.
Commands, when supplied, are sent once through their existing owner endpoint.
Camera motion is not a metric distance measurement without scene calibration.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


JOINT_NAMES = [f'{leg}_{joint}' for leg in ('rear_left', 'rear_right', 'front_left', 'front_right')
               for joint in ('shoulder', 'carrier', 'crank')]


def feedback_rows(records: list[dict], statuses: list[dict]) -> list[dict]:
    """Keep per-channel device times; nearest IMU is explicitly not simultaneous.

    The current feedback API has no boot ID or target-write timestamp. Infer a
    boot only when bracketing status agrees, and retain host timing and segments
    rather than merging a reset/recalibration into one continuous trajectory.
    """
    imus = {}
    for record in statuses:
        imu = record.get('imu') or {}
        if imu.get('available') and imu.get('fresh') and 'timestamp_us' in imu:
            imus[(imu.get('boot_id'), imu['timestamp_us'])] = imu
    rows, seen = [], set()
    segment, previous_device, previous_revision, previous_boot = 0, None, None, None
    for record in records:
        data = record['feedback']
        device = data.get('device_us')
        revision = data.get('revision')
        before, after = record.get('imu_before') or {}, record.get('imu_after') or {}
        boot = before.get('boot_id') if before.get('boot_id') == after.get('boot_id') else None
        if device is not None and before.get('timestamp_us', 0) > device:
            boot = None  # Cached pre-reboot status must not label the new clock.
        if previous_device is not None and (device is None or device < previous_device or
                revision != previous_revision or boot != previous_boot):
            segment += 1
        previous_device, previous_revision, previous_boot = device, revision, boot
        channels = {c['channel']: c for c in data.get('channels', [])}
        candidates = [v for (b, _), v in imus.items() if boot is not None and b == boot]
        for joint in data.get('joints', []):
            channel = channels.get(joint.get('channel'), {})
            stamp = channel.get('sampled_us')
            key = (segment, joint['id'], stamp)
            if stamp is not None and key in seen:
                continue
            seen.add(key)
            valid = bool(data.get('enabled') and data.get('initialized') and
                         joint.get('calibrated') and channel.get('valid') and stamp is not None)
            nearest = min(candidates, key=lambda i: abs(i['timestamp_us']-stamp)) if valid and candidates else None
            name = JOINT_NAMES[joint['id']] if 0 <= joint['id'] < len(JOINT_NAMES) else str(joint['id'])
            command = joint.get('command_us')
            measured = joint.get('filtered_us') if valid else None
            row = {'segment': segment, 'boot_id_inferred': boot, 'revision': revision,
                   'scan': data.get('scan'), 'joint_id': joint['id'], 'joint': name,
                   'channel': joint.get('channel'), 'output': joint.get('output'),
                   'valid': valid, 'sampled_us': stamp, 'response_device_us': device,
                   'request_s': record['request_s'], 'received_s': record['received_s'],
                   'command_us': command, 'raw_us': joint.get('measured_us') if valid else None,
                   'filtered_us': measured, 'velocity_us_s': joint.get('velocity_us_s') if valid else None,
                   'observed_error_us': command-measured if command and measured is not None else None,
                   'adc_spread': channel.get('spread'), 'at_adc_rail': channel.get('at_adc_rail'),
                   'in_calibrated_range': joint.get('in_calibrated_range'),
                   'sample_age_at_response_us': device-stamp if device is not None and stamp is not None else None,
                   'imu_timestamp_us': nearest['timestamp_us'] if nearest else None,
                   'imu_offset_us': nearest['timestamp_us']-stamp if nearest else None}
            for label, field in (('q', 'orientation_wxyz'), ('gyro', 'angular_rate_rad_s')):
                for index, value in enumerate((nearest or {}).get(field, [])):
                    row[f'imu_{label}{index}'] = value
            rows.append(row)
    return rows


def feedback_summary(rows: list[dict]) -> dict:
    joints = []
    for joint_id in sorted({r['joint_id'] for r in rows}):
        selected = [r for r in rows if r['joint_id'] == joint_id]
        valid = [r for r in selected if r['valid']]
        errors = [r['observed_error_us'] for r in valid if r['observed_error_us'] is not None]
        gaps = []
        for segment in {r['segment'] for r in valid}:
            stamps = sorted({r['sampled_us'] for r in valid if r['segment'] == segment})
            gaps.extend(b-a for a, b in zip(stamps, stamps[1:]))
        def span(key):
            values = [r[key] for r in valid if r[key] is not None and (key != 'command_us' or r[key] > 0)]
            return max(values)-min(values) if values else None
        joints.append({'joint_id': joint_id, 'joint': selected[0]['joint'],
                       'valid_samples': len(valid), 'invalid_samples': len(selected)-len(valid),
                       'command_span_us': span('command_us'), 'measured_span_us': span('filtered_us'),
                       'raw_measured_span_us': span('raw_us'),
                       'observed_error_rms_us': math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None,
                       'observed_error_peak_us': max(map(abs, errors)) if errors else None,
                       'maximum_sample_gap_us': max(gaps) if gaps else None})
    offsets = [abs(r['imu_offset_us']) for r in rows if r['imu_offset_us'] is not None]
    return {'joints': joints, 'segments': len({r['segment'] for r in rows}),
            'maximum_nearest_imu_offset_us': max(offsets) if offsets else None,
            'unpaired_rows': sum(r['imu_timestamp_us'] is None for r in rows),
            'target_sample_alignment': 'HTTP target snapshot; target write time unavailable',
            'imu_alignment': 'Nearest device timestamp, boot inferred from bracketing status; offsets retained',
            'contact_measured': False, 'torque_measured': False}


def imu_summary(records: list[dict]) -> dict:
    """Count distinct device samples; repeated dashboard polls are not samples."""
    samples = {}
    counters = {}
    for record in records:
        imu = record.get('imu') or {}
        # Counters describe acquisition, including snapshots that arrived stale.
        # Dashboard sample spacing alone cannot establish the sensor sample rate.
        if imu.get('boot_id') is not None and 'timestamp_us' in imu and all(
                isinstance(imu.get(k), int) for k in
                ('accepted_samples', 'rejected_samples', 'gap_restarts')):
            counters[(imu['boot_id'], imu['timestamp_us'])] = imu
        if imu.get('available') and imu.get('fresh') and 'timestamp_us' in imu:
            samples[(imu.get('boot_id'), imu['timestamp_us'])] = imu
    acquisition = []
    for boot in sorted({k[0] for k in counters}):
        observed = [counters[k] for k in sorted(counters) if k[0] == boot]
        first, last = observed[0], observed[-1]
        elapsed = (last['timestamp_us']-first['timestamp_us'])/1e6
        changes = {k: last[k]-first[k] for k in
                   ('accepted_samples', 'rejected_samples', 'gap_restarts')}
        monotonic = all(b[k] >= a[k] for a, b in zip(observed, observed[1:]) for k in changes)
        acquisition.append({'boot_id': boot, 'observed_seconds': elapsed,
                            'counter_sequence_monotonic': monotonic,
                            'accepted_samples_delta': changes['accepted_samples'] if monotonic else None,
                            'rejected_samples_delta': changes['rejected_samples'] if monotonic else None,
                            'gap_restarts_delta': changes['gap_restarts'] if monotonic else None,
                            'accepted_rate_hz': changes['accepted_samples']/elapsed
                            if elapsed > 0 and monotonic else None})
    gaps = []
    for boot in {key[0] for key in samples}:
        stamps = sorted(key[1] for key in samples if key[0] == boot)
        gaps.extend((b-a)/1e6 for a, b in zip(stamps, stamps[1:]))
    angles, rates, acceleration = [], [], []
    for imu in samples.values():
        q = imu.get('orientation_wxyz')
        if q and len(q) == 4 and all(math.isfinite(v) for v in q):
            norm = math.sqrt(sum(v*v for v in q))
            if norm:
                w, x, y, z = (v/norm for v in q)
                angles.append([math.degrees(math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y))),
                               math.degrees(math.asin(max(-1., min(1., 2*(w*y-z*x)))))])
        for field, target in [('angular_rate_rad_s', rates), ('acceleration_m_s2', acceleration)]:
            v = imu.get(field)
            if v and len(v) == 3 and all(math.isfinite(x) for x in v):
                target.append(math.sqrt(sum(x*x for x in v)))
    return {'unique_fresh_imu_samples': len(samples),
            'device_boots': len({k[0] for k in samples}),
            'imu_acquisition': acquisition,
            'imu_startup_observations': sum(bool(s.get('startup')) for s in samples.values()),
            'maximum_imu_sample_gap_s': max(gaps) if gaps else None,
            'roll_span_deg': max(a[0] for a in angles)-min(a[0] for a in angles) if angles else None,
            'pitch_span_deg': max(a[1] for a in angles)-min(a[1] for a in angles) if angles else None,
            'peak_sampled_angular_rate_rad_s': max(rates) if rates else None,
            'peak_sampled_acceleration_norm_m_s2': max(acceleration) if acceleration else None,
            'distance_m': None,
            'electrical_energy_j': None}


class Dashboard:
    def __init__(self, base: str, session_file: Path):
        self.base = base.rstrip('/')
        self.cookie = session_file.read_text().strip()
        self.csrf = self.json('/api/session')['csrf']

    def request(self, path: str, payload=None, *, timeout=10):
        headers = {'Cookie': 'ainekio_dashboard_session='+self.cookie}
        data = None
        if payload is not None:
            headers.update({'X-Ainekio-CSRF': self.csrf, 'Content-Type': 'application/json'})
            data = json.dumps(payload).encode()
        return urllib.request.urlopen(urllib.request.Request(self.base+path, data=data, headers=headers), timeout=timeout)

    def json(self, path: str, payload=None):
        with self.request(path, payload) as response:
            return json.load(response)


def capture_snapshot(client: Dashboard, robot: str, output: Path) -> dict:
    """Capture this request's still, not an unrelated preview or speech photo.

    Bracketing status is retained as evidence, not called exposure-synchronized
    IMU. This helper sends only Snap; it cannot move or stop the robot.
    """
    output.mkdir(parents=True, exist_ok=False)
    before = client.json('/api/status').get('robots', {}).get(robot, {})
    (output/'before.json').write_text(json.dumps(before, indent=2)+'\n')
    epoch = before.get('epoch')
    receipt = client.json('/api/snap', {'robot_id': robot})
    sequence = receipt['seq']
    (output/'request.json').write_text(json.dumps(receipt, indent=2)+'\n')
    query = urllib.parse.urlencode({'robot_id': robot, 'epoch': epoch, 'request_seq': sequence})
    while True:
        with client.request('/api/camera/frame?'+query, timeout=15) as response:
            if response.status != 204:
                if (response.headers.get('X-Ainekio-Camera-Origin') != 'request' or
                    response.headers.get('X-Ainekio-Camera-Origin-Id') != str(sequence) or
                    response.headers.get('X-Ainekio-Camera-Epoch') != str(epoch)):
                    raise ValueError('Camera response does not identify the requested snapshot')
                data = response.read()
                counter = int(response.headers['X-Ainekio-Camera-Counter'])
                break
        current = client.json('/api/status').get('robots', {}).get(robot, {})
        terminal = current.get('last_terminal') or {}
        if not current.get('connected') or current.get('epoch') != epoch:
            raise ValueError('Robot disconnected during snapshot capture')
        if terminal.get('seq') == sequence and terminal.get('t') != 'ack':
            raise ValueError('Snapshot ended without its matching image: '+json.dumps(terminal))
    (output/'image.jpg').write_bytes(data)
    after = client.json('/api/status').get('robots', {}).get(robot, {})
    (output/'after.json').write_text(json.dumps(after, indent=2)+'\n')
    result = {'robot_id': robot, 'epoch': epoch, 'request_sequence': sequence,
              'counter': counter, 'file': 'image.jpg', 'bytes': len(data),
              'imu_alignment': 'Bracketing status; camera exposure timestamp unavailable'}
    (output/'capture.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def record(client: Dashboard, robot: str, output: Path, seconds: float,
           command: str | None = None, payload: dict | None = None,
           feedback: bool = False, camera_enabled: bool = True,
           device_trace: bool = False, until_done: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    finished = threading.Event()
    start = time.monotonic()
    records, frames, errors = [], [], []
    shaft_records = []
    submitted = None
    ended_on_receipt = False
    trace = None

    def status_row():
        requested = time.monotonic()-start
        entry = client.json('/api/status').get('robots', {}).get(robot, {})
        status = entry.get('status') or {}
        return {'request_s': requested, 'received_s': time.monotonic()-start,
                'connected': entry.get('connected', False), 'epoch': entry.get('epoch'),
                'heartbeat_age_ms': entry.get('heartbeat_age_ms'),
                'body_clock': entry.get('body_clock'), 'imu': status.get('imu'),
                'balance': status.get('balance'), 'gait': status.get('gait_cadence'),
                'status': status, 'last_terminal': entry.get('last_terminal'),
                'body_command': entry.get('body_command'),
                'locomotion_measurement': entry.get('locomotion_measurement'),
                'pending_sequences': entry.get('pending_sequences')}

    def trace_download():
        try:
            while not finished.is_set():
                try:
                    more = trace.pull()
                except (OSError, ValueError, KeyError) as exc:
                    errors.append({'source': 'trace', 'at_s': time.monotonic()-start, 'error': str(exc)})
                    more = False
                if not more:
                    finished.wait(.1)
        finally:
            # This thread owns the cursor. Stop acquisition and drain it without
            # waiting for an unrelated camera response to finish downloading.
            try:
                trace.stop()
            except (OSError, ValueError, KeyError) as exc:
                errors.append({'source': 'trace_stop', 'error': str(exc)})

    def shaft_feedback():
        query = urllib.parse.urlencode({'robot_id': robot})
        with (output/'feedback.jsonl').open('w') as stream:
            while not finished.is_set():
                requested = time.monotonic()-start
                try:
                    def imu_status():
                        return (client.json('/api/status').get('robots', {}).get(robot, {}).get('status') or {}).get('imu')
                    before = imu_status()
                    data = client.json('/api/robot/servo-feedback?'+query)
                    received = time.monotonic()-start
                    after = imu_status()
                    row = {'request_s': requested, 'received_s': received, 'feedback': data,
                           'imu_before': before, 'imu_after': after}
                    shaft_records.append(row)
                    stream.write(json.dumps(row)+'\n');stream.flush()
                except (OSError, ValueError) as exc:
                    errors.append({'source': 'feedback', 'at_s': requested, 'error': str(exc)})
                finished.wait(.02)

    def camera():
        counter = None
        while not finished.is_set():
            query = {'robot_id': robot}
            if counter is not None:
                query['after'] = str(counter)
            requested = time.monotonic()-start
            try:
                with client.request('/api/camera/frame?'+urllib.parse.urlencode(query)) as response:
                    if response.status == 204:
                        continue
                    data = response.read()
                    counter = int(response.headers['X-Ainekio-Camera-Counter'])
                received = time.monotonic()-start
                name = f'frame-{len(frames):05d}.jpg'
                (output/name).write_bytes(data)
                frames.append({'file': name, 'counter': counter,
                               'request_s': requested, 'received_s': received,
                               'epoch': response.headers.get('X-Ainekio-Camera-Epoch'),
                               'origin': response.headers.get('X-Ainekio-Camera-Origin'),
                               'origin_id': response.headers.get('X-Ainekio-Camera-Origin-Id')})
            except (OSError, ValueError, KeyError) as exc:
                errors.append({'source': 'camera', 'at_s': time.monotonic()-start,
                               'error': str(exc)})
                finished.wait(.1)

    threads = ([threading.Thread(target=camera)] if camera_enabled else [])
    if feedback or device_trace:
        # Read-only provenance through existing owners. No settings are changed.
        metadata = {'robot_id': robot, 'capture_started_unix_s': time.time()}
        query = urllib.parse.urlencode({'robot_id': robot})
        for name, path, operation in (
                ('firmware', '/api/robot/firmware?'+query, None),
                ('calibration', '/api/calibration/body', {'op': 'get', 'robot_id': robot}),
                ('learning', '/api/robot/gait-learning?'+query, None),
                ('balance', '/api/balance', {'op': 'get', 'robot_id': robot})):
            try:
                metadata[name] = client.json(path, operation)
            except (OSError, ValueError) as exc:
                errors.append({'source': name, 'error': str(exc)})
        if device_trace:
            from .gait_trace import TraceCapture
            metadata['feedback'] = client.json('/api/robot/servo-feedback?'+query)
            trace = TraceCapture(client, robot, output)
            trace.pull('trace_start')
            threads.append(threading.Thread(target=trace_download))
        (output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
        if feedback and not device_trace:
            threads.append(threading.Thread(target=shaft_feedback))
    start = time.monotonic()
    for thread in threads:
        thread.start()
    try:
        if command:
            try:
                records.append(status_row())
            except (OSError, ValueError) as exc:
                errors.append({'source': 'initial_status', 'error': str(exc)})
            sent = time.monotonic()-start
            submitted = {'at_s': sent, 'endpoint': command, 'payload': payload,
                         'response': client.json('/api/'+command, {**(payload or {}), 'robot_id': robot})}
        with (output/'telemetry.jsonl').open('w') as stream:
            for row in records:
                stream.write(json.dumps(row)+'\n')
            while time.monotonic()-start < seconds:
                requested = time.monotonic()-start
                try:
                    row = status_row()
                    records.append(row)
                    stream.write(json.dumps(row)+'\n')
                    stream.flush()
                    terminal = row.get('last_terminal') or {}
                    if (until_done and submitted and submitted['response'].get('seq') is not None and
                            terminal.get('seq') == submitted['response'].get('seq')):
                        ended_on_receipt = True
                        break
                except (OSError, ValueError) as exc:
                    errors.append({'source': 'status', 'at_s': requested, 'error': str(exc)})
                finished.wait(.05)
    finally:
        finished.set()
        for thread in threads:
            thread.join()
        seq = ((submitted or {}).get('response') or {}).get('seq')
        receipts = [r['last_terminal'] for r in records
                    if seq is not None and (r.get('last_terminal') or {}).get('seq') == seq]
        from .gait_assessment import visual_summary, support_summary
        summary = {**imu_summary(records), **visual_summary(records), 'requested_recording_s': seconds,
                   'status_records': len(records), 'camera_frames': len(frames),
                   'maximum_camera_receipt_gap_s': max(
                       (b['received_s']-a['received_s'] for a, b in zip(frames, frames[1:])),
                       default=None),
                   'submitted': submitted, 'terminal_receipt': receipts[-1] if receipts else None,
                   'errors': errors, 'motion_stopped_by_recorder': False,
                   'recording_ended_on_receipt': ended_on_receipt}
        if device_trace:
            from .gait_trace import reconstruct
            rows, summary['feedback'] = reconstruct(trace.batches, metadata['feedback'])
            summary['support'] = support_summary(trace.batches)
        elif feedback:
            rows = feedback_rows(shaft_records, records + [
                {'imu': r.get(key)} for r in shaft_records for key in ('imu_before', 'imu_after')])
            summary['feedback'] = feedback_summary(rows)
            summary['feedback_responses'] = len(shaft_records)
        if feedback or device_trace:
            with (output/'joints.csv').open('w', newline='') as stream:
                if rows:
                    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
                    writer.writeheader();writer.writerows(rows)
        (output/'frames.json').write_text(json.dumps(frames, indent=2)+'\n')
        (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default='http://127.0.0.1:8791')
    p.add_argument('--session-file', type=Path, required=True)
    p.add_argument('--robot', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=12)
    p.add_argument('--command', choices=['intent', 'motion-plan'])
    p.add_argument('--payload', type=Path)
    p.add_argument('--feedback', action='store_true', help='Record fourth-wire measurements and timing quality')
    p.add_argument('--no-camera', action='store_true', help='Record telemetry without requesting camera frames')
    p.add_argument('--device-trace', action='store_true', help='Record local P4 events in batches (0.8.72+)')
    p.add_argument('--until-done', action='store_true', help='Finish recording when the submitted command completes; never stops robot motion')
    args = p.parse_args()
    payload = json.loads(args.payload.read_text()) if args.payload else None
    print(json.dumps(record(Dashboard(args.base, args.session_file), args.robot,
                            args.output, args.seconds, args.command, payload,
                            args.feedback, not args.no_camera, args.device_trace, args.until_done), indent=2))


if __name__ == '__main__':
    main()
