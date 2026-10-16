"""Dimensioned mechanism-plane reference; schematic links, not manufacturing CAD."""
import json,sys,numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
P=Path(__file__).resolve().parent;sys.argv=['plot','compact60']
import optimize_actual_body as a
v=np.array(json.load(open(P/'compact83-rounded39.json'))['dimensions'][0]);r=json.load(open(P/'body-audit-compact83-rounded39-n1920.json'))['rows'][-1]
a.shift=np.array(r['reference_body_plan']['shift']);a.weights=np.array(r['reference_body_plan']['weights']);N=120;a.N=N;a.step=.9/N;a.period=.9
x,lift=a.pathmodel.path(40);a.feet=np.tile(a.centres,(N,1,1));a.lifts=np.zeros((N,4))
for k,off in enumerate([0,60,90,30]):a.feet[:,k,0]+=np.roll(x,-off);a.lifts[:,k]=np.roll(lift,-off)
a.perf(v,True);ans=a.w.ik3(a.w.legs[0],np.c_[a.feet[:,0]-a.shift,47.27323-v[5]+a.lifts[:,0]],v[5]);i=48;O=a.m.O;C=a.m.C-O;D=ans['D'][i]-O;E=ans['E'][i]-O;Pp=ans['P'][i]-O;F=D-(E-D)*v[1]/v[3]
fig,ax=plt.subplots(figsize=(11,8),layout='constrained');ax.set_aspect('equal');ax.set_facecolor('#f5f7fa')
beta=ans['beta'][i]-a.m.b0;R=np.array([[np.cos(beta),-np.sin(beta)],[np.sin(beta),np.cos(beta)]]);verts=a.original[:,[0,2]]@R.T+D;outline=verts[ConvexHull(verts).vertices]
ax.fill(outline[:,0],outline[:,1],color='#9aa2ac',alpha=.45,label='Existing 55 / 28 mm lower-leg outline')
def link(p,q,color,label):
 ax.plot([p[0],q[0]],[p[1],q[1]],lw=5,color=color,label=label,solid_capstyle='round')
link(np.zeros(2),D,'#2074b4','Carrier 39 mm');link(C,Pp,'#e37b24','Crank 20 mm');link(Pp,E,'#9354b9','Connecting rod 56 mm');link(D,F,'#27804c','Knee-to-foot reference 55 mm');link(D,E,'#88a649','Pickup 28 mm')
for point,label in [(np.zeros(2),'Carrier shaft O'),(C,'Crank shaft C'),(D,'Knee D'),(E,'Rod pickup E'),(Pp,'Crank pin P'),(F,'Foot reference')]:
 ax.scatter(*point,s=58,facecolors='white',edgecolors='#172a3a',zorder=10);ax.annotate(label,point,xytext=(7,7),textcoords='offset points',fontsize=9)
ax.plot([0,C[0]],[0,C[1]],'--',color='#172a3a',lw=1)
ax.set_title('Compact linkage reference — 20 mm crank\n40 mm modeled planted sweep; mid-stance pose',loc='left',fontsize=14)
ax.set_xlabel('Mechanism local X (mm); mirrored for opposite-side legs');ax.set_ylabel('Mechanism local Z (mm)');ax.grid(alpha=.2);ax.legend(loc='upper left',bbox_to_anchor=(1.02,1),fontsize=9)
ax.text(.02,.03,'Crank shaft relative to carrier shaft:\nX = +15.5 mm, Z = +21.2 mm\n\nLower-link joint span = 55 + 28 = 83 mm\nSame lower-leg dimensions as installed part.\n\nSchematic only: motor housings and\nnew mounting brackets are not validated.',transform=ax.transAxes,fontsize=9,va='bottom',bbox=dict(facecolor='white',alpha=.9,edgecolor='#c3ccd4'))
ax.set_xlim(-85,65);ax.set_ylim(-105,48)
fig.savefig(P/'compact39-dimensioned-reference.png',dpi=160)
print('saved',P/'compact39-dimensioned-reference.png')
