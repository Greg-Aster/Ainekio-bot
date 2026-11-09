"""Ainekio locomotion objective and performance-based disturbance curriculum."""
import math
import inspect
from dataclasses import replace

import torch
from mjlab.managers import ManagerTermBase
from mjlab.tasks.velocity import mdp
from mjlab.utils.lab_api.math import quat_from_euler_xyz, quat_mul
from mjlab_microduck.tasks import mdp as upstream_mdp


def invalid_physics(env,**params):
    # Upstream checks derived root velocity, which is one physics substep
    # stale before mjlab's post-reset forward(). Check the authoritative
    # integration state too, including the free joint and warm start.
    bad=upstream_mdp.robot_state_is_nan(env,**params)
    for name in ("qpos","qvel","qacc","qacc_warmstart"):
        bad |= ~torch.isfinite(getattr(env.sim.data,name)).all(-1)
    return bad


def tracking_scores(actual, command, widths):
    """Bounded, dense tracking score and the score earned by standing still."""
    error=((actual-command)/widths).square()
    baseline=(command/widths).square()
    error=torch.stack((error[:,:2].sum(-1),error[:,2]),-1)
    baseline=torch.stack((baseline[:,:2].sum(-1),baseline[:,2]),-1)
    return 1/(1+error), 1/(1+baseline)


def state(env):
    return env.curriculum_manager.get_term_cfg("walking_difficulty").func


def scores(env):
    robot=env.scene["robot"].data
    command=env.command_manager.get_command("twist")
    actual=torch.cat((robot.root_link_lin_vel_b[:,:2],robot.root_link_ang_vel_b[:,2:3]),-1)
    quality,baseline=tracking_scores(actual,command,state(env).widths)
    moving=command.abs().sum(-1)>0
    return quality,baseline,moving


def tracking_twist(env):
    robot=env.scene["robot"].data
    command=env.command_manager.get_command("twist")
    actual=torch.cat((robot.root_link_lin_vel_b[:,:2],robot.root_link_ang_vel_b[:,2:3]),-1)
    quality,baseline,moving=scores(env)
    delta=quality-baseline
    headroom=(1-baseline).clamp_min(1e-6)
    component_moving=baseline<.95
    negative=torch.where(component_moving,delta/(1-baseline).clamp_min(.5),.75*delta)
    lin_cmd_sq=command[:,:2].square().sum(-1).clamp_min(1e-6)
    lin_dot=(actual[:,:2]*command[:,:2]).sum(-1)
    lin_ratio=lin_dot/lin_cmd_sq
    ang_ratio=(actual[:,2]*command[:,2])/command[:,2].square().clamp_min(1e-6)
    lin_prog=lin_ratio.clamp(0.,1.)
    ang_prog=ang_ratio.clamp(0.,1.)
    directed=torch.stack((lin_prog,ang_prog),-1)
    positive=.55*(delta/headroom).clamp_min(0.)+.45*directed
    wrong_way=torch.stack(((lin_ratio<0.)|(lin_ratio>2.),(ang_ratio<0.)|(ang_ratio>2.)),-1)
    comp=torch.where(wrong_way&(delta<0),negative,positive)
    ang_gate=.25+.75*(quality[:,1].clamp(0.,1.).square())
    lin_coupled=torch.where(comp[:,0]>0,comp[:,0]*ang_gate,comp[:,0])
    improvement=lin_coupled+comp[:,1]
    upright=(-robot.projected_gravity_b[:,2]).clamp(0,1)
    # Tilt cannot hide a negative tracking score. At nonzero commands, an
    # upright stationary robot earns zero task reward; better tracking pays.
    result=torch.where(improvement>0,improvement*upright,improvement)
    curriculum=state(env)
    active=baseline<1
    progress=torch.maximum((delta/headroom).clamp(0,1),(1.25*directed).clamp(0,1))
    progress=torch.nan_to_num(progress,nan=0.,posinf=0.,neginf=0.)
    curriculum.score_sum+=(progress*active).sum(-1)/active.sum(-1).clamp_min(1)
    curriculum.elapsed+=1
    curriculum.score_count+=moving
    env.extras["log"]["Tracking/linear_error_m_s"]=torch.norm(robot.root_link_lin_vel_b[:,:2]-command[:,:2],dim=-1).mean()
    env.extras["log"]["Tracking/yaw_error_rad_s"]=(robot.root_link_ang_vel_b[:,2]-command[:,2]).abs().mean()
    return result


