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
    """Compact authored stages; source paths are provenance, not curve targets."""
    from .kinematics import ROOT
    from .runtime import JOINTS
    compiler,clips=legacy_sources();clip=clips[name];rows=clip['positions']
    clip_source=json.loads((ROOT/'motions/gestures'/name/'source.json').read_text())['samples']
    number=lambda value:round(value/100,2)
    entry=[number(v) for v in rows[0]]
    if name=='stretch':
        # Owner's requested crouch, front-limb extension, holds and standing finish.
        # The old Blender/source curve lacks the accepted extension.
        program=stretch_program(entry)
        final=entry
    else:
        program=[call('face',expr=name),call('pose',joints=list(JOINTS),
            angles_deg=entry,reference='absolute',speed_pct=50,taper_deg=0)]
        previous=list(rows[0])
        for phase in clip['phases']:
            begin,end=[round(t*120) for t in phase['source_interval_s']]
            if phase.get('moving_joint_indices')==[] or 'hold' in phase['name'].lower():
                program.append(call('hold',seconds=round(phase['source_interval_s'][1]-phase['source_interval_s'][0],6)))
                continue
            if name=='wave' and phase['name']=='three_playful_waves':
                # The source holds every joint except the left front shoulder.
                # Its three full cycles have the same entry and exit pose.
                joint=6
                values=[row[joint]/100 for row in rows[begin:end+1]]
                amplitude=round((max(values)-min(values))/2,2)
                program.append(call('oscillate',joint=JOINTS[joint],amplitude_deg=amplitude,
                                    cycles=3,speed_pct=50,taper_deg=0))
                previous=list(rows[end])
                continue
            landmarks=[end]
            # Keep the source's lifted-foot waypoint before placing the foot.
            # Phase endpoints alone erase the step and teach floor dragging.
            if phase['name']!='three_playful_waves':
                for leg in range(4):
                    clearances=[row['sole_clearance_mm'][leg] for row in clip_source[begin:end+1]]
                    peak=max(range(len(clearances)),key=clearances.__getitem__)
                    if clearances[peak]>max(clearances[0],clearances[-1])+.01:
                        landmarks.append(begin+peak)
                landmarks=sorted(set(landmarks))
            if name=='shrug' and phase['name']=='Palms-out double shrug':
                # Retain each authored shrug's outer pose and return, instead
                # of collapsing the whole phase into one terminal pose.
                middle=(begin+end)//2
                landmarks=[]
                for first,last in ((begin,middle),(middle,end)):
                    peak=max(range(first,last+1),key=lambda i:sum(
                        (rows[i][j]-rows[first][j])**2 for j in range(12)))
                    landmarks.extend(sorted({peak,last}))
            for landmark in landmarks:
                goal=rows[landmark]
                ids=[i for i,(a,b) in enumerate(zip(previous,goal)) if round(a)!=round(b)]
                if ids:
                    travel=max(abs(goal[i]-previous[i]) for i in ids)/100
                    program.append(call('pose',joints=[JOINTS[i] for i in ids],
                        angles_deg=[number(goal[i]) for i in ids],reference='absolute',speed_pct=50,
                        taper_deg=round(min(10,.2*travel),2) if name in ('sit','rest','crouch') else 0))
                previous=list(goal)
        final=[number(v) for v in rows[-1]]
    path=ROOT/'motions/gestures'/name/'source.json'
    return {'program':program,'source_path':str(path.relative_to(ROOT.parents[3])),
            'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'execution_contract_sha256':hashlib.sha256(path.with_name('execution-contract.json').read_bytes()).hexdigest(),
            'semantic_end_s':clip['duration_s'],'source_samples':len(rows),
            'phases':[{'name':p['name'],'source_interval_s':p['source_interval_s']} for p in clip['phases']],
            'intentional_hold_s':round(sum(a['arguments']['seconds'] for a in program if a['name']=='hold'),6),
            'entry_model_deg':entry,'final_model_deg':final,
            'representation':'compact movement stages; no continuous source-curve fidelity claim'}


def stretch_program(entry=None):
    """Editable compact stretch; geometry checked, physical acceptance separate."""
    from .runtime import JOINTS
    entry=entry if entry is not None else [0,.94,-21.25]*4
    body=lambda dz:call('body',translation_mm=[0,0,dz],rotation_deg=[0,0,0],
                        legs=[],foot_offsets_mm=[],speed_pct=100,taper_deg=0)
    hands=lambda dx:call('feet',legs=['front_left','front_right'],offsets_mm=[[dx,0,0]]*2,
                         speed_pct=100,taper_deg=0)
    return [call('face',expr='stretch'),
            call('pose',joints=list(JOINTS),angles_deg=entry,reference='absolute',speed_pct=100,taper_deg=0),
            body(-20),hands(30),call('hold',seconds=.9),hands(5),call('hold',seconds=.7),
            hands(-35),body(20),
            call('pose',joints=list(JOINTS),angles_deg=entry,reference='absolute',speed_pct=100,taper_deg=0),
            call('hold',seconds=.5),call('face',expr='stand')]


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
        if action['name'] in ('pose','move','feet','body','oscillate'):action['arguments']['speed_pct'] = speed_pct
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
