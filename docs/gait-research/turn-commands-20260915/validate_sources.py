"""Source provenance, interpolation bounds and independently solved mirror checks."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from generate_turns import COMMANDS
from sample_reference import Motion

P=Path(__file__).resolve().parent
records=[];pairs={}
for command in COMMANDS:
    folder=P/'commands'/command
    source=json.loads((folder/'source.json').read_text())
    manifest=json.loads((folder/'manifest.json').read_text())
    for file,key in [(folder/'source.json','source_sha256'),(folder/'source.csv','csv_sha256'),
                     (P/'robot-gait-parameters.json','geometry_sha256'),(P/'sole-hulls.npz','sole_hulls_sha256')]:
        assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest[key],(command,key)
    cfg=source['metadata']['configuration'];rows=source['samples']
    q=np.array([r['actuator_angles_rad'] for r in rows]);body=np.array([r['body_position_world_mm'] for r in rows])
    yaw=np.array([r['body_yaw_world_rad'] for r in rows])
    assert np.isfinite(q).all() and q.shape==(manifest['sample_count'],4,3)
    assert np.max(abs(np.array([r['time_s'] for r in rows])-np.arange(len(rows))/120))<1e-8
    assert abs(math.degrees(yaw[-1])-manifest['heading_change_degrees'])<1e-8
    assert np.min(np.diff(yaw)*np.sign(yaw[-1]))>=-1e-10
    assert np.linalg.norm(body[-1,:2]-body[0,:2])<1e-7
    assert np.max(abs(np.diff(np.degrees(q),axis=0)))<3.,command
    for j,name in enumerate(['h','alpha','theta']):
        lo,hi=cfg['geometric_research_angle_bounds_degrees'][name]
        assert np.min(np.degrees(q[:,:,j]))>=lo-1e-6 and np.max(np.degrees(q[:,:,j]))<=hi+1e-6
    motion=Motion(folder);p=np.array(motion.positions);v=np.array(motion.velocities)
    secant=(p[1:]-p[:-1])*120;c2=3*secant-2*v[:-1]-v[1:];c3=v[:-1]+v[1:]-2*secant
    half=p[:-1]+(v[:-1]*.5+c2*.25+c3*.125)/120
    assert np.all(half>=np.minimum(p[:-1],p[1:])-1e-8) and np.all(half<=np.maximum(p[:-1],p[1:])+1e-8)
    peaks=np.maximum(abs(v[:-1]),abs(v[1:]))
    with np.errstate(divide='ignore',invalid='ignore'):u=-c2/(3*c3)
    interior=(u>0)&(u<1)
    candidate=v[:-1]+2*c2*np.where(interior,u,0)+3*c3*np.where(interior,u,0)**2
    peaks=np.maximum(peaks,np.where(interior,abs(candidate),0))
    acceleration=np.maximum(abs(2*c2*120),abs((2*c2+6*c3)*120))
    record=dict(command=command,source_hash_verified=True,interpolation_midpoints_checked=len(half),
                peak_interpolated_speed_degrees_s=float(peaks.max()/100),
                peak_interpolated_acceleration_degrees_s2=float(acceleration.max()/100),
                interpolation_continuity='C1; acceleration may jump at keys and contact-feature transfers',
                continuous_bounded_angles=True,heading_change_degrees=math.degrees(yaw[-1]))
    (folder/'interpolation-validation.json').write_text(json.dumps(record,indent=2)+'\n');records.append(record)
    assert motion.sample(motion.duration_us)['complete']
    assert motion.sample(motion.duration_us)['position']==motion.positions[-1]
    pairs[command]=(q,body,yaw)
mirror=[]
for angle in [180,90,45,15]:
    qr,br,yr=pairs[f'turn_right_{angle}'];ql,bl,yl=pairs[f'turn_left_{angle}']
    expected=qr[:,[1,0,3,2],:]*[-1,1,1]
    error=float(np.max(abs(np.degrees(ql-expected))))
    berror=float(np.max(abs(bl-br*[1,-1,1])))
    # Measured left/right CAD coordinates retain tiny import-rounding differences.
    # 0.0001 degree is far below the source geometry's demonstrated mesh precision.
    assert error<1e-4 and berror<1e-5 and np.max(abs(yr+yl))<1e-9
    mirror.append(dict(angle=angle,joint_mirror_error_degrees=error,body_mirror_error_mm=berror,
                       method='Independent IK on measured left/right legs; compare paired legs and reflected paths'))
(P/'source-validation.json').write_text(json.dumps(dict(commands=records,mirror_pairs=mirror),indent=2)+'\n')
print(json.dumps(dict(commands_verified=len(records),mirrors_verified=len(mirror),maximum_mirror_error_degrees=max(x['joint_mirror_error_degrees'] for x in mirror))))
