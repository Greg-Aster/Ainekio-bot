"""Encode complete previews; require every expected render before exporting."""
import json,math,subprocess,sys
from pathlib import Path
P=Path(__file__).resolve().parent
names=sys.argv[1:]
for m in json.loads((P/'motion-index.json').read_text())['commands']:
 if names and m['command'] not in names:continue
 folder=P/'commands'/m['command'];n=math.ceil(m['duration_s']*6)
 assert all((folder/'preview-frames'/f'{i:04}.png').exists() for i in range(n)),m['command']
 subprocess.run(['ffmpeg','-y','-loglevel','error','-framerate','6','-i',str(folder/'preview-frames/%04d.png'),'-t',str(m['duration_s']),'-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-r','24','-movflags','+faststart',str(folder/'preview.mp4')],check=True)
 result=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(folder/'preview.mp4')]))
 measured=float(result['format']['duration']);assert abs(measured-m['duration_s'])<1/24+.001
 print(json.dumps(dict(command=m['command'],render_frames=n,preview_duration_s=measured)),flush=True)
