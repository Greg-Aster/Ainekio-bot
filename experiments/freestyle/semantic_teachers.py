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


def clamp_goal(goal, name):
    """Keep compact stage targets within the nominal 500..2750 us operating margin."""
    if name=='crouch':
        return list(goal)
    result=list(goal)
    for leg in range(4):
        sh,ca,cr=result[3*leg:3*leg+3]
        result[3*leg:3*leg+3]=(max(-9850,min(8900,sh)),
                               max(-2250,min(16600,ca)),
                               max(-10650,min(7750,cr)))
    return result


def stage_goals(name, phase, rows, clip_source, previous):
    """Unloaded foot-lift transitions and bounded posture stages per source phase."""
    pname=phase['name']
    begin,end=[round(t*120) for t in phase['source_interval_s']]
    stand_row=[0,94,-2125]*4
    if name in ('celebrate','cute','surprised','swim'):
        wide=[-2280,2859,-2877]*4
        lift=[-1305,-1400,-2400]
        if pname=='lower_onto_belly':
            g1=list(stand_row);g1[0:3]=lift;g1[9:12]=lift
            g2=list(stand_row);g2[0:3]=wide[0:3];g2[9:12]=wide[9:12]
            g3=list(g2);g3[3:6]=lift;g3[6:9]=lift
            g4=list(wide)
            return [g1,g2,g3,g4,clamp_goal(rows[end],name)]
        if pname=='return_to_standing':
            g1=list(wide)
            g2=list(wide);g2[0:3]=lift;g2[9:12]=lift
            g3=list(wide);g3[0:3]=stand_row[0:3];g3[9:12]=stand_row[9:12]
            g4=list(g3);g4[3:6]=lift;g4[6:9]=lift
            return [g1,g2,g3,g4,list(stand_row)]
    if name in ('sit','wave','point','shrug','upright'):
        lift_r=[0,-832,-199]
        plant_r=[0,2324,715]
        if pname in ('lower_into_sit','sit_down','squat_rear_legs','Sit upright','sit'):
            g1=list(stand_row);g1[0:3]=lift_r
            g2=list(stand_row);g2[0:3]=plant_r
            g3=list(g2);g3[3:6]=lift_r
            g4=list(g2);g4[3:6]=plant_r
            sit_goal=clamp_goal(rows[end],name)
            if name=='shrug':
                sit_goal[2]=-2663;sit_goal[5]=-2663
            return [g1,g2,g3,g4,sit_goal]
        if pname in ('return_to_standing','Return to standing'):
            g1=list(stand_row);g1[0:3]=plant_r;g1[3:6]=plant_r
            g2=list(g1);g2[0:3]=lift_r
            g3=list(g1);g3[0:3]=stand_row[0:3]
            g4=list(g3);g4[3:6]=lift_r
            return [g1,g2,g3,g4,list(stand_row)]
        if name=='wave' and pname=='extend_carrier_and_crank':
            g=clamp_goal(rows[end],name);g[6]=-5600
            return [g]
        if name=='shrug' and pname=='Palms-out double shrug':
            middle=(begin+end)//2
            landmarks=[]
            for first,last in ((begin,middle),(middle,end)):
                peak=max(range(first,last+1),key=lambda i:sum(
                    (rows[i][j]-rows[first][j])**2 for j in range(12)))
                landmarks.extend(sorted({peak,last}))
            goals=[]
            for lm in landmarks:
                g=clamp_goal(rows[lm],name)
                g[0:6]=[0,-2250,-2663,0,-2250,-2663]
                goals.append(g)
            return goals
        if name=='shrug' and pname in ('Lift both forelegs','Lower both forelegs'):
            g=clamp_goal(rows[end],name)
            g[0:6]=[0,-2250,-2663,0,-2250,-2663]
            return [g]
        if name=='upright':
            if pname=='front_left_back':
                g1=list(previous);g1[6:9]=[359,-1231,-4500]
                g2=[0,5069,5124,0,5069,5124,614,-2250,-6200,0,3318,1322]
                return [g1,g2]
            if pname=='brace_shift':
                return [[0,5070,5121,0,5070,5121,614,-2250,-6200,0,3317,1324]]
            if pname=='front_right_back':
                g1=[0,5093,5134,0,5093,5134,615,-2250,-6200,318,-1231,-4500]
                g2=[0,5095,5135,0,5095,5135,615,-2250,-6200,615,-2250,-6200]
                return [g1,g2]
    if name=='rest' and pname=='lower_into_rest':
        lift_r=[0,-832,-199]
        plant_r=[0,2185,608]
        g1=list(stand_row);g1[0:3]=lift_r;g1[9:12]=lift_r
        g2=list(stand_row);g2[0:3]=plant_r;g2[9:12]=plant_r
        g3=list(g2);g3[3:6]=lift_r;g3[6:9]=lift_r
        g4=list(plant_r*4)
        return [g1,g2,g3,g4,[0,-2250,1998]*4]
    if name in ('lay_down','dead'):
        leg_map={'Lift and place FL':0,'Lift and place FR':1,'Lift and place RL':2,'Lift and place RR':3}
        if pname in leg_map and begin<400:
            leg=leg_map[pname]
            g1=list(previous);g1[3*leg:3*leg+3]=[-941,600,740]
            g2=list(previous);g2[3*leg:3*leg+3]=[-1635,6417,1615]
            return [g1,g2]
        if name=='dead' and pname in ('Lift and place RL','Lift and place RR') and begin>=600:
            leg=2 if pname.endswith('RL') else 3
            g1=list(previous);g1[3*leg:3*leg+3]=[-4200,6348,7750]
            g2=list(previous);g2[3*leg:3*leg+3]=[-2333,9862,6562]
            return [g1,g2]
    if name=='bow':
        brace=[0,-275,-1366]*4
        lift_f=[0,-1800,-2400]
        plant_f=[0,5500,3500]
        if pname=='brace_stance':
            return [brace]
        if pname=='stretch_front_into_bow':
            g1=list(brace);g1[6:9]=lift_f
            g2=list(brace);g2[6:9]=plant_f
            g3=list(g2);g3[9:12]=lift_f
            g4=list(g2);g4[9:12]=plant_f
            return [g1,g2,g3,g4,[0,742,732,0,742,732,0,12082,7572,0,12082,7572]]
        if pname=='raise_front':
            g1=list(brace);g1[6:9]=plant_f;g1[9:12]=plant_f
            g2=list(g1);g2[6:9]=lift_f
            g3=list(g1);g3[6:9]=brace[6:9]
            g4=list(g3);g4[9:12]=lift_f
            return [g1,g2,g3,g4,brace]
        if pname=='return_to_standing':
            return [list(stand_row)]
    if name=='worm':
        if pname.startswith('body_wave_'):
            return [clamp_goal(rows[begin+48],name),clamp_goal(rows[begin+144],name),clamp_goal(rows[end],name)]
        if pname=='return_to_standing':
            return [list(stand_row)]
    if name=='pushup':
        top=[0,-1766,-2102,0,-1766,-2102,0,2381,-3280,0,2381,-3280]
        bottom=[0,-680,3023,0,-680,3023,0,-863,3157,0,-863,3157]
        if pname=='squat_rear_legs' or pname.endswith('_up'):
            return [top]
        if pname.endswith('_down'):
            return [bottom]
        if pname=='return_to_standing':
            return [list(stand_row)]
    if name=='curious':
        base=[0,-1146,-2239]*4
        if pname=='prepare_curious':
            return [base]
        if pname=='look_right':
            g1=[0,-1800,-2800,0,600,-1200,0,-1600,-2800,1200,-1800,-3200]
            g2=[0,-1800,-2800,0,600,-1200,0,-1600,-2800,1200,-470,-1000]
            return [g1,g2]
        if pname=='look_right_return':
            g1=[0,-1800,-2800,0,600,-1200,0,-1600,-2800,0,-1800,-3200]
            return [g1,base]
        if pname=='look_left':
            g1=[0,600,-1200,0,-1800,-2800,-1200,-1800,-3200,0,-1600,-2800]
            g2=[0,600,-1200,0,-1800,-2800,-1200,-470,-1000,0,-1600,-2800]
            return [g1,g2]
        if pname=='look_left_return':
            g1=[0,600,-1200,0,-1800,-2800,0,-1800,-3200,0,-1600,-2800]
            return [g1,base]
        if pname=='inquisitive_front_lean':
            return [[0,-1030,-2031,0,-1030,-2031,0,-2200,-2789,0,-2200,-2789]]
        if pname=='inquisitive_front_lean_return':
            return [base]
    if name=='sad':
        soft=[0,-781,-2176]*4
        droop=[0,465,93,0,465,93,0,-1504,962,0,-1504,962]
        lift_f=[0,-1800,-2400]
        if pname=='soften_stance':
            return [soft]
        if pname=='droop_front':
            g1=list(soft);g1[6:9]=lift_f
            g2=list(soft);g2[6:9]=droop[6:9]
            g3=list(g2);g3[9:12]=lift_f
            return [g1,g2,g3,droop]
        if pname=='left_front_slump':
            return [[0,108,-301,0,378,436,0,-1723,362,0,-1756,1335]]
        if pname in ('center_after_left_slump','center_after_right_slump'):
            return [droop]
        if pname=='right_front_slump':
            return [[0,380,436,0,110,-301,0,-1753,1337,0,-1721,363]]
        if pname=='lift_sad_droop':
            g1=list(droop);g1[6:9]=lift_f
            g2=list(droop);g2[6:9]=soft[6:9]
            g3=list(g2);g3[9:12]=lift_f
            return [g1,g2,g3,soft]
    if name=='dance':
        neutral=[0,-1005,-2263]*4
        if pname=='settle_into_dance' or pname.startswith('rebound_'):
            return [neutral]
        if pname=='rock_left':
            return [[0,-600,-1600,-800,-2150,-3500,0,-600,-1600,-800,-2150,-3500]]
        if pname=='rock_right':
            return [[-800,-2150,-3500,0,-600,-1600,-800,-2150,-3500,0,-600,-1600]]
    if name=='nod':
        up=[0,-1850,-2200,0,-1850,-2200,0,2200,-3400,0,2200,-3400]
        down=[0,400,-800,0,400,-800,0,-2150,-2600,0,-2150,-2600]
        if pname=='crouch_rear_right' or pname.endswith('_up'):
            return [up]
        if pname.endswith('_down'):
            return [down]
        if pname=='return_to_standing':
            return [list(stand_row)]
    if name=='shake':
        prep=[0,-285,-730,0,-285,-730,0,-2150,-2500,0,-2150,-2500]
        peak=[0,1861,326,0,1861,326,0,-1600,-1623,0,-1600,-1623]
        if pname=='prepare_shake' or pname.endswith('_return'):
            return [prep]
        if pname.startswith('rear_pair_shake_'):
            return [peak]
    if name=='freaky':
        brace=[0,-2150,-2500,0,-1600,-2015,0,-2150,-2500,0,-1600,-2015]
        if pname=='lower_into_asymmetric_ground_pose':
            return [brace]
        if pname in ('raise_right_front_shoulder','fold_right_front_linkage'):
            g=list(brace);g[9:12]=[-6128,-2150,-2196]
            return [g]
        if pname=='replace_right_front_sole':
            return [brace]
        if pname=='return_to_standing':
            return [list(stand_row)]
        g=list(brace);g[9:12]=clamp_goal(rows[end],name)[9:12]
        return [g]
    landmarks=[end]
    if pname!='three_playful_waves':
        for leg in range(4):
            clearances=[row['sole_clearance_mm'][leg] for row in clip_source[begin:end+1]]
            peak=max(range(len(clearances)),key=clearances.__getitem__)
            if clearances[peak]>max(clearances[0],clearances[-1])+.01:
                landmarks.append(begin+peak)
        landmarks=sorted(set(landmarks))
    return [clamp_goal(rows[lm],name) for lm in landmarks]


