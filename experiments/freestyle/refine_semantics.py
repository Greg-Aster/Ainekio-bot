"""Build a geometry-reviewed continuation dataset from programs and trial reviews.

No runtime routing or named-motion fallback is introduced. A rejected offline
teacher remains in the audit with its failure; it is not silently clipped into
a different target. The original spatial dataset is preserved unchanged.
"""
import argparse
import copy
import hashlib
import json
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .challenge import digest, read_rows, replay, write_rows
from .runtime import compact
from .semantic_teachers import demonstration


# Phrases are teaching material, never input matching rules in the deployed API.
LANGUAGE={
    'clapping':['Clap your hands {n} times','Mime applauding with {n} claps'],
    'hand_circle':['Bend down and circle your {side} hand {n} times','Bow while making {n} loops with your {side} hand'],
    'alternating_side_stretch':['Stretch to the {side} with that arm raised, then do the opposite side','Reach upward and lean sideways on each side, starting on the {side}'],
    'pushing':['Mime pushing something away with both hands {n} times','Press an imaginary object forward with both arms {n} times'],
    'pulling':['Pretend to pull something toward you with both hands {n} times','Tug an imaginary rope with both arms {n} times'],
    'drinking':['Pretend to drink from a cup in your {side} hand','Bring an imaginary drink toward your face with the {side} hand, pause, then put it back'],
    'draw_then_pull':['Draw a left-to-right line and an upward line with the {side} hand, then pull back and lower the hand','Use your {side} hand to trace a horizontal then vertical line before retracting and dropping it'],
    'drumming':['Play imaginary drums with alternating hands for {n} pairs of strokes, {side} hand first','Drum {n} alternating pairs, starting with your {side} hand'],
    'saluting':['Squat and salute {n} times with your {side} hand','Lower your body and make {n} salutes using your {side} arm'],
    'wiping':['Wipe side to side with your {side} hand {n} times','Pretend to wipe a table with {n} sideways sweeps of your {side} hand'],
    'stirring':['Stir an imaginary pot with your {side} hand for {n} turns','Make {n} stirring circles with your {side} arm'],
    'boxing':['Throw {n} pairs of alternating punches, {side} hand first','Shadowbox with {n} alternating punch pairs, starting on the {side}'],
    'beckoning':['Beckon me closer with your {side} hand {n} times','Make a come-here motion {n} times using your {side} arm'],
    'conducting':['Conduct an imaginary orchestra with {n} outward and inward sweeps','Lead the music with both hands for {n} conducting beats'],
    'shrugging':['Shrug both arms {n} times','Raise and drop both hands in {n} questioning shrugs'],
    'bobbing':['Bob your body up and down {n} times','Make {n} little body dips and rises'],
    'swaying':['Sway your body left and right {n} times','Rock from side to side for {n} complete cycles'],
    'twisting':['Twist your body left and right {n} times','Turn your torso from side to side for {n} cycles'],
    'bowing':['Make a polite bow','Bow forward, pause, then straighten back up'],
    'tapping':['Tap with your {side} hand {n} times','Lift and replace your {side} hand in {n} taps'],
    'cross_reach':['Reach across your body with your {side} hand','Lift the {side} hand and stretch it across toward the opposite side'],
    'windshield':['Move both hands together like windshield wipers for {n} cycles','Sweep both hands in the same sideways direction and back {n} times'],
    'guitar_strumming':['Pretend to play a guitar, strumming {n} times with your {side} hand','Hold an imaginary guitar neck with one hand and strum {n} times with the {side} hand'],
    'bird_mime':['Act like a bird: spread your arms and flap {n} times while swaying','Mime a bird with {n} wing flaps and a side-to-side sway'],
    'airplane_mime':['Pretend to be an airplane with spread wings and banking turns','Spread your arms like airplane wings, hold them out and bank each way'],
    'two_hand_window_wiping':['Wash an imaginary window with both hands for {n} sweeps','Use both hands together to wipe a window {n} times'],
    'hammering':['Hammer an imaginary nail {n} times with your {side} hand','Hold an imaginary nail still with one hand and strike it {n} times with the {side} hand'],
    'swat_then_shrug':['Swat to the {side} {n} times with that hand, then shrug','Use your {side} hand to shoo something away {n} times, then shrug both arms'],
    'moonwalk':['Do a moonwalk for {n} alternating pairs of steps','Glide backward with alternating foot resets for {n} moonwalk cycles'],
}


