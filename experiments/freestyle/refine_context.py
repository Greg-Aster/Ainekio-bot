"""Train the compact contract with Body Control-shaped observations throughout.

All states are constructed, not captured recovery demonstrations. Existing
motion targets retain their provenance; no runtime routing or limits change.
"""
import argparse
import copy
import hashlib
import json
import math
import random
from pathlib import Path

from compact import call, move, sha
from recovery import quaternion, request_text
from refine import POSTURES, SYSTEM as PREVIOUS_SYSTEM, TOOLS, records as previous_records
from runtime import JOINTS, compact
from natural_language import records as language_records

SYSTEM = PREVIOUS_SYSTEM.split(' Tools:')[0] + (
    ' The request is the new goal; observation.action and imu.motion describe previous or current execution, not a new instruction.'
    ' Preserve the requested gesture when unrelated telemetry or a previous gait is present.'
    ' joint_speed_limit_deg_s is degrees per second, not speed_pct. speed_pct=50 means half that rate.'
    ' Use the requested percentage; for new joint movements without a requested speed use 50 percent.'
    ' Never copy a degrees-per-second number into a percent field.'
    ' Robot left and right use the named physical joint map. Then means sequential; together means simultaneous.'
    ' Interpret a reported jam using measured progress and recent free travel. Do not resume walking merely because an old action was walk.'
    ' A fall correction requires evidence about the effect of the previous correction; do not assume a successful recovery.'
    ' Tools: ' + compact(TOOLS))


def observation(rng):
    """Same field names/nesting as Bridge.observation, with varied numeric data."""
    timestamp = rng.randrange(1000000, 800000000)
    old = rng.choice(['wave', 'sit', 'walk', 'motion_plan', 'neutral'])
    joints = {}
    for index, joint in enumerate(JOINTS):
        home = [0, -30.87, -117.68][index % 3] + rng.choice([0, -1.25, 2.5])
        measured = round(home + rng.uniform(-18, 18), 5)
        commanded = round(measured + rng.uniform(-.8, .8), 5)
        joints[joint] = {'home_deg':home, 'commanded_model_deg':commanded,
                         'model_deg':measured, 'calibrated':True, 'in_calibrated_range':True,
                         'command_us':rng.randrange(400, 2800), 'velocity_deg_s':round(rng.uniform(-.2,.2),5)}
    imu = {'boot_id':rng.randrange(100000,999999), 'timestamp_us':timestamp, 'age_us':rng.randrange(100,4000),
           'accepted_samples':rng.randrange(1000,100000), 'rejected_samples':0,'gap_restarts':0,
           'available':True,'fresh':True,'startup':False,'calibration_applied':True,
           'gyro_recovery':False,'acceleration_recovery':False,'accelerometer_ignored':False,
           'frame':'body_nominal','orientation_wxyz':quaternion(rng.uniform(-6,6),rng.uniform(-6,6)),
           'acceleration_m_s2':[.1,.2,9.8],'angular_rate_rad_s':[.001,-.002,.001],
           'acquisition':{'io_errors':0,'no_data_polls':10000},
           'motion':{'command':old,'activity':'freestyle' if old=='motion_plan' else old,
                     'phase':'hold','sequence':rng.randrange(1,100),'connection':2,
                     'started_us':timestamp-20000,'sampled_us':timestamp,'expected_up':None},
           'face_token':'','received_at':'2026-10-21T00:00:00+00:00'}
    return {'epoch':2,'joints':joints,'imu':imu,'expected_up':None,
            'feedback':{'device_us':timestamp,'scan_us':1500,'enabled':True,'stalled_joints':0,'no_progress_ms':0},
            'joint_speed_limit_deg_s':rng.choice([90,180,360,720,1500,2000]),
            'action':{'t':'intent','name':old,'args':{'speed':200,'steps':0},'seq':9,'epoch':2},
            'model':'v2-12servo'}


def row(family, request, answers, obs=None, event=None, history=None, **metadata):
    query=request_text(request,obs,event,history)
    digest=hashlib.sha256(compact([query,answers]).encode()).hexdigest()
    return {'id':digest[:16],'family':family,'query':query,'answers':answers,
            'source_id':'context-synthetic:'+digest,'source_hash':digest,
            'evidence':'constructed state and program; no physical qualification',**metadata}


