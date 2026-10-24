"""Build an offline Freestyle curriculum with composition-held-out evaluation.

This authors synthetic demonstrations, never runtime behavior. Desired Cartesian
waypoints are stored before compilation and checked against independent FK of
the compiled trajectory. No replay claims contact, balance, or physical recovery.
Rejected candidates and pruning decisions remain in the output audit.
"""
import argparse
import copy
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .challenge import digest, read_rows, replay, write_rows
from .kinematics import ROOT, foot_positions
from .runtime import JOINTS, compact
from .semantic_teachers import call, feet, body


TASKS = ('wave', 'beckon', 'point', 'salute', 'drink', 'knock', 'wipe',
         'circle', 'square', 'triangle', 'figure_eight', 'spiral', 'scoop',
         'throw', 'punch', 'clap', 'drum', 'conduct', 'shrug', 'flap',
         'microphone', 'hammer', 'bow', 'sway', 'squat', 'twist',
         'stretch', 'fold', 'step_over', 'shuffle', 'offer', 'withdraw')


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_state(pose='stand'):
    source = ROOT/'motions/gestures'/('wave' if pose == 'stand' else pose)/'source.json'
    samples = json.loads(source.read_text())['samples']
    sample = samples[0 if pose == 'stand' else -1]
    angles = [round(math.degrees(q), 4) for leg in sample['actuator_angles_rad'] for q in leg]
    home_sample = json.loads((ROOT/'motions/gestures/wave/source.json').read_text())['samples'][0]
    homes = [round(math.degrees(q), 4) for leg in home_sample['actuator_angles_rad'] for q in leg]
    return {'model':'v2-12servo', 'epoch':1, 'speed_pct':50,
            'joint_speed_limit_deg_s':180,
            'joints':{j:{'model_deg':q, 'commanded_model_deg':q, 'home_deg':home,
                         'calibrated':True, 'velocity_deg_s':0, 'sampled_us':3000000}
                      for j,q,home in zip(JOINTS, angles, homes)},
            'imu':imu(0, 'roll', 3000000),
            'feedback':{'enabled':True, 'device_us':3000000}}


def imu(angle, axis, timestamp):
    r = math.radians(angle)
    q = [math.cos(r/2), math.sin(r/2) if axis == 'roll' else 0,
         math.sin(r/2) if axis == 'pitch' else 0, 0]
    # Static gravity in the body frame, consistent with this quaternion.
    gravity = [0, math.sin(r), math.cos(r)] if axis == 'roll' else [-math.sin(r), 0, math.cos(r)]
    return {'available':True, 'fresh':True, 'timestamp_us':timestamp,
            'orientation_wxyz':[round(v, 7) for v in q],
            'acceleration_m_s2':[round(v*9.80665, 6) for v in gravity],
            'angular_rate_rad_s':[0, 0, 0], 'frame':'body_nominal'}