def torso_heights(env, target_z=0.0642):
    """Estimate torso center, rear (-93 mm) and front (+80 mm) heights above stance feet."""
    robot=env.scene["robot"].data
    up_b=(-robot.projected_gravity_b).clamp(-1.,1.)
    rear_pitch_dz=-0.093*up_b[:,0]
    front_pitch_dz=0.080*up_b[:,0]
    if hasattr(env,"action_manager"):
        feet=env.action_manager.get_term("feet")
        q=feet.sensors.joint.to(feet.body.O.dtype).reshape(-1,4,3)
        foot_b_m=((feet.body.forward(q)[0]-feet.body.origin)*1e-3).to(up_b.dtype)
        horiz_sq=foot_b_m[...,:2].square().sum(-1)
        stride_arc_dz=0.40*(horiz_sq/target_z).clamp(0.,0.022)
        foot_b_m[...,2]-=target_z
        leg_z=-(foot_b_m*up_b.unsqueeze(1)).sum(-1)+stride_arc_dz
        rear_z=leg_z[:,:2].amax(-1)+0.5*rear_pitch_dz
        front_z=leg_z[:,2:].amax(-1)+0.5*front_pitch_dz
        left_z=leg_z[:,0::2].amax(-1)
        right_z=leg_z[:,1::2].amax(-1)
        torso_z=torch.minimum(0.5*(rear_z+front_z),torch.minimum(left_z,right_z))
    else:
        base_z=target_z*up_b[:,2].clamp_min(0.)
        rear_z=base_z+rear_pitch_dz
        front_z=base_z+front_pitch_dz
        torso_z=base_z
    return torso_z,rear_z,front_z


def body_collapsed(env, minimum_z=0.048):
    """Terminate when the torso center, rear pelvis or front chest collapses below 48 mm."""
    torso_z,rear_z,front_z=torso_heights(env)
    return (torso_z<minimum_z)|(rear_z<minimum_z)|(front_z<minimum_z)


def upright_cost(env):
    _,_,moving=scores(env)
    tilt_cost=1-(-env.scene["robot"].data.projected_gravity_b[:,2]).clamp(-1,1)
    torso_z,rear_z,front_z=torso_heights(env)
    target_z=torch.where(moving,0.060,0.0642)
    height_err=(
        ((torso_z-target_z)/0.015).square()
        +0.75*((rear_z-target_z)/0.015).square()
        +0.75*((front_z-target_z)/0.015).square()
    ).clamp(0.,4.)
    return tilt_cost+0.35*height_err


