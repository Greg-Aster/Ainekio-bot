"""V1 Worm: five whole-body front/rear undulations in a low posture."""
import json,math
import numpy as np
from motion_common import Motion,P,k

def generate(settings=None):
 m=Motion('worm','V1 lowers into a flat posture, then alternates mirrored front/rear lower-joint targets for five cycles. V2 performs five continuous low-body undulations: front dips as rear rises, then rear dips as front rises, with four grounded measured soles.',settings)
 height=m.cfg.get('worm_body_height_mm',58.);amplitude=m.cfg.get('worm_pitch_degrees',4.);cycles=m.cfg.get('cycles',5);period=m.cfg.get('cycle_seconds',1.8)
 lower=m.pose([0,0,height],[0,0,0],1.5,'lower_into_worm');base=m.body.copy();duration=cycles*period
 def wave(u):
  # One-cycle quintic amplitude ramp at each end gives zero velocity/acceleration.
  t=u*duration;env=k.smooth(min(1,t/period))*k.smooth(min(1,(duration-t)/period));phase=2*math.pi*t/period
  m.body=base+np.array([2.5*env*math.sin(phase),0,1.5*env*(1-math.cos(phase))]);m.euler=np.array([0,math.radians(amplitude)*env*math.sin(phase),0]);m.R=__import__('motion_common').rotation(m.euler)
  for i in range(4):m.roll(i)
 m.segment(duration,'five_front_rear_undulations',wave)
 # Reverse the actual final lowering stance so recorded sole rolling does not snap.
 m.pose(m.rows[0]['body_position_world_mm'],[0,0,0],1.5,'return_to_standing');end=m.now;m.hold(.5,'hold_standing')
 m.cfg.update(worm_body_height_mm=height,worm_pitch_degrees=amplitude,cycles=cycles,cycle_seconds=period,semantic_end_s=end,completion='Five front/rear undulations, then return to standing; rolling may accumulate a small sole contact displacement.')
 return m.finalize(end)
if __name__=='__main__':generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None)
