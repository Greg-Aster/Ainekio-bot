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
from .migrate_targets import CONTRACT, joint_state
from .program import compile_motion
from .runtime import JOINTS, compact

ENCODING = ProgramEncoding(CONTRACT)
MOTIONS = {'move', 'pose', 'oscillate', 'feet', 'body', 'gait'}
FACES = ('confused', 'sad', 'angry', 'thinking')


def call(name, **arguments):
    if name in ('move','pose','oscillate','feet','body'):
        arguments.setdefault('taper_deg',0)
    return {'name':name, 'arguments':arguments}


def completion(action, start, goal, tail, speed):
    """Keep the interrupted request's targets and remaining phases in the label."""
    if action['name'] in ('gait','oscillate'):
        # The synthetic checkpoint is inside the first cycle: no complete
        # cycles have been credited. Restore the oscillation's measured center.
        prefix = ([] if action['name']=='gait' else [call('pose',joints=list(JOINTS),
            angles_deg=list(start.values()),reference='absolute',speed_pct=speed)])
        return [*prefix,copy.deepcopy(action),*copy.deepcopy(tail)]
    return [call('pose',joints=list(JOINTS),angles_deg=[goal[j] for j in JOINTS],
                 reference='absolute',speed_pct=speed,
                 taper_deg=action['arguments'].get('taper_deg',0)),*copy.deepcopy(tail)]


