"""Geometry only: CAD millimeters, radians, q=(hip002, upper006, crank005).

No servo commands or collision checking. Limits are individual sweep evidence,
not a proven combined workspace. Default endpoint is the foot bolt datum.
"""
import json
import math as m
from pathlib import Path

PARAMETERS=json.loads(Path(__file__).with_name('robot-gait-parameters.json').read_text())
TAU=2*m.pi

def add(a,b): return [x+y for x,y in zip(a,b)]
def sub(a,b): return [x-y for x,y in zip(a,b)]
def norm(a): return m.sqrt(sum(x*x for x in a))
def arg(a): return m.atan2(a[1],a[0])
def wrap(a): return (a+m.pi)%TAU-m.pi
def rot(a,v):
    c,s=m.cos(a),m.sin(a)
    return [c*v[0]-s*v[1],s*v[0]+c*v[1]]
def acos_checked(x):
    if x < -1-1e-10 or x > 1+1e-10:
        raise ValueError('Target cannot satisfy linkage geometry')
    return m.acos(max(-1,min(1,x)))

def fk(leg,h=0.0,alpha=0.0,theta=0.0,foot_reference=None):
    p=PARAMETERS['legs'][leg]
    v=p['pivots_xy_mm']; O,C=v['O'],v['C']
    F0=foot_reference or p['foot_bolt_reference_xyz_mm']
    P=add(C,rot(theta,sub(v['P'],C)))
    w=sub(P,O); d=norm(w); a=norm(sub(v['Q'],O))
    L=p['lengths_mm']['coupler_PQ']
    if d<1e-12: raise ValueError('Four-bar circle centers coincide')
    psi=arg(w)+p['fourbar_assembly_branch_sign']*acos_checked((a*a+d*d-L*L)/(2*a*d))
    beta=wrap(psi-arg(sub(v['Q'],O)))
    Q=add(O,rot(beta,sub(v['Q'],O)))
    B=add(O,rot(beta,sub(v['B'],O)))
    D=add(O,rot(alpha,sub(v['D'],O)))
    E=add(D,rot(beta,sub(v['E'],v['D'])))
    F=add(D,rot(beta,sub(F0[:2],v['D'])))
    H=p['hip_axis_point_xyz_mm']
    yz=rot(h,[F[1]-H[1],F0[2]-H[2]])
    return dict(foot_CAD_xyz_mm=[F[0],H[1]+yz[0],H[2]+yz[1]],
                beta=beta,planar_pivots=dict(P=P,Q=Q,B=B,D=D,E=E,F=F))

def ik(leg,target_CAD_xyz_mm,seed=(0.0,0.0,0.0),foot_reference=None):
    """Return geometric branches closest to seed first; no collision/limit filter.

    Each result is (h002,alpha006,theta005), all radians about positive CAD axes.
    Caller must check joint calibration, limits, contacts and branch continuity.
    """
    p=PARAMETERS['legs'][leg]; v=p['pivots_xy_mm']; O,C=v['O'],v['C']
    F0=foot_reference or p['foot_bolt_reference_xyz_mm']
    H=p['hip_axis_point_xyz_mm']; target=target_CAD_xyz_mm
    yz=[target[1]-H[1],target[2]-H[2]]; z0=F0[2]-H[2]
    y2=sum(x*x for x in yz)-z0*z0
    if y2 < -1e-7: return []
    l1=norm(sub(v['D'],O)); l2=norm(sub(F0[:2],v['D']))
    r=norm(sub(v['P'],C)); L=p['lengths_mm']['coupler_PQ']
    found=[]
    for sign_h in (1,-1):
        y0=sign_h*m.sqrt(max(0,y2)); h=wrap(arg(yz)-arg([y0,z0]))
        F=[target[0],H[1]+y0]; w=sub(F,O); d=norm(w)
        if d<1e-12: continue
        try: opening=acos_checked((l1*l1+d*d-l2*l2)/(2*l1*d))
        except ValueError: continue
        for elbow in (-1,1):
            A=arg(w)+elbow*opening; alpha=wrap(A-arg(sub(v['D'],O)))
            D=add(O,rot(alpha,sub(v['D'],O)))
            beta=wrap(arg(sub(F,D))-arg(sub(F0[:2],v['D'])))
            Q=add(O,rot(beta,sub(v['Q'],O))); wq=sub(Q,C); dq=norm(wq)
            if dq<1e-12: continue
            try: opening_p=acos_checked((r*r+dq*dq-L*L)/(2*r*dq))
            except ValueError: continue
            for crank in (-1,1):
                theta=wrap(arg(wq)+crank*opening_p-arg(sub(v['P'],C)))
                candidate=(h,alpha,theta)
                try: result=fk(leg,*candidate,foot_reference=F0)
                except ValueError: continue
                if abs(wrap(result['beta']-beta))>1e-7: continue
                if norm(sub(result['foot_CAD_xyz_mm'],target))>1e-5: continue
                if not any(norm([wrap(a-b) for a,b in zip(candidate,q)])<1e-7 for q in found):
                    found.append(candidate)
    return sorted(found,key=lambda q:sum(wrap(a-b)**2 for a,b in zip(q,seed)))

def cad_to_body(point):
    d=sub(point,PARAMETERS['controller_body_datum_CAD_xyz_mm'])
    return [d[0],d[2],-d[1]]

if __name__=='__main__':
    for leg in PARAMETERS['legs']:
        foot=fk(leg)['foot_CAD_xyz_mm']
        print(leg,'neutral CAD foot bolt mm:',[round(x,4) for x in foot],
              'inverse angles deg:',[round(m.degrees(x),6) for x in ik(leg,foot)[0]])
