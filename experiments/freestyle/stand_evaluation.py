"""Score generated targets using the serving compiler and production native FK.

This is observation replay, not physics or proof of measured foot contact.
Reference episode timing sums actual inference calls and nominal travel; real
servo settling, transport and Q6A inference remain separately unmeasured.
"""
import argparse
import copy
import json
import math
import statistics
import subprocess
import time
import urllib.error
from collections import Counter
from pathlib import Path

import jsonschema

from .challenge import digest, read_rows, write_rows
from .generator import Generator
from .program import compile_motion, packets
from .runtime import JOINTS


def feedback_domain_evidence(targets, observation):
    """Offline observability audit, not a runtime travel restriction."""
    ranges={j:v['feedback_range_deg'] for j,v in observation.get('joints',{}).items()
            if 'feedback_range_deg' in v}
    violations=[]
    for index,target in enumerate(targets):
        for joint,(low,high) in ranges.items():
            if not low<=target[joint]<=high:
                violations.append({'target_index':index,'joint':joint,'target_deg':target[joint],
                    'feedback_range_deg':[low,high]})
    return {'known_joints':len(ranges),'outside_calibration':violations,
            'scope':'Known feedback measurement domain only; not mechanical limits or physical reachability.'}


def trajectory_evidence(generated, reference, tolerance_deg=.25):
    """Describe commanded landmarks; never equate them with physical success.

    This offline comparison deliberately exposes its angle tolerance. A valid
    alternative path may not follow the teacher's landmarks, so unmatched
    landmarks are unqualified evidence, not a runtime rejection criterion.
    """
    if not reference or 'high_stand' not in reference:
        return {'available':False}

    def error(actual, expected):
        return max(abs(a-b) for a,b in zip(actual,expected))

    high=reference['high_stand']['model_deg']
    nominal=reference['nominal_stand']['model_deg']
    high_indices=[i for i,angles in enumerate(generated) if error(angles,high)<=tolerance_deg]
    settle_indices=[i for i,angles in enumerate(generated) if error(angles,nominal)<=tolerance_deg]
    placements=[]
    stages=reference.get('stages',[])
    for i,stage in enumerate(stages):
        if stage['phase']!='place' or i==0 or i+1>=len(stages):
            continue
        lift,lower=stages[i-1],stages[i+1]
        if lift['phase']!='lift' or lower['phase']!='lower':
            continue
        leg=next(l for l in range(4) if stage['moving_joints']&(7<<(3*l)))
        start=lift['target']['feet_mm_flat'][3*leg:3*leg+2]
        end=stage['target']['feet_mm_flat'][3*leg:3*leg+2]
        distance=math.hypot(end[0]-start[0],end[1]-start[1])
        indices=[];after=-1
        for landmark in (lift,stage,lower):
            matches=[k for k,angles in enumerate(generated) if k>after and
                     error(angles,landmark['target']['model_deg'])<=tolerance_deg]
            if not matches:
                break
            after=matches[0];indices.append(after)
        placements.append({'leg':JOINTS[leg*3].removesuffix('_shoulder'),
                           'reference_translation_mm':distance,
                           'ordered_lift_place_lower_indices':indices,
                           'ordered_triplet_observed':len(indices)==3})
    return {'available':True,'reference_case':reference.get('case'),
            'comparison_tolerance_deg':tolerance_deg,
            'commanded_high_indices':high_indices,'commanded_nominal_indices':settle_indices,
            'commanded_high_then_nominal':any(h<s for h in high_indices for s in settle_indices),
            'placement_landmarks':placements,
            'scope':'Commanded target comparison in teacher geometry; not swept clearance, measured arrival, dynamics, contact, or physical success.'}


