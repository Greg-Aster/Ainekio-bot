"""Focused independent sample and midpoint four-bar/continuity check."""
import json,math
from pathlib import Path
import numpy as np
import gait_kinematics as g
P=Path(__file__).resolve().parent

def check():
    data=json.loads((P/'source.json').read_text());rows=data['samples'];cfg=data['metadata']['configuration'];angles=np.array([r['actuator_angles_rad'] for r in rows]);times=np.array([r['time_s'] for r in rows]);maximum=0.;beta_error=0.;max_beta_step=0.
    for idx in range(2*len(rows)-1):
        i=idx//2;q=angles[i] if idx%2==0 else (angles[i]+angles[i+1])/2
        for j,l in enumerate(data['metadata']['leg_order']):
            f=g.fk(l,*q[j]);v=g.PARAMETERS['legs'][l];length=np.linalg.norm(np.array(f['planar_pivots']['Q'])-f['planar_pivots']['P']);maximum=max(maximum,abs(length-v['lengths_mm']['coupler_PQ']))
            if idx%2==0:beta_error=max(beta_error,abs(g.wrap(f['beta']-rows[i]['passive_beta_rad'][j])))
    beta=np.array([r['passive_beta_rad'] for r in rows]);max_beta_step=float(abs(np.diff(beta,axis=0)).max());assert max_beta_step<.1
    assert np.isfinite(angles).all();assert np.max(np.abs(np.diff(times)-1/cfg['sample_hz']))<1e-9
    assert maximum<1e-8 and beta_error<1e-8
    assert np.max(abs(angles[-1]-angles[0]))<1e-9
    v=dict(samples_checked=len(rows),linear_midpoints_checked=len(rows)-1,max_fourbar_coupler_length_error_mm=maximum,max_passive_beta_error_rad=beta_error,max_passive_beta_adjacent_step_degrees=math.degrees(max_beta_step),timestamps_uniform=True,exact_geometric_standing_return=True,finite_actuator_angles=True,blender_evaluation_checked=False,collisions_checked=False,hardware_qualified=False)
    (P/'source-check.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v,indent=2))
if __name__=='__main__':check()
