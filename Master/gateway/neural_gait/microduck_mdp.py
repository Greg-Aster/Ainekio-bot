"""Ainekio locomotion objective and performance-based disturbance curriculum."""
import math
import inspect
from dataclasses import replace

import torch
from mjlab.managers import ManagerTermBase
from mjlab.managers.event_manager import requires_model_fields
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
    negative=torch.where(component_moving,delta/(1-baseline).clamp_min(.5),.25*delta)
    lin_cmd_sq=command[:,:2].square().sum(-1).clamp_min(1e-6)
    lin_dot=(actual[:,:2]*command[:,:2]).sum(-1)
    lin_ratio=lin_dot/lin_cmd_sq
    proj_vel=lin_ratio.unsqueeze(-1)*command[:,:2]
    orth_vel_sq=(actual[:,:2]-proj_vel).square().sum(-1)
    orth_gate=torch.exp(-orth_vel_sq/(0.065**2))
    ang_ratio=(actual[:,2]*command[:,2])/command[:,2].square().clamp_min(1e-6)
    lin_prog=lin_ratio.clamp(0.,1.)*orth_gate
    ang_prog=ang_ratio.clamp(0.,1.)
    directed=torch.stack((lin_prog,ang_prog),-1)
    positive=.60*(delta/headroom).clamp_min(0.)+.40*directed
    wrong_way=torch.stack(((lin_ratio<0.)|(lin_ratio>2.),(ang_ratio<0.)|(ang_ratio>2.)),-1)
    comp=torch.where(wrong_way&(delta<0),negative,positive)
    rev_turn_bonus=(
        0.55*torch.where(wrong_way[:,0],0.,lin_prog)*(command[:,0]<-0.02).to(lin_prog.dtype)
        +0.45*torch.where(wrong_way[:,1],0.,ang_prog)*(command[:,2].abs()>0.15).to(ang_prog.dtype)
    )
    ang_gate=.35+.65*quality[:,1].clamp(0.,1.)
    lin_coupled=torch.where(comp[:,0]>0,comp[:,0]*ang_gate,comp[:,0])
    ang_authority=torch.where((command[:,2].abs()>0.15)&(comp[:,1]>0),1.25,1.0)
    improvement=lin_coupled+ang_authority*comp[:,1]+rev_turn_bonus
    grav=robot.projected_gravity_b
    pitch_roll_gate=torch.exp(-3.5*grav[:,0].square()-4.5*grav[:,1].square())
    upright=(-grav[:,2]).clamp(0,1)*pitch_roll_gate
    if hasattr(env,"action_manager"):
        _,rear_z,_,left_z,right_z=_torso_all_heights(env)
        support_z=torch.minimum(rear_z,torch.minimum(left_z,right_z))
        upright=upright*((support_z-0.046)/0.014).clamp(0.20,1.0)
    # Tilt cannot hide a negative tracking score. At nonzero commands, an
    # upright stationary robot earns zero task reward; better tracking pays.
    result=torch.where(improvement>0,improvement*upright,improvement)
    curriculum=state(env)
    active=baseline<1
    progress=torch.maximum((delta/headroom).clamp(0,1),(1.35*torch.where(wrong_way,0.,directed)).clamp(0,1))
    progress=torch.nan_to_num(progress,nan=0.,posinf=0.,neginf=0.)
    curriculum.score_sum+=(progress*active).sum(-1)/active.sum(-1).clamp_min(1)
    curriculum.elapsed+=1
    curriculum.score_count+=moving
    env.extras["log"]["Tracking/linear_error_m_s"]=torch.norm(robot.root_link_lin_vel_b[:,:2]-command[:,:2],dim=-1).mean()
    env.extras["log"]["Tracking/yaw_error_rad_s"]=(robot.root_link_ang_vel_b[:,2]-command[:,2]).abs().mean()
    return result


def _true_joint_state(feet):
    if hasattr(feet,"_entity") and hasattr(feet,"joint_ids"):
        data=feet._entity.data
        return data.joint_pos[:,feet.joint_ids],data.joint_vel[:,feet.joint_ids]
    return feet.sensors.joint,feet.sensors.joint_velocity