def rollout(generator, row, geometry, rounds, position_error_deg=0.):
    """Finite offline trial, self-fed idealized shafts; never robot execution."""
    query=copy.deepcopy(json.loads(row['query']));history=query['history'];obs=query['observation']
    mapping=(geometry/'mapping.txt').read_text();executable=geometry/'stand-geometry'
    calibration=json.loads((geometry/'calibration-evidence.json').read_text())['payload']['result']
    joint_mapping={JOINTS[m['id']]:m for m in calibration['joints']}
    validator=jsonschema.validators.validator_for(generator.schema)(generator.schema)
    records=[];generated_targets=[];elapsed=0.;nominal=0.;state='offline_trial_budget_exhausted'
    for turn in range(rounds):
        started=time.perf_counter()
        try:
            value=generator.generate(query['request'],obs,query.get('event'),history)
        except (ValueError,urllib.error.URLError) as error:
            elapsed+=time.perf_counter()-started
            records.append({'turn':turn,'error':str(error),'evidence':getattr(error,'evidence',None)})
            state='generation_failure';break
        elapsed+=value['elapsed_s'];program=value['program'];planned=None;again=False;fault_event=None
        entry={'turn':turn,'request':copy.deepcopy(query),'observation':copy.deepcopy(obs),
               'history':copy.deepcopy(history),**value}
        records.append(entry)
        # The bridge refreshes feedback after inference before compiling.
        obs['feedback']['device_us']=int(3000000+(nominal+elapsed)*1e6)
        obs['imu']['timestamp_us']=obs['feedback']['device_us']
        try:
            validator.validate(program)
            for index,action in enumerate(program):
                name=action['name'];args=action['arguments']
                if name=='face':continue
                before=copy.deepcopy(obs);delta=None
                if name in ('move','pose','feet','body','oscillate'):
                    compiled=compile_motion(action,obs,planned);prior=compiled['start']
                    for speed,angles in compiled['frames']:
                        planned=dict(zip(JOINTS,[a/100 for a in angles]))
                        checked=native_pose(executable,mapping,obs,planned)
                        if not checked['valid'] or not checked['in_travel']:
                            raise ValueError('Generated target failed native FK or installed travel')
                        generated_targets.append([planned[j] for j in JOINTS])
                        nominal+=max(abs(planned[j]-prior[j]) for j in JOINTS)/(speed/100)
                        prior=planned
                        measured_target={j:planned[j]+((-1 if i%2 else 1)*position_error_deg)
                                         for i,j in enumerate(JOINTS)}
                        if feedback_domain_evidence([measured_target],obs)['outside_calibration']:
                            break
                    if name in ('move','pose'):
                        delta={j:compiled['end'][j]-compiled['start'][j] for j in compiled['moving']}
                    for i,j in enumerate(JOINTS):
                        obs['joints'][j]['commanded_model_deg']=planned[j]
                        obs['joints'][j]['model_deg']=planned[j]+((-1 if i%2 else 1)*position_error_deg)
                        m=joint_mapping[j]
                        obs['joints'][j]['command_us']=round(m['home_us']+(-1 if m['invert'] else 1)*
                            (planned[j]-m['home_cd']/100)*m['us_per_degree'])
                        obs['joints'][j]['commanded_model_deg']=m['home_cd']/100+(-1 if m['invert'] else 1)*(
                            obs['joints'][j]['command_us']-m['home_us'])/m['us_per_degree']
                    # Idealized shaft motion still cannot establish measured
                    # arrival outside the supplied feedback calibration. Feed
                    # that fault back through the same model event as the body;
                    # do not pretend the rest of the program completed.
                    fault_joints=[]
                    for i,j in enumerate(JOINTS):
                        joint_sample=obs['joints'][j]
                        if 'feedback_range_deg' not in joint_sample:continue
                        low,high=joint_sample['feedback_range_deg'];angle=joint_sample['model_deg']
                        valid=low<=angle<=high
                        joint_sample.update(in_calibrated_range=valid,feedback_usable=valid,feedback_faults=[])
                        if not valid:
                            below=(angle<low) != bool(joint_mapping[j]['invert'])
                            joint_sample['feedback_faults']=['below_calibration' if below else 'above_calibration']
                            fault_joints.append({'id':i,'name':j,'reasons':joint_sample['feedback_faults']})
                    if fault_joints:
                        fault_event={'type':'servo_feedback_fault','joints':fault_joints,
                                     'outputs_released':False}
                        entry['simulated_feedback_fault']=copy.deepcopy(fault_event)
                        again=True
                    if any('feedback_range_deg' in v for v in obs['joints'].values()):
                        obs['feedback']['waiting_joints']=sum(1<<v['id'] for v in fault_joints)
                    from protocol.control_v1 import MOTION_PLAN_V2_JOINT_MAP
                    obs['action']={'t':'motion_plan','map':MOTION_PLAN_V2_JOINT_MAP,
                                   'frames':list(packets(compiled['frames']))[-1],
                                   'end':'hold','control':'targets','epoch':obs.get('epoch',1),
                                   'seq':11+len(history)//2}
                elif name=='hold':nominal+=args['seconds']
                else:raise ValueError('Operation outside this offline Stand trial: '+name)
                obs['feedback']['device_us']=int(3000000+(nominal+elapsed)*1e6)
                obs['imu']['timestamp_us']=obs['feedback']['device_us']
                def sample(value):
                    return {'time_us':value['feedback']['device_us'],
                            'joints':{j:v['model_deg'] for j,v in value['joints'].items()},
                            'imu':copy.deepcopy(value['imu'])}
                initial={**sample(before),'action':action}
                if delta is not None:initial['correction_delta_deg']=delta
                after=sample(obs)
                after['receipts']=([{'t':'done','seq':len(generated_targets),'position_verified':True}]
                    if name in ('move','pose','feet','body','oscillate') and not fault_event else [])
                history.extend([initial,after])
                if fault_event:break
            if not again:state='model_finished';break
            query['event']=fault_event
        except (ValueError,KeyError,TypeError,jsonschema.ValidationError) as error:
            entry['error']=str(error);state='offline_target_or_schema_failure';break
    native=read_rows(geometry/'native-cases.jsonl')
    stand=next(r for r in native if 'case' in r)['nominal_stand']['model_deg']
    splayed=geometry/'splayed-audit/reproducible-cases.jsonl'
    if splayed.exists():native+=read_rows(splayed)
    reference=next((r for r in native if r.get('case')==row.get('episode_id')),None)
    return {'state':state,'inference_rounds':len(records),'inference_seconds':elapsed,
            'nominal_motion_seconds':nominal,'trial_round_budget':rounds,
            'position_error_deg':position_error_deg,
            'terminal_nominal_max_error_deg':max(abs(obs['joints'][j]['model_deg']-a) for j,a in zip(JOINTS,stand)),
            'generated_targets_model_deg':generated_targets,
            'trajectory_evidence':trajectory_evidence(generated_targets,reference),
            'history_samples':len(history),'turns':records,'physical_success':None,
            'scope':'Self-fed idealized shaft observations with full history; no dynamics, swept clearance, contact, or real settling proof.'}


def native_pose(executable, mapping, observation, target):
    q = observation['imu']['orientation_wxyz']
    w, x, y, z = q
    euler = [math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y)),
             math.asin(max(-1,min(1,2*(w*y-z*x)))), math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))]
    values = [observation['joints'][j]['model_deg'] for j in JOINTS] + euler + [target[j] for j in JOINTS]
    result = subprocess.run([str(executable.resolve()), '--evaluate'],
                            input=mapping + ' '.join(map(str,values))+'\n',
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def targets(program, observation):
    planned = None;duration = 0.;compiled = []
    for action in program:
        if action['name'] == 'hold':
            duration += action['arguments']['seconds']
        elif action['name'] in ('pose','move','feet','body','oscillate'):
            value = compile_motion(action, observation, planned)
            previous = value['start']
            for speed, angles in value['frames']:
                planned = dict(zip(JOINTS,[v/100 for v in angles]))
                duration += max(abs(planned[j]-previous[j]) for j in JOINTS)/(speed/100)
                compiled.append(planned);previous = planned
    return compiled, duration


def score(data, predictions, contract, geometry, output):
    rows = {r['id']:r for r in read_rows(data)}
    schema = Generator('http://unused','offline',contract).schema
    validator=jsonschema.validators.validator_for(schema)(schema)
    mapping = (geometry/'mapping.txt').read_text()
    executable = geometry/'stand-geometry'
    native_cases=read_rows(geometry/'native-cases.jsonl')
    splayed=geometry/'splayed-audit/reproducible-cases.jsonl'
    if splayed.exists():native_cases+=read_rows(splayed)
    episodes={r['case']:r for r in native_cases if 'case' in r}
    results = []
    for prediction in read_rows(predictions):
        row = rows[prediction['id']];query=json.loads(row['query']);obs=query['observation']
        result = {'id':row['id'], 'family':row['family'], 'episode_id':row.get('episode_id'),
                  'phase':row.get('phase'), 'elapsed_s':prediction['elapsed_s'],
                  'physical_success':None, 'exact':prediction['program']==row['answers'], 'schema_valid':False}
        if 'original_contract_schema_valid' in prediction:
            result['original_contract_schema_valid']=prediction['original_contract_schema_valid']
        stage='schema'
        try:
            conversion=prediction.get('duration_migration')
            if conversion and not conversion['accepted']:
                stage='legacy_target_translation'
                result['duration_migration']=conversion
                raise ValueError(conversion.get('error',conversion.get('reason')))
            if prediction.get('generation_error'):
                stage='generation'
                raise ValueError(prediction['generation_error'])
            validator.validate(prediction['program'])
            result['schema_valid']=True;stage='generated_target_compile'
            generated, duration = targets(prediction['program'], obs)
            result['feedback_domain']=feedback_domain_evidence(generated,obs)
            stage='reference_target_compile'
            reference, _ = targets(row['answers'], obs)
            result.update(schema_valid=True, nominal_travel_and_hold_s=duration,
                          target_count=len(generated), reference_target_count=len(reference))
            for label,names in (('hold',{'hold'}),('face',{'face'}),('control',{'gait','stop','release'})):
                actual_actions=[a for a in prediction['program'] if a['name'] in names]
                reference_actions=[a for a in row['answers'] if a['name'] in names]
                result[label+'_sequence_matches']=actual_actions==reference_actions
                result['generated_'+label+'_actions']=actual_actions
                result['reference_'+label+'_actions']=reference_actions
            if generated and reference:
                stage='native_geometry'
                result['target_angle_error_deg'] = max(abs(generated[-1][j]-reference[-1][j]) for j in JOINTS)
                episode=episodes.get(row.get('episode_id'))
                if episode:
                    choices=[s['target']['model_deg'] for s in episode['stages']]+[episode['nominal_stand']['model_deg']]
                    def nearest(target):
                        return min(range(len(choices)),key=lambda i:sum((target[j]-a)**2 for j,a in zip(JOINTS,choices[i])))
                    result['expected_stage_index']=nearest(reference[-1])
                    result['generated_nearest_stage_index']=nearest(generated[-1])
                    result['stage_choice_matches']=result['expected_stage_index']==result['generated_nearest_stage_index']
                generated_native=[native_pose(executable,mapping,obs,t) for t in generated]
                reference_native=[native_pose(executable,mapping,obs,t) for t in reference]
                actual=generated_native[-1];expected=reference_native[-1]
                result['invalid_generated_native_targets']=[i for i,t in enumerate(generated_native) if not t['valid'] or not t['in_travel']]
                result['invalid_reference_native_targets']=[i for i,t in enumerate(reference_native) if not t['valid'] or not t['in_travel']]
                result['native_checked_targets']=len(generated_native)
                result['native'] = actual
                if actual['valid'] and expected['valid']:
                    result['sole_height_error_mm']=max(abs(a-b) for a,b in zip(actual['pose']['sole_height_mm'],expected['pose']['sole_height_mm']))
                    result['foot_position_error_mm']=max(abs(a-b) for a,b in zip(actual['pose']['feet_mm_flat'],expected['pose']['feet_mm_flat']))
                    result['body_height_error_mm']=abs(actual['pose']['body_mm'][2]-expected['pose']['body_mm'][2])
                result['target_matches'] = (len(generated)==len(reference) and
                    all(max(abs(a[j]-b[j]) for j in JOINTS)<=.02 for a,b in zip(generated,reference)))
            else:
                result['target_matches'] = not generated and not reference
            result['next_step_matches'] = (result['target_matches'] and result['feedback_decision_matches']
                                           and result['hold_sequence_matches'] and result['control_sequence_matches'])
        except (ValueError,KeyError,TypeError,jsonschema.ValidationError) as error:
            result.update(error_stage=stage,error=str(error),next_step_matches=False)
        results.append(result)
    write_rows(output,results)
    report={'rows':len(results),'schema_valid':sum(r['schema_valid'] for r in results),
            'next_step_matches':sum(r['next_step_matches'] for r in results),
            'hold_sequence_matches':sum(r.get('hold_sequence_matches',False) for r in results),
            'face_sequence_matches':sum(r.get('face_sequence_matches',False) for r in results),
            'control_sequence_matches':sum(r.get('control_sequence_matches',False) for r in results),
            'families':dict(Counter(r['family'] for r in results)),
            'data_sha256':digest(data),'predictions_sha256':digest(predictions),
            'native_executable_sha256':digest(executable), 'physical_trials':0,
            'timing_scope':'Observed workstation inference plus nominal joint travel; not physical elapsed completion or Q6A performance.'}
    times=sorted(r['elapsed_s'] for r in results)
    report['latency_seconds']={'mean':statistics.mean(times),'p50':statistics.median(times),
                               'p95':times[max(0,math.ceil(.95*len(times))-1)]}
    report['errors_by_stage']=dict(Counter(r['error_stage'] for r in results if 'error_stage' in r))
    report['by_family']={family:{'rows':sum(r['family']==family for r in results),
                                  'next_step_matches':sum(r['family']==family and r['next_step_matches'] for r in results),
                                  'stage_choice_matches':sum(r['family']==family and r.get('stage_choice_matches',False) for r in results)}
                         for family in report['families']}
    episodes={}
    for r in results:
        if r['episode_id'] and r['family'] in ('feedback_stand_begin','feedback_stand_arrived','feedback_stand_high','feedback_stand_settled'):
            e=episodes.setdefault(r['episode_id'],{'inference_rounds':0,'inference_seconds':0.,'nominal_motion_seconds':0.,'all_next_steps_match':True})
            e['inference_rounds']+=1;e['inference_seconds']+=r['elapsed_s']
            e['nominal_motion_seconds']+=r.get('nominal_travel_and_hold_s',0)
            e['all_next_steps_match'] &= r['next_step_matches']
    report['observed_reference_episode_replay']=episodes
    output.with_suffix('.summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('data','predictions','contract','geometry','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--endpoint')
    p.add_argument('--model',default='freestyle-qwen')
    p.add_argument('--model-file',type=Path)
    p.add_argument('--generation-contract',type=Path,
                   help='Optional original model contract for offline legacy comparisons.')
    p.add_argument('--preserve-generated-durations',action='store_true',
                   help='Preserve legacy generated durations as equivalent nominal rates for scoring; retain original program.')
    p.add_argument('--rollout-data',type=Path)
    p.add_argument('--rollout-output',type=Path)
    p.add_argument('--trial-rounds',type=int,default=24,help='Offline test budget only; never a robot execution limit.')
    p.add_argument('--position-error-deg',type=float,action='append')
    args=vars(p.parse_args());endpoint=args.pop('endpoint');model=args.pop('model')
    model_file=args.pop('model_file');rollout_data=args.pop('rollout_data');rollout_output=args.pop('rollout_output')
    generation_contract=args.pop('generation_contract') or args['contract']
    preserve_durations=args.pop('preserve_generated_durations')
    rounds=args.pop('trial_rounds');errors=args.pop('position_error_deg') or [0.]
    if endpoint:
        generator=Generator(endpoint,model,generation_contract,model_file)
        with args['predictions'].open('x') as stream:
            for row in read_rows(args['data']):
                started=time.perf_counter()
                try:
                    value=generator.generate(row['query'])
                    if preserve_durations:
                        from .speed_curriculum import migrate
                        source=dict(row,answers=value['program'])
                        migrated,evidence=migrate(source,preserve_durations=True)
                        value['original_program']=value['program']
                        value['original_contract_schema_valid']=True
                        value['duration_migration']=evidence
                        value['program']=migrated['answers'] if evidence['accepted'] else None
                except (ValueError,urllib.error.URLError) as error:
                    value={'program':None,'elapsed_s':time.perf_counter()-started,
                           'generation_error':str(error),'evidence':getattr(error,'evidence',None)}
                result={'id':row['id'],'family':row['family'],**value,'execution':'not_dispatched'}
                stream.write(json.dumps(result,separators=(',',':'))+'\n');stream.flush()
                print(json.dumps({'id':row['id'],'elapsed_s':value['elapsed_s']}),flush=True)
    score(**args)
    if rollout_data:
        if not endpoint or not rollout_output:p.error('Rollout requires endpoint and rollout-output')
        with rollout_output.open('x') as stream:
            for row in read_rows(rollout_data):
                for position_error in errors:
                    result={'id':row['id'],'generator':generator.identity,
                            **rollout(generator,row,args['geometry'],rounds,position_error)}
                    stream.write(json.dumps(result,separators=(',',':'))+'\n');stream.flush()
                    print(json.dumps({k:result[k] for k in ('id','state','inference_rounds','terminal_nominal_max_error_deg')}),flush=True)