class Author:
    """Track the requested Cartesian scene, without using compiled IK results."""
    def __init__(self, observation, duration=.5, pause=.4):
        self.initial = foot_positions({j:observation['joints'][j]['model_deg'] for j in JOINTS})
        self.current = copy.deepcopy(self.initial)
        self.program, self.goals = [], []
        self.duration, self.pause = duration, pause

    def target(self, points, seconds=None):
        legs = list(points)
        before = copy.deepcopy(self.current)
        self.program.append(feet(legs, [[round(b-a, 6) for a,b in zip(self.current[leg], points[leg])]
                                        for leg in legs], seconds or self.duration))
        self.current.update(copy.deepcopy(points))
        self.goals.append({'kind':'line', 'before':before, 'after':copy.deepcopy(self.current),
                           'seconds':seconds or self.duration})

    def hold(self, seconds=None):
        seconds = self.pause if seconds is None else seconds
        self.program.append(call('hold', seconds=seconds))
        self.goals.append({'kind':'line', 'before':copy.deepcopy(self.current),
                           'after':copy.deepcopy(self.current), 'seconds':seconds})

    def torso(self, translation=(0, 0, 0), rotation=(0, 0, 0)):
        # All authored rotations here have one axis. The inverse rotation is
        # calculated independently of the spatial compiler's Mechanism object.
        before = copy.deepcopy(self.current)
        pivot = json.loads((ROOT/'geometry.json').read_text())['continuous_walk']['body_rotation_pivot_mm']
        for leg, point in before.items():
            v = [point[i]-translation[i]-pivot[i] for i in range(3)]
            for axis in (2, 1, 0):
                a, b = ((1, 2), (2, 0), (0, 1))[axis]
                theta = math.radians(-rotation[axis]); c, s = math.cos(theta), math.sin(theta)
                v[a], v[b] = c*v[a]-s*v[b], s*v[a]+c*v[b]
            self.current[leg] = [v[i]+pivot[i] for i in range(3)]
        self.program.append(body(translation, rotation, self.duration))
        self.goals.append({'kind':'body', 'before':before, 'after':copy.deepcopy(self.current),
                           'seconds':self.duration})

    def task(self, family, side, n, size):
        hand = 'front_'+side; other = 'front_'+('left' if side == 'right' else 'right')
        sign = 1 if side == 'left' else -1
        hands = ['front_left', 'front_right']
        start = copy.deepcopy(self.current)
        point = lambda x, y, z: [x, sign*y, z]
        at = lambda x, y, z: self.target({hand:point(x, y, z)})
        both = lambda x, y, z: self.target({leg:[x, y if leg.endswith('left') else -y, z] for leg in hands})
        restore = lambda legs: self.target({leg:start[leg] for leg in legs})
        if family in ('wave', 'beckon', 'knock', 'wipe', 'punch'):
            at(95, 90, 90 if family == 'wave' else 60)
            for _ in range(n):
                if family == 'wave':
                    at(95, 90+size, 90); at(95, 90-size, 90); at(95, 90, 90)
                elif family == 'beckon':
                    at(110, 90, 60); at(110-size, 90, 60+size/2)
                elif family == 'knock':
                    at(95, 90, 60+size); at(95, 90, 60)
                elif family == 'wipe':
                    at(95, 90+size, 60); at(95, 90-size, 60); at(95, 90, 60)
                else:
                    at(95+size, 90, 60); at(95, 90, 60)
            restore([hand])
            verb = {'wave':'wave', 'beckon':'beckon me closer', 'knock':'mime knocking',
                    'wipe':'wipe an imaginary window side to side', 'punch':'throw forward punches'}[family]
            return f'{verb} with your {side} hand for {n} complete cycles, then put that hand back'
        if family in ('point', 'offer', 'withdraw', 'stretch'):
            if family == 'point': at(115, 110, 65)
            elif family == 'offer': both(110, 85, 65)
            elif family == 'withdraw': at(90, 90, 60); at(90-size, 90, 60)
            else: both(95, 115+size/2, 85)
            self.hold()
            return {'point':f'point diagonally forward and outward with your {side} hand and keep it extended',
                    'offer':'offer an imaginary tray with both hands and keep it out',
                    'withdraw':f'draw your {side} hand back toward yourself and leave it raised',
                    'stretch':'stretch both arms outward and keep them spread'}[family]
        if family in ('salute', 'drink'):
            for _ in range(n):
                at(95, 90, 90); at(95, 90, 105); self.hold()
                if family == 'drink': at(95, 90, 115); at(95, 90, 105)
                at(95, 90, 90); restore([hand])
            return f"{'salute' if family == 'salute' else 'mime taking a drink'} {n} times with your {side} hand beside your head, returning it after each repetition"
        if family in ('circle', 'square', 'triangle', 'figure_eight', 'spiral'):
            at(95, 100, 60)
            if family == 'square': points = [(0, 0), (size, 0), (size, size), (0, size), (0, 0)]
            elif family == 'triangle': points = [(0, 0), (size, 0), (size/2, size), (0, 0)]
            else:
                points = []
                for i in range(17 if family in ('figure_eight', 'spiral') else 9):
                    theta = i*math.pi/(8 if family=='figure_eight' else 4)
                    radius = size/2*(1+i/32) if family == 'spiral' else size/2
                    points.append((radius*math.sin(theta), radius*(math.sin(2*theta) if family == 'figure_eight' else 1-math.cos(theta))))
            for _ in range(n):
                for y,z in points[1:]: at(95, 100+y, 60+z)
                at(95, 100, 60)
            restore([hand])
            return f'trace {n} {family.replace("_", " ")} shapes in a vertical plane with your {side} hand, then return it'
        if family == 'scoop':
            for _ in range(n):
                at(90, 90, 30); at(90+size, 90, 30); at(90+size, 90, 60); at(90, 90, 60); self.hold()
            restore([hand]); return f'mime scooping upward {n} times with your {side} hand, then return it'
        if family == 'throw':
            for _ in range(n):
                at(90, 100, 80); at(80, 100+size/2, 90); at(110, 100-size/2, 70); restore([hand])
            return f'mime {n} diagonal throws using your {side} arm, putting it back after each'
        if family in ('clap', 'conduct', 'flap', 'shrug'):
            both(95, 100, 65)
            for _ in range(n):
                if family == 'clap': both(105, 100-size, 65); both(95, 100, 65)
                elif family == 'conduct': both(95, 100+size, 65+size/2); both(95, 100, 65)
                elif family == 'flap': both(95, 100+size/2, 65+size); both(95, 100+size/2, 65)
                else: both(95, 100, 65+size); self.hold(); both(95, 100, 65)
            restore(hands)
            return f'mime {n} {family} cycles with both hands, then return both hands'
        if family == 'drum':
            both(95, 95, 50)
            for _ in range(n):
                for limb in (hand, other):
                    y = 95 if limb.endswith('left') else -95
                    self.target({limb:[95, y, 50+size]}); self.target({limb:[95, y, 50]})
            restore(hands); return f'drum {n} alternating pairs starting with the {side} hand, then return both'
        if family in ('microphone', 'hammer'):
            self.target({other:[95, -sign*90, 105 if family == 'microphone' else 50]})
            at(100, 110, 70)
            for _ in range(n):
                if family == 'microphone': at(110, 110+size, 80); at(100, 110, 70)
                else: at(100, 110, 70-size); at(100, 110, 70)
            restore([hand]); restore([other])
            return (f'hold an imaginary microphone beside your head with the {"left" if side == "right" else "right"} hand while the {side} hand gestures outward {n} times, then return both hands'
                    if family == 'microphone' else f'hold an imaginary nail with one hand and hammer {n} times using the {side} hand, then return both')
        if family == 'fold':
            both(95, 100, 90); both(110, 30, 90); self.hold(); both(95, 100, 90); restore(hands)
            return 'fold both hands inward near your chest, pause, then unfold and return them'
        if family in ('bow', 'sway', 'squat', 'twist'):
            for _ in range(n):
                if family == 'bow':
                    self.torso(rotation=(0, 6, 0)); self.hold(); self.torso(rotation=(0, -6, 0))
                elif family == 'squat':
                    self.torso((0, 0, -size/2)); self.hold(); self.torso((0, 0, size/2))
                elif family == 'sway':
                    self.torso((0, sign*size/4, 0)); self.torso((0, -sign*size/2, 0)); self.torso((0, sign*size/4, 0))
                else:
                    self.torso(rotation=(0, 0, sign*4)); self.torso(rotation=(0, 0, -sign*8)); self.torso(rotation=(0, 0, sign*4))
            return f'{family} with your torso for {n} complete cycles, returning the torso after each'
        if family in ('step_over', 'shuffle'):
            for _ in range(n):
                for limb in (hand, other):
                    anchor = self.current[limb][:]
                    path = ((0, size), (size, size), (size, 0), (size, size), (0, size), (0, 0)) if family=='step_over' else ((-size, 0), (-size, size/4), (0, size/4), (0, 0))
                    for dx,dz in path:
                        self.target({limb:[anchor[0]+dx, anchor[1], anchor[2]+dz]})
            return f'mime {n} pairs of {"stepping over a low bar" if family == "step_over" else "backward foot slides with forward resets"}, {side} front foot first, returning each foot'
        raise ValueError(family)


