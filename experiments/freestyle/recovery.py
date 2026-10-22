"""Synthetic observation-conditioned correction examples, not robot demonstrations.

The teacher computes numerical targets from supplied histories. It does not
claim that an untested pose can right a real robot or infer contact from ADC.
"""
import hashlib
import math
import random

from compact import call, move
from runtime import JOINTS, compact


def request_text(request, observation=None, event=None, history=None):
    if observation is None and event is None and not history:
        return request
    return compact({'request': request, 'event': event, 'observation': observation,
                    'history': history or []})


def quaternion(roll, pitch=0):
    r, p = math.radians(roll)/2, math.radians(pitch)/2
    return [round(v, 6) for v in (math.cos(r)*math.cos(p), math.sin(r)*math.cos(p),
                                 math.cos(r)*math.sin(p), -math.sin(r)*math.sin(p))]


def records(split):
    rng = random.Random({'train':2401, 'evaluation':2402, 'test':2403}[split])
    count = {'train':128, 'evaluation':16, 'test':24}[split]
    offsets = {'train':[8,12,16,20,24], 'evaluation':[11,17], 'test':[13,19,23]}[split]
    rows = []

    def add(family, request, observation, event, history, answers):
        query = request_text(request, observation, event, history)
        digest = hashlib.sha256(compact([query, answers]).encode()).hexdigest()
        rows.append({'id':digest[:16], 'family':family, 'query':query, 'answers':answers,
                     'source_id':'synthetic:'+digest, 'source_hash':digest,
                     'evidence':'constructed feedback history; no physical recovery qualification'})

    for i in range(count):
        joint = rng.choice(JOINTS)
        direction = rng.choice([-1,1]); gap = rng.choice(offsets)
        measured = rng.choice([-30,-15,0,15,30]); target = measured+direction*gap
        backoff = rng.choice([4,6,8]); speed = rng.choice([25,50,75])
        original = {'name':'wave','remaining_cycles':rng.choice([2,3,4]), 'period_s':rng.choice([1,1.5,2])}
        # Explicitly measured free-side excursion, not a guessed mechanical limit.
        free = measured-direction*(2*backoff)
        observation = {'joints':{joint:{'model_deg':measured, 'commanded_model_deg':target,
                           'calibrated':True, 'sampled_us':3000000}},
                       'imu':{'available':True,'orientation_wxyz':quaternion(0)},
                       'action':original, 'speed_pct':speed}
        history = [{'time_us':1000000,'joints':{joint:free}},
                   {'time_us':2000000,'joints':{joint:measured},'target_deg':target},
                   {'time_us':3000000,'joints':{joint:measured},'target_deg':target}]
        request = ('Finish the greeting with a smaller wave in the recently traversed free range; '
                   'back off to its midpoint, then use half that free range as the amplitude. '
                   'Keep the remaining cycles and period, then reassess.')
        add('jam_smaller_wave',request,observation,{'type':'servo_stall','joints':[joint]},history,
            [move(joint,measured-direction*backoff,'absolute',speed),
             call('oscillate',joint=joint,amplitude_deg=backoff,cycles=original['remaining_cycles'],period_s=original['period_s']),
             call('reassess')])
        # General obstruction: compute a reversal from measured position/history.
        add('jam_backoff',f'Clear the obstruction by retreating {backoff} degrees opposite the blocked travel direction, then reassess.',
            observation,{'type':'servo_stall','joints':[joint]},history,
            [move(joint,measured-direction*backoff,'absolute',speed),call('reassess')])

        # Recoveries use the measured effect of a preceding correction. This is
        # supervision for feedback reasoning, not a fabricated universal get-up.
        joint2 = rng.choice([j for j in JOINTS if j != joint])
        delta = rng.choice(offsets)*direction
        improved = bool(i%2)
        event_type = 'slip' if i%3==0 else 'fallen'
        side = rng.choice(['left','right','nose','tail','inverted'])
        before = rng.choice([12,18,24]) if event_type=='slip' else (170 if side=='inverted' else rng.choice([65,80,95]))
        after = before-6 if improved else before+6
        sign = -1 if side in ('right','tail') else 1
        def imu(angle):
            return {'available':True,'fresh':True,'timestamp_us':3000000,
                    'orientation_wxyz':quaternion(sign*angle if side not in ('nose','tail') else 0,
                                                  sign*angle if side in ('nose','tail') else 0),
                    'angular_rate_rad_s':[0,0,0]}
        correction = {joint:delta,joint2:-delta}
        obs = {'joints':{joint:{'model_deg':measured},joint2:{'model_deg':-measured}},
               'imu':imu(after),'expected_up':[0,0,1],'speed_pct':speed,
               'action':{'command':'walk','speed_pct':50,'remaining_cycles':3}}
        hist = [{'imu':imu(before),'correction_delta_deg':correction}, {'imu':imu(after)}]
        answers = [call('pose',joints=[joint,joint2],angles_deg=[delta if improved else -delta,-delta if improved else delta],
                        reference='current',speed_pct=speed),call('reassess')]
        add('slip_correction' if event_type=='slip' else 'fall_correction',
            'Use the previous correction and measured body orientation: repeat its joint deltas if it brought the body closer to upright; reverse them if it made the tilt worse. Then reassess.',
            obs,{'type':event_type},hist,answers)

        add('recovery_resume','The recovery has restored the intended upright posture and the joints track their targets. Complete the remaining requested walking cycles.',
            {'imu':imu(0),'joints':{joint:{'model_deg':measured,'commanded_model_deg':measured}},
             'action':{'command':'walk','speed_pct':speed,'remaining_cycles':gap}},
            {'type':'reassess'},hist,[call('gait',command='walk',speed_pct=speed,cycles=gap)])

        # Free-form compositions not represented by a named gesture call.
        add('novel_sequence',f'Invent a two-joint greeting: send {joint} {gap} degrees from its current angle while {joint2} moves {-gap} degrees, hold 1 second, wiggle {joint} twice with amplitude {backoff} and period 1.5 seconds, then move both to calibrated home at {speed}% speed. Use {speed}% for the opening pose too.',
            None,None,[],[call('pose',joints=[joint,joint2],angles_deg=[gap,-gap],reference='current',speed_pct=speed),
                         call('hold',seconds=1),call('oscillate',joint=joint,amplitude_deg=backoff,cycles=2,period_s=1.5),
                         call('pose',joints=[joint,joint2],angles_deg=[0,0],reference='home',speed_pct=speed)])
    return rows
