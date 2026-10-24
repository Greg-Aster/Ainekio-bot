"""Ground synthetic recovery observations and reserve an independent probe.

The probe measures new sensor/pose combinations, not unseen motion structure or
physical recovery. No model, robot, or production setting is changed here.
"""
import argparse
import copy
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .challenge import digest, write_rows
from .curriculum import audit, example, recovery_examples
from .kinematics import ROOT
from .runtime import JOINTS


def grounded_examples():
    source = json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
    def pose_at(t):
        sample = min(source['samples'], key=lambda s:abs(s['time_s']-t))
        return [round(math.degrees(q), 4) for leg in sample['actuator_angles_rad'] for q in leg]
    seated, extended = pose_at(1.2), pose_at(2.0)
    for original in recovery_examples():
        q = json.loads(original['query']); state=q['observation']; program=copy.deepcopy(original['answers'])
        group=original['episode_group']
        if original['family']=='recovery_wave':
            _, side, span, direction=group.split(':')
            limb='front_'+side; joint=limb+'_shoulder'
            before=state['joints'][joint]['model_deg']-int(direction)*int(span)
            current=dict(zip(JOINTS,seated))
            current.update({limb+'_'+axis:v for axis,v in zip(('shoulder','carrier','crank'),extended[6:9])})
            shift=current[joint]-before
            commanded=state['joints'][joint]['commanded_model_deg']+shift
            measured=state['joints'][joint]['model_deg']+shift
            for name,value in current.items():
                state['joints'][name].update(model_deg=value,commanded_model_deg=value)
            state['joints'][joint].update(model_deg=measured,commanded_model_deg=commanded)
            for entry in q['history']:
                entry['joints'][joint]+=shift;entry['target_deg']+=shift
            program[0]['arguments']['angle_deg']+=shift
            probe=int(span)==20
            scope='synthetic obstruction during the authored extended wave pose; feedback is synthetic and outcome unknown'
        else:
            probe=group.split(':')[1]=='rest'
            if original['family']=='recovery_tipped':
                q['request']=q['request'].replace('fall onto my side','fall away from upright')
            scope=original['evidence_scope']
        row=example(q['request'],state,program,original['family'],event=q['event'],history=q['history'],
                    split='recovery-probe' if probe else 'train',episode_group=group,
                    evidence_scope=scope,teacher='authored feedback episode with source-pose grounding',
                    source_wave_sha256=digest(ROOT/'motions/gestures/wave/source.json'),
                    parent_candidate_id=original['id'])
        yield row


def build(output, workers=4):
    output.mkdir(parents=True,exist_ok=False)
    accepted=[];rejected=[];audits=[]
    with ProcessPoolExecutor(workers) as pool:
        for row,evidence in pool.map(audit,grounded_examples()):
            row['kinematic_evidence']=evidence;audits.append(evidence)
            (accepted if evidence['accepted'] else rejected).append(row)
    for split in ('train','recovery-probe'):
        write_rows(output/(split+'.jsonl'),[r for r in accepted if r['split']==split])
    write_rows(output/'rejected.jsonl',rejected);write_rows(output/'audit.jsonl',audits)
    manifest={'generator_sha256':digest(Path(__file__)),'total':len(audits),'accepted':len(accepted),
              'training':sum(r['split']=='train' for r in accepted),'probe':sum(r['split']=='recovery-probe' for r in accepted),
              'rejected':len(rejected),'synthetic':True,'physical_trials':0,
              'scope':'Probe holds out span-20 wave feedback and rest-pose tilt episodes; action structures may overlap training. It is not physical recovery qualification.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--workers',type=int,default=4);a=p.parse_args();build(a.output,a.workers)
