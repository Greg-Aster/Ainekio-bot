"""Broad V2 twelve-servo Freestyle curriculum for natural-language generalization.

Every example is offline-authored and verified through the exact runtime
ProgramEncoding schema, geometric compiler (compile_motion + four-bar IK/FK),
and V2 servo operating margins before export. Geometric compilation does not
establish physical contact, balance, or hardware qualification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from pathlib import Path

from jsonschema import Draft202012Validator

from .compact_wire import ProgramEncoding, model_query
from .face_contract import face_tool
from .generator import argument_schema
from .kinematics import foot_positions
from .motion_space import TOOLS
from .observations import enrich, joint_state
from .program import compile_motion
from .runtime import JOINTS, compact

CONTRACT = [*TOOLS, face_tool()]
ENCODING = ProgramEncoding(CONTRACT)
VALIDATOR = Draft202012Validator(ENCODING.schema(argument_schema))

STAND_ANGLES = [0.0, 0.94, -21.25] * 4
SIT_ANGLES = [0.0, -21.8, -10.64, 0.0, -21.8, -10.64, 0.0, 13.74, -65.79, 0.0, 13.74, -65.79]
CROUCH_ANGLES = [0.0, -21.5, -22.0, 0.0, -21.5, -22.0, 0.0, -21.5, -22.0, 0.0, -21.5, -22.0]
REST_ANGLES = [0.0, -21.8, 19.98] * 4
DEEP_SQUAT_ANGLES = [0.0, -14.0, 26.0, 0.0, -14.0, 26.0, 0.0, -12.0, 22.0, 0.0, -12.0, 22.0]
WIDE_STANCE_ANGLES = [-14.0, 8.0, -24.0] * 4

STARTING_POSES = {
    'stand': STAND_ANGLES,
    'sit': SIT_ANGLES,
    'crouch': CROUCH_ANGLES,
    'rest': REST_ANGLES,
}


def op(name: str, **arguments):
    if name in ('move', 'pose', 'oscillate', 'feet', 'body'):
        arguments.setdefault('taper_deg', 0)
    return {'name': name, 'arguments': arguments}


def face(expr: str):
    return op('face', expr=expr)


def hold(seconds: float):
    return op('hold', seconds=round(seconds, 2))


def stand_pose(speed_pct: int = 65, taper_deg: float = 0):
    return op('pose', joints=list(JOINTS), angles_deg=list(STAND_ANGLES),
              reference='absolute', speed_pct=speed_pct, taper_deg=taper_deg)


def leg_joints(leg: str):
    return [f'{leg}_shoulder', f'{leg}_carrier', f'{leg}_crank']


def front_joints():
    return [*leg_joints('front_left'), *leg_joints('front_right')]


def rear_joints():
    return [*leg_joints('rear_left'), *leg_joints('rear_right')]


def sit_brace_enter(speed_pct: int = 65):
    """Unloaded rear-leg step-in into seated rear brace so both front paws are free."""
    return [
        op('pose', joints=['rear_left_carrier', 'rear_left_crank'],
           angles_deg=[-8.32, -1.99], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_left_carrier', 'rear_left_crank'],
           angles_deg=[23.24, 7.15], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_right_carrier', 'rear_right_crank'],
           angles_deg=[-8.32, -1.99], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_right_carrier', 'rear_right_crank'],
           angles_deg=[23.24, 7.15], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_left_carrier', 'rear_left_crank',
                           'rear_right_carrier', 'rear_right_crank',
                           'front_left_carrier', 'front_left_crank',
                           'front_right_carrier', 'front_right_crank'],
           angles_deg=[-22.5, -12.0, -22.5, -12.0, 14.0, -64.0, 14.0, -64.0],
           reference='absolute', speed_pct=speed_pct, taper_deg=2),
    ]


def sit_brace_exit(speed_pct: int = 65):
    """Return front paws to support and step rear legs cleanly back to nominal stand."""
    return [
        op('pose', joints=front_joints(),
           angles_deg=[0.0, 14.0, -64.0, 0.0, 14.0, -64.0],
           reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_left_carrier', 'rear_left_crank',
                           'rear_right_carrier', 'rear_right_crank',
                           'front_left_carrier', 'front_left_crank',
                           'front_right_carrier', 'front_right_crank'],
           angles_deg=[23.24, 7.15, 23.24, 7.15, 0.94, -21.25, 0.94, -21.25],
           reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_left_carrier', 'rear_left_crank'],
           angles_deg=[-8.32, -1.99], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_left_carrier', 'rear_left_crank'],
           angles_deg=[0.94, -21.25], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_right_carrier', 'rear_right_crank'],
           angles_deg=[-8.32, -1.99], reference='absolute', speed_pct=speed_pct),
        op('pose', joints=['rear_right_carrier', 'rear_right_crank'],
           angles_deg=[0.94, -21.25], reference='absolute', speed_pct=speed_pct),
    ]


def weight_shift_for(leg: str, speed_pct: int = 65):
    """Shift COM onto the three supporting legs before lifting one leg, plus inverse."""
    dx = -10 if leg.startswith('front_') else 10
    dy = 10 if leg.endswith('_right') else -10
    enter = op('body', translation_mm=[dx, dy, 0], rotation_deg=[0, 0, 0],
               legs=[], foot_offsets_mm=[], speed_pct=speed_pct)
    leave = op('body', translation_mm=[-dx, -dy, 0], rotation_deg=[0, 0, 0],
               legs=[], foot_offsets_mm=[], speed_pct=speed_pct)
    return enter, leave


def foot_Waypoints(leg: str, waypoints: list[list[float]], speed_pct: int = 70, taper_deg: float = 0):
    """Relative Cartesian offsets along closed or open waypoints starting at [0,0,0]."""
    pts = [[0.0, 0.0, 0.0], *waypoints]
    return [
        op('feet', legs=[leg],
           offsets_mm=[[round(b - a, 2) for a, b in zip(p, q)]],
           speed_pct=speed_pct, taper_deg=taper_deg)
        for p, q in zip(pts, pts[1:])
        if any(abs(b - a) > 0.01 for a, b in zip(p, q))
    ]


P4_FEATURES = [
    'motion_targets_v1', 'motion_curves_v1', 'command_deadline_v1', 'body_capabilities_v1',
    'body_commands_v1', 'body_calibration_v2', 'storage_control_v1', 'walk_controls_v2',
    'walk_steering_v1', 'walk_lateral_v1', 'walk_nominal_v1', 'run_gait_v1', 'crab_gait_v1',
    'motion_speed_v1', 'joint_speed_limit_v1', 'balance_control_v1', 'balance_tuning_v1',
    'balance_feedback_v1', 'walking_feedback_v1', 'servo_feedback_v1', 'robot_settings_v1',
    'camera_profiles_v1', 'camera_adaptive_v1', 'camera_motion_exposure_v1',
    'gateway_switching_v1', 'audio_input_v1', 'face_feedback_v1',
]

POSE_SEED_OFFSET = {'stand': 101, 'sit': 211, 'crouch': 307, 'rest': 401}
JOINT_CLAMP_BOUNDS = ((-96.0, 86.5), (-22.1, 163.5), (-104.0, 75.0))


def _euler_to_wxyz(roll_deg: float, pitch_deg: float, yaw_deg: float) -> list[float]:
    cr, sr = math.cos(math.radians(roll_deg) * 0.5), math.sin(math.radians(roll_deg) * 0.5)
    cp, sp = math.cos(math.radians(pitch_deg) * 0.5), math.sin(math.radians(pitch_deg) * 0.5)
    cy, sy = math.cos(math.radians(yaw_deg) * 0.5), math.sin(math.radians(yaw_deg) * 0.5)
    return [
        round(cr * cp * cy + sr * sp * sy, 6),
        round(sr * cp * cy - cr * sp * sy, 6),
        round(cr * sp * cy + sr * cp * sy, 6),
        round(cr * cp * sy - sr * sp * cy, 6),
    ]


def synthetic_observation(pose_name: str = 'stand', seed: int = 0):
    angles = STARTING_POSES[pose_name]
    if seed <= 0:
        joints = {}
        for idx, (name, base) in enumerate(zip(JOINTS, angles)):
            val = round(base, 2)
            joints[name] = {
                'model_deg': val,
                'commanded_model_deg': val,
                'home_deg': round([0.0, -30.87, -117.68][idx % 3], 2),
                'calibrated': True,
                'in_calibrated_range': True,
                'feedback_usable': True,
                'feedback_range_deg': [-98.0, 90.0] if idx % 3 == 0 else ([-25.0, 168.0] if idx % 3 == 1 else [-108.0, 80.0]),
                'arrival_tolerance_deg': 4.5,
            }
        return {
            'model': 'v2-12servo',
            'features': ['motion_targets_v1', 'motion_curves_v1'],
            'joint_speed_limit_deg_s': 2000,
            'imu': {'available': True, 'fresh': True, 'frame': 'body_nominal',
                    'orientation_wxyz': [1.0, 0.0, 0.0, 0.0], 'angular_rate_rad_s': [0.0, 0.0, 0.0]},
            'feedback': {'enabled': True, 'stalled_joints': 0, 'waiting_joints': 0},
            'joints': joints,
        }

    rng = random.Random(seed * 2654435761 + POSE_SEED_OFFSET.get(pose_name, 0))
    p4_mode = (seed % 4 != 0)
    installed_cal = p4_mode and (rng.random() < 0.35)
    installed_ranges = (
        [-113.4, 93.6], [-35.37, 171.63], [-111.38, 95.62],
        [-103.5, 103.5], [-23.22, 183.78], [-112.28, 94.72],
        [-103.5, 103.5], [-36.27, 170.73], [-122.18, 84.82],
        [-108.0, 99.0], [-36.27, 170.73], [-124.43, 82.57],
    )
    tol = rng.choices([16.2, 9.0, 4.5], weights=[6, 2, 2])[0] if p4_mode else 4.5
    joints = {}
    for idx, (name, base) in enumerate(zip(JOINTS, angles)):
        lo_bound, hi_bound = JOINT_CLAMP_BOUNDS[idx % 3]
        base_cmd = (0.0, 0.9, -21.29)[idx % 3] if (installed_cal and pose_name == 'stand') else base
        cmd_jitter = rng.choice([-0.05, -0.02, 0.0, 0.02, 0.05]) if (p4_mode and (abs(base_cmd) > 0.01 or installed_cal)) else 0.0
        cmd = round(min(hi_bound, max(lo_bound, base_cmd + cmd_jitter)), 2)
        err_span = 1.6 if pose_name == 'stand' else 0.7
        err = rng.uniform(-err_span, err_span) if p4_mode else rng.uniform(-0.45, 0.45)
        val = round(min(hi_bound, max(lo_bound, cmd + err)), 2)
        if installed_cal:
            cal_delta = rng.choice([-0.45, 0.0, 0.0, 0.45])
            fb_range = [round(installed_ranges[idx][0] + cal_delta, 2), round(installed_ranges[idx][1] + cal_delta, 2)]
        elif p4_mode:
            base_lo = (-108.0, -33.0, -118.0)[idx % 3]
            cal_lo = round(base_lo + rng.uniform(-6.0, 6.0), 2)
            fb_range = [cal_lo, round(cal_lo + 207.0, 2)]
        else:
            fb_range = [-98.0, 90.0] if idx % 3 == 0 else ([-25.0, 168.0] if idx % 3 == 1 else [-108.0, 80.0])
        j_entry = {
            'model_deg': val,
            'commanded_model_deg': cmd,
            'home_deg': round([0.0, -30.87, -117.68][idx % 3], 2),
            'calibrated': True,
            'in_calibrated_range': True,
            'feedback_usable': True,
            'feedback_range_deg': fb_range,
            'arrival_tolerance_deg': tol,
        }
        if p4_mode:
            j_entry['filtered_model_deg'] = round(min(hi_bound, max(lo_bound, val + rng.uniform(-1.6, 1.6))), 2)
            j_entry['velocity_deg_s'] = round(rng.uniform(-11.0, 11.0), 2)
            j_entry['feedback_faults'] = []
        joints[name] = j_entry

    if not p4_mode:
        roll_deg = rng.uniform(-1.2, 1.2)
        pitch_deg = rng.uniform(-1.2, 1.2)
        return {
            'model': 'v2-12servo',
            'features': ['motion_targets_v1', 'motion_curves_v1'],
            'joint_speed_limit_deg_s': 2000,
            'imu': {'available': True, 'fresh': True, 'frame': 'body_nominal',
                    'orientation_wxyz': _euler_to_wxyz(roll_deg, pitch_deg, 0.0),
                    'angular_rate_rad_s': [round(rng.uniform(-0.008, 0.008), 6) for _ in range(3)]},
            'feedback': {'enabled': True, 'stalled_joints': 0, 'waiting_joints': 0},
            'joints': joints,
        }

    roll_deg = rng.uniform(-2.8, 2.8)
    pitch_deg = rng.uniform(-2.4, 2.4)
    yaw_deg = rng.uniform(-6.0, 6.0)
    rr, pr = math.radians(roll_deg), math.radians(pitch_deg)
    accel = [
        round(-9.81 * math.sin(pr) + rng.uniform(-0.18, 0.18), 6),
        round(9.81 * math.sin(rr) * math.cos(pr) + rng.uniform(-0.18, 0.18), 6),
        round(9.81 * math.cos(rr) * math.cos(pr) + rng.uniform(-0.12, 0.12), 6),
    ]
    feedback = {'enabled': True, 'no_progress_ms': 3000, 'waiting_joints': 0}
    if seed % 3 == 0:
        stall_bit = 1 << rng.randrange(len(JOINTS))
        age_us = rng.randint(1_500_000, 180_000_000)
        dev_us = age_us + rng.randint(10_000_000, 90_000_000)
        feedback['stalled_joints'] = stall_bit
        feedback['device_us'] = dev_us
        feedback['stall_clock_us'] = dev_us - age_us
    else:
        feedback['stalled_joints'] = 0

    return {
        'model': 'v2-12servo',
        'expected_up': None,
        'joint_speed_limit_deg_s': 2000,
        'features': list(P4_FEATURES),
        'trajectory_progress': None,
        'imu': {
            'available': True,
            'fresh': True,
            'age_us': rng.randint(850, 4200),
            'frame': 'body_nominal',
            'orientation_wxyz': _euler_to_wxyz(roll_deg, pitch_deg, yaw_deg),
            'angular_rate_rad_s': [round(rng.uniform(-0.015, 0.015), 6) for _ in range(3)],
            'acceleration_m_s2': accel,
            'calibration_applied': True,
            'gyro_recovery': False,
            'acceleration_recovery': False,
            'accelerometer_ignored': False,
        },
        'feedback': feedback,
        'joints': joints,
    }


def validate_program(program: list[dict], start_pose_name: str = 'stand', *, obs: dict | None = None):
    if any(action['name'] == 'release' for action in program):
        raise ValueError('Custom curriculum must not emit servo release')
    encoded = ENCODING.encode(program)
    VALIDATOR.validate(encoded)
    check_obs_list = [synthetic_observation(start_pose_name, seed=0)]
    if obs is not None:
        check_obs_list.append(obs)
    for check_obs in check_obs_list:
        planned = None
        for index, action in enumerate(program):
            name = action['name']
            if name in ('move', 'pose', 'oscillate', 'feet', 'body'):
                compiled = compile_motion(action, check_obs, planned)
                planned = compiled['end']
                end_frame = [round(planned[j] * 100) for j in JOINTS]
                raw_frames = [frame for _, frame in compiled['frames']]
                check_frames = [*raw_frames, end_frame]
                for frame in check_frames:
                    for leg_idx in range(4):
                        sh = frame[3 * leg_idx] / 100.0
                        ca = frame[3 * leg_idx + 1] / 100.0
                        cr = frame[3 * leg_idx + 2] / 100.0
                        if not (-98.5 <= sh <= 89.0 and -22.5 <= ca <= 166.0 and -106.5 <= cr <= 77.5):
                            raise ValueError(
                                f'Step {index} ({name}) out of V2 bounds on leg {leg_idx}: '
                                f'sh={sh:.2f}, ca={ca:.2f}, cr={cr:.2f}'
                            )
                fk_frames = [end_frame]
                if raw_frames:
                    fk_frames.append(raw_frames[0])
                    fk_frames.append(raw_frames[len(raw_frames) // 2])
                for frame in fk_frames:
                    feet = foot_positions({j: q / 100.0 for j, q in zip(JOINTS, frame)})
                    if not all(math.isfinite(v) for pt in feet.values() for v in pt):
                        raise ValueError(f'Nonfinite FK at step {index}')
            elif name in ('stand', 'gait'):
                planned = dict(zip(JOINTS, STAND_ANGLES))
    return encoded


def make_entry(request: str, program: list[dict], curriculum_family: str, *,
               with_observation: str | None = None, seed: int = 0, split: str = 'train'):
    start_pose = with_observation or 'stand'
    full_program = list(program)
    if start_pose in ('sit', 'crouch', 'rest'):
        first_motion = next((a for a in full_program if a['name'] not in ('face', 'hold')), None)
        if first_motion and first_motion['name'] not in ('stand', 'stop'):
            insert_at = 1 if full_program and full_program[0]['name'] == 'face' else 0
            full_program.insert(insert_at, stand_pose(speed_pct=65))
    obs = synthetic_observation(with_observation, seed=max(1, seed)) if with_observation else None
    answers = validate_program(full_program, start_pose, obs=obs)
    if obs is not None:
        query_obj = model_query(enrich({
            'request': request, 'observation': obs, 'event': None, 'history': []
        }), ENCODING)
    else:
        query_obj = {'request': request}
    query = compact(query_obj)
    digest = hashlib.sha256(compact([curriculum_family, query, answers]).encode()).hexdigest()
    return {
        'id': digest[:16],
        'family': f'freestyle_{curriculum_family}',
        'curriculum_family': curriculum_family,
        'title': request,
        'query': query,
        'answers': answers,
        'split': split,
        'source_id': f'freestyle-curriculum:{curriculum_family}:{digest[:16]}',
        'source_hash': digest,
        'synthetic': True,
        'physical_qualification': False,
        'qualification_basis': 'v2_four_bar_ik_fk_and_operating_bounds_verified_not_physical_trial',
        'teacher': 'V2 twelve-servo compositional Freestyle curriculum',
    }


# ---------------------------------------------------------------------------
# Pillar 1: Limb, Side, and Joint Mastery (16 families)
# ---------------------------------------------------------------------------

def prog_raise_hand(side: str = 'right', mode: str = 'standing', speed: int = 65, hold_s: float = 0.8):
    if side == 'both':
        return [
            face('excited'),
            *sit_brace_enter(speed),
            op('pose', joints=front_joints(),
               angles_deg=[-52.0, 40.0, 14.0, -52.0, 40.0, 14.0],
               reference='absolute', speed_pct=speed),
            hold(hold_s),
            *sit_brace_exit(speed),
            face('stand'),
        ]
    leg = f'front_{side}'
    target_angles = [-56.0, 48.0, 18.0] if mode == 'seated' else [-52.0, 44.0, 14.0]
    return [
        face('happy'),
        *sit_brace_enter(speed),
        op('pose', joints=leg_joints(leg),
           angles_deg=target_angles, reference='absolute', speed_pct=speed),
        hold(hold_s),
        op('pose', joints=leg_joints(leg),
           angles_deg=[-26.0, 12.0, -34.0], reference='absolute', speed_pct=speed),
        *sit_brace_exit(speed),
        face('stand'),
    ]


def prog_wave_hand(side: str = 'right', cycles: int = 3, speed: int = 65, quick: bool = False):
    if side == 'both':
        return [
            face('wave'),
            *sit_brace_enter(speed),
            op('pose', joints=front_joints(),
               angles_deg=[-48.0, 38.0, 10.0, -48.0, 38.0, 10.0],
               reference='absolute', speed_pct=speed),
            *[a for _ in range(cycles) for a in (
                op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
                   angles_deg=[-72.0, -24.0], reference='absolute', speed_pct=speed),
                op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
                   angles_deg=[-24.0, -72.0], reference='absolute', speed_pct=speed),
            )],
            *sit_brace_exit(speed),
            face('stand'),
        ]
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    if quick:
        shift_in, shift_out = weight_shift_for(leg, speed)
        return [
            face('wave'),
            shift_in,
            op('feet', legs=[leg], offsets_mm=[[20, sign * 22, 58]], speed_pct=speed),
            op('oscillate', joint=f'{leg}_shoulder', amplitude_deg=22, cycles=cycles, speed_pct=speed),
            op('feet', legs=[leg], offsets_mm=[[-20, -sign * 22, -58]], speed_pct=speed),
            shift_out,
            face('stand'),
        ]
    return [
        face('wave'),
        *sit_brace_enter(speed),
        op('pose', joints=leg_joints(leg), angles_deg=[-54.0, -16.0, -38.0], reference='absolute', speed_pct=speed),
        op('pose', joints=leg_joints(leg), angles_deg=[-55.0, 46.0, 11.0], reference='absolute', speed_pct=speed),
        op('oscillate', joint=f'{leg}_shoulder', amplitude_deg=36, cycles=cycles, speed_pct=speed),
        op('pose', joints=leg_joints(leg), angles_deg=[-54.0, -16.0, -38.0], reference='absolute', speed_pct=speed),
        *sit_brace_exit(speed),
        face('stand'),
    ]


def prog_point(side: str = 'right', direction: str = 'forward', speed: int = 65):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    yaw = 8 * sign if direction == 'side' else (-6 * sign if direction == 'across' else 0)
    sh = -58.0 if direction == 'side' else (16.0 if direction == 'across' else -14.0)
    return [
        face('point'),
        *sit_brace_enter(speed),
        op('pose', joints=leg_joints(leg),
           angles_deg=[sh, 46.0, 28.0], reference='absolute', speed_pct=speed),
        *([] if yaw == 0 else [op('move', joint=f'{leg}_shoulder', angle_deg=yaw, reference='current', speed_pct=speed)]),
        hold(0.9),
        *sit_brace_exit(speed),
        face('stand'),
    ]


def prog_salute(side: str = 'right', cycles: int = 1, speed: int = 70):
    leg = f'front_{side}'
    return [
        face('listening'),
        *sit_brace_enter(speed),
        *[a for _ in range(cycles) for a in (
            op('pose', joints=leg_joints(leg),
               angles_deg=[-48.0, 48.0, 22.0], reference='absolute', speed_pct=speed),
            hold(0.65),
            op('pose', joints=leg_joints(leg),
               angles_deg=[-26.0, 12.0, -34.0], reference='absolute', speed_pct=speed),
        )],
        *sit_brace_exit(speed),
        face('stand'),
    ]


def prog_tap_paw(leg: str = 'front_right', cycles: int = 3, speed: int = 75):
    shift_in, shift_out = weight_shift_for(leg, speed)
    dx = 14 if leg.startswith('front_') else 10
    dz = 22 if leg.startswith('front_') else 16
    return [
        face('number_one' if cycles == 1 else ('number_two' if cycles == 2 else 'happy')),
        shift_in,
        *[a for _ in range(cycles) for a in (
            op('feet', legs=[leg], offsets_mm=[[dx, 0, dz]], speed_pct=speed),
            op('feet', legs=[leg], offsets_mm=[[-dx, 0, -dz]], speed_pct=min(100, speed + 10)),
        )],
        shift_out,
        face('stand'),
    ]


def prog_hand_circle(side: str = 'right', cycles: int = 2, speed: int = 75):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    pts = [[18, sign * 16, 36]]
    for i in range(1, 8 * cycles + 1):
        theta = 2 * math.pi * i / 8
        pts.append([
            round(18 + 10 * math.sin(theta), 2),
            round(sign * (16 + 10 * (1 - math.cos(theta))), 2),
            round(36 + 10 * math.sin(theta), 2),
        ])
    pts.append([0, 0, 0])
    return [
        face('curious'),
        shift_in,
        *foot_Waypoints(leg, pts, speed_pct=speed),
        shift_out,
        face('stand'),
    ]


def prog_beckon(side: str = 'right', cycles: int = 3, speed: int = 70):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    return [
        face('happy'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[26, sign * 12, 34]], speed_pct=speed),
        *[a for _ in range(cycles) for a in (
            op('feet', legs=[leg], offsets_mm=[[-16, 0, 14]], speed_pct=speed),
            op('feet', legs=[leg], offsets_mm=[[16, 0, -14]], speed_pct=speed),
        )],
        op('feet', legs=[leg], offsets_mm=[[-26, -sign * 12, -34]], speed_pct=speed),
        shift_out,
        face('stand'),
    ]


def prog_high_five(side: str = 'right', speed: int = 75):
    if side == 'both':
        return [
            face('celebrate'),
            *sit_brace_enter(speed),
            op('pose', joints=front_joints(),
               angles_deg=[-42.0, 52.0, 26.0, -42.0, 52.0, 26.0], reference='absolute', speed_pct=speed),
            hold(0.8),
            *sit_brace_exit(speed),
            face('stand'),
        ]
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    return [
        face('excited'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[24, sign * 18, 72]], speed_pct=speed),
        op('feet', legs=[leg], offsets_mm=[[8, 0, 6]], speed_pct=min(100, speed + 15)),
        hold(0.75),
        op('feet', legs=[leg], offsets_mm=[[-32, -sign * 18, -78]], speed_pct=speed),
        shift_out,
        face('stand'),
    ]


def prog_fist_bump(side: str = 'right', speed: int = 75):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    return [
        face('happy'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[14, sign * 10, 36]], speed_pct=speed),
        op('feet', legs=[leg], offsets_mm=[[20, 0, 4]], speed_pct=min(100, speed + 15)),
        hold(0.55),
        op('feet', legs=[leg], offsets_mm=[[-10, 0, 6]], speed_pct=85),
        op('feet', legs=[leg], offsets_mm=[[-24, -sign * 10, -46]], speed_pct=speed),
        shift_out,
        face('stand'),
    ]


def prog_shake_hands(side: str = 'right', cycles: int = 3, speed: int = 65):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    return [
        face('happy'),
        *sit_brace_enter(speed),
        op('pose', joints=leg_joints(leg),
           angles_deg=[-16.0, 38.0, 22.0], reference='absolute', speed_pct=speed),
        hold(0.35),
        *[a for _ in range(cycles) for a in (
            op('move', joint=f'{leg}_crank', angle_deg=12.0, reference='current', speed_pct=speed),
            op('move', joint=f'{leg}_crank', angle_deg=-12.0, reference='current', speed_pct=speed),
        )],
        *sit_brace_exit(speed),
        face('stand'),
    ]


def prog_clapping(cycles: int = 4, speed: int = 80):
    return [
        face('celebrate'),
        *sit_brace_enter(speed - 10),
        op('pose', joints=front_joints(),
           angles_deg=[-34.0, 32.0, 18.0, -34.0, 32.0, 18.0], reference='absolute', speed_pct=speed),
        *[a for _ in range(cycles) for a in (
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
               angles_deg=[18.0, 18.0], reference='absolute', speed_pct=min(100, speed + 10)),
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
               angles_deg=[-36.0, -36.0], reference='absolute', speed_pct=speed),
        )],
        *sit_brace_exit(speed - 10),
        face('stand'),
    ]


def prog_rear_kick(side: str = 'right', cycles: int = 2, speed: int = 75):
    if side == 'both_alt':
        return [
            face('excited'),
            *prog_rear_kick('right', cycles=1, speed=speed)[1:-1],
            *prog_rear_kick('left', cycles=1, speed=speed)[1:-1],
            face('stand'),
        ]
    leg = f'rear_{side}'
    shift_in, shift_out = weight_shift_for(leg, speed)
    return [
        face('excited'),
        shift_in,
        *[a for _ in range(cycles) for a in (
            op('pose', joints=leg_joints(leg), angles_deg=[-32.0, -10.0, -44.0], reference='absolute', speed_pct=min(100, speed + 10)),
            op('pose', joints=leg_joints(leg), angles_deg=[0.0, 0.94, -21.25], reference='absolute', speed_pct=speed),
        )],
        shift_out,
        face('stand'),
    ]


def prog_scratch_ear(side: str = 'right', cycles: int = 4, speed: int = 80):
    leg = f'rear_{side}'
    roll = -5 if side == 'right' else 5
    shift_in, shift_out = weight_shift_for(leg, speed - 10)
    sign = 1 if side == 'left' else -1
    return [
        face('happy'),
        shift_in,
        op('body', translation_mm=[0, 0, 0], rotation_deg=[roll, 3, 0], legs=[], foot_offsets_mm=[], speed_pct=65),
        op('feet', legs=[leg], offsets_mm=[[18, sign * 22, 46]], speed_pct=speed),
        op('oscillate', joint=f'{leg}_crank', amplitude_deg=14, cycles=cycles, speed_pct=min(100, speed + 10)),
        op('feet', legs=[leg], offsets_mm=[[-18, -sign * 22, -46]], speed_pct=speed),
        op('body', translation_mm=[0, 0, 0], rotation_deg=[-roll, -3, 0], legs=[], foot_offsets_mm=[], speed_pct=65),
        shift_out,
        face('stand'),
    ]


def prog_swat_fly(side: str = 'right', cycles: int = 3, speed: int = 85):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed - 15)
    return [
        face('curious'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[18, sign * 24, 44]], speed_pct=speed),
        *[a for _ in range(cycles) for a in (
            op('feet', legs=[leg], offsets_mm=[[6, -sign * 20, 8]], speed_pct=min(100, speed + 10)),
            op('feet', legs=[leg], offsets_mm=[[-6, sign * 20, -8]], speed_pct=speed),
        )],
        op('feet', legs=[leg], offsets_mm=[[-18, -sign * 24, -44]], speed_pct=speed - 10),
        shift_out,
        face('stand'),
    ]


def prog_cross_reach(side: str = 'right', speed: int = 65):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    return [
        face('stretch'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[22, -sign * 14, 38]], speed_pct=speed),
        hold(0.6),
        op('feet', legs=[leg], offsets_mm=[[-22, sign * 14, -38]], speed_pct=speed),
        shift_out,
        face('stand'),
    ]


# ---------------------------------------------------------------------------
# Pillar 2: Body Attitude, Gaze, Postures, and Emotional Reactions (12 families)
# ---------------------------------------------------------------------------

def prog_look(direction: str = 'up', speed: int = 55, hold_s: float = 0.8):
    if direction == 'up':
        rot = [0, -8, 0]; expr = 'curious'
    elif direction == 'down':
        rot = [0, 12, 0]; expr = 'curious'
    elif direction == 'left':
        rot = [0, 0, 12]; expr = 'turn_left_90'
    elif direction == 'right':
        rot = [0, 0, -12]; expr = 'turn_right_90'
    elif direction == 'scan':
        return [
            face('listening'),
            op('body', translation_mm=[0, 0, 4], rotation_deg=[0, -3, 12], legs=[], foot_offsets_mm=[], speed_pct=speed),
            hold(0.55),
            op('body', translation_mm=[0, 0, 0], rotation_deg=[0, 0, -24], legs=[], foot_offsets_mm=[], speed_pct=speed),
            hold(0.55),
            op('body', translation_mm=[0, 0, -4], rotation_deg=[0, 3, 12], legs=[], foot_offsets_mm=[], speed_pct=speed),
            face('stand'),
        ]
    else:
        raise ValueError(direction)
    return [
        face(expr),
        op('body', translation_mm=[0, 0, 0], rotation_deg=rot, legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=2),
        hold(hold_s),
        op('body', translation_mm=[0, 0, 0], rotation_deg=[-v for v in rot], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=2),
        face('stand'),
    ]


def prog_head_tilt(side: str = 'right', cycles: int = 1, speed: int = 55):
    roll = 8 if side == 'right' else -8
    if side == 'both':
        return [
            face('confused'),
            *[a for _ in range(cycles) for a in (
                op('body', translation_mm=[4, 0, 0], rotation_deg=[8, -3, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
                hold(0.45),
                op('body', translation_mm=[0, 0, 0], rotation_deg=[-16, 0, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
                hold(0.45),
                op('body', translation_mm=[-4, 0, 0], rotation_deg=[8, 3, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            )],
            face('stand'),
        ]
    return [
        face('curious'),
        op('body', translation_mm=[4, 0, 4], rotation_deg=[roll, -4, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=2),
        hold(0.85),
        op('body', translation_mm=[-4, 0, -4], rotation_deg=[-roll, 4, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=2),
        face('stand'),
    ]


def prog_peek_corner(side: str = 'right', speed: int = 60):
    dy = -16 if side == 'right' else 16
    yaw = -8 if side == 'right' else 8
    roll = 4 if side == 'right' else -4
    return [
        face('curious'),
        op('body', translation_mm=[6, 0, -6], rotation_deg=[0, 0, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
        op('body', translation_mm=[4, dy, 6], rotation_deg=[roll, -2, yaw], legs=[], foot_offsets_mm=[], speed_pct=speed - 10),
        hold(0.8),
        face('surprised'),
        op('body', translation_mm=[-10, -dy, 0], rotation_deg=[-roll, 2, -yaw], legs=[], foot_offsets_mm=[], speed_pct=min(100, speed + 25)),
        face('stand'),
    ]


def prog_lean_attitude(kind: str = 'forward', speed: int = 60):
    if kind == 'forward':
        t, r, expr = [16, 0, 4], [0, 5, 0], 'listening'
    elif kind == 'back':
        t, r, expr = [-22, 0, 4], [0, -6, 0], 'surprised'
    elif kind == 'side_to_side':
        return [
            face('happy'),
            op('body', translation_mm=[0, 18, 0], rotation_deg=[-5, 0, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            hold(0.4),
            op('body', translation_mm=[0, -36, 0], rotation_deg=[10, 0, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            hold(0.4),
            op('body', translation_mm=[0, 18, 0], rotation_deg=[-5, 0, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            face('stand'),
        ]
    else:
        raise ValueError(kind)
    return [
        face(expr),
        op('body', translation_mm=t, rotation_deg=r, legs=[], foot_offsets_mm=[], speed_pct=speed),
        hold(0.75),
        op('body', translation_mm=[-v for v in t], rotation_deg=[-v for v in r], legs=[], foot_offsets_mm=[], speed_pct=speed),
        face('stand'),
    ]


def prog_tiptoe_tall(speed: int = 55):
    return [
        face('excited'),
        op('body', translation_mm=[0, 0, 16], rotation_deg=[0, -2, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=3),
        hold(1.0),
        op('body', translation_mm=[0, 0, -16], rotation_deg=[0, 2, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=3),
        face('stand'),
    ]


def prog_sneak_prowl(speed: int = 35):
    prowl = [-10.0, -10.0, 12.0, -10.0, -10.0, 12.0, -10.0, -12.0, 14.0, -10.0, -12.0, 14.0]
    shoulders = ['rear_left_shoulder', 'rear_right_shoulder', 'front_left_shoulder', 'front_right_shoulder']
    return [
        face('curious'),
        op('pose', joints=list(JOINTS), angles_deg=prowl, reference='absolute', speed_pct=speed, taper_deg=2),
        op('pose', joints=shoulders, angles_deg=[-4.0, -18.0, -18.0, -4.0], reference='absolute', speed_pct=speed),
        hold(0.45),
        op('pose', joints=shoulders, angles_deg=[-18.0, -4.0, -4.0, -18.0], reference='absolute', speed_pct=speed),
        hold(0.45),
        stand_pose(speed_pct=speed + 20),
        face('stand'),
    ]


def prog_cat_cow_stretch(cycles: int = 2, speed: int = 45):
    return [
        face('stretch'),
        *[a for _ in range(cycles) for a in (
            op('body', translation_mm=[-4, 0, 10], rotation_deg=[0, 8, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=3),
            hold(0.6),
            op('body', translation_mm=[8, 0, -16], rotation_deg=[0, -12, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=3),
            hold(0.6),
            op('body', translation_mm=[-4, 0, 6], rotation_deg=[0, 4, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=2),
        )],
        face('stand'),
    ]


def prog_yes_no(kind: str = 'yes', cycles: int = 3, speed: int = 75):
    if kind == 'yes':
        return [
            face('nod'),
            *[a for _ in range(cycles) for a in (
                op('body', translation_mm=[0, 0, -4], rotation_deg=[0, 10, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
                op('body', translation_mm=[0, 0, 4], rotation_deg=[0, -10, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            )],
            face('stand'),
        ]
    return [
        face('angry' if speed >= 85 else 'confused'),
        *[a for _ in range(cycles) for a in (
            op('body', translation_mm=[0, 0, 0], rotation_deg=[0, 0, 10], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('body', translation_mm=[0, 0, 0], rotation_deg=[0, 0, -20], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('body', translation_mm=[0, 0, 0], rotation_deg=[0, 0, 10], legs=[], foot_offsets_mm=[], speed_pct=speed),
        )],
        face('stand'),
    ]


def prog_shiver_cold(cycles: int = 4, speed: int = 90):
    return [
        face('sad'),
        op('body', translation_mm=[-6, 0, -12], rotation_deg=[0, 4, 0], legs=[], foot_offsets_mm=[], speed_pct=60),
        *[a for _ in range(cycles) for a in (
            op('body', translation_mm=[0, 4, 0], rotation_deg=[3, 0, 3], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('body', translation_mm=[0, -8, 0], rotation_deg=[-6, 0, -6], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('body', translation_mm=[0, 4, 0], rotation_deg=[3, 0, 3], legs=[], foot_offsets_mm=[], speed_pct=speed),
        )],
        op('body', translation_mm=[6, 0, 12], rotation_deg=[0, -4, 0], legs=[], foot_offsets_mm=[], speed_pct=55),
        face('stand'),
    ]


def prog_laugh_giggle(cycles: int = 4, speed: int = 85):
    return [
        face('excited'),
        op('body', translation_mm=[-6, 0, 4], rotation_deg=[0, -4, 0], legs=[], foot_offsets_mm=[], speed_pct=70),
        *[a for _ in range(cycles) for a in (
            op('body', translation_mm=[0, 0, -10], rotation_deg=[0, 6, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('body', translation_mm=[0, 0, 10], rotation_deg=[0, -6, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
        )],
        op('body', translation_mm=[6, 0, -4], rotation_deg=[0, 4, 0], legs=[], foot_offsets_mm=[], speed_pct=65),
        face('happy'),
    ]


def prog_sigh_slump(speed: int = 35):
    return [
        face('sleepy'),
        op('body', translation_mm=[0, 0, 16], rotation_deg=[0, -5, 0], legs=[], foot_offsets_mm=[], speed_pct=45, taper_deg=3),
        hold(0.5),
        face('bored'),
        op('body', translation_mm=[-8, 0, -28], rotation_deg=[0, 12, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=4),
        hold(1.1),
        op('body', translation_mm=[8, 0, 12], rotation_deg=[0, -7, 0], legs=[], foot_offsets_mm=[], speed_pct=50, taper_deg=2),
        face('stand'),
    ]


# ---------------------------------------------------------------------------
# Pillar 3: Locomotion and Expressive Choreography (10 families)
# ---------------------------------------------------------------------------

def prog_walk(command: str = 'walk', cycles: int = 4, speed: int = 70, expr: str = 'walk'):
    return [face(expr), op('gait', command=command, speed_pct=speed, cycles=cycles), face('stand')]


def prog_pace_patrol(kind: str = 'pace', speed: int = 70):
    if kind == 'square':
        return [
            face('walk'),
            *[a for _ in range(4) for a in (
                op('gait', command='walk', speed_pct=speed, cycles=3),
                op('gait', command='left', speed_pct=speed, cycles=3),
            )],
            op('stand'),
            face('stand'),
        ]
    return [
        face('thinking'),
        op('gait', command='walk', speed_pct=speed, cycles=4),
        op('gait', command='left', speed_pct=speed, cycles=4),
        op('gait', command='walk', speed_pct=speed, cycles=4),
        op('gait', command='right', speed_pct=speed, cycles=4),
        op('stand'),
        face('stand'),
    ]


def prog_walk_and_greet(ending: str = 'wave', speed: int = 70):
    tail = prog_wave_hand('right', cycles=2, speed=70, quick=True) if ending == 'wave' else [
        face('bow'),
        op('body', translation_mm=[-8, 0, -8], rotation_deg=[0, 12, 0], legs=[], foot_offsets_mm=[], speed_pct=60, taper_deg=3),
        hold(0.8),
        op('body', translation_mm=[8, 0, 8], rotation_deg=[0, -12, 0], legs=[], foot_offsets_mm=[], speed_pct=60, taper_deg=3),
        face('stand'),
    ]
    return [
        face('walk'),
        op('gait', command='walk', speed_pct=speed, cycles=4),
        stand_pose(speed_pct=65),
        *tail,
    ]


def prog_happy_zoomies(kind: str = 'zoomies'):
    if kind == 'tippy_taps':
        pairs = [['front_left', 'rear_right'], ['front_right', 'rear_left']]
        return [
            face('excited'),
            *[a for _ in range(4) for pair in pairs for a in (
                op('feet', legs=pair, offsets_mm=[[10, 0, 16], [10, 0, 16]], speed_pct=95),
                op('feet', legs=pair, offsets_mm=[[-10, 0, -16], [-10, 0, -16]], speed_pct=95),
            )],
            face('happy'),
        ]
    return [
        face('excited'),
        op('gait', command='run', speed_pct=95, cycles=5),
        op('gait', command='left', speed_pct=90, cycles=6),
        op('gait', command='run', speed_pct=95, cycles=4),
        op('stand'),
        face('celebrate'),
        hold(0.5),
        face('stand'),
    ]


def prog_moonwalk(cycles: int = 3, speed: int = 75):
    pairs = [['front_left', 'rear_right'], ['front_right', 'rear_left']]
    steps = []
    for _ in range(cycles):
        for pair in pairs:
            steps.extend([
                op('body', translation_mm=[-8, 0, 0], rotation_deg=[0, 2, 0], legs=[], foot_offsets_mm=[], speed_pct=speed - 10),
                op('feet', legs=pair, offsets_mm=[[12, 0, 14], [12, 0, 14]], speed_pct=speed + 10),
                op('feet', legs=pair, offsets_mm=[[-12, 0, -14], [-12, 0, -14]], speed_pct=speed),
                op('body', translation_mm=[8, 0, 0], rotation_deg=[0, -2, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            ])
    return [face('dance'), *steps, stand_pose(speed_pct=65), face('stand')]


def prog_salsa_dance(cycles: int = 3, speed: int = 80):
    steps = [face('salsa')]
    for _ in range(cycles):
        steps.extend([
            op('body', translation_mm=[3, 9, 0], rotation_deg=[-3, 0, 5], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('feet', legs=['front_right'], offsets_mm=[[12, 0, 15]], speed_pct=speed + 10),
            op('feet', legs=['front_right'], offsets_mm=[[-12, 0, -15]], speed_pct=speed + 10),
            op('body', translation_mm=[-6, -18, 0], rotation_deg=[6, 0, -10], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('feet', legs=['front_left'], offsets_mm=[[12, 0, 15]], speed_pct=speed + 10),
            op('feet', legs=['front_left'], offsets_mm=[[-12, 0, -15]], speed_pct=speed + 10),
            op('body', translation_mm=[3, 9, 0], rotation_deg=[-3, 0, 5], legs=[], foot_offsets_mm=[], speed_pct=speed),
        ])
    steps.extend([stand_pose(speed_pct=65), face('stand')])
    return steps


def prog_macarena_dance(cycles: int = 2, speed: int = 75):
    seq = [face('macarena'), *sit_brace_enter(speed - 10)]
    for _ in range(cycles):
        seq.extend([
            # Right arm out straight, then left arm out straight
            op('pose', joints=leg_joints('front_right'), angles_deg=[-12.0, 42.0, 26.0], reference='absolute', speed_pct=speed),
            op('pose', joints=leg_joints('front_left'), angles_deg=[-12.0, 42.0, 26.0], reference='absolute', speed_pct=speed),
            # Flip / widen palms outward
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder'], angles_deg=[-42.0, -42.0], reference='absolute', speed_pct=speed),
            # Cross right to left shoulder, left to right shoulder
            op('pose', joints=front_joints(), angles_deg=[-38.0, 36.0, 18.0, 18.0, 10.0, -28.0], reference='absolute', speed_pct=speed),
            op('pose', joints=front_joints(), angles_deg=[18.0, 10.0, -28.0, 18.0, 10.0, -28.0], reference='absolute', speed_pct=speed),
            # Hands up to head sides
            op('pose', joints=front_joints(), angles_deg=[-65.0, 22.0, 18.0, -65.0, 22.0, 18.0], reference='absolute', speed_pct=speed),
            # Hip shimmy in seated brace using rear shoulders
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[-12.0, 12.0], reference='absolute', speed_pct=speed + 10),
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[12.0, -12.0], reference='absolute', speed_pct=speed + 10),
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[0.0, 0.0], reference='absolute', speed_pct=speed),
        ])
    seq.extend([*sit_brace_exit(speed - 10), face('stand')])
    return seq


def prog_disco_dance(cycles: int = 3, speed: int = 80):
    seq = [face('dance'), *sit_brace_enter(speed - 10)]
    # Left paw braces hip/waist while right paw points sky-high diagonal then across hip!
    seq.append(op('pose', joints=leg_joints('front_left'), angles_deg=[-32.0, 12.0, -36.0], reference='absolute', speed_pct=speed))
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=[*leg_joints('front_right'), 'rear_left_shoulder', 'rear_right_shoulder'],
               angles_deg=[-64.0, 50.0, 28.0, -10.0, 10.0], reference='absolute', speed_pct=speed),
            hold(0.25),
            op('pose', joints=[*leg_joints('front_right'), 'rear_left_shoulder', 'rear_right_shoulder'],
               angles_deg=[20.0, 6.0, -34.0, 10.0, -10.0], reference='absolute', speed_pct=speed),
            hold(0.25),
        ])
    seq.append(op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[0.0, 0.0], reference='absolute', speed_pct=speed))
    seq.extend([*sit_brace_exit(speed - 10), face('stand')])
    return seq


def prog_robot_poplock(speed: int = 95):
    # Crisp zero-taper discrete mechanical ticks + micro-holds
    return [
        face('freaky'),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(), angles_deg=[-45.0, 30.0, 0.0, 0.0, 14.0, -64.0], reference='absolute', speed_pct=speed, taper_deg=0),
        hold(0.22),
        op('pose', joints=front_joints(), angles_deg=[-45.0, 30.0, 0.0, -45.0, 30.0, 0.0], reference='absolute', speed_pct=speed, taper_deg=0),
        hold(0.22),
        op('pose', joints=front_joints(), angles_deg=[-15.0, 48.0, 24.0, -70.0, 10.0, -20.0], reference='absolute', speed_pct=speed, taper_deg=0),
        hold(0.22),
        op('pose', joints=front_joints(), angles_deg=[-70.0, 10.0, -20.0, -15.0, 48.0, 24.0], reference='absolute', speed_pct=speed, taper_deg=0),
        hold(0.22),
        op('pose', joints=front_joints(), angles_deg=[12.0, 28.0, 10.0, 12.0, 28.0, 10.0], reference='absolute', speed_pct=speed, taper_deg=0),
        hold(0.25),
        *sit_brace_exit(70),
        face('stand'),
    ]


def prog_headbang_rock(cycles: int = 4, speed: int = 95):
    return [
        face('excited'),
        op('pose', joints=list(JOINTS), angles_deg=list(WIDE_STANCE_ANGLES), reference='absolute', speed_pct=75),
        *[a for _ in range(cycles) for a in (
            op('body', translation_mm=[4, 0, -4], rotation_deg=[0, 11, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
            op('body', translation_mm=[-4, 0, 4], rotation_deg=[0, -11, 0], legs=[], foot_offsets_mm=[], speed_pct=speed),
        )],
        stand_pose(speed_pct=70),
        face('stand'),
    ]


# ---------------------------------------------------------------------------
# Pillar 4: Theatrical Acting, Absurd Mimes, and Impressions (22 families)
# ---------------------------------------------------------------------------

def prog_hamlet_scene(speed: int = 55):
    """Hamlet ('Alas, poor Yorick' / 'To be or not to be'): seated contemplation,
    right hand raised holding imaginary skull, gaze pitched toward hand, solemn
    pause, sorrowful shake, rise, and theatrical bow."""
    return [
        face('thinking'),
        *sit_brace_enter(speed),
        # Raise right hand forward-up holding Yorick's skull; left hand tucked to chest
        op('pose', joints=front_joints(),
           angles_deg=[16.0, 8.0, -34.0, -24.0, 48.0, 24.0],
           reference='absolute', speed_pct=speed, taper_deg=3),
        hold(1.0),
        face('sad'),
        # Contemplative tilt & slight raise of the skull
        op('pose', joints=[*leg_joints('front_right'), 'rear_left_shoulder', 'rear_right_shoulder'],
           angles_deg=[-32.0, 54.0, 28.0, -6.0, 6.0],
           reference='absolute', speed_pct=speed - 10, taper_deg=3),
        hold(1.1),
        # Gentle solemn shake
        op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'],
           angles_deg=[6.0, -6.0], reference='absolute', speed_pct=speed - 10),
        op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'],
           angles_deg=[0.0, 0.0], reference='absolute', speed_pct=speed - 10),
        # Lower hand and return to standing for curtain-call bow
        *sit_brace_exit(speed),
        face('bow'),
        op('body', translation_mm=[-10, 0, -10], rotation_deg=[0, 14, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=3),
        hold(0.9),
        op('body', translation_mm=[10, 0, 10], rotation_deg=[0, -14, 0], legs=[], foot_offsets_mm=[], speed_pct=speed, taper_deg=3),
        face('stand'),
    ]


def prog_knead_bread(cycles: int = 3, speed: int = 70):
    """Kneading a loaf of bread: seated baker brace so both front paws are free,
    rhythmic alternating right and left front-paw lift -> forward press-down ->
    fold-back cycles, then clean return to standing."""
    steps = [
        face('happy'),
        *sit_brace_enter(speed - 5),
    ]
    for _ in range(cycles):
        steps.extend([
            # Right paw lifts over dough while left paw folds back; then press right paw forward-down
            op('pose', joints=front_joints(),
               angles_deg=[14.0, 14.0, -34.0, -16.0, 42.0, 18.0],
               reference='absolute', speed_pct=speed + 5),
            op('pose', joints=leg_joints('front_right'),
               angles_deg=[-6.0, 22.0, -16.0],
               reference='absolute', speed_pct=speed, taper_deg=3),
            # Left paw lifts over dough while right paw folds back; then press left paw forward-down
            op('pose', joints=front_joints(),
               angles_deg=[-16.0, 42.0, 18.0, 14.0, 14.0, -34.0],
               reference='absolute', speed_pct=speed + 5),
            op('pose', joints=leg_joints('front_left'),
               angles_deg=[-6.0, 22.0, -16.0],
               reference='absolute', speed_pct=speed, taper_deg=3),
        ])
    steps.extend([
        *sit_brace_exit(speed - 5),
        face('stand'),
    ])
    return steps


def prog_sprinkler_dance(side: str = 'right', cycles: int = 2, speed: int = 80):
    """The sprinkler dance: seated brace, one paw tucked behind head/chest while
    the active arm extends and pulses across 4 discrete lateral sprinkler ticks
    then sweeps smoothly back."""
    active = f'front_{side}'
    tucked = 'front_left' if side == 'right' else 'front_right'
    seq = [
        face('dance'),
        *sit_brace_enter(speed - 10),
        op('pose', joints=[*leg_joints(tucked), *leg_joints(active)],
           angles_deg=[-58.0, 18.0, -18.0, -12.0, 44.0, 22.0],
           reference='absolute', speed_pct=speed),
    ]
    for _ in range(cycles):
        for sh in (-28.0, -44.0, -60.0, -76.0):
            seq.extend([
                op('pose', joints=[f'{active}_shoulder', f'{active}_crank'],
                   angles_deg=[sh, 28.0], reference='absolute', speed_pct=min(100, speed + 10)),
                op('pose', joints=[f'{active}_crank'],
                   angles_deg=[16.0], reference='absolute', speed_pct=min(100, speed + 10)),
            ])
        # Smooth sweep reset back to start of arc
        seq.append(op('pose', joints=[f'{active}_shoulder', f'{active}_crank'],
                      angles_deg=[-12.0, 22.0], reference='absolute', speed_pct=speed, taper_deg=3))
    seq.extend([*sit_brace_exit(speed - 10), face('stand')])
    return seq


def prog_frog_impression(hops: int = 2, speed: int = 85):
    """Frog impression: deep wide frog crouch, ribbit chest/throat pulse,
    energetic upward/forward spring hop and squat landing, curious fly scan,
    and return to stand."""
    frog_squat = [-18.0, -16.0, 24.0, -18.0, -16.0, 24.0, -14.0, -14.0, 18.0, -14.0, -14.0, 18.0]
    frog_leap = [-8.0, 28.0, -42.0, -8.0, 28.0, -42.0, -8.0, 22.0, -34.0, -8.0, 22.0, -34.0]
    seq = [
        face('excited'),
        op('pose', joints=list(JOINTS), angles_deg=frog_squat, reference='absolute', speed_pct=65, taper_deg=2),
        # Throat/body ribbit pulse in squat
        op('pose', joints=['front_left_carrier', 'front_right_carrier'], angles_deg=[-4.0, -4.0], reference='absolute', speed_pct=80),
        op('pose', joints=['front_left_carrier', 'front_right_carrier'], angles_deg=[-14.0, -14.0], reference='absolute', speed_pct=80),
        hold(0.35),
    ]
    for _ in range(hops):
        seq.extend([
            # Explosive frog hop extension + soft squat landing
            op('pose', joints=list(JOINTS), angles_deg=frog_leap, reference='absolute', speed_pct=min(100, speed + 15)),
            op('pose', joints=list(JOINTS), angles_deg=frog_squat, reference='absolute', speed_pct=speed, taper_deg=4),
            hold(0.35),
        ])
    seq.extend([
        face('happy'),
        stand_pose(speed_pct=65),
        face('stand'),
    ])
    return seq


def prog_drum_set(cycles: int = 3, speed: int = 90):
    """Imaginary drum set: seated rear brace, fast alternating snare/tom strikes
    across left/center/right + high double-paw cymbal crash!"""
    seq = [
        face('excited'),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(),
           angles_deg=[-22.0, 32.0, 14.0, -22.0, 32.0, 14.0], reference='absolute', speed_pct=80),
    ]
    for _ in range(cycles):
        seq.extend([
            # Right stick snare hit
            op('pose', joints=leg_joints('front_right'), angles_deg=[-12.0, 44.0, -4.0], reference='absolute', speed_pct=speed),
            op('pose', joints=leg_joints('front_right'), angles_deg=[-22.0, 28.0, 18.0], reference='absolute', speed_pct=speed),
            # Left stick snare hit
            op('pose', joints=leg_joints('front_left'), angles_deg=[-12.0, 44.0, -4.0], reference='absolute', speed_pct=speed),
            op('pose', joints=leg_joints('front_left'), angles_deg=[-22.0, 28.0, 18.0], reference='absolute', speed_pct=speed),
            # Outer floor-tom fill
            op('pose', joints=leg_joints('front_right'), angles_deg=[-48.0, 42.0, -2.0], reference='absolute', speed_pct=speed),
            op('pose', joints=leg_joints('front_right'), angles_deg=[-22.0, 28.0, 18.0], reference='absolute', speed_pct=speed),
        ])
    # Big double-hand overhead cymbal crash!
    seq.extend([
        face('celebrate'),
        op('pose', joints=front_joints(),
           angles_deg=[-54.0, 52.0, 28.0, -54.0, 52.0, 28.0], reference='absolute', speed_pct=100),
        hold(0.55),
        *sit_brace_exit(70),
        face('stand'),
    ])
    return seq


def prog_air_guitar(cycles: int = 4, speed: int = 90):
    seq = [
        face('excited'),
        *sit_brace_enter(70),
        # Left paw frets high guitar neck; right paw poised above strings
        op('pose', joints=front_joints(),
           angles_deg=[-56.0, 42.0, 20.0, -10.0, 26.0, 12.0], reference='absolute', speed_pct=80),
    ]
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=['front_right_shoulder', 'front_right_carrier', 'front_right_crank'],
               angles_deg=[14.0, 42.0, -10.0], reference='absolute', speed_pct=speed),
            op('pose', joints=['front_right_shoulder', 'front_right_carrier', 'front_right_crank'],
               angles_deg=[-26.0, 22.0, 18.0], reference='absolute', speed_pct=speed),
        ])
    seq.extend([hold(0.35), *sit_brace_exit(70), face('stand')])
    return seq


def prog_play_piano(cycles: int = 2, speed: int = 75):
    seq = [
        face('love'),
        *sit_brace_enter(65),
        op('pose', joints=front_joints(),
           angles_deg=[-18.0, 34.0, 14.0, -18.0, 34.0, 14.0], reference='absolute', speed_pct=speed),
    ]
    for _ in range(cycles):
        for sh_l, sh_r in [(-46.0, 10.0), (-20.0, -20.0), (10.0, -46.0), (-20.0, -20.0)]:
            seq.extend([
                op('pose', joints=front_joints(),
                   angles_deg=[sh_l, 40.0, 4.0, sh_r, 28.0, 18.0], reference='absolute', speed_pct=speed),
                op('pose', joints=front_joints(),
                   angles_deg=[sh_l, 28.0, 18.0, sh_r, 40.0, 4.0], reference='absolute', speed_pct=speed),
            ])
    seq.extend([*sit_brace_exit(65), face('stand')])
    return seq


def prog_conduct_orchestra(cycles: int = 3, speed: int = 75):
    seq = [
        face('excited'),
        *sit_brace_enter(65),
        op('pose', joints=front_joints(),
           angles_deg=[-28.0, 36.0, 18.0, -28.0, 36.0, 18.0], reference='absolute', speed_pct=speed),
    ]
    for _ in range(cycles):
        seq.extend([
            # Downbeat
            op('pose', joints=front_joints(), angles_deg=[-16.0, 44.0, -4.0, -16.0, 44.0, -4.0], reference='absolute', speed_pct=speed),
            # Outward beat 2
            op('pose', joints=front_joints(), angles_deg=[-54.0, 36.0, 14.0, -54.0, 36.0, 14.0], reference='absolute', speed_pct=speed),
            # Upbeat 3
            op('pose', joints=front_joints(), angles_deg=[-32.0, 48.0, 28.0, -32.0, 48.0, 28.0], reference='absolute', speed_pct=speed),
        ])
    seq.extend([hold(0.5), *sit_brace_exit(65), face('stand')])
    return seq


def prog_stir_pot(side: str = 'right', cycles: int = 2, taste: bool = True, speed: int = 70):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    pts = [[20, sign * 12, 26]]
    for i in range(1, 8 * cycles + 1):
        theta = 2 * math.pi * i / 8
        pts.append([round(20 + 10 * math.cos(theta), 2), round(sign * (12 + 10 * math.sin(theta)), 2), 26])
    if taste:
        pts.extend([[21, sign * 22, 92]])
    seq = [
        face('thinking'),
        shift_in,
        *foot_Waypoints(leg, pts, speed_pct=speed),
    ]
    if taste:
        seq.extend([
            hold(0.6),
            face('love'),
            op('feet', legs=[leg], offsets_mm=[[-21, -sign * 22, -92]], speed_pct=speed),
        ])
    else:
        seq.append(op('feet', legs=[leg], offsets_mm=[[-pts[-1][0], -pts[-1][1], -pts[-1][2]]], speed_pct=speed))
    seq.extend([shift_out, face('stand')])
    return seq


def prog_drink_cup(side: str = 'right', speed: int = 60):
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed)
    return [
        face('happy'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[22, sign * 14, 42]], speed_pct=speed),
        op('feet', legs=[leg], offsets_mm=[[-1, sign * 9, 54]], speed_pct=speed - 10),
        op('body', translation_mm=[0, 0, 0], rotation_deg=[0, -5, 0], legs=[], foot_offsets_mm=[], speed_pct=45),
        hold(0.85),
        op('body', translation_mm=[0, 0, 0], rotation_deg=[0, 5, 0], legs=[], foot_offsets_mm=[], speed_pct=45),
        op('feet', legs=[leg], offsets_mm=[[-21, -sign * 23, -96]], speed_pct=speed),
        shift_out,
        face('stand'),
    ]


def prog_wash_windows(hands_mode: str = 'one', side: str = 'right', cycles: int = 3, speed: int = 75):
    if hands_mode == 'both':
        seq = [face('happy'), *sit_brace_enter(65),
               op('pose', joints=front_joints(), angles_deg=[-20.0, 42.0, 20.0, -20.0, 42.0, 20.0], reference='absolute', speed_pct=speed)]
        for _ in range(cycles):
            seq.extend([
                op('pose', joints=['front_left_shoulder', 'front_right_shoulder'], angles_deg=[-54.0, 12.0], reference='absolute', speed_pct=speed),
                op('pose', joints=['front_left_shoulder', 'front_right_shoulder'], angles_deg=[12.0, -54.0], reference='absolute', speed_pct=speed),
            ])
        seq.extend([*sit_brace_exit(65), face('stand')])
        return seq
    leg = f'front_{side}'
    sign = 1 if side == 'left' else -1
    shift_in, shift_out = weight_shift_for(leg, speed - 10)
    return [
        face('happy'),
        shift_in,
        op('feet', legs=[leg], offsets_mm=[[22, sign * 18, 48]], speed_pct=speed),
        *[a for _ in range(cycles) for a in (
            op('feet', legs=[leg], offsets_mm=[[0, sign * 18, 6]], speed_pct=speed),
            op('feet', legs=[leg], offsets_mm=[[0, -sign * 32, -6]], speed_pct=speed),
            op('feet', legs=[leg], offsets_mm=[[0, sign * 14, 0]], speed_pct=speed),
        )],
        op('feet', legs=[leg], offsets_mm=[[-22, -sign * 18, -48]], speed_pct=speed),
        shift_out,
        face('stand'),
    ]


def prog_hammer_nail(side: str = 'right', cycles: int = 4, speed: int = 85):
    active = f'front_{side}'
    helper = 'front_left' if side == 'right' else 'front_right'
    seq = [
        face('angry'),
        *sit_brace_enter(65),
        # Helper paw holds imaginary nail low; active paw cocks hammer high
        op('pose', joints=[*leg_joints(helper), *leg_joints(active)],
           angles_deg=[10.0, 26.0, 4.0, -20.0, 48.0, 28.0], reference='absolute', speed_pct=75),
    ]
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=leg_joints(active), angles_deg=[-16.0, 38.0, -8.0], reference='absolute', speed_pct=min(100, speed + 10)),
            op('pose', joints=leg_joints(active), angles_deg=[-20.0, 48.0, 28.0], reference='absolute', speed_pct=speed - 15),
        ])
    seq.extend([*sit_brace_exit(65), face('stand')])
    return seq


def prog_lift_barbell():
    """Weightlifter straining to clean-and-jerk a heavy barbell."""
    return [
        face('angry'),
        *sit_brace_enter(60),
        # Reach low to grip the heavy barbell
        op('pose', joints=front_joints(),
           angles_deg=[-24.0, 20.0, -28.0, -24.0, 20.0, -28.0], reference='absolute', speed_pct=55),
        hold(0.5),
        # Slow straining clean to chest with slight left/right quiver
        op('pose', joints=front_joints(),
           angles_deg=[-32.0, 34.0, 2.0, -32.0, 34.0, 2.0], reference='absolute', speed_pct=28),
        op('pose', joints=['front_left_crank', 'front_right_crank'],
           angles_deg=[10.0, 6.0], reference='absolute', speed_pct=25),
        op('pose', joints=['front_left_crank', 'front_right_crank'],
           angles_deg=[8.0, 12.0], reference='absolute', speed_pct=25),
        # Overhead lockout!
        face('celebrate'),
        op('pose', joints=front_joints(),
           angles_deg=[-48.0, 54.0, 28.0, -48.0, 54.0, 28.0], reference='absolute', speed_pct=45, taper_deg=3),
        hold(1.1),
        *sit_brace_exit(60),
        face('stand'),
    ]


def prog_shadow_boxing(cycles: int = 2, speed: int = 90):
    seq = [
        face('angry'),
        *sit_brace_enter(70),
        # Guard up
        op('pose', joints=front_joints(),
           angles_deg=[-22.0, 24.0, 8.0, -22.0, 24.0, 8.0], reference='absolute', speed_pct=80),
    ]
    for _ in range(cycles):
        seq.extend([
            # Left jab
            op('pose', joints=leg_joints('front_left'), angles_deg=[-10.0, 46.0, 26.0], reference='absolute', speed_pct=speed),
            op('pose', joints=leg_joints('front_left'), angles_deg=[-22.0, 24.0, 8.0], reference='absolute', speed_pct=speed),
            # Right cross
            op('pose', joints=leg_joints('front_right'), angles_deg=[-8.0, 48.0, 28.0], reference='absolute', speed_pct=min(100, speed + 5)),
            op('pose', joints=leg_joints('front_right'), angles_deg=[-22.0, 24.0, 8.0], reference='absolute', speed_pct=speed),
            # Bob & weave slip using rear shoulders
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[-14.0, 14.0], reference='absolute', speed_pct=85),
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[14.0, -14.0], reference='absolute', speed_pct=85),
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[0.0, 0.0], reference='absolute', speed_pct=80),
        ])
    seq.extend([*sit_brace_exit(70), face('stand')])
    return seq


def prog_dj_turntable(cycles: int = 4, speed: int = 90):
    seq = [
        face('excited'),
        *sit_brace_enter(70),
        # Left paw holds headphone at ear; right paw over turntable platter
        op('pose', joints=front_joints(),
           angles_deg=[-68.0, 24.0, 18.0, -24.0, 36.0, 10.0], reference='absolute', speed_pct=80),
        # Record scratch oscillation on crank!
        op('oscillate', joint='front_right_crank', amplitude_deg=16, cycles=cycles, speed_pct=speed),
        # Raise right hand for the bass drop!
        face('celebrate'),
        op('pose', joints=leg_joints('front_right'), angles_deg=[-56.0, 52.0, 28.0], reference='absolute', speed_pct=95),
        hold(0.4),
        op('pose', joints=leg_joints('front_right'), angles_deg=[-24.0, 36.0, 6.0], reference='absolute', speed_pct=95),
        *sit_brace_exit(70),
        face('stand'),
    ]
    return seq


def prog_row_boat(cycles: int = 3, speed: int = 70):
    seq = [face('happy'), *sit_brace_enter(65)]
    for _ in range(cycles):
        seq.extend([
            # Reach oars forward
            op('pose', joints=front_joints(),
               angles_deg=[-20.0, 46.0, 26.0, -20.0, 46.0, 26.0], reference='absolute', speed_pct=speed),
            # Pull oars back powerfully toward ribs
            op('pose', joints=front_joints(),
               angles_deg=[-44.0, 14.0, -34.0, -44.0, 14.0, -34.0], reference='absolute', speed_pct=speed - 5, taper_deg=2),
        ])
    seq.extend([*sit_brace_exit(65), face('stand')])
    return seq


def prog_cast_fishing(speed: int = 80):
    return [
        face('thinking'),
        *sit_brace_enter(65),
        # Wind rod back overhead with both hands
        op('pose', joints=front_joints(),
           angles_deg=[-36.0, 24.0, 24.0, -36.0, 24.0, 24.0], reference='absolute', speed_pct=65),
        hold(0.35),
        # Crisp forward cast!
        op('pose', joints=front_joints(),
           angles_deg=[-14.0, 48.0, 26.0, -14.0, 48.0, 26.0], reference='absolute', speed_pct=min(100, speed + 15)),
        hold(0.9),
        # Bite on the line! Reel in with right hand while left holds rod!
        face('surprised'),
        op('pose', joints=leg_joints('front_left'), angles_deg=[-18.0, 44.0, 24.0], reference='absolute', speed_pct=85),
        op('oscillate', joint='front_right_crank', amplitude_deg=16, cycles=4, speed_pct=90),
        face('celebrate'),
        hold(0.5),
        *sit_brace_exit(65),
        face('stand'),
    ]


def prog_dig_hole(cycles: int = 4, speed: int = 85):
    steps = [
        face('excited'),
        op('body', translation_mm=[-6, 0, -10], rotation_deg=[0, 6, 0], legs=[], foot_offsets_mm=[], speed_pct=70),
    ]
    for _ in range(cycles):
        for leg in ('front_right', 'front_left'):
            steps.extend([
                op('feet', legs=[leg], offsets_mm=[[22, 0, 20]], speed_pct=speed),
                op('feet', legs=[leg], offsets_mm=[[-22, 0, -20]], speed_pct=min(100, speed + 10)),
            ])
    steps.extend([
        op('body', translation_mm=[6, 0, 10], rotation_deg=[0, -6, 0], legs=[], foot_offsets_mm=[], speed_pct=65),
        face('stand'),
    ])
    return steps


def prog_bird_airplane(kind: str = 'bird', cycles: int = 3, speed: int = 75):
    if kind == 'airplane':
        return [
            face('happy'),
            *sit_brace_enter(65),
            op('pose', joints=front_joints(),
               angles_deg=[-72.0, 34.0, 12.0, -72.0, 34.0, 12.0], reference='absolute', speed_pct=speed),
            hold(0.5),
            # Bank left, then bank right
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
               angles_deg=[-50.0, -84.0], reference='absolute', speed_pct=speed - 10, taper_deg=3),
            hold(0.6),
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
               angles_deg=[-84.0, -50.0], reference='absolute', speed_pct=speed - 10, taper_deg=3),
            hold(0.6),
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder'],
               angles_deg=[-72.0, -72.0], reference='absolute', speed_pct=speed - 10),
            *sit_brace_exit(65),
            face('stand'),
        ]
    # Bird flapping wings
    seq = [face('excited'), *sit_brace_enter(65)]
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=front_joints(),
               angles_deg=[-78.0, 42.0, 20.0, -78.0, 42.0, 20.0], reference='absolute', speed_pct=speed),
            op('pose', joints=front_joints(),
               angles_deg=[-32.0, 24.0, -8.0, -32.0, 24.0, -8.0], reference='absolute', speed_pct=speed),
        ])
    seq.extend([*sit_brace_exit(65), face('stand')])
    return seq


def prog_cat_dog_antics(kind: str = 'play_bow', cycles: int = 3, speed: int = 80):
    if kind == 'cat_pounce':
        return [
            face('curious'),
            # Low stalk crouch + pre-pounce butt wiggle!
            op('body', translation_mm=[-10, 0, -14], rotation_deg=[0, 5, 0], legs=[], foot_offsets_mm=[], speed_pct=60),
            *[a for _ in range(cycles) for a in (
                op('body', translation_mm=[0, 10, 0], rotation_deg=[0, 0, -6], legs=[], foot_offsets_mm=[], speed_pct=85),
                op('body', translation_mm=[0, -20, 0], rotation_deg=[0, 0, 12], legs=[], foot_offsets_mm=[], speed_pct=85),
                op('body', translation_mm=[0, 10, 0], rotation_deg=[0, 0, -6], legs=[], foot_offsets_mm=[], speed_pct=85),
            )],
            hold(0.35),
            face('excited'),
            # Pounce forward and settle back to stand!
            op('body', translation_mm=[28, 0, 18], rotation_deg=[0, -8, 0], legs=[], foot_offsets_mm=[], speed_pct=100),
            op('body', translation_mm=[-18, 0, -4], rotation_deg=[0, 3, 0], legs=[], foot_offsets_mm=[], speed_pct=75, taper_deg=3),
            face('stand'),
        ]
    # Dog play-bow + happy tail wag!
    bow_pose = [-8.0, 12.0, -24.0, -8.0, 12.0, -24.0, -10.0, 32.0, 24.0, -10.0, 32.0, 24.0]
    return [
        face('happy'),
        op('pose', joints=list(JOINTS), angles_deg=bow_pose, reference='absolute', speed_pct=70, taper_deg=2),
        *[a for _ in range(cycles) for a in (
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[-20.0, 4.0], reference='absolute', speed_pct=min(100, speed + 10)),
            op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[4.0, -20.0], reference='absolute', speed_pct=min(100, speed + 10)),
        )],
        stand_pose(speed_pct=70),
        face('stand'),
    ]


def prog_crab_turtle(kind: str = 'crab', speed: int = 75):
    if kind == 'turtle':
        peek_pose = [0.0, 2.0, -16.0] * 4
        return [
            face('surprised'),
            # Retract quickly into shell!
            op('pose', joints=list(JOINTS), angles_deg=list(REST_ANGLES), reference='absolute', speed_pct=85, taper_deg=3),
            hold(1.0),
            # Cautiously peek out!
            face('curious'),
            op('pose', joints=list(JOINTS), angles_deg=peek_pose, reference='absolute', speed_pct=30, taper_deg=3),
            op('body', translation_mm=[8, 0, 6], rotation_deg=[0, -4, 8], legs=[], foot_offsets_mm=[], speed_pct=30),
            hold(0.6),
            op('body', translation_mm=[0, 0, 0], rotation_deg=[0, 0, -16], legs=[], foot_offsets_mm=[], speed_pct=30),
            hold(0.6),
            stand_pose(speed_pct=55),
            face('stand'),
        ]
    # Crab scuttle + raised claw snaps!
    return [
        face('crab'),
        op('gait', command='crab', speed_pct=speed, cycles=3),
        op('gait', command='crab_right', speed_pct=speed, cycles=3),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(), angles_deg=[-62.0, 42.0, 22.0, -62.0, 42.0, 22.0], reference='absolute', speed_pct=85),
        op('oscillate', joint='front_left_crank', amplitude_deg=14, cycles=2, speed_pct=90),
        op('oscillate', joint='front_right_crank', amplitude_deg=14, cycles=2, speed_pct=90),
        *sit_brace_exit(70),
        face('stand'),
    ]


def prog_dramatic_theater(scene: str = 'romeo'):
    if scene == 'superhero':
        # Superhero landing: tall leap posture -> dramatic 3-point crouched landing with right fist forward -> slow heroic rise!
        hero_crouch = [-14.0, -18.0, 22.0, -14.0, -18.0, 22.0, -24.0, -16.0, 14.0, 8.0, 22.0, 28.0]
        return [
            face('angry'),
            op('body', translation_mm=[0, 0, 14], rotation_deg=[0, -3, 0], legs=[], foot_offsets_mm=[], speed_pct=85),
            op('pose', joints=list(JOINTS), angles_deg=hero_crouch, reference='absolute', speed_pct=95, taper_deg=3),
            hold(1.0),
            face('stand'),
            stand_pose(speed_pct=40, taper_deg=4),
        ]
    if scene == 'faint':
        return [
            face('surprised'),
            *sit_brace_enter(70),
            # Back of paw to forehead dramatically!
            op('pose', joints=leg_joints('front_right'), angles_deg=[-66.0, 26.0, 20.0], reference='absolute', speed_pct=75),
            hold(0.6),
            face('dead'),
            *sit_brace_exit(65),
            op('pose', joints=list(JOINTS), angles_deg=list(REST_ANGLES), reference='absolute', speed_pct=45, taper_deg=4),
            hold(1.2),
            face('surprised'),
            stand_pose(speed_pct=75),
            face('stand'),
        ]
    if scene == 'detective':
        return [
            face('thinking'),
            op('body', translation_mm=[8, 0, 4], rotation_deg=[0, 9, 8], legs=[], foot_offsets_mm=[], speed_pct=45),
            hold(0.7),
            op('body', translation_mm=[0, -12, 0], rotation_deg=[0, 0, -16], legs=[], foot_offsets_mm=[], speed_pct=45),
            hold(0.7),
            face('excited'),
            op('body', translation_mm=[-8, 12, -4], rotation_deg=[0, -9, 8], legs=[], foot_offsets_mm=[], speed_pct=75),
            face('stand'),
        ]
    # Romeo reaching up to Juliet's balcony
    return [
        face('love'),
        *sit_brace_enter(60),
        op('pose', joints=front_joints(),
           angles_deg=[14.0, 10.0, -32.0, -28.0, 56.0, 30.0], reference='absolute', speed_pct=55, taper_deg=3),
        hold(1.1),
        # Hand to heart, then reach out again
        op('pose', joints=leg_joints('front_right'), angles_deg=[18.0, 12.0, -28.0], reference='absolute', speed_pct=55),
        hold(0.5),
        op('pose', joints=leg_joints('front_right'), angles_deg=[-28.0, 56.0, 30.0], reference='absolute', speed_pct=55, taper_deg=3),
        hold(0.8),
        *sit_brace_exit(60),
        face('stand'),
    ]


def prog_juggle(cycles: int = 3, speed: int = 85):
    seq = [
        face('excited'),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(),
           angles_deg=[-24.0, 30.0, 10.0, -24.0, 44.0, 24.0], reference='absolute', speed_pct=speed),
    ]
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=front_joints(),
               angles_deg=[-36.0, 48.0, 26.0, -16.0, 26.0, 4.0], reference='absolute', speed_pct=speed),
            op('pose', joints=front_joints(),
               angles_deg=[-16.0, 26.0, 4.0, -36.0, 48.0, 26.0], reference='absolute', speed_pct=speed),
        ])
    seq.extend([*sit_brace_exit(70), face('stand')])
    return seq


def prog_wizard_spell(speed: int = 70):
    return [
        face('thinking'),
        *sit_brace_enter(65),
        op('pose', joints=front_joints(),
           angles_deg=[-48.0, 24.0, -10.0, -48.0, 24.0, -10.0], reference='absolute', speed_pct=45, taper_deg=3),
        op('pose', joints=front_joints(),
           angles_deg=[-34.0, 46.0, 22.0, -34.0, 46.0, 22.0], reference='absolute', speed_pct=50, taper_deg=3),
        op('oscillate', joint='front_right_shoulder', amplitude_deg=20, cycles=2, speed_pct=80),
        face('excited'),
        op('pose', joints=front_joints(),
           angles_deg=[-12.0, 52.0, 28.0, -12.0, 52.0, 28.0], reference='absolute', speed_pct=100),
        hold(0.7),
        *sit_brace_exit(65),
        face('stand'),
    ]


def prog_zombie_thriller(cycles: int = 2, speed: int = 75):
    seq = [
        face('freaky'),
        *sit_brace_enter(60),
        op('pose', joints=front_joints(),
           angles_deg=[-14.0, 44.0, 22.0, -14.0, 44.0, 22.0], reference='absolute', speed_pct=55),
    ]
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder', 'rear_left_shoulder', 'rear_right_shoulder'],
               angles_deg=[-46.0, 12.0, -10.0, 10.0], reference='absolute', speed_pct=speed, taper_deg=0),
            hold(0.3),
            op('pose', joints=['front_left_shoulder', 'front_right_shoulder', 'rear_left_shoulder', 'rear_right_shoulder'],
               angles_deg=[12.0, -46.0, 10.0, -10.0], reference='absolute', speed_pct=speed, taper_deg=0),
            hold(0.3),
        ])
    seq.append(op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[0.0, 0.0], reference='absolute', speed_pct=65))
    seq.extend([*sit_brace_exit(60), face('stand')])
    return seq


def prog_trex(speed: int = 80):
    return [
        face('angry'),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(),
           angles_deg=[14.0, 18.0, -44.0, 14.0, 18.0, -44.0], reference='absolute', speed_pct=speed),
        op('oscillate', joint='front_left_crank', amplitude_deg=10, cycles=2, speed_pct=90),
        op('oscillate', joint='front_right_crank', amplitude_deg=10, cycles=2, speed_pct=90),
        op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[-14.0, 14.0], reference='absolute', speed_pct=85),
        op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[14.0, -14.0], reference='absolute', speed_pct=85),
        op('pose', joints=['rear_left_shoulder', 'rear_right_shoulder'], angles_deg=[0.0, 0.0], reference='absolute', speed_pct=75),
        *sit_brace_exit(70),
        face('stand'),
    ]


def prog_karate(speed: int = 90):
    return [
        face('bow'),
        op('body', translation_mm=[-6, 0, 4], rotation_deg=[0, 11, 0], legs=[], foot_offsets_mm=[], speed_pct=60, taper_deg=2),
        hold(0.5),
        op('body', translation_mm=[6, 0, -4], rotation_deg=[0, -11, 0], legs=[], foot_offsets_mm=[], speed_pct=65, taper_deg=2),
        face('angry'),
        *sit_brace_enter(75),
        op('pose', joints=front_joints(),
           angles_deg=[-72.0, 44.0, 22.0, -72.0, 44.0, 22.0], reference='absolute', speed_pct=80),
        hold(0.5),
        op('pose', joints=leg_joints('front_right'), angles_deg=[10.0, 48.0, 16.0], reference='absolute', speed_pct=min(100, speed + 10)),
        op('pose', joints=leg_joints('front_left'), angles_deg=[10.0, 48.0, 16.0], reference='absolute', speed_pct=min(100, speed + 10)),
        hold(0.4),
        *sit_brace_exit(70),
        face('stand'),
    ]


def prog_cowboy_lasso(cycles: int = 4, speed: int = 90):
    return [
        face('excited'),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(),
           angles_deg=[-10.0, 28.0, 6.0, -48.0, 52.0, 26.0], reference='absolute', speed_pct=80),
        op('oscillate', joint='front_right_shoulder', amplitude_deg=24, cycles=cycles, speed_pct=speed),
        op('pose', joints=leg_joints('front_right'), angles_deg=[-10.0, 50.0, 28.0], reference='absolute', speed_pct=100),
        hold(0.5),
        op('pose', joints=leg_joints('front_right'), angles_deg=[-30.0, 22.0, -18.0], reference='absolute', speed_pct=90),
        hold(0.4),
        *sit_brace_exit(70),
        face('stand'),
    ]


def prog_typing_keyboard(cycles: int = 4, speed: int = 95):
    seq = [
        face('thinking'),
        *sit_brace_enter(70),
        op('pose', joints=front_joints(),
           angles_deg=[-16.0, 34.0, 12.0, -16.0, 34.0, 12.0], reference='absolute', speed_pct=80),
    ]
    for _ in range(cycles):
        seq.extend([
            op('pose', joints=['front_left_crank', 'front_right_crank'], angles_deg=[2.0, 18.0], reference='absolute', speed_pct=speed),
            op('pose', joints=['front_left_crank', 'front_right_crank'], angles_deg=[18.0, 2.0], reference='absolute', speed_pct=speed),
        ])
    seq.extend([*sit_brace_exit(70), face('stand')])
    return seq


def prog_sneeze():
    return [
        face('surprised'),
        op('body', translation_mm=[-3, 0, 3], rotation_deg=[0, -2, 0], legs=[], foot_offsets_mm=[], speed_pct=45),
        hold(0.35),
        op('body', translation_mm=[-3, 0, 3], rotation_deg=[0, -2, 0], legs=[], foot_offsets_mm=[], speed_pct=50),
        hold(0.35),
        op('body', translation_mm=[-3, 0, 3], rotation_deg=[0, -2, 0], legs=[], foot_offsets_mm=[], speed_pct=55),
        hold(0.45),
        face('excited'),
        op('body', translation_mm=[14, 0, -12], rotation_deg=[0, 11, 0], legs=[], foot_offsets_mm=[], speed_pct=100),
        hold(0.5),
        face('happy'),
        op('body', translation_mm=[-5, 0, 3], rotation_deg=[0, -5, 0], legs=[], foot_offsets_mm=[], speed_pct=55),
        face('stand'),
    ]


def prog_mime_box(speed: int = 70):
    return [
        face('surprised'),
        *sit_brace_enter(65),
        op('pose', joints=front_joints(), angles_deg=[-22.0, 48.0, 24.0, -22.0, 48.0, 24.0], reference='absolute', speed_pct=speed),
        hold(0.35),
        op('pose', joints=front_joints(), angles_deg=[-22.0, 28.0, 4.0, -22.0, 28.0, 4.0], reference='absolute', speed_pct=speed),
        hold(0.35),
        op('pose', joints=front_joints(), angles_deg=[-74.0, 38.0, 18.0, -74.0, 38.0, 18.0], reference='absolute', speed_pct=speed),
        hold(0.45),
        op('pose', joints=front_joints(), angles_deg=[-40.0, 54.0, 28.0, -40.0, 54.0, 28.0], reference='absolute', speed_pct=speed),
        hold(0.45),
        *sit_brace_exit(65),
        face('stand'),
    ]


def prog_opera_singer(speed: int = 55):
    return [
        face('love'),
        *sit_brace_enter(60),
        op('pose', joints=front_joints(), angles_deg=[16.0, 18.0, -20.0, 16.0, 18.0, -20.0], reference='absolute', speed_pct=speed),
        hold(0.5),
        face('excited'),
        op('pose', joints=front_joints(), angles_deg=[-74.0, 48.0, 26.0, -74.0, 48.0, 26.0], reference='absolute', speed_pct=speed, taper_deg=3),
        hold(1.2),
        *sit_brace_exit(60),
        face('bow'),
        op('body', translation_mm=[-6, 0, 4], rotation_deg=[0, 11, 0], legs=[], foot_offsets_mm=[], speed_pct=55, taper_deg=3),
        hold(0.7),
        op('body', translation_mm=[6, 0, -4], rotation_deg=[0, -11, 0], legs=[], foot_offsets_mm=[], speed_pct=55, taper_deg=3),
        face('stand'),
    ]


# ---------------------------------------------------------------------------
# Complete 60-Family Curriculum Generator (Train + Disjoint Evaluation)
# ---------------------------------------------------------------------------

def build_curriculum_splits(discarded_ids: set[str] | None = None):
    """Return (train_rows, eval_rows) with 60 families, verified against V2 FK/bounds."""
    discarded_ids = discarded_ids or set()
    specs: list[tuple[str, list[tuple[str, list[dict]]], tuple[str, list[dict]]]] = []

    # --- Pillar 1: Limb, Side & Joint Mastery (16 families) ---
    specs.append(('raise_right_hand', [
        ('Raise your right hand.', prog_raise_hand('right', 'standing', 65)),
        ('Lift your right front paw up and put it back down.', prog_raise_hand('right', 'standing', 65)),
        ('Put your right arm up high.', prog_raise_hand('right', 'seated', 65)),
        ('Can you raise your right hand for a moment, then stand?', prog_raise_hand('right', 'seated', 65, 1.0)),
        ('Slowly raise your right hand and lower it gently.', prog_raise_hand('right', 'standing', 30, 1.0)),
        ('Quickly shoot your right hand up!', prog_raise_hand('right', 'standing', 95, 0.5)),
    ], ('Hold up your right hand and then return to standing.', prog_raise_hand('right', 'standing', 65))))

    specs.append(('raise_left_hand', [
        ('Raise your left hand.', prog_raise_hand('left', 'standing', 65)),
        ('Lift your left front paw.', prog_raise_hand('left', 'standing', 65)),
        ('Put your left arm up high.', prog_raise_hand('left', 'seated', 65)),
        ('Raise your left hand, hold it briefly, and put it back down.', prog_raise_hand('left', 'standing', 65, 1.0)),
        ('Gently lift your left hand slowly.', prog_raise_hand('left', 'standing', 30, 0.9)),
        ('Snap your left hand up fast!', prog_raise_hand('left', 'standing', 95, 0.5)),
    ], ('Lift up your left arm and finish standing.', prog_raise_hand('left', 'standing', 65))))

    specs.append(('raise_both_hands', [
        ('Raise both hands in the air!', prog_raise_hand('both', 'seated', 70)),
        ('Put your hands up!', prog_raise_hand('both', 'seated', 75, 1.0)),
        ('Stick em up! Lift both front paws.', prog_raise_hand('both', 'seated', 80, 0.9)),
        ('Sit back and reach both arms up toward the ceiling.', prog_raise_hand('both', 'seated', 65, 1.1)),
        ('Throw both hands up in victory and finish standing.', prog_raise_hand('both', 'seated', 85, 0.8)),
    ], ('Lift both of your front hands up high, then stand.', prog_raise_hand('both', 'seated', 70))))

    specs.append(('wave_right_hand', [
        ('Wave with your right hand.', prog_wave_hand('right', 3, 65)),
        ('Wave hello using your right paw.', prog_wave_hand('right', 3, 65, quick=True)),
        ('Give a quick wave with your right arm.', prog_wave_hand('right', 2, 80, quick=True)),
        ('Sit and wave your right hand five times.', prog_wave_hand('right', 5, 70)),
        ('Wave goodbye slowly with your right hand.', prog_wave_hand('right', 3, 35, quick=True)),
    ], ('Say hi by waving your right hand.', prog_wave_hand('right', 3, 65, quick=True))))

    specs.append(('wave_left_hand', [
        ('Wave with your left hand.', prog_wave_hand('left', 3, 65)),
        ('Wave hello using your left paw.', prog_wave_hand('left', 3, 65, quick=True)),
        ('Wave your left paw at me twice.', prog_wave_hand('left', 2, 70, quick=True)),
        ('Sit and wave your left hand five times.', prog_wave_hand('left', 5, 70)),
        ('Gently wave your left arm slowly.', prog_wave_hand('left', 3, 35, quick=True)),
    ], ('Say hi by waving your left hand.', prog_wave_hand('left', 3, 65, quick=True))))

    specs.append(('wave_both_hands', [
        ('Wave hello with both hands!', prog_wave_hand('both', 3, 75)),
        ('Do a big two-handed wave to the crowd.', prog_wave_hand('both', 4, 80)),
        ('Sit back and wave both arms together.', prog_wave_hand('both', 3, 70)),
        ('Wave goodbye with both front paws.', prog_wave_hand('both', 2, 65)),
    ], ('Wave both of your hands enthusiastically.', prog_wave_hand('both', 3, 75))))

    specs.append(('point_right', [
        ('Point forward with your right hand.', prog_point('right', 'forward', 65)),
        ('Point off to the right.', prog_point('right', 'side', 65)),
        ('Point across your body with your right paw.', prog_point('right', 'across', 65)),
        ('Extend your right arm to point straight ahead.', prog_point('right', 'forward', 70)),
    ], ('Use your right arm to point straight ahead.', prog_point('right', 'forward', 65))))

    specs.append(('point_left', [
        ('Point forward with your left hand.', prog_point('left', 'forward', 65)),
        ('Point over to your left side.', prog_point('left', 'side', 65)),
        ('Point across your body with your left paw.', prog_point('left', 'across', 65)),
        ('Extend your left arm to point straight ahead.', prog_point('left', 'forward', 70)),
    ], ('Use your left arm to point straight ahead.', prog_point('left', 'forward', 65))))

    specs.append(('salute_right_hand', [
        ('Give me a crisp salute with your right hand.', prog_salute('right', 1, 75)),
        ('Salute with your right hand.', prog_salute('right', 1, 70)),
        ('Salute twice with your right paw.', prog_salute('right', 2, 75)),
        ('Reporting for duty! Snap a sharp right-hand salute.', prog_salute('right', 1, 90)),
    ], ('Perform a military salute with your right hand.', prog_salute('right', 1, 75))))

    specs.append(('salute_left_hand', [
        ('Salute with your left hand.', prog_salute('left', 1, 70)),
        ('Give me a crisp salute with your left hand.', prog_salute('left', 1, 75)),
        ('Salute twice with your left paw.', prog_salute('left', 2, 75)),
        ('Give a slow respectful salute with your left arm.', prog_salute('left', 1, 40)),
    ], ('Perform a military salute with your left hand.', prog_salute('left', 1, 75))))

    specs.append(('tap_right_paw', [
        ('Tap your right front paw once.', prog_tap_paw('front_right', 1, 75)),
        ('Tap your right paw twice.', prog_tap_paw('front_right', 2, 75)),
        ('Count to five by tapping your right paw five times.', prog_tap_paw('front_right', 5, 80)),
        ('Tap your back right foot twice.', prog_tap_paw('rear_right', 2, 70)),
    ], ('Tap your right front paw three times.', prog_tap_paw('front_right', 3, 75))))

    specs.append(('tap_left_paw', [
        ('Tap your left front paw once.', prog_tap_paw('front_left', 1, 75)),
        ('Tap your left paw twice.', prog_tap_paw('front_left', 2, 75)),
        ('Tap your left front foot three times.', prog_tap_paw('front_left', 3, 75)),
        ('Tap your rear left paw three times.', prog_tap_paw('rear_left', 3, 70)),
    ], ('Tap your left front paw two times.', prog_tap_paw('front_left', 2, 75))))

    specs.append(('hand_circle', [
        ('Trace a circle with your left paw.', prog_hand_circle('left', 2, 75)),
        ('Draw a circle in the air with your right hand.', prog_hand_circle('right', 2, 75)),
        ('Spin your left hand in three circles.', prog_hand_circle('left', 3, 80)),
        ('Make one smooth circle in the air with your right arm.', prog_hand_circle('right', 1, 60)),
    ], ('Trace two circles in front of you with your right paw.', prog_hand_circle('right', 2, 75))))

    specs.append(('beckon_come_here', [
        ('Beckon me over using your left paw.', prog_beckon('left', 3, 70)),
        ('Motion for me to come closer with your right hand.', prog_beckon('right', 3, 70)),
        ('Wave me toward you with your left hand.', prog_beckon('left', 3, 70)),
        ('Do a "come here" gesture with your right paw.', prog_beckon('right', 2, 75)),
    ], ('Gesture "come here" with your right arm.', prog_beckon('right', 3, 70))))

    specs.append(('high_five', [
        ('Give me a high five!', prog_high_five('right', 80)),
        ('High five with your left paw!', prog_high_five('left', 80)),
        ('High five with your right hand!', prog_high_five('right', 80)),
        ('High five with your left hand!', prog_high_five('left', 80)),
        ('Up top! Give me a double high five!', prog_high_five('both', 80)),
    ], ('Put your right paw up for a high five.', prog_high_five('right', 80))))

    specs.append(('fist_bump', [
        ('Bump fists with your left hand.', prog_fist_bump('left', 75)),
        ('Fist bump with your right paw!', prog_fist_bump('right', 80)),
        ('Fist bump with your left paw!', prog_fist_bump('left', 80)),
        ('Give me a fist bump.', prog_fist_bump('right', 75)),
    ], ('Offer a friendly fist bump with your right hand.', prog_fist_bump('right', 75))))

    specs.append(('shake_hands', [
        ('Offer your right paw to shake hands.', prog_shake_hands('right', 3, 65)),
        ('Shake hands with your left paw.', prog_shake_hands('left', 3, 65)),
        ('Shake my hand with your left hand.', prog_shake_hands('left', 3, 65)),
        ('Shake my hand.', prog_shake_hands('right', 3, 65)),
    ], ('Extend your right paw for a handshake.', prog_shake_hands('right', 3, 65))))

    specs.append(('clapping_applause', [
        ('Clap your hands!', prog_clapping(4, 80)),
        ('Give a round of applause!', prog_clapping(5, 85)),
        ('Clap three times happily.', prog_clapping(3, 75)),
        ('Bravo! Applaud enthusiastically!', prog_clapping(6, 90)),
    ], ('Sit back and clap your front paws four times.', prog_clapping(4, 80))))

    specs.append(('rear_leg_kick', [
        ('Kick your back left leg.', prog_rear_kick('left', 2, 75)),
        ('Kick back with your right hind leg.', prog_rear_kick('right', 2, 75)),
        ('Give one quick kick backward with your rear left foot.', prog_rear_kick('left', 1, 85)),
        ('Give one quick kick backward with your rear right foot.', prog_rear_kick('right', 1, 85)),
        ('Do a donkey kick alternating your back legs.', prog_rear_kick('both_alt', 1, 80)),
    ], ('Kick backward twice with your left hind leg.', prog_rear_kick('left', 2, 75))))

    specs.append(('scratch_and_swat', [
        ('Scratch behind your ear like a dog.', prog_scratch_ear('right', 4, 80)),
        ('Scratch an itch with your back left leg.', prog_scratch_ear('left', 4, 80)),
        ('Swat at an imaginary fly with your right paw.', prog_swat_fly('right', 3, 85)),
        ('Bat at a dangling string with your left paw.', prog_swat_fly('left', 3, 85)),
        ('Stretch your right arm across to the left, then your left arm across to the right.',
         [*prog_cross_reach('right', 65)[:-1], *prog_cross_reach('left', 65)[1:]]),
    ], ('Act like you have an itchy ear and scratch it with your right hind leg.', prog_scratch_ear('right', 4, 80))))

    specs.append(('direct_joint_control', [
        ('Abduct your front right shoulder outward by 25 degrees and return.',
         [op('move', joint='front_right_shoulder', angle_deg=-25, reference='current', speed_pct=50),
          hold(0.4),
          op('move', joint='front_right_shoulder', angle_deg=25, reference='current', speed_pct=50)]),
        ('Abduct your front left shoulder outward by 25 degrees and return.',
         [op('move', joint='front_left_shoulder', angle_deg=-25, reference='current', speed_pct=50),
          hold(0.4),
          op('move', joint='front_left_shoulder', angle_deg=25, reference='current', speed_pct=50)]),
        ('Oscillate the front right crank 3 times by 15 degrees at 70 percent speed.',
         [op('oscillate', joint='front_right_crank', amplitude_deg=15, cycles=3, speed_pct=70)]),
        ('Oscillate the rear left shoulder twice by 12 degrees.',
         [op('oscillate', joint='rear_left_shoulder', amplitude_deg=12, cycles=2, speed_pct=50)]),
        ('Wiggle both front shoulders outward and back together.',
         [op('pose', joints=['front_left_shoulder', 'front_right_shoulder'], angles_deg=[-22.0, -22.0], reference='absolute', speed_pct=65),
          op('pose', joints=['front_left_shoulder', 'front_right_shoulder'], angles_deg=[0.0, 0.0], reference='absolute', speed_pct=65)]),
        ('Flex both front cranks forward by 18 degrees at 80 percent speed, hold half a second, then bring them back.',
         [op('pose', joints=['front_left_crank', 'front_right_crank'], angles_deg=[18.0, 18.0], reference='current', speed_pct=80),
          hold(0.5),
          op('pose', joints=['front_left_crank', 'front_right_crank'], angles_deg=[-18.0, -18.0], reference='current', speed_pct=80)]),
    ], ('Oscillate your front left crank 2 times by 14 degrees at 60 percent speed.',
        [op('oscillate', joint='front_left_crank', amplitude_deg=14, cycles=2, speed_pct=60)])))

    # --- Pillar 2: Attitude, Gaze, Postures & Emotional Reactions (11 families) ---
    specs.append(('look_directions', [
        ('Look up at the ceiling.', prog_look('up', 55, 0.9)),
        ('Look down at the floor.', prog_look('down', 55, 0.9)),
        ('Look to your left.', prog_look('left', 60, 0.8)),
        ('Look over to your right.', prog_look('right', 60, 0.8)),
        ('Look left, then look right, scanning the room.', prog_look('scan', 60)),
    ], ('Tilt your gaze upward to look at the sky, then level out.', prog_look('up', 55, 0.9))))

    specs.append(('head_tilt_curious', [
        ('Tilt your head curiously to the right.', prog_head_tilt('right', 1, 55)),
        ('Cock your head to the left like you are listening.', prog_head_tilt('left', 1, 55)),
        ('Tilt your head side to side like a confused puppy.', prog_head_tilt('both', 2, 60)),
        ('Give me a puzzled head tilt.', prog_head_tilt('right', 1, 50)),
    ], ('Tilt your body curiously side to side twice.', prog_head_tilt('both', 2, 60))))

    specs.append(('peek_around_corner', [
        ('Peek around the right corner and duck back.', prog_peek_corner('right', 60)),
        ('Peek out to the left, look, and pull back.', prog_peek_corner('left', 60)),
        ('Play shy peekaboo to the right.', prog_peek_corner('right', 55)),
        ('Sneak a quick peek around the left side.', prog_peek_corner('left', 70)),
    ], ('Lean out to peek around the right edge, then pull back quickly.', prog_peek_corner('right', 65))))

    specs.append(('lean_attitudes', [
        ('Lean forward to listen closely.', prog_lean_attitude('forward', 55)),
        ('Lean back in surprise!', prog_lean_attitude('back', 80)),
        ('Whoa! Recoil backward like something startled you.', prog_lean_attitude('back', 90)),
        ('Sway your body weight left and right.', prog_lean_attitude('side_to_side', 60)),
    ], ('Lean closer toward me attentively, then return to center.', prog_lean_attitude('forward', 55))))

    specs.append(('tiptoe_and_sneak', [
        ('Stand up as tall as you can on your tiptoes!', prog_tiptoe_tall(55)),
        ('Rise up tall and proud, then settle back to normal height.', prog_tiptoe_tall(60)),
        ('Crouch low like you are sneaking quietly.', prog_sneak_prowl(35)),
        ('Get into a stealthy prowl and look left and right.', prog_sneak_prowl(40)),
    ], ('Stretch up tall on all four legs, hold for a second, and settle.', prog_tiptoe_tall(55))))

    specs.append(('cat_cow_yoga', [
        ('Do a cat-cow yoga stretch.', prog_cat_cow_stretch(2, 45)),
        ('Arch your back up and dip your belly down slowly.', prog_cat_cow_stretch(2, 35)),
        ('Do a morning yoga flow from downward dog into upward dog.', prog_cat_cow_stretch(1, 45)),
        ('Stretch your spine gently three times.', prog_cat_cow_stretch(3, 40)),
    ], ('Flow through two slow cat-cow stretches and finish standing.', prog_cat_cow_stretch(2, 40))))

    specs.append(('yes_and_no_gestures', [
        ('Say yes without speaking.', prog_yes_no('yes', 3, 75)),
        ('Nod enthusiastically three times!', prog_yes_no('yes', 3, 85)),
        ('Shake your head no.', prog_yes_no('no', 3, 75)),
        ('Refuse emphatically—no way!', prog_yes_no('no', 4, 90)),
        ('Give one slow affirmative nod.', prog_yes_no('yes', 1, 45)),
    ], ('Gesture "no" by shaking left and right three times.', prog_yes_no('no', 3, 75))))

    specs.append(('shiver_freezing', [
        ('Act like you are freezing cold!', prog_shiver_cold(4, 90)),
        ('Brrr! Shiver and tremble.', prog_shiver_cold(5, 95)),
        ('Tremble like you are scared.', prog_shiver_cold(4, 90)),
        ('Huddle down and shiver from the cold.', prog_shiver_cold(4, 85)),
    ], ('Pretend it is snowing and shiver in place.', prog_shiver_cold(4, 90))))

    specs.append(('laugh_and_sigh', [
        ('Laugh out loud with your whole body!', prog_laugh_giggle(4, 85)),
        ('Giggle happily!', prog_laugh_giggle(3, 80)),
        ('Let out a big exhausted sigh and slump down.', prog_sigh_slump(35)),
        ('Act bored and tired, like you are yawning.', prog_sigh_slump(30)),
    ], ('Chuckle and bounce like you just heard a funny joke.', prog_laugh_giggle(4, 85))))

    specs.append(('stop_and_faces', [
        ('Stop moving immediately!', [op('stop')]),
        ('Freeze right where you are!', [op('stop')]),
        ('Halt!', [op('stop')]),
        ('Make a happy face.', [face('happy')]),
        ('Look angry.', [face('angry')]),
        ('Show me a loving heart-eyes expression.', [face('love')]),
        ('Put on a thinking face.', [face('thinking')]),
        ('Show a sleepy face.', [face('sleepy')]),
    ], ('Stop all body motion now.', [op('stop')])))

    # --- Pillar 3: Locomotion & Expressive Choreography (10 families) ---
    specs.append(('walk_locomotion', [
        ('Walk forward four steps.', prog_walk('walk', 4, 70, 'walk')),
        ('Take a few steps backward.', prog_walk('backward', 4, 65, 'walk_slow')),
        ('Turn to your left.', prog_walk('left', 4, 70, 'turn_left_90')),
        ('Turn to your right.', prog_walk('right', 4, 70, 'turn_right_90')),
        ('Crawl forward slowly and carefully.', prog_walk('crawl', 4, 45, 'crawl')),
        ('Run forward quickly!', prog_walk('run', 5, 95, 'run')),
        ('Sidestep to the left like a crab.', prog_walk('crab', 4, 70, 'crab')),
        ('Crab-walk to the right.', prog_walk('crab_right', 4, 70, 'crab')),
    ], ('Walk backward three steps and stop.', prog_walk('backward', 3, 65, 'walk_slow'))))

    specs.append(('pace_and_patrol', [
        ('Pace back and forth like you are deep in thought.', prog_pace_patrol('pace', 65)),
        ('Walk a small patrol square around the floor.', prog_pace_patrol('square', 70)),
        ('Nervously pace around and come back to standing.', prog_pace_patrol('pace', 80)),
    ], ('Patrol in a four-sided square and finish standing.', prog_pace_patrol('square', 70))))

    specs.append(('walk_and_greet', [
        ('Walk up to me and wave hello with your right hand.', prog_walk_and_greet('wave', 70)),
        ('Step forward and give a polite bow.', prog_walk_and_greet('bow', 70)),
        ('Come over here and wave hi!', prog_walk_and_greet('wave', 75)),
        ('Walk forward to the front of the stage and take a bow.', prog_walk_and_greet('bow', 65)),
    ], ('Approach forward a few steps, then wave your right paw.', prog_walk_and_greet('wave', 70))))

    specs.append(('zoomies_and_tippy_taps', [
        ('Do happy tippy-taps in place!', prog_happy_zoomies('tippy_taps')),
        ('Tap your feet excitedly like dinner is ready!', prog_happy_zoomies('tippy_taps')),
        ('Do excited puppy zoomies!', prog_happy_zoomies('zoomies')),
        ('Run around in a burst of excitement and celebrate!', prog_happy_zoomies('zoomies')),
    ], ('Patter your paws rapidly in excited tippy-taps.', prog_happy_zoomies('tippy_taps'))))

    specs.append(('moonwalk_dance', [
        ('Do the moonwalk!', prog_moonwalk(3, 75)),
        ('Moonwalk backward like Michael Jackson.', prog_moonwalk(3, 80)),
        ('Glide backward in a smooth moonwalk.', prog_moonwalk(2, 70)),
        ('Show me your best moonwalk dance move.', prog_moonwalk(3, 75)),
    ], ('Perform a two-cycle backward moonwalk and stand.', prog_moonwalk(2, 75))))

    specs.append(('salsa_dance', [
        ('Dance salsa!', prog_salsa_dance(3, 80)),
        ('Do a spicy Latin salsa dance step.', prog_salsa_dance(3, 85)),
        ('Sway your hips and tap your feet to a salsa rhythm.', prog_salsa_dance(2, 75)),
        ('Show me some salsa dancing!', prog_salsa_dance(3, 80)),
    ], ('Perform a lively salsa dance routine.', prog_salsa_dance(3, 80))))

    specs.append(('macarena_dance', [
        ('Do the Macarena!', prog_macarena_dance(2, 75)),
        ('Dance the Macarena!', prog_macarena_dance(2, 80)),
        ('Hey Macarena! Do the arm choreography and hip shimmy.', prog_macarena_dance(1, 75)),
        ('Perform the classic Macarena party dance.', prog_macarena_dance(2, 75)),
    ], ('Show me the Macarena dance and finish standing.', prog_macarena_dance(2, 75))))

    specs.append(('disco_dance', [
        ('Do a disco dance!', prog_disco_dance(3, 80)),
        ('Point to the sky like Saturday Night Fever!', prog_disco_dance(3, 85)),
        ('Boogie down with a classic 70s disco finger point!', prog_disco_dance(4, 85)),
        ('Give me some groovy disco moves.', prog_disco_dance(3, 80)),
    ], ('Dance disco by pointing high and across your hip.', prog_disco_dance(3, 80))))

    specs.append(('robot_poplock', [
        ('Do the robot dance!', prog_robot_poplock(95)),
        ('Pop and lock like a classic mechanical robot.', prog_robot_poplock(95)),
        ('Dance with sharp robotic ticks and freezes.', prog_robot_poplock(90)),
        ('Show me your pop-and-lock breakdance moves!', prog_robot_poplock(95)),
    ], ('Perform a crisp mechanical robot dance routine.', prog_robot_poplock(95))))

    specs.append(('headbang_rock', [
        ('Headbang to heavy metal music!', prog_headbang_rock(4, 95)),
        ('Rock out and bang your head!', prog_headbang_rock(5, 95)),
        ('Get in a wide power stance and headbang!', prog_headbang_rock(4, 90)),
    ], ('Headbang energetically four times and return to stand.', prog_headbang_rock(4, 95))))

    # --- Pillar 4: Theatrical Acting, Absurd Mimes & Impressions (23 families) ---
    specs.append(('hamlet_scene', [
        ('Play a scene in Hamlet.', prog_hamlet_scene(55)),
        ('Act out Hamlet holding Yorick\'s skull.', prog_hamlet_scene(55)),
        ('Perform "To be, or not to be" from Shakespeare\'s Hamlet.', prog_hamlet_scene(50)),
        ('Do a dramatic Shakespearean monologue like Hamlet, then take a bow.', prog_hamlet_scene(55)),
        ('Alas, poor Yorick! Act out the graveyard scene in Hamlet.', prog_hamlet_scene(55)),
    ], ('Perform a dramatic scene from Hamlet holding an imaginary skull and finish with a bow.', prog_hamlet_scene(55))))

    specs.append(('knead_bread', [
        ('Act like you are kneading a loaf of bread.', prog_knead_bread(3, 70)),
        ('Pretend to knead bread dough on a counter.', prog_knead_bread(3, 70)),
        ('Mime a baker kneading pizza dough with both paws.', prog_knead_bread(4, 75)),
        ('Knead a batch of sourdough bread.', prog_knead_bread(3, 65)),
        ('Make biscuits like a cat kneading a blanket.', prog_knead_bread(4, 55)),
    ], ('Pretend you are a baker kneading a fresh loaf of bread.', prog_knead_bread(3, 70))))

    specs.append(('sprinkler_dance', [
        ('Do the sprinkler dance!', prog_sprinkler_dance('right', 2, 80)),
        ('Dance the sprinkler!', prog_sprinkler_dance('right', 2, 85)),
        ('Do the lawn sprinkler dance move with your left arm.', prog_sprinkler_dance('left', 2, 80)),
        ('Bust out the cheesy wedding sprinkler dance!', prog_sprinkler_dance('right', 3, 85)),
        ('Put one paw behind your head and do the sprinkler!', prog_sprinkler_dance('right', 2, 80)),
    ], ('Perform the sprinkler dance move and return to standing.', prog_sprinkler_dance('right', 2, 80))))

    specs.append(('frog_impression', [
        ('Pretend you are a frog.', prog_frog_impression(2, 85)),
        ('Act like a frog hopping around!', prog_frog_impression(2, 90)),
        ('Ribbit! Do a frog impression.', prog_frog_impression(2, 85)),
        ('Squat low and hop like a bullfrog.', prog_frog_impression(3, 90)),
        ('Give me one big frog hop.', prog_frog_impression(1, 85)),
    ], ('Impersonate a frog crouching and hopping twice.', prog_frog_impression(2, 85))))

    specs.append(('imaginary_drum_set', [
        ('Play an imaginary drum set!', prog_drum_set(3, 90)),
        ('Do an epic air-drum solo!', prog_drum_set(4, 95)),
        ('Pretend you are a rock drummer hitting the snare, toms, and crash cymbal.', prog_drum_set(3, 90)),
        ('Bang on an invisible drum kit!', prog_drum_set(3, 90)),
        ('Play the drums and finish with a big cymbal crash!', prog_drum_set(2, 95)),
    ], ('Perform an imaginary drum solo on an air drum kit.', prog_drum_set(3, 90))))

    specs.append(('air_guitar', [
        ('Play an imaginary electric guitar!', prog_air_guitar(4, 90)),
        ('Shred an air guitar solo!', prog_air_guitar(5, 95)),
        ('Strum an acoustic guitar.', prog_air_guitar(3, 70)),
        ('Pretend you are a rockstar playing guitar on stage.', prog_air_guitar(4, 90)),
    ], ('Play an energetic air guitar riff and return to standing.', prog_air_guitar(4, 90))))

    specs.append(('play_piano', [
        ('Play an imaginary grand piano.', prog_play_piano(2, 75)),
        ('Pretend you are Mozart playing a piano concerto.', prog_play_piano(2, 80)),
        ('Tickle the ivories on an invisible keyboard!', prog_play_piano(2, 75)),
        ('Mime playing a gentle melody on the piano.', prog_play_piano(1, 55)),
    ], ('Act like a concert pianist playing across the keys.', prog_play_piano(2, 75))))

    specs.append(('conduct_orchestra', [
        ('Conduct an orchestra!', prog_conduct_orchestra(3, 75)),
        ('Act like a symphony maestro conducting with a baton.', prog_conduct_orchestra(3, 75)),
        ('Lead a choir with dramatic conducting gestures.', prog_conduct_orchestra(2, 70)),
        ('Conduct three bars of music in triple time.', prog_conduct_orchestra(3, 80)),
    ], ('Pretend to conduct a grand symphony orchestra.', prog_conduct_orchestra(3, 75))))

    specs.append(('chef_stir_and_taste', [
        ('Act like a chef stirring a pot of soup and tasting it.', prog_stir_pot('right', 2, True, 70)),
        ('Stir a giant bubbling witch\'s cauldron!', prog_stir_pot('right', 3, False, 75)),
        ('Stir batter in a bowl with your left hand.', prog_stir_pot('left', 2, False, 70)),
        ('Mix a potion and take a taste test!', prog_stir_pot('left', 2, True, 70)),
    ], ('Pretend to stir a pot of sauce and taste a spoonful.', prog_stir_pot('right', 2, True, 70))))

    specs.append(('drink_from_cup', [
        ('Pretend to drink from a cup.', prog_drink_cup('right', 60)),
        ('Sip a warm mug of coffee with your right hand.', prog_drink_cup('right', 55)),
        ('Raise a glass for a toast and take a drink with your left hand.', prog_drink_cup('left', 60)),
        ('Chug an imaginary water bottle!', prog_drink_cup('right', 80)),
    ], ('Mime lifting a teacup to your mouth and taking a sip.', prog_drink_cup('right', 60))))

    specs.append(('wash_windows_mime', [
        ('Act like you are washing a window.', prog_wash_windows('one', 'right', 3, 75)),
        ('Wipe a mirror clean with both hands like a mime trapped behind glass.', prog_wash_windows('both', 'right', 3, 75)),
        ('Wax on, wax off! Polish with your left hand.', prog_wash_windows('one', 'left', 3, 75)),
        ('Scrub an imaginary windshield clean.', prog_wash_windows('both', 'right', 2, 80)),
    ], ('Mime wiping a large window with both front paws.', prog_wash_windows('both', 'right', 3, 75))))

    specs.append(('hammer_nail_mime', [
        ('Pretend to hammer a nail into wood.', prog_hammer_nail('right', 4, 85)),
        ('Use an imaginary hammer with your left hand.', prog_hammer_nail('left', 4, 85)),
        ('Pound three nails with a carpenter\'s hammer.', prog_hammer_nail('right', 3, 85)),
    ], ('Mime holding a nail and hammering it four times.', prog_hammer_nail('right', 4, 85))))

    specs.append(('lift_heavy_barbell', [
        ('Pretend to lift an impossibly heavy barbell!', prog_lift_barbell()),
        ('Act like an Olympic weightlifter doing a clean and jerk.', prog_lift_barbell()),
        ('Strain to press a giant boulder overhead in triumph!', prog_lift_barbell()),
        ('Show off your strength by lifting an imaginary heavyweight bar.', prog_lift_barbell()),
    ], ('Mime struggling to lift a heavy barbell overhead and celebrating.', prog_lift_barbell())))

    specs.append(('shadow_boxing', [
        ('Shadowbox!', prog_shadow_boxing(2, 90)),
        ('Act like a boxer throwing jabs, crosses, and dodging!', prog_shadow_boxing(2, 95)),
        ('Put up your dukes and throw a one-two punch combo!', prog_shadow_boxing(1, 90)),
        ('Warm up like Rocky Balboa shadowboxing in the ring.', prog_shadow_boxing(3, 95)),
    ], ('Throw two rounds of boxing combos with head movement.', prog_shadow_boxing(2, 90))))

    specs.append(('dj_turntable', [
        ('Act like a DJ scratching records and dropping the beat!', prog_dj_turntable(4, 90)),
        ('Hold one headphone to your ear and scratch on a turntable.', prog_dj_turntable(4, 90)),
        ('DJ spin that track!', prog_dj_turntable(3, 95)),
    ], ('Pretend you are a club DJ scratching vinyl and hyped for the drop.', prog_dj_turntable(4, 90))))

    specs.append(('row_boat_mime', [
        ('Pretend you are rowing a boat.', prog_row_boat(3, 70)),
        ('Row, row, row your boat gently down the stream!', prog_row_boat(3, 55)),
        ('Pull hard on both oars like an Olympic rower!', prog_row_boat(4, 85)),
    ], ('Mime rowing a rowboat with three smooth oar strokes.', prog_row_boat(3, 70))))

    specs.append(('cast_fishing_rod', [
        ('Pretend to cast a fishing rod and reel in a huge fish!', prog_cast_fishing(80)),
        ('Go fishing: cast your line, wait for a bite, and reel it in!', prog_cast_fishing(80)),
        ('Act like an angler hooking a big bass.', prog_cast_fishing(85)),
    ], ('Mime casting a fishing pole and reeling in a catch.', prog_cast_fishing(80))))

    specs.append(('dig_like_puppy', [
        ('Dig a hole like an excited puppy!', prog_dig_hole(4, 85)),
        ('Pretend to dig for buried treasure in the sand.', prog_dig_hole(4, 80)),
        ('Scrape and dig with your front paws.', prog_dig_hole(3, 80)),
    ], ('Act like a dog digging up a bone in the yard.', prog_dig_hole(4, 85))))

    specs.append(('bird_and_airplane', [
        ('Pretend you are an eagle flapping its wings!', prog_bird_airplane('bird', 3, 75)),
        ('Flap your arms like a bird trying to fly!', prog_bird_airplane('bird', 4, 85)),
        ('Act like an airplane banking left and right through the clouds.', prog_bird_airplane('airplane', 1, 70)),
        ('Spread your wings and soar like a glider plane.', prog_bird_airplane('airplane', 1, 60)),
    ], ('Imitate a bird flapping its wings three times.', prog_bird_airplane('bird', 3, 75))))

    specs.append(('cat_and_dog_impressions', [
        ('Act like a playful puppy doing a play-bow and wagging its tail!', prog_cat_dog_antics('play_bow', 3, 80)),
        ('Wag your tail happily!', prog_cat_dog_antics('play_bow', 4, 85)),
        ('Pretend you are a cat wiggling and pouncing on a mouse!', prog_cat_dog_antics('cat_pounce', 3, 85)),
        ('Stalk, wiggle your hips, and pounce like a kitten!', prog_cat_dog_antics('cat_pounce', 2, 85)),
    ], ('Impersonate a cat doing a pre-pounce wiggle and leaping forward.', prog_cat_dog_antics('cat_pounce', 3, 85))))

    specs.append(('crab_and_turtle_impressions', [
        ('Pretend you are a crab scuttling sideways and snapping its claws!', prog_crab_turtle('crab', 75)),
        ('Do a crab impression!', prog_crab_turtle('crab', 80)),
        ('Act like a shy turtle hiding in its shell and peeking back out.', prog_crab_turtle('turtle', 70)),
        ('Tuck into your turtle shell, wait, and cautiously poke your head out.', prog_crab_turtle('turtle', 65)),
    ], ('Imitate a turtle retreating into its shell and slowly peeking out.', prog_crab_turtle('turtle', 70))))

    specs.append(('romeo_and_superhero', [
        ('Play Romeo reaching up toward Juliet\'s balcony.', prog_dramatic_theater('romeo')),
        ('Reach longingly upward with your hand to your heart like a dramatic actor.', prog_dramatic_theater('romeo')),
        ('Do a superhero three-point landing pose!', prog_dramatic_theater('superhero')),
        ('Strike an epic superhero landing and rise up slowly.', prog_dramatic_theater('superhero')),
    ], ('Land in a dramatic superhero pose and slowly stand tall.', prog_dramatic_theater('superhero'))))

    specs.append(('faint_and_detective', [
        ('Faint dramatically and then wake back up!', prog_dramatic_theater('faint')),
        ('Swoon with your hand to your forehead and collapse, then pop back up!', prog_dramatic_theater('faint')),
        ('Act like Sherlock Holmes searching the floor for clues.', prog_dramatic_theater('detective')),
        ('Inspect the ground like a detective with a magnifying glass, then eureka!', prog_dramatic_theater('detective')),
    ], ('Act like a detective scanning the floor for clues and spotting one.', prog_dramatic_theater('detective'))))

    specs.append(('juggle_imaginary_balls', [
        ('Juggle three imaginary balls!', prog_juggle(3, 85)),
        ('Pretend you are a circus clown juggling!', prog_juggle(4, 90)),
        ('Mime juggling apples in the air with both hands.', prog_juggle(3, 80)),
        ('Toss and catch invisible juggling balls!', prog_juggle(3, 85)),
    ], ('Act like a juggler tossing balls back and forth in the air.', prog_juggle(3, 85))))

    specs.append(('wizard_magic_spell', [
        ('Cast a magic spell like a wizard!', prog_wizard_spell(70)),
        ('Abracadabra! Wave an imaginary magic wand and cast a spell!', prog_wizard_spell(75)),
        ('Pretend you are a sorcerer summoning arcane magic.', prog_wizard_spell(65)),
        ('Swirl your wand and shoot a magic beam forward!', prog_wizard_spell(80)),
    ], ('Mime a wizard gathering magic energy and casting a spell.', prog_wizard_spell(70))))

    specs.append(('zombie_thriller', [
        ('Act like a zombie!', prog_zombie_thriller(2, 75)),
        ('Do the Thriller zombie dance!', prog_zombie_thriller(3, 80)),
        ('Stretch your arms stiffly forward and lurch like a zombie.', prog_zombie_thriller(2, 70)),
        ('Pretend to be a spooky zombie walking at Halloween!', prog_zombie_thriller(2, 75)),
    ], ('Impersonate a zombie with stiff outstretched arms lurching side to side.', prog_zombie_thriller(2, 75))))

    specs.append(('t_rex_dinosaur', [
        ('Pretend you are a T-Rex!', prog_trex(80)),
        ('Act like a Tyrannosaurus Rex with tiny little arms!', prog_trex(85)),
        ('Tuck your front paws in like tiny dinosaur arms and roar!', prog_trex(80)),
        ('Do a fierce T-Rex dinosaur impression!', prog_trex(85)),
    ], ('Imitate a T-Rex dinosaur with short tucked front arms.', prog_trex(80))))

    specs.append(('karate_martial_arts', [
        ('Show me your karate moves!', prog_karate(90)),
        ('Bow, do the Karate Kid crane stance, and throw two karate chops!', prog_karate(90)),
        ('Act like a kung fu master practicing martial arts!', prog_karate(95)),
        ('Do a respectful dojo bow followed by sharp karate strikes.', prog_karate(85)),
    ], ('Perform a martial arts bow, wide crane stance, and twin karate chops.', prog_karate(90))))

    specs.append(('cowboy_lasso', [
        ('Twirl a cowboy lasso overhead and throw it!', prog_cowboy_lasso(4, 90)),
        ('Act like a rodeo cowboy roping a calf!', prog_cowboy_lasso(4, 95)),
        ('Yeehaw! Spin an imaginary lasso in the air and yank it back!', prog_cowboy_lasso(3, 90)),
        ('Pretend you are a cowboy swinging a lariat rope.', prog_cowboy_lasso(4, 85)),
    ], ('Mime a cowboy twirling a lasso overhead and casting it forward.', prog_cowboy_lasso(4, 90))))

    specs.append(('typing_fast_keyboard', [
        ('Type furiously on an imaginary computer keyboard!', prog_typing_keyboard(4, 95)),
        ('Act like a hacker typing code at lightning speed!', prog_typing_keyboard(5, 100)),
        ('Mime typing an angry email on a laptop.', prog_typing_keyboard(4, 95)),
        ('Pretend to type on an old-fashioned typewriter.', prog_typing_keyboard(3, 85)),
    ], ('Mime typing rapidly with both hands on an invisible keyboard.', prog_typing_keyboard(4, 95))))

    specs.append(('sneeze_achoo', [
        ('Pretend you are about to sneeze—achoo!', prog_sneeze()),
        ('Build up a giant sneeze: ah, ah, ACHOO!', prog_sneeze()),
        ('Act like pepper tickled your nose and let out a huge sneeze!', prog_sneeze()),
        ('Do a dramatic comic sneeze!', prog_sneeze()),
    ], ('Mime building up three inhales and sneezing explosively.', prog_sneeze())))

    specs.append(('mime_invisible_box', [
        ('Act like a French mime trapped inside an invisible box!', prog_mime_box(70)),
        ('Feel the walls and ceiling of an imaginary glass box.', prog_mime_box(65)),
        ('Do the classic mime stuck in a box routine!', prog_mime_box(70)),
        ('Press your paws against invisible walls all around you.', prog_mime_box(70)),
    ], ('Perform a mime routine feeling the front, sides, and top of an invisible box.', prog_mime_box(70))))

    specs.append(('opera_singer', [
        ('Sing dramatic opera!', prog_opera_singer(55)),
        ('Act like Pavarotti belting a grand opera high note and taking a bow!', prog_opera_singer(55)),
        ('Clasp your heart, fling your arms wide like an opera diva, and bow!', prog_opera_singer(55)),
        ('Perform a dramatic operatic aria without sound.', prog_opera_singer(50)),
    ], ('Mime an opera singer hitting a grand high note with wide arms and bowing.', prog_opera_singer(55))))

    # --- Pillar 5: Multi-Step Natural Compositions & Contextual Posture Starts ---
    specs.append(('multi_step_compositions', [
        ('First nod yes twice, pause for a second, then raise your right hand and finish standing.',
         [*prog_yes_no('yes', 2, 75)[:-1], hold(1.0), *prog_raise_hand('right', 'standing', 65)]),
        ('Look left, look right, then clap your hands three times.',
         [*prog_look('scan', 65)[:-1], *prog_clapping(3, 80)]),
        ('Give a polite bow, pause briefly, and salute with your right hand.',
         [face('bow'),
          op('body', translation_mm=[-8, 0, -8], rotation_deg=[0, 12, 0], legs=[], foot_offsets_mm=[], speed_pct=60, taper_deg=3),
          hold(0.7),
          op('body', translation_mm=[8, 0, 8], rotation_deg=[0, -12, 0], legs=[], foot_offsets_mm=[], speed_pct=60, taper_deg=3),
          hold(0.4),
          *prog_salute('right', 1, 75)]),
        ('Tap your left paw twice, tap your right paw twice, then jump up tall!',
         [*prog_tap_paw('front_left', 2, 80)[:-1],
          *prog_tap_paw('front_right', 2, 80)[1:-1],
          *prog_tiptoe_tall(75)]),
        ('Walk forward three steps, do a quick frog hop, and wave hello with your right hand.',
         [face('walk'), op('gait', command='walk', speed_pct=75, cycles=3), stand_pose(65),
          *prog_frog_impression(1, 85)[:-1],
          *prog_wave_hand('right', 2, 75, quick=True)]),
        ('Shake your head no twice, shrug it off with a laugh, and give a high five with your left paw.',
         [*prog_yes_no('no', 2, 75)[:-1], *prog_laugh_giggle(2, 85)[:-1], *prog_high_five('left', 80)]),
        ('Sneak low in a prowl, stand up tall in surprise, then do a superhero landing!',
         [*prog_sneak_prowl(35)[:-1], *prog_dramatic_theater('superhero')]),
        ('Stand up cleanly from your current posture.', [op('stand')]),
        ('Get back on your feet and stand normally.', [op('stand')]),
    ], ('First salute with your right hand, pause half a second, then nod yes twice.',
        [*prog_salute('right', 1, 75)[:-1], hold(0.5), *prog_yes_no('yes', 2, 75)])))

    def casual_prompt(text: str) -> str:
        cleaned = text.strip().rstrip('.!?').replace('—', ' ').replace('-', ' ')
        return ' '.join(cleaned.lower().split())

    train_rows = []
    eval_rows = []
    seen_queries = set()
    seen_ids = set(discarded_ids)

    obs_cycle = ('stand', 'sit', 'stand', 'crouch', 'stand', 'rest')
    for fam_idx, (fam, train_items, eval_item) in enumerate(specs):
        for item_idx, (prompt, program) in enumerate(train_items):
            low = prompt.lower()
            if item_idx == 0 or 'left' in low or 'right' in low:
                modes = [None, 'stand']
            elif item_idx in (1, 2):
                modes = [None, obs_cycle[(fam_idx + item_idx) % len(obs_cycle)]]
            else:
                modes = [None if (fam_idx + item_idx) % 2 == 0 else obs_cycle[(fam_idx + item_idx) % len(obs_cycle)]]
            req_variants = []
            for m_idx, mode in enumerate(modes):
                use_casual = item_idx >= 2 and (fam_idx + item_idx + m_idx) % 2 == 1
                req_text = casual_prompt(prompt) if use_casual else prompt
                seed_val = 1 + fam_idx * 17 + item_idx * 3 + m_idx
                req_variants.append((req_text, mode, seed_val))
            if item_idx == 0:
                req_variants.append((casual_prompt(prompt), 'stand', 2001 + fam_idx * 13))
                if 'left' in fam or 'right' in fam:
                    req_variants.append((casual_prompt(prompt), None, 0))
            for req_text, mode, seed_val in req_variants:
                row = make_entry(req_text, program, fam, with_observation=mode, seed=seed_val, split='train')
                if row['query'] in seen_queries or row['id'] in seen_ids:
                    continue
                seen_queries.add(row['query'])
                seen_ids.add(row['id'])
                train_rows.append(row)

        eval_prompt, eval_prog = eval_item
        eval_req = casual_prompt(eval_prompt) if fam_idx % 3 == 1 else eval_prompt
        erow = make_entry(eval_req, eval_prog, fam, with_observation='stand' if fam_idx % 2 else None, seed=901 + fam_idx, split='evaluation')
        if erow['query'] not in seen_queries and erow['id'] not in seen_ids:
            seen_queries.add(erow['query'])
            seen_ids.add(erow['id'])
            eval_rows.append(erow)

    return train_rows, eval_rows
