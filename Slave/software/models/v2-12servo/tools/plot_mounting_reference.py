"""Plot the planar mounting reference; requires NumPy and Matplotlib."""
from pathlib import Path
import json,math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
cfg=json.loads((ROOT/'geometry.json').read_text());profile=json.loads((ROOT/'servo_profile.json').read_text());p=cfg['parameters']
plt.rcParams['svg.fonttype']='none'
plt.rcParams['svg.hashsalt']='ainekio-servo-mounting-reference'
fig,axes=plt.subplots(1,2,figsize=(11,5.6),sharex=True,sharey=True)
for ax,offset,title in zip(axes,[[0,0],profile['center_degrees'][1:]],['CAD neutral reference',f"{profile['pulse_reference_us']} µs mounting reference"]):
    a=p['alpha_neutral']+math.radians(offset[0]);t=p['new_theta_neutral']+math.radians(offset[1]);O=np.array(p['O']);C=np.array(p['C_new']);D=O+p['primary_length']*np.array([math.cos(a),math.sin(a)]);P=C+p['input_length']*np.array([math.cos(t),math.sin(t)])
    v=P-D;distance=np.linalg.norm(v);b=p['pickup_length'];L=p['rod_length'];along=(b*b-L*L+distance*distance)/(2*distance);height=math.sqrt(b*b-along*along);E=D+(along*v+p['assembly_branch']*height*np.array([-v[1],v[0]]))/distance
    for A,B,color,label,width in [(O,C,'#999999','Fixed servo centers',2),(O,D,'#277da1','Part 023 carrier (40 mm)',4),(C,P,'#d1495b','Part 009 crank (24 mm)',4),(D,E,'#7b2cbf','Part 027 pickup (24 mm)',4),(P,E,'#35926c','Part 026 rod (38 mm)',3)]:
        ax.plot([A[0],B[0]],[A[1],B[1]],color=color,lw=width,label=label,solid_capstyle='round')
    for label,point in [('O',O),('C',C),('D',D),('P',P),('E',E)]:
        ax.plot(*point,'o',color='white',markeredgecolor='#222222',ms=7);ax.annotate(label,point,xytext=(7,6),textcoords='offset points',weight='bold')
    ax.set_title(title+'\n'+f'Carrier offset {offset[0]:g}°; crank offset {offset[1]:g}°',fontsize=12);ax.set_aspect('equal');ax.grid(alpha=.2);ax.set_xlabel('Mechanism local X (mm)');ax.set_xlim(-1,80);ax.set_ylim(12,115)
axes[0].set_ylabel('Mechanism local Z (mm)');axes[1].legend(loc='lower left',fontsize=8,framealpha=.9)
fig.suptitle('Ainekio V2 — horn indexing reference',fontsize=16)
fig.text(.5,.025,'All four legs use their own mirrored CAD frames. Shoulder offset = 0°. Offsets are model angles, not shaft dial readings.\nNon-inverted mapping; 234° shaft travel remains provisional. This Home pose does not clear all motion collisions.',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.09,1,.93]);fig.savefig(ROOT/'mechanics/servo-mounting-reference.svg',metadata={'Date':None});plt.close(fig)
