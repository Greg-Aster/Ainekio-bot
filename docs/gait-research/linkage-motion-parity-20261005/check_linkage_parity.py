"""Compare the unchanged planner under old and compact linkage geometry.
Host-only: no robot connection or firmware mutation. Run from the repository.
"""
import argparse,copy,hashlib,importlib.util,json,math,subprocess
from pathlib import Path
import numpy as np


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True)
 ap.add_argument('--output',type=Path,required=True);ap.add_argument('--root',type=Path,required=True);ap.add_argument('--baseline-root',type=Path,required=True)
 args=ap.parse_args();root=args.root.resolve();cfg=json.loads((root/'geometry.json').read_text());cfg=copy.deepcopy(cfg)
 spec=importlib.util.spec_from_file_location('parity_reference',root/'motions/walk/reference.py');ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
 walk=ref.Mechanism(cfg);crawl=ref.Mechanism(cfg)
 hulls=json.loads((root/'motions/locomotion/contact-hulls.json').read_text());crawl.hulls={l:np.array(hulls['soles'][l]) for l in ref.LEGS}
 result={'schema':'ainekio.linkage-motion-parity-study.v1','status':'Host kinematic comparison; collision correction deferred by owner; not hardware qualification','dimensions_mm':{label:cfg['parameters'][field] for label,field in [('carrier','primary_length'),('crank','input_length'),('pickup','pickup_length'),('rod','rod_length'),('lower_leg','distal_length')]},'source_sha256':{f:digest(args.baseline_root/f) for f in ['geometry.json','motion.c','walk_kinematics.c','servo_profile.json','motions/locomotion/config.json','motions/locomotion/crab.json','motions/run/config.json']},'candidate_geometry_sha256':digest(root/'geometry.json'),'binaries_sha256':{'baseline':digest(args.baseline),'candidate':digest(args.candidate)},'angle_zero_policy':'Retain existing motor-angle coordinate zero, including theta=2.484925850946935 radians. CAD neutral changed; it does not silently reindex a physical servo.','clock_scope':'1,000,000 degrees/s in both host samplers releases the existing common speed clock to compare identical phase/time targets. No device settings changed.','duration_seconds_per_case':30,'sample_hz':100,'existing_reference_mapping_only':True,'hardware_qualified':False,'cases':[]}
 overall=np.array([[math.inf]*3,[-math.inf]*3]);witnesses=[]
 for gait in ['walk','run','crawl','crab']:
  for direction in (['fwd','back','turn_l','turn_r','side_l','side_r'] if gait=='crab' else ['fwd','back','turn_l','turn_r']):
   for speed in ([1,20,50,100,101,150,200] if gait=='walk' else [1,50,100]):
    command=dict(t='intent',seq=1,name='walk',dir=direction,gait=gait,steps=0,speed=speed)
    runs=[subprocess.run([str(cli),'30000','100','1000000'],input=json.dumps(command)+'\n',capture_output=True,text=True) for cli in [args.baseline,args.candidate]]
    rows=[[json.loads(l) for l in r.stdout.splitlines()] for r in runs];old,new=rows
    item=dict(gait=gait,direction=direction,speed_percent=speed,returncodes=[r.returncode for r in runs],errors=[r.stderr.strip() for r in runs],samples=len(new))
    if any(r.returncode for r in runs) or len(old)!=len(new):result['cases'].append(item);print(item,flush=True);continue
    target_errors={k:float(abs(np.array([r[k] for r in new],dtype=float)-np.array([r[k] for r in old],dtype=float)).max()) for k in ['phase','body','euler','feet','grounded','run_blend']}
    q=np.array([r['q'] for r in new]).reshape(-1,4,3);deg=np.degrees(q);span=np.array([deg.min((0,1)),deg.max((0,1))]);overall[0]=np.minimum(overall[0],span[0]);overall[1]=np.maximum(overall[1],span[1])
    profile=json.loads((root/'servo_profile.json').read_text());pulse=np.array(profile['pulse_reference_us'])+(deg-np.array(profile['center_degrees']))*profile['us_per_degree'];pulse[:,[0,2]]=3300-pulse[:,[0,2]]
    m=crawl if gait=='crawl' else walk;xy_error=0.;sole=[math.inf,-math.inf]
    for n in range(0,len(new),10):
     r=new[n];m.body_euler=np.array(r['euler'])
     for i,l in enumerate(ref.LEGS):
      pt=m.reference(l,q[n,i],r['body']);z=m.vertices(l,q[n,i],r['body'])[:,2].min();xy_error=max(xy_error,float(abs(pt[:2]-r['feet'][i][:2]).max()));e=float(z-r['feet'][i][2]);sole=[min(sole[0],e),max(sole[1],e)]
    theta=deg[:,:,2]+math.degrees(cfg['parameters']['new_theta_neutral']);n,l=np.unravel_index(theta.argmin(),theta.shape)
    item.update(target_max_absolute_difference=target_errors,axis_min_max_deg=span.tolist(),reference_pulse_range_us=[float(pulse.min()),float(pulse.max())],independent_fk_xy_error_mm=xy_error,independent_full_sole_error_mm=sole,absolute_crank_range_deg=[float(theta.min()),float(theta.max())])
    witnesses.append(dict(case=dict(gait=gait,direction=direction,speed_percent=speed),sample=int(n),leg=ref.LEGS[l],pose=new[n]))
    result['cases'].append(item);print(gait,direction,speed,'target difference',max(target_errors.values()),'FK XY',round(xy_error,6),'pulse',np.round(item['reference_pulse_range_us'],3).tolist(),flush=True)
 result['overall_axis_min_max_deg']=overall.tolist();result['case_count']=len(result['cases']);result['successful_cases']=sum(x['returncodes']==[0,0] for x in result['cases'])
 result['reference_pulse_range_us']=[min(x['reference_pulse_range_us'][0] for x in result['cases']),max(x['reference_pulse_range_us'][1] for x in result['cases'])]
 result['maximum_target_difference']=max(max(x['target_max_absolute_difference'].values()) for x in result['cases']);result['maximum_independent_fk_xy_error_mm']=max(x['independent_fk_xy_error_mm'] for x in result['cases'])
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps(result,indent=2)+'\n');args.output.with_name('witness-poses.json').write_text(json.dumps(witnesses,indent=2)+'\n')
if __name__=='__main__':main()
