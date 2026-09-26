"""Desktop full-CAD validation of native controller outputs (NumPy/SciPy).

Uses the retained independent double-precision forward model and every original
sole vertex. No reference joint output is fed back into the native controller.
"""
import argparse, importlib.util, json, math, subprocess
from pathlib import Path
try:
    import numpy as np
    from build_sole_profile import distances
    from validate_locomotion import leverage_report
except ImportError:
    raise SystemExit(77)


def main(root, binary):
    spec=importlib.util.spec_from_file_location('cad_reference',root/'motions/walk/reference.py')
    ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
    cfg=json.loads((root/'geometry.json').read_text());contact=json.loads((root/'motions/locomotion/contact-hulls.json').read_text())
    profile=json.loads((root/'motions/locomotion/sole-profile.json').read_text());m=ref.Mechanism(cfg)
    bounds={}
    for gait in ('walk','crawl'):
        compact=np.array(profile['profiles'][gait]);maximum=0.
        for leg in cfg['leg_order']:
            original=np.array(cfg['legs'][leg]['sole_hull_local_mm'] if gait=='walk' else contact['soles'][leg])
            maximum=max(maximum,float(distances(original,compact).max()))
        assert maximum<profile['support_allowance_mm']-.0001
        bounds[gait]=maximum
    low=json.loads((root/'motions/locomotion/config.json').read_text())
    crab=json.loads((root/'motions/locomotion/crab.json').read_text())
    reviewed=np.load(root/'motions/gestures/reviewed-hulls.npz')
    leverage={}
    xy=0.;zlow=math.inf;zhigh=-math.inf;step=0.;count=0
    for gait in ('walk','crawl','run','crab'):
        m.hulls={leg:np.asarray(contact['soles'][leg] if gait=='crawl' else cfg['legs'][leg]['sole_hull_local_mm']) for leg in cfg['leg_order']}
        if gait=='crab':m.hulls={leg:reviewed['sole_'+leg] for leg in cfg['leg_order']}
        for direction in (('fwd','back','turn_l','turn_r','side_l','side_r') if gait=='crab' else ('fwd','back','turn_l','turn_r')):
            for hz in (25,50):
                initial=dict(t='intent',seq=1,name='walk',dir=direction,gait=gait,steps=0,speed=100)
                events=[(2000,200 if gait in ('walk','run') else 25),(4000,75),(6000,200 if gait in ('walk','run') else 100),(8500,0)]
                wire=json.dumps(initial)+'\n'
                for seq,(time,speed) in enumerate(events,2):
                    update=dict(initial,seq=seq,speed=speed,update=1)
                    wire+=str(time)+' '+json.dumps(update)+'\n'
                result=subprocess.run([str(binary),'20000',str(hz)],input=wire,text=True,capture_output=True)
                if result.returncode:raise RuntimeError((gait,direction,hz,result.returncode,result.stderr))
                rows=[json.loads(line) for line in result.stdout.splitlines()]
                assert rows[-1]['complete'] and all(rows[-1]['grounded'])
                leverage[f'{gait}/{direction}/{hz}']=leverage_report(cfg,np.array([r['q'] for r in rows]).reshape(-1,4,3),[r['grounded'] for r in rows],low['leverage_validation'])
                previous=None
                for row in rows:
                    m.body_euler=np.asarray(row['euler']);q=np.array(row['q']).reshape(4,3)
                    if previous is not None:step=max(step,float(abs(q-previous).max()))
                    previous=q
                    for i,leg in enumerate(cfg['leg_order']):
                        R,t=m.pose(leg,q[i],row['body']);point=R@np.asarray(cfg['legs'][leg]['foot_reference_local_mm'])+t
                        sole=float((m.hulls[leg]@R[2]+t[2]).min());error=sole-row['feet'][i][2]
                        xy=max(xy,float(abs(point[:2]-row['feet'][i][:2]).max()))
                        assert -.001<error<profile['support_allowance_mm']+(crab['sole_refinement_allowance_mm'] if gait=='crab' else .002),(gait,direction,hz,error)
                        zlow=min(zlow,error);zhigh=max(zhigh,error)
                    count+=1
    # Every pose uses its own profile allowance above; do not hide XY or
    # below-target errors behind the sole refinement allowance.
    assert xy<.005 and zlow>-.001,(xy,zlow,zhigh)
    result=dict(leverage=leverage,samples=count,whole_hull_distance_bound_mm=bounds,foot_xy_error_mm=xy,full_sole_height_error_mm=[zlow,zhigh],max_output_step_degrees=math.degrees(step))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('binary',type=Path)
    a=parser.parse_args();main(a.root,a.binary)
