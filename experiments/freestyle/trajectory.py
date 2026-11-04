"""Compile generated joint curves for the body's existing cubic player.

No motion names, robot transport or independent playback scheduler. Cubic and
distance-clock mathematics come from the native motion compiler.
"""
import bisect
import importlib.util
import math
from functools import lru_cache

from .runtime import JOINTS


@lru_cache(maxsize=1)
def native_compiler():
    from .kinematics import ROOT
    spec=importlib.util.spec_from_file_location('ainekio_curve_math',ROOT/'tools/compile_clips.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def track_sample(track,seconds,times=None):
    """A scalar Hermite track in seconds, model degrees and degrees/second."""
    i=max(0,min(len(track)-2,bisect.bisect_right(times if times is not None else [p[0] for p in track],seconds)-1))
    a,b=track[i],track[i+1]
    dt=b[0]-a[0];u=(seconds-a[0])/dt
    c=native_compiler().polynomial(a[1],b[1],a[2],b[2],dt)
    return native_compiler().evaluate(c,u),((3*c[0]*u+2*c[1])*u+c[2])/dt


def compile_trajectory(action,observation,planned=None):
    args=action['arguments'];joints=args['joints'];tracks=args['tracks']
    if not joints or len(joints)!=len(tracks) or len(set(joints))!=len(joints):
        raise ValueError('Each trajectory joint needs one distinct cubic track')
    duration=None
    for track in tracks:
        if len(track)<2 or any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in track):
            raise ValueError('Curve knots are [seconds, model degrees, degrees/second]')
        if track[0][0]!=0 or any(a[0]>=b[0] for a,b in zip(track,track[1:])):
            raise ValueError('Curve knot times start at zero and increase')
        if duration is not None and duration!=track[-1][0]:
            raise ValueError('Coordinated tracks share their final knot time')
        duration=track[-1][0]
    checkpoints=sorted(set([0.,duration,*args['checkpoints_s']]))
    holds=args['holds_s']
    if any(not math.isfinite(t) or not 0<=t<=duration for t in checkpoints):
        raise ValueError('A checkpoint must be within the trajectory')
    if any(len(p)!=2 or not all(math.isfinite(t) for t in p) or not 0<=p[0]<p[1]<=duration for p in holds):
        raise ValueError('Hold intervals must be within the trajectory')
    times=sorted(set([t for track in tracks for t,_,_ in track]+checkpoints+[t for p in holds for t in p]))
    start = dict(planned) if planned is not None else {
        j:(v.get('commanded_model_deg') if v.get('commanded_model_deg') is not None else v.get('model_deg'))
        for j,v in observation['joints'].items()}
    positions=[];velocities=[]
    track_times=[[p[0] for p in track] for track in tracks]
    for t in times:
        p=dict(start);v=dict.fromkeys(JOINTS,0.)
        for j,track,ticks in zip(joints,tracks,track_times):p[j],v[j]=track_sample(track,t,ticks)
        positions.append([p[j]*100 for j in JOINTS])
        velocities.append([v[j]*100 for j in JOINTS])
    clock=native_compiler().travel_clock(positions,list(range(len(times))),velocities,holds,times=times)
    attitude=args.get('expected_up',[])
    for i,p in enumerate(attitude):
        if (len(p)!=2 or not math.isfinite(p[0]) or not 0<=p[0]<=duration or
            (i and p[0]<=attitude[i-1][0]) or len(p[1])!=3 or
            not all(math.isfinite(v) for v in p[1]) or not max(abs(v) for v in p[1])):
            raise ValueError('Expected body-up references are ordered [seconds, nonzero XYZ vectors], or [] for unknown')
    if attitude and (attitude[0][0]!=0 or attitude[-1][0]!=duration):
        raise ValueError('Expected body-up references cover the complete trajectory')
    taper=args['taper_deg'];speed=observation['joint_speed_limit_deg_s']*args['speed_pct']/100
    if not math.isfinite(speed) or speed<=0 or not math.isfinite(taper) or not 0<=taper<=clock[-1][1]:
        raise ValueError('Curve speed must be positive and deceleration distance within its travel')
    return {'curve':{'times':times,'positions':positions,'velocities':velocities,'clock':clock,
                     'checkpoints':checkpoints,'expected_up':attitude,'taper':taper,'speed_deg_s':speed},
            'start':start,'end':dict(zip(JOINTS,[v/100 for v in positions[-1]])),
            'home':{j:v.get('home_deg') for j,v in observation['joints'].items()},'moving':list(joints)}
