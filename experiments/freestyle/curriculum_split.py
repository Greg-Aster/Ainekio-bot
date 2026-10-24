"""Keep shared motion structures and task compositions in one offline fold.

This operates on already-audited examples. It does not change a motion target.
"""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from .challenge import digest, read_rows, write_rows
from .curriculum import signature, summarize, audit
from .kinematics import ROOT


def motion_structure(program):
    """Ordered operations, limb relations, directions, repetitions; no timing.

    Canonical left/right reflection prevents mirrored copies crossing folds.
    This is a structural leakage check, not a claim of semantic equivalence.
    """
    def direction(value): return 1 if value>1e-5 else -1 if value < -1e-5 else 0
    def name(value, mirror):
        return value.replace('left','SIDE').replace('right','left').replace('SIDE','right') if mirror else value
    def build(mirror):
        out=[]
        for action in program:
            operation=action['name']; a=action['arguments']; item={'name':operation}
            for key in ('joint','joints','legs'):
                if key in a:
                    item[key]=[name(v,mirror) for v in a[key]] if isinstance(a[key],list) else name(a[key],mirror)
            for key in ('reference','command','cycles'):
                if key in a:item[key]=a[key]
            for key in ('offsets_mm','foot_offsets_mm'):
                if key in a:
                    item[key]=[[direction(v)*(-1 if mirror and i==1 else 1) for i,v in enumerate(p)] for p in a[key]]
            for key in ('translation_mm','rotation_deg'):
                if key in a:
                    flip=(1,) if key=='translation_mm' else (0,2)
                    item[key]=[direction(v)*(-1 if mirror and i in flip else 1) for i,v in enumerate(a[key])]
            # Keep the authored reference convention; angular direction is not
            # interpreted as a Cartesian direction or inferred from PWM.
            if 'angle_deg' in a:item['angle_direction']=direction(a['angle_deg'])
            if 'angles_deg' in a:item['angle_directions']=[direction(v) for v in a['angles_deg']]
            if 'legs' in item:
                field='offsets_mm' if 'offsets_mm' in item else 'foot_offsets_mm'
                pairs=sorted(zip(item['legs'],item.get(field,[])))
                item['legs']=[leg for leg,_ in pairs]
                item[field]=[offset for _,offset in pairs]
            if 'joints' in item and 'angle_directions' in item:
                pairs=sorted(zip(item['joints'],item['angle_directions']))
                item['joints']=[joint for joint,_ in pairs]
                item['angle_directions']=[direction for _,direction in pairs]
            out.append(item)
        return json.dumps(out, sort_keys=True, separators=(',',':'))
    return signature(min(build(False),build(True)))


def isolate(rows):
    """Union groups before assignment so transitive copies cannot leak."""
    parent={}
    def root(key):
        parent.setdefault(key,key)
        while parent[key]!=key:
            parent[key]=parent[parent[key]];key=parent[key]
        return key
    def join(a,b):parent[root(a)]=root(b)
    result=copy.deepcopy(rows)
    for row in result:
        row['motion_structure_sha256']=motion_structure(row['answers'])
        group=row.get('composition_group',row.get('episode_group',row['id']))
        # Feedback counterfactuals belong together even when the last result
        # changed the action direction. This is the scenario, not the answer.
        if row['family'] in ('recovery_slip','recovery_tipped'):
            group=':'.join(group.split(':')[:-1])
        row['split_group']=group
        join('group:'+group,'structure:'+row['motion_structure_sha256'])
    anchored={root('group:'+r['split_group']) for r in result
              if r.get('rehearsal') or r['family'].startswith('recovery_') or len(r.get('task_families',[]))==1}
    component_members={}
    for row in result:
        component_members.setdefault(root('group:'+row['split_group']),set()).add(row['split_group'])
    for row in result:
        component=root('group:'+row['split_group'])
        identity=signature(sorted(component_members[component]))
        bucket=int(identity[:8],16)%10
        row['split']='train' if component in anchored else 'evaluation' if bucket==0 else 'test' if bucket==1 else 'train'
        row['split_component_sha256']=identity
    return result


def retain_named_gaits(rows, source_rows):
    commands=lambda items:{a['arguments']['command'] for r in items for a in r['answers'] if a['name']=='gait'}
    missing=commands(source_rows)-commands(rows)
    added=[]
    for original in sorted(source_rows,key=lambda r:r['id']):
        if len(original['answers'])!=1 or original['answers'][0]['name']!='gait':continue
        command=original['answers'][0]['arguments']['command']
        if command not in missing:continue
        row=copy.deepcopy(original);row.update(rehearsal=True,split='train',synthetic=True,physical_qualification=False)
        _,evidence=audit(row);row['kinematic_evidence']=evidence
        if evidence['accepted']:
            rows.append(row);added.append(row['id']);missing.remove(command)
    return {'retained_commands':sorted(commands(rows)),'missing_commands':sorted(missing),'added_rows':added}


