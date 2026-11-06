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


def standing_pose(speed_pct=50):
    return {'name':'pose','arguments':{'joints':list(JOINTS),
        'angles_deg':list(STAND.values()),'reference':'absolute','speed_pct':speed_pct}}


def compact_speed(percent, base_speed):
    """Drop decimal digits that do not change the compiler's wire rate."""
    wire = lambda value: max(1, round((base_speed*value/100)*100))
    expected = wire(percent)
    for digits in range(7):
        candidate = round(percent, digits)
        if candidate > 0 and wire(candidate) == expected:
            return int(candidate) if digits == 0 else candidate
    return percent


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
        args['speed_pct']=compact_speed(round(100*travel/seconds/base_speed,6),base_speed)
        return action,goal
    if name=='oscillate' and 'period_s' in args:
        period=args.pop('period_s')
        if period<=0:raise ValueError('Nonpositive legacy oscillation period')
        args['speed_pct']=compact_speed(round(400*abs(args['amplitude_deg'])/period/base_speed,6),base_speed)
        return action,positions
    if name in ('move','pose'):
        frames=list(targets_for(action,positions,home,base_speed))
        goal=dict(zip(JOINTS,[x/100 for x in frames[-1][1]]))
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


def compact_row(row, previous_tools):
    """Replace the retired curve teacher and encode compact speed/taper targets."""
    from .semantic_teachers import stretch_program
    old=ProgramEncoding(previous_tools);new=ProgramEncoding(CONTRACT)
    result=copy.deepcopy(row)
    program=old.decode(row['answers'])
    if any(action['name']=='trajectory' for action in program):
        if row.get('family')!='legacy_asset_stretch':
            raise ValueError('Curve needs an authored compact replacement: '+row['id'])
        program=stretch_program()
        for key in ('source_alignment','canonical_source_motion_sha256','legacy_motion',
                    'review','review_evidence_id','expected_final_angles_deg','expected_final_model_deg',
                    'kinematic_evidence','motion_structure_sha256'):
            result.pop(key,None)
        result.update(physical_qualification=False,synthetic=True,
                      qualification_basis='owner_requested_compact_stretch_not_physically_reviewed',
                      teacher='compact crouch, front-limb extension, holds and standing finish')
    def context(value):
        if isinstance(value,list):
            if value and isinstance(value[0],str) and value[0] in old.tools:
                action=old.decode([value])[0]
                if action['name']=='trajectory':
                    raise ValueError('Historical curve context needs explicit attribution: '+row['id'])
                return new.encode([action])[0]
            return [context(item) for item in value]
        if isinstance(value,dict):
            if set(value)=={'name','arguments'} and value['name'] in old.tools:
                action=copy.deepcopy(value)
                if action['name']=='trajectory':
                    raise ValueError('Historical curve context needs explicit attribution: '+row['id'])
                if action['name'] in ('move','pose','oscillate','body','feet'):
                    action['arguments'].setdefault('taper_deg',0)
                return action
            return {key:context(item) for key,item in value.items()}
        return value
    query=json.loads(row['query'])
    result.update(query=compact(context(query)),answers=new.encode(program))
    if result['answers']==row['answers'] and json.loads(result['query'])==query:
        return copy.deepcopy(row)
    result['source_hash']=hashlib.sha256(compact([result['query'],result['answers']]).encode()).hexdigest()
    result['source_id']='compact-targets:'+row['id']+':'+result['source_hash'][:16]
    result['migrated_source_hash']=row['source_hash']
    return result


def compact_library(database, output):
    """Explicit offline contract migration; preserve edits and discarded IDs."""
    import io
    import zipfile
    from .motion_library import MotionLibrary
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    library=MotionLibrary(database)
    before=sqlite3.connect(output/'library-before.sqlite')
    with library.connect() as db:
        db.backup(before)
    before.close()
    with library.connect() as db,db:
        db.execute('BEGIN IMMEDIATE')
        tools=library.tools(db)
        originals=db.execute('SELECT id,revision,payload FROM examples ORDER BY id').fetchall()
        converted=[compact_row(json.loads(item['payload']),tools) for item in originals]
        for item,row in zip(originals,converted):
            if row==json.loads(item['payload']):continue
            revision=item['revision']+1
            row['library_revision']=revision
            db.execute('UPDATE examples SET revision=?,payload=? WHERE id=?',(revision,compact(row),item['id']))
            db.execute('DELETE FROM revisions WHERE id=?',(item['id'],))
            db.execute('INSERT INTO revisions VALUES (?,?,?)',(item['id'],revision,compact(row)))
        for item in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'file:%.jsonl'").fetchall():
            rows=[compact_row(json.loads(line),tools) for line in item['value'].splitlines() if line.strip()]
            db.execute('UPDATE metadata SET value=? WHERE key=?',(''.join(compact(row)+'\n' for row in rows),item['key']))
        db.execute("UPDATE metadata SET value=? WHERE key='tools'",(compact(CONTRACT),))
    # Use the established export owner, including its frozen held-out files.
    with zipfile.ZipFile(io.BytesIO(library.export())) as archive:
        archive.extractall(output)
    dataset=output/'dataset'
    report={'version':FORMAT,'source':'Body Control editable motion library',
            'training_rows':len(converted),'converted_rows':len(converted),
            'removed_model_operation':'trajectory','physical_trials':0,
            'system_prompt_tokens':0,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in dataset.iterdir() if p.is_file() and p.name!='manifest.json'}}
    # Keep the export owner's discarded-ID record in the snapshot manifest.
    report['discarded_examples']=json.loads((dataset/'manifest.json').read_text()).get('discarded_examples',[])
    (dataset/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'migration.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--compact',action='store_true')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    report=(compact_library(args.database,args.output) if args.compact else
            build(args.database,args.output,args.workers))
    print(compact({k:v for k,v in report.items() if k!='discarded_examples'}))
