"""Read-only shared-clock timing reference. No servo output or hardware approval.

python timing.py contracts/wave.json --profile research_candidate --scale 2 --time 3
Edit research_candidate.duration_s to explore individual phase durations.
"""
import argparse,bisect,json,math
from pathlib import Path


def build_schedule(contract,profile='demonstration',scale=1.,cycles=1,include_demo_recovery=False):
    if not math.isfinite(scale) or scale<=0:raise ValueError('scale must be positive and finite')
    if profile not in contract['timing_profiles']:raise ValueError('unknown timing profile')
    if profile=='operating':
        raise ValueError('Operating timing is uncalibrated; use research_candidate for offline evaluation')
    if type(cycles) is not int or not 1<=cycles<=contract['repeat']['maximum']:
        raise ValueError('invalid cycle count')
    durations=contract['timing_profiles'][profile]['duration_s']
    if set(durations)!={p['id'] for p in contract['phases']}:raise ValueError('phase IDs do not match')
    order=[]
    for group in ('entry','cycle','exit','clip'):
        phase_group=[p for p in contract['phases'] if p['section']==group and (include_demo_recovery or p.get('execution_role')!='optional_demonstration_recovery')]
        for cycle in range(cycles if group=='cycle' else 1):
            for phase in phase_group:order.append((phase,cycle if group=='cycle' else None))
    result=[];now=0.
    for phase,cycle in order:
        raw=durations[phase['id']]
        if type(raw) not in (float,int) or not math.isfinite(raw) or raw<=0:
            raise ValueError('every phase requires a positive finite duration')
        duration=raw/scale;lo,hi=phase['source_interval_s']
        if hi<=lo:raise ValueError('invalid source interval')
        result.append(dict(id=phase['id'],section=phase['section'],cycle=cycle,
            start_s=now,end_s=now+duration,source_start_s=lo,source_end_s=hi))
        now+=duration
    if not result:raise ValueError('empty schedule')
    # One common rate at all boundaries preserves the source's velocity matching.
    # Interior quintic warps accommodate independently edited phase durations.
    rate=min((p['source_end_s']-p['source_start_s'])/(p['end_s']-p['start_s']) for p in result)
    return dict(phases=result,duration_s=now,boundary_source_rate=rate,profile=profile,
        hardware_ready=False,retimed_geometry_validated=False)


def locate(schedule,elapsed_s):
    if not math.isfinite(elapsed_s) or elapsed_s<0:raise ValueError('time must be nonnegative and finite')
    phases=schedule['phases']
    if elapsed_s>=schedule['duration_s']:
        p=phases[-1]
        return dict(phase=p['id'],section=p['section'],cycle=p['cycle'],source_time_s=p['source_end_s'],
            source_rate=0.,source_acceleration=0.,complete=True,hardware_ready=False)
    i=bisect.bisect_right([p['end_s'] for p in phases],elapsed_s)
    p=phases[i];duration=p['end_s']-p['start_s'];length=p['source_end_s']-p['source_start_s']
    u=(elapsed_s-p['start_s'])/duration;r=schedule['boundary_source_rate'];extra=length-r*duration
    smooth=u**3*(10+u*(-15+6*u));d1=30*u*u*(1-u)**2;d2=60*u*(1-u)*(1-2*u)
    return dict(phase=p['id'],section=p['section'],cycle=p['cycle'],
        source_time_s=p['source_start_s']+r*duration*u+extra*smooth,
        source_rate=r+extra/duration*d1,source_acceleration=extra/duration**2*d2,
        complete=False,hardware_ready=False)


def event_times(schedule,source_time_s):
    """Map cues/contact events through the same monotone clock; one time per cycle."""
    events=[]
    for index,p in enumerate(schedule['phases']):
        if not (p['source_start_s']<=source_time_s<p['source_end_s'] or
                index==len(schedule['phases'])-1 and source_time_s==p['source_end_s']):continue
        lo,hi=p['start_s'],p['end_s']
        if source_time_s==p['source_start_s']:hi=lo
        else:
            for _ in range(52):
                middle=(lo+hi)/2
                if locate(schedule,middle)['source_time_s']<source_time_s:lo=middle
                else:hi=middle
        events.append((lo+hi)/2)
    return events


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('contract',type=Path)
    ap.add_argument('--profile',default='demonstration');ap.add_argument('--scale',type=float,default=1.)
    ap.add_argument('--cycles',type=int,default=1);ap.add_argument('--time',type=float,default=0.);ap.add_argument('--include-demo-recovery',action='store_true')
    a=ap.parse_args();c=json.loads(a.contract.read_text());s=build_schedule(c,a.profile,a.scale,a.cycles,a.include_demo_recovery)
    print(json.dumps(dict(command=c['command'],duration_s=s['duration_s'],sample=locate(s,a.time),
        face_cues=[dict(cue=cue,times_s=event_times(s,cue['time_s'])) for cue in c['face_cues']],
        hardware_ready=False),indent=2))
