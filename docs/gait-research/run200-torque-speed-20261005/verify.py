"""Independent numerical virtual-work checks at sampled full-motion poses."""
import json
import numpy as np
import analyze as a

def rotation(angle,axis):
    c,s=np.cos(angle),np.sin(angle)
    if axis==0:return np.array([[1,0,0],[0,c,-s],[0,s,c]])
    if axis==1:return np.array([[c,0,s],[0,1,0],[-s,0,c]])
    return np.array([[c,-s,0],[s,c,0],[0,0,1]])

def fk(q,euler,leg,A,r,b,L,contact=None):
    p=a.fa.P;g=a.fa.G['legs'][a.fa.CAD[leg]]
    ca=q[1]+p['alpha_neutral'];ct=q[2]+p['new_theta_neutral']
    D=np.array(p['O'])+A*np.array([np.cos(ca),np.sin(ca)])
    P=np.array(p['C_new'])+r*np.array([np.cos(ct),np.sin(ct)])
    v=P-D;distance=np.linalg.norm(v)
    beta=np.arctan2(v[1],v[0])+np.arccos((b*b+distance*distance-L*L)/(2*b*distance))
    S=np.array(g['shoulder_world']);M=np.array(g['mechanism_local'])
    body=rotation(euler[2],2)@rotation(euler[1],1)@rotation(euler[0],0)
    shoulder=body@np.diag(np.round(np.diag(S[:3,:3])))
    H=shoulder@rotation(q[0],0);R=H@np.diag([round(M[0,0]),1,1]);lower=rotation(p['beta_neutral']-beta,1)
    if contact is None:
        sole=np.array(g['sole_hull_local_mm']);contact=sole[np.argmin(sole@(R@lower)[2,:])]
    world=H@M[:3,3]+R@(np.array([D[0],0,D[1]])+lower@contact)
    return world*.001,contact

errors=[];records=[]
data=json.loads((a.ROOT/'results.json').read_text())
winners=json.loads((a.ROOT/'winners.json').read_text())
geometries={(40,24,24,38),(35,20,28,38),(40,24,24,41),(40,32,36,38),(40,32,36,41)}
geometries.update((x['carrier_mm'],x['crank_mm'],x['pickup_mm'],x['rod_mm']) for x in winners)
for A,r,b,L in sorted(geometries):
    s=a.setup(A);q,qd,torque,plus,minus=a.candidate(s,A,r,b,L)
    u=torque/a.STALL+abs(qd)/600
    worst=np.unravel_index(u.argmax(),u.shape)
    indices=set(np.linspace(0,len(q)-1,17,dtype=int).tolist()+[int(worst[0])])
    error=0.
    for k in sorted(indices):
        for leg in range(4):
            _,point=fk(q[k,leg],s['f'][k,6:9],leg,A,r,b,L)
            jac=np.empty((3,3));eps=1e-6
            for j in range(3):
                qp=q[k,leg].copy();qm=qp.copy();qp[j]+=eps;qm[j]-=eps
                jac[:,j]=(fk(qp,s['f'][k,6:9],leg,A,r,b,L,point)[0]-fk(qm,s['f'][k,6:9],leg,A,r,b,L,point)[0])/(2*eps)
            load=a.MASS*a.GRAVITY*s['ground'][k,leg]/max(1,s['ground'][k].sum())
            expected=(abs(jac[2])+0.2*abs(jac[0]))*load
            error=max(error,float(abs(expected-torque[k,leg]).max()))
    assert error<1e-7
    records.append(dict(geometry=[A,r,b,L],poses_per_leg=len(indices),max_torque_difference_Nm=error))
print(json.dumps(records,indent=2))
(a.ROOT/'independent_checks.json').write_text(json.dumps(records,indent=2))
convergence=[]
for A,r,b,L in [(40,24,24,38),(35,28,36,38),(40,32,36,38)]:
    scores=[]
    for step in [1000,250]:
        s=a.setup(A,step=step);q,qd,t,p,m=a.candidate(s,A,r,b,L)
        scores.append(a.score(s,q,qd,t,p,m,600,1.8,1,'symmetric')['utilization'])
    difference=abs(scores[1]/scores[0]-1)
    assert difference<.01
    convergence.append(dict(geometry=[A,r,b,L],utilization_1ms=scores[0],utilization_025ms=scores[1],relative_difference=difference))
(a.ROOT/'sampling_convergence.json').write_text(json.dumps(convergence,indent=2))
