"""Seated Wave using bounded carrier/crank reach and a modest shoulder arc."""
import copy,json,math
from pathlib import Path
import numpy as np
import plan_crawl as k
import generate_sit_reference as sit

P=Path(__file__).resolve().parent
LEGS=k.LEGS

def generate(settings=None):
    sit_keys={'target_body_height_mm','target_body_x_mm','target_body_pitch_degrees','lower_seconds','com','geometric_research_angle_bounds_degrees'}
    seated=sit.generate(dict(hold_seconds=0.,**{key:value for key,value in (settings or {}).items() if key in sit_keys}));cfg=copy.deepcopy(seated['metadata']['configuration'])
    cfg.update(command='wave',display_label='WAVE | SEATED',name='Seated extended-leg wave',
        waving_cad_leg='RL',waving_physical_leg='front_left',
        lift_seconds=1.2,extend_seconds=1.6,half_wave_seconds=.6,hold_seconds=.8,
        shoulder_waypoints_degrees=[80.,95.,65.,95.,65.,95.,80.],
        reach_alpha_degrees=cfg['geometric_research_angle_bounds_degrees']['alpha'][0],
        reach_theta_degrees=cfg['geometric_research_angle_bounds_degrees']['theta'][1],
        waving_shoulder_research_bounds_degrees=[-5.,100.],
        reach_basis='Use the existing research carrier/crank endpoints; do not solve for a straight or maximally stretched linkage. These endpoints are not calibrated hardware stops.',
        source_blend='Before-Wave-Seated.blend',output_blend='Ainekio-Wave-Seated.blend',scene_name='AINEKIO - Wave Seated',
        part023_forward_limit_degrees=None,face_cues=[dict(time_s=0.,name='wave',mode='once',fps=1)],
        completion='Lower the waving foot into Sit, then return to standing and hold; restore the stand face.',
        contact_model='Reuse the measured Sit contact path. While seated, three soles remain fixed; the extended front-left foot is airborne. Retrace the same arm and Sit paths to return.')
    cfg.update(settings or {});hz=cfg['sample_hz'];w=LEGS.index(cfg['waving_cad_leg']);wave=LEGS[w]
    rows=copy.deepcopy(seated['samples']);phases=[dict(start=0.,end=cfg['lower_seconds'],kind='sit_down')]
    for r in rows:r['phase']='sit_down'
    sit_rows=copy.deepcopy(rows);seated_row=rows[-1];body=np.array(seated_row['body_position_world_mm'])
    pitch=seated_row['body_rotation_euler_xyz_rad'][1];R=sit.ry(pitch);com=k.configured_body_com(cfg)
    q=np.array(seated_row['actuator_angles_rad']);sit_q=q[w].copy();now=rows[-1]['time_s']
    def record(time,phase,u):
        r=copy.deepcopy(seated_row);r.update(time_s=time,phase=phase,phase_fraction=u,swing_leg=wave)
        r['contact_active'][w]=False;r['actuator_angles_rad']=q.tolist()
        bolt,rotation,beta=k.foot_pose(wave,q[w],np.zeros(3));bolt=body+R@bolt
        vv=(k.SOLE[wave]-k.F0[wave])@(R@rotation).T+bolt;low=int(vv[:,2].argmin())
        if vv[low,2]<-1e-5:raise ValueError(('waving sole penetration',time,vv[low,2]))
        r['foot_bolt_world_mm'][w]=bolt.tolist();r['passive_beta_rad'][w]=beta
        r['contact_world_mm'][w]=vv[low].tolist();r['contact_vertex_index'][w]=low
        r['sole_clearance_mm'][w]=float(vv[low,2]);r['stance_constraint_error_mm'][w]=None
        r['support_margin_mm']=k.margin([v[:2] for i,v in enumerate(r['contact_world_mm']) if i!=w],(body+R@com)[:2])
        if r['support_margin_mm']<8.:raise ValueError(('assumed COM support margin',time,r['support_margin_mm']))
        par=k.g.PARAMETERS['legs'][wave];od=np.array(k.g.fk(wave,*q[w])['planar_pivots']['D'])-par['pivots_xy_mm']['O']
        a=math.degrees(math.atan2(od[1]*math.cos(q[w,0]),od[0]));r['part023_OD_angle_from_forward_degrees'][w]=a if a>=0 else a+360
        rows.append(r)
    def segment(target,duration,name):
        nonlocal q,now
        initial=q[w].copy();n=round(duration*hz);phases.append(dict(start=now,end=now+duration,kind=name))
        for j in range(1,n+1):
            q[w]=initial+(np.array(target)-initial)*k.smooth(j/n);record(round(now*hz+j)/hz,name,j/n)
        now=round((now+duration)*hz)/hz
    lifted=sit_q.copy();lifted[0]=math.radians(cfg['shoulder_waypoints_degrees'][0])
    segment(lifted,cfg['lift_seconds'],'lift_front_left')
    reached=np.radians([cfg['shoulder_waypoints_degrees'][0],cfg['reach_alpha_degrees'],cfg['reach_theta_degrees']])
    segment(reached,cfg['extend_seconds'],'extend_carrier_and_crank')
    reach_start=now
    for j,h in enumerate(cfg['shoulder_waypoints_degrees'][1:]):
        target=reached.copy();target[0]=math.radians(h);segment(target,cfg['half_wave_seconds'],f'shoulder_wave_{j+1}')
    reach_end=now
    segment(lifted,cfg['extend_seconds'],'retract_carrier_and_crank')
    segment(sit_q,cfg['lift_seconds'],'replace_front_left')
    # Exact seated contact at touchdown, then reverse the existing Sit path.
    touchdown=copy.deepcopy(seated_row);touchdown.update(time_s=now,phase='replace_front_left',phase_fraction=1.)
    rows[-1]=touchdown;phases.append(dict(start=now,end=now+cfg['lower_seconds'],kind='return_to_standing'))
    for j,r in enumerate(reversed(sit_rows[:-1]),1):
        r=copy.deepcopy(r);r.update(time_s=round(now*hz+j)/hz,phase='return_to_standing',phase_fraction=j/(len(sit_rows)-1));rows.append(r)
    now=round((now+cfg['lower_seconds'])*hz)/hz;motion_end=now
    cfg['face_cues'].append(dict(time_s=now,name='stand',mode='once',fps=1))
    phases.append(dict(start=now,end=now+cfg['hold_seconds'],kind='hold_standing'))
    for j in range(1,round(cfg['hold_seconds']*hz)+1):
        r=copy.deepcopy(rows[-1]);r.update(time_s=round(now*hz+j)/hz,phase='hold_standing',phase_fraction=1.);rows.append(r)
    qd=np.degrees([r['actuator_angles_rad'] for r in rows]);vel=np.gradient(qd,1/hz,axis=0);acc=np.gradient(vel,1/hz,axis=0)
    for leg in range(4):
        for axis,key in enumerate(['h','alpha','theta']):
            low,high=cfg['waving_shoulder_research_bounds_degrees'] if leg==w and axis==0 else cfg['geometric_research_angle_bounds_degrees'][key]
            if qd[:,leg,axis].min()<low-1e-6 or qd[:,leg,axis].max()>high+1e-6:raise ValueError(('bound',LEGS[leg],key,qd[:,leg,axis].min(),qd[:,leg,axis].max()))
    fk=k.g.fk(wave,*reached);par=k.g.PARAMETERS['legs'][wave]
    reach=float(np.linalg.norm(np.array(fk['planar_pivots']['F'])-par['pivots_xy_mm']['O']))
    v=dict(duration_s=rows[-1]['time_s'],motion_end_s=motion_end,sample_hz=hz,samples=len(rows),
        extended_wave_start_s=reach_start,extended_wave_end_s=reach_end,
        actuator_min_degrees=qd.min(0).tolist(),actuator_max_degrees=qd.max(0).tolist(),final_actuator_degrees=qd[-1].tolist(),
        actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
        maximum_adjacent_joint_step_degrees=float(abs(np.diff(qd,axis=0)).max()),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),minimum_stance_contacts=3,
        minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),
        min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        peak_waving_sole_height_mm=max(r['sole_clearance_mm'][w] for r in rows),
        peak_waving_foot_bolt_height_mm=max(r['foot_bolt_world_mm'][w][2] for r in rows),
        extended_planar_O_to_foot_bolt_mm=reach,
        max_stance_material_vertex_constraint_error_mm=max(e for r in rows for e in r['stance_constraint_error_mm'] if e is not None),
        maximum_rolling_normal_correction_mm=seated['validation']['maximum_rolling_normal_correction_mm'],
        final_joint_return_error_degrees=float(abs(qd[-1]-qd[0]).max()),research_angle_bounds_satisfied=True,
        collision_checked=False,hardware_servo_limits_verified=False,measured_mass_balance_verified=False,hardware_qualified=False)
    metadata=copy.deepcopy(seated['metadata']);metadata['configuration']=cfg
    return dict(metadata=metadata,phases=phases,samples=rows,validation=v)

if __name__=='__main__':
    data=generate()
    for file,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:
        (P/file).write_text(json.dumps(value,indent=None if file=='source.json' else 2)+'\n')
    print(json.dumps(data['validation'],indent=2))
