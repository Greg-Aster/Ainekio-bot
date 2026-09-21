# Point — twelve-servo motion reference

Created 2026-09-16 from the live **Ainekio-Swim.blend** scene, preserving the
current model and previous animations. This adapts the existing eight-servo
`point` command to the user's requested rear-leg crouch followed by a raised,
extended front leg. It is a finite **11-second demonstration**.

## Blender and preview

- Working copy: `/home/greggles/blender-5.0.0-linux-x64/robot-point-20260916/Ainekio-Point.blend`
- Preserved live source: `Before-Point.blend` in the same directory.
- Point frames **1849–2113**, after Swim ends at 1825.
- `point-preview.mp4`: full 11-second preview. `point-preview.png`: held point.
- Contact markers, the support triangle, projected assumed COM and sole paths
  remain visible. The original three-frame Point face plays in boomerang order
  `0,1,2,1` at 2 fps, with the Stand face restored at 10.4 seconds.

## Motion

| Time (s) | Action |
| --- | --- |
| 0–2 | Shift rearward/right and crouch toward the rear-right leg with four feet down |
| 2–3 | Raise the front-left leg with its shoulder; keep three supporting contacts |
| 3–4.2 | Extend the carrier and crank into the forward point |
| 4.2–6.2 | Hold the pointing pose |
| 6.2–7.4 | Retract the arm |
| 7.4–8.4 | Replace the front-left foot |
| 8.4–10.4 | Retrace the body shift and crouch to standing |
| 10.4–11 | Hold standing; retain this endpoint after command completion |

The crouched body datum is **[-18, -16, 73] mm** in world coordinates, with
Euler XYZ **[8, -13, 0] degrees**. Negative pitch raises the front; positive roll
lowers the right side. The rear-right carrier moves about +20.88° and its input
crank about −22.45° during this preparation, while the other legs accommodate
the body shift. The front-left foot lifts only after that preparation completes.

The pointing arm first raises the shoulder to **40°**, then reaches a held
geometric pose **[h, alpha, theta] = [35, -100, -48] degrees**. Its foot-bolt
position is approximately **[122.11, 50.01, 117.13] mm** in world coordinates.
Reach from pivot O to the foot bolt is now **97.20 mm**, compared with
**70.05 mm** in the first Point version; the foot is **31.66 mm farther forward**.
The carrier and distal link retain approximately **27.74°** of bend. This is an
extended airborne gesture: the Part006 research lower bound is −100° for the
lifted pointing arm, while every grounded leg retains the prior −34.24° carrier
bound. The expanded airborne range is not a measured servo stop or collision
limit. The lower linkage follows four-bar closure throughout; it has no independent
actuator. This is a fixed forward-point gesture, with a configurable joint pose.
It does not provide arbitrary target tracking.

## Coordinates and source ownership

World/body axes: **X forward, Y left, Z up**. Position units are millimeters;
source actuator angles are signed geometric radians; time is seconds.
Blender uses metric units at scale 0.001: one model unit is one millimeter.

| Source CAD leg | Physical leg | Flat joint indices |
| --- | --- | --- |
| FL | Rear-left | 0, 1, 2 |
| FR | Rear-right — crouch bias | 3, 4, 5 |
| RL | Front-left — pointing arm | 6, 7, 8 |
| RR | Front-right | 9, 10, 11 |

Each triplet is **h / Part002 shoulder, alpha / Part006 upper carrier,
theta / Part005 input crank**. These values are relative to the corrected CAD
neutral, including its existing Part005 re-clocking. They are not servo horn
angles, PWM pulse widths or calibrated electrical centers.

`source.json` contains **1321 samples at 120 Hz** with body pose, all twelve
actuator angles, passive linkage angles, foot-bolt positions, actual sole
clearance, contact states, contact vertices and assumed COM/support margins.
`source.csv` provides 61 explicitly named columns and integer microsecond
timestamps. `schema.json` defines units and ordering. `manifest.json` binds
source, geometry and face files by SHA-256.

The supplied `robot-gait-parameters.json`, `sole-hulls.npz` and
`body-samples.npz` retain the geometry used by Swim. The motion changes no mesh data. At final comparison, 294 of the original
296 meshes were unchanged; the front end panel had been edited and the old
2-inch LCD reference removed during concurrent live work. Those current edits
are preserved in the working copy. The measured leg geometry remains unchanged.
Body sample geometry therefore represents the pre-edit research snapshot,
not a new measurement of the revised face/panel.

## Firmware and timing handoff

