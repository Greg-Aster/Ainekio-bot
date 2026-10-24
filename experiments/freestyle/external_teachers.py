"""Offline corrections for external trials; never imported by the motion service.

Targets are authored paths, not human joint retargeting or measured robot skills.
Replay and semantic review remain separate before any example enters training.
"""
import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .challenge import digest, read_rows, replay, trajectory_metrics, write_rows
from .kinematics import ROOT, foot_positions
from .runtime import JOINTS, compact
from .semantic_teachers import body, call, feet


def corrected_program(family, observation, side='right', native_gait=None):
    if family in ('pickup_transfer','walk_pickup','backstep_food','sit_phone',
                  'overhead_gestures','head_outward_wave','backward_then_turn'):
        return composed_correction(family,observation,side,native_gait)
    positions = {joint: value['model_deg'] for joint, value in observation['joints'].items()}
    initial = foot_positions(positions)
    current = {leg: list(point) for leg, point in initial.items()}
    program = []
    hand = 'front_' + side
    hands = ['front_left', 'front_right']
    sign = 1 if side == 'left' else -1

    def point(leg, dx=0, dy=0, dz=0):
        return [initial[leg][0]+dx, initial[leg][1]+dy, initial[leg][2]+dz]

    def target(points, seconds=.7):
        legs = list(points)
        program.append(feet(legs, [[round(b-a, 3) for a,b in zip(current[leg], points[leg])]
                                   for leg in legs], seconds))
        current.update({leg:list(value) for leg,value in points.items()})

    def restore(legs):
        target({leg:initial[leg] for leg in legs})

    if family == 'dip_then_wipe':
        target({hand:point(hand, 20, 0, 35)})
        target({hand:point(hand, 20, 0, 15)}, .4)
        program.append(call('hold', seconds=.3))
        target({hand:point(hand, 20, 0, 35)}, .4)
        for dy in (20, -20, 0):
            target({hand:point(hand, 20, dy, 35)}, .6)
        restore([hand])
    elif family in ('both_hands_head_level', 'hand_head_level'):
        selected = hands if family.startswith('both') else [hand]
        # Alongside the head, above the 80.96 mm shoulder reference. These are
        # reachable side-of-head mimes, not claims of contact with an exact ear.
        target({leg:[95, 90 if leg.endswith('left') else -90, 105] for leg in selected}, 1.2)
        program.append(call('hold', seconds=.8))
        restore(selected)
    elif family == 'raise_extend_then_both':
        target({hand:point(hand, 0, sign*15, 45)})
        target({hand:point(hand, 20, sign*15, 45)})
        target({leg:[95, 100 if leg.endswith('left') else -100, 90] for leg in hands}, 1.1)
        program.append(call('hold', seconds=.7))
        restore(hands)
    elif family == 'drink_at_head':
        target({hand:[95, sign*90, 90]}, 1.0)
        target({hand:[95, sign*90, 105]}, .7)
        program.append(call('hold', seconds=.8))
        target({hand:[95, sign*90, 115]}, .5)
        target({hand:[95, sign*90, 105]}, .5)
        restore([hand])
    elif family == 'chest_level_wave':
        target({hand:[95, sign*90, 90]}, 1.0)
        target({hand:[95, sign*115, 90]}, .5)
        target({hand:[95, sign*70, 90]}, .7)
        target({hand:[95, sign*90, 90]}, .4)
        restore([hand])
    elif family == 'forward_kick':
        target({hand:point(hand, 0, 0, 25)}, .4)
        target({hand:point(hand, 35, 0, 25)}, .3)
        target({hand:point(hand, 0, 0, 25)}, .4)
        restore([hand])
    elif family == 'one_hand_weight_lift':
        # A one-handed exercise mime; the other front limb stays in place.
        target({hand:point(hand, 15, sign*10, 20)}, .6)
        for _ in range(2):
            target({hand:point(hand, 15, sign*10, 55)}, .6)
            program.append(call('hold', seconds=.4))
            target({hand:point(hand, 15, sign*10, 20)}, .6)
        restore([hand])
    elif family == 'shoulder_flinch':
        target({leg:point(leg, 0, 0, 12) for leg in hands}, .12)
        target({leg:point(leg) for leg in hands}, .35)
    elif family == 'squat_t_pose':
        program.append(body((0,0,-20), seconds=.8))
        for value in current.values():
            value[2] += 20
        squat_feet = {leg:current[leg][:] for leg in hands}
        target({'front_left':[95,120,85], 'front_right':[95,-120,85]}, .7)
        program.append(call('hold', seconds=.4))
        target(squat_feet, .8)
    elif family == 'squat_lower_raise_arm':
        program.append(body((0,0,-15), seconds=.8))
        for value in current.values():
            value[2] += 15
        raised = [current[hand][0]+15, current[hand][1]+sign*20, current[hand][2]+35]
        target({hand:raised}, .6)
        target({hand:[raised[0],raised[1],raised[2]-20]}, .5)
        target({hand:raised}, .5)
    elif family == 'collect_into_bin':
        # Three distinct low pickup locations and one common elevated bin.
        target({hand:point(hand, 10, sign*15, 35)}, .6)
        for x,y in ((10,10),(25,20),(5,30)):
            target({hand:point(hand, x, sign*y, 10)}, .5)
            program.append(call('hold', seconds=.25))
            target({hand:point(hand, x, sign*y, 35)}, .5)
            target({hand:point(hand, 20, sign*45, 40)}, .6)
            program.append(call('hold', seconds=.25))
        restore([hand])
    elif family == 'folded_hands':
        target({'front_left':[95,100,90], 'front_right':[95,-100,90]}, 1.0)
        target({'front_left':[110,30,90], 'front_right':[110,-30,90]}, .8)
        program.append(call('hold', seconds=1.2))
        target({'front_left':[95,100,90], 'front_right':[95,-100,90]}, .8)
        restore(hands)
    elif family == 'microphone_and_gesture':
        # Keep the microphone hand raised throughout the other arm's gesture.
        target({'front_left':[95,90,105]}, 1.0)
        target({'front_right':[100,-110,65]}, .7)
        target({'front_right':[115,-130,75]}, .5)
        program.append(call('hold', seconds=.6))
        target({'front_right':[100,-110,65]}, .5)
        restore(['front_right'])
        restore(['front_left'])
    elif family == 'teapot_mime':
        # Asymmetric bent-handle/extended-spout mime, followed by a pouring tilt.
        target({'front_left':[95,100,90], 'front_right':[100,-110,65]}, 1.0)
        target({'front_right':[115,-130,75]}, .7)
        program.append(call('hold', seconds=.5))
        pivot = json.loads((ROOT/'geometry.json').read_text())['continuous_walk']['body_rotation_pivot_mm']
        for angle in (6, -6):
            # The raised handle/spout move with the tilting torso. Keeping
            # these hands fixed in space would extend the spout arm instead.
            cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            offsets = []
            for leg in hands:
                y, z = current[leg][1]-pivot[1], current[leg][2]-pivot[2]
                offsets.append([0, round((cosine-1)*y-sine*z, 6),
                                   round(sine*y+(cosine-1)*z, 6)])
            program.append(call('body', translation_mm=[0,0,0], rotation_deg=[angle,0,0],
                                legs=hands, foot_offsets_mm=offsets, seconds=.7))
            if angle > 0:
                program.append(call('hold', seconds=.8))
        restore(hands)
    elif family == 'cross_arms_at_chest':
        target({'front_left':[95,100,90], 'front_right':[95,-100,90]}, 1.0)
        # Stagger the paths in X/Z rather than asking both reference points to
        # occupy the same point. Whole-limb collision is still unmeasured.
        target({'front_left':[120,-15,90], 'front_right':[100,15,110]}, 1.2)
        program.append(call('hold', seconds=.7))
        target({'front_left':[95,100,90], 'front_right':[95,-100,90]}, 1.0)
        restore(hands)
    elif family == 'shirt_removal_mime':
        target({'front_left':[95,100,90], 'front_right':[95,-100,90]}, 1.0)
        program.extend([body(rotation=(0,5,0), seconds=.6),
                        body(rotation=(0,-5,0), seconds=.6)])
        target({'front_left':[95,90,105], 'front_right':[95,-90,105]}, .8)
        target({'front_left':[95,90,125], 'front_right':[95,-90,125]}, .8)
        target({'front_left':[95,110,105], 'front_right':[95,-110,105]}, .7)
        restore(hands)
    elif family == 'arm_and_squat_exercise':
        for _ in range(2):
            target({leg:point(leg, 0, 15 if leg.endswith('left') else -15, 35)
                    for leg in hands}, .7)
            restore(hands)
            program.extend([body((0,0,-25), seconds=1.0),
                            call('hold', seconds=.3),
                            body((0,0,25), seconds=1.0)])
    elif family == 'seated_cringe':
        # Preserve the existing authored sitting endpoint rather than invent
        # a low hand gesture as a substitute for sitting. This is offline data.
        source = json.loads((ROOT/'motions/gestures/sit/source.json').read_text())
        angles = [round(math.degrees(q), 2)
                  for leg in source['samples'][-1]['actuator_angles_rad'] for q in leg]
        program.extend([call('pose', joints=list(JOINTS), angles_deg=angles,
                             reference='absolute', speed_pct=50),
                        call('hold', seconds=.3),
                        body(rotation=(0,5,0), seconds=.25),
                        call('hold', seconds=.3),
                        body(rotation=(0,-5,0), seconds=.5),
                        call('hold', seconds=.6)])
    elif family == 'forehand':
        target({hand:point(hand, -10, sign*20, 40)})
        program.append(call('hold', seconds=.3))
        target({hand:point(hand, 25, -sign*15, 40)}, .5)
        target({hand:point(hand, 35, -sign*20, 30)}, .5)
        restore([hand])
    elif family == 'left_step':
        # One whole-body leftward step adapted to four sequential foot resets.
        target({'front_left':point('front_left', 0, 0, 20)}, .4)
        target({'front_left':point('front_left', 0, 20, 20)}, .5)
        target({'front_left':point('front_left', 0, 20, 0)}, .4)
        program.append(body((0, 20, 0), seconds=1.0))
        # Body moved left with planted feet: every body-relative foot Y is -20.
        for value in current.values():
            value[1] -= 20
        for leg in ('rear_left', 'rear_right', 'front_right'):
            start = current[leg][:]
            target({leg:[start[0], start[1], start[2]+20]}, .4)
            target({leg:[start[0], start[1]+20, start[2]+20]}, .5)
            target({leg:[start[0], start[1]+20, start[2]]}, .4)
    elif family == 'walk_then_head_reach':
        # Whole-sequence review needs the optional native gait sampler: later
        # deltas start from its final target, not the pre-walk starting pose.
        program.append(call('gait', command='walk', speed_pct=50, cycles=1))
        program.extend(corrected_program('hand_head_level', observation, side))
    elif family == 'walk_then_stumble_twice':
        program.append(call('gait', command='walk', speed_pct=50, cycles=1))
        for _ in range(2):
            program.extend([body(rotation=(4,0,0), seconds=.4),
                            feet(['front_right'], [[0,-15,20]], .4),
                            call('hold', seconds=.2),
                            feet(['front_right'], [[0,15,-20]], .5),
                            body(rotation=(-4,0,0), seconds=.5)])
    else:
        raise ValueError(f'No reviewed authoring definition for {family}')
    return program