@lru_cache(maxsize=None)
def source_motion(name):
    """Compact authored stages; source paths are provenance, not curve targets."""
    from .kinematics import ROOT
    from .runtime import JOINTS
    compiler,clips=legacy_sources();clip=clips[name];rows=clip['positions']
    clip_source=json.loads((ROOT/'motions/gestures'/name/'source.json').read_text())['samples']
    number=lambda value:round(value/100,2)
    initial_row=list(rows[0]) if name=='crouch' else [0,94,-2125]*4
    entry=[number(v) for v in initial_row]
    if name=='stretch':
        # Owner's requested crouch, front-limb extension, holds and standing finish.
        # The old Blender/source curve lacks the accepted extension.
        program=stretch_program(entry)
        final=entry
    else:
        program=[call('face',expr=name),call('pose',joints=list(JOINTS),
            angles_deg=entry,reference='absolute',speed_pct=50,taper_deg=0)]
        previous=list(initial_row)
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
                continue
            for goal in stage_goals(name,phase,rows,clip_source,previous):
                ids=[i for i,(a,b) in enumerate(zip(previous,goal)) if round(a)!=round(b)]
                if ids:
                    travel=max(abs(goal[i]-previous[i]) for i in ids)/100
                    program.append(call('pose',joints=[JOINTS[i] for i in ids],
                        angles_deg=[number(goal[i]) for i in ids],reference='absolute',speed_pct=50,
                        taper_deg=round(min(10,.2*travel),2) if name in ('sit','rest','crouch') else 0))
                previous=list(goal)
        final=[number(v) for v in previous]
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
    body=lambda dx,dz:call('body',translation_mm=[dx,0,dz],rotation_deg=[0,0,0],
                           legs=[],foot_offsets_mm=[],speed_pct=100,taper_deg=0)
    step=lambda leg,dx,h=18:[
        call('feet',legs=[leg],offsets_mm=[[0,0,h]],speed_pct=100,taper_deg=0),
        call('feet',legs=[leg],offsets_mm=[[dx,0,-h]],speed_pct=100,taper_deg=0)]
    return [call('face',expr='stretch'),
            call('pose',joints=list(JOINTS),angles_deg=entry,reference='absolute',speed_pct=100,taper_deg=0),
            *step('front_left',30),*step('front_right',30),
            body(0,-16),call('hold',seconds=.9),body(-5,0),call('hold',seconds=.7),
            body(5,16),*step('front_left',-30),*step('front_right',-30),
            call('pose',joints=list(JOINTS),angles_deg=entry,reference='absolute',speed_pct=100,taper_deg=0),
            call('hold',seconds=.5),call('face',expr='stand')]


def call(name, **arguments):
    return {'name':name, 'arguments':arguments}


def feet(legs, offsets, seconds=.6):
    return call('feet', legs=legs, offsets_mm=offsets, speed_pct=100, taper_deg=0)


def body(translation=(0,0,0), rotation=(0,0,0), seconds=.8):
    return call('body', translation_mm=list(translation), rotation_deg=list(rotation),
                legs=[], foot_offsets_mm=[], speed_pct=100, taper_deg=0)


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
