"""Check native recordings and Blender interpolation against measured geometry."""
from pathlib import Path
import json,hashlib
import numpy as np
from scipy.spatial.transform import Rotation
from retarget_clips import load_reference,LEGS,SOURCE_ORDER,write

def leverage_report(cfg,q,contact,limits):
    """Offline gait gate, including linear joint midpoints.

    Planned contact determines the stronger stance margin. This does not
    estimate measured foot load or change the firmware/calibration mapping.
    """
    import numpy as np
    q=np.asarray(q);contact=np.asarray(contact,dtype=bool)
    if q.shape != (len(q),4,3) or contact.shape != q.shape[:2] or not len(q):
        raise ValueError('Invalid gait samples')
    q=np.concatenate((q,(q[:-1]+q[1:])*.5))
    contact=np.concatenate((contact,contact[:-1]|contact[1:]))
    p=cfg['parameters'];a=p['alpha_neutral']+q[:,:,1];t=p['new_theta_neutral']+q[:,:,2]
    D=np.array(p['O'])+p['primary_length']*np.stack((np.cos(a),np.sin(a)),axis=-1)
    P=np.array(p['C_new'])+p['input_length']*np.stack((np.cos(t),np.sin(t)),axis=-1)
    w=P-D;d=np.linalg.norm(w,axis=-1);b=p['pickup_length'];L=p['rod_length']
    if np.any(~np.isfinite(q)) or np.any(d<=abs(L-b)) or np.any(d>=L+b):
        raise ValueError('Gait reaches an impossible or straight four-bar pose')
    along=(b*b-L*L+d*d)/(2*d);height=np.sqrt(b*b-along*along)
    E=D+(along[...,None]*w+p['assembly_branch']*height[...,None]*np.stack((-w[:,:,1],w[:,:,0]),axis=-1))/d[...,None]
    rod=E-P;output=E-D;crank=P-p['C_new']
    def cross(x,y):return x[:,:,0]*y[:,:,1]-x[:,:,1]*y[:,:,0]
    branches=(cross(w,output),cross(E-p['C_new'],crank))
    if any(np.any(x*x[0]<=0.) for x in branches):
        raise ValueError('Gait crosses a linkage assembly branch')
    def angle(v):
        cosine=np.abs(np.sum(rod*v,axis=-1))/(L*np.linalg.norm(v,axis=-1))
        return np.rad2deg(np.arccos(np.clip(cosine,0,1)))
    result={'checked_leg_poses':int(q.shape[0]*4),'branch_reversals':0,
            'minimum_straightening_clearance_mm':float((L+b-d).min())}
    for name,angles in [('output',angle(output)),('input',angle(crank))]:
        for state,mask in [('stance',contact),('swing',~contact)]:
            if not mask.any():continue
            value=float(angles[mask].min());key=f'{state}_{name}_min_deg'
            result[key]=value
            if value<limits[key]:raise ValueError(f'Gait {key}: {value:.3f} < {limits[key]:g}')
    if result['minimum_straightening_clearance_mm']<limits['straightening_clearance_min_mm']:
        raise ValueError('Gait straightening clearance below regression margin')
    return result


def validate(root):
    cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);hulls=np.load(root/'motions/gestures/sit/posture-hulls.npz');pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);reports=[]
    for path in [root/'motions/gestures/crouch/source.json',*sorted((root/'motions/locomotion').glob('*/source.json'))]:
        source=json.loads(path.read_text());rows=source['samples'];m=ref.Mechanism(cfg);low=source['metadata']['native_initial_command']['gait']=='crawl'
        for name,expected in source['metadata']['native_sources_sha256'].items():
            # These files identify the historical recording implementation.
            # Geometry inputs stay pinned; current runtime is checked separately.
            # Crouch is a preserved compiled gesture, not regenerated locomotion.
            if path.parent.name=='crouch' and name=='motions/locomotion/config.json':continue
            if name not in ('motion.c','walk_kinematics.c'):assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,(path,name)
        if source['metadata']['native_initial_command']['gait']=='crab':
            hulls=np.load(root/'motions/gestures/reviewed-hulls.npz');m.hulls={l:hulls['sole_'+l] for l in ref.LEGS}
        else:hulls=np.load(root/'motions/gestures/sit/posture-hulls.npz')
        if low:m.hulls={l:hulls['sole_'+l] for l in ref.LEGS}
        q=np.array([r['actuator_angles_rad'] for r in rows]);b=np.array([r['body_translation_world_mm'] for r in rows]);e=np.array([r['body_rotation_euler_xyz_rad'] for r in rows]);t=np.array([np.c_[r['target_foot_reference_xy_mm'],r['target_sole_clearance_mm']] for r in rows]);contact=np.array([r['contact_active'] for r in rows]);drift=0.
        for i in range(4):
            mask=contact[1:,i]&contact[:-1,i]
            if mask.any():drift=max(drift,float(abs(np.diff(t[:,i,:2],axis=0)[mask]).max()))
        margins=leverage_report(cfg,q,contact,json.loads((root/'motions/locomotion/config.json').read_text())['leverage_validation'])
        minimum=1e9;body_min=1e9;closure=1e9;error=0.
        for angles,body,euler,target in zip((q[1:]+q[:-1])/2,(b[1:]+b[:-1])/2,(e[1:]+e[:-1])/2,(t[1:]+t[:-1])/2):
            m.body_euler=euler;B=Rotation.from_euler('xyz',euler).as_matrix();body_min=min(body_min,float(((hulls['body']-pivot)@B[2]+pivot[2]+body[2]).min()))
            for i,l in enumerate(LEGS):
                vs=m.vertices(l,angles[i],body);z=float(vs[:,2].min());minimum=min(minimum,z);closure=min(closure,m.planar(angles[i])[4]);point=np.r_[m.reference(l,angles[i],body)[:2],z];error=max(error,float(abs(point-target[i]).max()))
        report=dict(leverage=margins,command=path.parent.name,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),samples=len(rows),planted_xy_drift_mm=drift,minimum_interpolated_sole_z_mm=minimum,minimum_body_z_mm=body_min,minimum_closure_height_mm=float(closure),maximum_interpolated_target_error_mm=error,hardware_qualified=False)
        print(report,flush=True);assert drift<1e-8 and minimum>-.25 and body_min>0 and closure>0 and error<.5,report;reports.append(report)
    write(root/'motions/locomotion/validation.json',dict(commands=reports,hardware_qualified=False,scope='Recorded native trajectories and linear Blender midpoints; not physical tracking, collision or load qualification.'))
if __name__=='__main__':validate(Path(__file__).resolve().parents[1])
