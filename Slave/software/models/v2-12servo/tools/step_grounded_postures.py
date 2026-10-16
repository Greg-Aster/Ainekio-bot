"""Author Lay Down and Dead with lifted placements before body lowering.

The existing reviewed start and terminal poses are retained. This is an offline
kinematic authoring tool; actual foot contact and servo load need robot testing.
"""
import json
import hashlib
from pathlib import Path

import numpy as np

from retarget_clips import LEGS, load_reference


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / 'motions/gestures'
STEP_SECONDS = .8
LOWER_SECONDS = 2.
LIFT_MM = 8.


def author(name):
    path = FAMILY / name / 'reviewed.json'
    assert name in ('lay_down', 'dead')
    clip = json.loads(path.read_text())
    rows = clip['samples']
    start, end = rows[0], rows[-1]
    cfg = json.loads((ROOT / 'geometry.json').read_text())
    ref = load_reference(ROOT)
    model = ref.Mechanism(cfg)
    hulls = np.load(ROOT / 'motions/gestures/reviewed-hulls.npz')
    model.hulls = {leg: hulls['sole_' + leg] for leg in LEGS}
    body_hull = hulls['body']
    pivot = np.asarray(cfg['continuous_walk']['body_rotation_pivot_mm'])
    first_body, last_body = np.asarray(start['body']), np.asarray(end['body'])
    first_q, last_q = np.asarray(start['q']), np.asarray(end['q'])
    lay_end = json.loads((FAMILY / 'lay_down/reviewed.json').read_text())['samples'][-1]
    lay_q = np.asarray(lay_end['q'])
    assert np.max(np.abs(np.asarray(lay_end['body']) - last_body)) < 1e-5
    first_xy = np.asarray([model.reference(leg, q, first_body)[:2]
                           for leg, q in zip(LEGS, first_q)])
    lay_xy = np.asarray([model.reference(leg, q, last_body)[:2]
                         for leg, q in zip(LEGS, lay_q)])
    last_xy = np.asarray([model.reference(leg, q, last_body)[:2]
                          for leg, q in zip(LEGS, last_q)])
    q = first_q.copy()
    revised = []
    for index in range(len(rows)):
        t = index / clip['sample_hz']
        body_u = np.clip((t - 4 * STEP_SECONDS) / LOWER_SECONDS, 0., 1.)
        body = first_body + (last_body - first_body) * ref.smooth(float(body_u))
        desired_xy, contact, phases = first_xy.copy(), [], []
        for leg_index in range(4):
            u = np.clip((t - leg_index * STEP_SECONDS) / STEP_SECONDS, 0., 1.)
            desired_xy[leg_index] += ref.smooth(float(u)) * (lay_xy[leg_index] - first_xy[leg_index])
            lifted = 0. < u < 1.
            if name == 'dead' and leg_index >= 2:
                extension = np.clip((t - (5.2 + (leg_index - 2) * STEP_SECONDS)) / STEP_SECONDS, 0., 1.)
                desired_xy[leg_index] += ref.smooth(float(extension)) * (last_xy[leg_index] - lay_xy[leg_index])
                lifted = lifted or 0. < extension < 1.
                if 0. < extension < 1.:
                    u = extension
            contact.append(not lifted)
            if lifted:
                phases.append(f'Lift and place {LEGS[leg_index]}')
            height = LIFT_MM * ref.bump(float(u))
            q[leg_index], _ = model.solve(LEGS[leg_index], body, q[leg_index],
                                          desired_xy[leg_index], height)
        sole = [float(model.vertices(leg, joints, body)[:, 2].min())
                for leg, joints in zip(LEGS, q)]
        closure = min(model.planar(joints)[4] for joints in q)
        base = float((body_hull[:, 2] + body[2]).min())
        shell = float(((body_hull - pivot)[:, 2] + pivot[2] + body[2]).min())
        revised.append(dict(time_s=t, body=body.tolist(), euler=start['euler'], q=q.tolist(),
                            phase=phases[0] if phases else 'Lower body with planted feet'
                                  if 0. < body_u < 1. else 'Grounded hold',
                            sole_z=sole, closure_mm=float(closure), base_clearance_mm=base,
                            shell_clearance_mm=shell, contact=contact))
    # Keep exact approved end references; the solver reaches them to numerical precision.
    assert np.max(np.abs(np.asarray(revised[0]['q']) - first_q)) < 1e-5
    assert np.max(np.abs(np.asarray(revised[-1]['q']) - last_q)) < 1e-5
    revised[0]['q'] = first_q.tolist()
    revised[-1]['q'] = last_q.tolist()
    assert min(min(row['sole_z']) for row in revised) > -.02
    assert min(row['shell_clearance_mm'] for row in revised) > -.02
    clip['description'] = ('Lift and place each foot outward before lowering the body; '
                           'Dead then extends the front feet one at a time while lifted. '
                           'Hold the original grounded terminal pose until another command.'
                           if name == 'dead' else
                           'Lift and place each foot outward before lowering the body '
                           'onto the original grounded Lay Down pose; hold until another command.')
    clip['geometry_sha256'] = hashlib.sha256((ROOT / 'geometry.json').read_bytes()).hexdigest()
    clip['samples'] = revised
    path.write_text(json.dumps(clip, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    author('lay_down')
    author('dead')
