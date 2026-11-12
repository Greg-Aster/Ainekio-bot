"""Device-resident ADC/One-Euro feedback and six-axis IMU sensor state.

Feedback math follows servo_feedback_model.c; inclination fusion follows the
installed imu.c / FusionAhrs.c NWU algorithm and its existing default settings.
No root position, root velocity, contacts or true orientation enters features.
"""
import math
import torch
import torch.nn.functional as F


def gravity(q):
    w,x,y,z=q.unbind(-1)
    return torch.stack((2*(x*z-w*y),2*(y*z+w*x),2*(w*w+z*z)-1),-1)


class TensorSensors:
    def __init__(self,config,count,device):
        self.config=config;self.count=count;self.device=device
        def tensor(v):return torch.as_tensor(v,dtype=torch.float32,device=device)
        mapping=sorted(config.robot['calibration'],key=lambda j:j['id'])
        feedback=sorted(config.robot['feedback']['joints'],key=lambda j:j['id'])
        self.home=tensor([m['home_cd']/100 for m in mapping])
        self.pulse_home=tensor([m['home_us'] for m in mapping])
        self.scale=tensor([(-1 if m['invert'] else 1)*m['us_per_degree'] for m in mapping])
        points=[sorted(f['points'],key=lambda p:p['pulse_us']) for f in feedback]
        self.curve_raw=tensor([[p['raw'] for p in row] for row in points])
        self.curve_pulse=tensor([[p['pulse_us'] for p in row] for row in points])
        raw_order=[sorted(f['points'],key=lambda p:p['raw']) for f in feedback]
        self.inverse_raw=tensor([[p['raw'] for p in row] for row in raw_order])
        self.inverse_pulse=tensor([[p['pulse_us'] for p in row] for row in raw_order])
        ages=config.robot['feedback']['sample_age_from_last_channel_us']
        self.lag=torch.tensor([round(a*config.physics_hz/1e6) for a in ages],device=device)
        self.trace=torch.zeros((max(round(a*config.physics_hz/1e6) for a in ages)+2,count,12),device=device)
        self.channels=torch.arange(12,device=device)
        self.feedback_time=torch.zeros(count,device=device)
        self.imu_time=torch.zeros(count,device=device)
        self.raw=torch.zeros((count,12),device=device)
        self.raw_scale=torch.ones((count,1),device=device);self.raw_offset=torch.zeros((count,12),device=device)
        self.filtered=self.raw.clone();self.derivative=self.raw.clone();self.velocity=self.raw.clone()
        self.joint=self.raw.clone();self.joint_velocity=self.raw.clone()
        self.quaternion=torch.zeros((count,4),device=device);self.quaternion[:,0]=1
        self.gyro=torch.zeros((count,3),device=device);self.accel=self.gyro.clone()
        self.initialized=torch.zeros(count,dtype=torch.bool,device=device)
        self.feedback_initialized=self.initialized.clone()
        self.startup_gain=torch.full((count,),max(.5,10-9.5*config.imu_prehistory_s/3),device=device)
        self.recovery=torch.zeros(count,device=device);self.recovery_threshold=torch.full((count,),1040.,device=device)
        self.clock=0.;self.next_imu=1/208;self.next_feedback=.02

    def reset(self,ids,q0):
        self.trace[:,ids]=q0
        self.raw[ids]=0;self.filtered[ids]=0;self.derivative[ids]=0;self.velocity[ids]=0
        self.joint[ids]=0;self.joint_velocity[ids]=0
        self.quaternion[ids]=0;self.quaternion[ids,0]=1
        self.gyro[ids]=0;self.accel[ids]=0;self.initialized[ids]=False
        self.feedback_initialized[ids]=False
        # Reset is a stationary acquired scan, passed through ADC calibration
        # and the production filter, rather than an invented zero observation.
        positions=self.trace[0,ids]
        self.feedback(positions,.02,ids=ids)
        self.feedback_time[ids]=self.clock;self.imu_time[ids]=self.clock
        self.startup_gain[ids]=max(.5,10-9.5*self.config.imu_prehistory_s/3)
        self.recovery[ids]=0;self.recovery_threshold[ids]=1040.

    @staticmethod
    def interpolate(value,x,y):
        first=value<=x[:,1]
        low=torch.where(first,x[:,0],x[:,1]);high=torch.where(first,x[:,1],x[:,2])
        a=torch.where(first,y[:,0],y[:,1]);b=torch.where(first,y[:,1],y[:,2])
        return a+(value-low)*(b-a)/(high-low)

    def feedback(self,positions,dt,ids=None):
        ids=slice(None) if ids is None else ids
        interval=torch.as_tensor(dt,device=self.device)
        active=interval>0
        dt=interval.clamp_min(1e-9)
        positions=torch.nan_to_num(positions,nan=0.,posinf=0.,neginf=0.)
        pulse=self.pulse_home+(torch.rad2deg(positions)-self.home)*self.scale
        raw=self.interpolate(pulse,self.curve_pulse,self.curve_raw)*self.raw_scale[ids]+self.raw_offset[ids]
        raw=torch.round(raw+torch.randn_like(raw)*self.config.feedback_noise_raw_std).clamp(0,4095)
        alpha=1/(1+1/(2*math.pi*5*dt))
        derivative=self.derivative[ids]+alpha*((raw-self.raw[ids])/dt-self.derivative[ids])
        cutoff=1.5+.002*derivative.abs()
        gain=1/(1+1/(2*math.pi*cutoff*dt))
        filtered=self.filtered[ids]+gain*(raw-self.filtered[ids])
        velocity=self.velocity[ids]+alpha*((filtered-self.filtered[ids])/dt-self.velocity[ids])
        init=self.feedback_initialized[ids,None]
        self.filtered[ids]=torch.where(active,torch.where(init,filtered,raw),self.filtered[ids])
        self.derivative[ids]=torch.where(active,torch.where(init,derivative,0.),self.derivative[ids])
        self.velocity[ids]=torch.where(active,torch.where(init,velocity,0.),self.velocity[ids])
        self.raw[ids]=torch.where(active,raw,self.raw[ids]);self.feedback_initialized[ids]=True
        pulse=self.interpolate(self.filtered[ids],self.inverse_raw,self.inverse_pulse)
        self.joint[ids]=torch.deg2rad(self.home+(pulse-self.pulse_home)/self.scale)
        segment=torch.where(self.filtered[ids]<=self.inverse_raw[:,1],0,1)
        raw_span=torch.diff(self.inverse_raw,dim=-1).expand(len(positions),-1,-1)
        pulse_span=torch.diff(self.inverse_pulse,dim=-1).expand(len(positions),-1,-1)
        slope=(pulse_span/raw_span).gather(-1,segment.unsqueeze(-1)).squeeze(-1)
        self.joint_velocity[ids]=torch.deg2rad(slope*self.velocity[ids]/self.scale)

    def imu(self,accel,gyro,dt,ids=None):
        ids=slice(None) if ids is None else ids
        accel=torch.nan_to_num(accel,nan=0.,posinf=0.,neginf=0.)
        gyro=torch.nan_to_num(gyro,nan=0.,posinf=0.,neginf=0.)
        accel=accel+torch.randn_like(accel)*self.config.imu_accel_noise_std
        gyro=gyro+torch.randn_like(gyro)*self.config.imu_gyro_noise_std
        accel=torch.round(accel/(.000488*9.80665)).clamp(-32768,32767)*(.000488*9.80665)
        gyro=torch.round(gyro/(.07*math.pi/180)).clamp(-32768,32767)*(.07*math.pi/180)
        valid=(accel.abs()<=16*9.80665).all(-1)&(gyro.abs()<=2000*math.pi/180).all(-1)
        roll=torch.atan2(accel[:,1],accel[:,2])*.5
        pitch=torch.atan2(-accel[:,0],torch.hypot(accel[:,1],accel[:,2]))*.5
        inclination=torch.stack((torch.cos(roll)*torch.cos(pitch),torch.sin(roll)*torch.cos(pitch),
                                 torch.cos(roll)*torch.sin(pitch),-torch.sin(roll)*torch.sin(pitch)),-1)
        q=torch.where(self.initialized[ids,None],self.quaternion[ids],inclination)
        half=gravity(q)*.5
        normal=F.normalize(accel,dim=-1)
        residual=torch.linalg.cross(normal,half)
        residual=torch.where(((normal*half).sum(-1)>0)[:,None],residual,F.normalize(residual,dim=-1))
        # Fusion stores startupGainRate at its configured 208 Hz even when
        # SetSamplePeriod changes the integration interval for a given sample.
        self.startup_gain[ids]=(self.startup_gain[ids]-torch.where(self.initialized[ids]&valid&(torch.as_tensor(dt,device=self.device).reshape(-1)>0),9.5/(3*208),0.)).clamp_min(.5)
        startup=self.startup_gain[ids]>.5
        accepted=startup|(residual.square().sum(-1)<=(.5*math.sin(math.radians(10)))**2)
        trigger=self.recovery[ids]+torch.where(accepted,-9.,1.)
        recovery=trigger>self.recovery_threshold[ids]
        self.recovery_threshold[ids]=torch.where(recovery,0.,1040.)
        self.recovery[ids]=trigger.clamp(0,1040.)
        accepted=accepted|recovery
        rate=gyro*.5+torch.where(accepted[:,None],residual,0.)*self.startup_gain[ids,None]
        w=q[:,:1];xyz=q[:,1:]
        product=torch.cat((-(xyz*rate).sum(-1,keepdim=True),
                           w*rate+torch.linalg.cross(xyz,rate)),-1)
        updated=F.normalize(q+product*dt,dim=-1)
        updated=torch.where(self.initialized[ids,None],updated,inclination)
        # FusionAhrsUpdateNoMagnetometer zeros heading during startup.
        qw,qx,qy,qz=updated.unbind(-1)
        yaw=torch.atan2(2*(qw*qz+qx*qy),1-2*(qy*qy+qz*qz))*.5
        c=torch.cos(yaw);s=torch.sin(yaw)
        heading_zero=torch.stack((c*qw+s*qz,c*qx+s*qy,c*qy-s*qx,c*qz-s*qw),-1)
        updated=torch.where(startup[:,None],heading_zero,updated)
        self.quaternion[ids]=torch.where(valid[:,None],updated,self.quaternion[ids])
        self.gyro[ids]=torch.where(valid[:,None],gyro,self.gyro[ids])
        self.accel[ids]=torch.where(valid[:,None],accel,self.accel[ids])
        self.initialized[ids]|=valid

    def sample(self,positions,accel,gyro):
        self.trace=torch.roll(self.trace,1,0);self.trace[0]=positions
        if self.clock+1e-10>=self.next_feedback:
            sample=self.trace[self.lag, :, self.channels].transpose(0,1)
            self.feedback(sample,(self.clock-self.feedback_time)[:,None])
            self.feedback_time[:]=self.clock
            self.next_feedback+=.02
        if self.clock+1e-10>=self.next_imu:
            self.imu(accel,gyro,(self.clock-self.imu_time)[:,None])
            self.imu_time[:]=self.clock
            self.next_imu+=1/208
        self.clock+=1/self.config.physics_hz

    def features(self,command,previous_action):
        return torch.cat((self.joint,self.joint_velocity,self.gyro,self.accel/9.81,
                          -gravity(self.quaternion),command,previous_action),-1)
