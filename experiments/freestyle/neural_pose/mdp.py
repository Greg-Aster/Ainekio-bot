"""GPU MuJoCo (mjlab) reward, reset, four-bar closure, and goal curriculum for Neural Pose & Emote."""
from __future__ import annotations

import math
import torch
from mjlab.utils.lab_api.math import quat_from_euler_xyz, quat_mul
from gateway.neural_gait.tensor_body import wrap


def full_four_bar_qpos20(body, q43_rad: torch.Tensor) -> torch.Tensor:
    """Compute all 20 joint angles [sh, ca, pickup, cr, rod]*4 with 0.0 loop-closure error."""
    q43 = q43_rad.to(dtype=torch.float64)
    q0 = torch.zeros((1, 4, 3), dtype=torch.float64, device=q43.device)
    dx0, dz0, bc0, bs0, *_ = body.seed(q0)
    px0 = body.C[0] + body.r * math.cos(body.t0)
    pz0 = body.C[1] + body.r * math.sin(body.t0)
    gamma0 = torch.atan2(dz0 + body.b * bs0 - pz0, dx0 + body.b * bc0 - px0)

    dx, dz, bc, bs, *_ = body.seed(q43)
    beta = torch.atan2(bs, bc)
    th = body.t0 + q43[..., 2]
    px = body.C[0] + body.r * torch.cos(th)
    pz = body.C[1] + body.r * torch.sin(th)
    gamma = torch.atan2(dz + body.b * bs - pz, dx + body.b * bc - px)
    pickup = wrap(beta - body.b0 - q43[..., 1])
    rod = wrap(gamma - gamma0 - q43[..., 2])
    q20 = torch.stack((q43[..., 0], q43[..., 1], pickup, q43[..., 2], rod), dim=-1)
    return q20.reshape(-1, 20).to(dtype=torch.float32)