def foot_approach(state, present, goal, joint, speed, clearance, shift=False):
    """Author a foot-lift/carry approach using the existing geometric compiler.

    These millimetre waypoints are synthetic demonstrations, not runtime rules,
    measured clearance, contact labels, or a guarantee of recovery.
    """
    leg = joint.rsplit('_',1)[0]
    feet = foot_positions(present)
    target = foot_positions(goal)[leg]
    prefix = []
    if shift:
        others = [point for name,point in feet.items() if name != leg]
        center = [sum(point[axis] for point in others)/len(others) for axis in (0,1)]
        length = math.hypot(*center)
        translation = [round(10*v/length,2) for v in center] if length else [0,0]
        prefix.append(call('body',translation_mm=[*translation,0],rotation_deg=[0,0,0],
                           legs=[],foot_offsets_mm=[],speed_pct=speed))
        # A body translation with fixed world feet changes their body-relative
        # coordinates. Recompute those coordinates at the compiled joint pose.
        feet = foot_positions(compile_motion(prefix[0],state_at(state,present),present)['end'])
    current = feet[leg]
    height = max(current[2],target[2])+clearance
    prefix.append(call('feet',legs=[leg],offsets_mm=[[0,0,round(height-current[2],2)]],speed_pct=speed))
    prefix.append(call('feet',legs=[leg],offsets_mm=[[round(target[0]-current[0],2),
        round(target[1]-current[1],2),0]],speed_pct=speed))
    return prefix


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
    state = copy.deepcopy(query.get('observation') or {
        'model':'v2-12servo','joint_speed_limit_deg_s':2000,
        'joints':{joint:{'model_deg':angle,'commanded_model_deg':angle,'home_deg':angle}
                  for joint,angle in zip(JOINTS,row['reference_entry_model_deg'])}})
    state['joints'] = joint_state(state)
    positions = {j:v['model_deg'] for j,v in state['joints'].items()}
    program = ENCODING.decode(row['answers'])
    for index, action in enumerate(program):
        name = action['name']
        if name not in MOTIONS:
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
            goal = (dict(zip(JOINTS,[v/100 for v in compiled['frames'][0][1]]))
                    if name=='oscillate' else dict(compiled['end']))
        if max(abs(goal[j]-positions[j]) for j in JOINTS) > .1:
            return index, state_at(state, positions), goal, action, program[index+1:]
        if name != 'gait': positions = compiled['end']
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
        'reference_example_id':source['id'], 'reference_source_hash':source['source_hash'],
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
    motion_goal = {'request':original['request'], 'interrupted_action':action, 'remaining_program':tail}
    history = [{'joints':{joint:start[joint]}}, {'joints':{joint:measured}},
               {'program_state':'executing', 'interrupted_action':action, 'remaining_program':tail}]
    query = {'request':original['request'], 'event':{'type':'servo_stall',
        'joints':[JOINTS.index(joint)], 'outputs_released':False, 'reason':'no_position_progress'},
        'observation':jam_state, 'history':history, 'motion_goal':motion_goal}
    speed = action['arguments'].get('speed_pct',50)
    clearance = 15 if probe else 10
    recovery = [*foot_approach(state,present,goal,joint,speed,clearance),
                *completion(action,start,goal,tail,speed)]
    variant = 'held_out_feedback' if probe else 'training_feedback'
    evidence = {'joint':JOINTS.index(joint), 'blocked_deg':measured, 'direction':direction,
        'traversed_start_deg':start[joint], 'checkpoint_operation':action['name'],
        'clearance_mm':clearance,'scope':'synthetic foot lift/carry approach, original checkpoint target and unfinished phases'}
    jam = row_for(source,'library_jam_recovery',query,recovery,index,variant,evidence)
    validate_prefix(jam)
    yield jam

    # A second jam carries the original objective alongside the failed attempt.
    # Teach a changed support/approach plan rather than repeating that attempt.
    repeated = copy.deepcopy(query)
    failed = recovery[0]
    failed_target = compile_motion(failed,jam_state,present)['end']
    for shaft in JOINTS:
        repeated['observation']['joints'][shaft]['commanded_model_deg'] = failed_target[shaft]
    repeated['history'][-1] = {'program_state':'executing', 'interrupted_action':failed,
        'remaining_program':recovery[1:], 'joint_progress':[{joint:measured},{joint:measured}]}
    repeated_program = [*foot_approach(state,present,goal,joint,speed,clearance+10,shift=True),
                        *completion(action,start,goal,tail,speed)]
    second = row_for(source,'library_repeated_jam_recovery',repeated,repeated_program,index,variant,
        {**evidence,'clearance_mm':clearance+10,
         'scope':'synthetic repeated no-progress, changed body/foot approach, same unfinished objective'})
    validate_prefix(second)
    yield second

    # A fall correction is chosen from an observed effect, never an invented
    # universal righting pose. Preserve the requested movement after correction.
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
    history = [{'imu':imu(before,axis),'correction_delta_deg':delta}, {'imu':fallen['imu']},
               {'program_state':'executing','interrupted_action':action,'remaining_program':tail}]
    query = {'request':original['request'],'event':{'type':'tipped'},'observation':fallen,'history':history,'motion_goal':motion_goal}
    recovery = [call('face',expr=FACES[(seed+1)%len(FACES)]),
        call('pose',joints=list(pair),angles_deg=[d*(1 if improved else -1) for d in delta.values()],
             reference='current',speed_pct=speed),*completion(action,start,goal,tail,speed)]
    fall = row_for(source,'library_fall_recovery',query,recovery,index,variant,
        {'axis':axis,'before_tilt_deg':before,'after_tilt_deg':after,'improved':improved,
         'scope':'measured correction effect; no initial get-up policy or contact proof'})
    validate_prefix(fall)
    yield fall



def event_variants(rows):
    """Use the same compact lessons for the enabled feedback/IMU event routes."""
    for row in rows:
        yield row
        variant=copy.deepcopy(row);query=json.loads(variant['query'])
        if row['family'] in ('library_jam_recovery','library_repeated_jam_recovery'):
            query['event']['type']='servo_feedback_fault'
            query['event'].pop('reason',None)
            joint=row['recovery_evidence']['joint'];joints=query['observation']['joints']
            index=joints['ids'].index(joint);value=joints['model_deg'][index]
            increasing=row['recovery_evidence']['direction']>0
            # Counterfactual calibration status remains independent of the
            # visible measured position and the authored recovery movement.
            ranges=[None]*len(joints['ids']);ranges[index]=[value-200,value-.1] if increasing else [value+.1,value+200]
            faults=[[] for _ in joints['ids']];faults[index]=['above_calibration' if increasing else 'below_calibration']
            joints['feedback_range_deg']=ranges;joints['feedback_faults']=faults
            joints['feedback_usable']=[i!=index for i in range(len(joints['ids']))]
            variant['family']=('library_repeated_feedback_recovery' if row['family']=='library_repeated_jam_recovery'
                               else 'library_feedback_recovery')
        else:
            query['event']['type']='rapid_movement'
            variant['family']='library_movement_recovery'
        variant['query']=compact(query)
        digest=hashlib.sha256(compact([variant['query'],variant['answers']]).encode()).hexdigest()
        variant.update(id=digest[:16],source_id='library-recovery:'+digest[:16],source_hash=digest)
        yield variant


