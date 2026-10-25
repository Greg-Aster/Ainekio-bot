"""Offline recovery curriculum linked to each current motion-library example.

Counterfactual feedback is explicitly synthetic. Prefix FK and target checks
are not contact, balance, or physical recovery qualification. No robot I/O.
"""
import argparse
import copy
import hashlib
import json
import math
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .compact_wire import ProgramEncoding, model_query
from .gait_replay import sample_gait
from .kinematics import foot_positions
from .migrate_targets import CONTRACT, STAND, joint_state
from .program import compile_motion
from .runtime import JOINTS, compact

ENCODING = ProgramEncoding(CONTRACT)
MOTIONS = {'move', 'pose', 'oscillate', 'feet', 'body', 'stand', 'gait'}
FACES = ('confused', 'sad', 'angry', 'thinking')


def call(name, **arguments):
    return {'name':name, 'arguments':arguments}


def state_at(state, positions):
    result = copy.deepcopy(state)
    result['joints'] = joint_state(result)
    for joint, position in positions.items():
        result['joints'][joint].update(model_deg=position, commanded_model_deg=position,
                                      velocity_deg_s=0)
    return result


def checkpoint(row, native_gait):
    """Ground the interrupted target in the same compiler/native gait owner."""
    query = json.loads(row['query'])
    state = copy.deepcopy(query['observation'])
    state['joints'] = joint_state(state)
    positions = {j:v['model_deg'] for j,v in state['joints'].items()}
    program = ENCODING.decode(row['answers'])
    stand_candidate = None
    for index, action in enumerate(program):
        name = action['name']
        if name not in MOTIONS:
            continue
        if name == 'stand':
            if any(abs(STAND[j]-positions[j]) > .1 for j in JOINTS):
                stand_candidate = (index, state_at(state, positions), dict(STAND), action, program[index+1:])
            positions = dict(STAND)
            continue
        if name == 'gait':
            # Only the initial cycle is needed to locate an interrupted target.
            args = {**action['arguments'], 'cycles':1}
            gait = sample_gait(args, state['joint_speed_limit_deg_s'], native_gait)
            if gait['status'] != 'replayed':
                raise ValueError('Native gait checkpoint unavailable: '+str(gait))
            frames = [dict(zip(JOINTS, s['model_deg'])) for s in gait['segments'][0]['samples']]
            goal = next((p for p in frames if max(abs(p[j]-positions[j]) for j in JOINTS) > 2), None)
            if goal is None:
                raise ValueError('Native gait has no moving checkpoint')
        else:
            compiled = compile_motion(action, state_at(state, positions), positions)
            goal = dict(zip(JOINTS, [v/100 for v in compiled['frames'][0][1]]))
        if max(abs(goal[j]-positions[j]) for j in JOINTS) > .1:
            return index, state_at(state, positions), goal, action, program[index+1:]
        if name != 'gait': positions = compiled['end']
    if stand_candidate: return stand_candidate
    raise ValueError('No nonzero movement checkpoint')


def imu(angle, axis):
    r = math.radians(angle)
    return {'available':True, 'fresh':True, 'frame':'body_nominal',
        'orientation_wxyz':[round(math.cos(r/2),6),
            round(math.sin(r/2),6) if axis=='roll' else 0,
            round(math.sin(r/2),6) if axis=='pitch' else 0, 0],
        'angular_rate_rad_s':[0,0,0]}


def row_for(source, family, query, program, index, variant, evidence):
    query = compact(model_query(query, ENCODING))
    answers = ENCODING.encode(program)
    digest = hashlib.sha256(compact([query, answers]).encode()).hexdigest()
    return {'id':digest[:16], 'family':family, 'query':query, 'answers':answers,
        'title':family.replace('_',' ').title()+': '+source.get('title',json.loads(source['query'])['request']),
        'source_id':'library-recovery:'+digest[:16], 'source_hash':digest,
        'parent_example_id':source['id'], 'parent_source_hash':source['source_hash'],
        'source_action_index':index, 'scenario':variant,
        'synthetic':True, 'physical_qualification':False,
        'teacher':'Offline counterfactual feedback and target compiler; no physical demonstration',
        'qualification_basis':'synthetic_feedback_with_compiled_prefix_only',
        'recovery_evidence':evidence}


def validate_prefix(row):
    query = json.loads(row['query']); state=query['observation']
    state['joints'] = joint_state(state)
    planned = None; targets=[]
    for action in ENCODING.decode(row['answers']):
        if action['name'] == 'reassess': break
        if action['name'] in ('move','pose','oscillate','feet','body'):
            result = compile_motion(action, state, planned); planned=result['end']
            for _,frame in result['frames']:
                positions = dict(zip(JOINTS,[q/100 for q in frame]))
                feet = foot_positions(positions)
                if not all(math.isfinite(v) for p in feet.values() for v in p):
                    raise ValueError('Nonfinite linkage position')
                targets.append(positions)
    return targets