def _torso_all_heights(env, target_z=0.0642):
    """Estimate torso center, rear (-93 mm), front (+80 mm), left (+58 mm) and right (-58 mm) heights above stance feet."""
    robot=env.scene["robot"].data
    up_b=(-robot.projected_gravity_b).clamp(-1.,1.)
    rear_pitch_dz=-0.093*up_b[:,0]
    front_pitch_dz=0.080*up_b[:,0]
    left_roll_dz=0.058*up_b[:,1]
    right_roll_dz=-0.058*up_b[:,1]
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
        torso_z=0.5*(rear_z+front_z)
        left_z=torso_z+left_roll_dz
        right_z=torso_z+right_roll_dz
    else:
        base_z=target_z*up_b[:,2].clamp_min(0.)
        rear_z=base_z+rear_pitch_dz
        front_z=base_z+front_pitch_dz
        left_z=base_z+left_roll_dz
        right_z=base_z+right_roll_dz
        torso_z=base_z
    return torso_z,rear_z,front_z,left_z,right_z


def torso_heights(env, target_z=0.0642):
    """Estimate torso center, rear (-93 mm) and front (+80 mm) heights above stance feet."""
    torso_z,rear_z,front_z,_,_=_torso_all_heights(env,target_z=target_z)
    return torso_z,rear_z,front_z


def body_collapsed(env, minimum_z=0.048):
    """Terminate when the torso center, rear pelvis, front chest or side support collapses below 48 mm."""
    torso_z,rear_z,front_z,left_z,right_z=_torso_all_heights(env)
    side_min=minimum_z-0.003
    return (torso_z<minimum_z)|(rear_z<minimum_z)|(front_z<minimum_z)|(left_z<side_min)|(right_z<side_min)


def upright_cost(env):
    _,_,moving=scores(env)
    grav=env.scene["robot"].data.projected_gravity_b
    tilt_cost=(1-(-grav[:,2]).clamp(-1,1))+3.5*grav[:,0].square()+4.5*grav[:,1].square()
    torso_z,rear_z,front_z,left_z,right_z=_torso_all_heights(env)
    target_z=torch.where(moving,0.061,0.0642)
    rear_sag=((target_z-rear_z).clamp_min(0.)/0.010).square()
    side_z=torch.minimum(left_z,right_z)
    side_sag=((target_z-side_z).clamp_min(0.)/0.010).square()
    height_err=(
        ((torso_z-target_z)/0.014).square()
        +0.85*((rear_z-target_z)/0.014).square()
        +0.75*((front_z-target_z)/0.014).square()
        +0.80*rear_sag
        +0.90*side_sag
    ).clamp(0.,4.5)
    thigh_over=0.
    if hasattr(env,"action_manager"):
        q,_=_true_joint_state(env.action_manager.get_term("feet"))
        thigh_over=0.35*(q[:,1::3]-0.90).clamp_min(0.).square().sum(-1)
    return tilt_cost+0.40*height_err+thigh_over


