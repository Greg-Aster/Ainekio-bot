from pathlib import Path
import json,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path(__file__).resolve().parent
fig,ax=plt.subplots(1,2,figsize=(13,5),layout='constrained')
c=json.loads((p/'crank-comparison.json').read_text());c=[r for r in c if r['carrier']==35];x=np.arange(len(c));y=np.array([r['peak_Nm_per_10N_vertical'] for r in c]);ax[0].bar(x-.18,y[:,0],.36,label='Carrier');ax[0].bar(x+.18,y[:,1],.36,label='Crank');ax[0].set_xticks(x,[str(r['crank']) for r in c]);ax[0].set(xlabel='Crank length (mm)',ylabel='Peak torque for 10 N vertical foot force (Nm)',title='Change crank only: installed linkage\n40 mm planted stroke / 58 mm body clearance');ax[0].legend()
rows=json.loads((p/'ratio-candidates.json').read_text())
for free,label,color in [(False,'Existing pivot positions','#227cb4'),(True,'Relocated pivots','#c88d3f')]:
 a=np.array([[max(r['peak_speed_deg_s']),max(r['peak_traction_envelope_Nm'])] for r in rows if r['relocated_pivot']==free]);sel=(a[:,0]<1400)&(a[:,1]<1.2);ax[1].scatter(a[sel,0],a[sel,1],s=9,alpha=.3,label=label,c=color)
ax[1].set(xlabel='Peak joint speed, including return (degrees/s)',ylabel='Largest torque: Fz=10 N, Fx=+/-3 N (Nm)',title='Broader geometry study: 82 mm stroke\n2 s cycle / loaded leg at least 45 degrees');ax[1].legend(fontsize=8)
fig.suptitle('Geometry changes trade force, speed, posture and size — no globally ideal ratio established')
for a in ax:a.grid(alpha=.2)
fig.savefig(p/'crank-and-ratio-comparison.png',dpi=160)
