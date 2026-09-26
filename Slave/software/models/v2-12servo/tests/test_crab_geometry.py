"""Exercise ongoing Crab through the wire decoder and full Blender sole hulls."""
import json
from pathlib import Path
import subprocess
import sys

try:
    import numpy as np
    from scipy.spatial.transform import Rotation
except ImportError:
    raise SystemExit(77)

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'tools'))
from validate_compact_clips import transform

cfg = json.loads((root/'geometry.json').read_text())
hulls = np.load(root/'motions/gestures/reviewed-hulls.npz')
pivot = np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
allowance = json.loads((root/'motions/locomotion/sole-profile.json').read_text())['support_allowance_mm']
refinement = json.loads((root/'motions/locomotion/crab.json').read_text())['sole_refinement_allowance_mm']
maximum_error = 0.
minimum_closure = float('inf')
for direction in ('fwd', 'back', 'side_l', 'side_r', 'turn_l', 'turn_r'):
    initial = dict(t='intent', seq=1, name='walk', dir=direction, gait='crab', steps=0, speed=25)
    wire = json.dumps(initial)+'\n'
    updates = [(6000, dict(speed=100)), (15000, dict(stride=40, rate=3)), (25000, dict(speed=0))]
    for seq, (ms, fields) in enumerate(updates, 2):
        command = {k:v for k,v in initial.items() if k != 'speed'}
        wire += f'{ms} '+json.dumps({**command, **fields, 'seq':seq, 'update':1})+'\n'
    run = subprocess.run([sys.argv[1], '60000', '50'], input=wire, capture_output=True, text=True, check=True)
    rows = [json.loads(line) for line in run.stdout.splitlines()]
    assert rows[-1]['complete'] and rows[-1]['ms'] > 25000 and all(rows[-1]['grounded'])
    assert all(sum(r['grounded']) >= 3 and r['run_blend'] == 0 for r in rows)
    q = np.array([r['q'] for r in rows]).reshape(-1,4,3)[:,[2,3,0,1]]
    e = np.array([r['euler'] for r in rows])
    body = np.array([r['body'] for r in rows])
    matrices = Rotation.from_euler('xyz', e).as_matrix()
    offsets = body + pivot - matrices @ pivot
    targets = np.array([r['feet'] for r in rows])[:,[2,3,0,1]]
    assert abs(body[-1,2] - json.loads((root/'motions/locomotion/crab.json').read_text())['body_z_mm']) < 1e-8
    wide = rows[150]['feet']
    assert all(abs(abs(foot[1])-95) < 1e-6 for foot in wide)
    for i, leg in enumerate(('FL', 'FR', 'RL', 'RR')):
        rotation, translation, closure = transform(cfg, leg, q[:,i])
        translation = np.einsum('nij,nj->ni', matrices, translation) + offsets
        rotation = matrices @ rotation
        z = np.einsum('nj,vj->nv', rotation[:,2], hulls['sole_'+leg]) + translation[:,2,None]
        error = z.min(1)-targets[:,i,2]
        # Current live sole refinements differ from the original solver hull
        # by up to 0.08 mm over the revised pose set; test the full hull here.
        assert error.min() > -.001 and error.max() < allowance + refinement, (direction, error.min(), error.max())
        maximum_error = max(maximum_error, float(abs(error).max()))
        xy = np.einsum('nij,j->ni', rotation, cfg['legs'][leg]['foot_reference_local_mm']) + translation
        assert abs(xy[:,:2]-targets[:,i,:2]).max() < .005
        minimum_closure = min(minimum_closure, closure)
        assert closure > 0
    base_z = np.einsum('nj,vj->nv', matrices[:,2], hulls['body']-pivot) + pivot[2]+body[:,2,None]
    assert base_z.min() > 0
    assert np.rad2deg(abs(np.diff(q, axis=0))).max() < 18  # branch continuity at 20 ms
print(json.dumps(dict(directions=6, maximum_sole_height_error_mm=maximum_error,
    minimum_linkage_closure_mm=minimum_closure, hardware_qualified=False)))
