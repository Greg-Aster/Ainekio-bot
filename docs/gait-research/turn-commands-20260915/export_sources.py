"""Produce separate timestamped command sources, manifests and integration notes."""
import csv
import datetime
import hashlib
import json
import math
from pathlib import Path
from generate_turns import COMMANDS, config, write_source

P=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(command):
    folder=P/'commands'/command
    data=json.loads((folder/'source.json').read_text())
    # Refresh provenance and phase fractions without changing any joint/body track.
    data['metadata']['configuration'].update(config(command))
    write_source(command,data)
    cfg=data['metadata']['configuration'];v=data['validation'];legs=data['metadata']['leg_order']
    columns=['time_s','time_us','phase','phase_fraction','cycle','swing_leg']
    columns += ['body_'+a+'_mm' for a in 'xyz']+['body_q'+a for a in 'wxyz']+['body_yaw_rad']
    columns += ['assumed_com_'+a+'_mm' for a in 'xyz']+['support_margin_mm']
    for leg in legs:
        columns += [f'{leg}_{j}_rad' for j in ['h002','alpha006','theta005']]
        columns += [f'{leg}_foot_bolt_{a}_mm' for a in 'xyz']+[f'{leg}_sole_contact_{a}_mm' for a in 'xyz']
        columns += [f'{leg}_contact_active',f'{leg}_sole_clearance_mm',f'{leg}_part023_angle_deg']
    with (folder/'source.csv').open('w',newline='') as f:
        out=csv.writer(f);out.writerow(columns)
        for r in data['samples']:
            row=[r['time_s'],round(r['time_s']*1e6),r['phase'],r['phase_fraction'],r['cycle'],r['swing_leg'] or '']
            row+=r['body_position_world_mm']+r['body_orientation_world_quaternion_wxyz']+[r['body_yaw_world_rad']]
            row+=r['assumed_com_world_mm']+[r['support_margin_mm']]
            for i in range(4):
                row+=r['actuator_angles_rad'][i]+r['foot_bolt_world_mm'][i]+r['contact_world_mm'][i]
                row+=[int(r['contact_active'][i]),r['sole_clearance_mm'][i],r['part023_OD_angle_from_forward_degrees'][i]]
            out.writerow(row)
    par=json.loads((P/'robot-gait-parameters.json').read_text())
    schema=dict(command=command,columns=columns,leg_order=legs,joint_order=data['metadata']['joint_order'],
        physical_leg_mapping={l:par['legs'][l]['physical_name'] for l in legs},
        units=dict(length='mm',angles='radians except *_angle_deg diagnostic',time='seconds; time_us rounded integer microseconds'),
        coordinates='World X initial forward, Y initial left, Z up. Right yaw negative; left yaw positive. Quaternion wxyz.',
        source_sample_hz=120,contact_model=cfg['contact_model'],com=cfg['com'],servo_calibration=None,
        sample_timing='Use rational index elapsed_us*120/1000000; rounded CSV timestamps do not redefine the sample interval.',
        interpolation='Monotone cubic Hermite with harmonic secant tangents; first and last tangents zero. C1, not guaranteed C2.',
        actuator_zero='Corrected CAD neutral. Part005 re-clocking is already included.',
        positive_axes={'h002':'CAD +X / body +X','alpha006':'CAD +Z / body +Y','theta005':'CAD +Z / body +Y'})
    (folder/'schema.json').write_text(json.dumps(schema,indent=2)+'\n')
    manifest=dict(command=command,wire={'t':'intent','name':'emote','asset':command},
        new_body_control_command=command.endswith('_15'),gait_id=cfg['gait_id'],duration_seconds=v['duration_s'],
        source_sample_hz=120,sample_count=v['samples'],heading_change_degrees=cfg['yaw_degrees'],
        turn_source_seconds=v['turn_time_range_s'],turn_cycles=cfg['turn_cycles'],cycle_seconds=cfg['cycle_seconds'],
        entry_pose='CAD neutral with all feet supported; arbitrary current-pose entry has not been qualified.',
        final_actuator_angles_rad=data['samples'][-1]['actuator_angles_rad'],
        completion='Hold final recorded pose. Finite command, not a periodic loop. No invented zero-angle reset.',
        hardware_qualified=False,calibration=None,source_sha256=sha(folder/'source.json'),csv_sha256=sha(folder/'source.csv'),
        geometry_sha256=sha(P/'robot-gait-parameters.json'),sole_hulls_sha256=sha(P/'sole-hulls.npz'),
        blender_file=Path(cfg['output_blend']).name,blender_workspace_file=str(P/cfg['output_blend']),blender_in_source_archive=False,
        mirror_partner=command.replace('_left_','_right_') if '_left_' in command else command.replace('_right_','_left_'),
        source_validation=v)
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    title=command.replace('_',' ')
    text=f'''# {title}

**{abs(cfg['yaw_degrees']):g} degrees {cfg['direction']}; {v['duration_s']:g} seconds total.**
This is a separate twelve-servo geometric source for firmware and Body Control integration.

- Semantic command: `{command}`; envelope `{json.dumps(manifest['wire'],separators=(',',':'))}`.
- 120 Hz, {v['samples']} rows. Entry 0–5 s, turning 5–{v['turn_time_range_s'][1]:g} s, then six seconds of settling.
- {cfg['turn_cycles']} four-leg cycles; {abs(cfg['yaw_degrees'])/cfg['turn_cycles']:g} degrees per cycle. A cycle alternates four 0.5 s supported body shifts and four 0.5 s single-leg swings.
- Body height 78 mm, actual sole lift 5 mm. The center returns to its initial XY position.
- CAD leg step order: {', '.join(cfg['cad_leg_order'])}. Export column order: FL, FR, RL, RR; each h002, alpha006, theta005.
- FL/FR are physical rear left/right; RL/RR are physical front left/right.
- Angle signs and zero are geometric. No pulse widths, electrical centers or PCA9685 channels are assigned.

## Files

- `source.json`: complete body pose, twelve actuators, passive linkage angle, foot targets, sole contacts, contact states, COM assumption and phases.
- `source.csv` / `schema.json`: flat timestamped export and explicit units/order.
- `config.json`: independently adjustable recipe; shared geometry/solver are two directories above.
- `manifest.json`: command mapping, duration, final pose and provenance hashes.
- `validation.json`: complete sampled ranges and speed/acceleration estimates.
- `blender-validation.json`: evaluated mechanism and sole comparison, including poses between keys.
- `{manifest['blender_file']}`: full animation after the preserved range tests, beginning at frame 529.

## Qualification

The assumed-COM minimum support margin is **{v['minimum_support_margin_mm']:.3f} mm**; a negative value means the projection leaves the support triangle. Static balance is therefore unqualified.
Peak sampled actuator speed is {max(max(x) for x in v['actuator_peak_speed_degrees_s']):.3f} degrees/s. These are kinematic demands, not demonstrated servo capability.
Foot rolling retains a world-fixed sole vertex until the supporting feature changes; point-contact yaw is permitted. Friction, yaw scrub, full collision clearance, measured mass, loaded servo limits and dynamics remain unverified.
The final recorded standing pose differs slightly from CAD zero. Integrators must handle current-pose entry, hold/stop and command-to-command transitions; do not concatenate sources with a jump.

{'This 15-degree semantic command is new: add it to the existing Body Control catalog and model capabilities during integration.' if command.endswith('_15') else 'The existing Body Control semantic name can be retained; select this source only for the twelve-servo model.'}
'''
    (folder/'README.md').write_text(text)
    return dict(command=command,heading_degrees=cfg['yaw_degrees'],duration_s=v['duration_s'],samples=v['samples'],
                minimum_support_margin_mm=v['minimum_support_margin_mm'],new_command=manifest['new_body_control_command'],
                path='commands/'+command,source_sha256=manifest['source_sha256'])


if __name__=='__main__':
    records=[export(command) for command in COMMANDS]
    (P/'catalog.json').write_text(json.dumps(dict(generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        family='Ainekio twelve-servo finite turns',commands=records,hardware_qualified=False),indent=2)+'\n')
    print('EXPORTED',len(records),'independent command sources')
