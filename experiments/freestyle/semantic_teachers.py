"""Offline robot demonstrations for language training, never a runtime dispatcher.

These programs teach spatial composition, sides, repetitions and returns. Their
authoring vocabulary is not the generator's action vocabulary or capability list.
Every exported demonstration is replayed with the V2 geometry before training;
successful replay does not establish balance, contact or physical recovery.
"""
import argparse
import copy
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

from .challenge import assess, read_rows, replay, trajectory_metrics, write_rows
from .runtime import compact


@lru_cache(maxsize=1)
def legacy_sources():
    """The native importer's catalog, hashes and semantic completion."""
    from .kinematics import ROOT
    from .trajectory import native_compiler
    compiler=native_compiler()
    return compiler,{clip['command']:clip for clip in compiler.load_gestures(ROOT)}


@lru_cache(maxsize=None)
def source_motion(name):
    """Complete catalog motion as generated cubic curves, never named dispatch.

    Scalar tracks avoid repeating twelve coordinates at every global knot.
    Each fit uses the native compiler and its 0.005-degree budget. Native phase
    boundaries/reversals remain measured checkpoints. Semantic completion,
    intentional holds and the posture travel deceleration remain source-owned.
    """
    from .kinematics import ROOT
    from .runtime import JOINTS
    compiler,clips=legacy_sources();clip=clips[name];rows=clip['positions']
    required=compiler.gesture_targets(rows,clip['phases'])
    phase_boundaries={round(t*120) for p in clip['phases'] for t in p['source_interval_s']}
    native_knots,velocities,_=compiler.compact(rows,required)
    tracks=[];bound=0.
    number=lambda v:float(f'{v:.9g}')  # Native storage uses float32.
    for j in range(12):
        column=[row[j] for row in rows]
        if max(column)-min(column)<=compiler.COMPRESSION_ERROR_CD:
            tracks.append([[0.,number(column[0]/100),0.],
                           [clip['duration_s'],number(column[-1]/100),0.]])
            bound=max(bound,(max(column)-min(column))/100)
        else:
            # Other joints' reversals are checkpoints on the coordinated
            # player, not extra knots needed in this scalar curve's fit.
            indices,_,error=compiler.compact([[v]*12 for v in column],phase_boundaries)
            tracks.append([[number(i/120),number(rows[i][j]/100),number(velocities[i][j]/100)] for i in indices])
            bound=max(bound,error/100)
    authored_holds=[tuple(round(t*120) for t in p['source_interval_s']) for p in clip['phases']
                    if p.get('moving_joint_indices')==[] or p['name'].startswith('hold_')]
    clock=compiler.travel_clock(rows,native_knots,velocities,authored_holds)
    holds=[]
    for a,b in zip(clock,clock[1:]):
        if b[2]>a[2]:
            begin,end=a[0]/120,b[0]/120
            if holds and holds[-1][1]==begin:holds[-1]=(holds[-1][0],end)
            else:holds.append((begin,end))
    action=call('trajectory',joints=list(JOINTS),tracks=tracks,
                checkpoints_s=[number(i/120) for i in required],
                holds_s=[[number(t) for t in p] for p in holds],
                expected_up=[[number(i/120),[number(v) for v in clip['expected_up'][i]]]
                             for i in compiler.compact_up(clip['expected_up'])],
                speed_pct=50,taper_deg=0.)
    if name in ('sit','rest','crouch'):
        action['arguments']['taper_deg']=min(10.,.2*clock[-1][1])
    path=ROOT/'motions/gestures'/name/'source.json'
    return {'program':[call('face',expr=name),action],
            'source_path':str(path.relative_to(ROOT.parents[3])),
            'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'execution_contract_sha256':hashlib.sha256(path.with_name('execution-contract.json').read_bytes()).hexdigest(),
            'semantic_end_s':clip['duration_s'],'source_samples':len(rows),
            'phases':[{'name':p['name'],'source_interval_s':p['source_interval_s']} for p in clip['phases']],
            'required_source_samples':required,'path_error_bound_deg':bound,
            'intentional_hold_s':clock[-1][2],
            'native_distance_degrees':clock[-1][1],
            'scalar_curve_knots':sum(map(len,tracks)),
            'entry_model_deg':[number(v/100) for v in rows[0]],
            'final_model_deg':[number(v/100) for v in rows[-1]]}


