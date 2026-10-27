"""V2 instruction diversity, complete V2 motion-command coverage, and fresh tests."""
import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

from compact import TOOLS as V1_TOOLS, GESTURES, call, move, sha, tool
from runtime import JOINTS, compact
from recovery import records as recovery_records

GAITS = ['walk', 'backward', 'left', 'right', 'crawl', 'run', 'crab', 'crab_right',
         'crab_forward', 'crab_backward', 'crab_turn_left', 'crab_turn_right']
POSTURES = sorted(set(GESTURES) | {'neutral'})
TOOLS = copy.deepcopy(V1_TOOLS)
TOOLS[2]['parameters']['properties']['name']['enum'] = POSTURES
TOOLS += [tool('gait', 'Call the existing P4 gait. cycles=0 means ongoing; positive cycles requests that many gait cycles.', {
    'command': {'type':'string','enum':GAITS}, 'speed_pct':{'type':'number'}, 'cycles':{'type':'integer'}}),
    tool('stop', 'Stop body motion when the user requests stopping.', {})]
SYSTEM = ('Translate the request into a JSON array of calls, each with name and arguments. '
          'Output only requested actions, in requested order. Preserve holds, repetitions, and return targets. '
          'Use move for one joint, pose for joints moving together, oscillate for repeated back-and-forth joint movement, '
          'gesture for a complete named motion, gait for existing P4 walking, and stop for an explicit stop request. '
          'A joint oscillation is not the swim gesture. Rest, lay_down, dead and crouch are distinct postures. '
          'FR/RF=front_right, FL/LF=front_left, RR=rear_right, RL=rear_left. '
          'Angles are signed model degrees. home means the caller-supplied calibrated model home. '
          'Requests may include observation, event and history. Generate new joint sequences, not just named gestures. '
          'Use calibrated model_deg and commanded_model_deg, not raw voltage as an angle or force. '
          'A stall means lack of measured progress toward a target; compare recent samples and commanded direction. '
          'For obstruction use the measured free-side range to retreat and adapt the gesture. '
          'IMU orientation_wxyz is a body quaternion; compare body-up with expected_up and the previous correction. '
          'A correction is not proof of recovery. '
          'Return calls only, without reasoning or prose. Tools: '+compact(TOOLS))

PHRASES = {
    'move': [
        'Move {j} to {a} degrees {r} at {s}% speed.',
        'Set {j} to {a} degrees {r}; speed {s} percent.',
        'Using {s}% speed, put the {j} at {a} degrees {r}.',
        'The {j} should move to {a} degrees {r}, travelling at {s} percent speed.',
        'Please adjust {j}: angle {a} degrees {r}, speed {s}%.',
        'Position {j} {a} degrees {r}, with the travel speed at {s}%.',
        'At {s} percent speed please move {j} to {a} degrees {r}.',
        'I want {j} at {a} degrees {r}. Use {s}% movement speed.',
        'Reposition {j} to {a} degrees {r}, travelling at {s}%.',
        'Make the target for {j} {a} degrees {r} and travel there at {s}% speed.',
        'Give {j} a target of {a} degrees {r}; use a travel speed of {s}%.',
        'Please place {j} at {a} degrees {r}, moving at {s} percent speed.',
    ],
    'move_hold_return': [
        'Move {j} {a} degrees from home at {s}% speed, hold {h} seconds, then return home at {s}%.',
        'Put {j} at home plus {a} degrees. Pause {h} seconds there, then bring it home. Both moves at {s}%.',
        'At {s}% speed, extend {j} {a} degrees from home; stay there {h} seconds; return home at the same speed.',
        'Make {j} move {a} degrees from home at {s}%, wait {h} seconds, and move back home at {s}%.',
        'Target {a} degrees from home on {j}, hold for {h} seconds, target home again. Speed {s}% on both legs of the trip.',
        'Move {j} away from home by {a} degrees and back, with a {h}-second pause at the outer target. Use {s}% speed both ways.',
        'Please lift {j} to home plus {a} degrees at {s}%, keep that position {h} seconds, and return it home at {s}%.',
        'For {j}: home plus {a} degrees, {h} seconds holding, then home. Travel at {s}% both ways.',
        'Take {j} to {a} degrees relative to home at {s}%; hold it for {h} seconds before returning home at {s}%.',
        'Let {j} visit home plus {a} degrees, remain there {h} seconds and return home; both journeys at {s}% speed.',
        'Use {s}% speed to send {j} {a} degrees from home, keep it there {h} seconds, then send it home at {s}%.',
        'For {j}, go from home to home plus {a} degrees, dwell {h} seconds, then return home. Keep both travels at {s}%.',
    ],
    'oscillate': [
        'Oscillate {j} {n} times, amplitude {a} degrees, period {p} seconds.',
        'Swing {j} back and forth for {n} full cycles, {a} degrees either side of its starting position, {p} seconds per cycle.',
        'Wiggle {j} through {n} cycles around its starting position. Each side is {a} degrees and each cycle takes {p} seconds.',
        'Rock {j} {n} times with a {a}-degree amplitude and a {p}-second full cycle.',
        'Make {j} go back and forth {n} times, {a} degrees each side of the starting angle, with a period of {p} seconds.',
        'Repeat a {a}-degree oscillation of {j} for {n} cycles at {p} seconds per complete cycle.',
        'I want {n} oscillations on {j}: amplitude {a} degrees, full-cycle duration {p} seconds.',
        'Wave just the {j} to either side of its current angle by {a} degrees, for {n} complete cycles of {p} seconds each.',
        'Have {j} sway {a} degrees to each side of its starting angle, completing {n} cycles, each lasting {p} seconds.',
        'Create {n} back-and-forth cycles of {j}, spanning {a} degrees each side of where it starts; one cycle takes {p} seconds.',
        'Please rock {j} around its initial angle: {n} cycles, amplitude {a} degrees, period {p} seconds.',
        'On {j}, perform a repeated swing with {a} degrees of amplitude; finish {n} full cycles lasting {p} seconds apiece.',
    ],
    'pose': [
        'Together move {j} to {a} degrees and {k} to {b} degrees, both relative to home at {s}% speed.',
        'At {s} percent speed, coordinate {j} at home plus {a} degrees with {k} at home plus {b} degrees.',
        'Move {j} and {k} simultaneously, to {a} and {b} degrees from home respectively, at {s}%.',
        'Set both joints together: {j} at home plus {a} degrees, {k} at home plus {b} degrees. Speed {s}%.',
        'Make a simultaneous pose with {j} {a} degrees from home and {k} {b} degrees from home, at {s}% speed.',
        'In one coordinated movement at {s}%, put {j} at home plus {a} degrees and {k} at home plus {b} degrees.',
        'Please move these at the same time: {j} to {a} degrees from home; {k} to {b} degrees from home. Speed {s}%.',
        'Pose {j} and {k} together at home offsets {a} and {b} degrees, respectively. Both use {s}% speed.',
        'Synchronize {j} at home plus {a} degrees and {k} at home plus {b} degrees in a single {s}%-speed move.',
        'Arrange {j} at {a} degrees relative to home and {k} at {b} degrees relative to home concurrently, using {s}% speed.',
        'Please coordinate two home-relative targets: {j} {a} degrees and {k} {b} degrees, travelling together at {s}%.',
        'Send {j} to home plus {a} degrees while simultaneously sending {k} to home plus {b} degrees, both at {s}%.',
    ],
}
ALIASES = {'front_right':['front right','front-right','FR','RF'], 'front_left':['front left','front-left','FL','LF'],
           'rear_right':['rear right','rear-right','RR'], 'rear_left':['rear left','rear-left','RL']}
