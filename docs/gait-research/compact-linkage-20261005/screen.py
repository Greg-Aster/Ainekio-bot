"""Offline compact linkage comparison; never connects to hardware or edits CAD."""
import json, math, subprocess, importlib.util, sys
from pathlib import Path
import numpy as np

ROOT=Path('/home/greggles/Ainekio'); OUT=Path('/tmp/ainekio-compact-linkage')
MODEL=ROOT/'Slave/software/models/v2-12servo'
spec=importlib.util.spec_from_file_location('prior',ROOT/'docs/gait-research/run200-torque-speed-20261005/analyze.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior);fa=prior.fa

def collect():
    cache=OUT/'poses.npz'
    if cache.exists():
        data=np.load(cache);return {k:data[k] for k in data.files}
    groups=[];names=[];kinds=[];q=[];times=[];ground=[];euler=[]
    for gait in ['walk','run','crawl','crab']:
        for direction in (['fwd','back','turn_l','turn_r','side_l','side_r'] if gait=='crab' else ['fwd','back','turn_l','turn_r']):
            cmd=dict(t='intent',seq=1,name='walk',dir=direction,gait=gait,steps=0,speed=25)
            speeds=[50,100,150,200] if gait in ['walk','run'] else [50,100]
            wire=json.dumps(cmd)+'\n'
            for i,speed in enumerate(speeds+[0]):
                wire+=f'{(i+1)*6000} '+json.dumps(dict(cmd,seq=i+2,speed=speed,update=1))+'\n'
            p=subprocess.run([str(OUT/'native/v2_walk_command'),'50000','120','20000'],input=wire,capture_output=True,text=True)
            if p.returncode:raise RuntimeError((gait,direction,p.stderr))
            rows=[json.loads(x) for x in p.stdout.splitlines()]
            assert rows[-1]['complete'] and min(x['clock_scale'] for x in rows)>.9999
            n=len(rows);groups.extend([len(names)]*n);names.append(gait+'/'+direction);kinds.append(gait)
            q.extend(np.array([x['q'] for x in rows]).reshape(-1,4,3));times.extend([x['ms']/1000 for x in rows]);ground.extend([x['grounded'] for x in rows]);euler.extend([x['euler'] for x in rows])
            print(names[-1],n,flush=True)
    gait_count=len(q)
    for item in json.loads((MODEL/'motions/gestures/catalog.json').read_text())['commands']:
        manifest=json.loads((MODEL/'motions/gestures'/item['path']/'manifest.json').read_text())
        duration=round(manifest.get('semantic_end_seconds',manifest['duration_seconds'])*1e6)
        ts=np.unique(np.r_[np.arange(0,duration,round(1e6/120)),duration]).astype(int)
        p=subprocess.run([str(OUT/'native/v2_clip_sample')],input=''.join(f'{item["command"]} {t}\n' for t in ts),text=True,capture_output=True,check=True)
        qs=np.array([json.loads(x)['position'] for x in p.stdout.splitlines()]).reshape(-1,4,3)*np.pi/18000
        n=len(qs);groups.extend([len(names)]*n);names.append('clip/'+item['command']);kinds.append('clip');q.extend(qs);times.extend(ts/1e6);ground.extend(np.zeros((n,4),bool));euler.extend(np.zeros((n,3)))
        print(names[-1],n,flush=True)
    data=dict(q=np.array(q),time=np.array(times),ground=np.array(ground),euler=np.array(euler),group=np.array(groups),names=np.array(names),kinds=np.array(kinds),gait_count=np.array(gait_count))
    np.savez_compressed(cache,**data);return data

def mechanical(data):
    q=data['q'];D,beta,ba,bt=fa.planar(q,40)
    a=q[...,1]+fa.P['alpha_neutral']
    gc=int(data['gait_count']);qg=q[:gc];eg=data['euler'][:gc]
    yaw=eg[:,2];z=np.zeros((gc,3,3));z[:,0,0]=z[:,1,1]=np.cos(yaw);z[:,0,1]=-np.sin(yaw);z[:,1,0]=np.sin(yaw);z[:,2,2]=1
    body=z@fa.ry(eg[:,1])@fa.rx(eg[:,0]);hs=[];aa=[];bb=[]
    contact=json.loads((MODEL/'motions/locomotion/contact-hulls.json').read_text());crab=np.load(MODEL/'motions/gestures/reviewed-hulls.npz')
    for leg,key in enumerate(fa.CAD):
        S=np.array(fa.G['legs'][key]['shoulder_world']);M=np.array(fa.G['legs'][key]['mechanism_local']);Sr=np.diag(np.round(np.diag(S[:3,:3])));Mr=np.diag([round(M[0,0]),1,1]);sh=body@Sr;R=sh@fa.rx(qg[:,leg,0])@Mr
        lower=fa.ry(-(beta[:gc,leg]-fa.BETA0));v=np.empty((gc,3))
        for group in range(len(data['names'])):
            kind=data['kinds'][group]
            if kind=='clip':continue
            ids=np.flatnonzero(data['group'][:gc]==group)
            sole=np.array(contact['soles'][key] if kind=='crawl' else crab['sole_'+key] if kind=='crab' else fa.G['legs'][key]['sole_hull_local_mm'])
            for start in range(0,len(ids),256):
                ii=ids[start:start+256];idx=np.argmin((R[ii]@lower[ii])[:,2,:]@sole.T,axis=1);v[ii]=fa.mv(lower[ii],sole[idx])
        knee=np.stack([D[:gc,leg,0],np.zeros(gc),D[:gc,leg,1]],axis=1)
        world=fa.mv(sh,fa.mv(fa.rx(qg[:,leg,0]),np.broadcast_to(M[:3,3],(gc,3))))+fa.mv(R,knee+v)
        hs.append(np.linalg.det(Sr)*np.cross(sh[:,:,0],world)*.001)
        aa.append(fa.mv(R,np.stack([-40*np.sin(a[:gc,leg]),np.zeros(gc),40*np.cos(a[:gc,leg])],axis=1))*.001)
        bb.append(fa.mv(R,np.stack([-v[:,2],np.zeros(gc),v[:,0]],axis=1))*.001)
    return dict(D=D,beta=beta,a=a,h=np.stack(hs,axis=1),aJ=np.stack(aa,axis=1),bJ=np.stack(bb,axis=1))

def evaluate(data,m,r,b,L=38,detail=False):
    E=m['D']+b*fa.unit(m['beta']);w=E-fa.C;d=np.linalg.norm(w,axis=-1);cost=(r*r+d*d-L*L)/(2*r*d)
    bad=abs(cost)>=1
    if np.any(bad):
        groups=np.unique(data['group'][np.where(bad)[0]])
        return dict(crank=r,pickup=b,rod=L,valid=False,reason='unreachable',failed_groups=data['names'][groups].tolist())
    theta=np.arctan2(w[...,1],w[...,0])-np.arccos(cost);P=fa.C+r*fa.unit(theta)
    branch=(P-m['D'])[...,0]*(E-m['D'])[...,1]-(P-m['D'])[...,1]*(E-m['D'])[...,0]
    if np.any(branch<=0):
        groups=np.unique(data['group'][np.where(branch<=0)[0]])
        return dict(crank=r,pickup=b,rod=L,valid=False,reason='assembly branch changed',failed_groups=data['names'][groups].tolist())
    q=data['q'].copy();q[:,:,2]=theta-fa.P['new_theta_neutral'];qd=np.empty_like(q)
    for group in range(len(data['names'])):
        ids=np.flatnonzero(data['group']==group);q[ids]=np.unwrap(q[ids],axis=0);qd[ids]=np.gradient(q[ids],data['time'][ids],axis=0)*180/np.pi
    gamma=np.arctan2((E-P)[...,1],(E-P)[...,0]);ba=-40*np.sin(gamma-m['a'])/(b*np.sin(gamma-m['beta']));bt=r*np.sin(gamma-theta)/(b*np.sin(gamma-m['beta']))
    gc=int(data['gait_count']);J=np.stack([m['h'],m['aJ']+ba[:gc,...,None]*m['bJ'],bt[:gc,...,None]*m['bJ']],axis=-1)
    gr=data['ground'][:gc];load=.512*9.80665*gr/np.maximum(gr.sum(axis=1)[:,None],1)
    plus=-(J[:,:,2,:]+.2*J[:,:,0,:])*load[:,:,None];minus=-(J[:,:,2,:]-.2*J[:,:,0,:])*load[:,:,None];tau=np.maximum(abs(plus),abs(minus));v=abs(qd[:gc]);u=tau/(1.8*.0980665)+v/600
    idx=np.unravel_index(np.argmax(u),u.shape)
    steady={}
    for name,mask in [('all_gaits',np.ones(gc,bool)),('walk',np.isin(data['group'][:gc],np.flatnonzero(data['kinds']=='walk'))),('run',np.isin(data['group'][:gc],np.flatnonzero(data['kinds']=='run'))),('crawl',np.isin(data['group'][:gc],np.flatnonzero(data['kinds']=='crawl'))),('crab',np.isin(data['group'][:gc],np.flatnonzero(data['kinds']=='crab')))]:
        steady[name]=dict(peak_torque_kgcm=(tau[mask].max(axis=(0,1))/.0980665).tolist(),peak_speed_deg_s=v[mask].max(axis=(0,1)).tolist(),worst_utilization=float(u[mask].max()))
    result=dict(crank=r,pickup=b,rod=L,valid=True,score=float(u.max()),worst_group=str(data['names'][data['group'][idx[0]]]),worst_time=float(data['time'][idx[0]]),worst_joint=prior.JOINTS[idx[2]],metrics=steady,peak_clip_speed_deg_s=abs(qd[gc:]).max(axis=(0,1)).tolist(),max_crank_span_degrees=float(np.ptp(q[:,:,2],axis=0).max()*180/np.pi),min_circle_margin_mm=float(np.minimum(r+L-d,d-abs(r-L)).min()),min_transmission_sine=float(abs(np.sin(gamma-m['beta'])).min()))
    if detail:result.update(q=q,qd=qd,tau=tau,P=P,E=E)
    return result

if __name__=='__main__':
    data=collect();print('collected',len(data['q']),'poses',flush=True);m=mechanical(data);np.savez_compressed(OUT/'mechanical.npz',**m)
    rows=[]
    for r in range(20,33):
        for b in range(24,37):rows.append(evaluate(data,m,r,b))
        print('crank',r,'valid',sum(x['valid'] for x in rows),flush=True)
    (OUT/'screen.json').write_text(json.dumps(rows,indent=2))
    for x in sorted([x for x in rows if x['valid']],key=lambda x:x['score'])[:20]:print(x['crank'],x['pickup'],x['score'],x['metrics']['all_gaits'],flush=True)
