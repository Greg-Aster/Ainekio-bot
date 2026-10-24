"""Incrementally teach the owner-selected Stand default and explicit overrides.

Only changed/new targets are replayed. A proposed correction from a recorded
observation is not a successful physical trial. This never changes runtime code.
"""
import argparse
import copy
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .challenge import digest, read_rows, replay, write_rows
from .curriculum import Author, example, source_state
from .kinematics import ROOT
from .recordings import read_records
from .runtime import JOINTS, compact
from .semantic_teachers import call, source_wave


def final_pose(values, speed=50):
    return call('pose',joints=list(JOINTS),angles_deg=list(values),reference='absolute',speed_pct=speed)


def replace_wave_ending(program, values, establish_seated_shoulders=False):
    result=copy.deepcopy(program)
    last=max(i for i,a in enumerate(result) if a['name']=='pose')
    result[last]=final_pose(values,result[last]['arguments']['speed_pct'])
    if establish_seated_shoulders:
        first=next(a for a in result if a['name']=='pose')
        q=dict(zip(first['arguments']['joints'],first['arguments']['angles_deg']))
        q.update({j:0 for j in JOINTS if j.endswith('_shoulder')})
        result[result.index(first)]=final_pose([q[j] for j in JOINTS],first['arguments']['speed_pct'])
    return result


def candidates(base, stand, database, job_id):
    records=list(read_records(database,job_id))
    requested=next(r for r in records if r['kind']=='generation_requested')
    completed=next(r for r in records if r['kind']=='generation_completed')
    real=copy.deepcopy(requested['payload']['request'])
    metadata={'synthetic':True,'physical_qualification':False,
              'qualification_basis':'proposed_correction_not_executed'}
    for old in read_rows(base/'train.jsonl'):
        if old['family'] not in ('source_wave','source_joint_wave'):continue
        q=json.loads(old['query'])
        program=replace_wave_ending(old['answers'],stand)
        yield example(q['request'],q['observation'],program,old['family'],event=q.get('event'),history=q.get('history',[]),
                      parent_example_id=old['id'],ending_policy='default_stand',expected_final_model_deg=stand,
                      rehearsal=True,split='train',teacher='agent-authored full Stand endpoint correction',**metadata)
    perturbations={'stand':(-12,8,-35,18),'sit':(8,-6,25,-20),'crouch':(-15,12,-22,30),'rest':(10,-10,18,-16)}
    states=[]
    for pose,shoulders in perturbations.items():
        state=source_state(pose)
        for joint,value in state['joints'].items():
            value['home_deg']=real['observation']['joints'][joint]['home_deg']
        for leg,angle in zip(('rear_left','rear_right','front_left','front_right'),shoulders):
            state['joints'][leg+'_shoulder'].update(model_deg=angle,commanded_model_deg=angle)
        states.append(state)
        for side in ('left','right'):
            for ending in ('default_stand','explicit_start','explicit_raised'):
                program=source_wave(side,cycles=2,period_s=1.5,speed_pct=50)
                initial=[state['joints'][j]['model_deg'] for j in JOINTS]
                expected=stand if ending=='default_stand' else initial if ending=='explicit_start' else None
                program=replace_wave_ending(program,stand if expected is None else expected,True)
                request=f'Wave hello twice with your {side} hand.'
                if ending=='explicit_start':request+=' Return every joint to its starting position afterward.'
                elif ending=='explicit_raised':
                    request+=' Leave the waving hand extended afterward.'
                    program=program[:4]+[copy.deepcopy(program[-1])]
                yield example(request,copy.deepcopy(state),program,'gesture_ending_wave',ending_policy=ending,
                              expected_final_model_deg=expected,starting_pose=pose+'_nonzero_shoulders',split='train',
                              teacher='agent-authored matched ending instructions from constructed nonzero-shoulder poses',**metadata)
    requests={'clap':'Clap twice.','bow':'Give a polite bow.','shrug':'Shrug.',
              'salute':'Salute with your right hand.','drum':'Play the drums for two alternating pairs.',
              'point':'Point diagonally with your right hand.'}
    for state in states[:2]:
        for family,request in requests.items():
            author=Author(state,duration=.5,pause=.4)
            author.task(family,'right',2 if family in ('clap','drum') else 1,16)
            author.program.append(final_pose(stand))
            yield example(request,copy.deepcopy(state),author.program,'gesture_ending_'+family,
                          ending_policy='default_stand',expected_final_model_deg=stand,split='train',
                          teacher='agent-authored existing gesture with full Stand endpoint',**metadata)
    program=replace_wave_ending(completed['payload']['result']['program'],stand)
    yield example(real['request'],real['observation'],program,'proposed_recorded_wave_correction',event=real.get('event'),history=real.get('history',[]),
                  ending_policy='default_stand',expected_final_model_deg=stand,split='train',
                  observation_origin='recorded_robot',request_evidence_id=requested['id'],job_id=job_id,
                  teacher='agent-proposed endpoint correction from recorded observation; not executed',**metadata)


