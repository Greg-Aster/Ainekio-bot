"""Verify Upright geometry and modeled support without claiming loaded balance."""
import importlib.util
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('upright_geometry', ROOT / 'motions/walk/reference.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
source = json.loads((ROOT / 'motions/gestures/upright/source.json').read_text())
sit = json.loads((ROOT / 'motions/gestures/sit/source.json').read_text())
posture = json.loads((ROOT / 'motions/gestures/upright/posture.json').read_text())
cfg = json.loads((ROOT / 'geometry.json').read_text())
hulls = np.load(ROOT / 'motions/gestures/sit/posture-hulls.npz')
mechanism = reference.Mechanism(cfg)
legs = ['FL', 'FR', 'RL', 'RR']
mechanism.hulls = {leg: hulls['sole_' + leg] for leg in legs}
rows = source['samples']
assert rows[:361] == sit['samples'][:361], 'Accepted Sit choreography changed'
assert len(rows) == 2641 and rows[-1]['time_s'] == 22
rear_xy = np.array(rows[360]['foot_bolt_world_mm'])[:2, :2]
# The original choreography steps each front foot backward before bracing.
# Its planted front anchors are established at eight seconds, not after Sit.
front_xy = np.array(rows[960]['foot_bolt_world_mm'])[2:, :2]
minimum_margin = math.inf
minimum_sole = math.inf
minimum_body = math.inf
maximum_xy_error = 0.
for row in rows[361:]:
    body = np.array(row['body_translation_world_mm'])
    q = np.array(row['actuator_angles_rad'])
    mechanism.body_euler = np.array(row['body_rotation_euler_xyz_rad'])
    supports = []
    for i, leg in enumerate(legs):
        vertices = mechanism.vertices(leg, q[i], body)
        sole_z = float(vertices[:, 2].min())
        minimum_sole = min(minimum_sole, sole_z)
        assert sole_z > -.005, f'Sole below floor: {row["time_s"]}, {leg}'
        point = mechanism.reference(leg, q[i], body)
        assert np.max(np.abs(point - row['foot_bolt_world_mm'][i])) < .0001
        if i < 2:
            assert row['contact_active'][i]
            error = float(np.max(np.abs(point[:2] - rear_xy[i])))
            maximum_xy_error = max(maximum_xy_error, error)
            assert error < .001, 'Rear foot reference slid on the floor'
        elif 8 <= row['time_s'] <= 12:
            assert row['contact_active'][i], 'Front support removed before transfer finished'
            error = float(np.max(np.abs(point[:2] - front_xy[i - 2])))
            maximum_xy_error = max(maximum_xy_error, error)
            assert error < .001, 'Grounded front foot reference slid during transfer'
        if row['contact_active'][i]:
            assert abs(sole_z) < .005, 'Declared contact is airborne'
            supports.extend(vertices[vertices[:, 2] < sole_z + .5])
    if row['time_s'] > 12:
        assert row['contact_active'] == [True, True, False, False]
    pivot = np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    B = reference.rz(mechanism.body_euler[2]) @ reference.ry(mechanism.body_euler[1]) @ reference.rx(mechanism.body_euler[0])
    body_clearance = float(((hulls['body'] - pivot) @ B.T + pivot + body)[:, 2].min())
    minimum_body = min(minimum_body, body_clearance)
    assert body_clearance > 0, 'Body hull intersects floor'
    margin = reference.margin((body + pivot)[:2], supports)
    minimum_margin = min(minimum_margin, margin)
    assert margin > 0, 'Provisional COM is outside the supporting soles'
    assert abs(margin - row['support_margin_mm']) < .0001, 'Stored support result is stale'

assert abs(math.degrees(rows[-1]['body_rotation_euler_xyz_rad'][1]) + 90) < 1e-6
for i in (2, 3):
    assert np.max(np.abs(np.array(rows[-1]['actuator_angles_rad'][i]) - posture['front_extended_angles_rad_by_leg'][legs[i]])) < 1e-10
assert all(row['actuator_angles_rad'] == rows[-1]['actuator_angles_rad'] for row in rows[2400:])
assert not source['validation']['hardware_qualified']
# The calibrated endpoint retains extended forelimbs with 90.34 mm modeled reach.
# Electrical extrema and entry paths are checked by test_clip_calibration.c.
assert min(rows[-1]['arm_reach_mm'][2:]) > 90
print(f'Upright: exact Sit prefix, grounded transfer, anchored rear XY and vertical hold pass; '
      f'modeled support margin {minimum_margin:.6f} mm, sole {minimum_sole:.8f} mm, '
      f'body clearance {minimum_body:.6f} mm, XY error {maximum_xy_error:.8f} mm. '
      'Loaded balance remains unqualified.')
