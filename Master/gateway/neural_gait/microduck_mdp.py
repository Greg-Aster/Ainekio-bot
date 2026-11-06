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
    quality,baseline,moving=scores(env)
    improvement=(quality-baseline).sum(-1)
    upright=(-env.scene["robot"].data.projected_gravity_b[:,2]).clamp(0,1)
    # Tilt cannot hide a negative tracking score. At nonzero commands, an
    # upright stationary robot earns zero task reward; better tracking pays.
    result=torch.where(improvement>0,improvement*upright,improvement)
    curriculum=state(env)
    component_moving=baseline<1
    progress=((quality-baseline)/(1-baseline).clamp_min(1e-6)).clamp(0,1)
    progress=torch.nan_to_num(progress,nan=0.,posinf=0.,neginf=0.)
    curriculum.score_sum+=(progress*component_moving).sum(-1)/component_moving.sum(-1).clamp_min(1)
    curriculum.elapsed+=1
    curriculum.score_count+=moving
    robot=env.scene["robot"].data;command=env.command_manager.get_command("twist")
    env.extras["log"]["Tracking/linear_error_m_s"]=torch.norm(robot.root_link_lin_vel_b[:,:2]-command[:,:2],dim=-1).mean()
    env.extras["log"]["Tracking/yaw_error_rad_s"]=(robot.root_link_ang_vel_b[:,2]-command[:,2]).abs().mean()
    return result


def upright_cost(env):
    return 1-(-env.scene["robot"].data.projected_gravity_b[:,2]).clamp(-1,1)


def action_change(env):
    return (env.action_manager.action-env.action_manager.prev_action).square().mean(-1)


def action_size(env):
    return env.action_manager.action.square().mean(-1)


def standing_pose(env):
    _,_,moving=scores(env)
    feet=env.action_manager.get_term("feet")
    measured=feet.sensors.joint
    return (measured-feet.body.q0.reshape(1,12).to(measured.dtype)).square().mean(-1)*(~moving)


def tracked_air_time(env):
    quality,baseline,moving=scores(env)
    airtime=mdp.feet_air_time(env,sensor_name="feet_ground_contact",threshold_min=.05,
                            threshold_max=.3,command_name="twist",command_threshold=0.)
    upright=(-env.scene["robot"].data.projected_gravity_b[:,2]).clamp(0,1)
    return airtime/4*(.25+.75*quality.mean(-1))*moving*upright


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
