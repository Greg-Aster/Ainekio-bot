"""V1 Freaky: asymmetrical right-side posture and three right-front flicks."""
import json
import numpy as np
from motion_common import Motion,P

def generate(settings=None):
 m=Motion('freaky','V1 spreads its upper joints, partly folds right rear R4, and repeats three short right-front R3 flicks. V2 lowers into a three-foot braced posture, raises the right-front shoulder, and flicks right-front Part005 with coupled Part006. Three supporting soles are retained; no invented belly contact.',settings)
 lower=m.pose([-8,6,55],[0,0,0],1.5,'lower_into_asymmetric_ground_pose');folded=m.q.copy();m.contacts=[True,True,True,False];m.cfg['geometric_research_angle_bounds_degrees']['h']=[-95,95]
 raised=folded.copy();raised[3,0]=np.radians(-75);m.joints(raised,.8,'raise_right_front_shoulder');target=raised.copy();target[3,1:]=np.radians([15,10]);m.joints(target,.8,'set_right_front_freaky_pose')
 for j in range(3):
  flick=target.copy();flick[3,1:]=np.radians([22,35]);m.joints(flick,.5,'right_front_flick_'+str(j+1));m.joints(target,.5,'right_front_retract_'+str(j+1))
 m.joints(raised,.8,'fold_right_front_linkage');m.joints(folded,.8,'replace_right_front_sole');m.contacts=[True]*4;m.recorded(list(reversed(lower)),'return_to_standing');end=m.now;m.hold(.5,'hold_standing')
 m.cfg.update(cycles=3,right_front_CAD_leg='RR',right_rear_CAD_leg='FR',semantic_end_s=end,shoulder_bounds_basis='90 degree Swim research envelope; geometric only, uncalibrated electrical travel.')
 return m.finalize(end)
if __name__=='__main__':generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None)
