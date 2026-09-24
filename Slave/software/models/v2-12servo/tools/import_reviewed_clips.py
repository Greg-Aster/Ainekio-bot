"""Import approved Blender recordings into the existing compact clip pipeline.

The retained 30 Hz recording is the authoring source. Resampling preserves its
joint keys and Blender root transforms; no inverse kinematics retargets or
reduces the approved movement. CAD support geometry stays on the workstation.
"""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
from retarget_clips import digest, load_reference, support_margin, write, LEGS


def import_clips(root, commands=None):
    family = root / 'motions/gestures'
    cfg = json.loads((root / 'geometry.json').read_text())
    geometry_hash = digest(root / 'geometry.json')
    pivot = np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    hull_path = family / 'reviewed-hulls.npz'
    hulls = np.load(hull_path)
    mechanism = load_reference(root).Mechanism(cfg)
    mechanism.hulls = {leg: hulls['sole_' + leg] for leg in LEGS}
    policy_hash = digest(family / 'execution-policy.json')
    catalog = json.loads((family / 'catalog.json').read_text())
    reference = (family / 'sit/sample_reference.py').read_text()
    for path in sorted(family.glob('*/reviewed.json')):
        clip = json.loads(path.read_text())
        name = clip['command']
        if commands and name not in commands:
            continue
        if clip['geometry_sha256'] != geometry_hash:
            raise ValueError(f'{name}: reviewed geometry changed; review a new recording')
        folder = path.parent
        samples = clip['samples']
        hz = clip['sample_hz']
        if hz != 30 or any(abs(r['time_s'] - i / hz) > 1e-7 for i, r in enumerate(samples)):
            raise ValueError(f'{name}: expected the reviewed uniform 30 Hz clock')
        duration = (len(samples) - 1) / hz
        body = np.array([r['body'] for r in samples])
        angles = np.array([r['q'] for r in samples])
        eulers = np.array([r['euler'] for r in samples])
        matrices = Rotation.from_euler('xyz', eulers).as_matrix()
        roots = body + pivot - matrices @ pivot
        rows = []
        closure = float('inf')
        phases = []
        for i in range(round(duration * 120) + 1):
            lo = min(i // 4, len(samples) - 2)
            u = (i - lo * 4) / 4
            q = angles[lo] * (1-u) + angles[lo+1] * u
            e = eulers[lo] * (1-u) + eulers[lo+1] * u
            rotation = Rotation.from_euler('xyz', e)
            matrix = rotation.as_matrix()
            b = roots[lo] * (1-u) + roots[lo+1] * u - pivot + matrix @ pivot
            mechanism.body_euler = e
            feet, contacts, sole, indices, betas = [], [], [], [], []
            for leg, joints in zip(LEGS, q):
                vs = mechanism.vertices(leg, joints, b)
                k = int(vs[:, 2].argmin())
                feet.append(mechanism.reference(leg, joints, b).tolist())
                contacts.append(vs[k].tolist())
                sole.append(float(vs[k, 2]))
                indices.append(k)
                planar = mechanism.planar(joints)
                betas.append(float(planar[3] - mechanism.b0))
                closure = min(closure, planar[4])
            active = samples[min(i // 4, len(samples)-1)]['contact']
            clear = float(((hulls['body'] - pivot) @ matrix[2] + pivot[2] + b[2]).min())
            phase = samples[min(i // 4, len(samples)-1)]['phase']
            if not phases or phases[-1]['kind'] != phase:
                if phases:
                    phases[-1]['end'] = i / 120
                phases.append(dict(start=i/120, end=duration, kind=phase))
            rows.append(dict(time_s=i/120, phase=phase, body_translation_world_mm=b.tolist(),
                body_position_world_mm=(b+pivot).tolist(), body_rotation_euler_xyz_rad=e.tolist(),
                body_orientation_world_quaternion_wxyz=rotation.as_quat(scalar_first=True).tolist(),
                body_yaw_world_rad=float(e[2]), actuator_angles_rad=q.tolist(), passive_beta_rad=betas,
                foot_bolt_world_mm=feet, contact_world_mm=contacts, contact_vertex_index=indices,
                contact_active=active, sole_clearance_mm=sole, body_ground_clearance_mm=clear,
                body_contact_active=clear < .05, body_contact_polygon_world_mm=[],
                support_source='body_and_feet' if clear < .05 else 'feet',
                assumed_com_world_mm=(b+pivot).tolist(),
                support_margin_mm=support_margin([p for p, on in zip(contacts, active) if on], b+pivot),
                target_foot_reference_xy_mm=[p[:2] for p in feet], target_sole_clearance_mm=sole))
        phases = [p for p in phases if p['end'] > p['start']]
        report = dict(command=name, samples=len(rows), duration_s=duration, sample_hz=120,
            geometry_id=cfg['geometry_id'], min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
            minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),
            minimum_closure_triangle_height_mm=float(closure), hardware_qualified=False,
            collision_checked=False, reviewed_joint_keys_preserved=True,
            motion_end_s=duration, max_target_error_mm=0.,
            peak_joint_speed_deg_s=float(np.rad2deg(abs(np.diff(angles, axis=0))).max()*hz))
        assert report['min_sole_height_mm'] > -.25 and report['minimum_body_ground_clearance_mm'] > -.05 and closure > 0, report
        metadata = dict(configuration=dict(command=name, sample_hz=120, geometry_id=cfg['geometry_id']),
            leg_order=LEGS, joint_order=cfg['joint_order'], angle_units='radian', position_units='mm',
            time_units='second', authoring_source='reviewed.json', authoring_sha256=digest(path),
            generator='tools/import_reviewed_clips.py',
            body_position_datum='Root geometry rotation pivot plus translation.')
        source = dict(metadata=metadata, phases=phases, samples=rows, validation=report)
        (folder/'source.json').write_text(json.dumps(source, separators=(',', ':'), allow_nan=False)+'\n')
        write(folder/'validation.json', report)
        posture = dict(description=clip['description'], mechanism_geometry_sha256=geometry_hash,
            contact_hulls_file='../reviewed-hulls.npz', contact_hulls_sha256=digest(hull_path),
            body_support_scope='Measured Blender body and lower-leg surfaces; physical balance unqualified.')
        write(folder/'posture.json', posture)
        wire = dict(t='intent', name='emote', asset=name)
        gait_id = name + '_reviewed_expression'
        completion = 'Hold the grounded terminal pose until another command.' if name in ('dead', 'lay_down') else 'Return to the recorded standing pose.'
        manifest = dict(command=name, body_control_label=clip['label'], wire=wire, gait_id=gait_id,
            duration_seconds=duration, semantic_end_seconds=duration, source_sample_hz=120,
            sample_count=len(rows), entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],
            semantic_final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
            playlist_final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
            geometry_id=cfg['geometry_id'], geometry_sha256=geometry_hash,
            sole_hulls_sha256=digest(root/'motions/turns/sole-hulls.npz'), source_sha256=digest(folder/'source.json'),
            posture_sha256=digest(folder/'posture.json'), posture_hulls_sha256=posture['contact_hulls_sha256'],
            reviewed_sha256=digest(path), hardware_qualified=False, actuator_calibration=None,
            completion=completion, source_validation=report,
            blender_workspace_file='Slave/hardware/v2-12servo/ainekio-variable-gait-Recovery.blend',
            blender_scene='Motions - Current Geometry')
        write(folder/'manifest.json', manifest)
        schema = dict(command=name, geometry_id=cfg['geometry_id'], leg_order=LEGS,
            joint_order=cfg['joint_order'], sample_hz=120, semantic_end_s=duration,
            optional_demonstration_recovery=False, sample_fields=list(rows[0]),
            interpolation='Monotone cubic Hermite; compiled error bound 0.005 degree.',
            units=dict(angle='radian', position='mm', time='second'))
        write(folder/'schema.json', schema)
        contract_phases = [dict(id=f'p{i:03d}', name=p['kind'], section='clip', execution_role='command',
            source_interval_s=[p['start'],p['end']]) for i,p in enumerate(phases)]
        durations = {p['id']:p['source_interval_s'][1]-p['source_interval_s'][0] for p in contract_phases}
        owner = 'Slave/software/models/v2-12servo/motions/gestures/' + name
        contract = dict(command=name, gait_id=gait_id, wire=wire, policy_sha256=policy_hash,
            source_files=[dict(path=owner+'/'+n, sha256=digest(folder/n)) for n in ('source.json','manifest.json')],
            source_units=dict(angle='radian', position='mm', time='second'), source_sample_hz=120,
            leg_order=LEGS, joint_order=cfg['joint_order'], phases=contract_phases,
            timing_profiles=dict(demonstration=dict(duration_s=durations), research_candidate=dict(duration_s=durations)),
            repeat=dict(section=None,minimum=1,maximum=1), face_cues=[],
            entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad']),
            completion=dict(joint_angles_rad=rows[-1]['actuator_angles_rad'], contacts=rows[-1]['contact_active'],
                semantic_end_s=duration, optional_demo_recovery_end_s=None, behavior=completion), hardware_ready=False)
        write(folder/'execution-contract.json', contract)
        (folder/'sample_reference.py').write_text(reference.replace("command='sit'", f"command='{name}'"))
        files = ('reviewed.json','source.json','manifest.json','schema.json','execution-contract.json',
                 'posture.json','validation.json','sample_reference.py')
        entry = dict(command=name, path=name, handoff=owner, execution_handoff=owner+'/execution-contract.json',
            sha256={n:digest(folder/n) for n in files})
        old = next((i for i,e in enumerate(catalog['commands']) if e['command']==name), None)
        if old is None: catalog['commands'].append(entry)
        else: catalog['commands'][old] = entry
        print(name, report, flush=True)
    write(family/'catalog.json', catalog)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--recording', type=Path)
    parser.add_argument('--hulls', type=Path)
    parser.add_argument('--commands', nargs='+')
    args = parser.parse_args()
    if args.recording:
        recording = json.loads(args.recording.read_text())
        for clip in recording['clips']:
            if args.commands and clip['command'] not in args.commands: continue
            clip = copy.deepcopy(clip)
            clip['sample_hz'] = recording['fps']
            clip['geometry_sha256'] = digest(args.root/'geometry.json')
            folder = args.root/'motions/gestures'/clip['command']
            folder.mkdir(exist_ok=True)
            write(folder/'reviewed.json', clip)
    if args.hulls:
        raw = np.load(args.hulls)
        points = {**{'sole_'+l:raw[l] for l in LEGS}, 'body':np.vstack((raw['base'], raw['body']))}
        np.savez_compressed(args.root/'motions/gestures/reviewed-hulls.npz',
            **{k:v[ConvexHull(v).vertices] for k,v in points.items()})
    import_clips(args.root, args.commands)