def alternating_stride(env):
    """Reward diagonal trot stance, penalize same-girdle hops, and reward wide zero-mean AC stride excursion."""
    quality,_,moving=scores(env)
    robot=env.scene["robot"].data
    command=env.command_manager.get_command("twist")
    lin_cmd_sq=command[:,:2].square().sum(-1)
    lin_dot=(robot.root_link_lin_vel_b[:,:2]*command[:,:2]).sum(-1)
    ang_gate=.35+.65*quality[:,1].clamp(0.,1.)
    dir_gate=torch.where((lin_cmd_sq>1e-4)&(lin_dot<-0.01),0.2,1.0)*ang_gate
    grav=robot.projected_gravity_b
    upright=(-grav[:,2]).clamp(0,1)*torch.exp(-3.0*grav[:,:2].square().sum(-1))
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
        leg_q=0.5*(ac_dq[:,1::3]/0.35+ac_dq[:,2::3]/0.45)
        leg_vq=0.5*(vq[:,1::3]+vq[:,2::3])
        lin_mag=(lin_cmd_sq.sqrt()/0.15).clamp_min(0.)
        ang_mag=(command[:,2].abs()/0.60).clamp_min(0.)
        turn_frac=(ang_mag/(lin_mag+ang_mag+1e-5)).clamp(0.,1.)
        lin_frac=1.-turn_frac
        # In translational walking, diagonal legs (RL+FR, RR+FL) move in-phase in X
        # and girdle pairs (RL+RR, FL+FR) move anti-phase in X. During in-place
        # differential yaw turns, left (+1) and right (-1) sides move opposite in X.
        side_sign=leg_q.new_tensor([1.,-1.,1.,-1.])
        rot_q=leg_q*side_sign
        rot_vq=leg_vq*side_sign
        rear_anti_lin=(-(leg_q[:,0]*leg_q[:,1]+0.35*leg_vq[:,0]*leg_vq[:,1])).clamp(-0.2,1.5)
        front_anti_lin=(-(leg_q[:,2]*leg_q[:,3]+0.35*leg_vq[:,2]*leg_vq[:,3])).clamp(-0.2,1.5)
        diag_sync_lin=0.5*((leg_q[:,0]*leg_q[:,3]+0.35*leg_vq[:,0]*leg_vq[:,3])
                          +(leg_q[:,1]*leg_q[:,2]+0.35*leg_vq[:,1]*leg_vq[:,2])).clamp(-0.2,1.6)
        rear_anti_rot=(-(rot_q[:,0]*rot_q[:,1]+0.35*rot_vq[:,0]*rot_vq[:,1])).clamp(-0.2,1.5)
        front_anti_rot=(-(rot_q[:,2]*rot_q[:,3]+0.35*rot_vq[:,2]*rot_vq[:,3])).clamp(-0.2,1.5)
        diag_sync_rot=0.5*((rot_q[:,0]*rot_q[:,3]+0.35*rot_vq[:,0]*rot_vq[:,3])
                          +(rot_q[:,1]*rot_q[:,2]+0.35*rot_vq[:,1]*rot_vq[:,2])).clamp(-0.2,1.6)
        stride_q=(lin_frac*(rear_anti_lin+front_anti_lin+diag_sync_lin)
                 +turn_frac*(rear_anti_rot+front_anti_rot+diag_sync_rot))
        anchor_xy_gate=torch.where((command[:,0]<-0.02)|(command[:,2].abs()>0.15),0.25,1.0)
        thigh_over=(q[:,1::3]-0.90).clamp_min(0.).square().sum(-1)
        rew=rew+0.40*stride_q*dir_gate-0.15*anchor_xy_gate*feet.mean_dq.square().sum(-1)-1.80*thigh_over
        foot_pos_mm,_=feet.body.forward(q.to(feet.body.O.dtype).reshape(-1,4,3))
        foot_pos_m=(foot_pos_mm*1e-3).to(rew.dtype)
        feet.mean_foot_pos_m.lerp_(foot_pos_m,0.05)
        ac_pos_m=foot_pos_m-feet.mean_foot_pos_m
        s_xy=torch.stack((ac_pos_m[...,0]/0.022,ac_pos_m[...,1]/0.014),dim=-1)
        rot_xy_sign=s_xy.new_tensor([[1.,-1.],[-1.,-1.],[1.,1.],[-1.,1.]])
        r_xy=s_xy*rot_xy_sign
        rear_foot_lin=(-(s_xy[:,0]*s_xy[:,1]).sum(-1)).clamp(-0.2,1.5)
        front_foot_lin=(-(s_xy[:,2]*s_xy[:,3]).sum(-1)).clamp(-0.2,1.5)
        diag_foot_lin=0.5*((s_xy[:,0]*s_xy[:,3]).sum(-1)+(s_xy[:,1]*s_xy[:,2]).sum(-1)).clamp(-0.2,1.6)
        rear_foot_rot=(-(r_xy[:,0]*r_xy[:,1]).sum(-1)).clamp(-0.2,1.5)
        front_foot_rot=(-(r_xy[:,2]*r_xy[:,3]).sum(-1)).clamp(-0.2,1.5)
        diag_foot_rot=0.5*((r_xy[:,0]*r_xy[:,3]).sum(-1)+(r_xy[:,1]*r_xy[:,2]).sum(-1)).clamp(-0.2,1.6)
        stride_xy=(lin_frac*(rear_foot_lin+front_foot_lin+diag_foot_lin)
                  +turn_frac*(rear_foot_rot+front_foot_rot+diag_foot_rot))
        rew=rew+0.35*stride_xy*dir_gate
        mean_offset_m=feet.mean_foot_pos_m-feet.foot_home_pos_m
        amp_z=feet.mean_amp_z_m if hasattr(feet,"mean_amp_z_m") else torch.zeros_like(mean_offset_m[...,2])
        if hasattr(feet,"mean_amp_q") and hasattr(feet,"mean_amp_z_m"):
            feet.mean_amp_q.lerp_(leg_q.abs(),0.05)
            feet.mean_amp_z_m.lerp_(ac_pos_m[...,2].abs(),0.05)
            amp_z=feet.mean_amp_z_m
        rev_cmd=(command[:,0]<-0.02)
        rev_lift_allowance=torch.where(rev_cmd.unsqueeze(-1),(1.15*amp_z[:,:2]).clamp(0.,0.016),0.)
        rear_crouch_dz=((mean_offset_m[:,:2,2]-rev_lift_allowance)/0.0065).clamp_min(0.).square().sum(-1)
        xy_offset_cost=(mean_offset_m[...,:2]/0.022).square().sum((-1,-2))
        z_offset_cost=(mean_offset_m[...,2]/0.018).square().sum(-1)
        rew=rew-0.12*(anchor_xy_gate*xy_offset_cost+z_offset_cost)-0.40*rear_crouch_dz
        if hasattr(feet,"mean_amp_q") and hasattr(feet,"mean_amp_z_m"):
            difficulty=getattr(state(env),"difficulty",torch.zeros_like(upright))
            flat_terrain=(difficulty==0).to(rew.dtype)
            flat_level=flat_terrain*(upright>0.970).to(rew.dtype)
            straight_cmd=(command[:,2].abs()<0.15).to(rew.dtype)*(command[:,1].abs()<0.02).to(rew.dtype)
            pure_turn_cmd=(command[:,2].abs()>=0.15).to(rew.dtype)*(lin_cmd_sq<1e-4).to(rew.dtype)
            rev_f=rev_cmd.to(rew.dtype)
            sym_gate=flat_level*straight_cmd*dir_gate
            turn_z_gate=flat_level*pure_turn_cmd*dir_gate
            q_sym_err=(feet.mean_amp_q[:,0]-feet.mean_amp_q[:,1]).square()+(feet.mean_amp_q[:,2]-feet.mean_amp_q[:,3]).square()
            z_sym_err=((feet.mean_amp_z_m[:,0]-feet.mean_amp_z_m[:,1])/0.008).square()+((feet.mean_amp_z_m[:,2]-feet.mean_amp_z_m[:,3])/0.008).square()
            mean_dz=mean_offset_m[...,2]
            stance_sym_err=((mean_dz[:,0]-mean_dz[:,1])/0.008).square()+((mean_dz[:,2]-mean_dz[:,3])/0.008).square()
            roll_lean=(robot.projected_gravity_b[:,1]/0.08).square().clamp(0.,2.0)
            rear_sym_lift=(torch.minimum(feet.mean_amp_z_m[:,0],feet.mean_amp_z_m[:,1])/0.0085).clamp(0.,1.0)
            front_sym_lift=(torch.minimum(feet.mean_amp_z_m[:,2],feet.mean_amp_z_m[:,3])/0.0085).clamp(0.,1.0)
            sym_lift=0.26*rear_sym_lift+0.18*front_sym_lift
            rev_rear_lift=0.24*rev_f*dir_gate*rear_sym_lift
            stance_sym_gate=flat_terrain*(straight_cmd+pure_turn_cmd)*dir_gate
            rew=rew+dir_gate*sym_lift+rev_rear_lift-0.18*(straight_cmd+pure_turn_cmd)*dir_gate*roll_lean-0.25*stance_sym_gate*stance_sym_err.clamp(0.,2.0)
            rew=rew+sym_gate*(-0.30*q_sym_err-0.30*z_sym_err.clamp(0.,2.5))
            rew=rew+turn_z_gate*(-0.25*z_sym_err.clamp(0.,2.5))
    return rew*moving*upright


