"""Apply recorded corrections, authored face cues and current-compiler replay.

All mappings here author offline training examples. Serving never imports this
module or selects a motion/face by a request keyword.
"""
import argparse
import copy
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .challenge import digest, read_rows, write_rows
from .curriculum import Author, audit, example, source_state, signature
from .curriculum_split import motion_structure
from .ending_curriculum import final_pose, replace_wave_ending
from .face_contract import available_faces, extend_contract, FACE_SOURCE
from .recordings import read_records
from .runtime import JOINTS, compact
from .semantic_teachers import call


TASK_FACE={'wave':'wave','beckon':'happy','point':'point','salute':'happy','drink':'curious',
           'knock':'curious','wipe':'thinking','circle':'thinking','square':'thinking','triangle':'thinking',
           'figure_eight':'thinking','spiral':'thinking','scoop':'curious','throw':'excited','punch':'angry',
           'clap':'celebrate','drum':'excited','conduct':'dance','shrug':'shrug','flap':'happy',
           'microphone':'talk_happy','hammer':'thinking','bow':'bow','sway':'dance','squat':'pushup',
           'twist':'dance','stretch':'stretch','fold':'happy','step_over':'curious','shuffle':'dance',
           'offer':'happy','withdraw':'curious'}


def add_faces(row,cues):
    result=copy.deepcopy(row);program=[];goals=[]
    original_goals=result.get('goals')
    for index,action in enumerate(row['answers']):
        if index in cues:
            program.append(call('face',expr=cues[index]))
            if original_goals:
                point=original_goals[index]['before']
                goals.append({'kind':'face','before':copy.deepcopy(point),'after':copy.deepcopy(point),'seconds':0})
        program.append(copy.deepcopy(action))
        if original_goals:goals.append(copy.deepcopy(original_goals[index]))
    result['answers']=program
    if original_goals:result['goals']=goals
    result['parent_example_id']=row['id']
    value=signature([result['query'],program])
    result.update(id=value[:16],source_id='face-curriculum:'+value,source_hash=value,
                  face_cues=[{'before_motion_action':i,'expr':expr} for i,expr in sorted(cues.items())],
                  teacher=row.get('teacher','retained teacher')+'; agent-authored renderer face cues')
    return result


def decorate(row,spans):
    if any(a['name']=='face' for a in row['answers']):return copy.deepcopy(row)
    phases=spans.get(row['id'])
    if phases:
        return add_faces(row,{p['action_start']:TASK_FACE[p['family']] for p in phases})
    family=row['family']
    if 'wave' in family:return add_faces(row,{0:'wave'})
    if family.startswith('source_posture_'):return add_faces(row,{0:family.removeprefix('source_posture_')})
    if family.startswith('gesture_ending_'):
        return add_faces(row,{0:TASK_FACE[family.removeprefix('gesture_ending_')]})
    if family.startswith('recovery_'):return add_faces(row,{0:'thinking'})
    if family.startswith(('semantic_','grounded_','pose_grounded_')) or row['source_id'].startswith('reviewed-trial:'):
        key=family.removeprefix('semantic_').removeprefix('grounded_').removeprefix('pose_grounded_')
        return add_faces(row,{0:TASK_FACE.get(key,'curious')})
    return copy.deepcopy(row)


def eating_program(observation, stand, side='right', bites=2, ending='stand', duration=.35):
    """Offline mime teacher: reach, bring fruit beside face, bite, withdraw.

    A front foot represents the hand; no finger/gripper capability is assumed.
    This is a proposed reachable mime, not a contact or balance qualification.
    """
    prepared=copy.deepcopy(observation)
    for joint,angle in zip(JOINTS,stand):
        prepared['joints'][joint].update(model_deg=angle,commanded_model_deg=angle)
    author=Author(prepared,duration=duration)
    hand='front_'+side;sign=1 if side=='left' else -1
    author.target({hand:[95,sign*100,65]})
    author.hold(.15)
    author.target({hand:[95,sign*100,90]})
    for index in range(bites):
        author.target({hand:[95,sign*90,105]},duration if index==0 else .2)
        author.hold(.25)
        author.target({hand:[95,sign*100,90]},.2)
    if ending!='raised':author.target({hand:author.initial[hand]})
    program=[call('face',expr='happy'),final_pose(stand)]+author.program
    if ending=='stand':program.append(final_pose(stand))
    elif ending=='start':program.append(final_pose([observation['joints'][j]['model_deg'] for j in JOINTS]))
    elif ending!='raised':raise ValueError('Unknown eating ending')
    return program


