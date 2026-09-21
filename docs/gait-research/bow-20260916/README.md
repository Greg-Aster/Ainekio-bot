# Bow — twelve-servo motion reference

The robot braces its stance, stretches both front forelegs forward as it bows while keeping the rear raised,
holds the bow for **three seconds**, then returns to standing. The complete
Blender demonstration is **8.5 seconds**, using the existing V1 Bow face.

## Original eight-servo reference

`reference-v1-bow.json` is the unmodified Bow entry from
`Slave/software/assets/seed/motions-v1.json`. `reference-v1-joints.json` supplies
its joint labels. The V1 sequence is:

1. Standing targets, 360 ms.
2. Stance setup, 760 ms: R1=180°, R2=0°, L1=0°, L2=180°;
   rear lower R4=0°/L4=180° and front lower R3=180°/L3=0°.
3. Bow phase, 3040 ms: front lower **R3 and L3 both target 90°**.
4. Return to the recorded standing targets, 160 ms; restore the Stand face.

The project asset-conversion code identifies R3/L3 as the front pair. This V2
adaptation retains the front-leg stretch, front-low/rear-high shape, sustained bow, and return. The first front-dip revision omitted the stretch and is superseded; its live file is preserved as `Before-Bow-Front-Stretch.blend` and source under `superseded-front-dip/`.
Its explicit approach/hold/return durations are demonstration choices, not a
one-to-one reproduction of V1's electrical timing. The twelve-servo mechanism
uses different joints and geometry, so none of the eight electrical target
angles is directly copied into the twelve geometric joint coordinates.

## Blender and sequence

- Working file: `/home/greggles/blender-5.0.0-linux-x64/robot-bow-20260916/Ainekio-Bow.blend`
- Preserved live source, including unsaved edits: `Before-Bow.blend` in the same directory.
- Bow frames: **2881–3085**, after deep Pushup ends at 2857.
- Full preview: `bow-preview.mp4`; held pose: `bow-preview.png`.

| Source time | Action |
| --- | --- |
| 0–1 s | Settle into the braced stance |
| 1–2.5 s | Reach front soles forward 20 mm while shifting the body back and bowing |
| 2.5–5.5 s | Hold the bow |
| 5.5–7 s | Reverse the reach and raise the front through the braced stance |
| 7–8 s | Return to exact standing |
| 8–8.5 s | Standing hold, retained after completion |

Bracing places the body datum at **[0, 0, 76] mm**. The held bow uses
**[-10, 0, 70] mm** and XYZ Euler angles **[0, +12, 0] degrees**. Positive body
pitch lowers the front. The front-body datum [75, 0, 0] drops
**26.555 mm** from standing. The rear remains raised.
The symmetric bow keeps shoulders at neutral; carriers/Part006 and
cranks/Part005 produce the posture together. At the hold, both front carriers are **−32.824°** and cranks **−45.915°** in geometric coordinates. This rotates the lower forelegs close to horizontal; Part023 remains just behind vertical in body coordinates.

All four soles remain grounded. Both front soles intentionally slide **20 mm forward** during the stretch and reverse on return. Rear material contacts remain fixed between rolling feature transfers. The convex-sole model logs vertical transfer corrections. `prescribed_front_slide_mm` records the slide in JSON/CSV; JSON also labels each contact motion. Sliding friction and the load distribution are unverified, so this motion is a kinematic gesture reference. The reported material-contact error is relative to the prescribed moving anchors, not a zero-slip claim. Returning exactly reverses the solved approach. Passive
linkage angles are determined by four-bar closure throughout. No part was
mirrored/remodeled and no independent angle clamp was used.

## Source and firmware handoff

`source.json` and `source.csv` contain **1021 samples at 120 Hz**. CSV has 62
named columns including time in seconds and integer microseconds, body pose,
all twelve actuator angles, foot-bolt and sole positions, contacts and support
margin. JSON additionally includes passive angles and supporting sole vertices.
Positions are mm, joint angles signed geometric radians, quaternion order wxyz.
World/body axes: X forward, Y left, Z up. Blender metric scale 0.001 means one
model unit is one millimeter.