def scenarios(source, native_gait, probe=False):
    index, state, goal, action, tail = checkpoint(source, native_gait)
    original = json.loads(source['query'])
    start = {j:v['model_deg'] for j,v in state['joints'].items()}
    seed = int(source['id'][:8],16)
    changing = [j for j in JOINTS if abs(goal[j]-start[j]) > .1]
    joint = changing[seed % len(changing)]
    portion = .6 if probe else .75
    measured = round(start[joint]+portion*(goal[joint]-start[joint]),2)
    direction = 1 if goal[joint]>start[joint] else -1
    traversed = abs(measured-start[joint])
    retreat = round(traversed*(.4 if probe else .5),2)
    if retreat < .02: raise ValueError('Checkpoint excursion too small for distinct measured targets')
    # The counterfactual interrupts a coordinated move part-way through it.
    present = {j:round(start[j]+portion*(goal[j]-start[j]),2) for j in JOINTS}
    present[joint] = measured
    jam_state = state_at(state, present)
    # Every shaft retains the coordinated command, including the shafts still
    # progressing. Measured positions must not replace their intended targets.
    for j in JOINTS:
        jam_state['joints'][j]['commanded_model_deg'] = goal[j]
    jam_state['feedback'] = {'enabled':True, 'stalled_joints':1<<JOINTS.index(joint), 'no_progress_ms':1000}
    jam_state['imu'] = imu(0,'roll')
    history = [{'joints':{joint:start[joint]}}, {'joints':{joint:measured}},
               {'interrupted_action':action, 'remaining_program':tail}]
    query = {'request':original['request'], 'event':{'type':'servo_stall',
        'joints':[JOINTS.index(joint)], 'outputs_released':False, 'reason':'no_position_progress'},
        'observation':jam_state, 'history':history}
    speed = action['arguments'].get('speed_pct',50)
    recovery = [call('face',expr=FACES[seed%len(FACES)]),
                call('move',joint=joint,angle_deg=round(-direction*retreat,2),reference='current',speed_pct=speed)]
    if action['name']=='oscillate':
        recovery.append(call('oscillate',joint=joint,amplitude_deg=round(retreat/2,2),
                             cycles=action['arguments']['cycles'],speed_pct=speed))
    else:
        # Finish the other participating targets while shortening the blocked
        # joint's excursion, then measure the resulting posture. This is an
        # authored training adaptation, never a hard-coded runtime clamp.
        adapted = {j:goal[j] for j in changing}
        adapted[joint] = round(measured-direction*retreat/2,2)
        recovery.append(call('pose',joints=list(adapted),angles_deg=list(adapted.values()),
                             reference='absolute',speed_pct=speed))
    recovery.append(call('reassess'))
    variant = 'held_out_feedback' if probe else 'training_feedback'
    jam = row_for(source,'library_jam_recovery',query,recovery,index,variant,
        {'joint':JOINTS.index(joint), 'blocked_deg':measured, 'direction':direction,
         'traversed_start_deg':start[joint], 'checkpoint_operation':action['name'],
         'scope':'retreat and reduced excursion; continuation requires reassessment'})
    targets = validate_prefix(jam)
    if not targets or any(direction*(p[joint]-measured)>=0 for p in targets):
        raise ValueError('Recovery prefix repeats the blocked extreme')
    yield jam

    # A fall correction is chosen from an observed effect, never an invented
    # universal righting pose. The unfinished goal stays behind reassessment.
    axis = ('pitch' if seed%2 else 'roll') if not probe else ('roll' if seed%2 else 'pitch')
    sign = 1 if seed%3 else -1
    improved = bool(seed%2) if not probe else not bool(seed%2)
    before = sign*(80 if not probe else 92)
    after = before-sign*12 if improved else before+sign*12
    pair = ('rear_left_carrier','rear_right_carrier') if axis=='roll' else ('front_left_carrier','rear_left_carrier')
    # Vary the measured correction independently of direction and outcome.
    # Probe magnitudes interpolate between training values, so a constant
    # correction cannot pass as learning from the measured effect.
    magnitude = (1,2,3,4,6)[(seed//6)%5] + (.5 if probe else 0)
    delta = {pair[0]:sign*magnitude, pair[1]:-sign*magnitude}
    fallen = state_at(state,start); fallen['imu']=imu(after,axis); fallen['expected_up']=[0,0,1]
    pending = [copy.deepcopy(action),*copy.deepcopy(tail)]
    history = [{'imu':imu(before,axis),'correction_delta_deg':delta}, {'imu':fallen['imu']},
               {'interrupted_action':action,'remaining_program':pending}]
    query = {'request':original['request'],'event':{'type':'tipped'},'observation':fallen,'history':history}
    recovery = [call('face',expr=FACES[(seed+1)%len(FACES)]),
        call('pose',joints=list(pair),angles_deg=[d*(1 if improved else -1) for d in delta.values()],
             reference='current',speed_pct=50),call('reassess')]
    fall = row_for(source,'library_fall_recovery',query,recovery,index,variant,
        {'axis':axis,'before_tilt_deg':before,'after_tilt_deg':after,'improved':improved,
         'scope':'measured correction effect; no initial get-up policy or contact proof'})
    validate_prefix(fall)
    yield fall

    # Teach the other side of reassessment: when the supplied feedback is
    # upright and tracks the targets, actually continue the pending goal.
    resumed = state_at(state,start)
    resumed['imu']=imu(0,axis); resumed['expected_up']=[0,0,1]
    resumed['pending_actions']=pending
    history=[{'imu':imu(sign*(11 if probe else 12),axis),'correction_delta_deg':delta},
             {'imu':resumed['imu']}]
    query={'request':original['request'],'event':{'type':'reassess'},'observation':resumed,'history':history}
    expression=next((a[1] for a in source['answers'] if a[0]=='face'),'happy')
    yield row_for(source,'library_recovery_resume',query,[call('face',expr=expression),*pending],index,variant,
        {'scope':'synthetic upright tracking feedback; resume the pending source goal'})


def audit_source(task):
    source, native_gait = task
    try:
        training=list(scenarios(source,native_gait)); probe=list(scenarios(source,native_gait,True))
        return {'source_id':source['id'],'source_hash':source['source_hash'],
                'train':training,'probe':probe}
    except (ValueError,KeyError,TypeError) as error:
        return {'source_id':source['id'],'source_hash':source['source_hash'],'error':str(error)}


def deduplicate(rows):
    """Shared teaching content can cover several source motions without repeats."""
    unique = {}
    for row in rows:
        parent={'id':row['parent_example_id'],'source_hash':row['parent_source_hash']}
        if row['id'] not in unique:
            unique[row['id']]={**row,'parent_examples':[parent]}
        elif parent not in unique[row['id']]['parent_examples']:
            unique[row['id']]['parent_examples'].append(parent)
    return list(unique.values())


def build(source, output, native_gait, workers=4):
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rows=[json.loads(s) for s in (source/'train.jsonl').read_text().splitlines()]
    eligible=[]; excluded=[]
    for row in rows:
        query=json.loads(row['query'])
        if query.get('event') or not any(a[0] in MOTIONS for a in row['answers']):
            excluded.append({'id':row['id'],'reason':'existing recovery' if query.get('event') else 'no movement'})
        else:eligible.append(row)
    results=[]
    with ProcessPoolExecutor(workers) as pool:
        for result in pool.map(audit_source,((r,str(native_gait)) for r in eligible)):
            results.append(result)
            if len(results)%100==0:print('recovery sources',len(results),flush=True)
    # A resumption pair per source family teaches completion without letting
    # copies of long nominal plans dominate correction supervision.
    resume_sources={}
    for row in eligible:resume_sources.setdefault(row['family'],row['id'])
    resume_ids=set(resume_sources.values())
    for result in results:
        if result['source_id'] not in resume_ids:
            for split in ('train','probe'):
                if split in result:result[split]=[r for r in result[split] if r['family']!='library_recovery_resume']
    new_train=deduplicate(r for result in results for r in result.get('train',[]))
    new_probe=deduplicate(r for result in results for r in result.get('probe',[]))
    manifest=json.loads((source/'manifest.json').read_text())
    for path in source.iterdir():
        if path.is_file() and path.name!='manifest.json':(output/path.name).write_bytes(path.read_bytes())
    for split,added in (('train',new_train),('recovery-probe',new_probe)):
        path=output/(split+'.jsonl')
        with path.open('a') as stream:
            stream.writelines(compact(r)+'\n' for r in added)
        manifest['splits'][split]+=len(added)
        manifest['files'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    report={'eligible_source_motions':len(eligible),'covered_source_motions':sum('error' not in r for r in results),
        'added_training':len(new_train),'added_probes':len(new_probe),'families':dict(Counter(r['family'] for r in new_train)),
        'joint_coverage':dict(Counter(r['recovery_evidence']['joint'] for r in new_train if r['family']=='library_jam_recovery')),
        'excluded':excluded,'unresolved':[r for r in results if 'error' in r],
        'coverage':[{'source_id':r['source_id'],'source_hash':r['source_hash'],
            'train_ids':[v['id'] for v in r.get('train',[])],'probe_ids':[v['id'] for v in r.get('probe',[])]} for r in results],
        'slip_changes':False,'physical_trials':0,
        'scope':'Current motion-bearing training rows; probe shares source goals but holds out feedback values. Native emotes absent from the source library are not claimed covered.',
        'limitations':['No contact/dynamics simulation or physical success labels.',
            'Fall examples require a preceding measured correction; initial arbitrary fallen-pose righting remains unqualified.',
            'Only recovery prefixes before reassessment are validated; later plans must use fresh feedback.']}
    (output/'recovery-coverage.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest['library_recovery']={k:v for k,v in report.items() if k not in ('coverage','excluded')}
    manifest['library_recovery']['generator_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(compact({k:v for k,v in report.items() if k not in ('coverage','excluded')}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','native-gait'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    build(**vars(parser.parse_args()))
