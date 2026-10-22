"""Curated English motion meanings and compositions for the training exporter.

These are teacher interpretations, not a claim to cover every English request
or to have physically tested new combinations. No runtime keyword dispatcher.
"""
from compact import call


# Five training phrasings, one development phrasing, one held-out phrasing.
MEANINGS = {
    'wave': ['greet someone','say hello with your hand','give a friendly greeting','wave goodbye to me','give a little salute', 'welcome me with a wave','send me off with a goodbye wave'],
    'sit': ['take a seat','sit yourself down','sit on your haunches','get into a seated position','sit and stay there', 'settle into sitting','assume your sitting posture'],
    'stand': ['get up onto your feet','stand tall','get back on all fours','rise to standing','wake up and stand', 'come up to standing','get yourself standing again'],
    'lay_down': ['go to sleep','lie down on the floor','settle down for a nap','get ready for bed','lie flat and rest', 'curl up for bedtime','lower yourself for a nap on the floor'],
    'rest': ['take a rest','relax in your resting pose','settle into your rest position','have a rest','assume your rest posture', 'take your usual resting posture','ease into your resting position'],
    'crouch': ['crouch down','get low without lying down','squat down','make yourself short','duck down', 'lower into a squat','hunker down above the floor'],
    'neutral': ['return to neutral','take your neutral pose','reset to your neutral posture','go back to neutral','assume neutral', 'use your neutral stance','return your body to its neutral posture'],
    'dance': ['do a happy dance','dance to the music','show off your dance moves','bust a move','do a little dance', 'put on a dance for me','show me your dancing routine'],
    'swim': ['pretend to swim','paddle as if in water','do a swimming stroke','act like you are swimming','swim through imaginary water', 'demonstrate your swimming strokes','mime swimming across a pool'],
    'point': ['point ahead','point with your arm','show me your pointing pose','reach out to point','indicate something ahead', 'make a pointing gesture','extend an arm in a pointing motion'],
    'nod': ['nod yes','show that you agree','give an affirmative nod','say yes with your body','nod in agreement', 'signal agreement with a nod','give me a yes nod'],
    'shake': ['shake yourself','shake your body','give yourself a shake','shake it off','do a body shake', 'give a little body shake','show a shaking motion'],
    'shrug': ['shrug your shoulders','show that you do not know','give an uncertain shrug','act unsure with a shrug','make an I do not know gesture', 'shrug to show uncertainty','answer with an unsure shoulder shrug'],
    'bow': ['take a bow','bow politely','give a respectful bow','bow to your audience','make a courteous bow', 'acknowledge me with a bow','finish with a graceful bow'],
    'celebrate': ['celebrate','show your excitement','we won celebrate','do a victory celebration','act delighted', 'show me a victory celebration','express how excited you are that we won'],
    'stretch': ['stretch out','have a stretch','stretch your legs','loosen up with a stretch','do a full body stretch', 'give yourself a good stretch','stretch out after resting'],
    'curious': ['look curious','look around inquisitively','investigate your surroundings with your body','act curious','show curiosity', 'make a curious looking-around motion','look about as though something caught your interest'],
    'surprised': ['act surprised','show me a startled reaction','look astonished','react with surprise','show a surprised motion', 'make a surprised reaction','act as though something surprised you'],
    'sad': ['look sad','act disappointed','show sadness','make a sad gesture','look dejected', 'express disappointment with your body','act as though you feel down'],
    'cute': ['act cute','make a cute pose','look adorable','do something cute','show your cute side', 'give me an adorable pose','make your sweetest cute gesture'],
    'dead': ['play dead','pretend to be dead','do your play dead act','act lifeless','show the play dead pose', 'perform your pretend-dead trick','pretend you have fallen dead'],
    'pushup': ['do a pushup','show me a push up','exercise with a pushup','perform a push-up','do your pushup exercise', 'demonstrate a pushup','give me one complete push-up motion'],
    'worm': ['do the worm','perform the worm dance','show your worm move','dance like a worm','do your worm routine', 'demonstrate the worm motion','show me the worm dance move'],
    'freaky': ['act freaky','do your freaky dance','show your freaky move','perform the freaky routine','make the freaky gesture', 'demonstrate your freaky motion','give me your freaky performance'],
    'upright': ['take the upright pose','do your upright posture','assume the upright pose','show the upright pose','use the upright posture', 'demonstrate your upright posture','show me the named upright pose'],
}