Keep the existing semantic command: `{"t":"intent","name":"emote","asset":"point"}`.
V1's recorded targets and sequential timing are included in
`reference-v1-point.json` as provenance. Do not copy its eight electrical angles
into this twelve-joint model.

`execution-contract.json` defines eight motion phases, supporting legs, contact
events, source hashes, entry/exit poses, reference speeds and accelerations.
Use `timing.py` and the shared `execution-policy.json` for adjustable phase
durations and one coordinated motion clock. The demonstration profile is
recorded; operating durations and loaded actuator limits remain unconfigured.

All supporting legs, body pose and the pointing arm share source time.
Firmware PWM phase scheduling and controlled initial engagement remain separate
from the trajectory. Do not stagger the geometric joint tracks independently:
that would alter contacts and require a new motion evaluation. No power-spike
or brownout performance is claimed by these files.

The entry pose is standing neutral, not an arbitrary current posture. On
interruption, retain the three-foot support posture while retracting and
replacing the pointing foot before standing. Do not seek directly to the last
sample. `sample_reference.py` returns signed geometric centidegrees and their
derivatives as an offline porting example, not electrical servo values.

```bash
python3 timing.py execution-contract.json --profile research_candidate --scale 2 --time 2
```

This produces a 5.5-second offline candidate; it is not a qualified operating
speed. Speed scales by two and acceleration by four under that time scaling.
No firmware, gateway, Body Control implementation or V1 motion asset is changed.

## Focused validation

- **15 evaluated Blender poses**, including subframes: maximum joint connection
  error **0.0000360 mm**, maximum foot prediction error **0.0000270 mm**.
- Lowest evaluated sole Z **−0.0000246 mm**, numerical floor residue; source-sampled body
  clearance stays at least **23.210 mm**. The evaluated full-scene snapshot also
  included a camera reference below the floor (see the limitation below).
- Minimum assumed-COM support margin **24.858 mm**, including the three-foot
  pointing segment. The COM is explicitly assumed at the body datum. Config
  retains optional measured base mass, battery and Q6A payload placement.
- Contact model: discrete rolling over measured convex sole features while
  crouching, fixed material contacts during the arm gesture, then retracing.
  Largest feature-transfer vertical correction **0.002404 mm**; sampled planted
  material-contact error below **1.2e-13 mm**. This does not imply a rounded sole
  maintains the same surface contact point as it rolls.
- All configured research joint bounds pass, including the separate airborne carrier range; maximum adjacent source step
  **1.1645°**. Monotone Hermite interpolation has bounded interval midpoints;
  position and velocity are continuous. Full acceleration continuity is not
  established.
- Peak interpolated demand: **139.755°/s**, **384.584°/s²**. Final joint angles
  return exactly to standing neutral, and sampling beyond completion holds it.
- Earlier 60 animation curves match at seven sampled frames through Swim;
  294 model meshes retain their vertex hashes. The final preservation report
  records the concurrently edited front end panel and removed LCD reference;
  both current changes are retained.

One full-scene floor check in the saved revision found the object
`CRAWL | Face - OV5647 Camera - 25x24 reference` at **−2.2 mm**. A subsequent
live inspection found that reference hidden for viewport and rendering. This
reference/edit state is preserved; the complete-model floor check is therefore
not reported as passing. All evaluated leg soles still meet the ground tolerance.

Full collisions, wiring clearance, mechanical/electrical stops, measured mass
distribution, load-bearing servo performance and electrical capability remain
**unverified**. The assumed COM excludes moving-leg mass effects. A positive
kinematic support margin does not establish physical balance. Next hardware
inputs are per-joint calibration and travel, actual COM/payload placement,
loaded speed/current and clearance observations in this pose.

Detailed results: `validation.json`, `blender-validation.json`,
`interpolation-validation.json` and `preservation-validation.json`.

## Reproduce

With Python 3 and NumPy, from this source directory:

```bash
python3 generate_point.py
python3 export_point.py
```

The generator reads `config.json`; edit it to refine stance, pointing angles or
timing. Invalid source trajectories raise an error instead of clamping joints.
Open the preserved `Before-Point.blend` after saving other work. In Blender's
Python console, run:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-point-20260916/apply_point.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

The script appends Point and saves its own working copy. `check_blender.py`
compares evaluated geometry against the solver; `render_preview.py` creates the
preview in background Blender. The first Point version is preserved in `Before-Point-Extended.blend`,
`first-point/` in the workspace, and the included
`first-point/ainekio-point-initial-12servo-20260916.zip` reference bundle.
`point-variants.json` records both poses and their reach.
The current ZIP contains source, data, scripts, face
bitmaps and preview; the larger Blender files remain in the workspace.
