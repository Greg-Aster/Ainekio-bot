"""Independent saved Blender reference versus native C, including physical joint IDs."""
import json,math,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=json.loads((root/'motions/walk/source.json').read_text())['columns']
rows=[]
for body,euler,feet,sole in zip(source['body'],source['body_euler'],source['feet'],source['sole_z']):
    rows.append(' '.join(map(repr,body+euler+[x for leg in feet for x in leg]+sole)))
beg=time.perf_counter();result=subprocess.run([sys.argv[2]],input='\n'.join(rows),capture_output=True,text=True,check=True)
actual=[json.loads(line) for line in result.stdout.splitlines()];assert len(actual)==len(rows)
error=max(abs(a-b) for row,expected in zip(actual,source['q']) for a,b in zip(row,[x for leg in expected for x in leg]))
assert error<math.radians(.3),error
# The demo's full-stride hold supplies a separate whole-planner comparison.
indices=[i for i,p in enumerate(source['phase']) if 4.4<=p<=5.9][::8]
requests=''.join(f'{source["phase"][i]} 100 1\n' for i in indices)
result=subprocess.run([sys.argv[1]],input=requests,capture_output=True,text=True,check=True)
pose_rows=[json.loads(row) for row in result.stdout.splitlines()];assert len(pose_rows)==len(indices)
planner_error=0.
for i,actual_row in zip(indices,pose_rows):
    expected=[math.degrees(x)*100 for leg in [source['q'][i][j] for j in [2,3,0,1]] for x in leg]
    planner_error=max(planner_error,max(abs(a-b) for a,b in zip(actual_row,expected))/100)
# Upcoming anchors in the ramp anticipate the previous/next stride. Use the
# interior hold after all four legs have settled to the constant path.
assert planner_error<.3,planner_error
print(json.dumps({'reference_poses':len(rows),'native_joint_max_error_deg':math.degrees(error),'whole_planner_max_error_deg':planner_error,'source_joint_remapping':[2,3,0,1],'host_total_seconds':time.perf_counter()-beg}))