def recorded_proposals(database,stand):
    records=list(read_records(database));by_job={}
    for record in records:
        if record['job_id']:by_job.setdefault(record['job_id'],[]).append(record)
    for job,items in by_job.items():
        requested=next((r for r in items if r['kind']=='generation_requested'),None)
        generated=next((r for r in items if r['kind']=='generation_completed'),None)
        if not requested or not generated:continue
        q=copy.deepcopy(requested['payload']['request']);text=q['request'].lower().strip()
        # These are the actual cases explicitly submitted for offline review.
        if text not in ('wave','clap','stretch','act like you are sawing an imaginary log with your right hand',
                        'act like you are eating an imaginary apple'):continue
        kind='apple' if 'imaginary apple' in text else 'saw' if 'sawing' in text else text
        original=copy.deepcopy(generated['payload']['result']['program'])
        if kind=='apple':
            program=eating_program(q['observation'],stand)[1:];expression='happy'
            note=('Replace unrelated bilateral lifts with a one-hand reach, two bring-to-face/bite/withdraw cycles '
                  'and explicit full Stand. Use short travel and bite holds; inverse relative offsets alone do not establish an ending.')
        elif kind=='wave':
            program=replace_wave_ending(original,stand);expression='wave'
            note='Preserve the generated wave and replace its partial eight-joint endpoint with native twelve-joint Stand.'
        elif kind=='stretch':
            program=copy.deepcopy(original)
            final_feet=max(i for i,a in enumerate(program) if a['name']=='feet')
            program[final_feet]['arguments']['legs']=list(program[0]['arguments']['legs'])
            program.append(final_pose(stand));expression='stretch'
            note='Preserve the full30mm four-leg excursion and both20mm spread cycles; repair final four-leg/offset correspondence and finish Stand.'
        else:
            prepared=copy.deepcopy(q['observation'])
            for joint,angle in zip(JOINTS,stand):
                prepared['joints'][joint]['model_deg']=angle
                prepared['joints'][joint]['commanded_model_deg']=angle
            author=Author(prepared,duration=.6,pause=.4)
            if kind=='clap':
                author.task('clap','right',1,20)
                for action,seconds in zip(author.program,(.6,.35,.35,.6)):
                    action['arguments']['seconds']=seconds
                expression='celebrate'
                note='Prepare native Stand, then complete a bilateral inward/outward clap mime through reachable elevated hand points; original one-cycle durations retained.'
            else:
                strokes=2 if len(original)==8 else 3
                hand='front_right';author.target({hand:[95 if strokes==2 else 80,-100,65]},original[0]['arguments']['seconds'])
                for _ in range(strokes):
                    if strokes==2:
                        for x,seconds in ((110,.4),(80,.7),(95,.4)):
                            author.target({hand:[x,-100,65]},seconds)
                    else:
                        for x in (110,80):author.target({hand:[x,-100,65]},.7)
                author.target({hand:author.initial[hand]},original[-1]['arguments']['seconds'])
                expression='thinking'
                note='Prepare native Stand and an elevated right hand; use fore/aft strokes for sawing, preserving the recorded cycle count and stroke durations, then return Stand.'
            program=[final_pose(stand)]+author.program+[final_pose(stand)]
        program=[call('face',expr=expression)]+program
        yield example(q['request'],q['observation'],program,'proposed_recorded_'+kind+'_correction',
                      event=q.get('event'),history=q.get('history',[]),expected_final_model_deg=stand,
                      split='train',ending_policy='default_stand',observation_origin='recorded_robot',
                      job_id=job,request_evidence_id=requested['id'],generated_evidence_id=generated['id'],
                      review_evidence_ids=[r['id'] for r in items if r['kind']=='review'],
                      original_program=original,correction_note=note,
                      qualification_basis='proposed_correction_not_executed',
                      teacher='agent-proposed correction from recorded request, observation and failure evidence')


