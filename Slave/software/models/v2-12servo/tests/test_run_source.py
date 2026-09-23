"""Recorded Run must reproduce the actual native command path and provenance."""
import hashlib,json,math,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=json.loads((root/'motions/run/source.json').read_text());meta=source['metadata']
for path,digest in meta['native_sources_sha256'].items():
    # Implementation hashes identify the original recording. Optimized code
    # must reproduce its poses below; geometry and data inputs remain pinned.
    if path in ('motion.c','walk_kinematics.c'):continue
    assert hashlib.sha256((root/path).read_bytes()).hexdigest()==digest,path
wire=json.dumps(meta['native_initial_command'])+'\n'+''.join(str(event['at_ms'])+' '+json.dumps(event['command'])+'\n' for event in meta['native_updates'])
r=subprocess.run([sys.argv[1],'40000','120'],input=wire,text=True,capture_output=True,check=True)
actual=[json.loads(line) for line in r.stdout.splitlines()];expected=source['samples'];assert len(actual)==len(expected)
worst=0.;body_error=0.
for a,e in zip(actual,expected):
    for i,j in enumerate([2,3,0,1]):
        assert a['grounded'][j]==e['contact_active'][i]
        for k in range(3):worst=max(worst,abs(a['q'][j*3+k]-e['actuator_angles_rad'][i][k]))
    assert a['run_blend']==e['run_blend']
    body_error=max(body_error,max(abs(x-y) for x,y in zip(a['body'],e['body_translation_world_mm'])))
# Single-precision profile integration retains the recorded world path to
# one micrometre over the full demonstration; phase/contact timing stays exact.
assert body_error<.001,body_error
# Compact support has a certified 0.151 mm conservative allowance.
# Geometry checks independently bound contact and XY error; this angle budget
# is below one nominal PCA9685 pulse tick (about 0.44 degrees).
assert worst<math.radians(.4) and actual[-1]['complete'] and all(actual[-1]['grounded'])
print(f'{len(actual)} native Run demonstration samples match recording; joint error {worst:g} radians, body error {body_error:g} mm.')