def row(family, request, program, observation, **metadata):
    query=compact({'request':request,'event':None,'observation':observation,'history':[]})
    signature=hashlib.sha256(compact([query,program]).encode()).hexdigest()
    return {'id':signature[:16],'family':family,'query':query,'answers':program,
            'source_id':'semantic-teacher:'+signature,'source_hash':signature,
            'synthetic':True,'physical_qualification':False,**metadata}


def audit(item):
    value=json.loads(item['query']);state=value['observation']
    trace=replay(item['answers'],state)
    allowed_partial=trace['status']=='not_fully_replayed' and trace.get('operation') in ('gait','stop')
    # Prefix-only evidence is identified separately for feedback/gait examples.
    return item, {'id':item['id'],'family':item['family'],'status':trace['status'],
                  'completed_actions':trace['completed_actions'],'error':trace.get('error'),
                  'operation':trace.get('operation'),'accepted':trace['status']=='replayed' or allowed_partial,
                  'proof':'kinematic prefix only' if allowed_partial else 'full kinematic program',
                  'sample_count':len(trace['samples'])}


def build(source, state_file, corrections, output, workers):
    output.mkdir(parents=True,exist_ok=False)
    state=json.loads(state_file.read_text());rng=random.Random(5801)
    candidates=[];variants=[]
    for family,phrases in LANGUAGE.items():
        for side in ('right','left'):
            for cycles in (1,2,3):
                program=demonstration(family,side,cycles)
                request=phrases[cycles%2].format(side=side,n=cycles)+'. Return to your starting pose after the motion.'
                example=row('semantic_'+family,request,program,copy.deepcopy(state),teacher_family=family)
                candidates.append(example);variants.append(example)
    # Distinct compositions teach combinations, rather than only more aliases.
    for _ in range(96):
        chosen=rng.sample(variants,2 if _%3 else 3)
        text=' Then '.join(json.loads(r['query'])['request'] for r in chosen)
        candidates.append(row('semantic_composition',text,
            [a for r in chosen for a in r['answers']],copy.deepcopy(state),
            teacher_families=[r['teacher_family'] for r in chosen]))
    # Rehearsal preserves numerical instructions and feedback arithmetic.
    counts=Counter()
    for original in read_rows(source/'train.jsonl'):
        family=original['family']
        limit=24 if family.startswith('spatial_') else 32
        if counts[family]>=limit:continue
        counts[family]+=1;candidates.append(copy.deepcopy(original))
    for path in corrections:candidates.extend(read_rows(path))
    accepted=[];audits=[]
    with (output/'audit.jsonl').open('x') as stream, ProcessPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(audit,item) for item in candidates]):
            item, evidence=future.result();audits.append(evidence)
            stream.write(compact(evidence)+'\n');stream.flush()
            if evidence['accepted']:
                item['kinematic_evidence']=evidence;accepted.append(item)
            if len(audits)%40==0:
                print(compact({'audited':len(audits),'total':len(candidates),'accepted':len(accepted)}),flush=True)
    accepted.sort(key=lambda r:r['id'])
    # More language for the same reviewed teacher: retain geometry and provenance.
    additions=[]
    for item in accepted:
        if not item.get('teacher_family'):continue
        query=json.loads(item['query'])
        for prefix in ('Can you ', 'Act out this motion with your robot body: '):
            additions.append(row(item['family'],prefix+query['request'][0].lower()+query['request'][1:],
                                  item['answers'],query['observation'],
                                  teacher_family=item['teacher_family'],kinematic_evidence=item['kinematic_evidence']))
    accepted.extend(additions)
    accepted=list({r['query']:r for r in accepted}.values());rng.shuffle(accepted)
    write_rows(output/'train.jsonl',accepted)
    # Evaluation remains the original numerical fold, never copied into training.
    evaluation=read_rows(source/'evaluation.jsonl')
    write_rows(output/'evaluation.jsonl',evaluation)
    for name in ('system.txt','tools.json'):(output/name).write_bytes((source/name).read_bytes())
    manifest={'source_dataset_sha256':digest(source/'manifest.json'),'state_sha256':digest(state_file),
              'generator_sha256':digest(Path(__file__)),'teacher_sha256':digest(Path(__file__).with_name('semantic_teachers.py')),
              'splits':{'train':len(accepted),'evaluation':len(evaluation)},
              'families':dict(Counter(r['family'] for r in accepted)),
              'audit':{'candidates':len(candidates),'accepted_before_language_variants':sum(r['accepted'] for r in audits),
                       'rejected':sum(not r['accepted'] for r in audits)},
              'corrections':{str(path):digest(path) for path in corrections},
              'limits':['Synthetic kinematic targets; no physical stability or recovery qualification.',
                        'Named teacher families are offline examples, never a deployed capability list.',
                        'Source numerical evaluation remains untouched, including its earlier teacher limitations.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(compact(manifest),flush=True)


def extend_reviewed(source, state_file, output, workers):
    """Repair reviewed teachers and teach natural feedback requests consistently."""
    output.mkdir(parents=True,exist_ok=False)
    state=json.loads(state_file.read_text());originals=read_rows(source/'train.jsonl')
    candidates=[]
    for family in ('stirring','draw_then_pull'):
        for side in ('left','right'):
            for cycles in (1,2,3):
                request=LANGUAGE[family][cycles%2].format(side=side,n=cycles)+'. Return to your starting pose after the motion.'
                candidates.append(row('semantic_'+family,request,demonstration(family,side,cycles),state,
                                      teacher_family=family))
    amendments=[];audits=[]
    with ProcessPoolExecutor(workers) as pool:
        for item,evidence in pool.map(audit,candidates):
            audits.append(evidence)
            if evidence['accepted']:
                item['kinematic_evidence']=evidence;amendments.append(item)
                query=json.loads(item['query'])
                for prefix in ('Can you ', 'Act out this motion with your robot body: '):
                    amendments.append(row(item['family'],prefix+query['request'][0].lower()+query['request'][1:],
                        item['answers'],query['observation'],teacher_family=item['teacher_family'],kinematic_evidence=evidence))
    natural={
        'jam_smaller_wave':['Continue the interrupted movement with a smaller excursion through the recently traversed range.',
                            'Adapt the unfinished movement to this obstruction and continue with a smaller motion.'],
        'jam_backoff':['Recover from the jam.','This joint got stuck. Respond using the position feedback.'],
        'fall_correction':['Recover from falling over so I can walk again.','Use this feedback to correct my fallen posture.'],
        'slip_correction':['I slipped while walking. Correct the movement.','Adjust the movement after this slip.'],
    }
    for original in originals:
        if original['family'] not in natural:continue
        for number,request in enumerate(natural[original['family']]):
            query=json.loads(original['query']);query['request']=request
            if original['family']=='fall_correction' and number==1:
                query['event']={**query['event'],'type':'tipped'}
            text=compact(query)
            signature=hashlib.sha256(compact([text,original['answers'],original['source_hash']]).encode()).hexdigest()
            amendments.append({**copy.deepcopy(original),'id':signature[:16],
                'family':'natural_'+original['family'],'query':text,
                'source_id':'natural-feedback:'+signature,'source_hash':signature,
                'parent_teacher_id':original['id'],
                'scope':'same reviewed kinematic correction under a natural request; synthetic feedback effect, not a measured recovery'})
    # Corrected versions replace the same teaching query; old artifacts remain.
    rows=list({r['query']:r for r in originals+amendments}.values())
    random.Random(5802).shuffle(rows)
    write_rows(output/'train.jsonl',rows);write_rows(output/'amendment-audit.jsonl',audits)
    for name in ('evaluation.jsonl','system.txt','tools.json'):(output/name).write_bytes((source/name).read_bytes())
    manifest={'parent_manifest_sha256':digest(source/'manifest.json'),
              'parent_train_sha256':digest(source/'train.jsonl'),'generator_sha256':digest(Path(__file__)),
              'teacher_sha256':digest(Path(__file__).with_name('semantic_teachers.py')),
              'splits':{'train':len(rows),'evaluation':len(read_rows(output/'evaluation.jsonl'))},
              'families':dict(Counter(r['family'] for r in rows)),
              'amendment_audit':audits,'synthetic':True,'physical_trials':0,
              'limits':['Feedback reasoning examples do not establish physical fall/slip recovery.',
                        'Natural requests retain the original evidence and corrected target; only wording/event naming changes.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(compact({'splits':manifest['splits'],'amendments':len(amendments),
                   'teacher_repairs_replayed':sum(r['accepted'] for r in audits),'teacher_repairs_total':len(audits)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','state-file','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--corrections',type=Path,nargs='*',default=[]);p.add_argument('--workers',type=int,default=4)
    p.add_argument('--extend-reviewed',action='store_true')
    a=p.parse_args()
    if a.extend_reviewed:extend_reviewed(a.source,a.state_file,a.output,a.workers)
    else:build(a.source,a.state_file,a.corrections,a.output,a.workers)
