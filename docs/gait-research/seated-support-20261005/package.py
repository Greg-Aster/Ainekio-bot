from remap import *
import hashlib
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
family=ROOT/'motions/gestures';catalog=read(family/'catalog.json');results={}
for cmd in ['sit','wave','upright']:
 folder=family/cmd;source=read(WORK/(cmd+'.json'));original=read(BASE/f'motions/gestures/{cmd}/source.json');rows=source['samples'];q=np.array([r['actuator_angles_rad'] for r in rows]);t=np.array([r['time_s'] for r in rows]);manifest=read(folder/'manifest.json');posture=read(folder/'posture.json');schema=read(folder/'schema.json');contract=read(folder/'execution-contract.json')
 if cmd=='upright':
  # The recorded endpoint is a hold, not a repeated optimizer call.
  for i in range(2401,len(rows)):
   rows[i]=copy.deepcopy(rows[2400]);rows[i]['time_s']=i/120;rows[i]['phase']='hold'
 v=dict(command=cmd,geometry_id=cfg['geometry_id'],samples=len(rows),duration_s=t[-1],sample_hz=120,motion_end_s=manifest['source_validation'].get('motion_end_s',manifest['motion_end_seconds']),minimum_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),minimum_closure_triangle_height_mm=min(r['minimum_closure_height_mm'] for r in rows),maximum_adjacent_joint_step_degrees=float(np.degrees(abs(np.diff(q,axis=0))).max()),peak_joint_speed_deg_s=float(np.degrees(abs(np.gradient(q,t,axis=0))).max()),joint_min_deg=np.degrees(q.min(0)).tolist(),joint_max_deg=np.degrees(q.max(0)).tolist(),maximum_body_translation_difference_mm=float(np.max(np.linalg.norm(np.array([r['body_translation_world_mm'] for r in rows])-np.array([r['body_translation_world_mm'] for r in original['samples']]),axis=1))),maximum_body_pitch_difference_deg=float(np.max(abs(np.degrees(np.array([r['body_rotation_euler_xyz_rad'][1] for r in rows])-np.array([r['body_rotation_euler_xyz_rad'][1] for r in original['samples']]))))),hardware_qualified=False,collision_checked=False,calibration_qualified=False,timing_preserved=True,contact_schedule_preserved=True)
 assert [r['time_s'] for r in rows]==[r['time_s'] for r in original['samples']]
 assert [r['contact_active'] for r in rows]==[r['contact_active'] for r in original['samples']]
 if cmd=='upright':v.update(min_support_margin_after_sit_mm=min(r['support_margin_mm'] for r in rows[361:]),final_front_reach_mm=rows[-1]['arm_reach_mm'][2:],baseline_final_front_reach_mm=original['samples'][-1]['arm_reach_mm'][2:],final_pitch_deg=math.degrees(rows[-1]['body_rotation_euler_xyz_rad'][1]))
 else:v['seated_rear_landing_shift_mm']=[np.array(rows[360]['foot_bolt_world_mm'][i])-np.array(original['samples'][360]['foot_bolt_world_mm'][i]) for i in [0,1]];v['seated_rear_landing_shift_mm']=[a.tolist() for a in v['seated_rear_landing_shift_mm']]
 source['validation']=v;source['metadata'].pop('calibrated_path_fit',None);source['metadata']['linkage_remap']=dict(geometry_sha256=sha(ROOT/'geometry.json'),baseline_geometry_sha256=sha(BASE/'geometry.json'),baseline_source_sha256=sha(BASE/f'motions/gestures/{cmd}/source.json'),generator='docs/gait-research/seated-support-20261005/reproduce.py',scope='Offline supporting-sole and nearest-pose reconstruction. No runtime restriction, pulse remap or saved calibration change.')
 write(folder/'source.json',source);write(folder/'validation.json',v)
 posture['mechanism_geometry_sha256']=sha(ROOT/'geometry.json');posture.pop('calibrated_path_fit',None);posture['linkage_remap']=source['metadata']['linkage_remap'];posture['angle_scope']='Firmware geometric offsets; no physical servo calibration or assembly reindexing applied.'
 if cmd=='sit':posture['terminal_solver_seed_rad']={l:rows[360]['actuator_angles_rad'][i] for i,l in enumerate(legs[:2])}
 else:
  for key,name in [('source_sha256','source.json'),('posture_sha256','posture.json')]:posture['base_motion'][key]=sha(family/'sit'/name)
 if cmd=='upright':posture['front_extended_angles_rad_by_leg']={l:rows[-1]['actuator_angles_rad'][i] for i,l in enumerate(legs) if i>=2};posture['rear_support_policy']='Preserve both rear sole orientations and planted XY. Refit grounded bracing to the new linkage. Retain COM relative to both rear contact patches during the full vertical rise.'
 write(folder/'posture.json',posture)
 manifest.update(geometry_sha256=sha(ROOT/'geometry.json'),geometry_id=cfg['geometry_id'],source_sha256=sha(folder/'source.json'),posture_sha256=sha(folder/'posture.json'),source_validation=v,entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],generated_utc='2026-10-05')
 if 'semantic_end_seconds' in manifest:
  terminal=round(manifest['semantic_end_seconds']*120);manifest['semantic_final_actuator_angles_rad']=rows[terminal]['actuator_angles_rad'];manifest['playlist_final_actuator_angles_rad']=rows[-1]['actuator_angles_rad']
 else:terminal=len(rows)-1
 if 'body_target' in manifest:manifest['body_target']={'position_mm':rows[terminal]['body_position_world_mm'],'euler_xyz_rad':rows[terminal]['body_rotation_euler_xyz_rad']}
 write(folder/'manifest.json',manifest);schema['geometry_id']=cfg['geometry_id'];write(folder/'schema.json',schema)
 contract['geometry_id']=cfg['geometry_id'];contract['entry']['joint_angles_rad']=rows[0]['actuator_angles_rad'];contract['completion']['joint_angles_rad']=rows[terminal]['actuator_angles_rad']
 for f in contract['source_files']:
  name=Path(f['path']).name
  if (folder/name).exists():f['sha256']=sha(folder/name)
 contract['source_qualification']={'hardware_qualified':False,'collision_checked':False,'calibration_qualified':False,'support_scope':'Same provisional COM and supporting hull model as retained choreography; not physical balance qualification.'}
 write(folder/'execution-contract.json',contract)
 entry=next(e for e in catalog['commands'] if e['command']==cmd)
 for name in entry['sha256']:
  if (folder/name).exists():entry['sha256'][name]=sha(folder/name)
 results[cmd]=v
write(family/'catalog.json',catalog);write((WORK/'results.json'),results)
print(json.dumps({c:{k:v for k,v in x.items() if k in ['samples','minimum_body_ground_clearance_mm','min_support_margin_after_sit_mm','maximum_adjacent_joint_step_degrees','final_front_reach_mm','maximum_body_translation_difference_mm','maximum_body_pitch_difference_deg']} for c,x in results.items()},indent=2))