def build_pose_goal_bank(manifold, count: int = 2048, seed: int = 7) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Build a diverse GPU bank of (q_goal_rad [B,12], foot_norm [B,12], leg_support [B,4])."""
    import experiments.freestyle.freestyle_curriculum as fc

    device = manifold.device
    gen = torch.Generator(device="cpu")
    gen.manual_seed(seed)

    curated_deg: list[list[float]] = [
        list(fc.STAND_ANGLES),
        list(fc.SIT_ANGLES),
        list(fc.CROUCH_ANGLES),
        list(fc.REST_ANGLES),
        list(fc.DEEP_SQUAT_ANGLES),
        list(fc.WIDE_STANCE_ANGLES),
        # Seated rear brace + raised front paws
        [0.0, 23.24, 7.15, 0.0, 23.24, 7.15, 10.0, 52.0, 28.0, -10.0, 52.0, 28.0],
        [0.0, 23.24, 7.15, 0.0, 23.24, 7.15, -12.0, 38.0, -15.0, 12.0, 58.0, 35.0],
        # Front-right high wave / salute / point
        [-4.0, -6.0, -24.0, 6.0, -4.0, -22.0, 6.0, 4.0, -22.0, 14.0, 62.0, 48.0],
        [-4.0, -6.0, -24.0, 6.0, -4.0, -22.0, 6.0, 4.0, -22.0, -18.0, 58.0, 36.0],
        [-4.0, -6.0, -24.0, 6.0, -4.0, -22.0, 6.0, 4.0, -22.0, 0.0, 48.0, 12.0],
        # Front-left high wave / salute / point
        [6.0, -4.0, -22.0, -4.0, -6.0, -24.0, -14.0, 62.0, 48.0, -6.0, 4.0, -22.0],
        [6.0, -4.0, -22.0, -4.0, -6.0, -24.0, 18.0, 58.0, 36.0, -6.0, 4.0, -22.0],
        # Single-leg lifts & side-to-side swings (all 4 legs)
        [0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 22.0, 36.0, -5.0],
        [0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25, -22.0, 36.0, -5.0],
        [0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 22.0, 36.0, -5.0, 0.0, 0.94, -21.25],
        [0.0, 0.94, -21.25, 0.0, 0.94, -21.25, -22.0, 36.0, -5.0, 0.0, 0.94, -21.25],
        [22.0, 28.0, 10.0, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25],
        [-22.0, 28.0, 10.0, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25],
        [0.0, 0.94, -21.25, 22.0, 28.0, 10.0, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25],
        [0.0, 0.94, -21.25, -22.0, 28.0, 10.0, 0.0, 0.94, -21.25, 0.0, 0.94, -21.25],
        # Bow, two-stage forward stretch, frog crouch, pushup low/high
        [0.0, 14.0, -18.0, 0.0, 14.0, -18.0, 0.0, -22.0, 18.0, 0.0, -22.0, 18.0],
        [0.0, -16.0, -22.0, 0.0, -16.0, -22.0, 0.0, 40.0, 46.0, 0.0, 40.0, 46.0],
        [0.0, -16.0, -22.0, 0.0, -16.0, -22.0, 0.0, 115.0, 56.0, 0.0, 115.0, 56.0],
        [-16.0, -20.0, 22.0, -16.0, -20.0, 22.0, -16.0, -12.0, -35.0, -16.0, -12.0, -35.0],
    ]

    # Harvest poses from all 60+ curriculum families as well
    fams = [getattr(fc, k) for k in sorted(dir(fc)) if k.startswith("prog_") and callable(getattr(fc, k))]
    for fn in fams:
        try:
            rec = fn()
            prog = rec if isinstance(rec, list) else (rec.get("program", []) if isinstance(rec, dict) else [])
            cursor = list(fc.STAND_ANGLES)
            for op in prog:
                if op["name"] in ("pose", "move"):
                    args = op["arguments"]
                    j_list = [args["joint"]] if op["name"] == "move" else args["joints"]
                    a_list = [args["angle_deg"]] if op["name"] == "move" else args["angles_deg"]
                    for jn, av in zip(j_list, a_list):
                        idx = fc.JOINTS.index(jn)
                        cursor[idx] = float(av) if args.get("reference", "absolute") == "absolute" else cursor[idx] + float(av)
                    curated_deg.append(list(cursor))
        except Exception:
            pass

    stand_t = torch.tensor(fc.STAND_ANGLES, dtype=torch.float32).reshape(1, 4, 3)
    sit_brace_rear = torch.tensor([[0.0, 23.24, 7.15], [0.0, 23.24, 7.15]], dtype=torch.float32)

    remaining = max(64, count - len(curated_deg))
    n_stance = int(remaining * 0.35)
    n_one_leg = int(remaining * 0.35)
    n_two_paw = int(remaining * 0.15)
    n_free = remaining - n_stance - n_one_leg - n_two_paw

    # 1. Symmetric & asymmetric 4-leg postures / leans
    u_sh = (torch.rand((n_stance, 4), generator=gen) * 2 - 1) * 20.0
    u_ca = -22.0 + torch.rand((n_stance, 4), generator=gen) * 44.0
    u_cr = -55.0 + torch.rand((n_stance, 4), generator=gen) * 80.0
    # Make half of stance poses left-right symmetric (`body.sign` already mirrors roll sign: RL_sh == RR_sh)
    half = n_stance // 2
    u_sh[:half, 1] = u_sh[:half, 0]
    u_sh[:half, 3] = u_sh[:half, 2]
    u_ca[:half, 1] = u_ca[:half, 0]
    u_ca[:half, 3] = u_ca[:half, 2]
    u_cr[:half, 1] = u_cr[:half, 0]
    u_cr[:half, 3] = u_cr[:half, 2]
    stance_deg = torch.stack((u_sh, u_ca, u_cr), dim=-1).reshape(n_stance, 12)

    # 2. 3-leg balance + 1 gesturing leg (all 4 legs equally represented)
    one_leg_deg = stand_t.expand(n_one_leg, 4, 3).clone()
    one_leg_deg += (torch.rand((n_one_leg, 4, 3), generator=gen) * 2 - 1) * torch.tensor([6.0, 8.0, 8.0])
    free_leg = torch.randint(0, 4, (n_one_leg,), generator=gen)
    gest_sh = (torch.rand(n_one_leg, generator=gen) * 2 - 1) * 32.0
    gest_ca = 8.0 + torch.rand(n_one_leg, generator=gen) * 58.0
    gest_cr = -45.0 + torch.rand(n_one_leg, generator=gen) * 95.0
    rows = torch.arange(n_one_leg)
    one_leg_deg[rows, free_leg, 0] = gest_sh
    one_leg_deg[rows, free_leg, 1] = gest_ca
    one_leg_deg[rows, free_leg, 2] = gest_cr
    one_leg_deg = one_leg_deg.reshape(n_one_leg, 12)

    # 3. Seated rear-brace + 2 front paws gesturing
    two_paw_deg = torch.zeros((n_two_paw, 4, 3), dtype=torch.float32)
    two_paw_deg[:, :2, :] = sit_brace_rear.unsqueeze(0) + (torch.rand((n_two_paw, 2, 3), generator=gen) * 2 - 1) * 3.0
    two_paw_deg[:, 2:, 0] = (torch.rand((n_two_paw, 2), generator=gen) * 2 - 1) * 28.0
    two_paw_deg[:, 2:, 1] = 10.0 + torch.rand((n_two_paw, 2), generator=gen) * 55.0
    two_paw_deg[:, 2:, 2] = -40.0 + torch.rand((n_two_paw, 2), generator=gen) * 85.0
    two_paw_deg = two_paw_deg.reshape(n_two_paw, 12)

    # 4. Full arbitrary 4-leg combinations (for suspended air / rest / floor mimes)
    free_sh = (torch.rand((n_free, 4), generator=gen) * 2 - 1) * 30.0
    free_ca = -42.0 + torch.rand((n_free, 4), generator=gen) * 102.0
    free_cr = -85.0 + torch.rand((n_free, 4), generator=gen) * 135.0
    free_deg = torch.stack((free_sh, free_ca, free_cr), dim=-1).reshape(n_free, 12)

    curated_t = torch.tensor(curated_deg, dtype=torch.float32)
    grounded_part = torch.cat((curated_t, stance_deg, one_leg_deg, two_paw_deg), dim=0)
    grounded_count = min(count, int(grounded_part.shape[0]))
    all_deg = torch.cat((grounded_part, free_deg), dim=0)[:count]
    q_rad, foot_norm = manifold.project_batch_rad(all_deg.to(device=device) * (math.pi / 180.0))

    # Infer leg support vector [B, 4] on GPU
    pts, _ = manifold.body.forward(q_rad.to(torch.float64).reshape(-1, 4, 3))
    z_mm = pts[..., 2].to(torch.float32)
    min_z = z_mm.amin(dim=-1, keepdim=True)
    max_z = z_mm.amax(dim=-1, keepdim=True)
    flat = (max_z - min_z) <= 8.0
    support = torch.where(flat | ((z_mm - min_z) <= 10.0), 1.0, 0.0)
    all_zero = support.sum(dim=-1, keepdim=True) == 0.0
    support = torch.where(all_zero, torch.ones_like(support), support)
    return q_rad, foot_norm, support, grounded_count


def pose_tracking_reward(env) -> torch.Tensor:
    """Dense multi-scale joint tracking reward with stance balance slack and obstructed-stop target adaptation."""
    pose_term = env.action_manager.get_term("pose")
    q_true = pose_term._entity.data.joint_pos[:, pose_term.joint_ids]
    q_goal = pose_term.current_goal_rad
    support = pose_term.leg_support  # (N, 4)
    suspended = pose_term.is_suspended  # (N,)

    jam_contacted = getattr(pose_term, "jam_contacted", None)
    if jam_contacted is not None:
        jam_3 = jam_contacted.repeat_interleave(3, dim=-1)
        eff_goal = torch.where(jam_3, pose_term.jam_mid_rad, q_goal)
    else:
        eff_goal = q_goal

    err = (q_true - eff_goal).reshape(-1, 4, 3)
    abs_err = err.abs()

    # Stance legs during multi-leg lifts (sum(support) < 3.5) get 0.10 rad (~5.7 deg) CoM-balancing slack
    partial_support = (support.sum(dim=-1) < 3.5) & (~suspended)
    stance_leg = (support > 0.5) & partial_support.unsqueeze(-1)
    eff_err = torch.where(stance_leg.unsqueeze(-1), (abs_err - 0.10).clamp_min(0.0), abs_err)

    leg_sq = eff_err.square().mean(dim=-1)  # (N, 4)
    coarse = torch.exp(-leg_sq / (0.18 ** 2))
    fine = torch.exp(-leg_sq / (0.055 ** 2))
    per_leg = 0.65 * coarse + 0.35 * fine

    # Weight lifted/gesturing legs slightly higher so single-leg waves are crisp
    leg_w = torch.where((support < 0.5) & (~suspended.unsqueeze(-1)), 1.6, 1.0)
    score = (per_leg * leg_w).sum(dim=-1) / leg_w.sum(dim=-1).clamp_min(1.0)

    # Gate positive grounded reward on not being severely tipped
    grav = env.scene["robot"].data.projected_gravity_b
    upright_gate = torch.where(suspended, torch.ones_like(score), ((-grav[:, 2] - 0.35) / 0.45).clamp(0.15, 1.0))

    mae_deg = abs_err.mean() * (180.0 / math.pi)
    free_mask = (support < 0.5) & (~suspended.unsqueeze(-1))
    free_f = free_mask.to(torch.float32)
    free_sum = (abs_err * free_f.unsqueeze(-1)).sum() * (180.0 / math.pi)
    free_denom = (free_f.sum() * 3.0).clamp_min(1.0)
    free_mae_deg = torch.where(free_f.sum() > 0.5, free_sum / free_denom, mae_deg)
    env.extras["log"]["Pose/joint_mae_deg"] = mae_deg
    env.extras["log"]["Pose/gesture_leg_mae_deg"] = free_mae_deg
    return score * upright_gate


def jam_compliance_cost(env) -> torch.Tensor:
    """Penalize servo stall torque against obstructed limbs and reward compliant recoil onto q_true."""
    pose_term = env.action_manager.get_term("pose")
    if not hasattr(pose_term, "jam_contacted"):
        return torch.zeros(env.num_envs, device=env.device)

    q_true = pose_term._entity.data.joint_pos[:, pose_term.joint_ids]
    q_cmd = pose_term.logical.to(torch.float32)

    # Wait until observation delay + 2 ticks after physical stop contact so host telemetry reflects the jam
    delay_gate = pose_term.obs_delay_ticks.unsqueeze(-1) + 2
    ready_leg = pose_term.jam_leg_mask & pose_term.jam_contacted & (pose_term.jam_contact_age >= delay_gate)
    ready_j = ready_leg.repeat_interleave(3, dim=-1)
    blocked_j = ready_j & pose_term.jam_joint_mask

    # Gentle ~3.15 deg (0.055 rad) feeler preload keeps the jam observable across arbitrary hold lengths
    # while eliminating >85% of stall error |q_cmd - q_true| and allowing instant resume if unblocked.
    cmd_ideal = torch.where(blocked_j, q_true + 0.055 * pose_term.jam_dir, q_true)
    err = (q_cmd - cmd_ideal) * ready_j.to(torch.float32)
    abs_s = err.abs() / 0.085
    # Smooth L1 + bounded L2 so large 20..45 deg jams have strong non-zero recoil gradient everywhere
    per_j = 1.6 * abs_s + 0.55 * abs_s.square().clamp(max=16.0)
    cost = per_j.sum(dim=-1).clamp(0.0, 24.0)

    blk_f = blocked_j.to(torch.float32)
    stall_deg = ((q_cmd - q_true).abs() * blk_f).sum() * (180.0 / math.pi) / blk_f.sum().clamp_min(1.0)
    env.extras["log"]["Pose/jam_stall_deg"] = stall_deg
    return cost


def grounded_balance_cost(env) -> torch.Tensor:
    """Penalize unplanned tipping and torso ground-slam in grounded worlds."""
    pose_term = env.action_manager.get_term("pose")
    suspended = pose_term.is_suspended
    robot = env.scene["robot"].data
    grav = robot.projected_gravity_b  # upright = [0, 0, -1]

    # Allow intentional pitch/roll up to ~20 deg (0.34 rad) for bows/leans without penalty,
    # penalize tipping beyond safe support cone.
    horiz_tilt = torch.sqrt(grav[:, 0].square() + grav[:, 1].square() + 1e-6)
    excess_tilt = (horiz_tilt - 0.34).clamp_min(0.0)
    inverted = (1.0 - (-grav[:, 2]).clamp(-1.0, 1.0))
    # Strong penalty when single-leg or two-paw gesturing tilts toward falling
    partial_support = pose_term.leg_support.sum(dim=-1) < 3.5
    strict_tilt = torch.where(partial_support, 2.2 * (horiz_tilt - 0.22).clamp_min(0.0).square(), 0.0)
    tipped = (grav[:, 2] > -0.30).to(torch.float32)

    cost = (3.5 * excess_tilt.square() + 0.8 * inverted.square() + strict_tilt).clamp(0.0, 5.0) + 2.0 * tipped
    return torch.where(suspended, torch.zeros_like(cost), cost)


def action_smoothness_cost(env) -> torch.Tensor:
    """Penalize 50 Hz residual chattering, reversals, and unnecessary residual offset on unobstructed legs."""
    pose_term = env.action_manager.get_term("pose")
    u = pose_term.raw_action
    du = u - pose_term.prev_raw_action
    ddu = du - pose_term.prev_action_delta
    d_app = pose_term.applied_action - pose_term.prev_applied_action
    jam_contacted = getattr(pose_term, "jam_contacted", None)
    if jam_contacted is not None:
        unobstructed_f = (~jam_contacted.repeat_interleave(3, dim=-1)).to(u.dtype)
    else:
        unobstructed_f = torch.ones_like(u)
    return (
        0.55 * du.square().sum(dim=-1)
        + 0.40 * ddu.square().sum(dim=-1)
        + 1.50 * d_app.square().sum(dim=-1)
        + 0.06 * (u.square() * unobstructed_f).sum(dim=-1)
    ).clamp(0.0, 6.0)


def settle_damping_cost(env) -> torch.Tensor:
    """Penalize physical joint ringing and residual/command ripple once near a static goal or compliant stop."""
    pose_term = env.action_manager.get_term("pose")
    q_true = pose_term._entity.data.joint_pos[:, pose_term.joint_ids]
    v_true = pose_term._entity.data.joint_vel[:, pose_term.joint_ids]
    du = pose_term.raw_action - pose_term.prev_raw_action
    d_app = pose_term.applied_action - pose_term.prev_applied_action
    dd_app = d_app - pose_term.prev_applied_delta

    near_goal = (q_true - pose_term.current_goal_rad).abs() < 0.18
    jam_contacted = getattr(pose_term, "jam_contacted", None)
    if jam_contacted is not None:
        jam_3 = jam_contacted.repeat_interleave(3, dim=-1)
        q_cmd = pose_term.logical.to(torch.float32)
        cmd_ideal = torch.where(jam_3 & pose_term.jam_joint_mask, q_true + 0.060 * pose_term.jam_dir, q_true)
        near_jam = (q_cmd - cmd_ideal).abs() < 0.12
        near = torch.where(jam_3, near_jam, near_goal)
    else:
        near = near_goal

    osc_active = pose_term.osc_active
    static_f = (near & (~osc_active.unsqueeze(-1))).float()

    vel_ring = (v_true.square() * static_f).mean(dim=-1)
    res_ring = (du.square() * static_f).sum(dim=-1) * 2.0
    cmd_ring = ((d_app.square() + dd_app.square()) * static_f).sum(dim=-1) * 3.0
    env.extras["log"]["Pose/residual_rms"] = pose_term.raw_action.square().mean().sqrt()
    return (vel_ring + res_ring + cmd_ring).clamp(0.0, 6.0)


def stance_slip_cost(env, sensor_name: str = "feet_ground_contact", asset_cfg=None) -> torch.Tensor:
    """Penalize horizontal foot sliding on grounded stance legs."""
    pose_term = env.action_manager.get_term("pose")
    asset = env.scene["robot"]
    contact_sensor = env.scene[sensor_name]
    in_contact = (contact_sensor.data.found > 0).float() * pose_term.leg_support
    foot_vel_xy = asset.data.site_lin_vel_w[:, pose_term.foot_site_ids, :2]
    vel_sq = foot_vel_xy.square().sum(dim=-1)
    cost = (vel_sq * in_contact).sum(dim=-1).clamp(0.0, 3.0)
    return torch.where(pose_term.is_suspended, torch.zeros_like(cost), cost)


def tipped_over_termination(env) -> torch.Tensor:
    """Terminate grounded episodes if torso tips past ~72 degrees from upright."""
    pose_term = env.action_manager.get_term("pose")
    grav = env.scene["robot"].data.projected_gravity_b
    tipped = grav[:, 2] > -0.30
    return tipped & (~pose_term.is_suspended)


def reset_pose_worlds(env, env_ids):
    """Reset both grounded (70%) and suspended/unloaded (30%) worlds, including folded starts."""
    if env_ids is None:
        ids = torch.arange(env.num_envs, device=env.device)
    else:
        ids = env_ids
    n = len(ids)
    if n == 0:
        return

    pose_term = env.action_manager.get_term("pose")
    asset = env.scene["robot"]
    suspended = pose_term.is_suspended[ids]

    # Sample diverse initial joint poses:
    # 40% nominal stand, 35% folded/hanging/rest (including exact unloaded test angles!), 25% random bank pose
    u = torch.rand(n, device=env.device)
    q_init = pose_term.stand_q_rad.unsqueeze(0).expand(n, 12).clone()

    folded_presets = pose_term.folded_presets_rad  # (K, 12), pre-projected on closed manifold
    fold_idx = torch.randint(0, len(folded_presets), (n,), device=env.device)
    q_fold = folded_presets[fold_idx]

    bank_idx_g = torch.randint(0, pose_term.grounded_goal_count, (n,), device=env.device)
    bank_idx_s = torch.randint(0, len(pose_term.goal_bank_rad), (n,), device=env.device)
    bank_idx = torch.where(suspended, bank_idx_s, bank_idx_g)
    q_bank = pose_term.goal_bank_rad[bank_idx]

    q_proj = torch.where((u < 0.40).unsqueeze(-1), q_init, torch.where((u < 0.75).unsqueeze(-1), q_fold, q_bank))

    # Compute exact 20-DOF four-bar closed qpos
    q20 = full_four_bar_qpos20(pose_term.body, q_proj.reshape(n, 4, 3))
    v20 = torch.zeros_like(q20)
    asset.write_joint_state_to_sim(q20, v20, env_ids=ids)

    # Compute safe root z so folded/crouched poses spawn cleanly on terrain without penetration
    pts, _ = pose_term.body.forward(q_proj.to(torch.float64).reshape(n, 4, 3))
    lowest_foot_z_m = (pts[..., 2].amin(dim=-1).to(torch.float32)) * 1e-3
    grounded_z = (-lowest_foot_z_m + 0.022).clamp(0.052, 0.145)
    target_z = torch.where(suspended, torch.full_like(grounded_z, 0.28), grounded_z)

    root = asset.data.default_root_state[ids].clone()
    root[:, :3] = env.scene.env_origins[ids]
    root[:, 2] += target_z

    angles = (torch.rand((n, 3), device=env.device) * 2 - 1)
    angles[:, :2] *= math.radians(5.0)
    angles[:, 2] *= math.pi
    root[:, 3:7] = quat_mul(root[:, 3:7], quat_from_euler_xyz(*angles.unbind(-1)))
    root[:, 7:] = 0.0
    asset.write_root_state_to_sim(root, env_ids=ids)

    pose_term.reset_from_joint_state(ids, q_proj)
