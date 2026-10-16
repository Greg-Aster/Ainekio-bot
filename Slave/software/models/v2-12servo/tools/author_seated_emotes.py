"""Author seated Point, rear-braced slow Pushup, and brisk Worm on bare legs.

Baselines are immutable source archives, including the physically accepted Wave.
The IK fits the current fixed-shaft geometry; calibration is only measured, never
changed. These are authored trajectories, not new executor limits or fallbacks.
"""
import argparse
import copy
import gzip
import json
from pathlib import Path

import numpy as np
from scipy.optimize import brentq
from scipy.spatial.transform import Rotation

from author_expressive_gestures import finish, read, stamp
from retarget_clips import LEGS, load_reference, digest


def phases_for(items):
    phases = []
    start = 0.
    for name, duration in items:
        end = round(start + duration, 8)
        phases.append(dict(start=start, end=end, kind=name))
        start = end
    return phases


def seated_point(wave, previous, ref):
    entry = wave['samples'][:145]
    seat = np.array(entry[-1]['actuator_angles_rad'][2])
    lift = np.array(wave['samples'][192]['actuator_angles_rad'][2])
    extended = np.array(next(r for r in previous['samples'] if r['phase']=='hold_point')['actuator_angles_rad'][2])
    phases = phases_for([('squat_rear_legs',1.2), ('lift_front_left',.4),
        ('extend_to_point',.6), ('hold_point',1.5), ('retract_front_left',.6),
        ('replace_front_left',.4), ('return_to_standing',1.2), ('hold_standing',.2)])
    rows=[]
    for i in range(round(phases[-1]['end']*120)+1):
        t=i/120; p=next((p for p in phases if t<p['end']),phases[-1])
        if i<=144:
            row=copy.deepcopy(entry[i])
        elif t>=4.7:
            row=copy.deepcopy(entry[max(0,round((5.9-t)*120))])
        else:
            row=copy.deepcopy(entry[-1])
            if t<1.6:a,b,u=seat,lift,(t-1.2)/.4
            elif t<2.2:a,b,u=lift,extended,(t-1.6)/.6
            elif t<3.7:a,b,u=extended,extended,0.
            elif t<4.3:a,b,u=extended,lift,(t-3.7)/.6
            else:a,b,u=lift,seat,(t-4.3)/.4
            row['actuator_angles_rad'][2]=(a+(b-a)*ref.smooth(u)).tolist()
            row['contact_active']=[True,True,False,True]
        rows.append(stamp(row,t,p))
    return rows,phases


def body_vertices(hulls,cfg,e):
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    return (hulls['body']-pivot)@Rotation.from_euler('xyz',e).as_matrix().T+pivot


def rear_braced_pushup(anchor,mechanism,ref,hulls,cfg):
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    rear=hulls['body'][:,0]<pivot[0];front=hulls['body'][:,0]>pivot[0]
    def pose(pitch):
        e=np.deg2rad([0,pitch,0]);v=body_vertices(hulls,cfg,e)
        return np.array([-20.,0.,8.-v[rear,2].min()]),e
    def front_clearance(pitch):
        b,e=pose(pitch)
        return body_vertices(hulls,cfg,e)[front,2].min()+b[2]
    bottom=brentq(lambda p:front_clearance(p)-3.,0.,3.)
    standing=np.array(anchor['body_translation_world_mm']);es=np.zeros(3)
    high,eh=pose(-23.);low,el=pose(bottom)
    phases=phases_for([('squat_rear_legs',1.)]+[
        (f'pushup_{i}_{part}',duration) for i in range(1,6)
        for part,duration in [('down',1.1),('bottom',.2),('up',1.1)]]+
        [('return_to_standing',1.),('hold_standing',.2)])
    def target(t,p):
        u=ref.smooth((t-p['start'])/(p['end']-p['start']))
        if p['kind']=='squat_rear_legs':return standing+(high-standing)*u,es+(eh-es)*u
        if p['kind']=='return_to_standing':return high+(standing-high)*u,eh+(es-eh)*u
        if p['kind']=='hold_standing':return standing,es
        if p['kind'].endswith('_bottom'):return low,el
        # Compute the body translation from the rear clearance at every angle,
        # rather than linearly blending Z and letting the rear bob each press.
        angle=bottom+(-23.-bottom)*u if p['kind'].endswith('_up') else -23.+(bottom+23.)*u
        return pose(angle)
    return planted_rows(anchor,mechanism,phases,target),phases