def composed_correction(family, observation, side, native_gait):
    """Author failed multi-phase requests from the actual simulated prefix pose."""
    from .semantic_teachers import source_posture
    prefix=[]
    if family=='sit_phone':prefix=source_posture('sit')
    elif family in ('walk_pickup','backstep_food','backward_then_turn'):
        prefix=[call('gait',command='backward' if family in ('backstep_food','backward_then_turn') else 'walk',
                     speed_pct=50,cycles=1)]
    if family=='backward_then_turn':
        return prefix+[call('gait',command='right',speed_pct=50,cycles=1)]
    state=observation
    if prefix:
        trace=replay(prefix,observation,native_gait)
        if trace['status']!='replayed':raise ValueError('Teaching prefix did not complete: '+str(trace.get('error') or trace.get('reason')))
        state={**observation,'joints':{j:{**observation['joints'][j],'model_deg':q}
               for j,q in trace['samples'][-1]['joints_deg'].items()}}
    initial=foot_positions({j:v['model_deg'] for j,v in state['joints'].items()})
    current={leg:list(point) for leg,point in initial.items()}
    hand='front_'+side;sign=1 if side=='left' else -1
    program=list(prefix)
    def target(points,seconds=.7):
        legs=list(points)
        program.append(feet(legs,[[round(b-a,3) for a,b in zip(current[leg],points[leg])] for leg in legs],seconds))
        current.update({leg:list(point) for leg,point in points.items()})
    def hold(seconds=.5):program.append(call('hold',seconds=seconds))
    if family in ('pickup_transfer','walk_pickup'):
        x,y,z=initial[hand]
        target({hand:[x+20,y,z+25]})
        target({hand:[x+20,y,z+5]},.5)
        hold(.3)
        target({hand:[x+20,y,z+45]})
        if family=='pickup_transfer':target({hand:[x+20,y-30,z+45]})
        hold()
        target({hand:initial[hand]})
    elif family=='backstep_food':
        target({hand:[105,sign*100,60]})
        target({hand:[105,sign*100,40]},.5)
        hold(.3)
        target({hand:[105,sign*100,60]})
        target({hand:[95,sign*90,105]})
        hold(.8)
        target({hand:[105,sign*100,60]})
        target({hand:[105,sign*100,40]},.5)
        hold(.3)
        target({hand:initial[hand]})
    elif family=='sit_phone':
        target({hand:[85,sign*100,35]})
        hold(.3)
        target({hand:[95,sign*90,105]},1.0)
        hold(1.0)
    elif family=='overhead_gestures':
        hands=['front_left','front_right']
        target({leg:[95,100 if leg.endswith('left') else -100,125] for leg in hands},1.2)
        for _ in range(2):
            target({leg:[95,115 if leg.endswith('left') else -115,125] for leg in hands},.5)
            target({leg:[95,100 if leg.endswith('left') else -100,125] for leg in hands},.5)
        target({leg:initial[leg] for leg in hands},1.0)
    elif family=='head_outward_wave':
        target({hand:[95,sign*90,105]},1.2)
        for _ in range(3):
            target({hand:[95,sign*120,105]},.4)
            target({hand:[95,sign*90,105]},.5)
        target({hand:initial[hand]},.8)
    return program