def expand_recovery(source, rng):
    value=json.loads(source['query']); obs=observation(rng)
    special=value['observation']
    for joint, data in special.get('joints',{}).items():obs['joints'][joint].update(data)
    obs['imu'].update(special.get('imu',{}))
    obs.update({k:v for k,v in special.items() if k not in ('joints','imu')})
    kind=source['family']
    if kind.startswith('jam'):
        obs['feedback']['stalled_joints']=sum(1<<JOINTS.index(j) for j in value['event']['joints'])
        obs['feedback']['no_progress_ms']=900
    return row(kind,value['request'],source['answers'],obs,value['event'],value['history'])


def leg_targets(model_root):
    """Use the authored Wave lift; right-side mirroring remains synthetic."""
    source=model_root/'motions/gestures/wave/source.json'
    data=json.loads(source.read_text())
    lifted=data['samples'][round(1.6*120)]['actuator_angles_rad'][2]
    down=data['samples'][round(1.2*120)]['actuator_angles_rad'][2]
    targets={}
    for side in ('left','right'):
        sign=1 if side=='left' else -1
        targets[side]={name:[round(math.degrees(a)*(sign if i==0 else 1),2) for i,a in enumerate(values)]
                       for name,values in [('lift',lifted),('down',down)]}
    return targets,sha(source)


def records(split, model_root):
    rng=random.Random({'train':3401,'evaluation':3402,'test':3403}[split])
    rows=[]
    original=previous_records(split)
    for index, source in enumerate(original):
        if source['query'].startswith('{'):
            rows.append(expand_recovery(source,rng))
            # Retain partial-observation clients as well as complete snapshots.
            if index%3==0:rows.append(copy.deepcopy(source))
        else:
            rows.append(row(source['family'],source['query'],source['answers'],observation(rng)))
            if index%4==0:rows.append(copy.deepcopy(source))

    # Terse real requests and stale actions must not be learned only as plain text.
    templates={'train':['{}','{} please','please {}','can you {}','{} now'],
               'evaluation':['would you {} now'], 'test':['{} for me now']}[split]
    names={name:[name.replace('_',' ')] for name in POSTURES}
    names['wave'] += ['wave hello','say hello with a wave','give me a wave']
    names['lay_down'] += ['go to sleep','lie down','lay down']
    names['dance'] += ['do a dance','dance for me']
    for name,phrases in names.items():
        for phrase in phrases:
            for template in templates:
                for variant in range(2 if split=='train' else 1):
                    obs=observation(rng)
                    obs['action']={'t':'intent','name':rng.choice(['walk','sit','wave']),
                                   'args':{'speed':200,'steps':0},'seq':12,'epoch':2}
                    rows.append(row('natural_gesture',template.format(phrase),[call('gesture',name=name)],obs))

    # Paired natural recovery commands: same request, different measured obstruction.
    recovery_rows=[r for r in original if r['family'] in ('jam_backoff','jam_smaller_wave','fall_correction','slip_correction')]
    for source in recovery_rows:
        value=json.loads(expand_recovery(source,rng)['query']); kind=source['family']
        if kind=='jam_smaller_wave':
            text={'train':['wave','wave hello','finish waving hello'],
                  'evaluation':['continue the greeting'], 'test':['finish the wave for me']}[split]
        elif kind=='jam_backoff':
            backoff=abs(source['answers'][0]['arguments']['angle_deg']-
                        next(iter(json.loads(source['query'])['observation']['joints'].values()))['model_deg'])
            text=[f'Back away from the jam by {backoff:g} degrees.']
        else:
            text={'train':['Recover from the fall using what the last correction did.',
                           'Correct my tilt using the feedback from that last adjustment.'],
                  'evaluation':['Use that last adjustment to recover my balance.'],
                  'test':['Recover my posture based on whether the last movement helped.']}[split]
        # Natural jam variants retain supplied free range/cycles/speed as evidence.
        rows.append(row('natural_'+kind,rng.choice(text),source['answers'],value['observation'],value['event'],value['history']))

    # Explicit unit contrasts include high percentages when actually requested.
    for i in range({'train':160,'evaluation':20,'test':24}[split]):
        j=rng.choice(JOINTS); speed=rng.choice([25,50,75,100,150,200]); angle=rng.choice([8,12,16,24])
        obs=observation(rng); obs['joint_speed_limit_deg_s']=rng.choice([2000,1500,720])
        phrase=({'train':'Move {j} {a} degrees from home at {s}% speed.',
                 'evaluation':'At {s} percent, shift {j} {a} degrees from home.',
                 'test':'Use {s}% travel speed to offset {j} by {a} degrees relative to home.'}[split])
        rows.append(row('speed_units',phrase.format(j=j.replace('_',' '),a=angle,s=speed),[move(j,angle,'home',speed)],obs))

    targets,source_hash=leg_targets(model_root)
    for i in range({'train':180,'evaluation':24,'test':32}[split]):
        order=rng.sample(['left','right'],2); both=bool(i%3==0); return_first=bool(i%3==1)
        speed=rng.choice([25,50,75]); hold=rng.choice([1,2,3])
        obs=observation(rng); obs['action']={'t':'intent','name':'sit','seq':7,'epoch':2}
        for side in order:
            for axis,value in zip(('shoulder','carrier','crank'),targets[side]['down']):
                obs['joints'][f'front_{side}_{axis}'].update(home_deg=0,model_deg=value,commanded_model_deg=value)
        def pose(side,which='lift'):
            return call('pose',joints=[f'front_{side}_{axis}' for axis in ('shoulder','carrier','crank')],
                        angles_deg=targets[side][which],reference='absolute',speed_pct=speed)
        verb={'train':rng.choice(['Lift','Raise','Pick up']), 'evaluation':'Elevate','test':'Lift up'}[split]
        if i%5==0:
            speed=50
            text=f'{verb} the {order[0]} front leg.'
            actions=[pose(order[0])]
        elif i%5==1:
            speed=50
            text=f'{verb} the {order[0]} then the {order[1]} front leg.'
            actions=[pose(order[0]),pose(order[1])]
        elif both:
            text=f'{verb} both front legs together while seated at {speed}% speed.'
            actions=[call('pose',joints=[j for side in order for j in pose(side)['arguments']['joints']],
                          angles_deg=[a for side in order for a in targets[side]['lift']],reference='absolute',speed_pct=speed)]
        else:
            text=f'{verb} the {order[0]} front leg, hold {hold} seconds, '+('put it back, ' if return_first else '')+f'then lift the {order[1]} front leg. Stay seated and use {speed}% speed.'
            actions=[pose(order[0]),call('hold',seconds=hold)]+([pose(order[0],'down')] if return_first else [])+[pose(order[1])]
        rows.append(row('natural_leg_sequence',text,actions,obs,source_motion_sha256=source_hash,
                        physical_qualification=False,teacher='Wave lift sample; right-side geometric mirror unqualified'))
    for family,text,answers in language_records(split):
        for _ in range(2 if split=='train' else 1):
            rows.append(row(family,text,answers,observation(rng)))
        if split=='train':rows.append(row(family,text,answers))
    # Deduplicate exact inputs; never silently retain contradictory targets.
    unique={}
    for value in rows:
        if value['query'] in unique and unique[value['query']]['answers']!=value['answers']:
            raise ValueError('Contradictory targets')
        unique[value['query']]=value
    rows=list(unique.values());rng.shuffle(rows)
    return rows


