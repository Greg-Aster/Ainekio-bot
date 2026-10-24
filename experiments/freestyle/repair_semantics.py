"""Review replacements of superseded offline teaching paths, never runtime input.

Matches exact old program segments from a saved catalog, not user wording.
Produces candidates and traces for review; it does not export training rows.
"""
import argparse
import copy
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .challenge import digest, read_rows, replay, trajectory_metrics, write_rows
from .kinematics import frames_for_spatial
from .program import frames_for
from .runtime import JOINTS, compact
from .semantic_teachers import demonstration


def rewrite(program, observation, patterns):
    positions = {j:observation['joints'][j]['model_deg'] for j in JOINTS}
    home = {j:observation['joints'][j]['home_deg'] for j in JOINTS}
    result, replacements = [], []
    index = 0
    while index < len(program):
        match = next((p for p in patterns if program[index:index+len(p['program'])] == p['program']), None)
        if match:
            state = copy.deepcopy(observation)
            for joint,value in positions.items():
                state['joints'][joint]['model_deg'] = value
            actions = demonstration(match['family'],match['side'],match['cycles'],observation=state)
            replacements.append({'old_action_index':index, 'new_action_index':len(result),
                                 'old_actions':len(match['program']), 'new_actions':len(actions),
                                 'family':match['family'], 'side':match['side'], 'cycles':match['cycles']})
            index += len(match['program'])
        else:
            actions = [program[index]]
            index += 1
        for action in actions:
            if action['name'] == 'hold':
                pass
            elif action['name'] in ('feet','body'):
                frames = frames_for_spatial(action,positions)
                if frames: positions = dict(zip(JOINTS,[v/100 for v in frames[-1][1]]))
            elif action['name'] in ('move','pose','oscillate'):
                for _,angles in frames_for(action,positions,home,observation['joint_speed_limit_deg_s']):
                    positions = dict(zip(JOINTS,[v/100 for v in angles]))
            else:
                raise ValueError('Cannot infer the next teaching pose after '+action['name'])
            result.append(action)
    return result,replacements


def review(item, patterns):
    program,state = item['original_program'],item['observation']
    before = replay(program,state)
    result = {**item,'before_trace':before,'before_metrics':trajectory_metrics(before)}
    try:
        replacement,changes = rewrite(program,state,patterns)
        after = replay(replacement,state)
        result.update(corrected_program=replacement,changes=changes,
                      after_trace=after,after_metrics=trajectory_metrics(after))
    except (ValueError,KeyError,TypeError) as error:
        result['authoring_error'] = str(error)
    return result


def run(source, catalog, output, workers):
    output.mkdir(parents=True,exist_ok=False)
    patterns = json.loads(catalog.read_text())['patterns']
    patterns = list({compact(p['program']):p for p in patterns}.values())
    patterns.sort(key=lambda p:len(p['program']),reverse=True)
    grouped = {}
    for row in read_rows(source):
        program = row['answers']
        if not any(program[i:i+len(p['program'])] == p['program']
                   for p in patterns for i in range(len(program))):
            continue
        query = json.loads(row['query'])
        key = hashlib.sha256(compact([program,query['observation']]).encode()).hexdigest()[:16]
        item = grouped.setdefault(key,{'id':key,'original_program':program,
                'observation':query['observation'],'source_rows':[]})
        item['source_rows'].append({'id':row['id'],'query_sha256':hashlib.sha256(row['query'].encode()).hexdigest(),
                                    'request':query['request'],'family':row['family']})
    reviews = []
    with ProcessPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(review,item,patterns) for item in grouped.values()]):
            item = future.result()
            filename = item['id']+'.json'
            (output/filename).write_text(compact(item)+'\n')
            entry = {'id':item['id'],'evidence':filename,'evidence_sha256':digest(output/filename),
                     'source_rows':len(item['source_rows']),
                     'status':item.get('after_trace',{}).get('status','authoring_error'),
                     'error':item.get('authoring_error') or item.get('after_trace',{}).get('error'),
                     'review_status':'awaiting semantic review','physical_qualification':False}
            reviews.append(entry)
            print(compact(entry),flush=True)
    write_rows(output/'reviews.jsonl',reviews)
    (output/'manifest.json').write_text(json.dumps({
        'source_sha256':digest(source),'catalog_sha256':digest(catalog),
        'teacher_sha256':digest(Path(__file__).with_name('semantic_teachers.py')),
        'repair_sha256':digest(Path(__file__)),'unique_program_states':len(grouped),
        'affected_weighted_rows':sum(len(r['source_rows']) for r in grouped.values()),
        'training_exported':False,'physical_trials':0},indent=2)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','catalog','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2)
    run(**vars(parser.parse_args()))