def example(request, observation, program, family, **metadata):
    query = compact({'request':request, 'event':metadata.pop('event', None),
                     'observation':observation, 'history':metadata.pop('history', [])})
    identity = signature([query, program])
    return {'id':identity[:16], 'family':family, 'query':query, 'answers':program,
            'source_id':'curriculum-v8:'+identity, 'source_hash':identity,
            'synthetic':True, 'physical_qualification':False, **metadata}


def composition_group(tasks):
    # No side, wording, magnitude, timing, or starting-pose leakage.
    return 'composition:'+','.join(tasks)


def composition_split(tasks):
    if len(tasks) == 1: return 'train'
    bucket = int(signature(composition_group(tasks))[:8], 16) % 10
    return 'evaluation' if bucket == 0 else 'test' if bucket == 1 else 'train'


def compositions(seed, count):
    rng = random.Random(seed)
    chains = [(task,) for task in TASKS]
    while len(chains) < count+len(TASKS):
        chain = tuple(rng.sample(TASKS, rng.choice((2, 2, 3))))
        if chain not in chains: chains.append(chain)
    for chain in chains:
        for variant in range(2):
            pose = rng.choice(('stand', 'sit', 'crouch', 'rest'))
            state = source_state(pose)
            duration, pause = rng.choice((.35, .5, .7)), rng.choice((.25, .5, .8))
            author = Author(state, duration, pause)
            phrases = []
            spans = []
            for task in chain:
                size = rng.choice((12, 16, 20))
                begin=len(author.program)
                phrase = author.task(task, rng.choice(('left', 'right')), rng.choice((1, 2, 3)), size)
                spans.append({'family':task,'action_start':begin,'action_end':len(author.program)})
                phrases.append(phrase+' using '+{12:'compact',16:'medium',20:'broad'}[size]+' gestures')
            return_requested = variant == 0
            if return_requested: author.target(author.initial)
            request = '. Then '.join(phrases)+'.'
            request += f' Use {duration} second travel segments and {pause} second pauses where described.'
            request += ' Finish in your starting pose.' if return_requested else ' Leave the final requested pose in place.'
            yield example(request, state, author.program, 'open_composition' if len(chain)>1 else 'open_task',
                          task_families=list(chain), composition_group=composition_group(chain),
                          task_spans=spans,
                          split=composition_split(chain), starting_pose=pose,
                          goals=author.goals, returns_to_start=return_requested,
                          teacher='agent-authored Cartesian task templates, generated deterministically')