def action_change(env):
    return (env.action_manager.action-env.action_manager.prev_action).square().mean(-1)


def action_size(env):
    _,_,moving=scores(env)
    return env.action_manager.action.square().mean(-1)*(~moving)


def standing_pose(env):
    _,_,moving=scores(env)
    feet=env.action_manager.get_term("feet")
    measured,_=_true_joint_state(feet)
    pose_error=(measured-feet.body.q0.reshape(1,12).to(measured.dtype)).square().mean(-1)
    contact=env.scene["feet_ground_contact"].data
    air_hang=(contact.current_air_time-.40).clamp(0,1).mean(-1)
    stance_stall=(contact.current_contact_time-.60).clamp(0,1).mean(-1)
    return pose_error*(~moving)+(air_hang+.5*stance_stall)*moving


def tracked_air_time(env):
    quality,baseline,moving=scores(env)
    progress=((quality-baseline)/(1-baseline).clamp_min(1e-6)).clamp(0,1)
    progress=torch.nan_to_num(progress,nan=0.,posinf=0.,neginf=0.)
    airtime=mdp.feet_air_time(env,sensor_name="feet_ground_contact",threshold_min=.08,
                            threshold_max=.35,command_name="twist",command_threshold=0.)
    grav=env.scene["robot"].data.projected_gravity_b
    upright=(-grav[:,2]).clamp(0,1)*torch.exp(-3.0*grav[:,:2].square().sum(-1))
    return airtime/4*(.3+.7*progress.mean(-1))*moving*upright


