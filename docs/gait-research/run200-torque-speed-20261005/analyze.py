"""Offline conditional minimax torque/speed screening, no robot interfaces.
Run with Python+numpy, a C11 compiler, and the supplied original study snapshot.
Outputs stay beside this script. No runtime or CAD settings are changed.
"""
from pathlib import Path
import csv, hashlib, importlib.util, itertools, json, os, subprocess, sys
import numpy as np

SOURCE=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('AINEKIO_LINKAGE_OUTPUT','/tmp/ainekio-torque-speed-20261005'))
ROOT.mkdir(parents=True,exist_ok=True)
STUDY=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/home/greggles/Downloads/Ainekio-Run200-Linkage-Study')
MODEL=STUDY/'Slave/software/models/v2-12servo'
spec=importlib.util.spec_from_file_location('fa',STUDY/'force_analysis.py');fa=importlib.util.module_from_spec(spec);spec.loader.exec_module(fa)
MASS=.512;GRAVITY=9.80665;STALL=1.8*.0980665
NAMES=['front_left','front_right','rear_left','rear_right'];JOINTS=['shoulder','carrier','crank']
CARRIERS=[35,36,37,37.5,38,39,40]
CASES=[(w,t,l) for w,t,l in [(600,1.8,1),(750,1.8,1),(900,1.8,1),(1200,1.8,1),(1500,1.8,1),(600,1.4,1),(600,2.2,1),(600,1.8,1.5)]]

def sample(A,r=24,b=24,L=38,step=1000):
    import re
    d=ROOT/f'native_A{A:g}_r{r:g}_b{b:g}_L{L:g}_{step}';d.mkdir(exist_ok=True)
    output=d/'samples.csv'
    if output.exists() and (d/'success').exists():return np.loadtxt(output,delimiter=',')
    h=(MODEL/'generated/walk_data.h').read_text()
    for name,value in [('PRIMARY',A),('INPUT',r),('PICKUP',b),('ROD',L)]:h=re.sub(r'#define V2_'+name+r' .*',f'#define V2_{name} ({value:.9e}f)',h)
    (d/'walk_data.h').write_text(h)
    cmd=['cc','-O2','-std=c11',f'-I{d}',f'-I{MODEL}/include',f'-I{MODEL}/generated',f'-I{STUDY}/Slave/software/core/include',str(SOURCE/'sample.c'),str(MODEL/'motion.c'),str(MODEL/'walk_kinematics.c'),str(MODEL/'generated/walk_data.c'),'-lm','-o',str(d/'sample')]
    subprocess.run(cmd,check=True,capture_output=True)
    with output.open('w') as f:result=subprocess.run([str(d/'sample'),str(step)],stdout=f,stderr=subprocess.PIPE,text=True)
    (d/'status.json').write_text(json.dumps({'returncode':result.returncode,'stderr':result.stderr}))
    if result.returncode:raise ValueError(result.stderr)
    (d/'success').touch();return np.loadtxt(output,delimiter=',')

def unpack(f):return f[:,[10,11,12,14,15,16,18,19,20,22,23,24]].reshape(-1,4,3),f[:,[9,13,17,21]].astype(bool)

def setup(A,step=1000):
    f=sample(A,step=step);q,ground=unpack(f)
    assert f[:,2].min()>.999999 and f[-1,4]==1
    fa.RR=fa.B=24;fa.ROD=38
    D,beta,ba,bt=fa.planar(q,A)
    # Full native Euler orientation, including preparation and Finish.
    roll,pitch,yaw=f[:,6],f[:,7],f[:,8]
    z=np.zeros((len(f),3,3));z[:,0,0]=z[:,1,1]=np.cos(yaw);z[:,0,1]=-np.sin(yaw);z[:,1,0]=np.sin(yaw);z[:,2,2]=1
    body=z@fa.ry(pitch)@fa.rx(roll)
    hs=[];aa=[];bb=[]
    for leg,key in enumerate(fa.CAD):
        S=np.array(fa.G['legs'][key]['shoulder_world']);M=np.array(fa.G['legs'][key]['mechanism_local'])
        Sr=np.diag(np.round(np.diag(S[:3,:3])));Mr=np.diag([round(M[0,0]),1,1]);sh=body@Sr;R=sh@fa.rx(q[:,leg,0])@Mr
        lower=fa.ry(-(beta[:,leg]-fa.BETA0));sole=np.array(fa.G['legs'][key]['sole_hull_local_mm']);idx=np.argmin((R@lower)[:,2,:]@sole.T,axis=1)
        v=fa.mv(lower,sole[idx]);knee=np.stack([D[:,leg,0],np.zeros(len(f)),D[:,leg,1]],axis=1)
        world=fa.mv(sh,fa.mv(fa.rx(q[:,leg,0]),np.broadcast_to(M[:3,3],(len(f),3))))+fa.mv(R,knee+v)
        hs.append(np.linalg.det(Sr)*np.cross(sh[:,:,0],world)*.001)
        a=q[:,leg,1]+fa.P['alpha_neutral']
        aa.append(fa.mv(R,np.stack([-A*np.sin(a),np.zeros(len(f)),A*np.cos(a)],axis=1))*.001)
        bb.append(fa.mv(R,np.stack([-v[:,2],np.zeros(len(f)),v[:,0]],axis=1))*.001)
    return dict(f=f,q=q,ground=ground,D=D,beta=beta,h=np.stack(hs,axis=1),a=np.stack(aa,axis=1),b=np.stack(bb,axis=1))

