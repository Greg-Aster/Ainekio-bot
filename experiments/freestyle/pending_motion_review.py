"""Offline proposals for specific recorded requests, never a serving router.

Keep the frozen v8 run intact. Every label here is an unexecuted teacher
proposal, with measured trial evidence distinct from semantic interpretation.
"""
import argparse
import copy
import json
import math
from collections import Counter
from pathlib import Path

from .challenge import digest, read_rows, replay, write_rows
from .curriculum import Author, example, source_state
from .curriculum_split import motion_structure
from .ending_curriculum import final_pose
from .recordings import read_records
from .runtime import JOINTS
from .semantic_teachers import call


CASES = {
    '1e8a3e2a-4a22-41b1-bf8e-4431efe43dd5': dict(family='bread', side='right', ending='stand', cycles=2),
    '9b9084a9-e0e3-4823-b246-9fc9fc1663e1': dict(family='sigh', side='right', ending='stand', cycles=2),
    'ca8c9a55-27ae-4f60-b4ad-06fef2af0b84': dict(family='wiggle', side='right', ending='stand', cycles=2),
    'fe1ad7fb-628b-4b30-b561-c11a7ef0c224': dict(family='hand', side='right', ending='stand', cycles=2),
    '3dd78d91-ab50-45a6-91eb-37d69effe5d6': dict(family='hand', side='right', ending='stand', cycles=2),
}
OCT24_CASES = {
    'd468768b64e04d44bb21d721443e9bab': dict(family='stretch_forward', side='right', ending='stand', cycles=2),
    '0c679e2d9560457c8fa0811ad95ce737': dict(family='stretch_spread', side='right', ending='stand', cycles=2),
}
NOTES = {
    'bread': 'Add a visible two-choice survey, reach and gentle grasp mime, then lift. A foot represents a hand; no finger/gripper capability or real grasp is claimed.',
    'sigh': 'Keep the original 0.8s inhale, 0.6s hold and 0.8s exhale, with a visible torso/shoulder sink below the preparatory standing height before settling.',
    'wiggle': 'Replace diagonal-foot shuffling with alternating lateral torso shifts at the original 20mm excursion, then explicit full Stand. Recognition as a hip wiggle remains unverified.',
    'hand': 'Replace the 12mm foot twitch with a visible raised front hand. Keep the original 1s outward travel; default to Stand afterward unless explicitly asked to keep it raised.',
    'stretch_forward': 'Prepare native Stand before the full30mm front-arm lift and two20mm forward stretches; preserve every0.6s travel/hold, then restore both arms and finish full Stand.',
    'stretch_spread': 'Prepare native Stand before the full30mm four-leg excursion and two20mm front spreads; preserve0.6s entry/return and0.4s spread phases; restore all four legs and finish full Stand.',
}


def proposal(observation, stand, family, side='right', ending='stand', cycles=2):
    prepared = copy.deepcopy(observation)
    for joint, angle in zip(JOINTS, stand):
        prepared['joints'][joint].update(model_deg=angle, commanded_model_deg=angle)
    author = Author(prepared)
    hand = 'front_' + side
    sign = 1 if side == 'left' else -1
    if family == 'bread':
        # Survey two imaginary choices, then select one. Distinct task phases,
        # rather than paraphrasing the original reach-and-return program.
        author.target({hand: [80, sign * 110, 65]}, .6)
        author.target({hand: [110, sign * 110, 65]}, .6)
        author.target({hand: [95, sign * 100, 65]}, .6)
        author.hold(.25)
        author.target({hand: [95, sign * 100, 90]}, .279)
        author.hold(.25)
        if ending != 'raised':
            author.target({hand: [95, sign * 100, 65]}, .279)
            author.target({hand: author.initial[hand]}, .6)
        expression = 'curious'
    elif family == 'hand':
        author.target({hand: [95, sign * 100, 90]}, 1.)
        author.hold(.6)
        if ending != 'raised':
            author.target({hand: author.initial[hand]}, 1.)
        expression = 'happy'
    elif family == 'sigh':
        author.duration = .8
        author.torso(translation=(0, 0, 3))
        author.hold(.6)
        author.torso(translation=(0, 0, -6))
        expression = 'sad'
    elif family == 'wiggle':
        author.duration = .8
        author.torso(translation=(0, 20, 0))
        author.hold(.4)
        for index in range(cycles):
            author.duration = .5
            author.torso(translation=(0, -40 if index % 2 == 0 else 40, 0))
        author.hold(.4)
        author.duration = .8
        author.torso(translation=(0, 20 if cycles % 2 else -20, 0))
        expression = 'dance'
    elif family in ('stretch_forward', 'stretch_spread'):
        hands = ['front_left', 'front_right']
        legs = hands if family == 'stretch_forward' else list(author.initial)
        author.target({leg: [p[0], p[1], p[2] + 30]
                       for leg in legs for p in [author.initial[leg]]}, .6)
        raised = copy.deepcopy(author.current)
        for _ in range(cycles):
            targets = {leg: [raised[leg][0] + (20 if family == 'stretch_forward' else 0),
                             raised[leg][1] + ((20 if leg.endswith('left') else -20)
                                               if family == 'stretch_spread' else 0),
                             raised[leg][2]] for leg in hands}
            author.target(targets, .6 if family == 'stretch_forward' else .4)
            if family == 'stretch_forward':
                author.hold(.6)
            author.target({leg: raised[leg] for leg in hands}, .6 if family == 'stretch_forward' else .4)
        author.target({leg: author.initial[leg] for leg in legs}, .6)
        expression = 'stretch'
    else:
        raise ValueError(f'Unknown offline teacher: {family}')
    program = [call('face', expr=expression), final_pose(stand)] + author.program
    goals = [{'action_index': i + 2, **goal} for i, goal in enumerate(author.goals)]
    if ending == 'stand':
        program.append(final_pose(stand))
    elif ending != 'raised' or family not in ('hand', 'bread'):
        raise ValueError('Unsupported explicit ending')
    return program, goals


