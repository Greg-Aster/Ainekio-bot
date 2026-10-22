"""Offline corrections for external trials; never imported by the motion service.

Targets are authored paths, not human joint retargeting or measured robot skills.
Replay and semantic review remain separate before any example enters training.
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .challenge import digest, read_rows, replay, trajectory_metrics, write_rows
from .kinematics import foot_positions
from .runtime import compact
from .semantic_teachers import body, call, feet


def corrected_program(family, observation, side='right'):
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
        # P4 gait execution is outside this FK replay. Subsequent generated
        # spatial deltas still use measured positions when the bridge runs them.
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
}


def review_candidate(item):
    trace = replay(item['corrected_program'], item['observation'])
    return {**item, 'trace':trace, 'metrics':trajectory_metrics(trace)}


def author(trials, output, workers):
    output.mkdir(parents=True, exist_ok=False)
    candidates = []
    for trial in read_rows(trials):
        if trial['id'] not in CORRECTIONS:
            continue
        family, side = CORRECTIONS[trial['id']]
        candidates.append({'id':trial['id'], 'family':family, 'side':side,
                           'request':trial['request'], 'observation':trial['observation'],
                           'required_semantic_features':trial['required_semantic_features'],
                           'corrected_program':corrected_program(family, trial['observation'], side)})
    reviews = []
    with ProcessPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(review_candidate, item) for item in candidates]):
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
        'candidates':len(candidates), 'training_exported':False, 'physical_trials':0,
        'scope':'Authored candidate corrections; FK replay alone is not semantic approval or physical qualification.'
    }, indent=2)+'\n')


def curriculum(state_file, output, workers):
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
        for future in as_completed([pool.submit(review_candidate,item) for item in candidates]):
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
        'candidates':len(candidates), 'training_exported':False, 'physical_trials':0
    },indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--trials', type=Path)
    inputs.add_argument('--curriculum-state', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.curriculum_state:
        curriculum(args.curriculum_state, args.output, args.workers)
    else:
        author(args.trials, args.output, args.workers)