def candidate(s,A,r,b,L):
    E=s['D']+b*fa.unit(s['beta']);w=E-fa.C;d=np.linalg.norm(w,axis=-1);cost=(r*r+d*d-L*L)/(2*r*d)
    if np.any(abs(cost)>=1):raise ValueError('crank circle unreachable')
    theta=np.unwrap(np.arctan2(w[...,1],w[...,0])-np.arccos(cost),axis=0);P=fa.C+r*fa.unit(theta)
    branch=(P-s['D'])[...,0]*(E-s['D'])[...,1]-(P-s['D'])[...,1]*(E-s['D'])[...,0]
    if np.any(branch<=0):raise ValueError('assembly branch changed')
    gamma=np.arctan2((E-P)[...,1],(E-P)[...,0]);a=s['q'][:,:,1]+fa.P['alpha_neutral']
    ba=-A*np.sin(gamma-a)/(b*np.sin(gamma-s['beta']));bt=r*np.sin(gamma-theta)/(b*np.sin(gamma-s['beta']))
    J=np.stack([s['h'],s['a']+ba[...,None]*s['b'],bt[...,None]*s['b']],axis=-1)
    q=s['q'].copy();q[:,:,2]=theta-fa.P['new_theta_neutral'];qd=np.gradient(q,s['f'][:,0],axis=0)*180/np.pi
    # Worst robust horizontal force among Fx/Fz=-.2,0,+.2; torque and speed
    # are evaluated at the SAME sample and motor, including unloaded swings.
    count=s['ground'].sum(axis=1);load=MASS*GRAVITY*s['ground']/np.maximum(count[:,None],1)
    plus=-(J[:,:,2,:]+.2*J[:,:,0,:])*load[:,:,None]
    minus=-(J[:,:,2,:]-.2*J[:,:,0,:])*load[:,:,None]
    torque=np.maximum(abs(plus),abs(minus));speed=abs(qd)
    return q,qd,torque,plus,minus

def score(s,q,qd,torque,plus,minus,w0,stall_kgcm,mult,mode):
    ts=stall_kgcm*.0980665;v=abs(qd)/w0;t=torque*mult/ts
    if mode=='symmetric':u=t+v
    else:u=np.maximum.reduce([t,v,abs(plus*mult/ts+qd/w0),abs(minus*mult/ts+qd/w0)])
    k,l,j=np.unravel_index(np.argmax(u),u.shape)
    # Fraction of original timing that fits this envelope when only the
    # trajectory clock is scaled; contact load is unchanged, inertia omitted.
    if mode=='symmetric':cap=np.where(v>1e-10,(1-t)/np.maximum(v,1e-10),np.inf)
    else:
        signed=qd/w0;lo=np.minimum(plus,minus)*mult/ts;hi=np.maximum(plus,minus)*mult/ts
        cap=np.where(signed>1e-10,(1-hi)/np.maximum(signed,1e-10),np.where(signed< -1e-10,(1+lo)/np.maximum(-signed,1e-10),np.inf))
        cap=np.minimum(cap,np.where(v>1e-10,1/np.maximum(v,1e-10),np.inf))
    timing=0 if np.any(t>1) else max(0,float(cap.min()))
    steady=(s['f'][:,0]>=9)&(s['f'][:,0]<12)
    return dict(utilization=float(u.max()),margin=float(1-u.max()),phase=float(s['f'][k,1]%1),time_s=float(s['f'][k,0]),stage='finish' if s['f'][k,3] else ('steady_run' if s['f'][k,5]>.999999 else 'entry'),leg=NAMES[l],joint=JOINTS[j],torque_Nm=float(torque[k,l,j]*mult),speed_deg_s=float(abs(qd[k,l,j])),joint_utilization=u.max(axis=(0,1)).tolist(),timing_fraction_bound=timing,steady_utilization=float(u[steady].max()))