def foot_clearance(env, target_height=0.020, max_free_height=0.040, height_sensor_name="foot_height_scan",
                   sensor_name="feet_ground_contact", command_name="twist", command_threshold=0.01, asset_cfg=None):
    """Penalize low swing-foot drag below target_height while in air, allowing step-over lift up to max_free_height."""
    asset=env.scene[asset_cfg.name if asset_cfg is not None else "robot"]
    foot_height=env.scene[height_sensor_name].data.heights
    in_air=(env.scene[sensor_name].data.found==0).to(foot_height.dtype)
    foot_vel_xy=asset.data.site_lin_vel_w[:,asset_cfg.site_ids,:2]
    vel_gate=(torch.norm(foot_vel_xy,dim=-1)/0.16).clamp(max=1.4)
    low_err=0.55*((target_height-foot_height).clamp_min(0.)/target_height)
    high_err=0.25*((foot_height-max_free_height).clamp_min(0.)/target_height)
    leg_weight=torch.ones_like(foot_height)
    command=env.command_manager.get_command(command_name) if command_name is not None else None
    if command is not None:
        rev=(command[:,0]<-0.02).unsqueeze(-1)
        rear_mask=foot_height.new_tensor([[1.,1.,0.,0.]])>0.5
        leg_weight=torch.where(rev&rear_mask,1.25,1.0)
    cost=torch.sum((low_err+high_err)*vel_gate*in_air*leg_weight,dim=1)
    if command is not None:
        total_command=torch.norm(command[:,:2],dim=1)+torch.abs(command[:,2])
        cost=cost*(total_command>command_threshold).float()
    return cost


class foot_swing_height:
    """Penalize swing peak shortfall below target_height at landing, with a free step-over band up to max_free_height."""
    def __init__(self, cfg, env):
        height_sensor=env.scene[cfg.params["height_sensor_name"]]
        self.peak_heights=torch.zeros((env.num_envs,height_sensor.num_frames),device=env.device,dtype=torch.float32)
        self.step_dt=env.step_dt

    def reset(self, env_ids=None):
        if env_ids is None:
            self.peak_heights.zero_()
        else:
            self.peak_heights[env_ids]=0.

    def __call__(self, env, sensor_name, height_sensor_name, target_height=0.028,
                 command_name="twist", command_threshold=0.01, max_free_height=0.038):
        contact_sensor=env.scene[sensor_name]
        command=env.command_manager.get_command(command_name)
        foot_heights=env.scene[height_sensor_name].data.heights
        in_air=contact_sensor.data.found==0
        self.peak_heights=torch.where(in_air,torch.maximum(self.peak_heights,foot_heights),self.peak_heights)
        first_contact=contact_sensor.compute_first_contact(dt=self.step_dt)
        last_air=getattr(contact_sensor.data,"last_air_time",None)
        real_swing=first_contact if last_air is None else (first_contact&(last_air>=0.06))
        active=((torch.norm(command[:,:2],dim=1)+torch.abs(command[:,2]))>command_threshold).float()
        low_err=(target_height-self.peak_heights).clamp_min(0.)/target_height
        high_err=0.5*(self.peak_heights-max_free_height).clamp_min(0.)/target_height
        cost=torch.sum((low_err.square()+high_err.square())*real_swing.float(),dim=1)*active
        num_landings=torch.sum(real_swing.float())
        env.extras["log"]["Metrics/peak_height_mean"]=torch.sum(self.peak_heights*real_swing.float())/torch.clamp(num_landings,min=1)
        self.peak_heights=torch.where(first_contact,torch.zeros_like(self.peak_heights),self.peak_heights)
        return cost


