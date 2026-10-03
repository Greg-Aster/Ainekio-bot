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
# The owner-selected ceiling deliberately changes wall-clock timing. Compare
# the archived geometry independently, then verify current command timing.
rows=[]
for e in source['samples']:
    feet=[x for j in [2,3,0,1] for x in (*e['target_foot_reference_xy_mm'][j],0.)]
    values=e['body_translation_world_mm']+e['body_rotation_euler_xyz_rad']+feet+[e['target_sole_clearance_mm'][j] for j in [2,3,0,1]]
    rows.append(' '.join(map(repr,values)))
r=subprocess.run([sys.argv[2]],input='\n'.join(rows),text=True,capture_output=True,check=True)
actual=[json.loads(line) for line in r.stdout.splitlines()]
assert len(actual)==len(source['samples'])
worst=max(abs(a[j*3+k]-e['actuator_angles_rad'][i][k])
          for a,e in zip(actual,source['samples']) for i,j in enumerate([2,3,0,1]) for k in range(3))
assert worst<math.radians(.4),worst
r=subprocess.run([sys.argv[1],'120000','120'],input=wire,text=True,capture_output=True,check=True)
current=[json.loads(line) for line in r.stdout.splitlines()]
limit=json.loads((root/'servo_profile.json').read_text())['gait_max_joint_speed_degrees_s']
peak=0.
for before,after in zip(current,current[1:]):
    dt=(after['ms']-before['ms'])/1000.
    peak=max(peak,max(abs(a-b)*180/math.pi/dt for a,b in zip(after['q'],before['q'])))
assert peak<=limit+.1,peak
assert current[-1]['complete'] and all(current[-1]['grounded'])
assert any(a['clock_scale']<.999 for a in current)
print(f"{len(actual)} archived Run geometry samples match; joint error {worst:g} radians. Current coordinated Run completes within configured {limit:g} deg/s, observed peak {peak:g}.")
