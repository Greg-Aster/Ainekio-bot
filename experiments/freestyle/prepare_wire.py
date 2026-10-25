"""Re-encode reviewed examples for prompt-free, generated motion programs.

Existing motion targets are retained exactly. Missing initial face labels are
balanced explicit-expression examples, never a runtime expression-selection rule.
"""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from .compact_wire import LEGACY_FORMAT as FORMAT, ProgramEncoding, model_query
from .runtime import compact, JOINTS


def build(source, contract, output):
    tools = json.loads((contract/'tools.json').read_text())
    encoding = ProgramEncoding(tools)
    output.mkdir(parents=True,exist_ok=False)
    manifest = {'version':FORMAT,'source_manifest_sha256':hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
                'converter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'encoding_sha256':hashlib.sha256(Path(__file__).with_name('compact_wire.py').read_bytes()).hexdigest(),
                'source_files':{},'splits':{},'system_prompt_tokens':0,
                'face_annotation':'Missing initial faces are distributed across the renderer vocabulary with matching explicit expression requests. Original expressive examples and all motion targets are retained.',
                'physical_trials':0,'activation':'candidate-only','operations':{},'initial_faces':{},'added_faces':{}}
    faces = next(t for t in tools if t['name']=='face')['parameters']['properties']['expr']['enum']
    for split in ('train','evaluation','test','recovery-probe','regression-evaluation'):
        path=source/(split+'.jsonl')
        if not path.exists(): continue
        manifest['source_files'][split]=hashlib.sha256(path.read_bytes()).hexdigest()
        originals=[json.loads(line) for line in path.read_text().splitlines()]
        missing=sorted((r for r in originals if r['answers'] and r['answers'][0]['name']!='face'),
                       key=lambda r:hashlib.sha256((split+':'+r['id']).encode()).hexdigest())
        expressions={r['id']:faces[i % len(faces)] for i,r in enumerate(missing)}
        rows=[]; count=0; operations=Counter(); initial_faces=Counter(); added_faces=Counter()
        for original in originals:
            row=copy.deepcopy(original)
            query=json.loads(row['query'])
            program=row['answers']
            added=bool(program and program[0]['name']!='face')
            if added:
                expression=expressions[original['id']]
                program=[{'name':'face','arguments':{'expr':expression}},*program]
                instruction=' Use the '+expression.replace('_',' ')+' face.'
                if isinstance(query,dict): query['request']=query['request'].rstrip()+instruction
                else: query=query.rstrip()+instruction
                added_faces[expression]+=1
                count+=1
            wire=encoding.encode(program)
            if encoding.decode(wire)!=program:
                raise ValueError('Motion serialization changed a target: '+row['id'])
            query=model_query(query,encoding)
            row['query']=compact(query) if not isinstance(query,str) else query
            row['answers']=wire
            row['parent_example_id']=original['id']
            row['id']=hashlib.sha256(compact([FORMAT,row['query'],wire]).encode()).hexdigest()[:16]
            row['initial_face_annotation_added']=added
            row['teacher']=row.get('teacher','retained reviewed targets')+('; authored explicit expression request and matching initial face' if added else '')
            if added: row['face_annotation']={'expression':expression,'request_explicit':True}
            operations.update(call['name'] for call in program)
            if program: initial_faces[program[0]['arguments']['expr']]+=1
            rows.append(row)
        (output/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in rows))
        manifest['splits'][split]={'rows':len(rows),'initial_face_annotations':count}
        manifest['operations'][split]=dict(operations)
        manifest['initial_faces'][split]=dict(initial_faces)
        manifest['added_faces'][split]=dict(added_faces)
    (output/'system.txt').write_text('')
    (output/'tools.json').write_bytes((contract/'tools.json').read_bytes())
    (output/'wire.json').write_text(json.dumps({'format':FORMAT,'joint_order':JOINTS},indent=2)+'\n')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','contract','output'): p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(build(**vars(p.parse_args())),indent=2))