# This maps failed trial IDs to authored corrections only. It is never a
# deployed intent dispatcher. Other failures remain pending, not silently fixed.
CORRECTIONS = {
    'humanml3d:010757:2': ('dip_then_wipe', 'left'),
    'humanml3d:003559:1': ('walk_then_stumble_twice', 'right'),
    'humanml3d:012767:0': ('walk_then_head_reach', 'right'),
    'humanml3d:005858:0': ('left_step', 'left'),
    'humanml3d:006200:1': ('forehand', 'right'),
    'humanml3d:006329:2': ('both_hands_head_level', 'right'),
    'humanml3d:010973:1': ('raise_extend_then_both', 'right'),
    'humanml3d:002135:2': ('drink_at_head', 'right'),
    'humanml3d:007995:2': ('chest_level_wave', 'left'),
    'humanml3d:002968:1': ('cross_arms_at_chest', 'right'),
    'humanml3d:013917:2': ('shirt_removal_mime', 'right'),
    'humanml3d:011120:0': ('arm_and_squat_exercise', 'right'),
    'humanml3d:006401:2': ('seated_cringe', 'right'),
    'humanml3d:005789:0': ('forward_kick', 'right'),
    'humanml3d:002655:2': ('folded_hands', 'right'),
    'humanml3d:003801:2': ('microphone_and_gesture', 'right'),
    'humanml3d:006170:0': ('teapot_mime', 'right'),
    'humanml3d:003337:0': ('one_hand_weight_lift', 'right'),
    'humanml3d:012020:1': ('shoulder_flinch', 'right'),
    'humanml3d:007510:2': ('squat_t_pose', 'right'),
    'humanml3d:001998:2': ('squat_lower_raise_arm', 'left'),
    'humanml3d:003697:2': ('collect_into_bin', 'right'),
    'humanml3d:002475:1': ('pickup_transfer','right'),
    'humanml3d:010151:1': ('walk_pickup','right'),
    'humanml3d:003095:1': ('backstep_food','right'),
    'humanml3d:011579:0': ('sit_phone','right'),
    'humanml3d:004317:2': ('overhead_gestures','right'),
    'humanml3d:008813:2': ('head_outward_wave','right'),
    'humanml3d:004197:0': ('backward_then_turn','right'),
}


