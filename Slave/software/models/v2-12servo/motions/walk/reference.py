"""Ainekio 24/38 four-bar gait: geometric millimetres and radians, no PWM.
Run with --generate to bake the source data. Blender application is separate.
"""
import json, math, argparse
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull

HERE=Path(__file__).resolve().parent
LEGS=['RL','RR','FL','FR'] # physical front-left, front-right, rear-left, rear-right
def rx(a):
 c,s=math.cos(a),math.sin(a);return np.array([[1,0,0],[0,c,-s],[0,s,c]])
def ry(a):
 c,s=math.cos(a),math.sin(a);return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def rz(a):
 c,s=math.cos(a),math.sin(a);return np.array([[c,-s,0],[s,c,0],[0,0,1]])
def smooth(u):return u*u*u*(10+u*(-15+6*u))
def bump(u):return 64*u**3*(1-u)**3
def automatic_parameters(speed_percent):
 """Normal walking Speed: extend stride first, then raise cadence."""
 speed=float(speed_percent)
 if not math.isfinite(speed) or not 0<=speed<=100:raise ValueError('speed must be finite, 0..100')
 return min(100.,2*speed),max(1.,speed/50.)

def speed_parameters(stride_percent,motion_rate,cfg):
 """Independent geometric stride and shared-clock rate. No servo PWM scaling."""
 sweep=cfg['continuous_walk']['stance_sweep_100_mm']*np.asarray(stride_percent)/100
 advance=sweep/cfg['ground_contact_fraction']
 frequency=np.asarray(motion_rate)/cfg['gait_controls']['base_cycle_seconds']
 return advance*frequency,advance,frequency

class Mechanism:
 def __init__(self,config):
  self.body_euler=np.zeros(3);self.cfg=config;self.p=config['parameters'];self.geom=config['legs']
  self.O=np.array(self.p['O']);self.C=np.array(self.p['C_new']);self.a0=self.p['alpha_neutral'];self.t0=self.p['new_theta_neutral'];self.b0=self.p['beta_neutral']
  self.A=self.p['primary_length'];self.r=self.p['input_length'];self.L=self.p['rod_length'];self.b=self.p['pickup_length']
  self.hulls={leg:np.array(self.geom[leg]['sole_hull_local_mm']) for leg in LEGS}
 def planar(self,q):
  h,alpha,theta=q;a=self.a0+alpha;t=self.t0+theta
  D=self.O+self.A*np.array([math.cos(a),math.sin(a)])
  P=self.C+self.r*np.array([math.cos(t),math.sin(t)])
  w=P-D;d=np.linalg.norm(w)
  if not abs(self.L-self.b)+1e-5<d<self.L+self.b-1e-5:raise ValueError('Four-bar unreachable')
  along=(self.b*self.b-self.L*self.L+d*d)/(2*d);height=math.sqrt(self.b*self.b-along*along)
  E=D+(along*w+self.p['assembly_branch']*height*np.array([-w[1],w[0]]))/d
  beta=math.atan2(E[1]-D[1],E[0]-D[0]);beta=self.b0+math.atan2(math.sin(beta-self.b0),math.cos(beta-self.b0))
  return D,P,E,beta,height
 def pose(self,leg,q,body):
  D,P,E,beta,height=self.planar(q);g=self.geom[leg];S=np.array(g['shoulder_world']);M=np.array(g['mechanism_local'])
  R=S[:3,:3]@rx(q[0]);t=S[:3,3]+np.asarray(body)+R@M[:3,3]
  R=R@M[:3,:3];pos=t+R@np.array([D[0],0,D[1]])
  B=rz(self.body_euler[2])@ry(self.body_euler[1])@rx(self.body_euler[0]);pivot=np.asarray(self.cfg.get("continuous_walk",{}).get("body_rotation_pivot_mm",[0,0,65.]))
  return B@R@ry(-(beta-self.b0)),np.asarray(body)+pivot+B@(pos-np.asarray(body)-pivot)
 def vertices(self,leg,q,body):
  R,t=self.pose(leg,q,body);return self.hulls[leg]@R.T+t
 def reference(self,leg,q,body):
  R,t=self.pose(leg,q,body);return R@self.geom[leg]['foot_reference_local_mm']+t
 def solve(self,leg,body,seed,xy,height=0,local_point=None):
  g=self.geom[leg];ref=np.array(g['foot_reference_local_mm']) if local_point is None else local_point
  def residual(q):
   try:
    R,t=self.pose(leg,q,body);pt=R@ref+t;z=np.min(self.hulls[leg]@R[2]+t[2]);return np.array([pt[0]-xy[0],pt[1]-xy[1],z-height])
   except ValueError:return np.ones(3)*1e3+np.asarray(q)*.001
  # These are replaceable research offsets, NOT calibrated electrical stops.
  bound=np.deg2rad(self.cfg['research_angle_bounds_deg'])
  sol=least_squares(residual,seed,bounds=(bound[:,0],bound[:,1]),xtol=1e-9,ftol=1e-9,gtol=1e-9,max_nfev=40,diff_step=1e-5)
  error=np.linalg.norm(residual(sol.x))
  if error>.02:raise ValueError(f'{leg} IK residual {error:.5f} mm target={xy} body={body}')
  return sol.x,error

