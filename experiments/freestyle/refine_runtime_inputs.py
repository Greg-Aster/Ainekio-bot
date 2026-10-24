"""Teach existing reviewed targets in constructed host-shaped event envelopes.

This is offline data preparation, not event handling or a recovery policy.
Only parent training rows are transformed; held-out requests remain untouched.
"""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from .challenge import digest, read_rows, write_rows
from .runtime import JOINTS, compact


def variants(original):
    value = json.loads(original['query'])
    if not value.get('event'):
        return []
    family = original['family']
    if family not in ('natural_jam_smaller_wave', 'natural_jam_backoff',
                      'natural_fall_correction', 'natural_slip_correction'):
        return []
    result = []
    forms = ['rich_event', 'interrupted_job']
    if family == 'natural_jam_smaller_wave':
        forms.append('contextual_resume')
    for variant in forms:
        query = copy.deepcopy(value)
        obs = query['observation']
        event = query['event']
        names = [j['name'] if isinstance(j, dict) else j for j in event.get('joints', [])]
        kind = event['type']
        if kind == 'fallen':
            kind = 'tipped'
        event.update(type=kind, kind=kind, event_id='synthetic-training-'+original['id']+'-'+variant,
                     epoch=obs['epoch'], command_sequence=33, clock_us=3000000,
                     outputs_released=False)
        if names:
            event['joints'] = [{'id':JOINTS.index(j), 'name':j} for j in names]
            event['joint_mask'] = sum(1 << JOINTS.index(j) for j in names)
            event['reason'] = 'no_position_progress'
            obs['feedback'].update(stalled_joints=event['joint_mask'], no_progress_ms=1000)
        answers = copy.deepcopy(original['answers'])
        if variant == 'contextual_resume':
            # The task is identified by observation.action and the measured
            # history. Teach that inference without spelling out its solution
            # in the request or importing a held-out request into training.
            query['request'] = 'Carry on with the movement I asked for.'
        if variant == 'interrupted_job':
            # Bridge.observation has body_command, not the synthetic remaining-
            # cycles descriptor. Relevant program intent lives in job history.
            action = copy.deepcopy(obs.get('action'))
            if family == 'natural_jam_smaller_wave':
                joint = answers[0]['arguments']['joint']
                start = query['history'][0]['joints'][joint]
                interrupted = {'name':'oscillate', 'arguments':{
                    'joint':joint, 'amplitude_deg':abs(obs['joints'][joint]['commanded_model_deg'] -
                                                     start),
                    'cycles':action['remaining_cycles'], 'period_s':action['period_s']}}
                # Construct an interruption in the first cycle: no cycles have
                # finished, so the supplied original cycle count is still due.
                query['request'] = ('Finish the interrupted '+str(action['remaining_cycles'])+
                                    '-cycle wave using a smaller excursion that avoids the obstruction.')
            elif family == 'natural_jam_backoff':
                joint = answers[0]['arguments']['joint']
                interrupted = {'name':'move', 'arguments':{
                    'joint':joint, 'angle_deg':obs['joints'][joint]['commanded_model_deg'],
                    'reference':'absolute', 'speed_pct':50}}
            else:
                previous = next(h['correction_delta_deg'] for h in query['history'] if 'correction_delta_deg' in h)
                interrupted = {'name':'pose', 'arguments':{
                    'joints':list(previous), 'angles_deg':list(previous.values()),
                    'reference':'current', 'speed_pct':50}}
            obs['action'] = {'t':'intent', 'name':'motion_plan', 'args':{}, 'seq':33, 'epoch':obs['epoch']}
            obs.pop('speed_pct', None)
            # No speed request is carried by this actual host observation shape.
            # Apply the existing contract's unspecified-speed target (50%).
            for answer in answers:
                if 'speed_pct' in answer['arguments']:
                    answer['arguments']['speed_pct'] = 50
            query['history'].append({
                'observation':copy.deepcopy(obs), 'interrupted_action':interrupted,
                'interrupted_program':{'program':[interrupted]},
                'packet_progress':{'completed_frames':0},
                'event':{'name':'body_event','data':copy.deepcopy(event),'epoch':obs['epoch']}})
        signature = hashlib.sha256(compact([query, answers, original['source_hash'], variant]).encode()).hexdigest()
        result.append({**copy.deepcopy(original), 'id':signature[:16],
                       'query':compact(query), 'answers':answers,
                       'family':'host_input_'+family, 'source_id':'host-input:'+signature,
                       'source_hash':signature, 'parent_teacher_id':original['id'],
                       'input_variant':variant, 'synthetic':True, 'physical_qualification':False,
                       'scope':'Constructed host-shaped feedback reasoning. No measured recovery or dynamics evidence.'})
    return result


def build(source, corrections, output, curriculum=None, motion_weight=1):
    output.mkdir(parents=True, exist_ok=False)
    originals = read_rows(source/'train.jsonl')
    # Preserve parent weighting, but do not multiply it again while augmenting.
    unique = {r['query']:r for r in originals}
    additions = {v['query']:v for r in unique.values() for v in variants(r)
                 if v['query'] not in unique}
    additions = list(additions.values())
    corrected = [r for path in corrections for r in read_rows(path)]
    grounded = read_rows(curriculum) if curriculum else []
    rows = originals + additions + (corrected + grounded) * motion_weight
    evaluation = read_rows(source/'evaluation.jsonl')
    overlap = {r['query'] for r in rows} & {r['query'] for r in evaluation}
    if overlap:
        raise ValueError('Training/evaluation query overlap in proposed offline dataset')
    write_rows(output/'train.jsonl', rows)
    write_rows(output/'host-input-additions.jsonl', additions)
    for name in ('evaluation.jsonl', 'system.txt', 'tools.json'):
        (output/name).write_bytes((source/name).read_bytes())
    report = {'parent_train_sha256':digest(source/'train.jsonl'),
              'generator_sha256':digest(Path(__file__)),
              'bridge_source_sha256':digest(Path(__file__).with_name('bridge.py')),
              'corrections':{str(p):digest(p) for p in corrections},
              'curriculum_sha256':digest(curriculum) if curriculum else None,
              'distinct_curriculum_programs':len(grounded), 'new_motion_weight':motion_weight,
              'splits':{'train':len(rows), 'evaluation':len(evaluation)},
              'host_input_additions':len(additions), 'reviewed_corrections':len(corrected),
              'families':dict(Counter(r['family'] for r in rows)),
              'physical_trials':0, 'training_started':False,
              'scope':'Existing numerical recovery targets in varied host-shaped inputs plus independently reviewed external corrections.'}
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(compact({k:report[k] for k in ('splits','host_input_additions','reviewed_corrections')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--corrections', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--curriculum', type=Path)
    parser.add_argument('--motion-weight', type=int, default=1)
    args = parser.parse_args()
    build(args.source, args.corrections, args.output, args.curriculum, args.motion_weight)
