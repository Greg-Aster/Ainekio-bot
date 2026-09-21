"""Focused source-data checks, independent of Blender playback and hardware."""
import json,math
from pathlib import Path
import numpy as np
import motion_core as m
P=Path(__file__).resolve().parent

def check():
 data=json.loads((P/'source.json').read_text());rows=data['samples'];hz=data['metadata']['configuration']['sample_hz'];t=np.array([r['time_s'] for r in rows]);q=np.array([r['actuator_angles_rad'] for r in rows]);beta=np.array([r['passive_beta_rad'] for r in rows]);foot_error=0.;sole_error=0.;closure=0.;branch=0.
 assert np.isfinite(q).all() and np.isfinite(t).all();assert np.max(abs(np.diff(t)-1/hz))<1e-10
 for r in rows:
  R=m.rotation(r['body_rotation_euler_xyz_rad']);body=np.array(r['body_position_world_mm'])
  for i,l in enumerate(m.LEGS):
   qq=r['actuator_angles_rad'][i];f=m.k.g.fk(l,*qq);p=f['planar_pivots'];L=m.k.g.PARAMETERS['legs'][l]['lengths_mm']['coupler_PQ'];closure=max(closure,abs(np.linalg.norm(np.array(p['P'])-p['Q'])-L));branch=max(branch,abs(m.k.g.wrap(f['beta']-r['passive_beta_rad'][i])))
   bolt,orient,_=m.k.foot_pose(l,qq,np.zeros(3));world=body+R@bolt;sole=(m.k.SOLE[l]-m.k.F0[l])@(R@orient).T+world;foot_error=max(foot_error,float(np.linalg.norm(world-r['foot_bolt_world_mm'][i])));sole_error=max(sole_error,abs(float(sole[:,2].min())-r['sole_clearance_mm'][i]))
 assert closure<1e-7 and branch<1e-7 and foot_error<1e-7 and sole_error<1e-7
 assert np.max(np.abs(q[-1]-q[0]))<1e-10
 report=dict(command=data['metadata']['configuration']['command'],samples=len(rows),sample_hz=hz,uniform_timestamps=True,finite_angles=True,maximum_fourbar_coupler_closure_error_mm=closure,maximum_passive_branch_difference_rad=branch,maximum_forward_kinematic_foot_error_mm=foot_error,maximum_recomputed_sole_clearance_error_mm=sole_error,maximum_adjacent_passive_angle_step_degrees=float(np.degrees(abs(np.diff(beta,axis=0))).max()),exact_standing_return=True,blender_geometry_evaluation='Root integration step',hardware_qualified=False)
 (P/'source-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':check()
