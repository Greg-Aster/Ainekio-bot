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


def refresh_metrics(root,commands):
    """Refresh FK evidence after authoring; retain independent contact targets."""
    from retarget_clips import support_margin
    cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    ankle=np.array(json.loads((root/'motions/gestures/point/posture.json').read_text())['ankle_local_mm']);ankle[1]=0.
    for command in commands:
        folder=root/'motions/gestures'/command;p=folder/'source.json';source=json.loads(p.read_text());rows=source['samples'];m=ref.Mechanism(cfg);post=folder/'posture.json'
        hp=folder/json.loads(post.read_text())['contact_hulls_file'] if post.exists() else root/'motions/gestures/sit/posture-hulls.npz'
        with np.load(hp) as hulls:
            m.hulls={l:hulls['sole_'+l].copy() for l in LEGS};body_hull=hulls['body'].copy()
        error=0.
        for index,row in enumerate(rows):
            if command=='upright' and index<=360:continue
            q=np.array(row['actuator_angles_rad']);body=np.array(row['body_translation_world_mm']);m.body_euler=np.array(row['body_rotation_euler_xyz_rad']);matrix=Rotation.from_euler('xyz',m.body_euler).as_matrix();com=body+pivot;world_body=(body_hull-pivot)@matrix.T+pivot+body;clear=float(world_body[:,2].min());support=[];feet=[];contacts=[];zs=[];indices=[];betas=[];heights=[];reach=[]
            for i,l in enumerate(LEGS):
                vs=m.vertices(l,q[i],body);k=int(vs[:,2].argmin());feet.append(m.reference(l,q[i],body).tolist());contacts.append(vs[k].tolist());zs.append(float(vs[k,2]));indices.append(k)
                D,P,E,beta,height=m.planar(q[i]);betas.append(float(beta-m.b0));heights.append(height);reach.append(float(np.linalg.norm(np.r_[D[0]-m.O[0],0,D[1]-m.O[1]]+ref.ry(-(beta-m.b0))@ankle)))
                if row['contact_active'][i]:support.extend(vs[vs[:,2]<vs[k,2]+.5])
                if row['contact_active'][i] and 'target_foot_reference_xy_mm' in row:
                    error=max(error,float(abs(np.array(feet[-1])[:2]-row['target_foot_reference_xy_mm'][i]).max()),abs(zs[-1]-row['target_sole_clearance_mm'][i]))
            touching=clear<=.0005;patch=world_body[world_body[:,2]<.5] if touching else np.empty((0,3))
            if touching:support.extend(patch)
            row.update(foot_bolt_world_mm=feet,contact_world_mm=contacts,sole_clearance_mm=zs,contact_vertex_index=indices,passive_beta_rad=betas,body_position_world_mm=com.tolist(),assumed_com_world_mm=com.tolist(),body_ground_clearance_mm=clear,body_contact_active=touching,body_contact_polygon_world_mm=patch.tolist(),support_margin_mm=support_margin(support,com),minimum_closure_height_mm=float(min(heights)),arm_reach_mm=reach)
        angles=np.array([r['actuator_angles_rad'] for r in rows]);validation=source['validation'];validation.update(min_sole_z_mm=min(min(r['sole_clearance_mm']) for r in rows),min_body_z_mm=min(r['body_ground_clearance_mm'] for r in rows),minimum_closure_height_mm=min(r.get('minimum_closure_height_mm',float('inf')) for r in rows),maximum_adjacent_joint_step_degrees=float(np.rad2deg(abs(np.diff(angles,axis=0))).max()),maximum_planted_target_error_mm=error,hardware_qualified=False)
        if command=='upright':validation['min_support_margin_after_sit_mm']=min(r['support_margin_mm'] for r in rows[361:] if r['support_margin_mm'] is not None);validation['final_front_reach_mm']=rows[-1]['arm_reach_mm'][2:]
        if validation['min_sole_z_mm']<-.005 or validation['min_body_z_mm']<-.005:raise ValueError((command,'ground penetration',validation))
        p.write_text(json.dumps(source,separators=(',',':'),allow_nan=False)+'\n');write(folder/'validation.json',validation)
        rev=folder/'reviewed.json'
        if rev.exists():
            recorded=json.loads(rev.read_text())
            for i,r in enumerate(recorded['samples']):
                r['body']=rows[i*4]['body_translation_world_mm'];r['q']=rows[i*4]['actuator_angles_rad'];r['contact']=rows[i*4]['contact_active']
            write(rev,recorded)
        manifest=folder/'manifest.json';v=json.loads(manifest.read_text());v['source_validation'].update(validation);write(manifest,v)
        print(command,'FK metrics',validation['min_sole_z_mm'],validation['min_body_z_mm'],error,flush=True)


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


