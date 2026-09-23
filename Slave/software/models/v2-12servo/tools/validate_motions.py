"""Validate updated finite clips at every knot and halfway between knots.

Includes the firmware's monotone cubic and Blender's linear joint interpolation.
No physical stability or surface-collision qualification is inferred.
"""
from pathlib import Path
import hashlib,importlib.util,json
import numpy as np
from scipy.spatial.transform import Rotation
from retarget_clips import load_reference,LEGS,SOURCE_ORDER,write

def validate(root,commands=None):
    cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);m=ref.Mechanism(cfg)
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);hull=np.array(cfg['current_body_hull_local_mm']);results=[]
    for family in ['turns','gestures']:
        catalog_path=root/'motions'/family/'catalog.json';catalog=json.loads(catalog_path.read_text())
        for item in catalog['commands']:
            if commands and item['command'] not in commands:continue
            m=ref.Mechanism(cfg);hull=np.array(cfg['current_body_hull_local_mm'])
            folder=catalog_path.parent/item['path']
            if (folder/'posture.json').exists():
                posture=json.loads((folder/'posture.json').read_text());p=folder/posture['contact_hulls_file']
                assert hashlib.sha256(p.read_bytes()).hexdigest()==posture['contact_hulls_sha256']
                current=np.load(p);m.hulls={l:current['sole_'+l] for l in ref.LEGS};hull=current['body']
            source=json.loads((folder/'source.json').read_text());rows=source['samples'];q=np.array([x['actuator_angles_rad'] for x in rows]);body=np.array([x['body_translation_world_mm'] for x in rows]);e=np.array([x['body_rotation_euler_xyz_rad'] for x in rows]);targets=np.array([np.c_[x['target_foot_reference_xy_mm'], x['target_sole_clearance_mm']] for x in rows])
            slopes=np.diff(q,axis=0)*120;v=np.zeros_like(q);a,b=slopes[:-1],slopes[1:];same=a*b>0;v[1:-1][same]=2*a[same]*b[same]/(a[same]+b[same]);linear=(q[:-1]+q[1:])/2;cubic=linear+(v[:-1]-v[1:])/(8*120)
            report={'command':item['command'],'geometry_id':cfg['geometry_id'],'source_sha256':hashlib.sha256((folder/'source.json').read_bytes()).hexdigest(),'samples':len(rows),'hardware_qualified':False,'collision_checked':False,'interpolators':{}}
            for name,poses,bs,es,ts in [('source',q,body,e,targets),('native_monotone_cubic_midpoints',cubic,(body[:-1]+body[1:])/2,(e[:-1]+e[1:])/2,(targets[:-1]+targets[1:])/2),('blender_linear_midpoints',linear,(body[:-1]+body[1:])/2,(e[:-1]+e[1:])/2,(targets[:-1]+targets[1:])/2)]:
                ground=float('inf');closure=float('inf');error=0.;body_ground=float('inf')
                for angles,translation,euler,target in zip(poses,bs,es,ts):
                    m.body_euler=euler;B=Rotation.from_euler('xyz',euler).as_matrix();body_ground=min(body_ground,float(((hull-pivot)@B[2]+pivot[2]+translation[2]).min()))
                    for i,leg in enumerate(LEGS):
                        vs=m.vertices(leg,angles[i],translation);z=float(vs[:,2].min());xy=m.reference(leg,angles[i],translation)[:2];ground=min(ground,z);closure=min(closure,m.planar(angles[i])[4]);error=max(error,float(np.max(np.abs(np.r_[xy,z]-target[i]))))
                report['interpolators'][name]={'poses':len(poses),'minimum_sole_z_mm':ground,'minimum_body_z_mm':body_ground,'minimum_closure_height_mm':closure,'maximum_interpolated_target_error_mm':error}
                assert ground>-.25 and body_ground>-.05 and closure>0 and error<.5,(item['command'],name,report['interpolators'][name])
            write(folder/'interpolation-validation.json',report)
            if 'sha256' in item:item['sha256']['interpolation-validation.json']=hashlib.sha256((folder/'interpolation-validation.json').read_bytes()).hexdigest()
            results.append(report);print(item['command'],report['interpolators'],flush=True)
        write(catalog_path,catalog)
    aggregate=root/'motions/interpolation-validation.json'
    if commands and aggregate.exists():
        old=json.loads(aggregate.read_text())['commands'];updated={x['command']:x for x in results};results=[updated.get(x['command'],x) for x in old]
    write(aggregate,{'geometry_id':cfg['geometry_id'],'commands':results,'hardware_qualified':False})
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--commands',nargs='+');args=parser.parse_args()
    validate(Path(__file__).resolve().parents[1],args.commands)
