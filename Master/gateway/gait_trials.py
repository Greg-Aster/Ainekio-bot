"""Record supervised gait trials through the existing authenticated dashboard.

Recording duration only controls this recorder; it never stops robot motion.
Commands, when supplied, are sent once through their existing owner endpoint.
Camera motion is not a metric distance measurement without scene calibration.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def imu_summary(records: list[dict]) -> dict:
    """Count distinct device samples; repeated dashboard polls are not samples."""
    samples = {}
    for record in records:
        imu = record.get('imu') or {}
        if imu.get('available') and imu.get('fresh') and 'timestamp_us' in imu:
            samples[(imu.get('boot_id'), imu['timestamp_us'])] = imu
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

    def request(self, path: str, payload=None):
        headers = {'Cookie': 'ainekio_dashboard_session='+self.cookie}
        data = None
        if payload is not None:
            headers.update({'X-Ainekio-CSRF': self.csrf, 'Content-Type': 'application/json'})
            data = json.dumps(payload).encode()
        return urllib.request.urlopen(urllib.request.Request(self.base+path, data=data, headers=headers), timeout=10)

    def json(self, path: str, payload=None):
        with self.request(path, payload) as response:
            return json.load(response)


def record(client: Dashboard, robot: str, output: Path, seconds: float,
           command: str | None = None, payload: dict | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    finished = threading.Event()
    start = time.monotonic()
    records, frames, errors = [], [], []
    submitted = None

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
                               'request_s': requested, 'received_s': received})
            except (OSError, ValueError, KeyError) as exc:
                errors.append({'source': 'camera', 'at_s': time.monotonic()-start,
                               'error': str(exc)})
                finished.wait(.1)

    thread = threading.Thread(target=camera)
    thread.start()
    try:
        if command:
            sent = time.monotonic()-start
            submitted = {'at_s': sent, 'endpoint': command, 'payload': payload,
                         'response': client.json('/api/'+command, {**(payload or {}), 'robot_id': robot})}
        with (output/'telemetry.jsonl').open('w') as stream:
            while time.monotonic()-start < seconds:
                requested = time.monotonic()-start
                try:
                    entry = client.json('/api/status').get('robots', {}).get(robot, {})
                    status = entry.get('status') or {}
                    row = {'request_s': requested, 'received_s': time.monotonic()-start,
                           'connected': entry.get('connected', False), 'epoch': entry.get('epoch'),
                           'heartbeat_age_ms': entry.get('heartbeat_age_ms'),
                           'body_clock': entry.get('body_clock'), 'imu': status.get('imu'),
                           'balance': status.get('balance'), 'gait': status.get('gait_cadence'),
                           'status': status, 'last_terminal': entry.get('last_terminal'),
                           'body_command': entry.get('body_command'),
                           'pending_sequences': entry.get('pending_sequences')}
                    records.append(row)
                    stream.write(json.dumps(row)+'\n')
                    stream.flush()
                except (OSError, ValueError) as exc:
                    errors.append({'source': 'status', 'at_s': requested, 'error': str(exc)})
                finished.wait(.05)
    finally:
        finished.set()
        thread.join()
        seq = ((submitted or {}).get('response') or {}).get('seq')
        receipts = [r['last_terminal'] for r in records
                    if seq is not None and (r.get('last_terminal') or {}).get('seq') == seq]
        summary = {**imu_summary(records), 'requested_recording_s': seconds,
                   'status_records': len(records), 'camera_frames': len(frames),
                   'maximum_camera_receipt_gap_s': max(
                       (b['received_s']-a['received_s'] for a, b in zip(frames, frames[1:])),
                       default=None),
                   'submitted': submitted, 'terminal_receipt': receipts[-1] if receipts else None,
                   'errors': errors, 'motion_stopped_by_recorder': False}
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
    args = p.parse_args()
    payload = json.loads(args.payload.read_text()) if args.payload else None
    print(json.dumps(record(Dashboard(args.base, args.session_file), args.robot,
                            args.output, args.seconds, args.command, payload), indent=2))


if __name__ == '__main__':
    main()