def candidates(records, stand, cases=None, include_contrasts=True):
    cases = CASES if cases is None else cases
    for job, specification in cases.items():
        family = specification['family']
        items = [r for r in records if r['job_id'] == job]
        requested = next(r for r in items if r['kind'] == 'generation_requested')
        generated = next(r for r in items if r['kind'] == 'generation_completed')
        q = copy.deepcopy(requested['payload']['request'])
        program, goals = proposal(q['observation'], stand, **specification)
        yield example(q['request'], q['observation'], program, 'pending_recorded_' + family,
                      event=q.get('event'), history=q.get('history', []), split='train',
                      job_id=job, request_evidence_id=requested['id'],
                      generated_evidence_id=generated['id'],
                      review_evidence_ids=[r['id'] for r in items if r['kind'] == 'review'],
                      original_program=generated['payload']['result']['program'],
                      observation_origin='recorded_robot', correction_note=NOTES[family],
                      semantic_assessment='agent interpretation; no operator success or failure label inferred',
                      qualification_basis='proposed_correction_not_executed',
                      teacher='agent-authored proposed correction based on recorded request and observations',
                      reviewed_request_specification=specification,
                      expected_final_model_deg=stand if specification['ending'] == 'stand' else None,
                      ending_policy='default_stand' if specification['ending'] == 'stand' else 'explicit_raised',
                      spatial_goals=goals)
    if not include_contrasts:
        return
    # Meaningful contrasting labels: handedness, count and explicit final pose.
    for family, side, ending, cycles in (
        ('hand', 'left', 'stand', 2), ('hand', 'left', 'raised', 2),
        ('hand', 'right', 'stand', 2), ('hand', 'right', 'raised', 2),
        ('bread', 'left', 'raised', 2), ('bread', 'right', 'raised', 2),
        ('wiggle', 'right', 'stand', 1), ('wiggle', 'right', 'stand', 3),
    ):
        state = source_state()
        request = (f'Raise your {side} hand.' if family == 'hand' else
                   f'Choose an imaginary loaf, reach with your {side} hand, grasp gently and lift it.' if family == 'bread' else
                   f'Sway your hips from right to left {cycles} alternating times, then settle standing.')
        if ending == 'raised':
            request += ' Keep that hand raised at the end.'
        program, goals = proposal(state, stand, family, side, ending, cycles)
        yield example(request, state, program, 'pending_contrast_' + family, split='train',
                      teacher='agent-authored side/count/explicit-ending contrast; not a physical trial',
                      observation_origin='synthetic_source_pose',
                      qualification_basis='synthetic_unexecuted_proposal', spatial_goals=goals,
                      expected_final_model_deg=stand if ending == 'stand' else None,
                      ending_policy='explicit_raised' if ending == 'raised' else 'default_stand')


def qualify(row):
    trace = replay(row['answers'], json.loads(row['query'])['observation'])
    evidence = {'status': trace['status'], 'error': trace.get('error'),
                'completed_actions': trace['completed_actions'],
                'physical_success': None, 'accepted': False}
    if trace['status'] == 'replayed' and trace['completed_actions'] == len(row['answers']):
        endpoints = {s['action_index']: s for s in trace['samples']}
        error, timing = 0., 0.
        for goal in row['spatial_goals']:
            index = goal['action_index']
            end = endpoints[index]
            for leg, point in goal['after'].items():
                error = max(error, math.dist(end['feet_body_mm'][leg], point))
            timing = max(timing, abs(end['time_s'] - endpoints[index - 1]['time_s'] - goal['seconds']))
        expected = row['expected_final_model_deg']
        final_error = (max(abs(trace['samples'][-1]['joints_deg'][j] - angle)
                           for j, angle in zip(JOINTS, expected)) if expected else 0.)
        evidence.update(max_endpoint_error_mm=error, max_duration_error_s=timing,
                        final_pose_error_deg=final_error,
                        accepted=error < .15 and timing < .002 and final_error < .011,
                        proof='full kinematic replay and independent authored phase/end/timing checks; no physical qualification')
    row['kinematic_evidence'] = evidence
    return row


