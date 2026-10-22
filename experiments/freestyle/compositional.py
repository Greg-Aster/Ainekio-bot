"""Open spatial/joint program training; named motions are demonstrations only.

The program space is continuous and compositional. This exporter samples it;
its language examples are neither a runtime dictionary nor a capability list.
"""
import argparse
import copy
import hashlib
import json
import math
import random
from pathlib import Path

from compact import call, sha
from motion_space import TOOLS, INSTRUCTIONS, LEGS
from recovery import request_text, records as recovery_records
from refine import records as joint_records
from runtime import JOINTS, compact
from training_states import observation

SYSTEM=INSTRUCTIONS+' Tools: '+compact(TOOLS)
AXES={'forward':[1,0,0],'backward':[-1,0,0],'left':[0,1,0],'right':[0,-1,0],'up':[0,0,1],'down':[0,0,-1]}


def record(family,text,answers,obs=None,event=None,history=None,**meta):
    query=request_text(text,obs,event,history)
    digest=hashlib.sha256(compact([query,answers]).encode()).hexdigest()
    return {'id':digest[:16],'family':family,'query':query,'answers':answers,
            'source_id':'compositional:'+digest,'source_hash':digest,'synthetic':True,
            'physical_qualification':False,**meta}


def feet(legs,offsets,seconds):return call('feet',legs=legs,offsets_mm=offsets,seconds=seconds)
def body(translation=(0,0,0),rotation=(0,0,0),seconds=1):
    return call('body',translation_mm=list(translation),rotation_deg=list(rotation),legs=[],foot_offsets_mm=[],seconds=seconds)
def vector(direction,distance):return [v*distance for v in AXES[direction]]


def spatial_step(rng,split):
    distance=rng.choice({'train':[4,8,12,16,20],'evaluation':[6,14],'test':[7,11,17]}[split])
    seconds=rng.choice([.5,1,1.5,2]);direction=rng.choice(list(AXES));leg=rng.choice(LEGS)
    label=leg.replace('_',' ');offset=vector(direction,distance)
    template={'train':rng.choice(['Move the {leg} foot {d} mm {dir} over {s} seconds',
                                  'Send your {leg} foot {d} millimetres {dir} in {s} seconds',
                                  'Shift the {leg} foot {dir} by {d} mm, taking {s} seconds']),
              'evaluation':'Translate the {leg} foot {d} mm toward {dir} during {s} seconds',
              'test':'Over {s} seconds, displace your {leg} foot {d} millimetres {dir}'}[split]
    return template.format(leg=label,d=distance,dir=direction,s=seconds),feet([leg],[offset],seconds)


