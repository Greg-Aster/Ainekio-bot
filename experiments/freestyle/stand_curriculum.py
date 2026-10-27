"""Complete measured-target Stand programs from the production native geometry.

No serving imports, keyword dispatch or physical-success labels. Geometric
coordinates identify posture landmarks, never elapsed-time advancement.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

from .challenge import digest, read_rows, write_rows
from .curriculum import example
from .ending_curriculum import final_pose
from .recordings import read_records
from .runtime import JOINTS
from .face_contract import face_tool
from .motion_space import TOOLS, INSTRUCTIONS

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'Slave/software/models/v2-12servo'
P4 = ROOT / 'Slave/firmware/esp32p4-wifi6/main'
PYTHON = '/home/greggles/ComfyUI/venv/bin/python'


def native_export(output, database):
    output.mkdir(parents=True, exist_ok=True)
    records = list(read_records(database))
    record = next(r for r in reversed(records)
                  if r['payload'].get('result', {}).get('t') == 'calibration_status'
                  and len(r['payload']['result'].get('joints', [])) == 12)
    calibration = record['payload']['result']
    (output / 'calibration-evidence.json').write_text(json.dumps(record, indent=2) + '\n')
    mapping = ''.join(f"{j['channel']} {int(j['invert'])} {j['home_us']} {j['home_cd']} {j['us_per_degree']}\n"
                      for j in sorted(calibration['joints'], key=lambda j: j['id']))
    (output / 'mapping.txt').write_text(mapping)
    build = output / 'native-build'
    subprocess.run(['cmake', '-S', str(MODEL), '-B', str(build),
                    '-DPython3_EXECUTABLE=' + PYTHON, '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--target', 'ainekio_v2_motion', '-j', '4'], check=True)
    executable = output / 'stand-geometry'
    subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(MODEL / 'include'), '-I', str(ROOT / 'Slave/software/core/include'),
                    '-I', str(P4), str(Path(__file__).with_name('stand_geometry.c')),
                    str(P4 / 'joint_calibration.c'), str(build / 'libainekio_v2_motion.a'),
                    str(build / 'core/libainekio_core.a'), '-lm', '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], input=mapping, text=True, capture_output=True, check=True)
    (output / 'native-cases.jsonl').write_text(result.stdout)
    sources = [MODEL / 'posture.c', MODEL / 'walk_kinematics.c', MODEL / 'geometry.json',
               P4 / 'joint_calibration.c', Path(__file__).with_name('stand_geometry.c')]
    (output / 'native-manifest.json').write_text(json.dumps({
        'source_hashes': {str(p.relative_to(ROOT)): digest(p) for p in sources},
        'calibration_evidence_id': record['id'], 'calibration_time_ns': record['time_ns'],
        'executable_sha256': digest(executable), 'native_cases_sha256': digest(output / 'native-cases.jsonl'),
        'contact_qualification': 'modeled support plane, not measured foot contact',
    }, indent=2) + '\n')


def quaternion(euler):
    r, p, y = (a / 2 for a in euler)
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy]


def sensor(pose, timestamp):
    q = quaternion(pose['euler_rad']);w, x, y, z = q
    return {'available': True, 'fresh': True, 'startup': False, 'calibration_applied': True,
            'frame': 'body_nominal', 'timestamp_us': timestamp, 'orientation_wxyz': q,
            'acceleration_m_s2': [2*(x*z-w*y)*9.80665, 2*(w*x+y*z)*9.80665,
                                  (1-2*(x*x+y*y))*9.80665],
            'angular_rate_rad_s': [0, 0, 0]}


def observation(measured, commanded, calibration, timestamp):
    joints = {}
    for j, m in zip(JOINTS, sorted(calibration['joints'], key=lambda x: x['id'])):
        i = m['id'];home = m['home_cd'] / 100
        angle = measured['model_deg'][i];target = round(commanded['model_deg'][i], 2)
        pulse = m['home_us'] + (-1 if m['invert'] else 1) * (target-home) * m['us_per_degree']
        pulse = math.floor(pulse+.5)
        command_angle = home + (-1 if m['invert'] else 1) * (pulse-m['home_us']) / m['us_per_degree']
        joints[j] = {'model_deg': round(angle, 5), 'commanded_model_deg': command_angle,
                     'home_deg': home, 'command_us': pulse, 'velocity_deg_s': 0,
                     'calibrated': True, 'in_calibrated_range': True}
    return {'model': 'v2-12servo', 'epoch': 1, 'joints': joints,
            'imu': sensor(measured, timestamp), 'expected_up': [0, 0, 1],
            'feedback': {'enabled': True, 'device_us': timestamp, 'stalled_joints': 0, 'no_progress_ms': 0},
            'joint_speed_limit_deg_s': 180,
            'action': None}


def validate_case(case):
    reasons = []
    if not case['valid'] or len(case['stages']) != 17:
        reasons.append('incomplete_native_path')
    if not case['start_mapping']['in_travel']:
        reasons.append('initial_pose_outside_installed_travel')
    if case['fit_delta_deg'] > 1e-6:
        reasons.append('native_mapping_altered_requested_geometry')
    if not case.get('all_targets_in_travel', False):
        reasons.append('target_outside_installed_travel')
    clearance = []
    for stage in case['stages']:
        if stage['phase'] in ('lift', 'place'):
            leg = next(l for l in range(4) if stage['moving_joints'] & (7 << (3*l)))
            base = max(case['start']['sole_height_mm'][leg], case['high_stand']['sole_height_mm'][leg])
            clearance.append(stage['arrived']['sole_height_mm'][leg] - base)
    if clearance and min(clearance) < 7.98:
        reasons.append('missing_requested_8mm_clearance')
    return {'accepted': not reasons, 'reasons': reasons,
            'minimum_compiled_clearance_mm': min(clearance, default=None),
            'fit_delta_deg': case['fit_delta_deg'],
            'initial_in_travel': case['start_mapping']['in_travel']}


def pose_call(pose):
    return final_pose([round(v, 2) for v in pose['model_deg']])


def program_rows(cases, calibration):
    for case in cases:
        if not validate_case(case)['accepted']:
            continue
        split = ('stand-test' if case['order'] == 3 else
                 'stand-evaluation' if case['order'] == 2 and case['start_pose'] == 'lower5' else 'train')
        program = [pose_call(stage['target']) for stage in case['stages']]
        program.append(pose_call(case['nominal_stand']))
        obs = observation(case['start'], case['start'], calibration, 3000000)
        yield example('Stand up.', obs, program, 'measured_stand_program',
            split=split, episode_id=case['case'],
            observation_origin='synthetic_native_geometry_and_installed_mapping',
            teacher='complete native lift/place/lower targets and standing endpoint',
            qualification_basis='native_geometry_only_not_physical_success',
            expected_final_model_deg=case['nominal_stand']['model_deg'])


def build(geometry, base, output, overlays=()):
    output.mkdir(parents=True, exist_ok=False)
    native = read_rows(geometry / 'native-cases.jsonl')
    cases = [row for row in native if 'case' in row]
    calibration = json.loads((geometry / 'calibration-evidence.json').read_text())['payload']['result']
    write_rows(output / 'geometry-audit.jsonl', [{'case':row['case'], **validate_case(row)} for row in cases])
    rows = list(program_rows(cases, calibration))
    for source in (base, *overlays):
        rows.extend(read_rows(source / 'train.jsonl'))
    manifest = {'generator_sha256':digest(Path(__file__)), 'physical_trials':0, 'splits':{}}
    for split in ('train', 'stand-evaluation', 'stand-test'):
        selected = [row for row in rows if row.get('split', 'train') == split]
        write_rows(output / (split+'.jsonl'), selected)
        manifest['splits'][split] = len(selected)
    for split in ('evaluation', 'test', 'regression-evaluation', 'recovery-probe'):
        source = base / (split+'.jsonl')
        if source.exists():
            (output / source.name).write_bytes(source.read_bytes())
    (output/'tools.json').write_text(json.dumps([*TOOLS, face_tool()])+'\n')
    system=INSTRUCTIONS+' Tools: '+json.dumps([*TOOLS, face_tool()])+'\n'
    system += ('Unless explicitly asked for a different ending, finish gestures by acquiring Stand from measured servo positions and gyro observations. '
               'Lift a foot clear before translating it, place it, then lower it. Rise slightly above nominal standing height and settle level. '
               'Infer geometry from shaft angles and attitude without claiming measured ground contact. Preserve requested gesture phases and holds; '
               'Explicit numeric poses, return-to-start and keep-raised endings override the Stand default. '
               'Release servo outputs only when explicitly requested, including after a requested rest; never substitute release for a motion target. '
               'Coordinate requested expressions using face calls without adding motion pauses.\n')
    (output/'system.txt').write_text(system)
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--overlay', type=Path, action='append', default=[])
    args = parser.parse_args()
    if args.database:
        native_export(args.geometry, args.database)
    if args.output:
        print(json.dumps(build(args.geometry, args.base, args.output, args.overlay)))
