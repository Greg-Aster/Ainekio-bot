"""Adapt recorded gestures to measured chassis dimensions without rescaling them.

The source root is an unchanged previous model snapshot. Keep its recording,
timing, rotations and airborne joint keys as the parity reference. Solve planted
feet at translated anchors; correct body/foot penetration caused by the changed
geometry. This is an offline geometry operation, never a servo travel limiter.
"""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares

from retarget_clips import LEGS, SEARCH_BOUNDS, digest, load_reference, remap_footprint, write


def fit_contacts(mechanism,target,seed,body_hull,pivot,recorded):
    """Allow a minimal root correction when the new footprint needs it."""
    legs=np.flatnonzero(target['grounded']);requested=target['body'].copy()
    if not len(legs):return requested,seed.copy(),0.
    matrix=Rotation.from_euler('xyz',target['euler']).as_matrix()
    floor=float(((body_hull-pivot)@matrix[2]+pivot[2]).min())
    def residual(values):
        body=requested.copy();body[[0,2]]+=values[:2];errors=[]
        for i,q in zip(legs,values[2:].reshape(-1,3)):
            try:
                point=mechanism.reference(LEGS[i],q,body)
                height=float(mechanism.vertices(LEGS[i],q,body)[:,2].min())
                errors.extend([*(point[:2]-target['feet'][i]),height-target['z'][i]])
            except ValueError:errors.extend([1000.]*3)
        return np.r_[errors,values[:2]*.001,min(0.,floor+body[2])*10]
    values=np.r_[0.,0.,seed[legs].ravel()]
    bounds=(np.r_[-50.,-50.,np.tile(SEARCH_BOUNDS[:,0],len(legs))],np.r_[50.,50.,np.tile(SEARCH_BOUNDS[:,1],len(legs))])
    fit=least_squares(residual,values,bounds=bounds,xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=240,diff_step=1e-5)
    error=float(np.max(abs(residual(fit.x)[:3*len(legs)])))
    if error>.01:
        # A flat boot switches supporting vertices. Restart from the authored
        # pose if the preceding frame lands on that nonsmooth minimum.
        for dz in (0.,1.,-1.,3.,-3.):
            start=np.r_[0.,dz,recorded[legs].ravel()]
            candidate=least_squares(residual,start,bounds=bounds,xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=400,diff_step=1e-5)
            candidate_error=float(np.max(abs(residual(candidate.x)[:3*len(legs)])))
            if candidate_error<error:fit,error=candidate,candidate_error
            if error<.001:break
    if error>.01:raise ValueError(f'Planted pose cannot be preserved at {target["time_s"]}: {error} mm; fit={fit.x.tolist()}, residual={fit.fun.tolist()}')
    body=requested.copy();body[[0,2]]+=fit.x[:2];q=seed.copy();q[legs]=fit.x[2:].reshape(-1,3)
    return body,q,error


def remap(root, source_root):
    cfg=json.loads((root/'geometry.json').read_text())
    previous=json.loads((source_root/'geometry.json').read_text())
    cfg['research_angle_bounds_deg']=np.rad2deg(SEARCH_BOUNDS).tolist()
    ref=load_reference(root);old=ref.Mechanism(previous);new=ref.Mechanism(cfg)
    old_hulls=np.load(source_root/'motions/gestures/reviewed-hulls.npz')
    new_hulls=np.load(root/'motions/gestures/reviewed-hulls.npz')
    old.hulls={l:old_hulls['sole_'+l] for l in LEGS}
    new.hulls={l:new_hulls['sole_'+l] for l in LEGS}
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    for path in sorted((source_root/'motions/gestures').glob('*/reviewed.json')):
        original=json.loads(path.read_text());clip=copy.deepcopy(original);targets=[]
        body_correction=0.;joint_correction=0.;airborne_corrections=0
        for row in original['samples']:
            old.body_euler=np.array(row['euler']);body=np.array(row['body']);rot=Rotation.from_euler('xyz',row['euler']).as_matrix()
            old_clear=float(((old_hulls['body']-pivot)@rot[2]+pivot[2]+body[2]).min())
            new_clear=float(((new_hulls['body']-pivot)@rot[2]+pivot[2]+body[2]).min())
            if not targets:standing_clear=old_clear
            depth=np.clip(1.-old_clear/max(standing_clear,1e-9),0.,1.)
            correction=max(0.,old_clear-new_clear)*ref.smooth(depth)
            # Retain the recorded root at standing, smoothly accommodate the
            # changed body outline as the gesture lowers toward support.
            body[2]+=correction;body_correction=max(body_correction,correction)
            feet=np.array([old.reference(l,q,row['body'])[:2] for l,q in zip(LEGS,row['q'])])
            heights=np.array([float(old.vertices(l,q,row['body'])[:,2].min()) for l,q in zip(LEGS,row['q'])])
            targets.append(dict(time_s=row['time_s'],euler=np.array(row['euler']),body=body,feet=feet,z=heights,grounded=np.array(row['contact'],dtype=bool)))
        targets=remap_footprint(targets,previous['reference_stance_xy_mm'],cfg['reference_stance_xy_mm'],ref)
        maximum_error=0.;previous_q=np.array(original['samples'][0]['q']);root_correction=0.
        for row,target,prior in zip(clip['samples'],targets,original['samples']):
            new.body_euler=target['euler'];requested=target['body'].copy()
            fitted_body,fitted_q,error=fit_contacts(new,target,previous_q,new_hulls['body'],pivot,np.array(prior['q']))
            maximum_error=max(maximum_error,error);root_correction=max(root_correction,float(np.max(abs(fitted_body-requested))))
            target['body']=fitted_body;row['body']=fitted_body.tolist()
            for i,leg in enumerate(LEGS):
                q=np.array(prior['q'][i]);height=float(new.vertices(leg,q,target['body'])[:,2].min())
                if target['grounded'][i]:
                    q=fitted_q[i]
                elif height<-.02:
                    # Preserve the arm's horizontal reach; restore only the
                    # floor clearance lost to the changed chassis geometry.
                    xy=new.reference(leg,q,target['body'])[:2]
                    q,error=new.solve(leg,target['body'],q,xy,max(0.,target['z'][i]));maximum_error=max(maximum_error,error);airborne_corrections+=1
                joint_correction=max(joint_correction,float(np.rad2deg(abs(q-prior['q'][i])).max()))
                row['q'][i]=q.tolist()
                previous_q[i]=q
        clip['geometry_sha256']=digest(root/'geometry.json')
        clip['geometry_remap']=dict(source_recording_sha256=digest(path),source_geometry_sha256=digest(source_root/'geometry.json'),
            timing_rotations_phases_and_cues_preserved=True,amplitude_scale=1.,maximum_body_floor_correction_mm=body_correction,
            maximum_joint_correction_deg=joint_correction,airborne_floor_corrections=airborne_corrections,maximum_ik_error_mm=maximum_error,
            maximum_additional_root_correction_mm=root_correction,
            scope='Translated stance anchors and necessary floor corrections; no servo travel clipping or gesture amplitude scaling.')
        clip.pop('summary',None) # Previous geometry's clearance claims do not apply.
        write(root/'motions/gestures'/path.parent.name/'reviewed.json',clip)
        print(path.parent.name,clip['geometry_remap'],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--source-root',type=Path,required=True)
    args=ap.parse_args();remap(args.root,args.source_root)