def refit_internal_clearance(root, commands):
    """Reauthor conflicting finite paths in coupled joint coordinates.

    Keep recorded phase times and body rotations. Solve planted anchors with
    minimal root correction; retain airborne targets where the measured
    mechanism can reach them. This offline fit changes source paths, never
    operator settings or runtime limits.
    """
    from mechanical_limits import Limits
    from scipy.interpolate import PchipInterpolator
    limits=Limits(root);cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);m=ref.Mechanism(cfg)
    bounds=np.array(limits.bounds);pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    def encode(q):
        deg=np.rad2deg(q);theta=float(np.clip(deg[2],bounds[2,0]+.001,bounds[2,1]-.001));a,b=limits.alpha_bounds(theta)
        return [float(np.clip(deg[0],-109.999,109.999)),theta,float(np.clip((deg[1]-a)/(b-a),.00001,.99999))]
    def decode(v):
        a,b=limits.alpha_bounds(v[1]);return np.deg2rad([v[0],a+(b-a)*v[2],v[1]])
    lo=np.r_[-100.,-100.,np.tile([-110,bounds[2,0],0.],4)];hi=np.r_[100.,100.,np.tile([110,bounds[2,1],1.],4)]
    reports=[]
    for command in commands:
        folder=root/'motions/gestures'/command;source=json.loads((folder/'source.json').read_text());original=copy.deepcopy(source);rows=source['samples'];hull_file=folder/'posture.json'
        hp=folder/json.loads(hull_file.read_text())['contact_hulls_file'] if hull_file.exists() else root/'motions/gestures/sit/posture-hulls.npz'
        hulls=np.load(hp);m.hulls={l:hulls['sole_'+l] for l in LEGS};bh=hulls['body'];times=np.array([r['time_s'] for r in rows]);knots=np.unique(np.r_[np.arange(0,len(rows),24),len(rows)-1]);fitted=[];prev=None;max_ground=0.;max_air=0.
        for index in knots:
            row=original['samples'][index];body=np.array(row['body_translation_world_mm']);e=np.array(row['body_rotation_euler_xyz_rad']);m.body_euler=e;oldq=np.array(row['actuator_angles_rad']);active=np.array(row['contact_active']);target=np.array([m.reference(l,q,body) for l,q in zip(LEGS,oldq)]);z=np.array([m.vertices(l,q,body)[:,2].min() for l,q in zip(LEGS,oldq)]);matrix=Rotation.from_euler('xyz',e).as_matrix();floor=float(((bh-pivot)@matrix[2]+pivot[2]).min())
            def residual(v):
                b=body.copy();b[[0,2]]+=v[:2];qq=np.array([decode(x) for x in v[2:].reshape(4,3)]);errors=[]
                for i,l in enumerate(LEGS):
                    try:
                        point=m.reference(l,qq[i],b);height=m.vertices(l,qq[i],b)[:,2].min()
                        if active[i]:errors.extend(np.r_[point[:2]-target[i,:2],height-z[i]]*30.)
                        else:errors.extend((point-target[i])*.3)
                        errors.append(min(0.,height)*30.)
                    except ValueError:errors.extend([1000.]*4)
                # Angle regularization selects a continuous nearby branch;
                # root movement supplies clearance without shrinking gestures.
                qprev=oldq if prev is None else prev[1]
                return np.r_[errors,v[:2]*.002,(qq-oldq).ravel()*.01,(qq-qprev).ravel()*.02,min(0.,floor+b[2])*30.]
            start=np.r_[0.,0.,np.array([encode(q) for q in oldq]).ravel()] if prev is None else np.r_[prev[0]-body[[0,2]],np.array([encode(q) for q in prev[1]]).ravel()]
            start=np.minimum(hi-1e-10,np.maximum(lo+1e-10,start));fit=least_squares(residual,start,bounds=(lo,hi),max_nfev=80,ftol=1e-8,xtol=1e-8,gtol=1e-8,diff_step=1e-5)
            b=body.copy();b[[0,2]]+=fit.x[:2];q=np.array([decode(v) for v in fit.x[2:].reshape(4,3)])
            errors=[]
            for i,l in enumerate(LEGS):
                p=m.reference(l,q[i],b);height=m.vertices(l,q[i],b)[:,2].min();err=float(max(abs(p[:2]-target[i,:2]).max(),abs(height-z[i]))) if active[i] else float(np.linalg.norm(p-target[i]));errors.append(err)
                if active[i]:max_ground=max(max_ground,err)
                else:max_air=max(max_air,err)
            if max(errors[i] for i in range(4) if active[i])>.01 if any(active) else False:raise ValueError((command,row['time_s'],'planted residual',errors,fit.fun[:16]))
            fitted.append(np.r_[b,np.array([encode(a) for a in q]).ravel()]);prev=(b[[0,2]],q)
            if index%120==0:print('Fit',command,row['time_s'],'ground',round(max_ground,6),'air',round(max_air,3),flush=True)
        values=PchipInterpolator(times[knots],np.array(fitted),axis=0)(times);angles=np.array([[decode(a) for a in frame.reshape(4,3)] for frame in values[:,3:]])
        # The paired source interpolation is checked after fitting; independent
        # scalar smoothing must not cut across a curved collision boundary.
        for i,row in enumerate(rows):
            b=values[i,:3];q=angles[i];m.body_euler=np.array(row['body_rotation_euler_xyz_rad']);feet=[];contacts=[];zs=[];indices=[];betas=[]
            for l,a in zip(LEGS,q):
                if not limits.allowed(a):raise ValueError((command,'interpolation',i,np.rad2deg(a).tolist()))
                vs=m.vertices(l,a,b);k=int(vs[:,2].argmin());feet.append(m.reference(l,a,b).tolist());contacts.append(vs[k].tolist());zs.append(float(vs[k,2]));indices.append(k);betas.append(float(m.planar(a)[3]-m.b0))
            row.update(body_translation_world_mm=b.tolist(),body_position_world_mm=(b+pivot).tolist(),actuator_angles_rad=q.tolist(),foot_bolt_world_mm=feet,contact_world_mm=contacts,sole_clearance_mm=zs,contact_vertex_index=indices,passive_beta_rad=betas,target_foot_reference_xy_mm=original['samples'][i].get('target_foot_reference_xy_mm',[p[:2] for p in original['samples'][i]['foot_bolt_world_mm']]),target_sole_clearance_mm=original['samples'][i].get('target_sole_clearance_mm',original['samples'][i]['sole_clearance_mm']))
            matrix=Rotation.from_euler('xyz',m.body_euler).as_matrix();row['body_ground_clearance_mm']=float(((bh-pivot)@matrix[2]+pivot[2]+b[2]).min())
        olda=np.array([r['actuator_angles_rad'] for r in original['samples']]);report=dict(command=command,samples=len(rows),maximum_planted_knot_error_mm=max_ground,maximum_airborne_target_change_mm=max_air,maximum_root_correction_mm=float(abs(values[:,:3]-np.array([r['body_translation_world_mm'] for r in original['samples']])).max()),maximum_joint_step_degrees=float(np.rad2deg(abs(np.diff(angles,axis=0))).max()),timing_and_body_rotation_preserved=True,amplitude_scale=1.,profile_sha256=digest(root/'servo_profile.json'),scope='Coupled internal-linkage offline source fit; sampled contacts and all source interpolation checked separately. Physical tracking and whole-body strength unqualified.')
        source['metadata']['generator']='tools/remap_reviewed_clips.py --clearance';source['metadata']['internal_clearance_fit']=report;source['validation'].update(collision_checked=False,clearance_fit=report);(folder/'source.json').write_text(json.dumps(source,separators=(',',':'),allow_nan=False)+'\n')
        rev=folder/'reviewed.json'
        if rev.exists():
            clip=json.loads(rev.read_text())
            for i,r in enumerate(clip['samples']):r['body']=rows[i*4]['body_translation_world_mm'];r['q']=rows[i*4]['actuator_angles_rad']
            clip['internal_clearance_fit']=report;write(rev,clip)
        reports.append(report);print('FINISHED',json.dumps(report),flush=True)
    return reports

