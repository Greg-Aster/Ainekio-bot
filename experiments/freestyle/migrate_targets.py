"""Migrate the editable library to measured targets and speeds, with an audit receipt.

Conversion is offline. It never sends a robot command or launches training.
Old durations determine a nominal speed, not a completion deadline.
"""
import argparse
import copy
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
from collections import Counter

from .compact_wire import FORMAT, ProgramEncoding, model_query
from .face_contract import face_tool
from .motion_space import TOOLS
from .program import targets_for
from .runtime import JOINTS, compact

CONTRACT = [*TOOLS, face_tool()]
STAND = dict(zip(JOINTS, [0,3.46,-21.63]*4))


def joint_state(observation):
    joints = observation['joints']
    if 'ids' in joints:
        return {JOINTS[i]:{k:v[n] for k,v in joints.items() if k!='ids' and isinstance(v,list)}
                for n,i in enumerate(joints['ids'])}
    return joints


def convert_action(action, positions, home, base_speed):
    from .kinematics import target_for_spatial
    action=copy.deepcopy(action);name=action['name'];args=action['arguments']
    if name in ('feet','body') and 'seconds' in args:
        seconds=args.pop('seconds')
        if seconds<=0:raise ValueError('Nonpositive legacy movement duration')
        goal=dict(zip(JOINTS,[x/100 for x in target_for_spatial(action,positions)]))
        travel=max(abs(goal[j]-positions[j]) for j in JOINTS)
        if not travel:return {'name':'hold','arguments':{'seconds':seconds}},goal
        args['speed_pct']=round(100*travel/seconds/base_speed,6)
        return action,goal
    if name=='oscillate' and 'period_s' in args:
        period=args.pop('period_s')
        if period<=0:raise ValueError('Nonpositive legacy oscillation period')
        args['speed_pct']=round(400*abs(args['amplitude_deg'])/period/base_speed,6)
        return action,positions
    if name in ('move','pose'):
        frames=list(targets_for(action,positions,home,base_speed))
        goal=dict(zip(JOINTS,[x/100 for x in frames[-1][1]]))
        if name=='pose' and set(args['joints'])==set(JOINTS) and goal==STAND:
            return {'name':'stand','arguments':{}},goal
        return action,goal
    return action,positions


def convert_row(row):
    row=copy.deepcopy(row);query=json.loads(row['query'])
    obs=query.get('observation') or {}
    joints=joint_state(obs)
    start={j:v.get('model_deg') if v.get('model_deg') is not None else v.get('commanded_model_deg') for j,v in joints.items()}
    home={j:v['home_deg'] for j,v in joints.items()}
    speed=obs['joint_speed_limit_deg_s']
    if not speed or any(v is None for v in start.values()):raise ValueError('Missing conversion reference in '+row['id'])
    positions=dict(start);converted=[]
    for action in row['answers']:
        action,positions=convert_action(action,positions,home,speed)
        converted.append(action)
    # Context actions must use the same vocabulary as their training targets.
    def context(value):
        if isinstance(value,list):return [context(x) for x in value]
        if not isinstance(value,dict):return value
        if set(value)=={'name','arguments'}:
            return convert_action(value,start,home,speed)[0]
        return {k:context(v) for k,v in value.items()}
    encoding=ProgramEncoding(CONTRACT)
    query=model_query(context(query),encoding)
    old_hash=row['source_hash']
    row.update(query=compact(query),answers=encoding.encode(converted),
               source_id='motion-targets:'+row['id'],physical_qualification=False,
               qualification_basis='target_control_migration_not_physically_reviewed',
               migrated_source_hash=old_hash)
    for key in ('original_program','previous_kinematic_evidence','superseded_kinematic_evidence',
                'kinematic_evidence','live_trial_wall_seconds','review','repair_review'):
        row.pop(key,None)
    row['source_hash']=hashlib.sha256(compact([row['query'],row['answers']]).encode()).hexdigest()
    return row


def audit_row(row):
    try:
        return {'row':convert_row(row)}
    except (ValueError, KeyError, TypeError) as error:
        return {'error':{'id':row['id'],'family':row.get('family'),
                         'request':json.loads(row['query']).get('request'), 'reason':str(error)}}


def build(database, output, workers=4):
    from .recovery_curriculum import examples
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    with sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro',uri=True) as db:
        rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM examples ORDER BY id')]
        metadata=dict(db.execute('SELECT key,value FROM metadata'))
        discarded=[dict(zip(('id','replacement_id','reason'),r)) for r in db.execute('SELECT * FROM discarded_examples ORDER BY id')]
    old_encoding=ProgramEncoding(json.loads(metadata['tools']))
    def decode(row):
        if row['answers'] and isinstance(row['answers'][0],list):row['answers']=old_encoding.decode(row['answers'])
        return row
    counts={};hashes={};issues=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for split in ('train','evaluation','test','recovery-probe','regression-evaluation'):
            source=rows if split=='train' else [json.loads(line) for line in metadata.get('file:'+split+'.jsonl','').splitlines() if line]
            if not source:continue
            converted=[]
            for index,result in enumerate(pool.map(audit_row,map(decode,source)),1):
                if 'error' in result:
                    issues.append({'split':split,**result['error']})
                else:
                    converted.append(result['row'])
                if index%100==0:print(split,index,flush=True)
            if split in ('train', 'recovery-probe'):
                converted.extend(examples(evaluation=split=='recovery-probe'))
            path=output/(split+'.jsonl');path.write_text(''.join(compact(r)+'\n' for r in converted))
            counts[split]=len(converted);hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (output/'tools.json').write_text(compact(CONTRACT)+'\n')
    (output/'wire.json').write_text(compact({'format':FORMAT,'joint_order':JOINTS})+'\n')
    (output/'system.txt').write_text('')
    report={'format':FORMAT,'splits':counts,'files':hashes,'discarded_examples':discarded,
            'unresolved_conversion_issues':issues,
            'movement_completion':'measured_target_arrival','speed_conversion':'nominal angular travel divided by legacy duration; no timed movement execution',
            'physical_trials':0,'training_launched':False,'source_rows':len(rows)}
    report['authored_adaptive_wave_rows']={'train':24,'recovery-probe':16}
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    build(**vars(parser.parse_args()))
