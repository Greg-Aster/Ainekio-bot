"""Compile the measured current walk geometry; standard Python, no runtime IK here.

The firmware uses direct circle intersections and a compact sole profile.
Reference Python and Blender evidence retain their own source identities.
"""
import argparse,hashlib,json,math
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_walk(root,out):
    folder=root/'motions/walk'
    manifest=json.loads((folder/'manifest.json').read_text())
    if set(manifest['sha256'])!={'reference.py','../../geometry.json','../locomotion/config.json','source.json'}:raise ValueError('incomplete walk provenance')
    if manifest['source_leg_order']!=['RL','RR','FL','FR'] or manifest['model_leg_order']!=['FL','FR','RL','RR'] or manifest['model_from_source_legs']!=[2,3,0,1]:raise ValueError('manifest joint mapping mismatch')
    for name,expected in manifest['sha256'].items():
        if digest(folder/name)!=expected:raise ValueError(f'walk provenance mismatch: {name}')
    cfg=json.loads((root/'geometry.json').read_text());p=cfg['parameters']
    low=json.loads((root/'motions/locomotion/config.json').read_text())
    contacts=json.loads((root/'motions/locomotion/contact-hulls.json').read_text())
    sole=json.loads((root/'motions/locomotion/sole-profile.json').read_text())
    if sole['geometry_sha256']!=digest(root/'geometry.json') or sole['contact_source_sha256']!=digest(root/'motions/locomotion/contact-hulls.json'):raise ValueError('compact sole provenance')
    if low['geometry_sha256']!=digest(root/'geometry.json') or low['hardware_qualified'] is not False:raise ValueError('locomotion geometry provenance')
    if contacts['source_sha256']!=digest(root/'motions/gestures/sit/posture-hulls.npz'):raise ValueError('locomotion hull provenance')
    if cfg['leg_order']!=['RL','RR','FL','FR'] or cfg['joint_order']!=['h_Part002','alpha_Part006','theta_Part005']:
        raise ValueError('walk joint mapping mismatch')
    if manifest['hardware_qualified'] is not False:raise ValueError('unqualified source cannot arm hardware')
    model=json.loads((root/'model.json').read_text())
    if model['model']!='v2-12servo' or [j['cad_leg'] for j in model['joints']]!=[l for l in ['FL','FR','RL','RR'] for _ in range(3)]:raise ValueError('model order changed')
    def array(values, single=True):
        if isinstance(values,list):return '{'+','.join(array(v, single) for v in values)+'}'
        if not math.isfinite(values):raise ValueError('nonfinite geometry')
        return format(values,'.9e')+'f' if single else format(values,'.17e')
    header=['/* Generated measured walk geometry. No electrical assignments. */','#ifndef V2_WALK_DATA_H','#define V2_WALK_DATA_H','#include "ainekio/v2_walk.h"',
      'typedef struct { const float (*points)[3]; unsigned count; float allowance; } v2_sole_profile_t;',
      'typedef struct { float shoulder_sign[3],shoulder_translation[3],mechanism_translation[3],reference[3],mirror; } v2_walk_leg_t;',
      'extern const v2_walk_leg_t v2_walk_legs[4];','extern const v2_sole_profile_t v2_walk_sole,v2_crawl_sole;',
      'extern const float v2_walk_pivot[3];','extern const double v2_walk_stance[4][2],v2_walk_offsets[4];']
    for key,value in {'O_X':p['O'][0],'O_Z':p['O'][1],'C_X':p['C_new'][0],'C_Z':p['C_new'][1],'PRIMARY':p['primary_length'],'INPUT':p['input_length'],'ROD':p['rod_length'],'PICKUP':p['pickup_length'],'ALPHA_ZERO':p['alpha_neutral'],'THETA_ZERO':p['new_theta_neutral'],'BETA_ZERO':p['beta_neutral'],'BRANCH':p['assembly_branch'],'BETA_C':math.cos(p['beta_neutral']),'BETA_S':math.sin(p['beta_neutral'])}.items():header.append(f'#define V2_{key} ({value:.9e}f)')
    for key,value in {'PERIOD':cfg['gait_controls']['base_cycle_seconds'],'DUTY':cfg['ground_contact_fraction'],'SWEEP':cfg['continuous_walk']['stance_sweep_100_mm'],'BIAS':cfg['continuous_walk']['rearward_bias_100_mm'],'SWAY':cfg['continuous_walk']['lateral_sway_mm'],'BOB':cfg['continuous_walk']['body_bob_mm'],'ROLL':math.radians(cfg['continuous_walk']['roll_deg']),'PITCH':math.radians(cfg['continuous_walk']['pitch_deg']),'STAND_BODY_Z':cfg['body_translation_z_mm'],'BODY_Z':low['walk']['body_z_mm'],'MIN_LIFT':cfg['continuous_walk']['minimum_lift_mm'],'LIFT':cfg['sole_clearance_mm']}.items():header.append(f'#define V2_{key} ({value:.17e})')
    for key,field in {"WALK_SWEEP":"stance_sweep_mm","WALK_BIAS":"rearward_bias_mm","WALK_LIFT":"lift_mm","WALK_BODY_SCALE":"body_motion_scale","WALK_TRANSITION":"transition_cycles"}.items():
        header.append(f"#define V2_{key} ({low['walk'][field]:.17e})")
    run=json.loads((root/'motions/run/config.json').read_text())
    if run['geometry_sha256']!=digest(root/'geometry.json') or run['hardware_qualified'] is not False:raise ValueError('run geometry provenance')
    if run['mounting_profile_sha256']!=digest(root/'servo_profile.json'):raise ValueError('Run mounting profile changed; revalidate reach')
    if run['forward']['lane_assignment']!='physical_front_inside_rear_outside' or not 0<=run['forward']['lane_offset_mm']<=20:raise ValueError('unsupported Run lane assignment')
    if not 0<run['ground_contact_fraction']<.5 or [run['phase_offsets'][l] for l in cfg['leg_order']]!=[0,0,.5,.5]:raise ValueError('run must alternate front/rear pairs with flight')
    for key,value in {'RUN_FORWARD_PITCH':math.radians(run['forward']['pitch_deg']),'RUN_FORWARD_PITCH_PHASE':2*math.pi*run['forward']['pitch_phase_cycles'],'RUN_START_SWEEP':run['initial_sweep_mm'],'RUN_SWING_RAMP':run['swing_ramp_fraction'],'RUN_FORWARD_PITCH_BIAS':math.radians(run['forward']['pitch_bias_deg']),'RUN_FORWARD_LANE':run['forward']['lane_offset_mm'],'RUN_FORWARD_SWEEP':run['forward']['sweep_mm'],'RUN_FORWARD_BIAS':run['forward']['rearward_bias_mm'],'RUN_FORWARD_BODY_Z':run['forward']['body_z_mm'],'RUN_TRANSITION':run['transition_cycles'],'RUN_PERIOD':run['base_cycle_seconds'],'RUN_DUTY':run['ground_contact_fraction'],'RUN_SWEEP':run['sweep_mm'],'RUN_BIAS':run['rearward_bias_mm'],'RUN_LIFT':run['lift_mm'],'RUN_MIN_LIFT':run['minimum_lift_mm'],'RUN_BODY_Z':run['body_z_mm'],'RUN_BOB':run['bob_mm'],'RUN_PITCH':math.radians(run['pitch_deg']),'RUN_TURN':math.radians(run['turn_degrees_per_cycle'])}.items():header.append(f'#define V2_{key} ({value:.17e})')
    for key,value in low['leverage_validation'].items():
        if key!='scope':header.append(f'#define V2_CHECK_{key.upper()} ({value:.17e})')
    crawl=low['crawl']
    crab=json.loads((root/'motions/locomotion/crab.json').read_text())
    if crab['geometry_sha256']!=digest(root/'geometry.json') or crab['hardware_qualified'] is not False:raise ValueError('Crab geometry provenance')
    for key,field in {'STARTUP_CYCLES':'startup_cycles','BODY_Z':'body_z_mm','ENTRY':'entry_seconds','WIDTH':'stance_half_width_mm','PERIOD':'period_seconds','SWEEP':'sweep_mm','SIDE_SWEEP':'side_sweep_mm','LIFT':'lift_mm','MIN_LIFT':'minimum_lift_mm'}.items():
        header.append(f'#define V2_CRAB_{key} ({crab[field]:.17e})')
    header.append(f"#define V2_CRAB_TURN ({math.radians(crab['turn_degrees_per_cycle']):.17e})")
    header.append('static const double v2_crab_offsets[4] = {'+','.join(map(str,crab['phase_offsets']))+'};')
    for key,value in {'WALK_TURN':math.radians(low['walk_turn_degrees_per_cycle']),'CRAWL_TURN':math.radians(crawl['turn_degrees_per_cycle']),'CRAWL_BODY_Z':crawl['body_z_mm'],'CRAWL_ENTRY':crawl['entry_seconds'],'CRAWL_SWEEP':crawl['sweep_mm'],'CRAWL_BIAS':crawl['rearward_bias_mm'],'CRAWL_LIFT':crawl['lift_mm'],'CRAWL_MIN_LIFT':crawl['minimum_lift_mm'],'CRAWL_SWAY':crawl['sway_mm'],'CRAWL_BOB':crawl['bob_mm'],'CRAWL_ROLL':math.radians(crawl['roll_deg']),'CRAWL_PITCH':math.radians(crawl['pitch_deg'])}.items():header.append(f'#define V2_{key} ({value:.17e})')
    code=['#include "walk_data.h"',f'const char ainekio_v2_walk_id[] = {json.dumps(manifest["gait_id"])};',
          'const bool ainekio_v2_walk_hardware_qualified = false;',f'const char ainekio_v2_walk_geometry_id[] = {json.dumps(manifest["geometry_id"])};',
          'const ainekio_v2_joint_t ainekio_v2_joints[AINEKIO_V2_JOINT_COUNT] = {']
    code += ['{'+','.join(json.dumps(j[k]) for k in ('name','cad_leg','actuator','positive_body_axis'))+'},' for j in model['joints']]
    code+=['};']
    for name,values in [('pivot',cfg['continuous_walk']['body_rotation_pivot_mm']),('stance',cfg['reference_stance_xy_mm']),('offsets',[cfg['continuous_walk']['phase_offsets'][l] for l in cfg['leg_order']])]:
        dimensions={'pivot':'[3]','stance':'[4][2]','offsets':'[4]'}
        code.append(f'const {"float" if name=="pivot" else "double"} v2_walk_{name}{dimensions[name]} = {array(values, name=="pivot")};')
    for kind in ['walk','crawl']:
        points=sole['profiles'][kind]
        if not 4<=len(points)<=128:raise ValueError('compact sole budget')
        code.append(f'static const float {kind}_sole_points[][3] = {array(points)};')
        code.append(f'const v2_sole_profile_t v2_{kind}_sole = '+'{'+f'{kind}_sole_points,{len(points)},{array(sole["support_allowance_mm"])}'+'};')
    code.append('const v2_walk_leg_t v2_walk_legs[4] = {')
    for leg in cfg['leg_order']:
        g=cfg['legs'][leg];S=g['shoulder_world'];M=g['mechanism_local']
        signs=[round(S[i][i]) for i in range(3)];mirror=round(M[0][0])
        for i in range(3):
            for j in range(3):
                if abs(S[i][j]-(signs[i] if i==j else 0))>1e-5 or abs(M[i][j]-((mirror if i==0 else 1) if i==j else 0))>1e-5:raise ValueError('unsupported robot axes')
        values=[array(signs),array([r[3] for r in S[:3]]),array([r[3] for r in M[:3]]),array(g['foot_reference_local_mm']),array(mirror)]
        code.append('{'+','.join(values)+'},')
    code.append('};');header.append('#endif');out.mkdir(parents=True,exist_ok=True)
    (out/'walk_data.h').write_text('\n'.join(header)+'\n');(out/'walk_data.c').write_text('\n'.join(code)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args();compile_walk(a.root,a.out)