def review(row):
    trace=replay(row['answers'],json.loads(row['query'])['observation'])
    expected=row.get('expected_final_model_deg')
    end_error=max((abs(trace['samples'][-1]['joints_deg'][j]-v) for j,v in zip(JOINTS,expected)),default=0) if expected else None
    evidence={'status':trace['status'],'completed_actions':trace['completed_actions'],'error':trace.get('error'),
              'accepted':trace['status']=='replayed' and (end_error is None or end_error<=.011),
              'proof':'full kinematic trajectory','max_final_joint_error_deg':end_error,'physical_success':None}
    row['kinematic_evidence']=evidence
    return row


def build(base,output,stand_file,database,job_id,workers):
    output.mkdir(parents=True,exist_ok=False)
    stand_record=json.loads(stand_file.read_text());stand=stand_record['model_deg']
    generated=list(candidates(base,stand,database,job_id));write_rows(output/'candidates.jsonl',generated)
    with ProcessPoolExecutor(workers) as pool:reviewed=list(pool.map(review,generated))
    accepted=[r for r in reviewed if r['kinematic_evidence']['accepted']]
    rejected=[r for r in reviewed if not r['kinematic_evidence']['accepted']]
    write_rows(output/'reviewed.jsonl',reviewed);write_rows(output/'rejected.jsonl',rejected)
    replacements={r['parent_example_id']:r for r in accepted if 'parent_example_id' in r}
    original=read_rows(base/'train.jsonl')
    training=[replacements.get(r['id'],r) for r in original]+[r for r in accepted if 'parent_example_id' not in r]
    write_rows(output/'train.jsonl',training)
    for name in ('evaluation.jsonl','test.jsonl','regression-evaluation.jsonl','recovery-probe.jsonl','tools.json'):
        (output/name).write_bytes((base/name).read_bytes())
    policy=('\nUnless the request specifies a different ending, finish a completed gesture in Stand. '
            'An explicit return to the starting pose, a seated ending, or leaving a limb raised overrides this default. '
            'Stand is a full twelve-joint absolute model pose in joint order '+compact(list(JOINTS))+' with degrees '+compact(stand)+'. '
            'Stand is not calibration Home. Generate the required ending as part of the program; retain all requested gesture phases and holds.\n')
    (output/'system.txt').write_text((base/'system.txt').read_text()+policy)
    manifest={'version':'8-standing-overlay','base_manifest_sha256':digest(base/'manifest.json'),
              'generator_sha256':digest(Path(__file__)),'standing_reference':stand_record,'standing_reference_sha256':digest(stand_file),
              'candidates':len(generated),'accepted':len(accepted),'rejected':len(rejected),'replaced_training_rows':len(replacements),
              'added_training_rows':sum('parent_example_id' not in r for r in accepted),'training_rows':len(training),
              'ending_policies':dict(Counter(r['ending_policy'] for r in accepted)),
              'splits':{'train':len(training),**{s:len(read_rows(output/(s+'.jsonl'))) for s in ('evaluation','test','regression-evaluation','recovery-probe')}},
              'physical_trials':0,'recorded_observation_proposed_corrections':sum(r['family']=='proposed_recorded_wave_correction' for r in accepted),
              'limits':['Only new/replaced examples replayed; unchanged base retains its prior audit.',
                        'Recorded observation correction is proposed and unexecuted, not operator-qualified success.',
                        'Main holdout programs remain frozen; new default-standing examples are training material.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','output','stand-file','database'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--job-id',required=True);p.add_argument('--workers',type=int,default=6)
    a=p.parse_args();build(a.base,a.output,a.stand_file,a.database,a.job_id,a.workers)