def foot_slip(env, sensor_name="feet_ground_contact", command_name="twist", command_threshold=0.01, asset_cfg=None):
    """Penalize horizontal foot sliding during contact with L2 + 0.35 * smooth-L1."""
    asset=env.scene[asset_cfg.name if asset_cfg is not None else "robot"]
    contact_sensor=env.scene[sensor_name]
    command=env.command_manager.get_command(command_name)
    total_command=torch.norm(command[:,:2],dim=1)+torch.abs(command[:,2])
    active=(total_command>command_threshold).float()
    in_contact=(contact_sensor.data.found>0).float()
    foot_vel_xy=asset.data.site_lin_vel_w[:,asset_cfg.site_ids,:2]
    vel_xy_sq=foot_vel_xy.square().sum(dim=-1)
    slip_speed=torch.sqrt(vel_xy_sq+1e-6)-1e-3
    cost=torch.sum((vel_xy_sq+0.35*slip_speed.clamp_min(0.))*in_contact,dim=1)*active
    num_in_contact=torch.sum(in_contact)
    env.extras["log"]["Metrics/slip_velocity_mean"]=torch.sum(slip_speed.clamp_min(0.)*in_contact)/torch.clamp(num_in_contact,min=1)
    return cost


@requires_model_fields("geom_friction")
def randomize_multisurface_friction(env, env_ids=None, asset_cfg=None, ranges=(0.14, 1.45)):
    """Sample multi-surface friction across the 4 feet: 45% slick wood, 35% split wood/carpet, 20% carpet."""
    if hasattr(asset_cfg,"resolve"):
        asset_cfg.resolve(env.scene)
    ids=torch.arange(env.num_envs,device=env.device) if env_ids is None else env_ids
    n=len(ids)
    if n==0:
        return
    f_min,f_max=float(ranges[0]),float(ranges[1])
    slick_hi=0.35
    grip_lo=0.69
    med_lo=0.47
    # Pin world/terrain geoms to f_min so MuJoCo's contact friction resolves to each foot's local surface value.
    mj_m=env.sim.mj_model
    world_geom_ids=torch.tensor([i for i in range(mj_m.ngeom) if mj_m.geom_bodyid[i]<=1],
                                dtype=torch.long,device=env.device)
    if len(world_geom_ids)>0:
        env.sim.model.geom_friction[ids.unsqueeze(1),world_geom_ids.unsqueeze(0),0]=f_min
    u_mode=torch.rand((n,1),device=env.device)
    slick=f_min+(slick_hi-f_min)*torch.rand((n,4),device=env.device)
    grip=grip_lo+(f_max-grip_lo)*torch.rand((n,4),device=env.device)
    split=torch.where(torch.rand((n,4),device=env.device)<0.5,slick,grip)
    carpet=med_lo+(f_max-med_lo)*torch.rand((n,4),device=env.device)
    foot_mu=torch.where(u_mode<0.45,slick,torch.where(u_mode<0.80,split,carpet))
    geom_ids=torch.as_tensor(asset_cfg.geom_ids,dtype=torch.long,device=env.device)
    if len(geom_ids)==8:
        foot_mu_geoms=foot_mu.repeat_interleave(2,dim=1)
    elif len(geom_ids)==4:
        foot_mu_geoms=foot_mu
    else:
        foot_mu_geoms=foot_mu[:,:1].expand(n,len(geom_ids))
    env.sim.model.geom_friction[ids.unsqueeze(1),geom_ids.unsqueeze(0),0]=foot_mu_geoms