def export(destination, model_root):
    destination.mkdir(parents=True,exist_ok=False)
    data={split:records(split,model_root) for split in ('train','evaluation','test')}
    # Distinct observations alone are not held-out language: audit both separately.
    queries=[{r['query'] for r in rows} for rows in data.values()]
    assert not queries[0]&queries[1] and not queries[0]&queries[2] and not queries[1]&queries[2]
    for split,rows in data.items():
        (destination/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in rows))
    benchmark=[]
    for family in sorted({r['family'] for r in data['test']}):
        benchmark += [r for r in data['test'] if r['family']==family][:4]
    (destination/'benchmark.jsonl').write_text(''.join(compact(r)+'\n' for r in benchmark))
    (destination/'system.txt').write_text(SYSTEM)
    (destination/'tools.json').write_text(compact(TOOLS)+'\n')
    report={'generator_sha256':sha(__file__),'source_generator_sha256':sha(Path(__file__).with_name('refine.py')),
            'language_generator_sha256':sha(Path(__file__).with_name('natural_language.py')),
            'recovery_generator_sha256':sha(Path(__file__).with_name('recovery.py')),
            'splits':{s:len(v) for s,v in data.items()},'benchmark_count':len(benchmark),
            'synthetic':True,'measured_recovery_examples':0,
            'split_policy':'held-out request templates and numeric states; some terse request strings intentionally recur across different states',
            'input_contract':'Bridge.observation-shaped complete snapshots, plus partial observations and plain requests',
            'files':{p.name:sha(p) for p in destination.iterdir() if p.is_file()}}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-root',type=Path,default=Path('Slave/software/models/v2-12servo'))
    a=p.parse_args();print(compact(export(a.output,a.model_root)))
