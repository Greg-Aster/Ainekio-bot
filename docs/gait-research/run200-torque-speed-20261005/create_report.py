"""Package reproducible results and a static scientific figure for review."""
import gzip,html,json,shutil,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import analyze as a

OUT=Path('/home/greggles/Ainekio/docs/gait-research/run200-torque-speed-20261005')
OUT.mkdir(parents=True,exist_ok=True)
data=json.loads((a.ROOT/'results.json').read_text())
checks=json.loads((a.ROOT/'independent_checks.json').read_text())
native=json.loads((a.ROOT/'native_validation.json').read_text())
convergence=json.loads((a.ROOT/'sampling_convergence.json').read_text())
rows=[x for x in data['results'] if (x['w0_deg_s'],x['stall_kgcm'],x['load_multiplier'],x['envelope'],x['rod_mm'])==(600,1.8,1,'symmetric',38)]
def key(x):return f"{x['carrier_mm']:g}/{x['crank_mm']}/{x['pickup_mm']}/{x['rod_mm']}"
bykey={key(x):x for x in rows};baseline=bykey['40/24/24/38']['utilization']
selected=['40/24/24/38','35/20/28/38','36/24/28/38','37.5/24/28/38','35/28/36/38','40/32/36/38']
table=''
for k in selected:
 x=bykey[k];m=data['geometry_metrics'][k]
 table+=f"<tr><td>{k.rsplit('/',1)[0]}</td><td>{x['utilization']:.3f}</td><td>{100*(1-x['utilization']/baseline):.1f}%</td><td>{x['joint_utilization'][1]:.3f}</td><td>{x['joint_utilization'][2]:.3f}</td><td>{m['peak_speed_by_joint_deg_s'][1]:.0f}</td><td>{m['peak_speed_by_joint_deg_s'][2]:.0f}</td></tr>"
sensitivity=''
for w in [600,750,900,1200,1500]:
 x=min([x for x in data['results'] if (x['w0_deg_s'],x['stall_kgcm'],x['load_multiplier'],x['envelope'],x['rod_mm'])==(w,1.8,1,'symmetric',38)],key=lambda x:x['utilization'])
 sensitivity+=f"<tr><td>{w}</td><td>{key(x).rsplit('/',1)[0]}</td><td>{x['utilization']:.3f}</td><td>{x['stage']}: {x['leg']} {x['joint']}</td></tr>"

fig,axes=plt.subplots(3,1,figsize=(11,9),sharex=True,sharey=True,layout='constrained')
for ax,k in zip(axes,['40/24/24/38','35/20/28/38','40/32/36/38']):
 A,r,b,L=map(float,k.split('/'));s=a.setup(A);q,qd,t,p,m=a.candidate(s,A,r,b,L);u=t/a.STALL+abs(qd)/600
 for j,color in enumerate(['#777777','#d56b00','#126ba0']):ax.plot(s['f'][:,0],u[:,:,j].max(axis=1),label=a.JOINTS[j],color=color,lw=.9)
 ax.axhline(1,color='#a02020',ls='--',lw=1,label='assumed envelope boundary')
 ax.axvline(12,color='#444444',ls=':',lw=1);ax.set_title(k.rsplit('/',1)[0]+' mm carrier / crank / pickup');ax.set_ylabel('Worst simultaneous demand U');ax.grid(alpha=.2);ax.set_ylim(0,3)
axes[0].legend(ncol=4,fontsize=8);axes[-1].set_xlabel('Seconds from Start (Finish requested at 12 s)')
fig.suptitle('Conditional torque–speed screening: 512 g, 600°/s, 1.8 kgf·cm\nEqual weight sharing among indicated contacts; 38 mm rod; inertia excluded',fontsize=11)
fig.savefig(OUT/'joint-demand.svg');fig.savefig(OUT/'joint-demand.png',dpi=160);plt.close(fig)

for name in ['analyze.py','sample.c','verify.py','create_report.py','winners.json','native_validation.json','independent_checks.json','sampling_convergence.json']:
 source=(a.SOURCE if name.endswith(('.py','.c')) else a.ROOT)/name
 if source.resolve()!=(OUT/name).resolve():shutil.copyfile(source,OUT/name)
for name in ['results.json','ranking.csv']:
 with gzip.open(OUT/(name+'.gz'),'wb') as out:out.write((a.ROOT/name).read_bytes())
summary=dict(source_study=str(a.STUDY),source_commit='a129fe65bafb459e77c32d53468eb313c66914e3',tested_candidates=len(data['geometry_metrics'])+len(data['invalid']),reachable_candidates=len(data['geometry_metrics']),native_validations=len(native),maximum_independent_torque_error_Nm=max(x['max_torque_difference_Nm'] for x in checks),selected_results=[bykey[k] for k in selected],sampling_convergence=convergence)
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))

