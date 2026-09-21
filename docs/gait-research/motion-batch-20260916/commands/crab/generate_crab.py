"""V1 Crab: five alternating left/right side strokes in a wide posture."""
import copy,json,math
import numpy as np
from motion_common import Motion,P,k

def generate(settings=None):
 m=Motion('crab','V1 rotates the upper joints to 90 degrees and alternates left/right lower pairs for five cycles. V2 widens a lowered stance, then alternates left and right side shuffles for five cycles. Each side pair is staggered into individual steps so three soles remain supporting; the body sways laterally with the steps.',settings)
 m.cfg.update(minimum_support_margin_requested_mm=5.,stance_widen_mm=10.,side_stroke_mm=7.,swing_clearance_mm=5.,cycles=5,step_seconds=.6,shift_seconds=.375)
 original=copy.deepcopy(m.rows[0]);lower=m.pose([0,0,65],[0,0,0],1.,'lower_for_crab');original_targets={l:np.array(m.foot(i)[0][:2]) for i,l in enumerate(k.LEGS)}
 def step_leg(i,target,name):
  l=k.LEGS[i];support=[m.state[k.LEGS[j]]['anchor'][:2] for j in range(4) if j!=i];goal=k.inside(support,(m.body+m.com)[:2],m.cfg['minimum_support_margin_requested_mm'])-m.com[:2]
  m.pose([*goal,m.body[2]],[0,0,0],m.cfg['shift_seconds'],'shift_support_'+name)
  start=m.foot(i)[0][:2].copy();m.contacts[i]=False
  def step(u):
   s=k.smooth(u);xy=start+(np.array(target)-start)*s;clear=m.cfg['swing_clearance_mm']*64*u**3*(1-u)**3
   m.q[i],_=k.sole_target(l,xy,clear,m.body,m.q[i])
  m.segment(m.cfg['step_seconds'],name,step);m.contacts[i]=True;m.state[l]=k.contact_state(l,m.q[i],m.body)
  m.rows[-1].update(contact_active=[True]*4,swing_leg=None)
  m.rows[-1]['contact_world_mm'][i]=m.state[l]['anchor'].tolist();m.rows[-1]['contact_vertex_index'][i]=m.state[l]['index'];m.rows[-1]['stance_constraint_error_mm'][i]=0.
 # Side pairs are left FL/RL and right FR/RR; spread with airborne feet, never a planted slide.
 for i in [0,2,1,3]:
  sign=1 if i in [0,2] else -1;target=original_targets[k.LEGS[i]]+np.array([0,sign*m.cfg['stance_widen_mm']]);step_leg(i,target,'widen_'+k.LEGS[i])
 wide={l:np.array(m.foot(i)[0][:2]) for i,l in enumerate(k.LEGS)}
 for cycle in range(m.cfg['cycles']):
  offset=m.cfg['side_stroke_mm'] if cycle%2==0 else 0.
  for i in [0,2,1,3]:
   sign=1 if i in [0,2] else -1;target=wide[k.LEGS[i]]+np.array([0,sign*offset]);step_leg(i,target,'side_stroke_'+str(cycle+1)+'_'+k.LEGS[i])
 for i in [0,2,1,3]:step_leg(i,original_targets[k.LEGS[i]],'close_stance_'+k.LEGS[i])
 # A short explicitly sliding settle restores exact neutral geometry for the next command.
 start_body=m.body.copy();target_body=np.array(lower[-1]['body_position_world_mm']);start_xy=[m.foot(i)[0][:2].copy() for i in range(4)]
 def settle(u):
  s=k.smooth(u);m.body=start_body+(target_body-start_body)*s
  for i,l in enumerate(k.LEGS):
   xy=start_xy[i]+(original_targets[l]-start_xy[i])*s;m.q[i],_=k.sole_target(l,xy,0,m.body,m.q[i]);m.state[l]=k.contact_state(l,m.q[i],m.body)
 m.segment(.8,'intentional_contact_settle',settle)
 for r in m.rows:
  r['contact_motion_model']=['intentional_slide' if r['phase']=='intentional_contact_settle' else 'rolling' if c else 'airborne' for c in r['contact_active']]
 m.cfg['contact_model']='Measured rolling stance soles and 5 mm airborne shuffles. Final 0.8 second settle intentionally slides four grounded contacts to restore exact standing; sliding friction unverified.'
 m.recorded(list(reversed(lower)),'return_to_standing');end=m.now;m.hold(.5,'hold_standing');m.cfg.update(intentional_final_contact_settle=True,maximum_final_bolt_xy_settle_mm=max(float(np.linalg.norm(original_targets[l]-start_xy[i])) for i,l in enumerate(k.LEGS)),sliding_friction_verified=False,semantic_end_s=end,body_motion='Alternating lateral weight transfers with contact-constrained stance; five alternating side-pair strokes return to the original body position.',completion='Five alternating side-pair cycles, narrow the stance, and return to standing. Not a calibrated translational crab-walk command.')
 return m.finalize(end)
if __name__=='__main__':generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None)
