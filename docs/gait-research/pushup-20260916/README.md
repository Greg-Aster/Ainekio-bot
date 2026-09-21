# Pushup — twelve-servo motion reference

Generated 2026-09-16 from the live Ainekio-Point scene, including unsaved edits.
The robot first crouches toward its rear-right leg, then performs **five
pushups with both front legs working together**, and returns to standing.

## Deliverables

- Saved Blender: `/home/greggles/blender-5.0.0-linux-x64/robot-pushup-20260916/Ainekio-Pushup.blend`
- Preserved live source: `Before-Pushup.blend` in the same workspace directory.
- Timeline: **2137–2485**, appended after Point ends at 2113.
- `pushup-preview.mp4`: full **14.5-second** demonstration.
- `source.json`, `source.csv`: **1741 samples at 120 Hz**, 61 CSV columns.
- `config.json`, `generate_pushup.py`, `apply_pushup.py`: editable settings and reproducible generator/application.
- `robot-gait-parameters.json`, `sole-hulls.npz`: current unchanged leg geometry.
- `body-samples.npz`, `body-sample-provenance.json`: refreshed body geometry from the preserved current scene.
- `manifest.json`, `schema.json`, `execution-contract.json`: source hashes, units, joint ordering, contact events and phase timing.

## Sequence

| Source time | Motion |
| --- | --- |
| 0–2 s | Crouch toward rear-right with all four feet supported |
| 2–12 s | Five repetitions: 1 second lowering, 1 second pressing up |
| 12–14 s | Reverse the crouch into exact standing |
| 14–14.5 s | Recorded standing hold; retain endpoint afterward |

The raised crouch puts the body datum at **[0, −8, 78] mm**, with XYZ Euler
rotation **[4, −12, 0] degrees**. The right-side bias increases rear-right
carrier rotation to about **35.13°**, compared with **22.70°** rear-left.
Both rear legs contribute support; rear-right is the deliberate crouch bias.

During repetitions, body pitch varies from **−12° to +5°** about a fixed
research pivot at body-local **[−50, −40, 0] mm**. This is a trajectory construction
point, not a new physical joint. The front body datum at **[75, 0, 0] mm** moves
vertically by **36.833 mm**. The front legs bend and straighten
together; rear joints accommodate pitch while maintaining their grounded stance.

All four soles stay grounded. The contact model holds a measured sole material
vertex fixed until a supporting-feature change, then makes a logged vertical
rolling correction. The upward path exactly reverses the solved downward path;
repetitions reuse it without accumulating contact drift. The passive linkage
orientation always comes from four-bar closure. No servo angle is independently
clamped to force an infeasible target.

The original V1 Pushup face bitmap plays once at the start. The Stand face is
restored at 14 seconds. Sole paths, active contacts, the support polygon and
projected assumed COM remain available in the viewport.

## Coordinates and firmware handoff

| CAD leg | Physical leg | Flat indices |
| --- | --- | --- |
| FL | Rear-left | 0–2 |
| FR | Rear-right | 3–5 |
| RL | Front-left | 6–8 |
| RR | Front-right | 9–11 |

Each triplet is **h / Part002 shoulder, alpha / Part006 carrier, theta / Part005
input crank**. World axes are X forward, Y left, Z up. Source positions are mm,
angles are signed geometric radians and time is seconds; CSV also supplies
integer microsecond timestamps. Body quaternion order is wxyz. Blender's metric
scale is 0.001, meaning one model unit is one millimeter.

Keep the existing semantic command:
`{"t":"intent","name":"emote","asset":"pushup"}`.
`reference-v1-pushup.json` records the old eight-servo gesture and face cues as
provenance. Its electrical targets and sequential timing are not copied to the
twelve-joint mechanism. The V2 export remains in corrected CAD joint coordinates
until horn centers, directions and pulse calibration are measured.

The execution contract has 13 phases, entry and final standing poses, four-foot
contact states and source-bound speeds/accelerations. It uses the existing shared
coordination and engagement policy: one trajectory clock for all joints, body,
feet and face cues. Firmware PWM phase offsets and controlled initial engagement
are separate from geometric trajectory timing. Do not independently delay joint
tracks to manage current; doing so would change the planned contacts.

Demonstration timing is recorded. Research phase durations are editable;
operating timing and loaded servo limits are unconfigured. For an offline
7.25-second time-scaled candidate:

```bash
python3 timing.py execution-contract.json --profile research_candidate --scale 2 --time 3
```

This doubles speeds and quadruples accelerations; it is not a hardware-qualified
operating profile. Entry from an arbitrary current pose is not provided. For
interruption, retain coordinated support, return through the raised crouch and
then stand; do not jump to the final sample. The finite command contains all five
repetitions and should execute once per request.

## Focused validation

- **16 evaluated Blender poses**, including subframes: maximum linkage
  connection error **0.0000341 mm**, foot prediction error
  **0.0000311 mm**.
- Minimum evaluated leg-sole Z **-0.0000669 mm**, numerical
  floor residue. Rigid body samples retain **7.699 mm** clearance.
- Minimum assumed-COM support margin **39.115 mm**. COM is
  explicitly assumed at the body datum; moving-leg mass effects are not modeled.
  Battery and optional Q6A mass/placement remain configurable.
- All four contacts persist; five repetitions have exactly matching joint
  samples. Final joint return error is zero.
- Largest rolling transfer normal correction **0.001005 mm**;
  sampled material-contact error **1.36e-13 mm**.
- Research joint ranges pass. Maximum adjacent sample step **0.8879°**.
  All 1740 interpolation intervals have bounded midpoints, with continuous
  position and velocity. Full acceleration continuity is not established.
- Peak interpolated demand: **106.565°/s**,
  **538.262°/s²**.
- All 298 compared model meshes retain their vertex hashes. Earlier 60 animation
  curves match at eight sampled frames, including Point.

The full-scene floor check remains flagged by the existing
`CRAWL | Face - OV5647 Camera - 25x24 reference` at **−2.2 mm**. The reference
and current model edits are preserved; the complete-model floor check is not a
pass. Leg-sole checks pass independently. No full collision check was performed.
Measured COM, mechanical/electrical travel, loaded torque/speed and power/brownout
performance remain unverified. Kinematic support margins do not prove physical
stability. Before hardware execution, measure calibration, loaded joint limits,
actual mass placement, pose clearance and current/voltage under load.

See `validation.json`, `blender-validation.json`, `interpolation-validation.json`,
`repeat-validation.json` and `preservation-validation.json` for detailed results.
No firmware, gateway, Body Control code or V1 motion assets were changed.

## Reproduce

With Python 3 and NumPy, from this package directory:

```bash
python3 generate_pushup.py
python3 export_pushup.py
```

Edit `config.json` to change crouch, body pitch, repetitions or timing. Open the
preserved `Before-Pushup.blend` after saving other work, then run in Blender's
Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-pushup-20260916/apply_pushup.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

The application saves its own working copy and preserves earlier command keys.
`check_blender.py` compares the evaluated mechanism to the solver;
`render_preview.py` renders the preview in background Blender. The ZIP contains
the portable source/data/preview; large Blender files stay in the workspace.
