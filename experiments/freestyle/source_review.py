"""Offline, ordered full-path comparison of authored gesture candidates.

Distances allow different travel speeds but preserve sample ordering. They are
measurements, not acceptance gates or physical contact/stability evidence.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from .challenge import digest
from .kinematics import CAD_LEGS, ROOT
from .runtime import JOINTS


def ordered_distance(first, second):
    """Discrete Frechet distance with maximum-coordinate error and linear memory.

Unlike nearest-point distances, monotone matching cannot erase an out-and-back
movement just because both paths visit the same set of points.
"""
    first, second = np.asarray(first), np.asarray(second)
    if not len(first) or not len(second):
        raise ValueError('Both trajectories must contain samples')
    previous = np.full(len(second), np.inf)
    for i, point in enumerate(first):
        distances = np.max(np.abs(second - point), axis=1)
        current = np.empty(len(second))
        current[0] = distances[0] if i == 0 else max(distances[0], previous[0])
        for j in range(1, len(second)):
            current[j] = max(distances[j], min(previous[j], previous[j-1], current[j-1]))
        previous = current
    return float(previous[-1])


def densify(points, spacing):
    """Sample the stored polyline evenly enough to compare unequal trace rates."""
    points = np.asarray(points)
    output = [points[0]]
    for start, end in zip(points, points[1:]):
        distance = float(np.max(np.abs(end-start)))
        if distance == 0:
            continue
        steps = max(1, int(np.ceil(distance/spacing)))
        output.extend(start+(end-start)*i/steps for i in range(1, steps+1))
    return np.asarray(output)


def review(candidate_file):
    candidate = json.loads(candidate_file.read_text())
    source_file = Path(candidate['source_file'])
    if digest(source_file) != candidate['source_sha256']:
        raise ValueError('Authored source changed since candidate generation')
    source = json.loads(source_file.read_text())['samples']
    trace = candidate['trace']
    if trace['status'] != 'replayed':
        return {'candidate_sha256': digest(candidate_file), 'status': 'incomplete_replay',
                'completed_actions': trace['completed_actions'], 'error': trace.get('error'),
                'physical_qualification': False, 'training_exported': False}
    samples = trace['samples']
    times = np.array([s['time_s'] for s in source])
    joints = np.rad2deg([s['actuator_angles_rad'] for s in source]).reshape(-1, 12)
    config = json.loads((ROOT/'geometry.json').read_text())
    pivot = np.asarray(config.get('continuous_walk', {}).get('body_rotation_pivot_mm', [0, 0, 65.]))
    # Bring stored world-space foot points into the same zero-body coordinates
    # as the independently replayed FK trace, using the source body's transform.
    feet = np.array([
        (np.asarray(s['foot_bolt_world_mm']) - pivot - s['body_translation_world_mm'])
        @ Rotation.from_euler('xyz', s['body_rotation_euler_xyz_rad']).as_matrix() + pivot
        for s in source
    ]).reshape(-1, 12)
    phases = []
    for phase in candidate['source_phases']:
        a, b = [int(np.argmin(abs(times-t))) for t in (phase['start'], phase['end'])]
        begin, end = phase['action_start'], phase['action_end']
        prior = [s for s in samples if s['action_index'] < begin][-1]
        actual = [prior] + [s for s in samples if begin <= s['action_index'] < end]
        actual_joints = np.array([[s['joints_deg'][j] for j in JOINTS] for s in actual])
        actual_feet = np.array([[s['feet_body_mm'][leg] for leg in CAD_LEGS] for s in actual]).reshape(-1, 12)
        phases.append({
            'phase': phase['kind'], 'source_samples': b-a+1, 'replayed_samples': len(actual),
            'ordered_joint_distance_deg': ordered_distance(densify(joints[a:b+1], .25), densify(actual_joints, .25)),
            'ordered_foot_distance_mm': ordered_distance(densify(feet[a:b+1], .25), densify(actual_feet, .25)),
            'source_duration_s': phase['end']-phase['start'],
            'candidate_duration_s': actual[-1]['time_s']-prior['time_s'],
            'joint_range_loss_deg': float(np.max(np.maximum(
                joints[a:b+1].max(0)-actual_joints.max(0),
                actual_joints.min(0)-joints[a:b+1].min(0)))),
        })
    return {'candidate_sha256': digest(candidate_file), 'source_sha256': digest(source_file),
            'reviewer_sha256': digest(Path(__file__)), 'status': 'measured', 'phases': phases,
            'max_ordered_joint_distance_deg': max(p['ordered_joint_distance_deg'] for p in phases),
            'max_ordered_foot_distance_mm': max(p['ordered_foot_distance_mm'] for p in phases),
            'joint_comparison_spacing_deg': .25, 'foot_comparison_spacing_mm': .25,
            'physical_qualification': False, 'training_exported': False,
            'scope': 'Stored polylines densified in source phase order, allowing travel-speed differences. Discrete distances include comparison spacing; interpolation adds no source measurements. No contact, balance or physical execution claim.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = {}
    for path in args.candidates:
        results[str(path)] = review(path)
        print(json.dumps({'candidate': str(path), **{k: v for k, v in results[str(path)].items()
                         if k not in ('phases', 'scope')}}), flush=True)
    args.output.write_text(json.dumps(results, indent=2)+'\n')
