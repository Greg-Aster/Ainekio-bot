from remap import *
def module(name):
 spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parent/(name+'.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
tr=module('transfer-fit');af=module('air-fit')
s=read((WORK/'sit.json'));src=read(BASE/'motions/gestures/upright/source.json');anchor=np.array(s['samples'][360]['foot_bolt_world_mm'][0]);anchor1=np.array(s['samples'][360]['foot_bolt_world_mm'][1]);out=copy.deepcopy(s['samples'][:361]);prev=np.array(out[-1]['actuator_angles_rad']);dx=anchor[0]-src['samples'][360]['foot_bolt_world_mm'][0][0]
cache=(WORK/'transfer-supported.npz')
if cache.exists():data=np.load(cache);parameters=data['parameters']
else:
 params=[];previous=None
 _,b8,*_=tr.transfer(src['samples'][960],anchor);shift8=b8[0]-src['samples'][960]['body_translation_world_mm'][0]
 for n in range(960,1441):
  previous,body,rear,front,cost=tr.transfer(src['samples'][n],anchor,previous,src['samples'][n]['body_translation_world_mm'][0]+shift8+(dx-shift8)*ref.smooth((n-960)/480));params.append(previous)
  if n%120==0:print('fitted transfer',n/120,flush=True)
 parameters=np.array(params);np.savez(cache,parameters=parameters)
row8=src['samples'][960];rear8,_=rear_at(row8,anchor,row8['body_translation_world_mm'][0]+dx*ref.smooth(5/9),np.array(row8['actuator_angles_rad'][0]));delta_a8=parameters[0,0]-rear8[1];delta_p8=parameters[0,1]-row8['body_rotation_euler_xyz_rad'][1]

def supported(row,ar,pitch):
 oq=np.array(row['actuator_angles_rad'][0]);old.body_euler=np.array(row['body_rotation_euler_xyz_rad']);Rold,_=old.pose('FL',oq,np.array(row['body_translation_world_mm']));m.body_euler=np.array([0.,pitch,0.]);S=np.array(m.geom['FL']['shoulder_world']);M=np.array(m.geom['FL']['mechanism_local']);Rbase=ref.ry(pitch)@S[:3,:3]@ref.rx(oq[0])@M[:3,:3];rotation=Rbase.T@Rold;beta=m.b0-math.atan2(rotation[0,2],rotation[0,0]);q=inverse(oq[0],ar,beta,prev[0,2]);target_anchor=anchor.copy();target_anchor[2]=row['foot_bolt_world_mm'][0][2];body=target_anchor-m.reference('FL',q,np.zeros(3));return q,body
for n in range(361,2641):
 row=src['samples'][n];t=row['time_s'];oq=np.array(row['actuator_angles_rad']);e0=np.array(row['body_rotation_euler_xyz_rad']);body0=np.array(row['body_translation_world_mm']);q=[]
 if t<8:
  ar,_=rear_at(row,anchor,body0[0]+dx*ref.smooth((t-3)/9),prev[0]);blend=ref.smooth((t-3)/5);rear,body=supported(row,ar[1]+delta_a8*blend,e0[1]+delta_p8*blend)
 elif t<=12:
  v=parameters[n-960];rear,body=supported(row,v[0],v[1])
 else:
  u=1-ref.smooth(np.clip((t-12)/8,0,1));pitch=e0[1]+(parameters[-1,1]-src['samples'][1440]['body_rotation_euler_xyz_rad'][1])*u
  ar=root_scalar(lambda ar:supported(row,ar,pitch)[1][0]-(body0[0]+dx),x0=prev[0,1],x1=prev[0,1]+.001,xtol=1e-11).root;rear,body=supported(row,ar,pitch)
 q.append(rear);pitch=m.body_euler[1];old.body_euler=e0;Rold,_=old.pose('FR',oq[1],body0);S=np.array(m.geom['FR']['shoulder_world']);M=np.array(m.geom['FR']['mechanism_local']);base=ref.ry(pitch)@S[:3,:3]@ref.rx(oq[1,0])@M[:3,:3];rotation=base.T@Rold;beta1=m.b0-math.atan2(rotation[0,2],rotation[0,0]);q1=inverse(oq[1,0],rear[1]+oq[1,1]-oq[0,1],beta1,prev[1,2]);q.append(q1)
 if t<=12:
  for i,l in enumerate(legs[2:],2):
   qq,_=m.solve(l,body,prev[i],np.array(row['foot_bolt_world_mm'][i])[:2],row['sole_clearance_mm'][i]);q.append(qq)
  if t==12:
   tip_new=af.plane(*q[2][1:])[0];D,P,E,beta,_=old.planar(oq[2]);tip_old=D-old.O+(ref.ry(old.b0-beta)@ankle)[[0,2]];tip_delta=tip_new-tip_old;Dnew=m.planar(q[2])[0];knee_delta=Dnew-m.O-(D-old.O);h_delta=q[2][0]-oq[2,0]
 else:
  # Match the planted handoff exactly, blending the new reach into the old
  # withdrawal in its existing 12..14 second phase.
  u=1-ref.smooth(np.clip((t-12)/2,0,1));oq2=oq[2].copy();oq2[0]+=h_delta*u;qq,err=af.fitair(oq2,prev[2],tip_delta*u,knee_delta*u,body);q.append(qq);q.append(np.r_[qq[0]+oq[3,0]-oq[2,0],qq[1:]])
 newrow=copy.deepcopy(row);newrow['body_rotation_euler_xyz_rad']=[0.,pitch,0.];newrow['body_orientation_world_quaternion_wxyz']=[math.cos(pitch/2),0.,math.sin(pitch/2),0.];prev=np.array(q);out.append(metrics(newrow,prev,body))
 if n%120==0:print('built',t,'sole',min(out[-1]['sole_clearance_mm']),'body',out[-1]['body_ground_clearance_mm'],'margin',out[-1]['support_margin_mm'],'frontq',np.degrees(q[2]),flush=True)
src['samples']=out;report('upright',out);(WORK/'upright.json').write_text(json.dumps(src))
