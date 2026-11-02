"""Guided foot-trajectory teachers for DAgger imitation.

The original generator was never added to maintained source; only its output and a
`teacher_generator_source_sha256` provenance hash survive. This rebuilds it from the
recorded demonstrations rather than inventing a gait: the steady-state cycle is
extracted from a reference recording and re-rendered at a new period, amplitude and
leg order, so the waveform shape stays the one that was recorded.

Recovered model, verified against `speed-curriculum-p2.5-s40-x0-y16-z12`:

    phase_i(t) = frac(t / (period * control_hz) + order_i)
    ramp(t)    = min(1, t / (period * control_hz))       # first cycle only
    offset_i   = ramp * waveform(phase_i) * amplitude_scale + lean_x

Stance spans 75% of the cycle with x sweeping +stride/2 to -stride/2 linearly
(`x = (stride/2)(1 - phase/0.375)`), swing spans the remaining 25% and carries the
lift. Amplitude scales linearly with `stride`, `lean_y` and `lift` about the
reference case, so those three plus `period` and `order` are faithful search axes.
`shaped_lift` is not: only the reference lift shape is recoverable, so it is held.

Output matches `training.load_demonstrations`: a `.npz` with `observation`/`action`
and a `.json` sidecar carrying the current schema, environment version, geometry
representation and `recommended_cycle_rows` for `--demonstration-cycles`.

Run `python -m gateway.neural_gait.teachers --verify` to check the reconstruction
reproduces a reference recording before trusting a search built on it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .environment import (
    ENVIRONMENT_VERSION,
    EnvironmentConfig,
    make_environment,
    representation_identity,
)

LEG_ORDER = ("rear_left", "rear_right", "front_left", "front_right")
STANCE_FRACTION = 0.75
GUIDED_STEPS = Path(__file__).resolve().parents[3] / "build/neural-gait/guided-steps"
DEFAULT_REFERENCE = "speed-curriculum-p2.5-s40-x0-y16-z12"


def reference_case(path):
    """Read a recorded demonstration and the case parameters that produced it."""
    path = Path(path)
    sidecar = json.loads(path.with_suffix(".json").read_text())
    with np.load(path, allow_pickle=False) as data:
        arrays = {key: np.asarray(data[key]) for key in
                  ("requested_offset_mm", "phase", "action", "position_m")}
    return sidecar, arrays


def steady_waveform(arrays, order, period, control_hz):
    """One phase-indexed offset table per leg, pooled over every steady cycle.

    Each leg gets its own table because turning gaits are left/right asymmetric:
    a single shared waveform reproduces the straight-line teachers exactly but is
    off by 12-18 mm on the turn references, and rendering those from it produces
    no yaw at all. Indexing every leg by its own phase is fully general — for the
    symmetric straight-line cases all four tables simply agree.

    Pooling over steady cycles matters because `order * cycle` is not integral, so
    one leg samples the waveform only sparsely; several cycles give a dense enough
    grid to keep interpolation error off the sharply curved lift profile. The first
    cycle is excluded because it carries the startup ramp, which would otherwise be
    baked into every regenerated teacher as a decaying amplitude.
    """
    offsets, phase = arrays["requested_offset_mm"], arrays["phase"]
    order = np.asarray(order, dtype=float)
    cycle = max(2, round(period * control_hz))
    if len(offsets) < 2 * cycle:
        raise ValueError("Reference recording is shorter than two gait cycles")
    steady = slice(cycle, (len(offsets) // cycle) * cycle)
    tables = []
    for leg in range(len(order)):
        phases = phase[steady, leg]
        rows = np.argsort(phases, kind="stable")
        tables.append((phases[rows], offsets[steady, leg, :][rows]))
    return dict(cycle=cycle, tables=tables, legs=len(order))


def _interpolate(phase, table_phase, table_value):
    """Linear interpolation on the sorted phase table, wrapping 1.0 back to 0.0."""
    wrapped_phase = np.concatenate([table_phase, [table_phase[0] + 1.0]])
    wrapped_value = np.concatenate([table_value, table_value[:1]])
    return np.interp(phase, wrapped_phase, wrapped_value)


def render_offsets(steps, waveform, order, scale, lean_x, cycle):
    """Foot offsets in mm for every leg at every control step.

    `cycle` is the requested period in control steps, not the reference's. The
    tables are indexed by phase, so a new period re-times the same shape; taking
    the cycle length from the waveform instead would silently ignore --period and
    render every candidate at the reference cadence.
    """
    order = np.asarray(order, dtype=float)
    time_index = np.arange(steps)
    ramp = np.minimum(1.0, time_index / cycle)
    leg_phase = ((time_index / cycle)[:, None] + order[None, :]) % 1.0
    offsets = np.empty((steps, len(order), 3))
    for leg, (table_phase, table_value) in enumerate(waveform["tables"]):
        for axis in range(3):
            offsets[:, leg, axis] = _interpolate(leg_phase[:, leg], table_phase,
                                                 table_value[:, axis])
    offsets = offsets * np.asarray(scale)[None, None, :]
    offsets[..., 0] += lean_x
    return offsets * ramp[:, None, None]


def cycle_rows(period, control_hz, steps):
    """One complete steady cycle, after startup, for --demonstration-cycles."""
    cycle = round(period * control_hz)
    start = 3 * cycle
    if start + cycle > steps:
        raise ValueError("Recording is too short to hold three startup cycles plus one")
    return [int(start), int(start + cycle)]


def generate(case, config, waveform, out_dir):
    """Drive the guided trajectory through the simulator and record the contract."""
    scale = (case["stride"] / case["reference_stride"],
             case["lean_y"] / case["reference_lean_y"],
             case["lift"] / case["reference_lift"])
    steps = round(case["duration_s"] * config.control_hz)
    cycle = max(2, round(case["period"] * config.control_hz))
    offsets = render_offsets(steps, waveform, case["order"], scale, case["lean_x"], cycle)
    action_scale = np.tile(np.asarray(config.foot_action_scale_mm, dtype=float), 4)
    actions = (offsets.reshape(steps, 12) / action_scale).astype(np.float32)
    if np.abs(actions).max() > 1.0:
        raise ValueError(
            "Gait exceeds the foot action envelope: maximum normalized action %.4f "
            "(offending axis amplitude must stay within foot_action_scale_mm)"
            % float(np.abs(actions).max()))

    # Demonstrations and their consuming learner must use the same CAD contact
    # geometry and mass distribution. Omit rendering meshes only; omitting the
    # assembly substitutes primitive bodies and changes the physical plant.
    env = make_environment(config, include_visuals=False)
    started = time.monotonic()
    try:
        observations, next_observations, rewards, positions, uprights, contacts, phases = [], [], [], [], [], [], []
        terminal_flags, truncation_flags = [], []
        stages, jam, rejections, slip, travel, headings, clearance, fits = [], [], [], [], [], [], [], []
        requested, fitted = [], []
        reset_options = ({"scenario": case["scenario_id"]} if case.get("scenario_id") else None)
        observation, reset_info = env.reset(seed=case.get("seed", 1), options=reset_options)
        for index in range(steps):
            observations.append(np.asarray(observation, dtype=np.float32))
            phases.append([(index / cycle + value) % 1.0 for value in case["order"]])
            stages.append(1)
            observation, reward, terminated, truncated, info = env.step(actions[index])
            next_observations.append(np.asarray(observation, dtype=np.float32))
            terminal_flags.append(bool(terminated))
            truncation_flags.append(bool(truncated))
            rewards.append(float(reward))
            positions.append(env.data.qpos[:3].copy())
            uprights.append(float(info["upright"]))
            jam.append(int(info.get("jammed_joints", 0)))
            rejections.append(int(bool(info.get("target_rejected", False))))
            slip.append(float(info.get("contact_slip_speed_squared_m2_s2", 0.0)))
            travel.append(float(info.get("travel_reward", 0.0)))
            headings.append(float(info.get("heading_rad", 0.0)))
            fits.append(list(info.get("foot_fit") or [np.nan] * 4))
            # Requested nominal offsets are the submitted action, not measured
            # shaft/foot travel. Native P4 execution does not expose its fitted
            # offsets here; retain that absence rather than inventing a match.
            requested.append(actions[index].reshape(4, 3) * np.asarray(config.foot_action_scale_mm))
            measured_fit = info.get("fitted_foot_offset_mm")
            fitted.append(np.asarray(measured_fit if measured_fit is not None
                                     else np.full((4, 3), np.nan), dtype=float))
            feet = env.foot_measurements()
            contacts.append(list(feet["contact"]))
            clearance.append([float(value) * 1000 for value in feet["clearance_m"]])
            if terminated:
                raise ValueError("Guided teacher fell at step %d; reject this case" % index)
        start, end = np.asarray(positions[0]), np.asarray(positions[-1])
        steady_start = np.asarray(positions[cycle])
        displacement = end - start
        duration = steps / config.control_hz
    finally:
        env.close()
    requested = np.asarray(requested)
    fitted = np.asarray(fitted)

    identifier = case["id"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    demonstration = out_dir / f"{identifier}.npz"
    payload = dict(
        observation=np.asarray(observations, dtype=np.float32),
        action=actions,
        next_observation=np.asarray(next_observations, dtype=np.float32),
        reward=np.asarray(rewards, dtype=np.float64),
        position_m=np.asarray(positions, dtype=np.float64),
        upright=np.asarray(uprights, dtype=np.float64),
        contact=np.asarray(contacts, dtype=bool),
        requested_offset_mm=requested,
        fitted_offset_mm=fitted,
        phase=np.asarray(phases, dtype=np.float64),
        jam_mask=np.asarray(jam, dtype=np.int64),
        clearance_mm=np.asarray(clearance, dtype=np.float64),
        stage=np.asarray(stages, dtype=np.int64),
        terminated=np.asarray(terminal_flags, dtype=bool),
        truncated=np.asarray(truncation_flags, dtype=bool),
        contact_slip_squared=np.asarray(slip, dtype=np.float64),
        travel_reward=np.asarray(travel, dtype=np.float64),
        heading_rad=np.asarray(headings, dtype=np.float64),
        fallen=np.zeros(steps, dtype=bool),
        fit=np.asarray(fits, dtype=np.float64),
    )
    # np.savez appends ".npz" when the suffix is missing, so the temporary name
    # must already carry it or the rename target will not exist.
    temporary = out_dir / f"{identifier}.tmp.npz"
    np.savez(temporary, **payload)
    temporary.replace(demonstration)

    sidecar = dict(
        id=identifier,
        scope=("Offline guided foot trajectories; unchanged full CAD physics; "
               "not physical qualification"),
        schema=config.observation_schema,
        environment_version=ENVIRONMENT_VERSION,
        environment=asdict(config),
        representation=representation_identity(),
        case={key: case[key] for key in
              ("id", "period", "stride", "lean_x", "lean_y", "lift", "duration_s", "order")},
        command_m_s_rad_s=list(config.command),
        commands=[list(config.command)],
        scenario_id=reset_info.get("scenario_id"),
        leg_order=list(LEG_ORDER),
        warmup_s=0.0,
        duration_s=duration,
        waveform_reference=case["waveform_reference"],
        requested_offset_scope="Submitted nominal foot offsets; not measured motion",
        fitted_offset_scope=("Direct solver output" if config.execution_backend == "direct"
                             else "Not reported by native P4 executor; NaN in fitted arrays"),
        waveform_provenance=("steady cycle resampled from the recorded reference; "
                             "recorded nominal requests, not measured physical foot travel"),
        recommended_cycle_rows=cycle_rows(case["period"], config.control_hz, steps),
        recommended_cycle_scope=("Complete stable cycle after startup; all %d "
                                 "sensor/action rows retained. Authored guidance only, "
                                 "not a trained policy." % steps),
        displacement_m=[float(value) for value in displacement],
        steady_displacement_m=[float(value) for value in (end - steady_start)],
        mean_forward_m_s=float(displacement[0] / duration),
        yaw_change_rad=float(np.unwrap(headings)[-1] - np.unwrap(headings)[0]),
        min_upright=float(np.min(uprights)),
        final_upright=float(uprights[-1]),
        jam_frames=int(np.sum(jam)),
        target_rejections=int(np.sum(rejections)),
        contact_fraction=[float(value) for value in np.mean(contacts, axis=0)],
        mean_contact_slip_squared_m2_s2=float(np.mean(slip)),
        maximum_normalized_action=float(np.abs(actions).max()),
        mean_reward=float(np.mean(rewards)),
        reward_sum=float(np.sum(rewards)),
        elapsed_wall_s=time.monotonic() - started,
        generator=Path(__file__).resolve().name,
        generator_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        demonstration_sha256=hashlib.sha256(demonstration.read_bytes()).hexdigest(),
        assumptions=["component mass distribution", "servo torque and gains",
                     "friction", "no calibrated vision noise model"],
        physical_qualification=False,
    )
    sidecar_path = out_dir / f"{identifier}.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2, allow_nan=False))
    return sidecar


def case_from_args(args, reference_sidecar):
    """Search parameters plus the reference amplitudes they scale against."""
    reference = reference_sidecar["case"]
    identifier = args.id or "guided-p%s-s%g-x%g-y%g-l%g" % (
        args.period, args.stride, args.lean_x, args.lean_y, args.lift)
    return dict(
        id=identifier, period=args.period, stride=args.stride, lean_x=args.lean_x,
        lean_y=args.lean_y, lift=args.lift, duration_s=args.duration,
        order=args.order, reference_stride=reference["stride"],
        reference_lean_y=reference["lean_y"], reference_lift=reference["lift"],
        waveform_reference=reference["id"], seed=args.seed,
        scenario_id=args.scenario,
    )


def build_config(base, command, duration):
    """The consuming run's environment contract, with only command and length changed.

    `base` is normally the training run's own `environment.json` rather than the
    reference sidecar: `load_demonstrations` requires a demonstration's environment
    to equal the training config apart from `episode_seconds` and `command`, and the
    version-7 reference sidecars predate several current fields.
    """
    environment = dict(base)
    environment["command"] = list(command)
    environment["episode_seconds"] = float(duration)
    return EnvironmentConfig(**environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", default=str(GUIDED_STEPS / f"{DEFAULT_REFERENCE}.npz"))
    parser.add_argument("--base-config",
                        help="environment.json of the run that will consume these "
                             "demonstrations; defaults to the reference sidecar")
    parser.add_argument("--out-dir", default=str(GUIDED_STEPS))
    parser.add_argument("--id")
    parser.add_argument("--period", type=float, default=2.5)
    parser.add_argument("--stride", type=float, default=40.0, help="peak-to-peak foot sweep, mm")
    parser.add_argument("--lean-x", type=float, default=0.0)
    parser.add_argument("--lean-y", type=float, default=16.0)
    parser.add_argument("--lift", type=float, default=25.0)
    parser.add_argument("--duration", type=float, default=16.0)
    parser.add_argument("--order", type=float, nargs=4, default=[0.75, 0.25, 0.5, 0.0])
    parser.add_argument("--command", type=float, nargs=3, default=[0.08, 0.0, 0.0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--scenario", help="Configured starting scenario to record explicitly")
    parser.add_argument("--verify", action="store_true",
                        help="regenerate the reference case and report the offset error")
    args = parser.parse_args(argv)

    sidecar, arrays = reference_case(args.reference)
    reference = sidecar["case"]
    waveform = steady_waveform(arrays, reference["order"], reference["period"],
                               sidecar["environment"]["control_hz"])
    if args.verify:
        steps = len(arrays["requested_offset_mm"])
        rendered = render_offsets(steps, waveform, reference["order"], (1., 1., 1.), 0.,
                                  waveform["cycle"])
        delta = np.abs(rendered - arrays["requested_offset_mm"])
        # The startup cycle is reported separately: it is the one place a small
        # residual is expected, because the ramp multiplies a waveform recovered
        # from steady cycles only.
        cycle = waveform["cycle"]
        print("reference           : %s" % reference["id"])
        print("steps compared      : %d" % steps)
        print("max offset error    : %.6f mm" % delta.max())
        print("mean offset error   : %.6f mm" % delta.mean())
        print("per-axis max error  : %s mm" % np.round(delta.max(axis=(0, 1)), 6).tolist())
        print("steady cycles only  : max %.6f mm, mean %.6f mm"
              % (delta[cycle:].max(), delta[cycle:].mean()))
        # 0.5 mm is about 1% of the 40 mm stride: below it the residual is linear
        # interpolation across a waveform corner, which cannot change the contact
        # sequence. The asymmetric turn references sit near 0.16 mm for that reason.
        print("RECONSTRUCTION      : %s" % ("EXACT" if delta.max() < 1e-6 else
                                            "faithful" if delta.max() < 0.5 else "DIVERGENT"))
        return 0

    case = case_from_args(args, sidecar)
    base = (json.loads(Path(args.base_config).read_text()) if args.base_config
            else sidecar["environment"])
    config = build_config(base, args.command, args.duration)
    result = generate(case, config, waveform, args.out_dir)
    print("%-46s fwd=%+7.1f mm/s  min_upr=%.4f  max|action|=%.3f  cycle_rows=%s"
          % (result["id"], result["mean_forward_m_s"] * 1000, result["min_upright"],
             result["maximum_normalized_action"], result["recommended_cycle_rows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
