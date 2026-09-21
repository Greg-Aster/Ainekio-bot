"""Read-only reference for firmware ports: twelve signed geometric joint tracks.

python sample_reference.py 3000
Time is elapsed milliseconds; output is CAD centidegrees and its derivatives.
"""
import argparse
import json
import math
from pathlib import Path

P=Path(__file__).resolve().parent


class Motion:
    def __init__(self, folder):
        source=json.loads((Path(folder)/'source.json').read_text())
        self.hz=source['metadata']['configuration']['sample_hz']
        self.positions=[[math.degrees(v)*100 for leg in r['actuator_angles_rad'] for v in leg] for r in source['samples']]
        slopes=[[(b-a)*self.hz for a,b in zip(p,q)] for p,q in zip(self.positions,self.positions[1:])]
        self.velocities=[[0.]*12]+[[2*a*b/(a+b) if a*b>0 else 0. for a,b in zip(p,q)]
                                 for p,q in zip(slopes,slopes[1:])]+[[0.]*12]
        self.duration_us=round(source['samples'][-1]['time_s']*1000000)

    def sample(self, elapsed_us):
        if not isinstance(elapsed_us,int) or elapsed_us<0:
            raise ValueError('elapsed_us must be a nonnegative integer')
        if elapsed_us>=self.duration_us:
            return dict(position=self.positions[-1],velocity=[0.]*12,acceleration=[0.]*12,complete=True)
        index,remainder=divmod(elapsed_us*self.hz,1000000)
        u=remainder/1000000.;dt=1/self.hz
        position=[];velocity=[];acceleration=[]
        for p0,p1,v0,v1 in zip(self.positions[index],self.positions[index+1],self.velocities[index],self.velocities[index+1]):
            secant=(p1-p0)/dt;c2=3*secant-2*v0-v1;c3=v0+v1-2*secant
            position.append(p0+dt*(v0*u+c2*u*u+c3*u*u*u))
            velocity.append(v0+2*c2*u+3*c3*u*u)
            acceleration.append((2*c2+6*c3*u)/dt)
        return dict(position=position,velocity=velocity,acceleration=acceleration,complete=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elapsed_ms',type=int)
    args=parser.parse_args()
    result=Motion(P).sample(args.elapsed_ms*1000)
    result.update(command='nod',leg_order=['FL','FR','RL','RR'],joint_order=['h002','alpha006','theta005'],
                  units=['CAD centidegrees','centidegrees/second','centidegrees/second squared'],hardware_ready=False)
    print(json.dumps(result,indent=2))
