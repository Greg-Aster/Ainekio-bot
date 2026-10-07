import sys,json,subprocess,re,numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent));import screen as s
out=s.OUT/'native_compact';out.mkdir(exist_ok=True)
header=(s.OUT/'native/walk/walk_data.h').read_text()
for name,value in [('INPUT',28),('PICKUP',30)]:header=re.sub(r'#define V2_'+name+r' .*',f'#define V2_{name} ({value:.9e}f)',header)
(out/'walk_data.h').write_text(header)
subprocess.run(['cc','-O2','-std=c11',f'-I{out}',f'-I{s.OUT}/native/servo',f'-I{s.MODEL}/include',f'-I{s.ROOT}/Slave/software/core/include',str(s.MODEL/'tests/walk_command_cli.c'),str(s.MODEL/'motion.c'),str(s.MODEL/'walk_kinematics.c'),str(s.OUT/'native/walk/walk_data.c'),str(s.OUT/'native/core/libainekio_core.a'),'-lm','-o',str(out/'v2_walk_command')],check=True)
data=s.collect();m=dict(np.load(s.OUT/'mechanical.npz'));expected=s.evaluate(data,m,28,30,detail=True)['q'];results=[]
for group in range(18):
 gait,direction=str(data['names'][group]).split('/');cmd=dict(t='intent',seq=1,name='walk',dir=direction,gait=gait,steps=0,speed=25)
 speeds=[50,100,150,200] if gait in ['walk','run'] else [50,100];wire=json.dumps(cmd)+'\n'
 for i,speed in enumerate(speeds+[0]):wire+=f'{(i+1)*6000} '+json.dumps(dict(cmd,seq=i+2,speed=speed,update=1))+'\n'
 p=subprocess.run([str(s.OUT/'native_compact/v2_walk_command'),'50000','120','20000'],input=wire,capture_output=True,text=True,check=True)
 rows=[json.loads(x) for x in p.stdout.splitlines()];q=np.array([x['q'] for x in rows]).reshape(-1,4,3);ids=np.flatnonzero(data['group']==group)
 assert len(rows)==len(ids) and rows[-1]['complete']
 error=float(abs((q-expected[ids]+np.pi)%(2*np.pi)-np.pi).max()*180/np.pi)
 assert error<.003,(gait,direction,error)
 results.append(dict(group=str(data['names'][group]),samples=len(rows),max_angle_error_deg=error));print(results[-1],flush=True)
(s.OUT/'native_all_gaits.json').write_text(json.dumps(results,indent=2))