def alternating_stride(env):
    """Reward diagonal trot stance, penalize same-girdle hops, and reward wide zero-mean AC stride excursion."""
    quality,_,moving=scores(env)
    robot=env.scene["robot"].data
    command=env.command_manager.get_command("twist")
    lin_cmd_sq=command[:,:2].square().sum(-1)
    lin_dot=(robot.root_link_lin_vel_b[:,:2]*command[:,:2]).sum(-1)
    ang_gate=.25+.75*(quality[:,1].clamp(0.,1.).square())
    dir_gate=torch.where((lin_cmd_sq>1e-4)&(lin_dot<-0.01),0.2,1.0)*ang_gate
    upright=(-robot.projected_gravity_b[:,2]).clamp(0,1)
    c=(env.scene["feet_ground_contact"].data.found>0).to(upright.dtype)
    # Leg order: [RL (0), RR (1), FL (2), FR (3)]
    diag_a=c[:,0]*c[:,3]*(1.-c[:,1])*(1.-c[:,2])
    diag_b=c[:,1]*c[:,2]*(1.-c[:,0])*(1.-c[:,3])
    three_foot=torch.where(c.sum(-1)==3.,.35,0.)
    same_girdle_hop=(1.-c[:,0])*(1.-c[:,1])+(1.-c[:,2])*(1.-c[:,3])
    rew=0.14*(diag_a+diag_b+three_foot)*dir_gate-0.14*same_girdle_hop
    if hasattr(env,"action_manager"):
        feet=env.action_manager.get_term("feet")
        q=feet.sensors.joint
        vq=feet.sensors.joint_velocity/8.
        q0=feet.body.q0.reshape(1,12).to(q.dtype)
        dq=q-q0
        feet.mean_dq.lerp_(dq,0.05)
        ac_dq=dq-feet.mean_dq
        leg_q=0.5*(ac_dq[:,1::3]/0.55+ac_dq[:,2::3]/0.65)
        leg_vq=0.5*(vq[:,1::3]+vq[:,2::3])
        rear_anti_q=(-(leg_q[:,0]*leg_q[:,1]+0.35*leg_vq[:,0]*leg_vq[:,1])).clamp(-0.2,1.6)
        front_anti_q=(-(leg_q[:,2]*leg_q[:,3]+0.35*leg_vq[:,2]*leg_vq[:,3])).clamp(-0.2,1.6)
        diag_sync_q=0.5*((leg_q[:,0]*leg_q[:,3]+0.35*leg_vq[:,0]*leg_vq[:,3])
                        +(leg_q[:,1]*leg_q[:,2]+0.35*leg_vq[:,1]*leg_vq[:,2])).clamp(-0.2,1.8)
        rew=rew+0.42*(rear_anti_q+front_anti_q+diag_sync_q)*dir_gate-0.15*feet.mean_dq.square().sum(-1)
        foot_pos_mm,_=feet.body.forward(q.to(feet.body.O.dtype).reshape(-1,4,3))
        foot_pos_m=(foot_pos_mm*1e-3).to(rew.dtype)
        prev_foot_pos_m=getattr(feet,"prev_foot_pos_m",foot_pos_m)
        foot_vel_m_s=(foot_pos_m-prev_foot_pos_m)*50.
        if hasattr(feet,"prev_foot_pos_m"):
            feet.prev_foot_pos_m.copy_(foot_pos_m)
        feet.mean_foot_pos_m.lerp_(foot_pos_m,0.05)
        ac_pos_m=foot_pos_m-feet.mean_foot_pos_m
        s_xy=ac_pos_m[...,:2]/0.038
        rear_foot_anti=(-(s_xy[:,0]*s_xy[:,1]).sum(-1)).clamp(-0.2,1.8)
        front_foot_anti=(-(s_xy[:,2]*s_xy[:,3]).sum(-1)).clamp(-0.2,1.8)
        diag_foot_sync=0.5*((s_xy[:,0]*s_xy[:,3]).sum(-1)+(s_xy[:,1]*s_xy[:,2]).sum(-1)).clamp(-0.2,1.8)
        sz=(ac_pos_m[...,2]/0.018).clamp(-1.6,1.6)
        rear_z_anti=(-(sz[:,0]*sz[:,1])).clamp(-0.2,1.5)
        front_z_anti=(-(sz[:,2]*sz[:,3])).clamp(-0.2,1.5)
        diag_z_sync=0.5*(sz[:,0]*sz[:,3]+sz[:,1]*sz[:,2]).clamp(-0.2,1.5)
        rew=rew+0.40*(rear_foot_anti+front_foot_anti+diag_foot_sync)*dir_gate+0.20*(rear_z_anti+front_z_anti+diag_z_sync)*dir_gate
        lin_active=(lin_cmd_sq>1e-4).to(rew.dtype)
        u_xy=command[:,:2]/lin_cmd_sq.sqrt().clamp_min(1e-4).unsqueeze(-1)
        v_along=((foot_vel_m_s[...,:2]*u_xy.unsqueeze(1)).sum(-1)/0.22).clamp(-1.6,1.6)
        swing_sign=0.5*(1.-2.*c)+0.5*sz
        leg_propel=(swing_sign*v_along).clamp(-0.6,1.5)
        rear_propel=0.5*(leg_propel[:,0]+leg_propel[:,1])
        front_propel=0.5*(leg_propel[:,2]+leg_propel[:,3])
        propel_rew=0.5*(rear_propel+front_propel)+0.5*torch.minimum(rear_propel,front_propel)
        rew=rew+0.50*propel_rew*lin_active*dir_gate
        rew=rew-0.12*((feet.mean_foot_pos_m-feet.foot_home_pos_m)/0.020).square().sum((-1,-2))
        if hasattr(feet,"mean_amp_q") and hasattr(feet,"mean_amp_z_m"):
            raw_leg_q=0.5*(ac_dq[:,1::3].abs()+ac_dq[:,2::3].abs())
            feet.mean_amp_q.lerp_(raw_leg_q,0.05)
            feet.mean_amp_z_m.lerp_(ac_pos_m[...,2].abs(),0.05)
            difficulty=getattr(state(env),"difficulty",torch.zeros_like(upright))
            flat_level=(difficulty==0).to(rew.dtype)*(upright>0.980).to(rew.dtype)
            straight_cmd=(command[:,2].abs()<0.15).to(rew.dtype)*(command[:,1].abs()<0.02).to(rew.dtype)
            sym_gate=flat_level*straight_cmd*dir_gate
            q_scale_r=0.5*(feet.mean_amp_q[:,0]+feet.mean_amp_q[:,1]).clamp_min(0.28)
            q_scale_f=0.5*(feet.mean_amp_q[:,2]+feet.mean_amp_q[:,3]).clamp_min(0.28)
            q_sym_err=((feet.mean_amp_q[:,0]-feet.mean_amp_q[:,1])/q_scale_r).square()+((feet.mean_amp_q[:,2]-feet.mean_amp_q[:,3])/q_scale_f).square()
            z_scale_r=0.5*(feet.mean_amp_z_m[:,0]+feet.mean_amp_z_m[:,1]).clamp_min(0.014)
            z_scale_f=0.5*(feet.mean_amp_z_m[:,2]+feet.mean_amp_z_m[:,3]).clamp_min(0.014)
            z_sym_err=((feet.mean_amp_z_m[:,0]-feet.mean_amp_z_m[:,1])/z_scale_r).square()+((feet.mean_amp_z_m[:,2]-feet.mean_amp_z_m[:,3])/z_scale_f).square()
            mean_dz=feet.mean_foot_pos_m[...,2]-feet.foot_home_pos_m[:,2]
            stance_sym_err=((mean_dz[:,0]-mean_dz[:,1])/0.008).square()+((mean_dz[:,2]-mean_dz[:,3])/0.008).square()
            roll_lean=(robot.projected_gravity_b[:,1]/0.08).square().clamp(0.,1.5)
            sym_lift=0.35*(torch.minimum(feet.mean_amp_z_m[:,0],feet.mean_amp_z_m[:,1])+torch.minimum(feet.mean_amp_z_m[:,2],feet.mean_amp_z_m[:,3]))/0.018
            sym_stride_q=0.45*(torch.minimum(feet.mean_amp_q[:,0],feet.mean_amp_q[:,1])+torch.minimum(feet.mean_amp_q[:,2],feet.mean_amp_q[:,3]))/0.65
            rew=rew+sym_gate*(sym_lift.clamp(0.,0.65)+sym_stride_q.clamp(0.,0.65)-0.15*q_sym_err.clamp(0.,3.0)-0.20*z_sym_err.clamp(0.,3.0)-0.25*stance_sym_err.clamp(0.,2.0)-0.15*roll_lean)
    return rew*moving*upright