def recovery_examples():
    """Coherent counterfactual episodes; no synthetic outcome is physical proof."""
    for side in ('left', 'right'):
        for span in (8, 12, 16, 20):
            for direction in (-1, 1):
                for cycles in (1, 2, 3):
                    state = source_state('sit')
                    joint = f'front_{side}_shoulder'
                    start = state['joints'][joint]['model_deg']; blocked = start+direction*span
                    target = blocked+direction*8
                    state['joints'][joint].update(model_deg=blocked, commanded_model_deg=target,
                                                 velocity_deg_s=0, sampled_us=3000000)
                    state['action'] = {'name':'wave', 'remaining_cycles':cycles, 'period_s':1.5}
                    state['feedback'].update(stalled_joints=1 << JOINTS.index(joint), no_progress_ms=1000)
                    history = [{'time_us':t, 'joints':{joint:q}, 'target_deg':goal}
                               for t,q,goal in ((1000000,start,blocked), (2000000,blocked,target), (3000000,blocked,target))]
                    center = round((start+blocked)/2, 4)
                    program = [call('move', joint=joint, angle_deg=center, reference='absolute', speed_pct=50),
                               call('oscillate', joint=joint, amplitude_deg=span/2, cycles=cycles, period_s=1.5),
                               call('reassess')]
                    yield example(f'Finish waving with the {side} hand despite the jam; adapt the remaining {cycles} cycles to the range just traversed.',
                                  state, program, 'recovery_wave', event={'type':'servo_stall','joints':[joint]}, history=history,
                                  episode_group=f'wave:{side}:{span}:{direction}', split='train',
                                  evidence_scope='synthetic jam and traversed range; continuation outcome unknown')
    for event in ('slip', 'tipped'):
        for pose in ('stand', 'sit', 'crouch', 'rest'):
            for axis in ('roll', 'pitch'):
                for direction in (-1, 1):
                    for improved in (False, True):
                        state = source_state(pose)
                        joints = ['rear_left_carrier', 'rear_right_carrier'] if axis == 'roll' else ['front_left_carrier', 'rear_left_carrier']
                        delta = {j:direction*(3 if i==0 else -3) for i,j in enumerate(joints)}
                        before = direction*(70 if event=='tipped' else 18)
                        after = before*(.8 if improved else 1.15)
                        history = [{'time_us':2000000, 'imu':imu(before, axis, 2000000),
                                    'joints':{j:state['joints'][j]['model_deg']-delta.get(j, 0) for j in JOINTS},
                                    'correction_delta_deg':delta},
                                   {'time_us':3000000, 'imu':imu(after, axis, 3000000),
                                    'joints':{j:state['joints'][j]['model_deg'] for j in JOINTS}}]
                        state['imu'] = imu(after, axis, 3000000); state['expected_up'] = [0, 0, 1]
                        state['action'] = {'name':'walk' if event=='slip' else 'freestyle', 'remaining_cycles':2}
                        program = [call('pose', joints=joints, angles_deg=[delta[j]*(1 if improved else -1) for j in joints],
                                        reference='current', speed_pct=50), call('reassess')]
                        yield example('Adapt the correction after this '+('slip while walking.' if event=='slip' else 'fall onto my side.')+
                                      ' Use the measured effect of the previous attempt and observe again.',
                                      state, program, 'recovery_'+event, event={'type':event}, history=history,
                                      episode_group=f'{event}:{pose}:{axis}:{direction}:{improved}', split='train',
                                      evidence_scope='synthetic observed trend, no causal dynamics or get-up qualification')