def phrasing(split, values):
    return values[:5] if split=='train' else values[5:6] if split=='evaluation' else values[6:7]


def records(split):
    examples=[]
    for name,phrases in MEANINGS.items():
        for text in phrasing(split,phrases):
            examples.append(('everyday_motion',text,[call('gesture',name=name)]))
    # Intent combinations are learned as ordered programs, not as new library IDs.
    recipes=[
        ('wake up and stretch',['stand','stretch']),
        ('greet me and take a bow',['wave','bow']),
        ('celebrate our win with a dance',['celebrate','dance']),
        ('stretch then settle down for sleep',['stretch','lay_down']),
        ('look around then point ahead',['curious','point']),
        ('act surprised then celebrate',['surprised','celebrate']),
        ('nod in agreement then take a seat',['nod','sit']),
        ('give a cute greeting',['cute','wave']),
        ('dance and finish with a bow',['dance','bow']),
        ('do a pushup then stretch',['pushup','stretch']),
        ('shrug then look around curiously',['shrug','curious']),
        ('play dead then get back onto your feet',['dead','stand']),
        ('say goodbye with a wave then lie down',['wave','lay_down']),
        ('look disappointed then take a rest',['sad','rest']),
        ('stand up and greet someone',['stand','wave']),
        ('bow then sit down',['bow','sit']),
        ('pretend to swim then shake yourself off',['swim','shake']),
        ('crouch then stand tall',['crouch','stand']),
        ('show your worm dance then celebrate',['worm','celebrate']),
        ('point ahead then nod yes',['point','nod']),
    ]
    wrappers={'train':['Please {}.','Can you {}?','I would like you to {}.'],
              'evaluation':['For me, {}.'], 'test':['Your next task is to {}.']}[split]
    for text,names in recipes:
        for wrapper in wrappers:
            examples.append(('everyday_sequence',wrapper.format(text),[call('gesture',name=n) for n in names]))
    # Preserve requested repetitions and pauses across different named motions.
    names=['wave','dance','bow','nod','shrug','stretch','pushup','shake','swim','celebrate']
    for name in names:
        for count in ([2,3,4] if split=='train' else [5] if split=='evaluation' else [6]):
            hold=2 if split=='train' else 1.5 if split=='evaluation' else 3
            text=({'train':'Do {n} complete {m} motions, pausing {h} seconds between them.',
                   'evaluation':'Repeat {m} {n} times with a {h}-second pause between repeats.',
                   'test':'Show {m} {n} times in a row; hold still for {h} seconds between each one.'}[split]).format(n=count,m=name,h=hold)
            actions=[]
            for i in range(count):
                if i:actions.append(call('hold',seconds=hold))
                actions.append(call('gesture',name=name))
            examples.append(('everyday_repetition',text,actions))
    # Locomotion is requested explicitly, never inferred from an old status action.
    locomotion=[
        ('walk','walk forward','move ahead'),('backward','back up','move backwards'),
        ('left','turn left','rotate left'),('right','turn right','rotate right'),
        ('crab','sidestep left','move sideways to your left'),
        ('crab_right','sidestep right','move sideways to your right'),
        ('crawl','crawl forward','creep forwards'),('run','run forward','run ahead')]
    for command,phrase,alternative in locomotion:
        words=phrase if split=='train' else alternative
        for cycles in ([1,2,3] if split=='train' else [4] if split=='evaluation' else [5]):
            text=f'{words.capitalize()} for {cycles} cycles, then stop moving.'
            examples.append(('everyday_locomotion',text,[call('gait',command=command,speed_pct=150 if command=='run' else 50,cycles=cycles),call('stop')]))
    return examples