def geometric_records(split):
    rng=random.Random({'train':4501,'evaluation':4502,'test':4503}[split])
    n={'train':360,'evaluation':40,'test':48}[split];rows=[]
    def add(family,text,actions,obs=None):
        rows.append(record(family,text,actions,observation(rng) if obs is None else obs))
    for i in range(n):
        text,action=spatial_step(rng,split)
        add('spatial_foot',text+'.',[action])
        # Generated combinations span sides, directions, order and independent timing.
        parts=[];actions=[]
        for _ in range(rng.choice([2,3,4])):
            t,a=spatial_step(rng,split);parts.append(t);actions.append(a)
        add('spatial_sequence',('; then ' if split!='test' else '. Afterwards, ').join(parts)+'.',actions)
        other=rng.choice([l for l in LEGS if l!=action['arguments']['legs'][0]])
        second=rng.choice(list(AXES));amount=rng.choice([5,10,15]);seconds=action['arguments']['seconds']
        add('spatial_coordination',text+f' and simultaneously move the {other.replace("_"," ")} foot {amount} mm {second}.',
            [feet(action['arguments']['legs']+[other],action['arguments']['offsets_mm']+[vector(second,amount)],seconds)])
        axes=rng.choice(list(AXES));distance=rng.choice([3,5,8,10]);seconds=rng.choice([.5,1,2])
        add('spatial_body',f'Move your body {distance} mm {axes} over {seconds} seconds while keeping the foot reference points fixed.',
            [body(vector(axes,distance),seconds=seconds)])
        axis=rng.randrange(3);degrees=rng.choice([-6,-3,3,6]);rotation=[0,0,0];rotation[axis]=degrees
        add('spatial_rotation',f'Rotate your body {degrees} degrees about its {"XYZ"[axis]} axis over {seconds} seconds, holding the foot reference points.',
            [body(rotation=rotation,seconds=seconds)])
        translation=vector(axes,distance)
        leg=action['arguments']['legs'][0];delta=action['arguments']['offsets_mm'][0]
        add('spatial_whole_body',f'Together over {seconds} seconds: shift the body {distance} mm {axes}, rotate it {degrees} degrees about {"XYZ"[axis]}, and shift the {leg.replace("_"," ")} foot by {delta} mm in XYZ.',
            [call('body',translation_mm=translation,rotation_deg=rotation,legs=[leg],foot_offsets_mm=[delta],seconds=seconds)])

    # Everyday physical verbs map to coordinates, not to library identifiers.
    for i in range(n):
        side=rng.choice(['left','right']);leg='front_'+side;other='front_'+('left' if side=='right' else 'right')
        height=rng.choice([8,12,16]);seconds=rng.choice([.5,1,1.5]);pause=rng.choice([.5,1,2])
        verb={'train':rng.choice(['Raise','Lift','Pick up']), 'evaluation':'Bring up','test':'Lift up'}[split]
        noun=rng.choice(['hand','front foot','arm'])
        kind=i%6
        if kind==0:
            text=f'{verb} your {side} {noun} {height} mm in {seconds} seconds.'
            actions=[feet([leg],[[0,0,height]],seconds)]
        elif kind==1:
            text=f'{verb} your {side} hand, then your other hand, each by {height} mm over {seconds} seconds.'
            actions=[feet([leg],[[0,0,height]],seconds),feet([other],[[0,0,height]],seconds)]
        elif kind==2:
            text=f'{verb} both hands together {height} mm in {seconds} seconds.'
            actions=[feet(['front_left','front_right'],[[0,0,height]]*2,seconds)]
        elif kind==3:
            text=f'{verb} your {side} hand {height} mm, hold for {pause} seconds, then put it back. Each movement takes {seconds} seconds.'
            actions=[feet([leg],[[0,0,height]],seconds),call('hold',seconds=pause),feet([leg],[[0,0,-height]],seconds)]
        elif kind==4:
            text=f'Reach forward with the {side} hand by {height} mm and retract it; spend {seconds} seconds on each part.'
            actions=[feet([leg],[[height,0,0]],seconds),feet([leg],[[-height,0,0]],seconds)]
        else:
            text=f'Spread both hands outward by {height} mm each, then bring them back together. Each part lasts {seconds} seconds.'
            actions=[feet(['front_left','front_right'],[[0,height,0],[0,-height,0]],seconds),feet(['front_left','front_right'],[[0,-height,0],[0,height,0]],seconds)]
        add('spatial_language',text,actions)
        if i%6==0:
            add('open_ended_lift',f'{verb} your {side} {noun}.',[feet([leg],[[0,0,12]],1)])

    # Paths and rhythms are synthesized coordinates; no circle/dance identifiers.
    for i in range({'train':120,'evaluation':16,'test':24}[split]):
        leg=rng.choice(LEGS);radius=rng.choice([4,6,8]);seconds=rng.choice([.4,.6,1]);cycles=rng.choice([1,2,3])
        shape=rng.choice(['square','triangle']);plane=rng.choice(['XY','XZ','YZ'])
        a,b=['XYZ'.index(v) for v in plane]
        vertices=([(0,0),(radius,0),(radius,radius),(0,radius),(0,0)] if shape=='square' else [(0,0),(radius,0),(0,radius),(0,0)])
        actions=[]
        for _ in range(cycles):
            for p,q in zip(vertices,vertices[1:]):
                delta=[0,0,0];delta[a]=q[0]-p[0];delta[b]=q[1]-p[1]
                actions.append(feet([leg],[delta],seconds))
        text=f'Trace a {shape} with the {leg.replace("_"," ")} foot in the {plane} plane, starting along positive {plane[0]}. Use {radius} mm sides on those axes, {seconds} seconds per edge, and repeat {cycles} times.'
        add('generated_path',text,actions)
        # Whole-body rhythmic compositions also retain the exact number of returns.
        amount=rng.choice([3,5,7]);hold=rng.choice([.25,.5,1]);actions=[]
        for _ in range(cycles):
            actions += [body([0,amount,0],seconds=seconds),call('hold',seconds=hold),body([0,-2*amount,0],seconds=seconds),body([0,amount,0],seconds=seconds)]
        add('generated_rhythm',f'Rock your body left and right {cycles} times, {amount} mm to each side of the starting position. Take {seconds} seconds for each move, pause {hold} seconds at the left side, and return to centre after each cycle.',actions)
    return rows