def qualify(row):
    previous=row.get('kinematic_evidence')
    row,evidence=audit(row)
    row['previous_kinematic_evidence']=previous
    expected=row.get('expected_final_model_deg')
    if expected and evidence['accepted']:
        # Every explicit endpoint target is a final full-pose call, with face
        # calls/holds allowed afterward. Check this separately from valid IK.
        last=next((a for a in reversed(row['answers']) if a['name'] not in ('face','hold')),None)
        actual=dict(zip(last['arguments'].get('joints',[]),last['arguments'].get('angles_deg',[]))) if last and last['name']=='pose' else {}
        evidence['full_endpoint_matches']=len(actual)==12 and all(abs(actual.get(j,float('inf'))-v)<.011 for j,v in zip(JOINTS,expected))
        evidence['accepted'] &= evidence['full_endpoint_matches']
    row['kinematic_evidence']=evidence
    return accept_completed_targets(row)


def accept_completed_targets(row):
    """Report cadence approximation separately from target/phase completion.

    At the real20ms output cadence, straight Cartesian teacher segments become
    piecewise joint interpolation. Do not discard completed intended motions
    solely for submillimetre between-output curvature. IK stays unchanged.
    """
    e=row['kinematic_evidence']
    if e['status']=='replayed' and e.get('error') is None:
        if 'max_linear_path_error_mm' in e:
            e['continuous_line_tolerance_passed']=e['max_linear_path_error_mm']<.15
        e['accepted']=(e.get('max_endpoint_error_mm',0)<.15
                       and e.get('max_action_duration_error_s',0)<.002
                       and e.get('full_endpoint_matches',True))
        if row.get('goals') and len(row['goals'])!=len(row['answers']):
            e.update(accepted=False,error='Authored goal/action count mismatch')
        e['acceptance_basis']='all actions replayed, requested endpoints and durations retained; cadence path error reported separately'
    return row