def audit(item):
    trace = replay(item['answers'], json.loads(item['query'])['observation'])
    allowed_prefix = trace['status']=='not_fully_replayed' and trace.get('operation') in ('reassess', 'gait', 'stop')
    accepted = trace['status']=='replayed' or allowed_prefix
    evidence = {'id':item['id'], 'status':trace['status'], 'completed_actions':trace['completed_actions'],
                'error':trace.get('error'), 'operation':trace.get('operation'), 'accepted':accepted,
                'proof':'kinematic prefix' if allowed_prefix else 'full kinematic trajectory',
                'physical_success':None, 'sample_count':len(trace['samples'])}
    if accepted and item.get('goals'):
        grouped = defaultdict(list)
        for sample in trace['samples']: grouped[sample['action_index']].append(sample)
        worst_endpoint, worst_path, worst_time = 0., 0., 0.
        previous_time = 0.
        for index, goal in enumerate(item['goals']):
            samples = grouped[index]
            if not samples:
                evidence.update(accepted=False, error='missing requested action samples'); break
            end = samples[-1]
            worst_time = max(worst_time, abs(end['time_s']-previous_time-goal['seconds']))
            for leg in goal['after']:
                worst_endpoint = max(worst_endpoint, math.dist(end['feet_body_mm'][leg], goal['after'][leg]))
                if goal['kind']=='line':
                    for sample in samples:
                        u = min(1, (sample['time_s']-previous_time)/goal['seconds'])
                        point = [a+(b-a)*u for a,b in zip(goal['before'][leg], goal['after'][leg])]
                        worst_path = max(worst_path, math.dist(sample['feet_body_mm'][leg], point))
            previous_time = end['time_s']
        evidence.update(max_endpoint_error_mm=worst_endpoint, max_linear_path_error_mm=worst_path,
                        max_action_duration_error_s=worst_time, requested_goals=len(item['goals']))
        # Offline measurement tolerance only; never an execution restriction.
        evidence['accepted'] &= worst_endpoint < .15 and worst_path < .15 and worst_time < .002
    return item, evidence


def prune_rehearsal(rows):
    """Keep distinct references, not arbitrary repetitions of the same target."""
    selected, decisions, seen_query, seen_target = [], [], {}, set()
    counts = Counter()
    for row in sorted(rows, key=lambda r:r['id']):
        value = json.loads(row['query']); family = row['family']
        event = value.get('event')
        reason = None
        if event or any(s in family for s in ('jam', 'fall', 'slip', 'feedback', 'resume')):
            reason = 'replace old synthetic recovery envelopes with coherent episodes'
        elif row['source_id'].startswith(('host-input:', 'natural-feedback:')):
            reason = 'remove redundant envelope-only variants'
        elif 'composition' in family:
            reason = 'replace old compositions with grouped curriculum splits'
        target = signature(row['answers'])
        if row['query'] in seen_query:
            reason = 'duplicate query' if seen_query[row['query']]==target else 'conflicting query'
        seen_query[row['query']] = target
        if target in seen_target: reason = reason or 'duplicate target program'
        cap = 12 if row['source_id'].startswith('compositional:') else 16
        if counts[family] >= cap: reason = reason or 'balanced rehearsal sample already represented'
        if reason is None:
            item = copy.deepcopy(row)
            item.update(split='train', rehearsal=True, synthetic=True, physical_qualification=False)
            selected.append(item); seen_target.add(target); counts[family] += 1
        decisions.append({'id':row['id'], 'family':family, 'kept':reason is None, 'reason':reason})
    return selected, decisions


def summarize(rows):
    return {'rows':len(rows), 'distinct_requests':len({json.loads(r['query'])['request'] for r in rows}),
            'distinct_queries':len({r['query'] for r in rows}),
            'distinct_programs':len({signature(r['answers']) for r in rows}),
            'families':dict(Counter(r['family'] for r in rows)),
            'task_families':dict(Counter(t for r in rows for t in r.get('task_families', []))),
            'composition_groups':len({r['composition_group'] for r in rows if r.get('composition_group')}),
            'starting_poses':dict(Counter(r.get('starting_pose', 'rehearsal_or_recovery') for r in rows)),
            'action_count':{'min':min((len(r['answers']) for r in rows), default=0),
                            'max':max((len(r['answers']) for r in rows), default=0),
                            'over_20':sum(len(r['answers'])>20 for r in rows)}}