def worm(anchor,mechanism,ref,hulls,cfg):
    standing=np.array(anchor['body_translation_world_mm']);es=np.zeros(3)
    # Three complete heave/pitch waves. The phase offset moves the low end of
    # the body from front to rear; all four bare feet stay on their anchors.
    def wave(u, envelope=1.):
        a=2*np.pi*u
        e=np.deg2rad([0,20*np.sin(a)*envelope,0])
        clearance=4.+6.*(1.-np.cos(a))*envelope
        v=body_vertices(hulls,cfg,e)
        return np.array([-16.+6.*np.sin(a)*envelope,0.,clearance-v[:,2].min()]),e
    base,eb=wave(0.)
    phases=phases_for([('lower_into_worm',.7)]+[(f'body_wave_{i}',1.6) for i in range(1,4)]+
                      [('return_to_standing',.7),('hold_standing',.2)])
    def target(t,p):
        u=(t-p['start'])/(p['end']-p['start'])
        if p['kind']=='lower_into_worm':return standing+(base-standing)*ref.smooth(u),eb
        if p['kind']=='return_to_standing':return base+(standing-base)*ref.smooth(u),eb
        if p['kind']=='hold_standing':return standing,es
        envelope=ref.smooth(min(1.,(t-.7)/.3,(5.5-t)/.3))
        return wave((t-.7)/1.6,envelope)
    return planted_rows(anchor,mechanism,phases,target),phases


def planted_rows(anchor,mechanism,phases,target):
    xy=np.array(anchor['target_foot_reference_xy_mm']);seed=np.array(anchor['actuator_angles_rad']);rows=[]
    for i in range(round(phases[-1]['end']*120)+1):
        t=i/120;p=next((p for p in phases if t<p['end']),phases[-1]);body,e=target(t,p)
        mechanism.body_euler=e
        q=np.array([mechanism.solve(l,body,seed[j],xy[j],0)[0] for j,l in enumerate(LEGS)])
        row=copy.deepcopy(anchor)
        row.update(body_translation_world_mm=body.tolist(),body_rotation_euler_xyz_rad=e.tolist(),
                   actuator_angles_rad=q.tolist(),contact_active=[True]*4,
                   target_foot_reference_xy_mm=xy.tolist(),target_sole_clearance_mm=[0.]*4)
        rows.append(stamp(row,t,p));seed=q
    return rows


def main(root,baseline_dir,calibration_path,commands):
    cfg=read(root/'geometry.json');ref=load_reference(root);m=ref.Mechanism(cfg)
    sole=np.array(read(root/'motions/locomotion/walk-contact.json')['sole_hull_local_mm'])
    hulls=dict(np.load(root/'motions/gestures/sit/posture-hulls.npz'))
    for leg in LEGS:hulls['sole_'+leg]=sole.copy()
    m.hulls={leg:sole for leg in LEGS}
    load=lambda name:json.loads(gzip.decompress((baseline_dir/(name+'-baseline.json.gz')).read_bytes()))
    wave=load('wave');anchor=wave['samples'][0];cal=read(calibration_path)
    descriptions={
        'point':'Accepted Wave rear-leg seating, quick front-left lift and full forward point, held before seated foot replacement and recovery.',
        'pushup':'Rear-first squat; five slow deep front presses with rear body clearance held at 8 mm, front down to 3 mm, all four bare feet planted.',
        'worm':'Three brisk large front-to-rear pitch/heave waves with all four bare feet planted, then standing recovery.'}
    for name in commands:
        source=load(name)
        source['metadata']['wave_reference_archive_sha256']=digest(baseline_dir/'wave-baseline.json.gz')
        if name=='point':rows,phases=seated_point(wave,source,ref)
        elif name=='pushup':rows,phases=rear_braced_pushup(anchor,m,ref,hulls,cfg)
        else:rows,phases=worm(anchor,m,ref,hulls,cfg)
        finish(root,name,source,rows,phases,descriptions[name],hulls,cal,
               baseline_dir/(name+'-baseline.json.gz'),generator='tools/author_seated_emotes.py')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--baseline-dir',type=Path,required=True)
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--commands',nargs='+',choices=['point','pushup','worm'],default=['point','pushup','worm'])
    a=p.parse_args();main(a.root.resolve(),a.baseline_dir.resolve(),a.calibration,a.commands)
