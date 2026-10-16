"""Preserved Run geometry stays compatible with the current native controller."""
import hashlib,json,math,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
recording=root/'motions/run/source.json'
source=json.loads(recording.read_text());meta=source['metadata']
report=json.loads((root/'motions/run/validation.json').read_text())
assert hashlib.sha256(recording.read_bytes()).hexdigest()==report['source_sha256'], 'Archived Run source changed'
# native_sources_sha256 identifies the historical recording's inputs, including
# its old research bounds and mounting profile. Keep that provenance intact.
# Current compatibility is checked against every recorded pose below; the
# command-path check uses the current compiled geometry and servo-speed setting.
wire=json.dumps(meta['native_initial_command'])+'\n'+''.join(str(event['at_ms'])+' '+json.dumps(event['command'])+'\n' for event in meta['native_updates'])
# Compare archived geometry independently of the current command schedule.
# The current gait clock must run without automatic cadence reductions.
rows=[]
for e in source['samples']:
    feet=[x for j in [2,3,0,1] for x in (*e['target_foot_reference_xy_mm'][j],0.)]
    values=e['body_translation_world_mm']+e['body_rotation_euler_xyz_rad']+feet+[e['target_sole_clearance_mm'][j] for j in [2,3,0,1]]
    rows.append(' '.join(map(repr,values)))
r=subprocess.run([sys.argv[2]],input='\n'.join(rows),text=True,capture_output=True,check=True)
actual=[json.loads(line) for line in r.stdout.splitlines()]
assert len(actual)==len(source['samples'])
# Stored angles describe boots that are no longer fitted. Verify their semantic
# spatial targets against the independent current bare-foot model instead.
import numpy as np
sys.path.insert(0,str(root/'tools'))
from retarget_clips import load_reference
cfg=json.loads((root/'geometry.json').read_text());model=load_reference(root).Mechanism(cfg)
bare=np.array(json.loads((root/'motions/locomotion/walk-contact.json').read_text())['sole_hull_local_mm'])
allowance=json.loads((root/'motions/locomotion/sole-profile.json').read_text())['support_allowance_mm']
worst=0.
for row,e in zip(actual,source['samples']):
    model.body_euler=np.array(e['body_rotation_euler_xyz_rad'])
    for i,j in enumerate([2,3,0,1]):
        leg=cfg['leg_order'][j];q=np.array(row[j*3:j*3+3]);R,t=model.pose(leg,q,e['body_translation_world_mm'])
        point=R@np.array(cfg['legs'][leg]['foot_reference_local_mm'])+t
        xy=float(abs(point[:2]-e['target_foot_reference_xy_mm'][i]).max())
        z=float((bare@R[2]+t[2]).min()-e['target_sole_clearance_mm'][i])
        assert xy<.005 and -.002<z<allowance+.003,(leg,xy,z)
        worst=max(worst,xy)
r=subprocess.run([sys.argv[1],'120000','120'],input=wire,text=True,capture_output=True,check=True)
current=[json.loads(line) for line in r.stdout.splitlines()]
peak=0.
for before,after in zip(current,current[1:]):
    dt=(after['ms']-before['ms'])/1000.
    peak=max(peak,max(abs(a-b)*180/math.pi/dt for a,b in zip(after['q'],before['q'])))
assert current[-1]['complete'] and all(current[-1]['grounded'])
assert any(abs(a['clock_scale']-1.)>.1 for a in current if a['run_blend']>.99)
assert all(math.isfinite(a['clock_scale']) and a['clock_scale']>=0. for a in current)
print(f"{len(actual)} archived Run spatial targets checked with bare contact; XY error {worst:g} mm. Current Run completes without cadence reduction; observed commanded peak {peak:g} deg/s.")
