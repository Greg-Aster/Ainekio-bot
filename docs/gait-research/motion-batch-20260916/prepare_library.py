"""Assign final contiguous slots and export every completed command."""
import json,shutil,subprocess,sys
from pathlib import Path
P=Path(__file__).resolve().parent
names=['cute','freaky','worm','shake','shrug','dead','crab','celebrate','stretch','surprised','sad','curious'];base=P.parent/'robot-bow-20260916';start=3109;items=[]
for name in names:
 folder=P/'commands'/name;d=json.loads((folder/'source.json').read_text());cfg=d['metadata']['configuration'];cfg.update(gait_start_frame=start,existing_animation_end_frame=start-24,source_blend=str(P/'Before-Motion-Batch.blend'),output_blend=str(P/'Ainekio-Motion-Library.blend'),scene_name='AINEKIO - Motion Library')
 end=start+round(d['samples'][-1]['time_s']*24);sem=start+round(cfg.get('semantic_end_s',d['samples'][-1]['time_s'])*24)
 # Select meaningful pose snapshots from gesture phases, excluding setup/recovery.
 phases=[p for p in d['phases'] if not any(s in p['kind'] for s in ['standing','return','recover','entry','lower_body','splay','brace'])]
 if not phases:phases=d['phases'][1:-1] or d['phases']
 chosen=[phases[min(len(phases)-1,round(k*(len(phases)-1)/2))] for k in range(3)]
 review=[start+round((p['start']+p['end'])*12) for p in chosen]
 item=dict(command=name,label=cfg['display_label'],start_frame=start,end_frame=end,semantic_end_frame=sem,next_start_frame=end+24,duration_s=d['samples'][-1]['time_s'],review_frames=review,source=f'commands/{name}/source.json',contact_model=cfg['contact_model'])
 items.append(item)
 (folder/'config.json').write_text(json.dumps(cfg,indent=2)+'\n');(folder/'source.json').write_text(json.dumps(d,separators=(',',':'),allow_nan=False)+'\n')
 for file in ['sample_reference.py','execution-policy.json']:
  shutil.copy2(base/file,folder/file)
 for file in ['blender-rig.json','robot-gait-parameters.json','saved-neutral-snapshot.json','body-and-face-reference.json','body-samples.npz','sole-hulls.npz']:
  if not (folder/file).exists():shutil.copy2(base/file,folder/file)
 shutil.copy2(P/'export_command.py',folder/'export_command.py')
 shutil.copy2(P/'timing.py',folder/'timing.py')
 subprocess.run([sys.executable,str(folder/'export_command.py')],check=True)
 start=end+24
index=dict(created='2026-09-16',source_backup='Before-Motion-Batch.blend',saved_blend='Ainekio-Motion-Library.blend',prior_animation_end_frame=3085,render_fps=24,source_sample_hz=120,aliases={'strech':'stretch'},commands=items)
(P/'motion-index.json').write_text(json.dumps(index,indent=2)+'\n')
print('READY',len(items),'motions; final frame',items[-1]['end_frame'])