def margin(point,contacts):
 contacts=np.asarray(contacts)[:,:2];point=np.asarray(point)
 if len(contacts)==2:
  a,b=contacts;d=b-a;u=np.clip(np.dot(point-a,d)/np.dot(d,d),0,1)
  return -float(np.linalg.norm(point-a-u*d))
 poly=contacts[ConvexHull(contacts).vertices];d=np.roll(poly,-1,axis=0)-poly
 return float(np.min((d[:,0]*(point[1]-poly[:,1])-d[:,1]*(point[0]-poly[:,0]))/np.linalg.norm(d,axis=1)))

def load():return json.loads((HERE.parents[1]/'geometry.json').read_text())

def stand(cfg):
 m=Mechanism(cfg);body=np.array([0.,0.,cfg['body_translation_z_mm']]);qs=[];pts=[]
 for i,leg in enumerate(LEGS):
  q,e=m.solve(leg,body,np.zeros(3),cfg['reference_stance_xy_mm'][i]);vs=m.vertices(leg,q,body);idx=vs[:,2].argmin();qs.append(q);pts.append(vs[idx])
 return m,body,np.array(qs),np.array(pts)

def phase_path(phase,advance,duty,lift):
 """C2 closed foot path. World XY velocity is zero at lift/touchdown.
 During stance the foot reference is stationary in world XY. The swing's
 backward endpoint velocity in body coordinates matches the stance exactly.
 """
 p=np.asarray(phase)%1;sweep=advance*duty
 u=np.clip((p-duty)/(1-duty),0,1);retract=advance*(1-duty)
 stance=sweep/2-advance*p
 swing=-sweep/2-retract*u+advance*smooth(u)
 return np.where(p<duty,stance,swing),lift*bump(u),(p<duty).astype(np.int8)

def profile(phase,cfg):
 """C2 control curves in unwrapped gait phase; rate changes time only."""
 c=cfg['gait_controls'];ph=np.asarray(phase,dtype=float)
 if c['mode']=='steady':
  return np.full_like(ph,c['stride_percent']),np.full_like(ph,c['motion_rate']),np.full(ph.shape,'STEADY WALK',dtype='U32')
 nodes=c['demo_keypoints'];period=nodes[-1]['phase'];p=ph%period
 knots=np.array([r['phase'] for r in nodes]);i=np.clip(np.searchsorted(knots,p,side='right')-1,0,len(nodes)-2)
 u=(p-knots[i])/(knots[i+1]-knots[i]);u=smooth(u)
 stride=np.array([r['stride_fraction'] for r in nodes]);rate=np.array([r['rate_fraction'] for r in nodes])
 return c['stride_percent']*((1-u)*stride[i]+u*stride[i+1]),c['motion_rate']*((1-u)*rate[i]+u*rate[i+1]),np.array([r['label'] for r in nodes],dtype='U32')[i]

