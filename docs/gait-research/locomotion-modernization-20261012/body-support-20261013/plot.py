import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=Path(__file__).resolve().parent
a=json.loads((p/'refined-40-28-30-45.json').read_text())
b=json.loads((p/'refined-45-32-34-55.json').read_text())
fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
fig.suptitle('82 mm nominal stroke: body support and actuator demand\nAssumed torso point mass; no physical walking qualification',fontsize=14)
for d,name,color in [(a,'A: 40 / 28 / 30 mm','#007db3'),(b,'B: 45 / 32 / 34 mm','#dc6300')]:
 phase=np.array(d['phase'])*100
 tau=np.array(d['joint_torques'])
 axes[0,0].plot(phase,np.max(abs(tau[:,:,1]),axis=1),color=color,label=name+' carrier')
 axes[0,0].plot(phase,np.max(abs(tau[:,:,2]),axis=1),color=color,ls='--',label=name+' crank')
 axes[1,0].plot(phase,d['support_margin_mm'],color=color,label=name)
axes[0,0].set(ylabel='Largest supporting-joint torque (Nm/kg)',xlabel='Walking cycle (%)',title='Carrier solid; crank dashed')
axes[0,0].legend(fontsize=8)
axes[1,0].set(xlabel='Walking cycle (%)',ylabel='Effective pressure-point margin (mm)',title='Distance inside planned contact polygon')
axes[1,0].axhline(0,color='gray',lw=1)
shift=np.array(b['body_shift'])
axes[0,1].plot(phase,shift[:,0],label='Forward/back')
axes[0,1].plot(phase,shift[:,1],label='Left/right')
axes[0,1].set(xlabel='Walking cycle (%)',ylabel='Body shift (mm)',title='Body moves over supporting feet during gait')
axes[0,1].legend()
weights=np.array(b['weights'])
for k,label in enumerate(['Front left','Front right','Rear left','Rear right']):
 axes[1,1].plot(phase,weights[:,k],label=label)
axes[1,1].set(xlabel='Walking cycle (%)',ylabel='Fraction of total vertical load',title='B: planned load transfer before foot lift')
axes[1,1].legend(fontsize=8)
for ax in axes.flat:ax.grid(alpha=.25)
fig.savefig(p/'joint-load-and-support.png',dpi=170)