def call(name, **arguments):
    return {'name':name, 'arguments':arguments}


def feet(legs, offsets, seconds=.6):
    return call('feet', legs=legs, offsets_mm=offsets, seconds=seconds)


def body(translation=(0,0,0), rotation=(0,0,0), seconds=.8):
    return call('body', translation_mm=list(translation), rotation_deg=list(rotation),
                legs=[], foot_offsets_mm=[], seconds=seconds)


def path(leg, points, seconds=.5):
    """Relative deltas between authored points, including the explicit return."""
    return [feet([leg], [[round(b-a,3) for a,b in zip(p,q)]], seconds)
            for p,q in zip(points, points[1:])]


def circle(leg, radius=15, plane='xy', cycles=1):
    a,b = ['xyz'.index(axis) for axis in plane]
    points=[]
    for i in range(8*cycles+1):
        theta=2*math.pi*i/8
        point=[0.,0.,0.]
        point[a]=round(radius*math.sin(theta),3)
        outward=-1 if leg.endswith('right') and 'xyz'[b]=='y' else 1
        point[b]=round(outward*radius*(1-math.cos(theta)),3)
        points.append(point)
    return path(leg,points,.25)


def demonstration(family, side='right', cycles=2, scale=1., observation=None):
    """Authored semantic examples, not aliases of existing named robot emotes."""
    leg='front_'+side
    other='front_'+('left' if side=='right' else 'right')
    sign=1 if side=='left' else -1
    hands=['front_left','front_right']
    h=round(30*scale,3); d=round(20*scale,3)
    lift=lambda ls:feet(ls,[[0,0,h] for _ in ls])
    lower=lambda ls:feet(ls,[[0,0,-h] for _ in ls])
    hold=call('hold',seconds=.6)
    if family in ('drinking','saluting'):
        from .kinematics import ROOT, foot_positions
        from .runtime import JOINTS
        if observation is None:
            source=json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
            values=[math.degrees(q) for limb in source['samples'][0]['actuator_angles_rad'] for q in limb]
            positions=dict(zip(JOINTS,values))
        else:
            positions={j:observation['joints'][j]['model_deg'] for j in JOINTS}
        initial=foot_positions(positions)[leg]
        # A reachable point beside the head, above the 80.96 mm shoulder
        # reference. An arbitrary 40-50 mm lift did not reach this region.
        head=[round(b-a,3) for a,b in zip(initial,[95,sign*90,105])]
    if family=='clapping':
        # Deliberate in/out mime; contact between hands is not claimed.
        return [lift(hands)]+[a for _ in range(cycles) for a in (
            feet(hands,[[0,-d,0],[0,d,0]],.35),feet(hands,[[0,d,0],[0,-d,0]],.35))]+[lower(hands)]
    if family=='hand_circle':
        return [body(rotation=(0,4,0)),lift([leg])]+circle(leg,d/2,cycles=cycles)+[lower([leg]),body(rotation=(0,-4,0))]
    if family=='alternating_side_stretch':
        result=[]
        for limb,s in [(leg,sign),(other,-sign)]:
            result += [feet([limb],[[0,s*d,h]]),body(rotation=(s*4,0,0)),hold,
                       body(rotation=(-s*4,0,0)),feet([limb],[[0,-s*d,-h]])]
        return result
    if family in ('pushing','pulling'):
        direction=1 if family=='pushing' else -1
        return [lift(hands)]+[a for _ in range(cycles) for a in (
            feet(hands,[[direction*d,0,0]]*2),hold,feet(hands,[[-direction*d,0,0]]*2))]+[lower(hands)]
    if family=='drinking':
        return path(leg,[[0,0,0],[d,0,h],head])+[hold]+path(leg,[head,[d,0,h],[0,0,0]])
    if family=='draw_then_pull':
        # Place the drawing plane outward from the chosen shoulder. Its left-to-
        # right stroke still spans d mm; neither the vertical nor pull is cut.
        end_y=sign*d
        return path(leg,[[0,0,0],[d,end_y+d,h],[d,end_y,h],[d,end_y,h+d],
                         [0,end_y,h+d],[0,end_y,0],[0,0,0]])
    if family=='drumming':
        return [a for _ in range(cycles) for limb in [leg,other]
                for a in (feet([limb],[[d/2,0,h]],.3),feet([limb],[[-d/2,0,-h]],.25))]
    if family=='saluting':
        # Lowering the torso raises fixed foot coordinates by 8 mm relative to
        # it. Compute the reach from that changed pose, then preserve returns.
        reach=[head[0],head[1],round(head[2]-8,3)]
        return [body((0,0,-8))]+[a for _ in range(cycles) for a in (
            feet([leg],[reach],.5),hold,feet([leg],[[-v for v in reach]],.5))]+[body((0,0,8))]
    if family=='wiping':
        return [lift([leg])]+[a for _ in range(cycles) for a in (
            feet([leg],[[0,d,0]],.4),feet([leg],[[0,-2*d,0]],.7),feet([leg],[[0,d,0]],.4))]+[lower([leg])]
    if family=='stirring':
        return [body(rotation=(0,4,0)),lift([leg])]+circle(leg,d/2,cycles=cycles)+[lower([leg]),body(rotation=(0,-4,0))]
    if family=='guitar_strumming':
        # One hand holds the imaginary neck; the other makes vertical strokes.
        return [feet([other,leg],[[d,0,h],[d,0,h+d]])]+[
            a for _ in range(cycles) for a in (
                feet([leg],[[0,0,-d]],.3),feet([leg],[[0,0,d]],.3))]+[
            feet([other,leg],[[-d,0,-h],[-d,0,-h-d]])]
    if family=='bird_mime':
        return [feet(hands,[[0,d,h],[0,-d,h]])]+[
            a for _ in range(cycles) for a in (
                feet(hands,[[0,0,d/2],[0,0,d/2]],.4),body(rotation=(3,0,0)),
                feet(hands,[[0,0,-d/2],[0,0,-d/2]],.4),body(rotation=(-6,0,0)),
                body(rotation=(3,0,0)))]+[feet(hands,[[0,-d,-h],[0,d,-h]])]
    if family=='airplane_mime':
        return [feet(hands,[[0,d,h],[0,-d,h]]),hold,
                body(rotation=(4,0,0)),hold,body(rotation=(-8,0,0)),hold,
                body(rotation=(4,0,0)),feet(hands,[[0,-d,-h],[0,d,-h]])]
    if family=='two_hand_window_wiping':
        return [lift(hands)]+[a for _ in range(cycles) for a in (
            feet(hands,[[0,d,0]]*2,.4),feet(hands,[[0,-2*d,0]]*2,.7),
            feet(hands,[[0,d,0]]*2,.4))]+[lower(hands)]
    if family=='hammering':
        return [feet([other,leg],[[d/2,0,h/2],[d,0,h+d]])]+[
            a for _ in range(cycles) for a in (
                feet([leg],[[0,0,-d]],.25),feet([leg],[[0,0,d]],.5))]+[
            feet([other,leg],[[-d/2,0,-h/2],[-d,0,-h-d]])]
    if family=='swat_then_shrug':
        return [lift([leg])]+[a for _ in range(cycles) for a in (
            feet([leg],[[0,sign*d,0]],.3),feet([leg],[[0,-sign*d,0]],.5))]+[
            lower([leg]),lift(hands),hold,lower(hands)]
    if family=='moonwalk':
        # Authored backward-glide/alternating-reset kinematics. Contact, friction
        # and balance are not simulated; this is not a measured walking gait.
        pairs=[['front_left','rear_right'],['front_right','rear_left']]
        return [a for _ in range(cycles) for pair in pairs for a in (
            body((-d/2,0,0),seconds=.7),feet(pair,[[0,0,h/3]]*2,.3),
            feet(pair,[[-d,0,0]]*2,.5),feet(pair,[[0,0,-h/3]]*2,.3))]
    if family=='boxing':
        return [lift(hands)]+[a for _ in range(cycles) for limb in [leg,other]
                for a in (feet([limb],[[d,0,0]],.3),feet([limb],[[-d,0,0]],.4))]+[lower(hands)]
    if family=='beckoning':
        return [lift([leg]),feet([leg],[[d,0,0]])]+[a for _ in range(cycles) for a in (
            feet([leg],[[-d,0,d/2]],.4),feet([leg],[[d,0,-d/2]],.4))]+[feet([leg],[[-d,0,0]]),lower([leg])]
    if family=='conducting':
        return [lift(hands)]+[a for _ in range(cycles) for a in (
            feet(hands,[[0,d,d/2],[0,-d,d/2]],.4),
            feet(hands,[[0,-d,-d/2],[0,d,-d/2]],.4))]+[lower(hands)]
    if family=='shrugging':
        return [a for _ in range(cycles) for a in (lift(hands),hold,lower(hands))]
    if family=='bobbing':
        return [a for _ in range(cycles) for a in (body((0,0,-8)),body((0,0,8)))]
    if family=='swaying':
        return [a for _ in range(cycles) for a in (body((0,5,0)),body((0,-10,0)),body((0,5,0)))]
    if family=='twisting':
        return [a for _ in range(cycles) for a in (body(rotation=(0,0,4)),body(rotation=(0,0,-8)),body(rotation=(0,0,4)))]
    if family=='bowing':
        return [body(rotation=(0,6,0)),hold,body(rotation=(0,-6,0))]
    if family=='tapping':
        return [a for _ in range(cycles) for a in (feet([leg],[[0,0,h]],.3),feet([leg],[[0,0,-h]],.3))]
    if family=='cross_reach':
        return [lift([leg]),feet([leg],[[d,-sign*d,0]]),hold,feet([leg],[[-d,sign*d,0]]),lower([leg])]
    if family=='windshield':
        return [lift(hands)]+[a for _ in range(cycles) for a in (
            feet(hands,[[0,d,0]]*2,.4),feet(hands,[[0,-2*d,0]]*2,.8),feet(hands,[[0,d,0]]*2,.4))]+[lower(hands)]
    raise ValueError(f'No authored teaching example for {family}')