def finalize(source, output, recovery=None, rehearsal_source=None):
    output.mkdir(parents=True,exist_ok=False)
    originals=[r for split in ('train','evaluation','test') for r in read_rows(source/(split+'.jsonl'))]
    for row in originals:
        if row['family'] in ('open_task','open_composition'):
            row['teacher']='agent-authored Cartesian task templates, generated deterministically'
    replaced_recovery_rows=sum(r['family'].startswith('recovery_') for r in originals) if recovery else 0
    probes=[]
    if recovery:
        originals=[r for r in originals if not r['family'].startswith('recovery_')]
        originals.extend(read_rows(recovery/'train.jsonl'))
        probes=read_rows(recovery/'recovery-probe.jsonl')
        write_rows(output/'recovery-probe.jsonl',probes)
    gait_retention=retain_named_gaits(originals,read_rows(rehearsal_source/'train.jsonl')) if rehearsal_source else None
    rows=isolate(originals)
    splits={split:[r for r in rows if r['split']==split] for split in ('train','evaluation','test')}
    for split,items in splits.items():write_rows(output/(split+'.jsonl'),items)
    for filename in ('system.txt','tools.json','regression-evaluation.jsonl'):
        (output/filename).write_bytes((source/filename).read_bytes())
    overlap={}
    for left,right in (('train','evaluation'),('train','test'),('evaluation','test')):
        fields=('query','composition_group','motion_structure_sha256','split_component_sha256')
        overlap[left+'_'+right]={field:len({r[field] for r in splits[left] if field in r}&{r[field] for r in splits[right] if field in r}) for field in fields}
        overlap[left+'_'+right]['exact_programs']=len({signature(r['answers']) for r in splits[left]}&{signature(r['answers']) for r in splits[right]})
    audit_manifest=json.loads((source/'manifest.json').read_text())
    rejected=read_rows(source/'rejected.jsonl')
    def failure_kind(row):
        evidence=row['kinematic_evidence'];error=evidence.get('error') or ''
        if 'no converged IK solution' in error:return 'unconverged_ik'
        if evidence.get('max_endpoint_error_mm',0)>=.15:return 'endpoint_tolerance'
        if evidence.get('max_linear_path_error_mm',0)>=.15:return 'path_tolerance'
        if evidence.get('max_action_duration_error_s',0)>=.002:return 'duration_mismatch'
        return evidence['status']
    expected=set(t for r in read_rows(source/'candidates.jsonl') for t in r.get('task_families',[]))
    represented=set(t for r in rows for t in r.get('task_families',[]))
    manifest={'version':8,'audit_dataset':str(source),'audit_manifest_sha256':digest(source/'manifest.json'),
              'splitter_sha256':digest(Path(__file__)),'splits':{k:summarize(v) for k,v in splits.items()},
              'overlap':overlap,'recovery':dict(Counter(r['family'] for r in rows if r['family'].startswith('recovery_'))),
              'unrepresented_new_tasks':sorted(expected-represented),
              'recovery_grounding_manifest_sha256':digest(recovery/'manifest.json') if recovery else None,
              'native_gait_retention':gait_retention,
              'rehearsal_source_sha256':digest(rehearsal_source/'train.jsonl') if rehearsal_source else None,
              'recovery_probe':{'rows':len(probes),'queries_shared_with_training':len({r['query'] for r in probes}&{r['query'] for r in splits['train']}),
                                'motion_structures_shared_with_training':len({motion_structure(r['answers']) for r in probes}&{r['motion_structure_sha256'] for r in splits['train']}),
                                'scope':'New feedback/pose combinations, not unseen motion structure or physical recovery.'},
              'supporting_source_sha256':{str(p):digest(p) for p in [Path(__file__).with_name('kinematics.py'),
                  Path(__file__).with_name('program.py'),Path(__file__).with_name('challenge.py'),ROOT/'geometry.json']},
              'synthetic':True,'physical_trials':0,'motion_target_program_changes':0,
              'original_audit_summary':audit_manifest['audit'],
              'replaced_original_recovery_rows':replaced_recovery_rows,
              'final_accepted_rows':len(rows),'separate_recovery_probe_rows':len(probes),
              'final_evidence':dict(Counter(r['kinematic_evidence']['proof'] for r in rows)),
              'rejections':{'total':len(rejected),'taxonomy':dict(Counter(failure_kind(r) for r in rejected)),
                            'task_membership':dict(Counter(t for r in rejected for t in r.get('task_families',[])))},
              'limits':audit_manifest['limits']+[
                  'No overlap of ordered normalized motion structures across the three folds.',
                  'Primitive tasks, recovery episodes and retained source/rehearsal targets stay in training; new compositions are grouped before assignment.',
                  'Main folds measure new compositions; the separate recovery probe measures unseen sensor/pose combinations and allows shared action structures.',
                  'Task-level geometry checks qualify authored demonstrations; exact-reference scoring alone is not an open-ended model success metric.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--recovery',type=Path)
    p.add_argument('--rehearsal-source',type=Path)
    a=p.parse_args();finalize(a.source,a.output,a.recovery,a.rehearsal_source)