def polish_clearance(root, commands, source_root=None):
    """Solve residual contact drift after coarse offline path authoring.

    The retained source supplies the contact targets. Never replace a target
    with its achieved position: that would conceal fitting error.
    """
    from mechanical_limits import Limits
    limits=Limits(root);cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);m=ref.Mechanism(cfg);bounds=np.array(limits.bounds);pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    def encode(q):
        d=np.rad2deg(q);theta=np.clip(d[2],bounds[2,0]+.0001,bounds[2,1]-.0001);a,b=limits.alpha_bounds(theta)
        return [np.clip(d[0],-109.9999,109.9999),theta,np.clip((d[1]-a)/(b-a),.000001,.999999)]
    def decode(v):
        a,b=limits.alpha_bounds(v[1]);return np.deg2rad([v[0],a+(b-a)*v[2],v[1]])
    low=np.r_[-100,-100,np.tile([-110,bounds[2,0],0.],4)];high=np.r_[100,100,np.tile([110,bounds[2,1],1.],4)]
    for command in commands:
        folder=root/'motions/gestures'/command;p=folder/'source.json';source=json.loads(p.read_text());original=json.loads(((source_root or root)/p.relative_to(root)).read_text());rows=source['samples'];op=original['samples'];post=folder/'posture.json';hp=folder/json.loads(post.read_text())['contact_hulls_file'] if post.exists() else root/'motions/gestures/sit/posture-hulls.npz';hulls=np.load(hp);m.hulls={l:hulls['sole_'+l] for l in LEGS};bh=hulls['body'];maxerr=0.;count=0;minimum=1e9
        for index,(row,target) in enumerate(zip(rows,op)):
            body=np.array(row['body_translation_world_mm']);q=np.array(row['actuator_angles_rad']);m.body_euler=np.array(row['body_rotation_euler_xyz_rad']);matrix=Rotation.from_euler('xyz',m.body_euler).as_matrix();floor=float(((bh-pivot)@matrix[2]+pivot[2]).min());active=np.array(target['contact_active'],dtype=bool);xy=np.array(target['foot_bolt_world_mm'])[:,:2];z=np.maximum(.0001,np.array(target['sole_clearance_mm']));oldq=q.copy()
            def values(qq,bb):
                pp=[];hh=[]
                for l,a in zip(LEGS,qq):
                    R,T=m.pose(l,a,bb);pp.append(R@m.geom[l]['foot_reference_local_mm']+T);hh.append(float((m.hulls[l]@R[2]+T[2]).min()))
                return np.array(pp),np.array(hh)
            point,height=values(q,body);seedpoint=point.copy();err=float(max(abs(point[active,:2]-xy[active]).max(initial=0),abs(height[active]-z[active]).max(initial=0)))
            if err>.003 or min(height)<-.0001 or not all(limits.allowed(a) for a in q):
                def residual(v):
                    bb=body.copy();bb[[0,2]]+=v[:2];qq=np.array([decode(a) for a in v[2:].reshape(4,3)])
                    try:pp,hh=values(qq,bb)
                    except ValueError:return np.r_[np.ones(16)*1000,v[:2]*.0001,(qq-oldq).ravel()*.001,min(0.,floor+bb[2])*30]
                    errors=[]
                    for i in range(4):
                        errors.extend(np.r_[pp[i,:2]-xy[i],hh[i]-z[i]]*30 if active[i] else (pp[i]-seedpoint[i])*.1);errors.append(min(0.,hh[i]-.0001)*30)
                    return np.r_[errors,v[:2]*.0001,(qq-oldq).ravel()*.001,min(0.,floor+bb[2])*30]
                v=np.r_[0.,0.,np.array([encode(a) for a in q]).ravel()];v=np.minimum(high-1e-10,np.maximum(low+1e-10,v));fit=least_squares(residual,v,bounds=(low,high),max_nfev=40,ftol=1e-9,xtol=1e-9,gtol=1e-9,diff_step=1e-5);body[[0,2]]+=fit.x[:2];q=np.array([decode(a) for a in fit.x[2:].reshape(4,3)]);point,height=values(q,body);err=float(max(abs(point[active,:2]-xy[active]).max(initial=0),abs(height[active]-z[active]).max(initial=0)));count+=1
            if err>.01 or min(height)<-.001 or not all(limits.allowed(a) for a in q):raise ValueError((command,index,err,min(height),'polish could not meet retained contacts'))
            maxerr=max(maxerr,err);minimum=min(minimum,min(height));contacts=[];indices=[];betas=[]
            for l,a in zip(LEGS,q):
                vs=m.vertices(l,a,body);k=int(vs[:,2].argmin());contacts.append(vs[k].tolist());indices.append(k);betas.append(float(m.planar(a)[3]-m.b0))
            row.update(body_translation_world_mm=body.tolist(),body_position_world_mm=(body+pivot).tolist(),actuator_angles_rad=q.tolist(),foot_bolt_world_mm=point.tolist(),contact_world_mm=contacts,sole_clearance_mm=height.tolist(),contact_vertex_index=indices,passive_beta_rad=betas,target_foot_reference_xy_mm=target.get('target_foot_reference_xy_mm',xy.tolist()),target_sole_clearance_mm=target.get('target_sole_clearance_mm',target['sole_clearance_mm']),body_ground_clearance_mm=floor+body[2])
            if index%240==0:print('Polish',command,index,'solved',count,'error',maxerr,flush=True)
        report=source['metadata'].setdefault('internal_clearance_fit',{});report.update(maximum_planted_sample_error_mm=maxerr,minimum_sole_clearance_mm=minimum,polished_samples=count);source['validation']['clearance_fit']=report;source['metadata']['generator']='tools/remap_reviewed_clips.py --clearance';p.write_text(json.dumps(source,separators=(',',':'),allow_nan=False)+'\n');rev=folder/'reviewed.json'
        if rev.exists():
            clip=json.loads(rev.read_text())
            for i,r in enumerate(clip['samples']):r['body']=rows[i*4]['body_translation_world_mm'];r['q']=rows[i*4]['actuator_angles_rad']
            clip['internal_clearance_fit']=report;write(rev,clip)
        print('POLISHED',command,json.dumps(report),flush=True)