def source_posture(name, speed_pct=50):
    """Complete source entry and hold for posture prefixes in compositions."""
    if name not in ('sit', 'rest', 'crouch'):
        raise ValueError('This teacher covers only single-transition postures')
    program = copy.deepcopy([a for a in source_motion(name)['program'] if a['name'] != 'face'])
    for action in program:
        if action['name'] in ('pose','trajectory'):action['arguments']['speed_pct'] = speed_pct
    return program


def review_one(item):
    trace=replay(item['program'],item['observation'])
    return {**item,'trace':trace,'metrics':trajectory_metrics(trace)}


def correct_round(trials_file, output, workers=2):
    output.mkdir(parents=True,exist_ok=False)
    items=[]
    for trial in read_rows(trials_file):
        family=trial['motion_family']
        cycles=5 if family=='clapping' else 2
        items.append({'id':trial['id'],'family':family,'program':demonstration(family,cycles=cycles),
                      'observation':trial['observation'],'criteria':trial.get('criteria',[])})
    reviews=[]
    with ProcessPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(review_one,item) for item in items]):
            item=future.result();trace=item.pop('trace')
            filename=item['id'].replace(':','_')+'.correction.json'
            evidence={**item,'trace':trace,'assessment':assess(item['metrics'],item['criteria'],trace),
                      'scope':'authored kinematic correction; physical task success not established'}
            if trace['status']!='replayed':
                evidence['assessment']['criteria_passed']=False
            (output/filename).write_text(compact(evidence)+'\n')
            reviews.append({'id':item['id'],'reviewer':'codex-semantic-path-review',
                            'motion_family':item['family'],'evidence':filename,
                            'corrected_program':item['program'],'replay_status':trace['status'],
                            'review_status':'awaiting trajectory review'})
            print(compact({'id':item['id'],'status':trace['status'],'error':trace.get('error'),
                           'criteria':evidence['assessment']['criteria_passed']}),flush=True)
    write_rows(output/'reviews.jsonl',reviews)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trials',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();correct_round(a.trials,a.output,a.workers)
