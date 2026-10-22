"""Compact motion-program training contract. Offline; no robot transport."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from runtime import JOINTS, compact

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / 'Slave/software/models/v2-12servo'
GESTURES = sorted({p.parent.name for p in (MODEL_ROOT/'motions/gestures').glob('*/source.json')} | {'stand'})


def tool(name, description, properties):
    return {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': properties, 'required': list(properties),
        'additionalProperties': False}}


JOINT = {'type': 'string', 'enum': list(JOINTS),
         'description': 'RF/FR=front_right, LF/FL=front_left, RR=rear_right, RL=rear_left.'}
NUMBER = {'type': 'number'}
REFERENCE = {'type': 'string', 'enum': ['home', 'current', 'absolute']}
TOOLS = [
    tool('move', 'Move one joint. angle_deg is relative to the selected reference; home means calibrated home.',
         {'joint': JOINT, 'angle_deg': NUMBER, 'reference': REFERENCE, 'speed_pct': NUMBER}),
    tool('hold', 'Hold the preceding movement targets for seconds.', {'seconds': NUMBER}),
    tool('gesture', 'Perform the complete existing named gesture, preserving its sequence.',
         {'name': {'type': 'string', 'enum': GESTURES}}),
    tool('oscillate', 'Oscillate a joint around its starting position; amplitude is degrees each side, period is seconds per full cycle.',
         {'joint': JOINT, 'amplitude_deg': NUMBER, 'cycles': {'type': 'integer'}, 'period_s': NUMBER}),
    tool('pose', 'Move the listed joints together; each angle corresponds to the joint at the same index.',
         {'joints': {'type': 'array', 'items': JOINT}, 'angles_deg': {'type': 'array', 'items': NUMBER},
          'reference': REFERENCE, 'speed_pct': NUMBER}),
]
SYSTEM = ('Translate the requested robot motion into a JSON array of function calls. '
          'Each call has name and arguments. Calls are ordered; pose explicitly coordinates joints. '
          'FR/RF means front_right, FL/LF front_left, RR rear_right, RL rear_left. '
          'Use only the requested actions and values. Return calls only, without reasoning or prose. '
          'Tools: '+compact(TOOLS))


def call(operation, **arguments):
    return {'name': operation, 'arguments': arguments}


def move(joint, angle, reference, speed):
    return call('move', joint=joint, angle_deg=angle, reference=reference, speed_pct=speed)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def records(split):
    rng = random.Random({'train': 41, 'evaluation': 42, 'test': 43}[split])
    angles = {'train': [-30, -20, -10, 10, 20, 30, 40],
              'evaluation': [-18, 18], 'test': [-25, -15, 15, 25, 35]}[split]
    rows = []

    def add(family, query, answers):
        identity = hashlib.sha256(compact([query, answers]).encode()).hexdigest()
        rows.append({'id': identity[:16], 'family': family, 'query': query, 'answers': answers,
                     'source_id': 'synthetic:'+identity, 'source_hash': identity})

    aliases = {'front_right': 'RF', 'front_left': 'LF', 'rear_right': 'RR', 'rear_left': 'RL'}
    for joint in JOINTS:
        leg, axis = joint.rsplit('_', 1)
        label = joint.replace('_', ' ') if split == 'train' else aliases[leg]+' '+axis
        for angle in angles:
            speed = rng.choice([25, 50, 75, 100])
            for reference in ('home', 'current', 'absolute'):
                phrase = {'home': f'{angle} degrees from home', 'current': f'{angle} degrees from its current position',
                          'absolute': f'an absolute angle of {angle} degrees'}[reference]
                query = (f'Move the {label} to {phrase} at {speed}% speed.' if split == 'train'
                         else f'Please set {label} to {phrase}, using {speed} percent speed.')
                add('move', query, [move(joint, angle, reference, speed)])
            for seconds in ([1, 2, 3] if split == 'train' else [1.5, 2.5]):
                query = (f'Move {label} {angle} degrees from home at {speed}% speed, hold for {seconds} seconds, then return it home at {speed}% speed.'
                         if split == 'train' else
                         f'At {speed} percent speed put {label} {angle} degrees away from home. Stay there {seconds} seconds and bring it home at the same speed.')
                add('move_hold_return', query, [move(joint, angle, 'home', speed), call('hold', seconds=seconds), move(joint, 0, 'home', speed)])
            if angle > 0:
                for cycles in (2, 3, 5):
                    period = rng.choice([0.5, 1, 1.5, 2])
                    query = (f'Oscillate {label} {cycles} times with amplitude {angle} degrees and a {period} second period.'
                             if split == 'train' else
                             f'Swing {label} back and forth for {cycles} full cycles, {angle} degrees either side of its starting position, {period} seconds per cycle.')
                    add('oscillate', query, [call('oscillate', joint=joint, amplitude_deg=angle, cycles=cycles, period_s=period)])
    for i in range({'train': 160, 'evaluation': 24, 'test': 48}[split]):
        joints = rng.sample(list(JOINTS), 2)
        values = rng.sample(angles, 2)
        speed = rng.choice([25, 50, 75, 100])
        labels = [j.replace('_', ' ') for j in joints]
        query = (f'Together move {labels[0]} to {values[0]} degrees and {labels[1]} to {values[1]} degrees, both relative to home at {speed}% speed.'
                 if split == 'train' else
                 f'At {speed} percent speed, coordinate {labels[0]} at home plus {values[0]} degrees with {labels[1]} at home plus {values[1]} degrees.')
        add('pose', query, [call('pose', joints=joints, angles_deg=values, reference='home', speed_pct=speed)])
    for name in GESTURES:
        label = name.replace('_', ' ')
        phrases = {'train': [f'Perform {label}.', f'Please do the complete {label} gesture.', f'Show me {label}.'],
                   'evaluation': [f'Could you demonstrate {label}?'], 'test': [f'I would like to see you {label}.']}[split]
        if name == 'lay_down':
            phrases += {'train': ['Go to sleep.', 'Lie down to rest.'],
                        'evaluation': ['Time for bed; lie down.'], 'test': ['Settle down for a nap.']}[split]
        for phrase in phrases:
            add('gesture', phrase, [call('gesture', name=name)])
            seconds = rng.choice([1, 2, 3])
            add('gesture_sequence', phrase+f' Then hold for {seconds} seconds and stand.',
                [call('gesture', name=name), call('hold', seconds=seconds), call('gesture', name='stand')])
    # Stand is a body posture command even when the authored gesture folder omits it.
    rng.shuffle(rows)
    return rows


def export(destination):
    all_rows = {split: records(split) for split in ('train', 'evaluation', 'test')}
    destination.mkdir(parents=True, exist_ok=False)
    for split, rows in all_rows.items():
        (destination/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in rows))
    selected = []
    for family in sorted({r['family'] for r in all_rows['test']}):
        selected.extend([r for r in all_rows['test'] if r['family'] == family][:10])
    (destination/'benchmark.jsonl').write_text(''.join(compact(r)+'\n' for r in selected))
    (destination/'tools.json').write_text(compact(TOOLS)+'\n')
    report = {'source': 'synthetic instruction-to-program examples; not physical demonstrations',
              'generator_sha256': sha(__file__), 'splits': {k: len(v) for k,v in all_rows.items()},
              'benchmark_count': len(selected), 'benchmark_policy': 'first ten shuffled cases per family, fixed before training',
              'reasoning_targets': False, 'robot_dispatch': False,
              'files': {p.name: sha(p) for p in destination.iterdir() if p.is_file()}}
    (destination/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(compact(export(parser.parse_args().output)))
