"""Batched tensor form of the maintained four-bar and P4 calibration math.

Source owners: walk_kinematics.c, learning.c, joint_calibration.c and transition.c.
CPU work is confined to construction. All rollout operations stay on the tensor
device; native C remains the deployment implementation and regression oracle.
"""
import math
import torch


def wrap(x):
    return torch.atan2(torch.sin(x), torch.cos(x))


class TensorBody:
    def __init__(self, geometry, config, *, device="cpu"):
        self.device = device
        def tensor(value):
            # The native linkage owner uses double precision. In particular,
            # its centidegree finite differences need this precision when the
            # GPU compiler fuses operations near a calibrated travel boundary.
            return torch.as_tensor(value, dtype=torch.float64, device=device)
        p=geometry["parameters"]
        self.O=tensor(p["O"]); self.C=tensor(p["C_new"])
        self.A=p["primary_length"]; self.r=p["input_length"]
        self.L=p["rod_length"]; self.b=p["pickup_length"]
        self.a0=p["alpha_neutral"]; self.t0=p["new_theta_neutral"]
        self.b0=p["beta_neutral"]; self.branch=p["assembly_branch"]
        order=geometry["leg_order"]; legs=[geometry["legs"][order[(i+2)%4]] for i in range(4)]
        self.sign=tensor([[round(g["shoulder_world"][i][i]) for i in range(3)] for g in legs])
        self.translation=tensor([[g["mechanism_local"][i][3] for i in range(3)] for g in legs])
        self.shoulder=tensor([[g["shoulder_world"][i][3] for i in range(3)] for g in legs])
        self.mirror=tensor([round(g["mechanism_local"][0][0]) for g in legs])
        self.reference=tensor([g["foot_reference_local_mm"] for g in legs])
        mapping=sorted(config.robot["calibration"],key=lambda j:j["id"])
        self.home=tensor([m["home_cd"]/100 for m in mapping]).reshape(4,3)
        self.pulse_home=tensor([m["home_us"] for m in mapping]).reshape(4,3)
        self.pulse_scale=tensor([(-1 if m["invert"] else 1)*m["us_per_degree"] for m in mapping]).reshape(4,3)
        a=self.home+(500-self.pulse_home)/self.pulse_scale
        b=self.home+(2800-self.pulse_home)/self.pulse_scale
        self.low=torch.minimum(a,b)*math.pi/180
        self.high=torch.maximum(a,b)*math.pi/180
        self.low[:,0]=-torch.inf;self.high[:,0]=torch.inf
        # Fit the fixed origin once with the authoritative deployment owner.
        from .native import BodyModel
        native=BodyModel(config.robot)
        try:
            origin=native.target(config.reference_joint_deg,config.reference_joint_deg,
                                 config.joint_speed_deg_s,0.)
            if origin is None:
                raise ValueError("The recorded reference has no calibrated four-bar pose")
            self.q0=tensor(origin[1]).reshape(4,3)*math.pi/180
        finally:
            native.close()
        self.origin,_=self.forward(self.q0)
        self.scale=tensor(config.foot_action_scale_mm)
        self.max_travel=math.radians(config.joint_speed_deg_s)/config.control_hz
        prescale=math.floor(config.pwm_oscillator_hz/(4096*config.pwm_frequency_hz)+.5)-1
        self.tick_us=(prescale+1)*1e6/config.pwm_oscillator_hz
        self.projection_fractions=tensor([2.**-i for i in range(8)])
        self.foot_fractions=tensor([2.**-i for i in range(13)])

    def circle(self,d2,radius,other):
        safe=d2.clamp_min(1e-8)
        along=(radius*radius-other*other+d2)/(2*safe)
        height=torch.sqrt((radius*radius/safe-along*along).clamp_min(0))
        valid=(d2>1e-8)&(d2>=(radius-other)**2)&(d2<=(radius+other)**2)
        return along,height,valid

    def seed(self,q):
        h,a,t=q.unbind(-1);a=a+self.a0;t=t+self.t0
        dx=self.O[0]+self.A*torch.cos(a);dz=self.O[1]+self.A*torch.sin(a)
        x=self.C[0]+self.r*torch.cos(t)-dx;z=self.C[1]+self.r*torch.sin(t)-dz
        along,height,valid=self.circle(x*x+z*z,self.b,self.L)
        height=height*self.branch
        bc=(along*x-height*z)/self.b;bs=(along*z+height*x)/self.b
        lc=bc*math.cos(self.b0)+bs*math.sin(self.b0)
        ls=bs*math.cos(self.b0)-bc*math.sin(self.b0)
        return dx,dz,bc,bs,lc,ls,valid

    def forward(self,q):
        dx,dz,bc,bs,lc,ls,valid=self.seed(q)
        h=q[...,0];ch=torch.cos(h);sh=torch.sin(h)
        x=dx+lc*self.reference[:,0]-ls*self.reference[:,2]
        y=self.translation[:,1]+self.reference[:,1]
        z=self.translation[:,2]+dz+ls*self.reference[:,0]+lc*self.reference[:,2]
        points=torch.stack((self.translation[:,0]+self.mirror*x,ch*y-sh*z,sh*y+ch*z),-1)
        return self.shoulder+self.sign*points,valid

    def inverse(self,target):
        v=(target-self.shoulder)*self.sign
        y=self.translation[:,1]+self.reference[:,1]
        zz=v[...,1]**2+v[...,2]**2-y*y
        z=-torch.sqrt(zz.clamp_min(0));norm=(v[...,1]**2+v[...,2]**2).clamp_min(1e-8)
        hc=(y*v[...,1]+z*v[...,2])/norm;hs=(y*v[...,2]-z*v[...,1])/norm
        x=(v[...,0]-self.translation[:,0])*self.mirror-self.O[0]
        z=z-self.translation[:,2]-self.O[1]
        length2=self.reference[:,0]**2+self.reference[:,2]**2
        along,height,valid=self.circle(x*x+z*z,self.A,torch.sqrt(length2))
        ax=self.O[0]+along*x-height*z;az=self.O[1]+along*z+height*x
        bx=self.O[0]+along*x+height*z;bz=self.O[1]+along*z-height*x
        dx0,dz0,bc0,bs0,*_=self.seed(self.q0)
        first=(ax-dx0)**2+(az-dz0)**2 <= (bx-dx0)**2+(bz-dz0)**2
        dx=torch.where(first,ax,bx);dz=torch.where(first,az,bz)
        lx=x+self.O[0]-dx;lz=z+self.O[1]-dz
        lc=(lx*self.reference[:,0]+lz*self.reference[:,2])/length2
        ls=(lz*self.reference[:,0]-lx*self.reference[:,2])/length2
        bc=math.cos(self.b0)*lc-math.sin(self.b0)*ls
        bs=math.sin(self.b0)*lc+math.cos(self.b0)*ls
        ex=dx+self.b*bc;ez=dz+self.b*bs
        cx=ex-self.C[0];cz=ez-self.C[1]
        ca,cht,crank_ok=self.circle(cx*cx+cz*cz,self.r,self.L)
        oldt=self.t0+self.q0[:,2]
        branch=(dx0+self.b*bc0-self.C[0])*torch.sin(oldt)-(dz0+self.b*bs0-self.C[1])*torch.cos(oldt)
        candidates=[];valids=[]
        for sign in (-1.,1.):
            px=self.C[0]+ca*cx-sign*cht*cz;pz=self.C[1]+ca*cz+sign*cht*cx
            angle=wrap(torch.atan2(pz-self.C[1],px-self.C[0])-self.t0)
            okay=((cx*(pz-self.C[1])-cz*(px-self.C[0]))*branch>0)
            okay &= ((px-dx)*(ez-dz)-(pz-dz)*(ex-dx))*self.branch>=0
            candidates.append(angle);valids.append(okay)
        distance0=wrap(candidates[0]-self.q0[:,2]).abs()
        distance1=wrap(candidates[1]-self.q0[:,2]).abs()
        choose=valids[0]&(~valids[1]|(distance0<=distance1))
        theta=torch.where(choose,candidates[0],candidates[1])
        q=torch.stack((torch.atan2(hs,hc),wrap(torch.atan2(dz-self.O[1],dx-self.O[0])-self.a0),theta),-1)
        return q,valid&crank_ok&(zz>=0)&(valids[0]|valids[1])

    def bounded(self,q):
        """Same eight projected Gauss-Newton passes and eight trials as P4."""
        target,_=self.forward(q)
        outside=((q<self.low)|(q>self.high)).any(-1)
        q=q.clamp(self.low,self.high)
        probe_step=math.pi/18000 # one centidegree, as walk_kinematics.c
        fractions=self.projection_fractions
        for _ in range(8):
            position,valid=self.forward(q);error=target-position;cost=error.square().sum(-1)
            jac=[];derivative_ok=valid
            for j in (1,2):
                step=torch.where(q[...,j]+probe_step<=self.high[:,j],probe_step,-probe_step)
                probe=q.clone();probe[...,j]+=step
                value,okay=self.forward(probe)
                jac.append((value-position)/step.unsqueeze(-1))
                derivative_ok=derivative_ok&okay&(q[...,j]+step>=self.low[:,j])
            ja,jb=jac;a=ja.square().sum(-1);b=(ja*jb).sum(-1);d=jb.square().sum(-1)
            e=(ja*error).sum(-1);f=(jb*error).sum(-1);det=a*d-b*b
            sa=torch.where(det>1e-12,(d*e-b*f)/det.clamp_min(1e-12),e/a.clamp_min(1e-12))
            sb=torch.where(det>1e-12,(a*f-b*e)/det.clamp_min(1e-12),f/d.clamp_min(1e-12))
            ba=((q[...,1]<=self.low[:,1])&(sa<0))|((q[...,1]>=self.high[:,1])&(sa>0))
            sa=torch.where(ba,0.,sa);sb=torch.where(ba,f/d.clamp_min(1e-12),sb)
            bb=((q[...,2]<=self.low[:,2])&(sb<0))|((q[...,2]>=self.high[:,2])&(sb>0))
            sb=torch.where(bb,0.,sb);sa=torch.where(bb,e/a.clamp_min(1e-12),sa)
            delta=torch.stack((torch.zeros_like(sa),sa,sb),-1)
            shape=(8,)+(1,)*(q.ndim-1)+(1,)
            probes=(q.unsqueeze(0)+fractions.reshape(shape)*delta.unsqueeze(0)).clamp(self.low,self.high)
            points,good=self.forward(probes)
            better=good&((target.unsqueeze(0)-points).square().sum(-1)<cost.unsqueeze(0))
            index=better.to(torch.int64).argmax(0)
            selected=torch.gather(probes,0,index.unsqueeze(0).unsqueeze(-1).expand((1,)+q.shape)).squeeze(0)
            update=outside&derivative_ok&(cost>=1e-8)&better.any(0)
            q=torch.where(update.unsqueeze(-1),selected,q)
        _,valid=self.forward(q)
        return q,valid

    def decode(self,actions):
        actions=actions.to(self.O.dtype)
        # The thirteen powers of two are the existing P4 per-leg feasibility
        # fit, evaluated in parallel. They do not slow target travel.
        fractions=self.foot_fractions
        target=self.origin+actions.reshape(-1,4,3).unsqueeze(1)*self.scale*fractions.reshape(1,13,1,1)
        q,valid=self.inverse(target)
        projected,projected_ok=self.bounded(q)
        in_bounds=((q>=self.low)&(q<=self.high)).all(-1)
        q=torch.where(in_bounds.unsqueeze(-1),q,projected)
        valid=valid&torch.where(in_bounds,True,projected_ok)
        pulse=self.pulse_home+(torch.rad2deg(q)-self.home)*self.pulse_scale
        pulse=torch.floor(pulse+.5)
        valid=valid&((pulse[...,1:]>=500)&(pulse[...,1:]<=2800)).all(-1)
        valid=valid&((pulse>=1)&(pulse<=65535)).all(-1)
        index=valid.to(torch.int64).argmax(1)
        selected=torch.gather(q,1,index[:,None,:,None].expand(-1,1,4,3)).squeeze(1)
        return torch.where(valid.any(1).unsqueeze(-1),selected,self.q0).reshape(-1,12)

    def pwm(self,q):
        q=q.reshape(-1,4,3)
        pulse=torch.floor(self.pulse_home+(torch.rad2deg(q)-self.home)*self.pulse_scale+.5)
        logical=torch.deg2rad(self.home+(pulse-self.pulse_home)/self.pulse_scale)
        width=torch.floor(pulse/self.tick_us+.5)*self.tick_us
        physical=torch.deg2rad(self.home+(width-self.pulse_home)/self.pulse_scale)
        return logical.reshape(-1,12),physical.reshape(-1,12)

    def coordinates(self,q):
        theta=self.t0+q[...,2];a=self.a0+q[...,1]
        x=self.C[0]-self.O[0]+self.r*torch.cos(theta)
        z=self.C[1]-self.O[1]+self.r*torch.sin(theta)
        d=torch.sqrt(x*x+z*z);phi=torch.atan2(z,x)
        offset=wrap(a-phi);c=torch.cos(offset)
        limit=self.cosine_limit(d,c>=0)
        return theta,phi,(c/limit.clamp_min(1e-12)).clamp(-1,1),torch.where(offset<0,-1.,1.),limit>0

    def cosine_limit(self,d,positive):
        reach=torch.where(positive,abs(self.L-self.b),self.L+self.b)
        c=(self.A*self.A+d*d-reach*reach)/(2*self.A*d)
        return torch.minimum(torch.ones_like(c),torch.where(positive,c,-c))

    def transition(self,previous,goal,u):
        theta,phi,n,side,valid=self.coordinates(previous)
        _,phi1,n1,side1,valid1=self.coordinates(goal)
        delta=goal[...,2]-previous[...,2]
        turn=self.a0+previous[...,1]-phi-wrap(self.a0+previous[...,1]-phi)
        phi_end=phi+delta+wrap(phi1-phi-delta)
        expected=phi_end+side*torch.acos(torch.cos(self.a0+goal[...,1]-phi1))+turn
        valid=valid&valid1&(side==side1)&((expected-self.a0-goal[...,1]).abs()<1e-5)
        u=u.unsqueeze(-1)
        x=self.C[0]-self.O[0]+self.r*torch.cos(theta+u*delta)
        z=self.C[1]-self.O[1]+self.r*torch.sin(theta+u*delta)
        d=torch.sqrt(x*x+z*z);p=torch.atan2(z,x)
        p=phi+u*delta+wrap(p-phi-u*delta)
        nu=n+u*(n1-n)
        carrier=p+side*torch.acos((nu*self.cosine_limit(d,nu>=0)).clamp(-1,1))+turn-self.a0
        result=previous+u.unsqueeze(-1)*(goal-previous)
        result=result.clone();result[...,1]=carrier
        result=torch.where((u==0).unsqueeze(-1),previous,result)
        result=torch.where((u==1).unsqueeze(-1),goal,result)
        _,closed=self.forward(result)
        return result,(valid|((u==0)|(u==1)))&closed

    def command(self,actions,previous):
        goal=self.decode(actions).reshape(-1,4,3)
        previous=previous.to(self.O.dtype).reshape(-1,4,3)
        remaining=(goal-previous).abs().flatten(1).amax(-1)
        u=(self.max_travel/remaining.clamp_min(1e-12)).clamp(max=1.)
        candidate,valid=self.transition(previous,goal,u)
        partial=(u>0)&(u<1)
        low=torch.zeros_like(u);high=torch.ones_like(u);result=previous.clone()
        active=partial.clone()
        for _ in range(32):
            distance=(candidate-previous).abs().flatten(1).amax(-1)
            feasible=distance<=self.max_travel
            low=torch.where(active&feasible,u,low);high=torch.where(active&~feasible,u,high)
            result=torch.where((active&feasible)[:,None,None],candidate,result)
            next_u=(low+high)*.5
            active=active&(distance!=self.max_travel)&(next_u!=u)
            u=torch.where(active,next_u,u)
            candidate,next_valid=self.transition(previous,goal,u)
            valid=valid&torch.where(active[:,None],next_valid,True)
        result=torch.where(partial[:,None,None],result,goal)
        result,closed=self.bounded(result)
        good=valid.all(-1)&closed.all(-1)
        result=torch.where(good[:,None,None],result,previous)
        return self.pwm(result)