class FootPlanner:
 """Keep stance anchors fixed; anticipate body travel during the next stance.
 Rear bias is proportional to that stance's actual travel. Swing joins two
 world-space anchors with zero velocity/acceleration at lift and touchdown.
 """
 def __init__(self,cfg):
  self.cfg=cfg;c=cfg['gait_controls'];self.end_phase=c['demo_keypoints'][-1]['phase'] if c['mode']=='demo' else c['steady_cycles']
  self.grid=np.linspace(-2,self.end_phase+2,int((self.end_phase+4)*4096)+1)
  stride,rate,_=profile(self.grid,cfg);v,L,f=speed_parameters(stride,rate,cfg)
  def integrate(y):
   result=np.r_[0,np.cumsum((y[1:]+y[:-1])*.5*np.diff(self.grid))]
   return result-np.interp(0.,self.grid,result)
  self.xgrid=integrate(L);self.tgrid=integrate(1/f)
  self.duty=cfg['ground_contact_fraction'];self.bias_ratio=cfg['continuous_walk']['rearward_bias_100_mm']/cfg['continuous_walk']['stance_sweep_100_mm']
 def x(self,p):return np.interp(p,self.grid,self.xgrid)
 def time(self,p):return np.interp(p,self.grid,self.tgrid)
 def anchor(self,touchdown):
  start=self.x(touchdown);travel=self.x(touchdown+self.duty)-start
  return start+travel*(.5-self.bias_ratio)
 def target(self,phase,offset):
  touchdown=math.floor(phase-offset)+offset;local=phase-touchdown
  first=self.anchor(touchdown)
  if local<self.duty:return first,0.,1
  u=(local-self.duty)/(1-self.duty);last=self.anchor(touchdown+1)
  stride,_,_=profile(touchdown+(1+self.duty)/2,self.cfg)
  h=self.cfg['continuous_walk']['minimum_lift_mm']+(self.cfg['sole_clearance_mm']-self.cfg['continuous_walk']['minimum_lift_mm'])*float(stride)/100
  return first+(last-first)*smooth(u),h*bump(u),0