def main():
    for item in json.loads((STUDY/'SOURCE_MANIFEST.json').read_text()):
        raw=(STUDY/item['path']).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==item['git_blob_sha']
    previous=json.loads((ROOT/'results.json').read_text()) if (ROOT/'results.json').exists() else {}
    allrows=previous.get('results',[]);invalid=previous.get('invalid',[]);details=previous.get('geometry_metrics',{});validations=[]
    for A in CARRIERS:
        s=setup(A);print('carrier seed',A,'samples',len(s['f']),flush=True)
        combinations=set(itertools.product(range(20,25),range(24,29),[38,41]))|set(itertools.product(range(20,33,2),range(28,37,2),[38,41]))
        for r,b,L in sorted(combinations):
            identity=dict(carrier_mm=A,crank_mm=r,pickup_mm=b,rod_mm=L,distal_mm=55)
            key=f'{A:g}/{r}/{b}/{L}'
            if key in details or any(all(x.get(k)==v for k,v in identity.items()) for x in invalid):continue
            try:q,qd,torque,plus,minus=candidate(s,A,r,b,L)
            except ValueError as e:invalid.append(dict(identity,reason=str(e)));continue
            metrics=dict(identity,peak_speed_deg_s=float(abs(qd).max()),maximum_motor_span_deg=float(np.ptp(q*180/np.pi,axis=0).max()),peak_torque_Nm=float(torque.max()),peak_by_joint_Nm=torque.max(axis=(0,1)).tolist(),peak_speed_by_joint_deg_s=abs(qd).max(axis=(0,1)).tolist())
            for w,ts,lm in CASES:
                for mode in ['symmetric','signed_dc']:
                    result=score(s,q,qd,torque,plus,minus,w,ts,lm,mode)
                    row=dict(identity,w0_deg_s=w,stall_kgcm=ts,load_multiplier=lm,envelope=mode,**result);allrows.append(row)
            details[key]=metrics
        print('candidates',len(details),'invalid',len(invalid),flush=True)
    (ROOT/'results.json').write_text(json.dumps(dict(method='simultaneous minimax conditional envelopes',mass_kg=MASS,cases=CASES,results=allrows,geometry_metrics=details,invalid=invalid),indent=2))
    with (ROOT/'ranking.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
    finalists=set(['40/24/24/38','35/20/28/38','37.5/24/28/38','40/24/24/41','40/32/36/38','40/32/36/41','37.5/30/36/38'])
    winners=[]
    for w,ts,lm in CASES:
        for mode in ['symmetric','signed_dc']:
            for L in [38,41]:
                rows=[x for x in allrows if (x['w0_deg_s'],x['stall_kgcm'],x['load_multiplier'],x['envelope'],x['rod_mm'])==(w,ts,lm,mode,L)]
                best=min(rows,key=lambda x:x['utilization']);winners.append(best);finalists.add(f"{best['carrier_mm']:g}/{best['crank_mm']}/{best['pickup_mm']}/{L}")
    for key in sorted(finalists):
        A,r,b,L=map(float,key.split('/'));s=setup(A);q,*_=candidate(s,A,r,b,L)
        try:
            native=sample(A,r,b,L);nq,ng=unpack(native)
            assert native.shape==s['f'].shape and np.array_equal(ng,s['ground'])
            err=float(np.max(abs((nq-q+np.pi)%(2*np.pi)-np.pi))*180/np.pi)
            assert err<.002
            validations.append(dict(geometry=key,native_completed=True,maximum_angle_error_deg=err))
        except (ValueError,AssertionError) as e:validations.append(dict(geometry=key,native_completed=False,reason=str(e)))
        print('native',validations[-1],flush=True)
    (ROOT/'winners.json').write_text(json.dumps(winners,indent=2));(ROOT/'native_validation.json').write_text(json.dumps(validations,indent=2))
    print('complete',len(details),'valid candidates;',len(invalid),'rejected geometry paths',flush=True)
if __name__=='__main__':main()
