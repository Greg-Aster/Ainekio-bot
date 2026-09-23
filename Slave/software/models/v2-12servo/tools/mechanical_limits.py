"""Canonical V2 model-angle limits; standard-library consumer for all generators."""
import bisect,json,math
from pathlib import Path

class Limits:
    def __init__(self,root=None):
        root=Path(root) if root is not None else Path(__file__).resolve().parents[1]
        self.profile=json.loads((root/'servo_profile.json').read_text())
        self.bounds=self.profile['joint_bounds_degrees'];self.nodes=self.profile['coupled_envelope']['nodes'];self.theta=[r[0] for r in self.nodes]
        if any(len(r)!=3 or r[1]>=r[2] for r in self.nodes) or any(a>=b for a,b in zip(self.theta,self.theta[1:])):raise ValueError('invalid coupled envelope')
    def alpha_bounds(self,theta):
        if not math.isfinite(theta) or theta<self.theta[0] or theta>self.theta[-1]:return None
        i=min(len(self.nodes)-2,max(0,bisect.bisect_right(self.theta,theta)-1));a,b=self.nodes[i:i+2];u=(theta-a[0])/(b[0]-a[0])
        return (a[1]+u*(b[1]-a[1]),a[2]+u*(b[2]-a[2]))
    def allowed_degrees(self,q,tolerance=1e-6):
        if len(q)!=3 or any(not math.isfinite(x) for x in q):return False
        if any(x<lo-tolerance or x>hi+tolerance for x,(lo,hi) in zip(q,self.bounds)):return False
        theta=min(self.theta[-1],max(self.theta[0],q[2]));ab=self.alpha_bounds(theta)
        return ab is not None and ab[0]-tolerance<=q[1]<=ab[1]+tolerance
    def allowed(self,q):return self.allowed_degrees([math.degrees(x) for x in q])
    def box_allowed(self,low,high):
        if any(l<b[0]-1e-6 or h>b[1]+1e-6 for l,h,b in zip(low,high,self.bounds)):return False
        xs=[max(self.theta[0],low[2]),min(self.theta[-1],high[2])]+[t for t in self.theta if low[2]<t<high[2]]
        intervals=[self.alpha_bounds(t) for t in xs]
        return all(x is not None for x in intervals) and low[1]>=max(x[0] for x in intervals)-1e-6 and high[1]<=min(x[1] for x in intervals)+1e-6
    def bezier_allowed(self,points,depth=0):
        """Conservative proof using convex hulls and recursive De Casteljau splits."""
        low=[min(p[j] for p in points) for j in range(3)];high=[max(p[j] for p in points) for j in range(3)]
        if self.box_allowed(low,high):return True
        if depth>=16 or not self.allowed_degrees(points[0]) or not self.allowed_degrees(points[-1]):return False
        def mid(a,b):return [(x+y)/2 for x,y in zip(a,b)]
        a,b,c,d=points;ab,bc,cd=mid(a,b),mid(b,c),mid(c,d);abc,bcd=mid(ab,bc),mid(bc,cd);middle=mid(abc,bcd)
        return self.bezier_allowed([a,ab,abc,middle],depth+1) and self.bezier_allowed([middle,bcd,cd,d],depth+1)
    def verify_track(self,positions_cd,command):
        q=[[v/100 for v in row] for row in positions_cd];slopes=[[b-a for a,b in zip(x,y)] for x,y in zip(q,q[1:])]
        tangents=[[0.]*12]
        for a,b in zip(slopes,slopes[1:]):tangents.append([2*x*y/(x+y) if x*y>0 else 0. for x,y in zip(a,b)])
        tangents.append([0.]*12)
        for i,row in enumerate(q):
            for leg in range(4):
                j=3*leg
                if not self.allowed_degrees(row[j:j+3]):raise ValueError(f'{command}: joint limits at knot {i}, leg {leg}: {row[j:j+3]}')
                if i==len(q)-1:continue
                a=row[j:j+3];d=q[i+1][j:j+3];b=[x+v/3 for x,v in zip(a,tangents[i][j:j+3])];c=[x-v/3 for x,v in zip(d,tangents[i+1][j:j+3])]
                if not self.bezier_allowed([a,b,c,d]):raise ValueError(f'{command}: coupled interpolation bounds at segment {i}, leg {leg}')