report=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Ainekio torque and speed linkage calculation</title>
<style>body{{font:17px/1.55 system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 24px;color:#20252b}}h1,h2{{line-height:1.2}}table{{border-collapse:collapse;width:100%;font-size:15px}}th,td{{text-align:left;border-bottom:1px solid #ccc;padding:9px}}th{{background:#eef2f5}}code,pre{{background:#f1f3f5;padding:3px 6px}}pre{{white-space:pre-wrap}}img{{width:100%}}.lead{{font-size:20px}}.note{{border-left:4px solid #ba7600;padding:8px 18px;background:#fff8e8}}</style>
<h1>Ainekio: minimize the most challenged servo</h1><p>October 5, 2026 · Offline engineering comparison · No firmware, robot settings, calibration or CAD changes.</p>
<p class="lead">Including torque and speed together changes the preferred linkage. Under the nominal comparison assumptions, 35/28/36 mm is the best tested carrier/crank/pickup combination. Keeping the 40 mm carrier and using a 32 mm crank with 36 mm pickup scores within 0.93% of that result.</p>
<p>The previously suggested 35/20/28 configuration improves static leverage, but its extra crank speed is a cost once motor performance is included. The larger pickup paired with a longer crank gives a better combined result in this sweep. These dimensions describe calculated candidates, not print-qualified parts.</p>
<h2>What was optimized</h2>
<p>For every sampled instant and every one of the twelve servos, calculate contact torque and angular speed together. The symmetric screening objective is</p>
<pre>U = max over time, legs, motors and tested force directions:
    |required contact torque| / assumed stall torque
  + |required angular speed| / assumed zero-load speed

Remaining normalized margin = 1 − U. Minimize U.</pre>
<p>U=1 is the boundary of this assumed linear envelope; below 1 leaves margin. U=2.3 is a combined demand score, not a statement that torque alone is 230% of capacity. The nominal comparison uses 600°/s and 1.8 kgf·cm (0.1765 Nm), referencing <a href="https://towerpro.com.tw/product/mg90s-3/">TowerPro MG90S ratings at 4.8 V</a>. The installed servos are identified in repository notes as Miuzei: this is a comparison curve, not their measured specification. The linear DC motor approximation follows <a href="https://support.maxongroup.com/hc/en-us/articles/360013761160-Motor-data-and-simulation">maxon’s characteristic-line explanation</a>; the complete hobby servo includes gearing and a controller that this approximation does not characterize.</p>
<h2>Nominal comparison: lower demand is better</h2>
<p>38 mm rods, 55 mm distal lengths, fixed pivot locations, 512 g reported mass. Original Run200 targets and timing retained; the offline command limit is 20,000°/s so the software limiter does not hide geometric demand.</p>
<table><tr><th>Carrier/crank/pickup mm</th><th>Worst U</th><th>Reduction vs baseline</th><th>Carrier U</th><th>Crank U</th><th>Peak carrier °/s</th><th>Peak crank °/s</th></tr>{table}</table>
<p>Peak speeds are over the full entry/run/Finish sequence. Each U uses simultaneous torque and speed; the separate peak-speed columns need not occur at the limiting U. Carrier and crank U columns are their respective worst values over all four legs and times.</p>
<p class="note">Every tested option exceeds U=1 at the original unrestricted timing under the nominal comparison curve. Geometry improves the balance but does not establish that these installed servos can track full Run200. No speed cap or motion restriction was changed.</p>
<img src="joint-demand.svg" alt="Simultaneous torque and speed demands throughout entry, running and Finish for three geometries">
<h2>Scope, assumptions and sensitivity</h2>
<ul><li>Commanded forward automatic Run200, from initialized native standing through entry and steady running, then Finish at 12 seconds; native completion at 15.046 seconds. This does not include startup Home, standing up from a collapsed posture, Walk-to-Run from an already walking state, other directions/gaits, or the 23 named motions.</li>
<li>Sampled at 1 ms. Both rods, 38 and 41 mm, are analyzed with the same base-pivot positions. Carrier grid: 35,36,37,37.5,38,39,40 mm. Union of crank 20–24/pickup 24–28 at 1 mm spacing, and crank 20–32/pickup 28–36 at 2 mm spacing. {summary['tested_candidates']} candidates evaluated; {summary['reachable_candidates']} retain four-bar closure and assembly branch across the sampled sequence. Invalid cases are recorded, not silently omitted.</li>
<li>Full per-leg sole hulls; actual native body Euler angles at each instant, including entry and Finish. Contact torque uses independently actuated crank and carrier angles, not a serial-knee approximation. All twelve motors participate in the objective.</li>
<li>Hypothetical vertical force mg divided equally among legs tagged grounded by the gait, with Fx/Fz ranging from −0.2 to +0.2 and no sideways force. Swing legs have zero contact torque. These are load scenarios, not reconstructed actual ground forces.</li>
<li>The native entry contains 0.475 seconds in total with only one leg tagged grounded. This assumption assigns full body weight to that leg, producing some of the largest torque estimates. It also overloads the nominal shoulder benchmark in that scenario. A dynamic transition might distribute forces differently; the model cannot prove the robot will experience these exact peaks.</li>
<li>Flight, impact, gravity/inertia of individual links, servo acceleration torque, compliance, friction, stability/COM balance, thermal/current limits and actual torque-speed curves are excluded. Larger printed parts may increase inertia. A speed-only retiming cannot remedy a torque-only overload in this assumed load history; the zero timing bounds in the raw data mean that modeled scenario fails even at zero speed, not that the robot is incapable of movement.</li>
<li>Signed motor operation was also checked: U=max(|τ|/Ts, |ω|/ω0, |τ/Ts+ω/ω0|), for both horizontal-force extremes. This idealized DC-voltage/current envelope allows a different braking tradeoff. Both approaches select the same nominal winner; higher-speed assumptions can change ranking. Neither substitutes for measured servo braking behavior.</li></ul>
<h2>The preferred crank depends on the motor curve</h2>
<p>Hold assumed stall torque at 1.8 kgf·cm and vary the speed intercept; these are sensitivity cases, not claims that raising voltage produces these speeds.</p>
<table><tr><th>Assumed speed °/s</th><th>Best tested dimensions mm</th><th>Worst U</th><th>Limiting instant/motor</th></tr>{sensitivity}</table>
<p>Additional cases use 1.4 and 2.2 kgf·cm and a 1.5× contact-force multiplier. Complete rankings for both envelope models and both rods are included. With 41 mm rods the nominal winner remains 35/28/36; other motor assumptions can select different dimensions.</p>
<h2>Interpretation for the design</h2>
<p>The useful direction is to enlarge the pickup and choose crank length against the motor’s torque/speed tradeoff. There is little Run200 benefit here from shortening the carrier compared with retaining 40 mm. Preserve the 40 mm option in subsequent full-repertoire and packaging analysis; unchanged carrier length alone does not prove all poses remain reachable with a different crank and pickup.</p>
<p>This is a bounded search, not a global optimum. The best pickup reaches the 36 mm search boundary and the best carrier reaches 35 mm. More extreme lengths may improve this mathematical objective, but physical clearance and permitted packaging dimensions have not been supplied or evaluated. The 32 mm crank and 36 mm pickup need mechanical interference, fastening and stiffness review; horn reindexing and actual PWM travel are also unqualified. No final printable dimensions can be selected from this objective alone.</p>
<h2>Checks and reproducibility</h2>
<p>The original source manifest was verified in the prior reproduction; the runner verifies it on new runs. {len(native)} selected native builds completed entry, running and Finish. Retargeted angles match native builds within {max(x.get('maximum_angle_error_deg',0) for x in native):.5f}°. An independent circle-closure forward-kinematics implementation perturbed actual motor angles and confirmed contact-torque calculations at sampled poses, including limiting poses: maximum discrepancy {summary['maximum_independent_torque_error_Nm']:.2e} Nm.</p>
<p>Rechecking at 0.25 ms changes the baseline U by 0.83%, the 35/28/36 candidate by 0.011%, and the retained-carrier candidate by 0.011%. The native integrator’s contact-event timing explains why transition peaks need finer sampling; reported tables consistently use the original 1 ms sweep.</p>
<p><a href="summary.json">Concise machine-readable results</a> · <a href="results.json.gz">All results, compressed JSON</a> · <a href="ranking.csv.gz">All rankings, compressed CSV</a> · <a href="native_validation.json">Native validation</a> · <a href="independent_checks.json">Independent torque checks</a> · <a href="sampling_convergence.json">Sampling convergence</a></p>
<p>The original supplied study snapshot is required. Python with NumPy/Matplotlib and a C11 compiler are required. Generated trajectories and builds default to /tmp; use a fresh output directory to avoid reusing earlier samples.</p>
<pre>AINEKIO_LINKAGE_OUTPUT=/tmp/ainekio-torque-speed-repeat python analyze.py /path/to/Ainekio-Run200-Linkage-Study
AINEKIO_LINKAGE_OUTPUT=/tmp/ainekio-torque-speed-repeat python verify.py /path/to/Ainekio-Run200-Linkage-Study</pre>
<p>Source: <code>a129fe65bafb459e77c32d53468eb313c66914e3</code> study snapshot. Source model/motion files match the inspected local repository. The research output does not modify runtime code.</p></html>'''
(OUT/'report.html').write_text(report)
print(json.dumps(summary,indent=2))