def restore_stand_returns(root, commands, source_root):
    """Retain the common entry and finish while solving the return contacts."""
    from mechanical_limits import Limits
    L=Limits(root);cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);m=ref.Mechanism(cfg)
    for name in commands:
        p=root/'motions/gestures'/name/'source.json';s=json.loads(p.read_text());original=json.loads((source_root/p.relative_to(root)).read_text());rows=s['samples'];op=original['samples'];post=p.with_name('posture.json');hp=post.parent/json.loads(post.read_text())['contact_hulls_file'] if post.exists() else root/'motions/gestures/sit/posture-hulls.npz';h=np.load(hp);m.hulls={l:h['sole_'+l] for l in LEGS}
        if max(abs(np.array(op[-1]['actuator_angles_rad'])-np.array(op[0]['actuator_angles_rad'])).ravel())>1e-5:continue
        phase=next((x for x in reversed(s.get('phases',[])) if any(k in x['kind'].lower() for k in ['return','rise','standing'] ) and x['end']-x['start']>.6),None)
        begin=phase['start'] if phase else rows[-1]['time_s']-2.;end=phase['end'] if phase else rows[-1]['time_s'];end=min(end,rows[-1]['time_s']);seed=np.array(rows[max(0,round(begin*120)-1)]['actuator_angles_rad'])
        rows[0]=copy.deepcopy(op[0])
        for i in range(round(begin*120),len(rows)):
            row=rows[i];target=op[i];u=ref.smooth(np.clip((row['time_s']-begin)/(end-begin),0,1));body=(1-u)*np.array(row['body_translation_world_mm'])+u*np.array(target['body_translation_world_mm']);m.body_euler=np.array(target['body_rotation_euler_xyz_rad']);q=[]
            if u==1.:
                rows[i]=copy.deepcopy(target);seed=np.array(target['actuator_angles_rad']);continue
            for j,l in enumerate(LEGS):
                a,e=m.solve(l,body,seed[j],np.array(target['foot_bolt_world_mm'])[j,:2],max(0.,target['sole_clearance_mm'][j]))
                if not L.allowed(a):raise ValueError((name,i,l,'return leaves coupled envelope',np.rad2deg(a)))
                q.append(a)
            q=np.array(q);seed=q;row.update(body_translation_world_mm=body.tolist(),actuator_angles_rad=q.tolist())
        s['metadata'].setdefault('internal_clearance_fit',{})['common_stand_entry_and_finish_preserved']=True;p.write_text(json.dumps(s,separators=(',',':'))+'\n');print('RETURN',name,begin,end,flush=True)


