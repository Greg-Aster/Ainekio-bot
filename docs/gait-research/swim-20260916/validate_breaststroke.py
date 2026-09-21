"""Verify the requested front/rear timing, working crank, and closed foot stroke."""
import json
from pathlib import Path

import numpy as np

P = Path(__file__).resolve().parent
d = json.loads((P/'source.json').read_text())
cfg = d['metadata']['configuration']
par = json.loads((P/'robot-gait-parameters.json').read_text())
legs = d['metadata']['leg_order']
front = [i for i,l in enumerate(legs) if par['legs'][l]['physical_name'].startswith('front')]
rear = [i for i,l in enumerate(legs) if par['legs'][l]['physical_name'].startswith('rear')]
assert front == [2,3] and rear == [0,1]
hz = cfg['sample_hz']; start = round(cfg['steady_stroke_source_seconds'][0]*hz)
end = round(cfg['steady_stroke_source_seconds'][1]*hz)
cycle = round(cfg['stroke_seconds']*hz)
q = np.array([r['actuator_angles_rad'] for r in d['samples']])
feet = np.array([r['foot_bolt_world_mm'] for r in d['samples']])
step = np.linalg.norm(np.diff(np.degrees(q[start:end+1,:,1:]),axis=0),axis=2)
assert np.all(step > .1), 'No leg may rest during the steady breaststroke'
repeat_error = float(abs(q[start:end-cycle+1]-q[start+cycle:end+1]).max())
assert repeat_error < 1e-10
phase_lag = [r['front_phase_cycles']-r['rear_phase_cycles'] for r in d['samples'][start:end+1]]
assert max(abs(v-cfg['rear_phase_lag_cycles']) for v in phase_lag) < 1e-10
assert all(r['body_contact_active'] and not any(r['contact_active']) for r in d['samples'][start:end+1])
crank_ranges = np.degrees(np.ptp(q[start:start+cycle+1,:,2],axis=0))
assert np.all(crank_ranges > 59.)
areas = []
for i in range(4):
    xy = feet[start:start+cycle+1,i,:2]
    areas.append(float(abs(np.sum(xy[:-1,0]*xy[1:,1]-xy[1:,0]*xy[:-1,1]))/2))
assert min(areas) > 10., 'Pull and recovery should not retrace the same foot path'
report = dict(physical_front_CAD_legs=[legs[i] for i in front],physical_rear_CAD_legs=[legs[i] for i in rear],
    steady_cycle_seconds=cfg['stroke_seconds'],rear_phase_lag_cycles=cfg['rear_phase_lag_cycles'],
    equivalent_rear_phase_lag_seconds=cfg['rear_phase_lag_cycles']*cfg['stroke_seconds'],
    steady_source_seconds=cfg['steady_stroke_source_seconds'],all_four_legs_move_throughout_steady_segment=True,
    minimum_per_leg_joint_step_steady_degrees=step.min(0).tolist(),maximum_cycle_repeat_error_rad=repeat_error,
    Part005_stroke_range_degrees=crank_ranges.tolist(),closed_foot_path_area_xy_mm2=areas,
    body_support_retained=True,physical_stability_verified=False)
(P/'breaststroke-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