| CAD leg | Physical leg | Flat indices |
| --- | --- | --- |
| FL | Rear-left | 0–2 |
| FR | Rear-right | 3–5 |
| RL | Front-left | 6–8 |
| RR | Front-right | 9–11 |

Every triplet is **h/Part002 shoulder, alpha/Part006 carrier,
theta/Part005 crank**. `schema.json` specifies coordinates and ordering;
`manifest.json` binds sources, geometry and face bitmaps with SHA-256 hashes.

Semantic command: `{"t":"intent","name":"emote","asset":"bow"}`.
`execution-contract.json` provides six phases, contacts, entry/exit poses and
editable timing, using the same `execution-policy.json` as prior commands.
All joints, body, feet and face cues share one trajectory clock. PWM phase offsets
and initial servo engagement remain separate firmware concerns; independent
motion-track delays would alter contacts and require a new trajectory evaluation.

Demonstration timing is recorded. Operating timing and physical servo calibration
remain unconfigured. Entry from an arbitrary pose is not provided. For
interruption, retain coordinated four-foot support and raise the front along the
recorded return path before standing; never jump to the last sample. The original
Bow face bitmap is retained, with Stand restored at 8 seconds.

## Focused validation

- **14 evaluated Blender poses**, including subframes: maximum linkage
  connection error **0.0000333 mm**, foot prediction error
  **0.0000279 mm**.
- Lowest evaluated sole Z **-0.0000416 mm**, numerical floor residue.
  Rigid body samples retain **3.094 mm** minimum clearance.
- Minimum assumed-COM support margin **29.477 mm**. COM is
  assumed at the body datum; moving-leg mass effects are not modeled. Battery
  and optional Q6A mass/placement remain configurable.
- Maximum rolling normal correction **0.000607 mm**;
  prescribed material-contact error **1.34e-13 mm**.
- All configured research angle ranges pass. Final joint return error is zero.
  Maximum adjacent source step is **0.4388°**.
- Peak interpolated demand **52.671°/s** and
  **139.199°/s²**. All 1020 interpolation intervals
  have bounded midpoints, with continuous position/velocity. Full acceleration
  continuity is not established.
- All 298 compared model meshes are unchanged. Prior 60 animation curves match
  at 14 sampled frames, including Nod and deep Pushup.

The pre-existing `CRAWL | Face - OV5647 Camera - 25x24 reference` still flags
full-scene floor clearance at −2.2 mm. The reference is preserved; complete-model
floor clearance is not a pass. Leg-sole checks are reported independently.
Full collisions, wiring clearance, measured COM, calibrated joint travel, loaded
servo capability and electrical/brownout behavior remain unverified. A positive
kinematic support margin is not physical stability proof. Measure those hardware
properties before implementation on the robot.

Detailed reports: `validation.json`, `blender-validation.json`,
`interpolation-validation.json`, `preservation-validation.json`.
No firmware, gateway, Body Control code or V1 assets were changed.

## Reproduce

From this package directory, with Python 3 and NumPy:

```bash
python3 generate_bow.py
python3 export_bow.py
python3 timing.py execution-contract.json --profile research_candidate --scale 2 --time 2
```

The timing example is an unqualified **4.25-second offline candidate**; speeds
scale by two and accelerations by four. Edit `config.json` for geometry/timing
research; infeasible trajectories raise an error.

Open `Before-Bow.blend`, then in Blender's Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-bow-20260916/apply_bow.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

The script appends Bow and saves its working copy. `check_blender.py` compares
evaluated geometry; `render_preview.py` creates a preview in background Blender.
The portable ZIP includes source, scripts, measured geometry, preview and timing
contract. Larger Blender files remain in the workspace.
