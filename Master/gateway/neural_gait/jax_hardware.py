"""GPU tensor implementation of the existing Ainekio hardware transforms.

The native C owners remain the numerical reference. This module contains no
gait generator, network, command admission, robot connection or recovery owner.
Geometry and calibration are captured from those owners at preparation time.
"""
import jax
from jax import numpy as jnp


RAD_PER_CD = 0.00017453292519943296


def wrap(angle):
    return angle - 2*jnp.pi*jnp.rint(angle/(2*jnp.pi))


def round_away(value):
    return jnp.sign(value)*jnp.floor(jnp.abs(value)+.5)


def circle(distance2, radius, other):
    valid = ((distance2 > 1e-8) & (distance2 >= (radius-other)**2)
             & (distance2 <= (radius+other)**2))
    denominator = jnp.where(valid, distance2, 1.)
    along = (radius*radius-other*other+distance2)/(2*denominator)
    height = jnp.sqrt(jnp.maximum(0., radius*radius/denominator-along*along))
    return along, height, valid


class Kinematics:
    """Vectorized walk_kinematics.c / learning.c / joint_calibration.c math.

    Internal joint units are the firmware's float centidegrees. Public foot
    offsets are body-frame millimetres in physical RL/RR/FL/FR order.
    """

    def __init__(self, geometry, robot, reference_deg, foot_scale_mm, pwm_tick_us):
        self.p = jnp.asarray(geometry['parameters'], jnp.float32)
        self.legs = jnp.asarray(geometry['legs'], jnp.float32)
        mapping = sorted(robot['calibration'], key=lambda row: row['id'])
        self.home = jnp.array([row['home_cd'] for row in mapping], jnp.float32).reshape(4,3)
        self.pulse_home = jnp.array([row['home_us'] for row in mapping], jnp.float32).reshape(4,3)
        self.pulse_scale = jnp.array([(-1 if row['invert'] else 1)*row['us_per_degree']
                                     for row in mapping], jnp.float32).reshape(4,3)
        endpoints = (jnp.array([500.,2800.])[:,None,None]-self.pulse_home)*100/self.pulse_scale+self.home
        self.low = jnp.min(endpoints, axis=0).at[:,0].set(-jnp.inf)
        self.high = jnp.max(endpoints, axis=0).at[:,0].set(jnp.inf)
        self.reference = jnp.asarray(reference_deg, jnp.float32).reshape(4,3)*100
        self.foot_scale = jnp.asarray(foot_scale_mm, jnp.float32)
        self.tick_us = jnp.float32(pwm_tick_us)

    def seed(self, q):
        ox,oz,cx,cz,a,r,length,b,a0,t0,b0,branch = self.p
        h,alpha,theta = q*RAD_PER_CD
        d = jnp.array([ox+a*jnp.cos(a0+alpha), oz+a*jnp.sin(a0+alpha)])
        pin = jnp.array([cx+r*jnp.cos(t0+theta), cz+r*jnp.sin(t0+theta)])
        vector = pin-d
        along,height,valid = circle(jnp.dot(vector,vector), b, length)
        bc,bs = (along*vector+branch*height*jnp.array([-vector[1],vector[0]]))/b
        lc = bc*jnp.cos(b0)+bs*jnp.sin(b0)
        ls = bs*jnp.cos(b0)-bc*jnp.sin(b0)
        return (jnp.cos(h),jnp.sin(h),d,bc,bs,lc,ls), valid

    def point(self, q, leg):
        (hc,hs,d,bc,bs,lc,ls),valid = self.seed(q)
        sign,translation,mount,ref,mirror = leg[:3],leg[3:6],leg[6:9],leg[9:12],leg[12]
        local = jnp.array([d[0]+lc*ref[0]-ls*ref[2],ref[1],d[1]+ls*ref[0]+lc*ref[2]])
        value = jnp.array([mount[0]+mirror*local[0],
                           hc*(mount[1]+local[1])-hs*(mount[2]+local[2]),
                           hs*(mount[1]+local[1])+hc*(mount[2]+local[2])])
        return translation+sign*value, valid

    def inverse(self, reference, delta, leg):
        ox,oz,cx,cz,a,r,length,b,a0,t0,b0,assembly = self.p
        (old_hc,old_hs,old_d,old_bc,old_bs,old_lc,old_ls),old_valid = self.seed(reference)
        old_point,_ = self.point(reference,leg)
        sign,mount,ref,mirror = leg[:3],leg[6:9],leg[9:12],leg[12]
        v = (old_point+delta-leg[3:6])*sign
        y = mount[1]+ref[1]
        zz = v[1]*v[1]+v[2]*v[2]-y*y
        z = -jnp.sqrt(jnp.maximum(zz,0.))
        norm = v[1]*v[1]+v[2]*v[2]
        hc = (y*v[1]+z*v[2])/jnp.maximum(norm,1e-8)
        hs = (y*v[2]-z*v[1])/jnp.maximum(norm,1e-8)
        vector = jnp.array([(v[0]-mount[0])*mirror-ox,z-mount[2]-oz])
        ref_length2 = ref[0]*ref[0]+ref[2]*ref[2]
        along,height,reachable = circle(jnp.dot(vector,vector),a,jnp.sqrt(ref_length2))
        side = height*jnp.array([-vector[1],vector[0]])
        first = jnp.array([ox,oz])+along*vector+side
        second = jnp.array([ox,oz])+along*vector-side
        d = jnp.where(jnp.sum((first-old_d)**2)<=jnp.sum((second-old_d)**2),first,second)
        lower = vector+jnp.array([ox,oz])-d
        lc = (lower[0]*ref[0]+lower[1]*ref[2])/ref_length2
        ls = (lower[1]*ref[0]-lower[0]*ref[2])/ref_length2
        bc = jnp.cos(b0)*lc-jnp.sin(b0)*ls
        bs = jnp.sin(b0)*lc+jnp.cos(b0)*ls
        end = d+b*jnp.array([bc,bs])
        vector = end-jnp.array([cx,cz])
        along,height,crank_reachable = circle(jnp.dot(vector,vector),r,length)
        old_theta = t0+reference[2]*RAD_PER_CD
        old_end = old_d+b*jnp.array([old_bc,old_bs])-jnp.array([cx,cz])
        old_branch = old_end[0]*jnp.sin(old_theta)-old_end[1]*jnp.cos(old_theta)
        sides = jnp.array([-1.,1.])
        pins = jnp.array([cx,cz])+along*vector+sides[:,None]*height*jnp.array([-vector[1],vector[0]])
        relative = pins-jnp.array([cx,cz])
        on_branch = ((vector[0]*relative[:,1]-vector[1]*relative[:,0])*old_branch>0)
        same_assembly = ((pins[:,0]-d[0])*(end[1]-d[1])-(pins[:,1]-d[1])*(end[0]-d[0]))*assembly>=0
        theta = wrap(jnp.arctan2(relative[:,1],relative[:,0])-t0)
        candidates = on_branch & same_assembly
        index = jnp.argmin(jnp.where(candidates,jnp.abs(wrap(theta-reference[2]*RAD_PER_CD)),jnp.inf))
        q = jnp.array([jnp.arctan2(hs,hc),wrap(jnp.arctan2(d[1]-oz,d[0]-ox)-a0),theta[index]])/RAD_PER_CD
        valid = old_valid & (zz>=0) & (norm>=1e-8) & reachable & crank_reachable & jnp.any(candidates)
        return q, valid & jnp.all(jnp.isfinite(q))

    def pulse(self, q, home, pulse_home, pulse_scale):
        return round_away(pulse_home+(q-home)*pulse_scale/100)

    def valid(self, q, home, pulse_home, pulse_scale):
        pulse = self.pulse(q,home,pulse_home,pulse_scale)
        return jnp.all(jnp.isfinite(q)) & jnp.all((pulse>=1)&(pulse<=65535)) & jnp.all((pulse[1:]>=500)&(pulse[1:]<=2800))

    def bounded(self, q, low, high, leg):
        target, target_valid = self.point(q,leg)
        initial = jnp.clip(q,low,high)
        position, initial_valid = self.point(initial,leg)
        changed = jnp.any(initial!=q)

        def iterate(_, state):
            current,position,active = state
            error = target-position
            cost = jnp.dot(error,error)
            steps = jnp.where(current[1:]+1<=high[1:],1.,-1.)
            probes = jnp.tile(current,(2,1)).at[jnp.arange(2),jnp.arange(1,3)].add(steps)
            values,valid = jax.vmap(self.point,in_axes=(0,None))(probes,leg)
            jac = (values-position)/steps[:,None]
            aa,bb,dd = jnp.dot(jac[0],jac[0]),jnp.dot(jac[0],jac[1]),jnp.dot(jac[1],jac[1])
            ee,ff = jnp.dot(jac[0],error),jnp.dot(jac[1],error)
            det = aa*dd-bb*bb
            movement = jnp.array([jnp.where(aa>1e-12,ee/jnp.maximum(aa,1e-30),0.),jnp.where(dd>1e-12,ff/jnp.maximum(dd,1e-30),0.)])
            movement = jnp.where(det>1e-12,jnp.array([dd*ee-bb*ff,aa*ff-bb*ee])/jnp.maximum(det,1e-30),movement)
            first_bound = ((current[1]<=low[1])&(movement[0]<0))|((current[1]>=high[1])&(movement[0]>0))
            movement = jnp.where(first_bound,jnp.array([0.,jnp.where(dd>1e-12,ff/jnp.maximum(dd,1e-30),0.)]),movement)
            second_bound = ((current[2]<=low[2])&(movement[1]<0))|((current[2]>=high[2])&(movement[1]>0))
            movement = jnp.where(second_bound,jnp.array([jnp.where(aa>1e-12,ee/jnp.maximum(aa,1e-30),0.),0.]),movement)
            fractions = jnp.exp2(-jnp.arange(8,dtype=jnp.float32))
            trials = jnp.tile(current,(8,1)).at[:,1:].add(fractions[:,None]*movement)
            trials = jnp.clip(trials,low,high)
            points,possible = jax.vmap(self.point,in_axes=(0,None))(trials,leg)
            improves = possible & (jnp.sum((target-points)**2,axis=1)<cost)
            index = jnp.argmax(improves)
            accepted = active & (cost>=1e-8) & jnp.all(valid) & jnp.all(current[1:]+steps>=low[1:]) & jnp.any(improves)
            return jnp.where(accepted,trials[index],current),jnp.where(accepted,points[index],position),accepted

        result,_,_ = jax.lax.fori_loop(0,8,iterate,(initial,position,changed & initial_valid & target_valid))
        _,valid = self.seed(result)
        return jnp.where(changed,result,q),valid & target_valid & initial_valid

    def foot_target(self, offsets):
        def leg_target(reference,delta,leg,low,high,home,pulse_home,pulse_scale):
            def attempt(index,state):
                accepted,current,fit = state
                fraction = jnp.exp2(-jnp.asarray(index,jnp.float32))
                candidate,possible = self.inverse(reference,delta*fraction,leg)
                mapped = self.valid(candidate,home,pulse_home,pulse_scale)
                projected,project_valid = self.bounded(candidate,low,high,leg)
                candidate = jnp.where(mapped,candidate,projected)
                good = possible & (mapped|project_valid) & self.valid(candidate,home,pulse_home,pulse_scale)
                use = ~accepted & good
                return accepted|good,jnp.where(use,candidate,current),jnp.where(use,fraction,fit)
            _,q,fit = jax.lax.fori_loop(0,13,attempt,(jnp.array(False),reference,jnp.float32(0.)))
            return jnp.where(jnp.all(delta==0),reference,q),jnp.where(jnp.all(delta==0),1.,fit)
        return jax.vmap(leg_target)(self.reference,jnp.asarray(offsets).reshape(4,3),self.legs,
                                   self.low,self.high,self.home,self.pulse_home,self.pulse_scale)

    def pwm(self, q):
        pulses = self.pulse(q,self.home,self.pulse_home,self.pulse_scale)
        delivered = jnp.floor(pulses/self.tick_us+.5)*self.tick_us
        logical = self.home+100*(pulses-self.pulse_home)/self.pulse_scale
        physical = self.home+100*(delivered-self.pulse_home)/self.pulse_scale
        return physical*RAD_PER_CD,logical*RAD_PER_CD
