import sys,json,math
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parent));import screen as s
fa=s.fa
def fk(q,euler,leg,r,b,L=38,point=None,hull=None):
    a=q[1]+fa.P['alpha_neutral'];theta=q[2]+fa.P['new_theta_neutral'];D=fa.O+40*fa.unit(a);P=fa.C+r*fa.unit(theta);v=P-D;d=np.linalg.norm(v);along=(b*b-L*L+d*d)/(2*d)
    E=D+(along*v+math.sqrt(b*b-along*along)*fa.perp(v))/d;beta=math.atan2(*(E-D)[::-1])
    def rz(x):return np.array([[math.cos(x),-math.sin(x),0],[math.sin(x),math.cos(x),0],[0,0,1]])
    S=np.array(fa.G['legs'][fa.CAD[leg]]['shoulder_world']);M=np.array(fa.G['legs'][fa.CAD[leg]]['mechanism_local']);R=rz(euler[2])@fa.ry(euler[1])@fa.rx(euler[0])@np.diag(np.round(np.diag(S[:3,:3])))@fa.rx(q[0]);base=R@np.diag([round(M[0,0]),1,1]);lower=fa.ry(fa.BETA0-beta)
    if point is None:
        if hull is None:hull=np.array(fa.G['legs'][fa.CAD[leg]]['sole_hull_local_mm'])
        point=hull[np.argmin(hull@(base@lower)[2,:])]
    world=R@M[:3,3]+base@(np.array([D[0],0,D[1]])+lower@point)
    return world*.001,point,beta

def joint_for(q,r,b,L=38):
    D,beta,*_=fa.planar(np.array(q),40);E=D+b*fa.unit(beta);v=E-fa.C;d=np.linalg.norm(v,axis=-1);theta=np.arctan2(v[...,1],v[...,0])-np.arccos((r*r+d*d-L*L)/(2*r*d));out=np.array(q).copy();out[...,2]=theta-fa.P['new_theta_neutral'];return out

def jac(q,e,leg,r,b,hull=None):
    _,point,_=fk(q,e,leg,r,b,hull=hull);J=np.zeros((3,3));eps=1e-6
    for j in range(3):
        p=q.copy();n=q.copy();p[j]+=eps;n[j]-=eps;J[:,j]=(fk(p,e,leg,r,b,point=point)[0]-fk(n,e,leg,r,b,point=point)[0])/(2*eps)
    return J

if __name__=='__main__':
    data=s.collect();m=dict(np.load(s.OUT/'mechanical.npz'));results=[]
    contact=json.loads((s.MODEL/'motions/locomotion/contact-hulls.json').read_text());crab=np.load(s.MODEL/'motions/gestures/reviewed-hulls.npz')
    seed=s.prior.setup(40);fine=s.prior.setup(40,step=250)
    for r,b in [(24,24),(32,36),(24,26),(26,28),(28,30),(28,31),(29,32),(30,34)]:
        z=s.evaluate(data,m,r,b,detail=True);q=z.pop('q');qd=z.pop('qd');tau=z.pop('tau');P=z.pop('P');E=z.pop('E');errors=[];position_error=0;gc=int(data['gait_count'])
        for group in range(18):
            ids=np.flatnonzero(data['group']==group);chosen=ids[np.linspace(0,len(ids)-1,5,dtype=int)]
            for idx in chosen:
                for leg in range(4):
                    key=fa.CAD[leg];kind=data['kinds'][group];hull=np.array(contact['soles'][key] if kind=='crawl' else crab['sole_'+key] if kind=='crab' else fa.G['legs'][key]['sole_hull_local_mm'])
                    J=jac(q[idx,leg],data['euler'][idx],leg,r,b,hull);load=.512*9.80665*data['ground'][idx,leg]/max(1,data['ground'][idx].sum());expected=(abs(J[2])+.2*abs(J[0]))*load;errors.append(float(abs(expected-tau[idx,leg]).max()))
        # All clip types and locomotion groups: independently compare unchanged material points.
        for group in range(len(data['names'])):
            ids=np.flatnonzero(data['group']==group)
            for idx in ids[np.linspace(0,len(ids)-1,5,dtype=int)]:
                for leg in range(4):
                    for point in [np.zeros(3),np.array([17.,-3.,-45.])]:
                        old=fk(data['q'][idx,leg],data['euler'][idx],leg,24,24,point=point)[0];new=fk(q[idx,leg],data['euler'][idx],leg,r,b,point=point)[0];position_error=max(position_error,float(np.linalg.norm(old-new)*1000))
        assert max(errors)<1e-7 and position_error<1e-6,(errors,position_error)
        z['independent_torque_error_Nm']=max(errors);z['independent_material_point_error_mm']=position_error
        standq=joint_for(np.zeros((4,3)),r,b);stand=[]
        for leg in range(4):
            J=jac(standq[leg],np.zeros(3),leg,r,b);stand.append((abs(J[2])*.512*9.80665/4/.0980665).tolist())
        z['standing_vertical_four_feet_kgcm']=np.max(stand,axis=0).tolist()
        z['standing_with_horizontal_20pct_kgcm']=(tau[0].max(axis=0)/.0980665).tolist()
        run=[]
        for runseed in [seed,fine]:
            cq,cv,ct,cp,cm=s.prior.candidate(runseed,40,r,b,38);score=s.prior.score(runseed,cq,cv,ct,cp,cm,600,1.8,1,'symmetric')
            run.append(dict(score=score['utilization'],peak_speed_deg_s=abs(cv).max(axis=(0,1)).tolist(),peak_torque_kgcm=(ct.max(axis=(0,1))/.0980665).tolist()))
        z['run200_1ms_025ms']=run
        native=s.prior.sample(40,r,b,38);nq,ng=s.prior.unpack(native);eq,*_=s.prior.candidate(seed,40,r,b,38)
        assert len(nq)==len(eq)
        z['native_Run200_max_angle_error_deg']=float(abs((nq-eq+np.pi)%(2*np.pi)-np.pi).max()*180/np.pi)
        assert z['native_Run200_max_angle_error_deg']<.002
        results.append(z);print(r,b,'stand',np.round(z['standing_vertical_four_feet_kgcm'],4),'Run200',run[-1]['score'],'verified',flush=True)
    (s.OUT/'verified.json').write_text(json.dumps(results,indent=2))