def wave_demonstrations(model_root,split):
    """An authored full Wave teaches a generated program; it is never looked up at execution."""
    import numpy as np
    from scipy.spatial.transform import Rotation
    import importlib.util
    spec=importlib.util.spec_from_file_location('wave_kinematic_teacher',model_root/'motions/walk/reference.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=module.Mechanism(json.loads((model_root/'geometry.json').read_text()))
    source_path=model_root/'motions/gestures/wave/source.json';source=json.loads(source_path.read_text())
    times=[0,1.2,1.6,2,4,4.4,4.8,6,6.2];program=[]
    cad=['FL','FR','RL','RR'];physical=list(LEGS)
    for start,end in zip(times,times[1:]):
        if start==2:
            program.append(call('oscillate',joint='front_left_shoulder',amplitude_deg=42,cycles=3,period_s=round(2/3,6)));continue
        a=source['samples'][round(start*120)];b=source['samples'][round(end*120)]
        if start==6:program.append(call('hold',seconds=.2));continue
        ra=Rotation.from_euler('xyz',a['body_rotation_euler_xyz_rad']);rb=Rotation.from_euler('xyz',b['body_rotation_euler_xyz_rad'])
        translation=ra.inv().apply(np.array(b['body_translation_world_mm'])-a['body_translation_world_mm'])
        rotation=(ra.inv()*rb).as_euler('xyz',degrees=True)
        offsets=[]
        for index,leg in enumerate(cad):
            model.body_euler=np.array(a['body_rotation_euler_xyz_rad'])
            pa=model.reference(leg,np.array(a['actuator_angles_rad'][index]),np.array(a['body_translation_world_mm']))
            model.body_euler=np.array(b['body_rotation_euler_xyz_rad'])
            pb=model.reference(leg,np.array(b['actuator_angles_rad'][index]),np.array(b['body_translation_world_mm']))
            offsets.append([round(float(v),3) for v in ra.inv().apply(pb-pa)])
        program.append(call('body',translation_mm=[round(float(v),3) for v in translation],
                            rotation_deg=[round(float(v),3) for v in rotation],legs=physical,
                            foot_offsets_mm=offsets,seconds=round(end-start,3)))
    rng=random.Random({'train':4601,'evaluation':4602,'test':4603}[split]);rows=[]
    phrases={'train':['wave','wave hello','wave goodbye','give a friendly wave','greet me with your left hand'],
             'evaluation':['give me a greeting wave'], 'test':['make a waving motion to say hello']}[split]
    for phrase in phrases:
        for i in range(8 if split=='train' else 2):
            obs=observation(rng)
            for j,q in zip(JOINTS,[math.degrees(q) for leg in source['samples'][0]['actuator_angles_rad'] for q in leg]):
                obs['joints'][j].update(model_deg=round(q,5),commanded_model_deg=round(q,5))
            rows.append(record('generated_wave_demonstration',phrase,copy.deepcopy(program),obs,
                               teacher='Authored Wave phase geometry plus three shoulder cycles',source_motion_sha256=sha(source_path)))
    return rows


def records(split,model_root):
    rows=geometric_records(split)+wave_demonstrations(model_root,split)
    rng=random.Random({'train':4701,'evaluation':4702,'test':4703}[split])
    counts={}
    for original in joint_records(split):
        if any(a['name']=='gesture' for a in original['answers']):continue
        family=original['family'];counts[family]=counts.get(family,0)+1
        if counts[family] > (80 if split=='train' else 12):continue
        if original['query'].startswith('{'):
            value=json.loads(original['query']);obs=observation(rng);special=value['observation'] or {}
            for j,v in special.get('joints',{}).items():obs['joints'][j].update(v)
            obs['imu'].update(special.get('imu',{}));obs.update({k:v for k,v in special.items() if k not in ('joints','imu')})
            rows.append(record(family,value['request'],original['answers'],obs,value['event'],value['history']))
        else:
            rows.append(record(family,original['query'],original['answers'],observation(rng)))
    rng.shuffle(rows)
    return list({r['query']:r for r in rows}.values())


def export(destination,model_root):
    destination.mkdir(parents=True,exist_ok=False)
    data={s:records(s,model_root) for s in ('train','evaluation','test')}
    queries=[{r['query'] for r in rows} for rows in data.values()]
    assert not queries[0]&queries[1] and not queries[0]&queries[2] and not queries[1]&queries[2]
    for split,rows in data.items():
        (destination/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in rows))
    benchmark=[]
    for family in sorted({r['family'] for r in data['test']}):
        benchmark += [r for r in data['test'] if r['family']==family][:4]
    (destination/'benchmark.jsonl').write_text(''.join(compact(r)+'\n' for r in benchmark))
    (destination/'system.txt').write_text(SYSTEM);(destination/'tools.json').write_text(compact(TOOLS)+'\n')
    report={'splits':{s:len(v) for s,v in data.items()},'benchmark_count':len(benchmark),
            'generated_action_space':'continuous foot/body/joint motion programs; no emote identifier operation',
            'synthetic':True,'physical_trials':0,'generator_sha256':sha(__file__),
            'geometry_sha256':sha(model_root/'geometry.json'),'contract_sha256':sha(Path(__file__).with_name('motion_space.py')),
            'state_generator_sha256':sha(Path(__file__).with_name('training_states.py')),
            'limitations':['Kinematic reach is not dynamic stability, contact, collision clearance or task success.',
                           'Sampled language and motion patterns do not establish universal request understanding.',
                           'Wave is one source-derived demonstration, not a runtime lookup.'],
            'files':{p.name:sha(p) for p in destination.iterdir() if p.is_file()}}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-root',type=Path,default=Path('Slave/software/models/v2-12servo'))
    a=p.parse_args();print(compact(export(a.output,a.model_root)))
