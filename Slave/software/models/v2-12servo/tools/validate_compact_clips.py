"""Desktop full-sole comparison of compact playback against retained recordings.

Run after the native source/derivative tests. Requires NumPy. This checks the
resulting CAD clearance differences; it does not establish hardware clearance.
"""
import argparse,importlib.util,json,math,subprocess
from pathlib import Path
import numpy as np


def rotations(angles,axis):
    result=np.zeros((len(angles),3,3));c,s=np.cos(angles),np.sin(angles)
    other=[i for i in range(3) if i!=axis];a,b=other
    if axis==1:s=-s
    result[:,axis,axis]=1;result[:,a,a]=result[:,b,b]=c
    result[:,a,b]=-s;result[:,b,a]=s
    return result


def transform(cfg,leg,q):
    p=cfg['parameters'];g=cfg['legs'][leg]
    O,C=np.array(p['O']),np.array(p['C_new']);a=q[:,1]+p['alpha_neutral'];t=q[:,2]+p['new_theta_neutral']
    D=O+p['primary_length']*np.c_[np.cos(a),np.sin(a)]
    P=C+p['input_length']*np.c_[np.cos(t),np.sin(t)]
    w=P-D;d2=np.sum(w*w,axis=1);along=(p['pickup_length']**2-p['rod_length']**2+d2)/(2*d2)
    height2=p['pickup_length']**2/d2-along**2
    assert height2.min()>0
    E=D+along[:,None]*w+p['assembly_branch']*np.sqrt(height2)[:,None]*np.c_[-w[:,1],w[:,0]]
    beta=np.arctan2(E[:,1]-D[:,1],E[:,0]-D[:,0])-p['beta_neutral']
    S,M=np.array(g['shoulder_world']),np.array(g['mechanism_local'])
    shoulder=S[:3,:3]@rotations(q[:,0],0);base=shoulder@M[:3,:3]
    offset=S[:3,3]+np.einsum('nij,j->ni',shoulder,M[:3,3])+np.einsum('nij,nj->ni',base,np.c_[D[:,0],np.zeros(len(D)),D[:,1]])
    return base@rotations(-beta,1),offset,float((np.sqrt(height2*d2)).min())


def main(root,binary):
    cfg=json.loads((root/'geometry.json').read_text());results=[]
    catalog=json.loads((root/'motions/gestures'/'catalog.json').read_text())
    for item in catalog['commands']:
        folder=root/'motions/gestures'/item['path'];manifest=json.loads((folder/'manifest.json').read_text())
        reference=folder/'sample_reference.py'
        spec=importlib.util.spec_from_file_location('clip_reference',reference);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);motion=module.Motion(folder)
        duration=round(manifest.get('semantic_end_seconds',manifest['duration_seconds'])*1e6)
        count=round(duration*120/1e6);times=sorted({round((i+f)*1e6/120) for i in range(count) for f in (0,.371)}|{duration})
        data=subprocess.run([str(binary)],input=''.join(f'{item["command"]} {t}\n' for t in times),text=True,capture_output=True,check=True)
        actual=np.array([json.loads(line)['position'] for line in data.stdout.splitlines()]).reshape(-1,4,3)*math.pi/18000
        expected=np.array([motion.sample(t)['position'] for t in times]).reshape(-1,4,3)*math.pi/18000
        source=json.loads((folder/'source.json').read_text())['samples']
        # Body orientation is identical; interpolate only to evaluate the
        # direction of gravity between source knots.
        orientation=np.array([s['body_rotation_euler_xyz_rad'] for s in source])
        u=np.asarray(times)*120/1e6;lo=np.minimum(u.astype(int),len(source)-2);f=u-lo
        e=orientation[lo]*(1-f[:,None])+orientation[lo+1]*f[:,None]
        body=rotations(e[:,2],2)@rotations(e[:,1],1)@rotations(e[:,0],0)
        posture=folder/'posture.json';hulls=None
        if posture.exists():hulls=np.load(folder/json.loads(posture.read_text())['contact_hulls_file'])
        vertex_error=0.;floor_error=0.;closure=math.inf
        for i,leg in enumerate(('FL','FR','RL','RR')):
            points=np.array(hulls['sole_'+leg] if hulls is not None else cfg['legs'][leg]['sole_hull_local_mm'])
            oldR,oldT,margin=transform(cfg,leg,expected[:,i]);newR,newT,newmargin=transform(cfg,leg,actual[:,i]);closure=min(closure,margin,newmargin)
            deltaR=newR-oldR;deltaT=newT-oldT
            for start in range(0,len(times),128):
                end=start+128
                delta=np.einsum('nkj,vj->nvk',deltaR[start:end],points)+deltaT[start:end,None,:]
                vertex_error=max(vertex_error,float(np.linalg.norm(delta,axis=2).max()))
                oldWorld=body[start:end]@oldR[start:end];newWorld=body[start:end]@newR[start:end]
                oldZ=np.einsum('nj,vj->nv',oldWorld[:,2],points)+np.einsum('nj,nj->n',body[start:end,2],oldT[start:end])[:,None]
                newZ=np.einsum('nj,vj->nv',newWorld[:,2],points)+np.einsum('nj,nj->n',body[start:end,2],newT[start:end])[:,None]
                floor_error=max(floor_error,float(abs(newZ.min(1)-oldZ.min(1)).max()))
        row=dict(command=item['command'],samples=len(times),max_sole_vertex_error_mm=vertex_error,max_sole_clearance_change_mm=floor_error,min_closure_height_mm=closure)
        assert vertex_error<.1 and floor_error<.1,row
        results.append(row)
    print(json.dumps(dict(samples=sum(r['samples'] for r in results),maximum_vertex_error_mm=max(r['max_sole_vertex_error_mm'] for r in results),maximum_clearance_change_mm=max(r['max_sole_clearance_change_mm'] for r in results),commands=results),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--binary',type=Path,required=True);a=parser.parse_args();main(a.root,a.binary)