def generate(cfg,outname='gait-data',hz=None,output_dir=None):
 output_dir=Path(output_dir) if output_dir is not None else HERE
 c=cfg['gait_controls'];hz=hz or cfg['sample_hz'];planner=FootPlanner(cfg)
 # Constant phase spacing retains geometric accuracy when the clock speeds up.
 per_cycle=max(120,int(math.ceil(c['base_cycle_seconds']*hz)))
 phase=np.linspace(0,planner.end_phase,int(planner.end_phase*per_cycle)+1)
 times=planner.time(phase);stride,rate,stages=profile(phase,cfg)
 speed,advance,frequency=speed_parameters(stride,rate,cfg)
 m,_,qs,_=stand(cfg);stance=np.array(cfg['reference_stance_xy_mm']);settings=cfg['continuous_walk'];rows=[];maxerr=0.
 for n,ph in enumerate(phase):
  strength=stride[n]/100;a=2*np.pi*ph
  body=np.array([planner.x(ph),settings['lateral_sway_mm']*strength*np.sin(a),cfg['body_translation_z_mm']+settings['body_bob_mm']*strength*np.cos(2*a)])
  euler=np.deg2rad([settings['roll_deg']*strength*np.sin(a),settings['pitch_deg']*strength*np.sin(2*a),0.]);m.body_euler=euler
  feet=[];contacts=[];soles=[];states=[];closure=1e9
  for i,leg in enumerate(LEGS):
   x,z,state=planner.target(ph,settings['phase_offsets'][leg]);target=stance[i]+[x,0]
   if n==0:
    start=m.reference(leg,qs[i],body)[:2];start_z=m.vertices(leg,qs[i],body)[:,2].min();steps=max(1,int(np.ceil(np.linalg.norm(target-start)/8)))
    for u in np.linspace(0,1,steps+1)[1:]:qs[i],_=m.solve(leg,body,qs[i],start+(target-start)*u,start_z+(z-start_z)*u)
   qs[i],err=m.solve(leg,body,qs[i],target,z);maxerr=max(maxerr,err)
   vs=m.vertices(leg,qs[i],body);contacts.append(vs[vs[:,2].argmin()]);soles.append(vs[:,2].min());feet.append(m.reference(leg,qs[i],body));states.append(state);closure=min(closure,m.planar(qs[i])[4])
  states=np.array(states,dtype=np.int8);B=ry(euler[1])@rx(euler[0]);pivot=np.array(settings['body_rotation_pivot_mm']);com=body+pivot+B@(np.array(cfg['provisional_COM_body_mm'])-pivot)
  rows.append(dict(time_s=times[n],phase=ph,body=body,body_euler=euler,q=qs.copy(),feet=np.array(feet),contacts=np.array(contacts),states=states,sole_z=np.array(soles),margin=margin(com[:2],np.array(contacts)[states.astype(bool)]),closure=closure))
 data={k:np.array([r[k] for r in rows]) for k in rows[0]}
 data.update(stride_percent=stride,motion_rate=rate,stage=stages,command_v=speed,frequency=frequency,cycle_advance=advance,stance_sweep=advance*planner.duty,rear_bias=cfg['continuous_walk']['rearward_bias_100_mm']*stride/100)
 t=data['time_s'];vel=np.gradient(data['q'],t,axis=0);acc=np.gradient(vel,t,axis=0);drift=[];material=[]
 for i,leg in enumerate(LEGS):
  for n in range(1,len(t)):
   if data['states'][n,i] and data['states'][n-1,i]:
    drift.append(np.linalg.norm(data['feet'][n,i,:2]-data['feet'][n-1,i,:2]))
    m.body_euler=data['body_euler'][n-1];R,T=m.pose(leg,data['q'][n-1,i],data['body'][n-1]);old=(data['contacts'][n-1,i]-T)@R
    m.body_euler=data['body_euler'][n];R,T=m.pose(leg,data['q'][n,i],data['body'][n]);material.append(np.linalg.norm((R@old+T)[:2]-data['contacts'][n-1,i,:2]))
 def extent(x):return [float(np.min(x)),float(np.max(x))]
 summary=dict(schema='ainekio.stride-and-rate.v3',mode=c['mode'],duration_s=float(t[-1]),cycles=float(phase[-1]),samples=len(t),stride_percent_range=extent(stride),motion_rate_range=extent(rate),body_speed_mm_s_range=extent(speed),cycle_frequency_hz_range=extent(frequency),stance_sweep_mm_range=extent(data['stance_sweep']),rear_bias_mm_range=extent(data['rear_bias']),effective_sample_hz_range=extent(1/np.diff(t)),
  max_ik_error_mm=maxerr,cycle_joint_seam_error_deg=float(np.rad2deg(abs(data['q'][0]-data['q'][-1])).max()),minimum_closure_triangle_height_mm=float(data['closure'].min()),ground_penetration_mm=float(max(0,-data['sole_z'].min())),max_stance_reference_step_xy_mm=float(max(drift)),max_stance_material_point_step_xy_mm=float(max(material)),joint_min_deg=np.rad2deg(data['q'].min(0)).tolist(),joint_max_deg=np.rad2deg(data['q'].max(0)).tolist(),peak_joint_speed_deg_s=np.rad2deg(abs(vel).max(0)).tolist(),peak_joint_acceleration_deg_s2=np.rad2deg(abs(acc).max(0)).tolist(),minimum_grounded_feet=int(data['states'].sum(1).min()),maximum_grounded_feet=int(data['states'].sum(1).max()),all_feet_grounded_samples=int(np.sum(data['states'].sum(1)==4)),static_support_margin_min_mm=float(data['margin'].min()),validation_scope='Geometric animation with a shared variable clock and fixed stance references. Dynamics, traction and loaded servo capability are unmeasured.')
 summary['timeline']=[dict(label=r['label'],phase=r['phase'],time_s=float(planner.time(r['phase']))) for r in c['demo_keypoints'][:-1]] if c['mode']=='demo' else [dict(label='STEADY WALK',phase=0,time_s=0.)]
 assert summary['ground_penetration_mm']<.01 and summary['max_stance_reference_step_xy_mm']<.001
 assert summary['cycle_joint_seam_error_deg']<.001
 np.savez_compressed(output_dir/(outname+'.npz'),**data);(output_dir/(outname+'-results.json')).write_text(json.dumps(summary,indent=2))
 print(json.dumps(summary,indent=2),flush=True);return data,summary

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--config',type=Path,default=HERE.parents[1]/'geometry.json');parser.add_argument('--output-config',type=Path);parser.add_argument('--speed',type=float);parser.add_argument('--output-dir',type=Path,default=HERE);parser.add_argument('--generate',action='store_true');parser.add_argument('--stride',type=float,help='Planted sweep percent, 1..100')
 parser.add_argument('--rate',type=float,help='Independent cycle-rate multiplier, 0.25..3')
 mode=parser.add_mutually_exclusive_group();mode.add_argument('--demo',action='store_true');mode.add_argument('--steady',action='store_true')
 args=parser.parse_args();cfg=json.loads(args.config.read_text());c=cfg['gait_controls']
 if args.speed is not None:
  if args.stride is not None or args.rate is not None:parser.error('choose --speed OR --stride/--rate')
  if not 0<args.speed<=100:parser.error('preview --speed must be >0..100; the native state machine handles controlled stop at zero')
  c['stride_percent'],c['motion_rate']=automatic_parameters(args.speed)
 if args.stride is not None:
  if not 1<=args.stride<=100:parser.error('--stride must be 1..100')
  c['stride_percent']=args.stride
 if args.rate is not None:
  if not .25<=args.rate<=3:parser.error('--rate must be 0.25..3')
  c['motion_rate']=args.rate
 if args.demo:c['mode']='demo'
 if args.steady:c['mode']='steady'
 if args.generate:
  args.output_dir.mkdir(parents=True,exist_ok=True);generate(cfg,output_dir=args.output_dir);(args.output_config or args.output_dir/'geometry.json').write_text(json.dumps(cfg,indent=2))
