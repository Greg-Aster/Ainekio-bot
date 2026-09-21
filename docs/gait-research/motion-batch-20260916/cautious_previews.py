"""One preview child at a time. Launch inside the documented systemd memory cap."""
import json,math,os,subprocess,time,fcntl,signal
from pathlib import Path
P=Path(__file__).resolve().parent
lock=(P/'preview-worker.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
MIN_AVAILABLE_KB=20*1024*1024
SOFT_RSS_KB=8*1024*1024

def memory_available():
 return int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))
def valid(path):
 try:
  with path.open('rb') as f:
   first=f.read(8);f.seek(-12,2);last=f.read(12)
  return first==b'\x89PNG\r\n\x1a\n' and last==b'\x00\x00\x00\x00IEND\xaeB`\x82'
 except (OSError,ValueError):return False
def progress():
 total=done=0
 for m in json.loads((P/'motion-index.json').read_text())['commands']:
  f=P/'commands'/m['command'];paths=[f/'preview-frames'/f'{j:04}.png' for j in range(math.ceil(m['duration_s']*6))]+[f/f'pose-{j}.png' for j in range(1,4)]
  total+=len(paths);done+=sum(valid(x) for x in paths)
 return done,total

def status(**values):
 values.update(time_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),memory_available_kib=memory_available())
 (P/'cautious-render-status.json').write_text(json.dumps(values,indent=2)+'\n')
child=None;history=[]
try:
 while True:
  done,total=progress()
  if done==total:status(state='complete',done=done,total=total,chunks=history);break
  if memory_available()<MIN_AVAILABLE_KB:status(state='stopped_low_host_memory',done=done,total=total,chunks=history);break
  if (P/'STOP_PREVIEWS').exists():status(state='stopped_by_request',done=done,total=total,chunks=history);break
  batch=len(history)+1;peak=0;reason=None
  env=os.environ.copy();env.update(AINEKIO_MAX_RENDER_FRAMES='12',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1')
  with (P/f'cautious-render-{batch:03}.log').open('w') as log:
   child=subprocess.Popen([str(P.parent/'blender'),'-b',str(P/'Ainekio-Motion-Library.blend'),'-t','2','--python',str(P/'render_batch.py')],cwd=P.parent,stdout=log,stderr=subprocess.STDOUT,env=env)
   while child.poll() is None:
    try:rss=int(next(l.split()[1] for l in Path(f'/proc/{child.pid}/status').read_text().splitlines() if l.startswith('VmRSS:')))
    except (OSError,StopIteration):rss=0
    peak=max(peak,rss)
    status(state='rendering',done=done,total=total,child_pid=child.pid,chunk=batch,peak_child_rss_kib=peak,chunks=history)
    if memory_available()<MIN_AVAILABLE_KB:reason='low_host_memory'
    if rss>SOFT_RSS_KB:reason='child_memory_limit'
    if (P/'STOP_PREVIEWS').exists():reason='owner_stop'
    if reason:
     child.terminate()
     try:child.wait(timeout=5)
     except subprocess.TimeoutExpired:child.kill();child.wait()
     break
    time.sleep(1)
  code=child.returncode;child=None;new_done,_=progress();history.append(dict(chunk=batch,exit_code=code,completed=new_done-done,peak_rss_kib=peak,stop_reason=reason))
  if reason or code!=0 or new_done<=done:status(state='stopped',reason=reason or 'worker_failure_or_no_progress',done=new_done,total=total,chunks=history);break
finally:
 if child and child.poll() is None:child.terminate();child.wait()
