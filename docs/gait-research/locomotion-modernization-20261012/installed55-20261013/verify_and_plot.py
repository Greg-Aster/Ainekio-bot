from calculate import *
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path(__file__).resolve().parent
rows=json.loads((p/'calibrated-stance-options.json').read_text())
selected=[next(r for r in rows if r['clearance']==H and r['stroke']==S) for H,S in [(43,78),(58,40)]]
fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained');errors=[]
for ax,row in zip(axes,selected):
 r,v=calc(55,35,28,38,row['clearance'],row['stroke'],row['bias']);offset=np.array([-m.O[0],r['clearance']-m.floor]); colors=['#d86219','#14936b','#176bb0']
 for i,color,label in zip([400,200,0],colors,['Front of stroke','Middle','Rear of stroke']):
  D,P,E=v['D'][i],v['P'][i],v['E'][i];rot=v['beta'][i]-m.b0;R=np.array([[np.cos(rot),-np.sin(rot)],[np.sin(rot),np.cos(rot)]]);foot=D+R@m.ref
  for pts,lw in [(np.array([m.O,D]),4),(np.array([m.C,P,E]),2),(np.array([E,D,foot]),4)]:
   pts=pts+offset;ax.plot(*pts.T,c=color,lw=lw,alpha=.8)
  sole=m.hull@R.T+D+offset;h=ConvexHull(sole);poly=sole[np.r_[h.vertices,h.vertices[0]]];ax.plot(*poly.T,c=color,lw=.7,alpha=.6)
  ax.plot([],[],c=color,label=label)
  # Differentiate fixed material contact point to avoid contact-vertex switching.
  z=(m.hull@R.T)[:,1];local=m.hull[z.argmin()];a,t=np.deg2rad(v['q'][i])+[m.a0,m.t0]
  def fk(aa,tt):
   dd=m.O+m.A*np.array([np.cos(aa),np.sin(aa)]);pp=m.C+m.r*np.array([np.cos(tt),np.sin(tt)]);ee,ok=m.circle(pp-dd,m.b,m.L,1);assert bool(ok);beta=np.arctan2(ee[1],ee[0]);rr=beta-m.b0;return dd+np.array([[np.cos(rr),-np.sin(rr)],[np.sin(rr),np.cos(rr)]])@local
  eps=1e-6;J=np.stack([(fk(a+eps,t)-fk(a-eps,t))/(2*eps),(fk(a,t+eps)-fk(a,t-eps))/(2*eps)],-1);errors.append(float(abs(J-v['jac'][i]).max()))
 ax.axhline(0,c='black',lw=1);ax.axhline(r['clearance'],c='gray',ls=':',label='Model body underside')
 ax.set(aspect='equal',xlabel='Foot position relative to carrier pivot (mm)',ylabel='Height above ground (mm)',title=f"Existing parts: {r['stroke']} mm stroke / {r['clearance']} mm clearance\nSmallest lower-leg angle: {r['lower_leg_angle_deg'][0]:.1f} degrees")
 ax.legend(fontsize=8);ax.grid(alpha=.2)
fig.suptitle('55 mm leg / 35 carrier / 38 rod / 28 pickup / 20 crank\nPlanar planted paths; no return swing or body-support qualification')
fig.savefig(p/'existing-parts-stance-comparison.png',dpi=160)
(p/'numerical-verification.json').write_text(json.dumps({'central_difference_contact_jacobian_max_error_mm_per_radian':max(errors),'poses_checked':len(errors)},indent=2))
print('Jacobian max error',max(errors))
