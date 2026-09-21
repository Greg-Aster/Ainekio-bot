"""Evaluate actual saved Blender linkage and soles at representative/subframe poses."""
import bpy,json,sys
from pathlib import Path
P=Path(__file__).resolve().parent
index=json.loads((P/'motion-index.json').read_text())
base=P.parent/'robot-bow-20260916/check_blender.py'
source=base.read_text()
source=source.replace("chosen=sorted(set(round(t*cfg['sample_hz']) for t in [0.,.5,1.,1.5,2.,2.5,3.5,5.5,6.,6.5,7.,7.5,8.,8.5]))", "chosen=sorted(set([0,len(rows)-1]+[round(x) for x in np.linspace(0,len(rows)-1,12)]+[round((p['start']+p['end'])*cfg['sample_hz']/2) for p in d['phases']]))")
reports=[]
selected=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
for item in index['commands']:
 if selected and item['command'] not in selected:continue
 folder=P/'commands'/item['command']
 # Every command uses identical measured geometry; reload local import explicitly.
 for name in ['gait_kinematics']:sys.modules.pop(name,None)
 exec(compile(source,str(folder/'check_blender.py'),'exec'),{'__file__':str(folder/'check_blender.py')})
 r=json.loads((folder/'blender-validation.json').read_text());reports.append(dict(command=item['command'],**{k:v for k,v in r.items() if k!='poses'}))
 (folder/'check_blender.py').write_text(source)
previous=json.loads((P/'blender-review-summary.json').read_text()) if selected and (P/'blender-review-summary.json').exists() else []
by_name={r['command']:r for r in previous+reports}
(P/'blender-review-summary.json').write_text(json.dumps(list(by_name.values()),indent=2)+'\n')
exec(compile((P/'check_preservation.py').read_text(),str(P/'check_preservation.py'),'exec'),{'__file__':str(P/'check_preservation.py')})