def reauthor_rest(root):
    """Place feet before lowering; keep the original body-contact depth."""
    from mechanical_limits import Limits
    from scipy.optimize import least_squares
    p=root/'motions/gestures/rest/source.json';source=json.loads(p.read_text());cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);m=ref.Mechanism(cfg);L=Limits(root);h=np.load(p.with_name('posture-hulls.npz'));m.hulls={l:h['sole_'+l] for l in LEGS};m.body_euler=np.zeros(3);pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);body_end=-float(h['body'][:,2].min());stance=np.array(cfg['reference_stance_xy_mm'])[[2,3,0,1]];dest=stance+np.array([37.545,0]);dest[:,1]+=np.sign(dest[:,1])*24.166;seed=np.zeros((4,3));rows=source['samples']
    def decode(v):a,b=L.alpha_bounds(v[1]);return np.deg2rad([v[0],a+(b-a)*v[2],v[1]])
    for i,row in enumerate(rows):
        t=row['time_s'];body=np.array([0.,0.,cfg['body_translation_z_mm']+(body_end-cfg['body_translation_z_mm'])*ref.smooth(np.clip((t-1.)/2.,0,1))]);q=[];contacts=[];feet=[];heights=[];on=[];indices=[]
        for j,l in enumerate(LEGS):
            u=np.clip((t-j*.25)/.25,0,1);xy=stance[j]+ref.smooth(u)*(dest[j]-stance[j]);z=8*ref.bump(u) if 0<u<1 else 0.;d=np.rad2deg(seed[j]);a,b=L.alpha_bounds(float(np.clip(d[2],-53.27,139.36)));start=[d[0],np.clip(d[2],-53.2699,139.3599),np.clip((d[1]-a)/(b-a),.00001,.99999)]
            def residual(v):
                qq=decode(v)
                try:R,T=m.pose(l,qq,body);pt=R@m.geom[l]['foot_reference_local_mm']+T;zz=(m.hulls[l]@R[2]+T[2]).min();return np.r_[pt[:2]-xy,zz-z]
                except ValueError:return [999.]*3
            f=least_squares(residual,start,bounds=([-110,-53.27,0],[110,139.36,1]),max_nfev=100,ftol=1e-8,xtol=1e-8,gtol=1e-8,diff_step=1e-5);qq=decode(f.x)
            if max(abs(f.fun))>.005:raise ValueError(('Rest placement',i,l,f.fun))
            seed[j]=qq;q.append(qq.tolist());vs=m.vertices(l,qq,body);k=int(vs[:,2].argmin());feet.append(m.reference(l,qq,body).tolist());contacts.append(vs[k].tolist());heights.append(float(vs[k,2]));indices.append(k);on.append(not 0<u<1)
        clear=float(h['body'][:,2].min()+body[2]);row.update(phase='place_feet' if t<1 else 'lower_into_rest' if t<3 else 'hold_rest',body_translation_world_mm=body.tolist(),body_position_world_mm=(body+pivot).tolist(),actuator_angles_rad=q,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_vertex_index=indices,contact_active=on,sole_clearance_mm=heights,body_ground_clearance_mm=clear,body_contact_active=clear<.001,target_foot_reference_xy_mm=[a[:2] for a in feet],target_sole_clearance_mm=heights)
    source['metadata']['internal_clearance_fit']=dict(command='rest',feet_placed_before_lowering=True,body_contact_depth_preserved=True,hardware_qualified=False,profile_sha256=digest(root/'servo_profile.json'));p.write_text(json.dumps(source,separators=(',',':'))+'\n');print('REST REAUTHORED',body_end,flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--source-root',type=Path);ap.add_argument('--clearance',action='store_true');ap.add_argument('--polish',action='store_true');ap.add_argument('--returns',action='store_true');ap.add_argument('--rest',action='store_true');ap.add_argument('--metrics',action='store_true');ap.add_argument('--commands',nargs='+')
    args=ap.parse_args()
    if args.metrics:refresh_metrics(args.root,args.commands)
    elif args.rest:reauthor_rest(args.root)
    elif args.returns:restore_stand_returns(args.root,args.commands,args.source_root)
    elif args.polish:polish_clearance(args.root,args.commands,args.source_root)
    elif args.clearance:
        for command in args.commands:
            refit_internal_clearance(args.root,[command])
            polish_clearance(args.root,[command],args.source_root)
    else:remap(args.root,args.source_root)
