import json,numpy as np,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
p=Path(__file__).resolve().parent;d=json.loads((p/'cycles.json').read_text());live=json.loads((p/'live45.json').read_text());C=np.array(live['params']['C_new'])
fig,axs=plt.subplots(2,2,figsize=(11,6),sharex=True)
report=[]
for case,col in zip(d['cases'],['#169bc1','#e17516']):
 rows=case['rows'];q=np.array([r['q'] for r in rows]);t=np.array([r['phase'] for r in rows])*2;vel=np.gradient(q,t,axis=0)
 for j,n in enumerate(['Carrier','Crank']):
  axs[0,j].plot(t,q[:,j],color=col,label=f"{case['stroke_mm']} mm");axs[1,j].plot(t,vel[:,j],color=col);axs[0,j].set_title(n);axs[0,j].set_ylabel('Angle (degrees)');axs[1,j].set_ylabel('Speed (degrees/s)');axs[1,j].set_xlabel('Cycle time (seconds)')
 D=np.array([r['D'] for r in rows]);P=np.array([r['P'] for r in rows]);E=np.array([r['E'] for r in rows]);rod=E-P;pickup=E-D;crank=P-C
 ang=lambda a,b:np.rad2deg(np.arccos(np.clip(np.abs((a*b).sum(1))/(np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1)),0,1)))
 branch=(E-C)[:,0]*crank[:,1]-(E-C)[:,1]*crank[:,0]
 row={'stroke_mm':case['stroke_mm'],'peak_speed_deg_s':np.max(abs(vel),axis=0).tolist(),'min_output_angle_deg':float(ang(rod,pickup).min()),'min_input_angle_deg':float(ang(rod,crank).min()),'inverse_branch_positive_samples':int((branch>0).sum())};report.append(row);print(row)
for ax in axs.flat:
 ax.axvspan(1.5,2,color='gray',alpha=.12);ax.grid(alpha=.2)
axs[0,0].legend();fig.suptitle('45 mm leg / 30 mm rod — full-cycle kinematic comparison\n2 s cycle; shaded interval = lifted return; no servo dynamics');fig.tight_layout();fig.savefig(p/'angle-and-speed.png',dpi=160);(p/'cycle-metrics.json').write_text(json.dumps(report,indent=2))