def action_change(env):
    return (env.action_manager.action-env.action_manager.prev_action).square().mean(-1)


def action_size(env):
    _,_,moving=scores(env)
    return env.action_manager.action.square().mean(-1)*(~moving)


def standing_pose(env):
    _,_,moving=scores(env)
    feet=env.action_manager.get_term("feet")
    measured=feet.sensors.joint
    pose_error=(measured-feet.body.q0.reshape(1,12).to(measured.dtype)).square().mean(-1)
    contact=env.scene["feet_ground_contact"].data
    air_hang=(contact.current_air_time-.25).clamp(0,1).mean(-1)
    stance_stall=(contact.current_contact_time-.32).clamp(0,1).mean(-1)
    return pose_error*(~moving)+(air_hang+.5*stance_stall)*moving


def tracked_air_time(env):
    quality,baseline,moving=scores(env)
    progress=((quality-baseline)/(1-baseline).clamp_min(1e-6)).clamp(0,1)
    progress=torch.nan_to_num(progress,nan=0.,posinf=0.,neginf=0.)
    airtime=mdp.feet_air_time(env,sensor_name="feet_ground_contact",threshold_min=.04,
                            threshold_max=.24,command_name="twist",command_threshold=0.)
    upright=(-env.scene["robot"].data.projected_gravity_b[:,2]).clamp(0,1)
    return airtime/4*(.3+.7*progress.mean(-1))*moving*upright