def audit_source(task):
    source, native_gait, include_probes = task
    try:
        training=list(event_variants(scenarios(source,native_gait)))
        probe=list(event_variants(scenarios(source,native_gait,True))) if include_probes else []
        return {'source_id':source['id'],'source_hash':source['source_hash'],
                'train':training,'probe':probe}
    except (ValueError,KeyError,TypeError) as error:
        return {'source_id':source['id'],'source_hash':source['source_hash'],'error':str(error)}


def deduplicate(rows):
    """Shared teaching content can cover several source motions without repeats."""
    unique = {}
    for row in rows:
        parent={'id':row['reference_example_id'],'source_hash':row['reference_source_hash']}
        if row['id'] not in unique:
            unique[row['id']]={**row,'reference_examples':[parent]}
        elif parent not in unique[row['id']]['reference_examples']:
            unique[row['id']]['reference_examples'].append(parent)
    return list(unique.values())


def build(source, output, native_gait, workers=4, include_probes=True):
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rows=[json.loads(s) for s in (source/'train.jsonl').read_text().splitlines()]
    eligible=[]; excluded=[]
    for row in rows:
        query=json.loads(row['query'])
        if query.get('event') or not any(a[0] in MOTIONS for a in row['answers']):
            excluded.append({'id':row['id'],'reason':'existing recovery' if query.get('event') else 'no movement'})
        else:eligible.append(row)
    # The three approved phrasings share a motion target. Derive feedback
    # lessons from one recorded-context source per motion, retaining every
    # ordinary request in the exported training split.
    by_motion = {}
    source_motion = {row['id']:row.get('reference_motion') for row in rows if row.get('reference_motion')}
    for row in eligible:
        key = row.get('reference_motion') or source_motion.get(row.get('reference_example_id')) or row['id']
        old = by_motion.get(key)
        priority = lambda item: (bool(item.get('reference_motion')),
                                 bool(json.loads(item['query']).get('observation')))
        if old is None or priority(row) > priority(old):
            by_motion[key] = row
    eligible = list(by_motion.values())
    results=[]
    with ProcessPoolExecutor(workers) as pool:
        for result in pool.map(audit_source,((r,str(native_gait),include_probes) for r in eligible)):
            results.append(result)
            if len(results)%100==0:print('recovery sources',len(results),flush=True)
    new_train=deduplicate(r for result in results for r in result.get('train',[]))
    new_probe=deduplicate(r for result in results for r in result.get('probe',[]))
    manifest=json.loads((source/'manifest.json').read_text())
    for path in source.iterdir():
        if path.is_file() and path.name!='manifest.json':(output/path.name).write_bytes(path.read_bytes())
    for split,added in (('train',new_train),('recovery-probe',new_probe)):
        path=output/(split+'.jsonl')
        with path.open('a') as stream:
            stream.writelines(compact(r)+'\n' for r in added)
        manifest.setdefault('splits',{}).setdefault(split,len(rows) if split=='train' else 0)
        manifest['splits'][split]+=len(added)
        if split=='train':manifest['training_rows']=manifest['splits'][split]
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
            'Geometric replay does not establish physical recovery.']}
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
    parser.add_argument('--skip-probes',action='store_true')
    arguments=vars(parser.parse_args());arguments['include_probes']=not arguments.pop('skip_probes')
    build(**arguments)
