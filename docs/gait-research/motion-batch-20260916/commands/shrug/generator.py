"""V1 Shrug: flat/dead preparation then four-limb upward shrug and stand."""
import json
import generate_lower_reference as lower
from motion_core import *
def hull(points):
 points=sorted(set(tuple(round(float(v),7) for v in point) for point in points))
 def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
 def half(seq):
  out=[]
  for p in seq:
   while len(out)>=2 and cross(out[-2],out[-1],p)<=0:out.pop()
   out.append(p)
  return out
 return np.array(half(points)[:-1]+half(reversed(points))[:-1])
def generate(settings=None):
 cfg=configuration('shrug','V1 Shrug: all four lower joints move from standing to 90-degree flat/dead pose, then to their opposite extrema, then stand. V2 rests its belly, splays all shoulders flat and raises all four limbs in a synchronized upward shrug.')
 cfg.update(dict(lower_seconds=1.5,splay_seconds=1.,gesture_seconds=.8,shrug_hold_seconds=1.2,flat_hold_seconds=.5,stand_hold_seconds=.5,flat_shoulder_degrees=90.,raised_shoulder_degrees=125.,flat_alpha_degrees=12.,flat_theta_degrees=0.,shoulder_signs=[1.,-1.,1.,-1.]))
 cfg.update(settings or {});mesh=np.load(P/'body-samples.npz')['vertices'];rest=json.loads((P/'body-rest-plane.json').read_text());height=rest['height_mm'];cfg['target_body_height_mm']=height;cfg['target_body_pitch_degrees']=rest['pitch_degrees'];cfg['body_rest_support_polygon_world_mm']=rest['contact_world_mm'];cfg.pop('bottom_contact_polygon_body_xy_mm',None);cfg['bottom_contact_geometry']='Current rear bottom-cover edge plus front visor low point';cfg['allow_known_body_reference_overlap']=False;cfg['body_floor_limitations']='Complete current model uses a pitched rest plane with rear cover plus front visor support; geometric floor clearance is checked, but physical visor contact strength and load capacity remain unverified.';cfg['geometric_research_angle_bounds_degrees']['h']=[-145.,145.];cfg['shoulder_bounds_basis']='Continuous geometric shoulder research envelope, not calibrated electrical endpoints or combined-pose collision proof.';cfg['contact_model']='Grounded rolling soles lower body onto the current rear cover plus front visor support plane at -5.714 degrees pitch. The fixed body then carries airborne limbs. Geometric floor clearance is enforced; visor load capacity and contact friction are unverified.'
 lowered=lower.generate(dict(target_body_height_mm=height,target_body_pitch_degrees=rest['pitch_degrees'],lower_seconds=cfg['lower_seconds'],hold_seconds=0.));m=Motion(cfg);m.rows=copy.deepcopy(lowered['samples']);m.phases=[dict(start=0,end=cfg['lower_seconds'],kind='lower_onto_belly')]
 for r in m.rows:r.update(phase='lower_onto_belly',body_contact_active=False,support_source='feet',body_contact_polygon_world_mm=[],contact_motion_model=['rolling']*4,body_ground_clearance_mm=float((mesh@rotation(r['body_rotation_euler_xyz_rad'])[2]+r['body_position_world_mm'][2]).min()))
 m.now=m.rows[-1]['time_s'];m.body=np.array(m.rows[-1]['body_position_world_mm']);m.euler=np.array(m.rows[-1]['body_rotation_euler_xyz_rad']);m.R=rotation(m.euler);m.q=np.array(m.rows[-1]['actuator_angles_rad']);folded=m.q.copy();lowerpath=copy.deepcopy(m.rows);m.correction=lowered['validation']['maximum_rolling_normal_correction_mm'];m.transfers=lowered['validation']['rolling_transfers']
 for i,l in enumerate(LEGS):m.state[l]=dict(index=m.rows[-1]['contact_vertex_index'][i],anchor=np.array(m.rows[-1]['contact_world_mm'][i]))
 flat=folded.copy();flat[:,0]=np.radians(cfg['flat_shoulder_degrees'])*np.array(cfg['shoulder_signs']);splay=m.joint_segment(flat,cfg['splay_seconds'],'splay_flat_dead_pose');ready=flat.copy();ready[:,1]=math.radians(cfg['flat_alpha_degrees']);ready[:,2]=math.radians(cfg['flat_theta_degrees']);extend=m.joint_segment(ready,.7,'open_flat_limbs');m.hold(cfg['flat_hold_seconds'],'hold_flat_pose');raised=ready.copy();raised[:,0]=np.radians(cfg['raised_shoulder_degrees'])*np.array(cfg['shoulder_signs']);gesture_start=m.now;gesture=m.joint_segment(raised,cfg['gesture_seconds'],'raise_all_limbs_shrug');m.hold(cfg['shrug_hold_seconds'],'hold_upward_shrug');m.reverse(gesture,'release_shrug');m.reverse(extend,'fold_limbs_for_ground');m.reverse(splay,'replace_all_feet');m.reverse(lowerpath,'return_to_standing');cfg['face_cues']=[dict(time_s=0,name='dead',mode='once',fps=1),dict(time_s=gesture_start,name='shrug',mode='once',fps=1),dict(time_s=m.now,name='stand',mode='once',fps=1)];m.hold(cfg['stand_hold_seconds'],'hold_standing');return m.output()
if __name__=='__main__':save(generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None))