def reclassify_existing(output):
    """Apply a measurement-interpretation revision without replaying again."""
    rows=[r for split in ('train','evaluation','test','recovery-probe','rejected') for r in read_rows(output/(split+'.jsonl'))]
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Audit examples must be distinct')
    rows=[accept_completed_targets(r) for r in rows];rows.sort(key=lambda r:r['id'])
    manifest=json.loads((output/'manifest.json').read_text())
    for split in ('train','evaluation','test','recovery-probe'):
        selected=[r for r in rows if r['split']==split and r['kinematic_evidence']['accepted']]
        (output/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in selected))
        manifest['splits'][split]=len(selected)
    rejected=[r for r in rows if not r['kinematic_evidence']['accepted']]
    (output/'rejected.jsonl').write_text(''.join(compact(r)+'\n' for r in rejected))
    (output/'audit.jsonl').write_text(''.join(compact({'id':r['id'],'split':r['split'],'family':r['family'],**r['kinematic_evidence']})+'\n' for r in rows))
    manifest['audit'].update(accepted=len(rows)-len(rejected),rejected=len(rejected),rejected_by_split=dict(Counter(r['split'] for r in rejected)))
    errors=[r['kinematic_evidence']['max_linear_path_error_mm'] for r in rows if 'max_linear_path_error_mm' in r['kinematic_evidence']]
    manifest['cadence_measurements']={'max_linear_path_error_mm':max(errors,default=0),
        'replayed_examples_above_legacy_line_tolerance':sum(r['kinematic_evidence'].get('continuous_line_tolerance_passed') is False for r in rows),
        'policy':'Retain fullreplayed endpoint/timing-correct trajectories; report between-output curve approximation separately. IK tolerance unchanged.',
        'reviewer_authorization':'Owner-task root approved separating20ms cadence approximation from target/phase completion.',
        'review_code_sha256':digest(Path(__file__))}
    splits={s:[r for r in rows if r['split']==s and r['kinematic_evidence']['accepted']] for s in ('train','evaluation','test')}
    for left,right in (('train','evaluation'),('train','test'),('evaluation','test')):
        manifest['overlap'][left+'_'+right]={'queries':len({r['query'] for r in splits[left]}&{r['query'] for r in splits[right]}),
                                          'motion_structures':len({motion_structure(r['answers']) for r in splits[left]}&{motion_structure(r['answers']) for r in splits[right]})}
    manifest['training_rows_with_faces']=sum(any(a['name']=='face' for a in r['answers']) for r in splits['train'])
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def build(base,output,stand_file,spans_file,database,workers):
    output.mkdir(parents=True,exist_ok=False)
    stand=json.loads(stand_file.read_text())['model_deg'];spans=json.loads(spans_file.read_text())
    candidates=[]
    for split in ('train','evaluation','test','recovery-probe'):
        for row in read_rows(base/(split+'.jsonl')):
            # Replaced below with the current recorded correction plus its face.
            if row['family']=='proposed_recorded_wave_correction':continue
            row=decorate(row,spans);row['split']=split;candidates.append(row)
    state=source_state()
    for expression in available_faces():
        candidates.append(example('Show the '+expression.replace('_',' ')+' face.',state,
                                  [call('face',expr=expression)],'face_only',split='train',
                                  teacher='agent-authored face-only instruction using renderer vocabulary'))
    wave=next(r for r in candidates if r['family']=='gesture_ending_wave' and r.get('ending_policy')=='default_stand')
    for expression in ('happy','sad','angry','surprised','confused','thinking','excited','love'):
        row=copy.deepcopy(wave);q=json.loads(row['query']);q['request']+=' Use a '+expression+' face throughout the gesture.'
        program=[call('face',expr=expression)]+[a for a in row['answers'] if a['name']!='face']
        candidates.append(example(q['request'],q['observation'],program,'explicit_face_gesture',
                                  event=q.get('event'),history=q.get('history',[]),split='train',
                                  expected_final_model_deg=stand,teacher='agent-authored explicit face override of a known body program'))
    candidates.extend(recorded_proposals(database,stand))
    write_rows(output/'candidates.jsonl',candidates)
    reviewed=[]
    with ProcessPoolExecutor(workers) as pool,(output/'audit.jsonl').open('x') as stream:
        for future in as_completed([pool.submit(qualify,row) for row in candidates]):
            row=future.result();reviewed.append(row)
            stream.write(compact({'id':row['id'],'split':row['split'],'family':row['family'],**row['kinematic_evidence']})+'\n');stream.flush()
            if len(reviewed)%50==0:print(compact({'reviewed':len(reviewed),'total':len(candidates)}),flush=True)
    reviewed.sort(key=lambda r:r['id'])
    rejected=[r for r in reviewed if not r['kinematic_evidence']['accepted']]
    write_rows(output/'rejected.jsonl',rejected)
    accepted={split:[r for r in reviewed if r['split']==split and r['kinematic_evidence']['accepted']]
              for split in ('train','evaluation','test','recovery-probe')}
    for split,rows in accepted.items():write_rows(output/(split+'.jsonl'),rows)
    (output/'regression-evaluation.jsonl').write_bytes((base/'regression-evaluation.jsonl').read_bytes())
    system,tools=extend_contract((base/'system.txt').read_text(),json.loads((base/'tools.json').read_text()))
    (output/'system.txt').write_text(system);(output/'tools.json').write_text(compact(tools)+'\n')
    overlap={}
    for left,right in (('train','evaluation'),('train','test'),('evaluation','test')):
        overlap[left+'_'+right]={'queries':len({r['query'] for r in accepted[left]}&{r['query'] for r in accepted[right]}),
                                'motion_structures':len({motion_structure(r['answers']) for r in accepted[left]}&{motion_structure(r['answers']) for r in accepted[right]})}
    manifest={'version':'8-reviewed-faces','parent_manifest_sha256':digest(base/'manifest.json'),
              'generator_sha256':digest(Path(__file__)),'face_source_sha256':digest(FACE_SOURCE),
              'compiler_sha256':digest(Path(__file__).with_name('kinematics.py')),
              'replay_sha256':digest(Path(__file__).with_name('challenge.py')),
              'splits':{k:len(v) for k,v in accepted.items()},'regression_rows':len(read_rows(output/'regression-evaluation.jsonl')),
              'audit':{'candidates':len(candidates),'accepted':len(reviewed)-len(rejected),'rejected':len(rejected),
                       'rejected_by_split':dict(Counter(r['split'] for r in rejected))},
              'face_vocabulary':len(available_faces()),'training_rows_with_faces':sum(any(a['name']=='face' for a in r['answers']) for r in accepted['train']),
              'recorded_corrections':[{k:r.get(k) for k in ('id','job_id','request_evidence_id','review_evidence_ids','correction_note')}
                                      for r in accepted['train'] if r.get('observation_origin')=='recorded_robot'],
              'overlap':overlap,'physical_trials':0,
              'limits':['All corrections are unexecuted proposals; no physical-success labels inferred from replay.',
                        'The retained regression fold is unchanged historical data, not freshly qualified current-compiler trajectories.',
                        'Face assignments are offline teacher choices; runtime has no request-keyword mapping.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(compact(manifest),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','output','stand-file','spans-file','database'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--workers',type=int,default=8);a=p.parse_args()
    build(a.base,a.output,a.stand_file,a.spans_file,a.database,a.workers)
