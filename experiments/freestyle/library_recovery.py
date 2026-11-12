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
from .face_contract import face_tool
from .gait_replay import sample_gait
from .kinematics import foot_positions
from .motion_space import TOOLS
from .observations import joint_state
from .program import compile_motion
from .runtime import JOINTS, compact

CONTRACT = [*TOOLS, face_tool()]
STAND = dict(zip(JOINTS, [0.0, 0.94, -21.25] * 4))
ENCODING = ProgramEncoding(CONTRACT)
MOTIONS = {'move', 'pose', 'oscillate', 'feet', 'body', 'gait'}
FACES = ('confused', 'sad', 'angry', 'thinking')


def standing_pose(speed_pct=50, taper_deg=0):
    return {'name': 'pose', 'arguments': {'joints': list(JOINTS),
            'angles_deg': list(STAND.values()), 'reference': 'absolute',
            'speed_pct': speed_pct, 'taper_deg': taper_deg}}


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
        translation = [round(4*v/length,2) for v in center] if length else [0,0]
        prefix.append(call('body',translation_mm=[*translation,8],rotation_deg=[0,0,0],
                           legs=[],foot_offsets_mm=[],speed_pct=speed))
        # A body translation with fixed world feet changes their body-relative
        # coordinates. Recompute those coordinates at the compiled joint pose.
        feet = foot_positions(compile_motion(prefix[0],state_at(state,present),present)['end'])
    current = feet[leg]
    height = min(19.0, max(current[2]+2.0, min(current[2],target[2])+clearance))
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
    try:
        query = json.loads(row['query'])
        if not isinstance(query, dict):
            query = {'request': str(query)}
    except ValueError:
        query = {'request': row['query']}
    default_entry = row.get('reference_entry_model_deg') or [0.0, 0.94, -21.25] * 4
    state = copy.deepcopy(query.get('observation') or {
        'model':'v2-12servo','joint_speed_limit_deg_s':2000,
        'joints':{joint:{'model_deg':angle,'commanded_model_deg':angle,'home_deg':angle}
                  for joint,angle in zip(JOINTS,default_entry)}})
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
    clearance = 18 if probe else 16
    recovery = [*foot_approach(state,present,goal,joint,speed,clearance),
                *completion(action,start,goal,tail,speed)]
    variant = 'held_out_feedback' if probe else 'training_feedback'
    evidence = {'joint':JOINTS.index(joint), 'blocked_deg':measured, 'direction':direction,
        'traversed_start_deg':start[joint], 'checkpoint_operation':action['name'],
        'clearance_mm':clearance,'scope':'synthetic foot lift/carry approach, original checkpoint target and unfinished phases'}
    jam = row_for(source,'library_jam_recovery',query,recovery,index,variant,evidence)
    validate_prefix(jam)
    yield jam

    # An unverified completion receipt reports program_state=='error' with failed_action
    # and error_evidence (position_verified: false). Recover and complete the plan.
    unverified = copy.deepcopy(query)
    unverified['history'] = [
        {'joints':{joint:start[joint]}},
        {'joints':{joint:measured}},
        {'program_state':'error', 'failed_action':action,
         'error':'Body did not verify the requested motion target: '+action['name'],
         'error_evidence':{'t':'done', 'seq':1, 'position_verified':False,
                           'unverified_joints':1<<JOINTS.index(joint)},
         'remaining_program':tail}]
    unverified['motion_goal'] = {'request':original['request'], 'program_state':'error',
                                 'failed_action':action, 'remaining_program':tail}
    error_row = row_for(source,'library_error_recovery',unverified,recovery,index,variant,
        {**evidence,'scope':'synthetic unverified target receipt, foot lift/carry approach, failed action and remaining phases'})
    validate_prefix(error_row)
    yield error_row

    # A second jam carries the original objective alongside the failed attempt.
    # Teach a changed support/approach plan rather than repeating that attempt.
    repeated = copy.deepcopy(query)
    failed = recovery[0]
    failed_target = compile_motion(failed,jam_state,present)['end']
    for shaft in JOINTS:
        repeated['observation']['joints'][shaft]['commanded_model_deg'] = failed_target[shaft]
    repeated['history'][-1] = {'program_state':'executing', 'interrupted_action':failed,
        'remaining_program':recovery[1:], 'joint_progress':[{joint:measured},{joint:measured}]}
    repeated_program = [*foot_approach(state,present,goal,joint,speed,clearance+4,shift=True),
                        *completion(action,start,goal,tail,speed)]
    second = row_for(source,'library_repeated_jam_recovery',repeated,repeated_program,index,variant,
        {**evidence,'clearance_mm':clearance+4,
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
    fallen_start = {j: max(-16.0, min(150.0, v)) if j.endswith('_carrier') else v for j, v in start.items()}
    fallen = state_at(state,fallen_start); fallen['imu']=imu(after,axis); fallen['expected_up']=[0,0,1]
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


def standalone_scenarios(probe=False):
    """Unowned body-event recovery lessons (history=[], no motion_goal) returning to Stand."""
    stand_angles = [0.0, 0.94, -21.25] * 4
    stand_goal = dict(zip(JOINTS, stand_angles))
    base_state = {'model':'v2-12servo', 'joint_speed_limit_deg_s':2000,
                  'joints':{j:{'model_deg':a, 'commanded_model_deg':a, 'home_deg':a}
                            for j,a in zip(JOINTS, stand_angles)}}
    base_state['joints'] = joint_state(base_state)
    request = 'Recover from the reported body event using the available observations.'
    source_stub = {'id':'standalone000000', 'source_hash':'0'*64, 'title':request,
                   'query':compact({'request':request})}
    variant = 'held_out_feedback' if probe else 'training_feedback'
    clearance = 18 if probe else 16
    stand_pose = call('pose', joints=list(JOINTS), angles_deg=stand_angles, reference='absolute', speed_pct=50, taper_deg=0)
    for j_idx, joint in enumerate(JOINTS):
        offset = (-6.0 if probe else -8.0) if (j_idx % 3 == 2) else (6.0 if probe else 8.0)
        measured = round(stand_goal[joint] + offset, 2)
        present = dict(stand_goal)
        present[joint] = measured
        jam_state = state_at(base_state, present)
        for j in JOINTS:
            jam_state['joints'][j]['commanded_model_deg'] = stand_goal[j]
        jam_state['feedback'] = {'enabled':True, 'stalled_joints':1<<j_idx, 'no_progress_ms':1000}
        jam_state['imu'] = imu(0, 'roll')
        query = {'request':request,
                 'event':{'type':'servo_stall', 'joints':[j_idx], 'outputs_released':False, 'reason':'no_position_progress'},
                 'observation':jam_state, 'history':[]}
        program = [*foot_approach(base_state, present, stand_goal, joint, 50, clearance), stand_pose]
        evidence = {'joint':j_idx, 'blocked_deg':measured, 'direction':-1 if offset>0 else 1,
                    'traversed_start_deg':measured, 'checkpoint_operation':'standalone',
                    'clearance_mm':clearance, 'scope':'standalone unowned stall recovery to nominal standing pose'}
        jam_row = row_for(source_stub, 'standalone_jam_recovery', query, program, 0, variant, evidence)
        validate_prefix(jam_row)
        yield jam_row

        fb_row = copy.deepcopy(jam_row)
        fb_query = json.loads(fb_row['query'])
        fb_query['event']['type'] = 'servo_feedback_fault'
        fb_query['event'].pop('reason', None)
        joints_obs = fb_query['observation']['joints']
        idx_in_ids = joints_obs['ids'].index(j_idx)
        val = joints_obs['model_deg'][idx_in_ids]
        increasing = evidence['direction'] > 0
        ranges = [None] * len(joints_obs['ids'])
        ranges[idx_in_ids] = [val-200, val-.1] if increasing else [val+.1, val+200]
        faults = [[] for _ in joints_obs['ids']]
        faults[idx_in_ids] = ['above_calibration' if increasing else 'below_calibration']
        joints_obs['feedback_range_deg'] = ranges
        joints_obs['feedback_faults'] = faults
        joints_obs['feedback_usable'] = [i != idx_in_ids for i in range(len(joints_obs['ids']))]
        fb_row['family'] = 'standalone_feedback_recovery'
        fb_row['title'] = 'Standalone Feedback Recovery: ' + joint
        fb_row['query'] = compact(fb_query)
        digest = hashlib.sha256(compact([fb_row['query'], fb_row['answers']]).encode()).hexdigest()
        fb_row.update(id=digest[:16], source_id='library-recovery:'+digest[:16], source_hash=digest)
        validate_prefix(fb_row)
        yield fb_row

    legs = ('rear_left', 'rear_right', 'front_left', 'front_right')
    for l_idx, leg in enumerate(legs):
        for s_idx, sign in enumerate((-1, 1)):
            c_joint = f'{leg}_carrier'
            present = dict(stand_goal)
            present[c_joint] = round(stand_goal[c_joint] + sign * (7.0 if probe else 9.0), 2)
            slip_state = state_at(base_state, present)
            axis = 'roll' if l_idx % 2 == 0 else 'pitch'
            slip_state['imu'] = imu(sign * (5 if probe else 7), axis)
            slip_state['expected_up'] = [0, 0, 1]
            query = {'request':request, 'event':{'type':'slip'}, 'observation':slip_state, 'history':[]}
            program = [call('face', expr=FACES[(l_idx + s_idx) % len(FACES)]),
                       *foot_approach(base_state, present, stand_goal, c_joint, 50, clearance),
                       stand_pose]
            evidence = {'leg':leg, 'axis':axis, 'clearance_mm':clearance,
                        'scope':'standalone slip recovery unloading slipped leg and returning to standing'}
            slip_row = row_for(source_stub, 'standalone_slip_recovery', query, program, 0, variant, evidence)
            validate_prefix(slip_row)
            yield slip_row

    for idx, (axis, sign, mag, base_tilt) in enumerate((
            ('roll', 1, 3, 16), ('roll', -1, 3, 16), ('pitch', 1, 4, 16), ('pitch', -1, 4, 16),
            ('roll', 1, 5, 66), ('roll', -1, 5, 66), ('pitch', 1, 6, 78), ('pitch', -1, 6, 78))):
        pair = ('rear_left_carrier', 'rear_right_carrier') if axis == 'roll' else ('front_left_carrier', 'rear_left_carrier')
        delta_val = mag + (.5 if probe else 0)
        present = dict(stand_goal)
        present[pair[0]] = round(stand_goal[pair[0]] - sign * delta_val, 2)
        present[pair[1]] = round(stand_goal[pair[1]] + sign * delta_val, 2)
        tilt = sign * (base_tilt + (4 if probe else 0))
        fallen = state_at(base_state, present)
        fallen['imu'] = imu(tilt, axis)
        fallen['expected_up'] = [0, 0, 1]
        program = [call('face', expr=FACES[idx % len(FACES)]),
                   call('pose', joints=list(pair), angles_deg=[sign * delta_val, -sign * delta_val],
                        reference='current', speed_pct=50, taper_deg=0),
                   stand_pose]
        for ev_type, fam in (('tipped', 'standalone_fall_recovery'), ('rapid_movement', 'standalone_movement_recovery')):
            query = {'request':request, 'event':{'type':ev_type}, 'observation':copy.deepcopy(fallen), 'history':[]}
            ev_row = row_for(source_stub, fam, query, program, 0, variant,
                             {'axis':axis, 'tilt_deg':tilt, 'scope':'standalone attitude recovery to nominal standing pose'})
            validate_prefix(ev_row)
            yield ev_row

    # Post-completion faults (program_state == 'completed', remaining_program == []):
    # Bridge retains active ownership after a completed motion so immediate post-motion
    # stalls or falls recover to standing without re-running the finished gesture.
    completed_actions = (
        ('Wave with your right hand.', call('pose', joints=list(JOINTS), angles_deg=stand_angles, reference='absolute', speed_pct=60)),
        ('Give a polite bow.', call('pose', joints=list(JOINTS), angles_deg=stand_angles, reference='absolute', speed_pct=50)),
        ('Pretend you are a frog.', call('feet', legs=['front_left', 'front_right'], offsets_mm=[[0, 0, -18], [0, 0, -18]], speed_pct=70)),
        ('Do the sprinkler dance.', call('feet', legs=['front_right'], offsets_mm=[[-20, 0, -24]], speed_pct=65)),
    )
    for c_idx, (orig_req, completed_act) in enumerate(completed_actions):
        source_done = {'id': f'completed{c_idx:07d}', 'source_hash': f'{c_idx + 1:064x}',
                       'title': orig_req, 'query': compact({'request': orig_req})}
        j_idx = (6, 9, 1, 4)[c_idx % 4]
        joint = JOINTS[j_idx]
        offset = (7.0 if not probe else 9.0) * (1 if c_idx % 2 == 0 else -1)
        present = dict(stand_goal)
        present[joint] = round(stand_goal[joint] + offset, 2)
        post_jam = state_at(base_state, present)
        for j in JOINTS:
            post_jam['joints'][j]['commanded_model_deg'] = stand_goal[j]
        post_jam['feedback'] = {'enabled': True, 'stalled_joints': 1 << j_idx, 'no_progress_ms': 1000}
        post_jam['imu'] = imu(0, 'roll')
        goal_done = {'request': orig_req, 'program_state': 'completed',
                     'completed_action': completed_act, 'remaining_program': []}
        hist_done = [{'joints': {joint: stand_goal[joint]}}, {'joints': {joint: present[joint]}},
                     {'program_state': 'completed', 'completed_action': completed_act, 'remaining_program': []}]
        for req_text in (orig_req, request):
            q_done = {'request': req_text,
                      'event': {'type': 'servo_stall', 'joints': [j_idx], 'outputs_released': False, 'reason': 'no_position_progress'},
                      'observation': copy.deepcopy(post_jam), 'history': copy.deepcopy(hist_done),
                      'motion_goal': copy.deepcopy(goal_done)}
            prog_done = [*foot_approach(base_state, present, stand_goal, joint, 50, clearance), stand_pose]
            done_row = row_for(source_done, 'completed_jam_recovery', q_done, prog_done, 0, variant,
                               {'joint': j_idx, 'blocked_deg': present[joint], 'direction': -1 if offset > 0 else 1,
                                'clearance_mm': clearance, 'scope': 'post-completion stall recovery without repeating finished gesture'})
            validate_prefix(done_row)
            yield done_row

        axis = 'roll' if c_idx % 2 == 0 else 'pitch'
        sign = 1 if c_idx < 2 else -1
        pair = ('rear_left_carrier', 'rear_right_carrier') if axis == 'roll' else ('front_left_carrier', 'rear_left_carrier')
        mag = 5 + (0.5 if probe else 0)
        before_tilt = sign * (74 if not probe else 82)
        after_tilt = before_tilt - sign * 10
        delta = {pair[0]: sign * mag, pair[1]: -sign * mag}
        fallen_done = state_at(base_state, stand_goal)
        fallen_done['imu'] = imu(after_tilt, axis)
        fallen_done['expected_up'] = [0, 0, 1]
        fall_hist = [{'imu': imu(before_tilt, axis), 'correction_delta_deg': delta},
                     {'imu': fallen_done['imu']},
                     {'program_state': 'completed', 'completed_action': completed_act, 'remaining_program': []}]
        for req_text in (orig_req, request):
            q_fall = {'request': req_text, 'event': {'type': 'tipped'},
                      'observation': copy.deepcopy(fallen_done), 'history': copy.deepcopy(fall_hist),
                      'motion_goal': copy.deepcopy(goal_done)}
            prog_fall = [call('face', expr=FACES[c_idx % len(FACES)]),
                         call('pose', joints=list(pair), angles_deg=[sign * mag, -sign * mag],
                              reference='current', speed_pct=50, taper_deg=0),
                         stand_pose]
            fall_done_row = row_for(source_done, 'completed_fall_recovery', q_fall, prog_fall, 0, variant,
                                    {'axis': axis, 'before_tilt_deg': before_tilt, 'after_tilt_deg': after_tilt,
                                     'improved': True, 'scope': 'post-completion tipped recovery without repeating finished gesture'})
            validate_prefix(fall_done_row)
            yield fall_done_row

    # Adaptive oscillation recovery: retreat from an obstructed shoulder sweep and
    # finish the requested wave within the unobstructed range.
    retreats = (5.0,) if probe else (4.0, 6.0)
    for side, j_idx in (('left', 6), ('right', 9)):
        for direction in (-1, 1):
            for r_idx, retreat in enumerate(retreats):
                for finish in ('stand', 'raised'):
                    measured = direction * (46.0 if probe else 48.0)
                    req_wave = (f'Wave to the audience with your front-{side} foot. '
                                + ('Return to standing afterwards.' if finish == 'stand' else 'Keep that foot raised afterwards.'))
                    obs_wave = state_at(base_state, stand_goal)
                    for idx_j, name_j in enumerate(JOINTS):
                        obs_wave['joints'][name_j]['home_deg'] = [0.0, -30.87, -117.68][idx_j % 3]
                    obs_wave['joints'][JOINTS[j_idx]].update(
                        model_deg=measured, commanded_model_deg=measured + direction * 18.0, velocity_deg_s=0.0)
                    obs_wave['feedback'] = {'enabled': True, 'no_progress_ms': 1000, 'stalled_joints': 1 << j_idx}
                    obs_wave['imu'] = imu(0, 'roll')
                    interrupted = call('move', joint=JOINTS[j_idx], angle_deg=measured + direction * 18.0,
                                       reference='absolute', speed_pct=45)
                    rem = [call('oscillate', joint=JOINTS[j_idx], amplitude_deg=12, cycles=3, speed_pct=45)]
                    if finish == 'stand':
                        rem.append(copy.deepcopy(stand_pose))
                    q_wave = {
                        'request': req_wave,
                        'event': {'type': 'servo_stall', 'joints': [j_idx], 'reason': 'no_position_progress', 'outputs_released': False},
                        'observation': obs_wave,
                        'history': [{'program_state': 'executing', 'interrupted_action': interrupted, 'remaining_program': rem}],
                        'motion_goal': {'request': req_wave, 'interrupted_action': interrupted, 'remaining_program': rem},
                    }
                    prog_wave = [
                        call('face', expr=FACES[r_idx % len(FACES)]),
                        call('move', joint=JOINTS[j_idx], angle_deg=-direction * retreat, reference='current', speed_pct=45),
                        call('face', expr='wave'),
                        call('oscillate', joint=JOINTS[j_idx], amplitude_deg=round(retreat / 2, 2), cycles=3, speed_pct=45),
                    ]
                    if finish == 'stand':
                        prog_wave.append(copy.deepcopy(stand_pose))
                    wave_stub = {'id': f'adapwave{j_idx}{1 if direction>0 else 0}{int(retreat)}',
                                 'source_hash': hashlib.sha256(req_wave.encode()).hexdigest(),
                                 'title': req_wave, 'query': compact({'request': req_wave})}
                    wave_row = row_for(wave_stub, 'adaptive_wave_recovery', q_wave, prog_wave, 0, variant,
                                       {'joint': j_idx, 'blocked_deg': measured, 'direction': direction,
                                        'retreat_deg': retreat, 'scope': 'retreat from obstructed shoulder extreme and finish smaller sweep'})
                    validate_prefix(wave_row)
                    yield wave_row


def event_variants(rows):
    """Use the same compact lessons for the enabled feedback/IMU event routes."""
    def with_goal_request(item):
        yield item
        q = json.loads(item['query'])
        if q.get('motion_goal') and q.get('request') != 'Recover from the reported body event using the available observations.':
            goal_item = copy.deepcopy(item)
            q['request'] = 'Recover from the reported body event using the available observations.'
            goal_item['query'] = compact(q)
            goal_item['title'] = 'Recovery: ' + item['title']
            digest = hashlib.sha256(compact([goal_item['query'], goal_item['answers']]).encode()).hexdigest()
            goal_item.update(id=digest[:16], source_id='goal-recovery:' + digest[:16], source_hash=digest)
            yield goal_item

    for row in rows:
        yield from with_goal_request(row)
        variant=copy.deepcopy(row);query=json.loads(variant['query'])
        if row['family'] in ('library_jam_recovery','library_repeated_jam_recovery','library_error_recovery'):
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
                               else 'library_error_feedback_recovery' if row['family']=='library_error_recovery'
                               else 'library_feedback_recovery')
        else:
            query['event']['type']='rapid_movement'
            variant['family']='library_movement_recovery'
        variant['query']=compact(query)
        digest=hashlib.sha256(compact([variant['query'],variant['answers']]).encode()).hexdigest()
        variant.update(id=digest[:16],source_id='library-recovery:'+digest[:16],source_hash=digest)
        yield from with_goal_request(variant)


def audit_source(task):
    source, native_gait, include_probes = task
    try:
        expand_all = bool(source.get('reference_motion'))
        base_train = list(scenarios(source, native_gait))
        if expand_all:
            training = list(event_variants(base_train))
        else:
            # For broad curriculum families, emit one crisp lesson per fault route
            # (rotating stall vs feedback_fault, tipped vs rapid_movement, and
            # direct request vs generic body-event request) to avoid 4x bloat.
            seed = int(source['id'][:8], 16)
            training = []
            for idx, item in enumerate(base_train):
                variants = list(event_variants([item]))
                training.append(variants[(seed + idx) % len(variants)])
        base_probe = list(scenarios(source, native_gait, True)) if include_probes else []
        if expand_all:
            probe = list(event_variants(base_probe))
        else:
            seed = int(source['id'][:8], 16)
            probe = []
            for idx, item in enumerate(base_probe):
                variants = list(event_variants([item]))
                probe.append(variants[(seed + idx + 1) % len(variants)])
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
        try:
            query=json.loads(row['query'])
            if not isinstance(query, dict):
                query={'request':str(query)}
        except ValueError:
            query={'request':row['query']}
        if query.get('event') or not any(a[0] in MOTIONS for a in row['answers']):
            excluded.append({'id':row['id'],'reason':'existing recovery' if query.get('event') else 'no movement'})
        else:eligible.append(row)
    # Derive feedback lessons from one representative source per motion family,
    # retaining every ordinary request in the exported training split.
    by_motion = {}
    source_motion = {row['id']:row.get('reference_motion') for row in rows if row.get('reference_motion')}
    for row in eligible:
        key = (row.get('reference_motion') or row.get('curriculum_family')
               or source_motion.get(row.get('reference_example_id')) or row['id'])
        old = by_motion.get(key)
        def priority(item):
            try:
                q = json.loads(item['query'])
                has_obs = isinstance(q, dict) and bool(q.get('observation'))
            except ValueError:
                has_obs = False
            return (bool(item.get('reference_motion')), has_obs)
        if old is None or priority(row) > priority(old):
            by_motion[key] = row
    eligible = list(by_motion.values())
    results=[]
    with ProcessPoolExecutor(workers) as pool:
        for result in pool.map(audit_source,((r,str(native_gait),include_probes) for r in eligible)):
            results.append(result)
            if len(results)%100==0:print('recovery sources',len(results),flush=True)
    standalone_train=list(standalone_scenarios(False))
    standalone_probe=list(standalone_scenarios(True)) if include_probes else []
    new_train=deduplicate([*(r for result in results for r in result.get('train',[])), *standalone_train])
    new_probe=deduplicate([*(r for result in results for r in result.get('probe',[])), *standalone_probe])
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