@requires_model_fields("actuator_forcerange", "actuator_gainprm", "actuator_biasprm")
def randomize_actuators(env, env_ids=None, kp_range=(0.70, 1.15), kd_range=(0.80, 1.45),
                        rear_kp_range=(0.62, 1.00), weak_corner_kp_range=(0.55, 0.78)):
    """Randomize per-joint kp/kd, single-corner leg compliance, and ratiometric 4th-wire ADC rail sag."""
    ids=torch.arange(env.num_envs,device=env.device) if env_ids is None else env_ids
    n=len(ids)
    if n==0:
        return
    mj_m=env.sim.mj_model
    base_kp=torch.as_tensor(mj_m.actuator_gainprm[:12,0],dtype=torch.float32,device=env.device).unsqueeze(0)
    base_kd=torch.as_tensor(-mj_m.actuator_biasprm[:12,2],dtype=torch.float32,device=env.device).unsqueeze(0)
    kp_mult=kp_range[0]+(kp_range[1]-kp_range[0])*torch.rand((n,12),device=env.device)
    u_mode=torch.rand(n,device=env.device)
    # 30% symmetric rear-load compliance, 30% single-corner weak leg (65% RL/RR), 40% nominal per-joint spread.
    rear_load_mask=(u_mode<0.30).unsqueeze(-1)
    rear_mult=rear_kp_range[0]+(rear_kp_range[1]-rear_kp_range[0])*torch.rand((n,4),device=env.device)
    kp_mult[:,[1,2,4,5]]=torch.where(rear_load_mask,rear_mult,kp_mult[:,[1,2,4,5]])
    weak_mask=(u_mode>=0.30)&(u_mode<0.60)
    u_leg=torch.rand(n,device=env.device)
    weak_leg=torch.where(u_leg<0.325,0,torch.where(u_leg<0.650,1,torch.where(u_leg<0.825,2,3)))
    weak_mult=weak_corner_kp_range[0]+(weak_corner_kp_range[1]-weak_corner_kp_range[0])*torch.rand((n,2),device=env.device)
    row_idx=torch.arange(n,device=env.device)[weak_mask]
    if len(row_idx)>0:
        leg_sel=weak_leg[weak_mask]
        kp_mult[row_idx,leg_sel*3+1]=weak_mult[weak_mask,0]
        kp_mult[row_idx,leg_sel*3+2]=weak_mult[weak_mask,1]
    kd_mult=kd_range[0]+(kd_range[1]-kd_range[0])*torch.rand((n,12),device=env.device)
    kp=base_kp*kp_mult
    kd=base_kd*kd_mult
    ctrl_ids=torch.arange(12,dtype=torch.long,device=env.device)
    env.sim.model.actuator_gainprm[ids.unsqueeze(1),ctrl_ids.unsqueeze(0),0]=kp
    env.sim.model.actuator_biasprm[ids.unsqueeze(1),ctrl_ids.unsqueeze(0),1]=-kp
    env.sim.model.actuator_biasprm[ids.unsqueeze(1),ctrl_ids.unsqueeze(0),2]=-kd
    if hasattr(env,"action_manager"):
        feet=env.action_manager.get_term("feet")
        if hasattr(feet,"sensors") and hasattr(feet.sensors,"raw_scale"):
            adc_active=torch.rand((n,1),device=env.device)<0.50
            scale_jitter=0.975+0.050*torch.rand((n,1),device=env.device)
            offset_jitter=-20.0+40.0*torch.rand((n,12),device=env.device)
            feet.sensors.raw_scale[ids]=torch.where(adc_active,scale_jitter,1.0)
            feet.sensors.raw_offset[ids]=torch.where(adc_active,offset_jitter,0.0)
            feet.sensors.feedback_initialized[ids]=False
            feet.sensors.feedback(feet.sensors.trace[0,ids],.02,ids=ids)


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
        level=((quality/0.72).clamp(0.,1.)*survival*rows).long().clamp(0,rows-1)
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
