"""Author the seated, bare-Part027 Wave; leave other gestures unchanged.

Run with the model root and a locally saved calibration readback. The pulse
comparison is offline evidence, not a runtime limiter or calibration change.
"""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.spatial.transform import Rotation

from retarget_clips import LEGS, digest, load_reference, write
from remap_reviewed_clips import refresh_metrics


def author(root, calibration):
    family = root / 'motions/gestures'
    folder = family / 'wave'
    read = lambda p: json.loads(p.read_text())
    write_source = lambda value: (folder/'source.json').write_text(
        json.dumps(value,separators=(',',':'),allow_nan=False)+'\n')
    cfg = read(root / 'geometry.json')
    ref = load_reference(root)
    mechanism = ref.Mechanism(cfg)
    sit = read(family / 'sit/source.json')['samples'][:361]
    contact = root / 'motions/locomotion/walk-contact.json'
    sole = np.array(read(contact)['sole_hull_local_mm'])
    hulls = dict(np.load(family / 'sit/posture-hulls.npz'))
    for leg in LEGS:
        hulls['sole_' + leg] = sole.copy()
    mechanism.hulls = {leg: sole for leg in LEGS}
    np.savez_compressed(folder / 'contact-hulls.npz', **hulls)

    timing = dict(sit_end=1.2, lift_end=1.6, extension_end=2., wave_end=4.,
                  retraction_end=4.4, foot_replacement_end=4.8,
                  stand_end=6., clip_end=6.2)
    names = ['sit_down', 'lift_front_left', 'extend_carrier_and_crank',
             'three_playful_waves', 'retract_carrier_and_crank',
             'replace_front_left', 'return_to_standing', 'hold_standing']
    ends = [0., *timing.values()]
    phases = [dict(start=a, end=b, kind=n)
              for a, b, n in zip(ends, ends[1:], names)]
    times = np.array([r['time_s'] for r in sit])
    fields = ['body_translation_world_mm', 'body_rotation_euler_xyz_rad',
              'actuator_angles_rad', 'target_foot_reference_xy_mm',
              'target_sole_clearance_mm']
    curves = {key: PchipInterpolator(times, np.array([r[key] for r in sit]), axis=0)
              for key in fields}
    # Retain Sit's sequential foot placement; refit its body and feet to the
    # installed bare leg. At the seated endpoint the body has 1 mm clearance.
    seat_body = np.array(sit[-1]['body_translation_world_mm'])
    body_delta = np.array([1., 0., -16.38499608 - seat_body[2]])
    pitch_delta = np.deg2rad(-25.5) - sit[-1]['body_rotation_euler_xyz_rad'][1]
    entry = []
    for i in range(round(timing['sit_end'] * 120) + 1):
        u = i / (timing['sit_end'] * 120)
        t = 3. * u
        row = copy.deepcopy(sit[min(360, round(t * 120))])
        row.update({key: curve(t).tolist() for key, curve in curves.items()})
        body = np.array(row['body_translation_world_mm']) + ref.smooth(u) * body_delta
        euler = np.array(row['body_rotation_euler_xyz_rad'])
        euler[1] += ref.smooth(u) * pitch_delta
        mechanism.body_euler = euler
        q = np.array(row['actuator_angles_rad'])
        for j, leg in enumerate(LEGS):
            q[j], _ = mechanism.solve(leg, body, q[j],
                row['target_foot_reference_xy_mm'][j], row['target_sole_clearance_mm'][j])
        row.update(body_translation_world_mm=body.tolist(),
                   body_rotation_euler_xyz_rad=euler.tolist(), actuator_angles_rad=q.tolist())
        entry.append(row)

    lift = np.deg2rad([-54.882981602214706, -18.84378232264318, -39.58767469151016])
    extended = np.deg2rad([-58.05184658711478, 48.8306052678101, 11.44430141980432])
    seated = np.array(entry[-1]['actuator_angles_rad'][2])
    blend = lambda a, b, u: a + (b-a) * ref.smooth(float(np.clip(u, 0., 1.)))
    rows = []
    for i in range(round(timing['clip_end'] * 120) + 1):
        t = i / 120
        if i <= 144:
            row = copy.deepcopy(entry[i])
        elif i >= 576:
            row = copy.deepcopy(entry[max(0, 720-i)])
        else:
            row = copy.deepcopy(entry[-1])
            if t <= 1.6:
                arm = blend(seated, lift, (t-1.2)/.4)
            elif t <= 2.:
                arm = blend(lift, extended, (t-1.6)/.4)
            elif t <= 4.:
                arm = extended.copy()
                envelope = ref.smooth(min(1., (t-2.)/.2, (4.-t)/.2))
                arm[0] += np.deg2rad(42.) * np.sin(3*np.pi*(t-2.)) * envelope
            elif t <= 4.4:
                arm = blend(extended, lift, (t-4.)/.4)
            else:
                arm = blend(lift, seated, (t-4.4)/.4)
            row['actuator_angles_rad'][2] = arm.tolist()
            row['contact_active'] = [True, True, False, True]
        phase = next((p for p in phases if t < p['end']), phases[-1])
        euler = row['body_rotation_euler_xyz_rad']
        quat = Rotation.from_euler('xyz', euler).as_quat()
        row.update(time_s=t, phase=phase['kind'],
                   phase_fraction=(t-phase['start'])/(phase['end']-phase['start']),
                   body_orientation_world_quaternion_wxyz=[float(quat[3]), *quat[:3]],
                   body_yaw_world_rad=euler[2])
        rows.append(row)

    description = ('Seated bare-Part027 Wave: sequential seating, quick front-left lift, '
                   'three broad shoulder waves, foot replacement and standing recovery.')
    posture = read(folder / 'posture.json')
    for key in ['linkage_remap', 'calibrated_motion_revision', 'knee_to_ankle_local_unit']:
        posture.pop(key, None)
    posture.update(description=description, contact_hulls_file='contact-hulls.npz',
        contact_hulls_sha256=digest(folder/'contact-hulls.npz'),
        posture_sample_time_s=1.2, shoulder_wave_amplitude_deg=42., wave_cycles=3,
        wave_envelope_seconds=.2, timing_s=timing, grounded_legs=['FL', 'FR', 'RR'],
        lift_joint_offsets_deg=np.rad2deg(lift).tolist(),
        extended_joint_offsets_deg=np.rad2deg(extended).tolist(),
        seated_body_translation_mm=entry[-1]['body_translation_world_mm'],
        seated_body_pitch_deg=-25.5, bare_contact_source_sha256=digest(contact))
    for kind in ['source', 'posture']:
        posture['base_motion'][kind+'_sha256'] = digest(family/'sit'/(kind+'.json'))
    write(folder/'posture.json', posture)
    source = read(folder/'source.json')
    metadata = source['metadata']
    for key in ['linkage_remap', 'calibrated_motion_revision', 'baseline_validation']:
        metadata.pop(key, None)
    metadata.update(generator='tools/author_expressive_wave.py', contact_model='Bare Part027 hull minimum Z; complete body hull; assumed COM.',
        authoring=dict(sit_source_sha256=digest(family/'sit/source.json'),
        geometry_sha256=digest(root/'geometry.json'), contact_source_sha256=digest(contact),
        scope=description, hardware_qualified=False))
    source.update(samples=rows, phases=phases, validation={})
    write_source(source)
    refresh_metrics(root, ['wave'])
    source = read(folder/'source.json'); rows = source['samples']
    q = np.array([r['actuator_angles_rad'] for r in rows])
    velocity = np.gradient(q, 1/120, axis=0)
    acceleration = np.gradient(velocity, 1/120, axis=0)
    cal = read(calibration); joints = cal.get('calibration', cal)['joints']
    pulses = np.zeros((len(rows), 12))
    for j in joints:
        pulses[:, j['id']] = j['home_us'] + (np.rad2deg(q.reshape(-1, 12)[:, j['id']])
            - j['home_cd']/100) * j['us_per_degree'] * (-1 if j['invert'] else 1)
    v = source['validation']
    v.update(command='wave', duration_s=6.2, motion_end_s=6., samples=len(rows), sample_hz=120,
        geometry_id=cfg['geometry_id'], peak_joint_speed_deg_s=float(np.rad2deg(abs(velocity)).max()),
        joint_min_deg=np.rad2deg(q.min(0)).tolist(), joint_max_deg=np.rad2deg(q.max(0)).tolist(),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows if r['support_margin_mm'] is not None),
        minimum_wave_support_margin_mm=min(r['support_margin_mm'] for r in rows[145:576]),
        minimum_waving_foot_clearance_mm=min(r['sole_clearance_mm'][2] for r in rows[240:481]),
        mapped_pulse_min_us=float(pulses.min()), mapped_pulse_max_us=float(pulses.max()),
        reviewed_pulse_window_us=[400, 2900], collision_checked=False, hardware_qualified=False,
        qualification='Offline geometry and installed pulse mapping only; loaded tracking and whole-body collision unqualified.')
    write(folder/'validation.json', v)
    write_source(source)
    manifest = read(folder/'manifest.json')
    manifest.update(gait_id='wave_playful_bare_35_20_28_20261015', generated_utc='2026-10-15',
        duration_seconds=6.2, motion_end_seconds=6., sample_count=len(rows),
        source_sha256=digest(folder/'source.json'), posture_sha256=digest(folder/'posture.json'),
        posture_hulls_sha256=digest(folder/'contact-hulls.npz'),
        entry_actuator_angles_rad=rows[0]['actuator_angles_rad'], final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
        entry_pose='Bare-Part027 standing pose; existing executor owns entry interpolation.',
        source_validation=v, contact_model=metadata['contact_model'], retargeting_notes=description,
        body_target=dict(position_mm=rows[-1]['body_position_world_mm'], euler_xyz_rad=rows[-1]['body_rotation_euler_xyz_rad']))
    manifest['face_cues'][-1]['time_s'] = 6.
    manifest['current_mounting_qualification'] = (
        'Wave refitted to bare Part027 and checked against installed pulse mapping; '
        'whole-body collision and loaded behavior remain unqualified.')
    manifest.pop('blender_workspace_file', None)
    manifest.pop('blender_scene', None)
    write(folder/'manifest.json', manifest)
    schema = read(folder/'schema.json')
    schema.update(wave_posture=description, contact_model=metadata['contact_model'])
    write(folder/'schema.json', schema)
    config = read(folder/'config.json')
    config['geometry_id'] = cfg['geometry_id']
    write(folder/'config.json', config)
    contract = read(folder/'execution-contract.json')
    contract.update(gait_id=manifest['gait_id'], face_cues=manifest['face_cues'], phases=[], contact_events=[])
    for i, p in enumerate(phases):
        a, b = round(p['start']*120), round(p['end']*120)
        contacts = np.array([r['contact_active'] for r in rows[a:b+1]])
        contract['phases'].append(dict(id=f'p{i:03d}_{p["kind"]}', name=p['kind'], section='clip',
            source_interval_s=[p['start'],p['end']], source_sample_indices_inclusive=[a,b],
            demonstration_duration_s=p['end']-p['start'],
            supporting_legs_throughout=[l for j,l in enumerate(LEGS) if contacts[:,j].all()],
            contact_states=np.unique(contacts,axis=0).tolist(),
            moving_joint_indices=np.flatnonzero(np.ptp(q[a:b+1].reshape(-1,12),axis=0)>1e-6).tolist(),
            coordination='whole_body_shared_clock',
            reference_peak_speed_rad_s=abs(velocity[a:b+1]).max(0).ravel().tolist(),
            reference_peak_acceleration_rad_s2=abs(acceleration[a:b+1]).max(0).ravel().tolist()))
    for name, profile in contract['timing_profiles'].items():
        profile['duration_s']={p['id']:None if name=='operating' else p['demonstration_duration_s'] for p in contract['phases']}
    for i,r in enumerate(rows):
        if i==0 or r['contact_active']!=rows[i-1]['contact_active']:
            contract['contact_events'].append(dict(source_time_s=r['time_s'],sample_index=i,
                active=r['contact_active'],body_contact_active=r['body_contact_active'],support_source='feet'))
    contract['entry'].update(joint_angles_rad=rows[0]['actuator_angles_rad'],
        body_position_world_mm=rows[0]['body_position_world_mm'],
        body_orientation_world_quaternion_wxyz=rows[0]['body_orientation_world_quaternion_wxyz'])
    contract['completion']['joint_angles_rad']=rows[-1]['actuator_angles_rad']
    for f in contract['source_files']:
        f['sha256']=digest(folder/Path(f['path']).name)
    write(folder/'execution-contract.json',contract)
    for name in ['interpolation-validation.json', 'blender-validation.json']:
        write(folder/name,dict(status='pending_current_source_validation',source_sha256=digest(folder/'source.json')))
    catalog=read(family/'catalog.json')
    item=next(e for e in catalog['commands'] if e['command']=='wave')
    item['sha256']['contact-hulls.npz']=digest(folder/'contact-hulls.npz')
    for name in item['sha256']:
        item['sha256'][name]=digest(folder/name)
    (family/'catalog.json').write_text(json.dumps(catalog,separators=(',',':'))+'\n')
    print(json.dumps(v,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--calibration',type=Path,required=True)
    args=parser.parse_args()
    author(args.root.resolve(),args.calibration)