NATURAL = {
    'lay_down':['go to sleep','lie down on the floor','settle down for a nap','get ready for bed'],
    'rest':['take the rest pose','rest in your resting posture','relax in the rest position'],
    'dead':['play dead','pretend to be dead','do your play-dead pose'],
    'wave':['wave hello','greet me with a wave','wave goodbye','give me a friendly wave'],
    'dance':['do a dance','dance for me','show your dance moves'],
    'point':['point with your arm','do your pointing gesture'],
    'swim':['pretend you are swimming','do the swimming gesture'],
    'crouch':['crouch down','squat above the floor'],
    'stand':['stand on all four feet','stand up normally'],
    'neutral':['return to the neutral posture','take the neutral pose'],
    'sit':['sit down','take a seat'],
    'nod':['give me a nod','nod in agreement'],
    'shrug':['shrug your shoulders','give a shrug'],
    'bow':['take a bow','bow politely'],
}


def records(split):
    rng = random.Random({'train':1401,'evaluation':1402,'test':1403}[split])
    patterns = {'train':range(8),'evaluation':range(8,10),'test':range(10,12)}[split]
    angles = {'train':[-35,-30,-25,-20,-15,-10,10,15,20,25,30,35,40],
              'evaluation':[-19,19,-27,27], 'test':[-23,23,-17,17,29,-29]}[split]
    count = {'train':384,'evaluation':48,'test':64}[split]
    result = {}

    def add(family, query, answers):
        identity = hashlib.sha256(compact([query,answers]).encode()).hexdigest()
        result[query] = {'id':identity[:16],'family':family,'query':query,'answers':answers,
                         'source_id':'synthetic:'+identity,'source_hash':identity}

    def label(j):
        leg,axis=j.rsplit('_',1)
        return rng.choice(ALIASES[leg])+' '+axis

    for family in PHRASES:
        for i in range(count):
            j,k=rng.sample(list(JOINTS),2)
            a,b=rng.sample(angles,2)
            s=rng.choice([25,50,75,100]);h=rng.choice([0.5,1,1.5,2,2.5,3,4])
            n=rng.choice([2,3,4,5,6]);p=rng.choice([0.5,1,1.5,2,2.5])
            ref=rng.choice(['home','current','absolute'])
            r={'home':'relative to home','current':'relative to the current angle','absolute':'as an absolute model angle'}[ref]
            if family=='oscillate':a=abs(a)
            text=PHRASES[family][list(patterns)[i%len(patterns)]].format(j=label(j),k=label(k),a=a,b=b,s=s,h=h,n=n,p=p,r=r)
            if family=='move':answers=[move(j,a,ref,s)]
            elif family=='move_hold_return':answers=[move(j,a,'home',s),call('hold',seconds=h),move(j,0,'home',s)]
            elif family=='oscillate':answers=[call('oscillate',joint=j,amplitude_deg=a,cycles=n,period_s=p)]
            else:answers=[call('pose',joints=[j,k],angles_deg=[a,b],reference='home',speed_pct=s)]
            add(family,text,answers)
            if i<({'train':64,'evaluation':8,'test':8}[split]):
                # Explicit sequencing examples retain every specified step.
                add('composed',text+' Then hold for 2 seconds and wave.',answers+[call('hold',seconds=2),call('gesture',name='wave')])
    wrappers={'train':['Perform {}.','Please do {}.','Show me {}.','I want to see {}.','Could you {}?','Do the complete {} motion.'],
              'evaluation':['Demonstrate {} for me.'], 'test':['I would appreciate seeing you {}.']}[split]
    for name in POSTURES:
        phrases=[w.format(name.replace('_',' ')) for w in wrappers]
        if split=='train':phrases += [p.capitalize()+'.' for p in NATURAL.get(name,[])]
        for phrase in phrases:
            add('gesture',phrase,[call('gesture',name=name)])
            h=rng.choice([1,1.5,2,2.5,3]);other=rng.choice(POSTURES)
            add('gesture_sequence',phrase+f' Hold for {h} seconds, then do {other.replace("_"," ")}.',
                [call('gesture',name=name),call('hold',seconds=h),call('gesture',name=other)])
            if split=='train':
                add('gesture_sequence',phrase+' Hold for 2 seconds and repeat the same gesture.',
                    [call('gesture',name=name),call('hold',seconds=2),call('gesture',name=name)])
    gait_words={'walk':'walk forward','backward':'walk backward','left':'turn left','right':'turn right',
                'crawl':'crawl forward','run':'run forward','crab':'crab sideways left','crab_right':'crab sideways right',
                'crab_forward':'crab forward','crab_backward':'crab backward','crab_turn_left':'turn left with the crab gait',
                'crab_turn_right':'turn right with the crab gait'}
    for name in GAITS:
        for i in range({'train':20,'evaluation':3,'test':4}[split]):
            s=rng.choice([50,75,100,150] if name=='run' else [25,50,75,100]);n=rng.choice([0,1,2,3,4,6,8,12])
            duration='continuously' if n==0 else f'for {n} gait cycles'
            pattern=rng.choice(['Please {g} {d} at {s}% speed.','At {s}% speed, {g} {d}.','Use the {c} command {d} at {s}% speed.']) if split=='train' else ('Can you {g} {d}, using {s} percent speed?' if split=='evaluation' else 'I want you to {g} {d}; travel speed {s}%.')
            add('gait',pattern.format(g=gait_words[name],d=duration,s=s,c=name),[call('gait',command=name,speed_pct=s,cycles=n)])
    stop_phrases={'train':['Stop.','Stop moving.','Halt the body movement.','Cancel the current motion.','Please stop the robot.','Stop walking now.'],
                  'evaluation':['Bring the movement to a stop.'], 'test':['Please halt the motion now.']}[split]
    for phrase in stop_phrases:add('stop',phrase,[call('stop')])
    rows=list(result.values())+recovery_records(split);rng.shuffle(rows)
    return rows