def build(source, output, count=240, workers=6, seed=8101, audit_cache=None):
    output.mkdir(parents=True, exist_ok=False)
    originals = read_rows(source/'train.jsonl')
    rehearsal, pruning = prune_rehearsal(originals)
    candidates = list(compositions(seed, count))+list(recovery_examples())+rehearsal
    write_rows(output/'candidates.jsonl', candidates)
    write_rows(output/'pruning.jsonl', pruning)
    accepted, rejected, evidence_rows = [], [], []
    cached = {}
    if audit_cache:
        old_items = {r['id']:r for r in read_rows(audit_cache/'candidates.jsonl')}
        old_evidence = {r['id']:r for r in read_rows(audit_cache/'audit.jsonl')}
        for item in candidates:
            old = old_items.get(item['id'])
            if old and item['id'] in old_evidence and all(old.get(k)==item.get(k) for k in ('query','answers','goals')):
                cached[item['id']] = old_evidence[item['id']]
    with ProcessPoolExecutor(workers) as pool, (output/'audit.jsonl').open('x') as audit_stream:
        pending = [pool.submit(audit,item) for item in candidates if item['id'] not in cached]
        def results():
            for item in candidates:
                if item['id'] in cached: yield item, cached[item['id']]
            for future in as_completed(pending): yield future.result()
        for number, (item, evidence) in enumerate(results(), 1):
            evidence_rows.append(evidence); audit_stream.write(compact(evidence)+'\n'); audit_stream.flush()
            item['kinematic_evidence'] = evidence
            (accepted if evidence['accepted'] else rejected).append(item)
            if number%20==0: print(compact({'audited':number, 'total':len(candidates), 'accepted':len(accepted)}), flush=True)
    accepted.sort(key=lambda r:r['id']);rejected.sort(key=lambda r:r['id'])
    splits = {name:[r for r in accepted if r['split']==name] for name in ('train', 'evaluation', 'test')}
    for name,rows in splits.items(): write_rows(output/(name+'.jsonl'), rows)
    write_rows(output/'rejected.jsonl', rejected)
    # The previous numerical fold is a separate retention check, not the new
    # composition-generalization metric. Never silently mix the two scores.
    for name in ('system.txt', 'tools.json'): (output/name).write_bytes((source/name).read_bytes())
    (output/'regression-evaluation.jsonl').write_bytes((source/'evaluation.jsonl').read_bytes())
    leakage = {}
    for left,right in (('train','evaluation'),('train','test'),('evaluation','test')):
        leakage[left+'_'+right] = {key:len({r[key] for r in splits[left] if key in r}&{r[key] for r in splits[right] if key in r})
                                  for key in ('query','composition_group')}
    manifest = {'version':8, 'source_manifest_sha256':digest(source/'manifest.json'),
                'source_train_sha256':digest(source/'train.jsonl'), 'generator_sha256':digest(Path(__file__)),
                'seed':seed, 'splits':{k:summarize(v) for k,v in splits.items()},
                'pruning':{'input_rows':len(originals), 'selected_rehearsal':len(rehearsal),
                           'reasons':dict(Counter(r['reason'] for r in pruning if not r['kept']))},
                'audit':{'candidates':len(candidates), 'accepted':len(accepted), 'rejected':len(rejected),
                         'reused_identical_cases':len(cached),'audit_cache':str(audit_cache) if audit_cache else None},
                'leakage':leakage, 'synthetic':True, 'physical_trials':0,
                'limits':['Task interpretations are authored, not human demonstrations or independent semantic ratings.',
                          'Cartesian replay does not model balance, collisions, friction, contact, or get-up dynamics.',
                          'Recovery examples teach feedback-conditioned continuations; actual outcomes remain unknown.',
                          'Composition holdouts are new to this dataset; prior-model exposure is not ruled out by this split.',
                          'The frozen external challenge remains necessary for genuinely unseen-language evaluation.']}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(compact(manifest), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compositions', type=int, default=240)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--seed', type=int, default=8101)
    parser.add_argument('--audit-cache', type=Path)
    args = parser.parse_args()
    build(args.source, args.output, args.compositions, args.workers, args.seed, args.audit_cache)
