"""Upright retains Sit and transfers support before lifting the front pair."""
import json, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=json.loads((ROOT/'motions/gestures/upright/source.json').read_text())
sit=json.loads((ROOT/'motions/gestures/sit/source.json').read_text())
rows=source['samples']
assert rows[:361]==sit['samples'][:361], 'Accepted Sit choreography changed'
assert len(rows)==2641 and rows[-1]['time_s']==22
for r in rows[361:]:
 assert min(r['sole_clearance_mm'])>-.005
 assert r['body_ground_clearance_mm']>0
 assert r['support_margin_mm']>0, 'Provisional COM is outside the supporting soles'
 for i in [0,1]:
  assert r['contact_active'][i]
  assert math.dist(r['foot_bolt_world_mm'][i],rows[360]['foot_bolt_world_mm'][i])<.001, 'Rear lower leg slid'
 if r['time_s']>12:
  assert r['contact_active']==[True,True,False,False]
assert abs(math.degrees(rows[-1]['body_rotation_euler_xyz_rad'][1])+90)<1e-6
assert min(rows[-1]['arm_reach_mm'][2:])>92
assert all(r['actuator_angles_rad']==rows[-1]['actuator_angles_rad'] for r in rows[2400:])
print('Upright: exact Sit prefix, planted rear legs, support transfer, vertical endpoint and hold pass')