def evidence_snapshot(records, cases=None):
    """Associate raw packets only inside their job operation's monotonic window.

    Epoch/sequence counters restart across gateway processes. A key alone is
    not globally unique in an append-only database.
    """
    cases = CASES if cases is None else cases
    selected = {r['id']: r for r in records if r['job_id'] in cases}
    for job in cases:
        items = [r for r in records if r['job_id'] == job]
        starts = [r for r in items if r['kind'] == 'operation_started']
        for receipt in (r for r in items if r['kind'] == 'command_receipt'):
            preceding = [r for r in starts if r['monotonic_ns'] <= receipt['monotonic_ns']]
            if not preceding:
                continue
            start = preceding[-1]
            key = tuple(receipt[k] for k in ('robot_id', 'epoch', 'sequence'))
            for row in records:
                if (start['monotonic_ns'] <= row['monotonic_ns'] <= receipt['monotonic_ns']
                        and start['time_ns'] <= row['time_ns'] <= receipt['time_ns']
                        and tuple(row[k] for k in ('robot_id', 'epoch', 'sequence')) == key):
                    selected[row['id']] = row
    return sorted(selected.values(), key=lambda r: (r['time_ns'], r['id']))


def build(database, base, stand_file, output, batch='earlier'):
    output.mkdir(parents=True, exist_ok=False)
    frozen_hash = digest(base / 'train.jsonl')
    stand = json.loads(stand_file.read_text())['model_deg']
    records = list(read_records(database))
    cases = OCT24_CASES if batch == 'oct24' else CASES
    rows = [qualify(r) for r in candidates(records, stand, cases, batch == 'earlier')]
    accepted = [r for r in rows if r['kinematic_evidence']['accepted']]
    write_rows(output / 'train.jsonl', accepted)
    write_rows(output / 'rejected.jsonl', [r for r in rows if not r['kinematic_evidence']['accepted']])
    write_rows(output / 'audit.jsonl', [{'id': r['id'], **r['kinematic_evidence']} for r in rows])
    unlabeled = ({'81cd66f2d9694a18a5529553f9c3fe65':
                  'Rapid yaw event at1.94deg tilt; generated large relative pose/rotations then superseded. Cause and effective recovery unknown; no positive or corrected target inferred.'}
                 if batch == 'oct24' else {})
    write_rows(output / 'recorded-evidence.jsonl', evidence_snapshot(records, set(cases) | set(unlabeled)))
    for name in ('system.txt', 'tools.json'):
        (output / name).write_bytes((base / name).read_bytes())
    overlap = {}
    structures = {motion_structure(r['answers']) for r in accepted}
    for fold in ('evaluation', 'test'):
        held_out = read_rows(base / (fold + '.jsonl'))
        overlap[fold] = {
            'exact_queries': len({r['query'] for r in accepted} & {r['query'] for r in held_out}),
            'motion_structures': len(structures & {motion_structure(r['answers']) for r in held_out}),
        }
    manifest = {'status': 'reviewed_pending_next_training_pass', 'rows': len(accepted),
                'rejected': len(rows) - len(accepted), 'recorded_proposals': len(cases),
                'review_batch': batch,
                'reviewed_not_labeled': unlabeled,
                'families': dict(Counter(r['family'] for r in accepted)),
                'frozen_v8_train_sha256': frozen_hash, 'frozen_v8_unchanged': digest(base / 'train.jsonl') == frozen_hash,
                'teacher_sha256': digest(Path(__file__)),
                'held_out_overlap': overlap,
                'compiler_sha256': digest(Path(__file__).with_name('kinematics.py')),
                'replay_sha256': digest(Path(__file__).with_name('challenge.py')),
                'physical_trials': 0, 'evidence_association': 'job IDs plus operation-bounded monotonic and wall-clock packet windows',
                'limits': ['Semantic interpretations are proposals, not operator judgments.',
                           'Kinematics do not establish balance, clearance, contact or recognizable physical performance.',
                           'Preserved authored travel durations; transport delays are not trained away.']}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database', 'base', 'stand-file', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--batch', choices=('earlier', 'oct24'), default='earlier')
    a = p.parse_args()
    build(a.database, a.base, a.stand_file, a.output, a.batch)
