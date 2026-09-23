"""Check native recordings and Blender interpolation against measured geometry."""
from pathlib import Path
import json,hashlib
import numpy as np
from scipy.spatial.transform import Rotation
from retarget_clips import load_reference,LEGS,SOURCE_ORDER,write

def validate(root):
    cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);hulls=np.load(root/'motions/gestures/sit/posture-hulls.npz');pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);reports=[]
    for path in [root/'motions/gestures/crouch/source.json',*sorted((root/'motions/locomotion').glob('*/source.json'))]:
        source=json.loads(path.read_text());rows=source['samples'];m=ref.Mechanism(cfg);low=source['metadata']['native_initial_command']['gait']=='crawl'
        for name,expected in source['metadata']['native_sources_sha256'].items():
            # These files identify the historical recording implementation.
            # Geometry inputs stay pinned; current runtime is checked separately.
            if name not in ('motion.c','walk_kinematics.c'):assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,(path,name)
        if low:m.hulls={l:hulls['sole_'+l] for l in ref.LEGS}
        q=np.array([r['actuator_angles_rad'] for r in rows]);b=np.array([r['body_translation_world_mm'] for r in rows]);e=np.array([r['body_rotation_euler_xyz_rad'] for r in rows]);t=np.array([np.c_[r['target_foot_reference_xy_mm'],r['target_sole_clearance_mm']] for r in rows]);contact=np.array([r['contact_active'] for r in rows]);drift=0.
        for i in range(4):
            mask=contact[1:,i]&contact[:-1,i]
            if mask.any():drift=max(drift,float(abs(np.diff(t[:,i,:2],axis=0)[mask]).max()))
        minimum=1e9;body_min=1e9;closure=1e9;error=0.
        for angles,body,euler,target in zip((q[1:]+q[:-1])/2,(b[1:]+b[:-1])/2,(e[1:]+e[:-1])/2,(t[1:]+t[:-1])/2):
            m.body_euler=euler;B=Rotation.from_euler('xyz',euler).as_matrix();body_min=min(body_min,float(((hulls['body']-pivot)@B[2]+pivot[2]+body[2]).min()))
            for i,l in enumerate(LEGS):
                vs=m.vertices(l,angles[i],body);z=float(vs[:,2].min());minimum=min(minimum,z);closure=min(closure,m.planar(angles[i])[4]);point=np.r_[m.reference(l,angles[i],body)[:2],z];error=max(error,float(abs(point-target[i]).max()))
        report=dict(command=path.parent.name,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),samples=len(rows),planted_xy_drift_mm=drift,minimum_interpolated_sole_z_mm=minimum,minimum_body_z_mm=body_min,minimum_closure_height_mm=float(closure),maximum_interpolated_target_error_mm=error,hardware_qualified=False)
        print(report,flush=True);assert drift<1e-8 and minimum>-.25 and body_min>0 and closure>0 and error<.5,report;reports.append(report)
    write(root/'motions/locomotion/validation.json',dict(commands=reports,hardware_qualified=False,scope='Recorded native trajectories and linear Blender midpoints; not physical tracking, collision or load qualification.'))
if __name__=='__main__':validate(Path(__file__).resolve().parents[1])