class WalkingDifficulty(ManagerTermBase):
    """Terrain/tilt/push severity follows completed-episode tracking skill.

    All rows start flat with zero tilt/push. A full episode with 80% of the
    available improvement over standing reaches the hardest of five levels.
    Standing commands cannot advance the curriculum. Command ranges, motor
    capability and foot workspace are never scaled by difficulty.
    """
    def __init__(self,cfg,env):
        super().__init__(env)
        self.difficulty=torch.zeros(env.num_envs,device=env.device)
        self.score_sum=torch.zeros_like(self.difficulty)
        self.score_count=torch.zeros_like(self.difficulty)
        self.elapsed=torch.zeros_like(self.difficulty)
        self.widths=torch.tensor(cfg.params["widths"],device=env.device)
        self.push_limits=torch.tensor([.2,.15,0.,.5,.5,0.],device=env.device)

    def __call__(self,env,env_ids,**kwargs):
        ids=slice(None) if env_ids is None else env_ids
        quality=self.score_sum[ids]/self.score_count[ids].clamp_min(1)
        survival=self.elapsed[ids]/env.max_episode_length
        terrain=env.scene.terrain
        rows=terrain.terrain_origins.shape[0]
        level=(quality*survival*rows).long().clamp(0,rows-1)
        self.difficulty[ids]=level/(rows-1)
        terrain.terrain_levels[ids]=level
        # Use the existing terrain owner to update the selected patch origin.
        zero=torch.zeros_like(level,dtype=torch.bool)
        terrain.update_env_origins(env_ids,zero,zero)
        self.score_sum[ids]=0;self.score_count[ids]=0;self.elapsed[ids]=0
        return {"mean":self.difficulty.mean(),"terrain_level":terrain.terrain_levels.float().mean()}


def reset_base(env,env_ids):
    asset=env.scene["robot"]
    root=asset.data.default_root_state[env_ids].clone()
    root[:,:3]+=env.scene.env_origins[env_ids]
    angles=torch.rand((len(env_ids),3),device=env.device)*2-1
    angles[:,:2]*=math.radians(10)*state(env).difficulty[env_ids,None]
    angles[:,2]*=math.pi
    root[:,3:7]=quat_mul(root[:,3:7],quat_from_euler_xyz(*angles.unbind(-1)))
    asset.write_root_state_to_sim(root,env_ids=env_ids)


def push_robot(env,env_ids):
    asset=env.scene["robot"]
    delta=(torch.rand((len(env_ids),6),device=env.device)*2-1)*state(env).push_limits
    delta*=state(env).difficulty[env_ids,None]
    asset.write_root_link_velocity_to_sim(asset.data.root_link_vel_w[env_ids]+delta,env_ids=env_ids)


class BoundedCost(ManagerTermBase):
    """Bound an existing cost before its weight and episode accumulation.

    The limit is a reward budget, not a motor/body velocity restriction.
    Nonfinite terminal-world costs stay within budget; nan_state owns reset.
    """
    def __init__(self,cfg,env):
        super().__init__(env)
        self.function=cfg.params["function"]
        self.limit=cfg.params["limit"]
        self.parameters=cfg.params["parameters"]
        for value in self.parameters.values():
            if hasattr(value,"resolve"):
                value.resolve(env.scene)
        if inspect.isclass(self.function):
            self.function=self.function(cfg=replace(cfg,func=self.function,params=self.parameters),env=env)

    def reset(self,env_ids):
        if hasattr(self.function,"reset"):
            self.function.reset(env_ids=env_ids)

    def __call__(self,env,**kwargs):
        value=self.function(env,**self.parameters)
        return torch.nan_to_num(value,nan=0.,posinf=self.limit,neginf=0.).clamp(0,self.limit)
