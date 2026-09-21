# Turn-source integration handoff

## Requested commands

Implement the model-specific assets listed in `catalog.json`: `turn_left_180`, `turn_right_180`, `turn_left_90`, `turn_right_90`, `turn_left_45`, `turn_right_45`, and the new `turn_left_15` / `turn_right_15`.

Keep the existing semantic envelope:

```json
{"t":"intent","name":"emote","asset":"turn_left_15"}
```

The gateway adds sequence/session/deadline fields under its existing protocol. The robot resolves the semantic asset to its own twelve-servo model source. A left turn is positive yaw about world Z; right is negative, viewed from above. The opposite heading is exactly ±180° in the geometric animation. Physical yaw needs calibration and measurement.

## Canonical integration owners, checked 2026-09-15

- `Master/gateway/environment_adapter/translation.py`: existing semantic catalog, aliases and descriptions. Add the two 15° names here when implementing them; do not create a separate MetaHuman catalog.
- `Master/gateway/body_capabilities.py`: per-body command selection, using `body_commands_v1`, the explicit installed list and `motion` readiness. The current V2 execution gate remains false.
- `Slave/software/models/v2-12servo/`: twelve-joint definition, geometry and model-owned motion sampling. It already contains the forward-walk sampler. Import these independent turn assets here as part of firmware integration.
- `Slave/software/core/`: common protocol and admission/lifecycle. Reuse semantic `emote` decoding; do not globally change the eight-servo V1 structures into twelve-servo arrays.
- `Slave/firmware/esp32p4-wifi6/main/controller.c`: native controller admission, capability advertisement and eventual calibrated actuator execution. Keep the existing readiness/stop paths.

These paths describe the current repository state; this research package does not modify those owners. Coordinate with concurrent firmware work before importing assets.

## Twelve-joint layout

| Indices | CAD leg | Physical leg | Joint order |
| --- | --- | --- | --- |
| 0–2 | FL | rear left | shoulder h / Part002; carrier alpha / Part006; crank theta / Part005 |
| 3–5 | FR | rear right | h, alpha, theta |
| 6–8 | RL | front left | h, alpha, theta |
| 9–11 | RR | front right | h, alpha, theta |

Source angles are **signed geometric radians**, relative to corrected CAD neutral. Positive h is about body +X; positive alpha/theta is about body +Y. The Part005 neutral re-clocking is included already. Convert to CAD centidegrees with `radians * 180/pi * 100` only if the existing V2 sampler API requires it. This is not conversion to electrical servo angles or pulse widths. Electrical channel assignment, zero, sign, travel and pulse mapping must come from actual calibration.

The lower linkage is passive. Use the twelve actuator columns only; `passive_beta_rad` is a mechanism diagnostic. Each leg retains its four-bar assembly branch and measured link lengths. The current measured couplers are 40 mm on all four legs. `robot-gait-parameters.json` and `sole-hulls.npz` are the geometry used for these sources.

## Timing and interpolation

Every command has a full independent source, including entry and exit; do not crop the 180° joint tracks to obtain a smaller turn. A smaller angle has different yaw targets and newly solved foot placements.

1. Select the source by semantic command and body model.
2. Use a local monotonic elapsed clock. At 120 Hz, `elapsed_us * 120 / 1_000_000` gives the segment index and fraction without accumulating rounded 8,333 µs intervals.
3. Evaluate all twelve positions together using the provided monotone cubic Hermite convention. Interior tangent = `2*a*b/(a+b)` when adjacent secants have the same sign; otherwise zero. Start/end tangents are zero. See `sample_reference.py` for an executable reference.
4. After the duration, hold the last recorded pose. There is no wrap, repeat, extra held source row, or instantaneous reset to geometric zero.
5. Issue lifecycle completion only from the real executor. Geometric sampling alone must not emit a physical-motion `done` claim.

All sources start from the same CAD standing pose. Their final poses differ slightly from neutral because the measured sole rolls. **Current-pose entry, transitions from walking/other commands, and interrupted-command braking/hold remain integration work.** Do not play the first frame over an arbitrary pose. Repeated commands must preserve the robot's actual accumulated heading; the world pose in each research file is relative to that command's initial heading.

## Contact and balance assumptions

Foot targets are attachment-bolt references; actual ground/clearance checks use the evaluated sole. Stance holds a material sole vertex fixed in world coordinates until the supporting feature changes. Small normal corrections at feature transfers are logged. The point-contact model permits yaw rotation about the support point; it does not prove available friction or acceptable torsional scrub.

Body COM is explicitly assumed at the body datum. Battery and optional Q6A masses/placement remain configurable; their unknown masses are not invented. Negative support margins, existing mount interference and unmeasured loads mean this package must stay hardware-unqualified until the appropriate measurements and refinements are complete.

## Evidence to retain with an imported asset

Each folder includes provenance hashes, all body/foot/contact tracks, the twelve angles, terminal pose, sampled limits/demands, cubic interpolation demands, and evaluated Blender checks. Retain those alongside the imported source. The model/mesh preservation check includes saved-file reopen, original test animations and intended mount objects.

The 15° commands have no existing eight-servo counterpart in the current catalog. Decide their V1 availability independently; adding a V2 semantic name must not advertise an unimplemented V1 asset.
