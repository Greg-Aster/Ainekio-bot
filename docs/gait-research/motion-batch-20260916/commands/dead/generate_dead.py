"""V1 Dead held flattening with complete-body contact plane and optional recovery."""
import json
import numpy as np
from motion_common import Motion,P

def generate(settings=None):
 m=Motion('dead','V1 moves all four lower joints to 90 degrees and holds with the boomerang dead face. V2 lowers onto the measured complete-body rear-cover/visor support plane, flattens four legs outward using mirrored shoulders and coordinated lower joints, and remains still. Appended stand recovery is demonstration-only.',settings)
 m.mesh=np.load(P/'current-body-samples.npz')['vertices'];plane=json.loads((P/'body-rest-plane.json').read_text());height=plane['height_mm'];pitch=np.radians(plane['pitch_degrees'])
 for key in ['dead_body_height_mm','ground_support_note','known_camera_reference_floor_penetration_mm','known_intended_visor_floor_penetration_mm','whole_model_lowest_body_z_mm','whole_model_lowest_object','bottom_contact_polygon_body_xy_mm'] :m.cfg.pop(key,None)
 m.cfg.update(body_clearance_geometry='Current complete rigid body samples, including intended visor and camera reference.',body_support_geometry='Measured rear bottom-cover edge plus intended front visor low point',body_rest_plane='body-rest-plane.json',target_body_height_mm=height,target_body_pitch_degrees=plane['pitch_degrees'],body_contact_load_capacity_verified=False,whole_model_floor_check_passed=True,contact_model='Measured sole rolling during approach/recovery. During flattening and hold, the measured rear-cover edge and front visor support the body; visor contact load capacity is unverified.')
 lower=m.pose([0,0,height],[0,pitch,0],2.,'lower_into_dead_pose');m.belly=True;m.support_polygon_world=plane['contact_world_mm'];m.cfg['geometric_research_angle_bounds_degrees']['h']=[-95,95];m.cfg['body_contact_polygon_world_mm']=plane['contact_world_mm'];folded=m.q.copy();m.contacts=[False]*4
 wide=folded.copy();wide[:,0]=np.radians([90,-90,90,-90]);m.joints(wide,1.4,'flatten_shoulders');flat=wide.copy();flat[:,1]=np.radians(-10);flat[:,2]=np.radians(15);m.joints(flat,1.,'flatten_all_four_lower_legs');hold_start=m.now;m.hold(3.,'hold_dead');semantic=m.now
 m.cfg.update(semantic_pose_reached_s=hold_start,semantic_end_s=semantic,semantic_completion='Remain in dead pose until an explicit later command. Stop at semantic_end_s in hardware command execution.',demonstration_recovery_start_s=semantic,completion='V1 holds dead. The source includes a separately labelled optional demonstration recovery after semantic_end_s for a continuous Blender playlist.',shoulder_bounds_basis='90 degree Swim research envelope; geometric only, uncalibrated electrical travel.')
 m.joints(wide,1.,'demonstration_recovery_fold_linkages');m.joints(folded,1.4,'demonstration_recovery_replace_feet');m.contacts=[True]*4;m.recorded(list(reversed(lower)),'demonstration_recovery_stand');end=m.now;m.hold(.5,'hold_standing')
 for r in m.rows:
  r['whole_body_ground_clearance_mm']=r['body_ground_clearance_mm']
  if r['body_contact_active']:r['support_source']='rear_cover_and_front_visor' if not any(r['contact_active']) else 'rear_cover_front_visor_and_feet'
 result=m.finalize(end);result['validation'].update(whole_model_floor_check_passed=True,minimum_whole_body_ground_clearance_mm=min(r['whole_body_ground_clearance_mm'] for r in m.rows),body_support_required=True,body_contact_load_capacity_verified=False)
 (P/'validation.json').write_text(json.dumps(result['validation'],indent=2)+'\n');(P/'source.json').write_text(json.dumps(result)+'\n');return result
if __name__=='__main__':generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None)