def review_candidate(item, native_gait=None):
    trace = replay(item['corrected_program'], item['observation'], native_gait)
    return {**item, 'trace':trace, 'metrics':trajectory_metrics(trace)}


def author(trials, output, workers, native_gait=None):
    output.mkdir(parents=True, exist_ok=False)
    candidates = []
    for trial in read_rows(trials):
        if trial['id'] not in CORRECTIONS:
            continue
        family, side = CORRECTIONS[trial['id']]
        candidates.append({'id':trial['id'], 'family':family, 'side':side,
                           'request':trial['request'], 'observation':trial['observation'],
                           'required_semantic_features':trial['required_semantic_features'],
                           'corrected_program':corrected_program(family, trial['observation'], side, native_gait)})
    reviews = []
    with ProcessPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(review_candidate, item, native_gait) for item in candidates]):
            item = future.result()
            name = item['id'].replace(':','_') + '.correction.json'
            (output/name).write_text(compact(item)+'\n')
            review = {'id':item['id'], 'motion_family':item['family'],
                      'corrected_program':item['corrected_program'], 'evidence':name,
                      'replay_status':item['trace']['status'],
                      'review_status':'awaiting independent semantic review',
                      'physical_qualification':False}
            reviews.append(review)
            print(compact({k:review[k] for k in ('id','replay_status')}), flush=True)
    write_rows(output/'reviews.jsonl', reviews)
    (output/'manifest.json').write_text(json.dumps({
        'trials_sha256':digest(trials), 'author_sha256':digest(Path(__file__)),
        'native_gait_binary_sha256':digest(native_gait) if native_gait else None,
        'candidates':len(candidates), 'training_exported':False, 'physical_trials':0,
        'scope':'Authored candidate corrections; FK replay alone is not semantic approval or physical qualification.'
    }, indent=2)+'\n')