def export(destination, previous):
    destination.mkdir(parents=True,exist_ok=False)
    data={s:records(s) for s in ('train','evaluation','test')}
    # Previously inspected failures are now training material, never fresh-test evidence.
    if previous:
        old=[json.loads(l) for l in (previous/'benchmark.jsonl').read_text().splitlines()]
        seen={r['query'] for r in data['train']}
        data['train'] += [r for r in old if r['query'] not in seen]
        (destination/'regression.jsonl').write_text(''.join(compact(r)+'\n' for r in old))
    for split,rows in data.items():
        (destination/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in rows))
    benchmark=[]
    for family in sorted({r['family'] for r in data['test']}):
        benchmark += [r for r in data['test'] if r['family']==family][:10]
    (destination/'benchmark.jsonl').write_text(''.join(compact(r)+'\n' for r in benchmark))
    (destination/'system.txt').write_text(SYSTEM)
    (destination/'tools.json').write_text(compact(TOOLS)+'\n')
    report={'generator_sha256':sha(__file__),'recovery_generator_sha256':sha(Path(__file__).with_name('recovery.py')),
            'splits':{s:len(v) for s,v in data.items()},
            'benchmark_count':len(benchmark),'synthetic':True,'measured_recovery_examples':0,
            'coverage':{'gestures_and_postures':POSTURES,'gaits':GAITS,'explicit_stop':True},
            'old_benchmark_is_training_regression':bool(previous),
            'files':{p.name:sha(p) for p in destination.iterdir() if p.is_file()}}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--previous',type=Path)
    a=p.parse_args();print(compact(export(a.output,a.previous)))
