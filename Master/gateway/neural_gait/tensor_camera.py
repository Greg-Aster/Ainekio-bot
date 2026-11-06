"""GPU optical sampling and asynchronous delivery of the existing depth layout."""
from dataclasses import dataclass
import torch


@dataclass
class OpticalPattern:
    profile: dict

    def generate_rays(self,mj_model,device):
        width,height=self.profile['imageSize'];k=self.profile['cameraMatrix']
        u=(torch.arange(8,device=device)+.5)*width/8
        v=(torch.arange(8,device=device)+.5)*height/8
        yy,xx=torch.meshgrid(v,u,indexing='ij')
        direction=torch.stack(((xx.flatten()-k[0][2])/k[0][0],
                               (yy.flatten()-k[1][2])/k[1][1],torch.ones(64,device=device)),-1)
        return torch.zeros_like(direction),torch.nn.functional.normalize(direction,dim=-1)


class TensorCamera:
    def __init__(self,profile,count,device):
        self.profile=profile;self.device=device
        self.cached=torch.zeros((count,147),device=device)
        self.pending=self.cached.clone();self.waiting=self.cached.clone()
        self.busy=torch.zeros(count,dtype=torch.bool,device=device)
        self.has_waiting=self.busy.clone();self.first=torch.ones_like(self.busy)
        self.due=torch.zeros(count,device=device);self.stamp=self.due.clone()
        self.pending_stamp=self.due.clone();self.waiting_stamp=self.due.clone()
        self.next_capture=0.
        _,rays=OpticalPattern(profile).generate_rays(None,device)
        self.z_component=rays[:,2]
        width,height=profile['imageSize'];k=profile['cameraMatrix']
        self.intrinsics=torch.tensor([k[0][0]/width,k[1][1]/height,k[0][2]/width,k[1][2]/height],device=device)
        transform=profile.get('cameraToBody') if profile.get('publish_camera_to_body',True) else None
        self.transform=torch.tensor([v for row in transform[:3] for v in row]
                                    if transform is not None else [0.]*12,device=device)
        self.flags=torch.tensor([1.,float(transform is not None),0.],device=device)

    def reset(self,ids):
        for tensor in (self.cached,self.pending,self.waiting):tensor[ids]=0
        self.busy[ids]=False;self.has_waiting[ids]=False;self.first[ids]=True
        self.stamp[ids]=-float('inf')

    def observe(self,sensor,now):
        delivered=self.busy&(self.due<=now)
        self.cached=torch.where(delivered[:,None],self.pending,self.cached)
        self.stamp=torch.where(delivered,self.pending_stamp,self.stamp)
        self.busy&=~delivered
        take=delivered&self.has_waiting
        self.pending=torch.where(take[:,None],self.waiting,self.pending)
        self.pending_stamp=torch.where(take,self.waiting_stamp,self.pending_stamp)
        self.due=torch.where(take,now+self.profile['latency_s'],self.due)
        self.busy|=take;self.has_waiting&=~take
        if now+1e-10>=self.next_capture:
            distance=sensor.data.distances
            valid=(distance>0)&(torch.rand_like(distance)>=self.profile['dropout_probability'])
            depth=distance*self.z_component+torch.randn_like(distance)*self.profile['noise_std_m']
            valid&=depth>0;depth=torch.where(valid,depth,0.)
            count=len(distance)
            capture=torch.cat((depth,valid.float(),self.intrinsics.expand(count,-1),
                               self.transform.expand(count,-1),self.flags.expand(count,-1)),-1)
            capture=torch.where(valid.any(-1,keepdim=True),capture,0.)
            idle=~self.busy
            self.pending=torch.where(idle[:,None],capture,self.pending)
            self.pending_stamp=torch.where(idle,now,self.pending_stamp)
            self.waiting=torch.where(self.busy[:,None],capture,self.waiting)
            self.waiting_stamp=torch.where(self.busy,now,self.waiting_stamp)
            self.has_waiting|=self.busy
            startup=self.profile.get('startup_latency_s',0.)
            bounds=startup if isinstance(startup,(list,tuple)) else (startup,startup)
            first_delay=torch.rand_like(self.due)*(bounds[1]-bounds[0])+bounds[0]
            delay=torch.where(self.first,first_delay,self.profile['latency_s'])
            self.due=torch.where(idle,now+delay,self.due)
            self.first&=~idle;self.busy|=idle
            self.next_capture=now+1/self.profile['capture_hz']
        max_age=self.profile.get('max_frame_age_s')
        if max_age is None:return self.cached
        return torch.where((now-self.stamp<=max_age)[:,None],self.cached,0.)