def curriculum(state_file, output, workers, native_gait=None):
    """Replay distinct mirrored paths and ordered compositions for new teaching."""
    output.mkdir(parents=True, exist_ok=False)
    state = json.loads(state_file.read_text())
    motions = [
        ('dip_then_wipe', 'left', 'Dip your left hand into imaginary cleaner, then wipe a surface with it'),
        ('dip_then_wipe', 'right', 'Dip your right hand into imaginary cleaner, then wipe a surface with it'),
        ('forehand', 'left', 'Make a left-handed tennis forehand with a wind-back, sweep and follow-through'),
        ('forehand', 'right', 'Make a right-handed tennis forehand with a wind-back, sweep and follow-through'),
        ('both_hands_head_level', 'right', 'Lift both hands beside your head, hold them there, then lower them'),
        ('hand_head_level', 'left', 'Raise your left hand beside your head, pause and put it down'),
        ('hand_head_level', 'right', 'Raise your right hand beside your head, pause and put it down'),
        ('raise_extend_then_both', 'left', 'Lift your left hand, extend it forward, then bring both hands up to chest height and lower them'),
        ('raise_extend_then_both', 'right', 'Lift your right hand, extend it forward, then bring both hands up to chest height and lower them'),
        ('left_step', 'left', 'Take one step to your left'),
    ]
    candidates = []
    for i, (family, side, text) in enumerate(motions):
        candidates.append({'id':f'grounded-path-{i}', 'family':'grounded_'+family,
                           'request':text+'.', 'observation':state,
                           'corrected_program':corrected_program(family, state, side)})
    # Different order, side and unilateral/bilateral transitions, not merely
    # new names for a fixed emote. Every composed target is replayed as a whole.
    for i, indexes in enumerate(((9,3),(9,4),(0,4),(1,5),(2,6),(3,5),
                                  (5,6),(6,5),(7,0),(8,1),(4,2),(4,3))):
        selected = [motions[index] for index in indexes]
        candidates.append({'id':f'grounded-composition-{i}', 'family':'grounded_composition',
                           'request':'. Then '.join(text for _,_,text in selected)+'.',
                           'observation':state,
                           'corrected_program':[action for family,side,_ in selected
                                                for action in corrected_program(family,state,side)]})
    reviews = []
    with ProcessPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(review_candidate,item,native_gait) for item in candidates]):
            item = future.result()
            filename = item['id']+'.json'
            (output/filename).write_text(compact(item)+'\n')
            review = {'id':item['id'], 'family':item['family'], 'evidence':filename,
                      'replay_status':item['trace']['status'],
                      'review_status':'awaiting independent semantic review'}
            reviews.append(review)
            print(compact(review),flush=True)
    write_rows(output/'reviews.jsonl',reviews)
    (output/'manifest.json').write_text(json.dumps({
        'author_sha256':digest(Path(__file__)), 'state_sha256':digest(state_file),
        'native_gait_binary_sha256':digest(native_gait) if native_gait else None,
        'candidates':len(candidates), 'training_exported':False, 'physical_trials':0
    },indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--trials', type=Path)
    inputs.add_argument('--curriculum-state', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--native-gait', type=Path, help='Offline native gait executable for authored walking compositions')
    args = parser.parse_args()
    if args.curriculum_state:
        curriculum(args.curriculum_state, args.output, args.workers, args.native_gait)
    else:
        author(args.trials, args.output, args.workers, args.native_gait)
