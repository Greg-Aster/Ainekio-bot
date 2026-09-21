# Pushup — deep rear crouch

The original shallow sequence has been preserved separately as **Nod**.
This revised Pushup lowers **both rear legs into a near-bottom crouch** before
five coordinated front-leg presses. Timing remains **14.5 seconds**.

## Files and timeline

- Current Blender: `/home/greggles/blender-5.0.0-linux-x64/robot-pushup-deep-20260916/Ainekio-Pushup.blend`
- Preserved starting scene: `Before-Deep-Pushup.blend` in the same directory.
- Nod: frames **2137–2485**, preserved unchanged.
- Deep Pushup: frames **2509–2857**, appended after Nod.
- Full preview: `pushup-preview.mp4`; source: `source.json` and `source.csv`.
- Reproducible generator/configuration: `generate_pushup.py`, `config.json`.
- Independent firmware contract: `execution-contract.json`.

## Motion and depth

| Source time | Action |
| --- | --- |
| 0–2 s | Crouch both rear legs |
| 2–12 s | Five repetitions, each 1 s lowering and 1 s pressing up |
| 12–14 s | Return through the crouch transition to standing |
| 14–14.5 s | Recorded standing hold, retained after completion |

The raised crouch body datum is **[−8, 0, 62.8] mm**, with XYZ Euler angles
**[0, −27.5, 0] degrees**. Both rear shoulder-axis centers descend to
**27.545 mm above the floor**. They remain between
**27.545 and 34.911 mm** during the presses.
The rear carriers reach **67.297°**, close to the current
**67.4° research bound**. Minimum rigid-body sample clearance is
**1.385 mm**.

This is a near-bottom *research pose*, not a calibrated physical maximum.
`stance-candidates.json` records the tested alternatives: several lower or more
inclined poses reached the body-floor or carrier-angle boundary and were rejected.
No component was remodeled or mirrored to obtain the stance.

During presses the pitch changes between **−27.5° and −10.5°**, about the
research body-local construction point **[−50, 0, 0] mm**. This point is not an
additional physical joint. Front-body datum **[75, 0, 0] mm** travels vertically
by **34.939 mm**, compared with 36.833 mm in Nod. Both front legs
still work together; rear joints accommodate body pitch while keeping the rear
stance low. All four soles remain grounded. The upward path reverses the solved
downward path exactly, so repeats accumulate no contact drift.

## Coordinates and execution

Source positions are millimeters, angles signed geometric radians, time seconds.
CSV additionally supplies integer microsecond timestamps. Body axes: X forward,
Y left, Z up; quaternion wxyz. Blender metric scale 0.001 means one model unit is
one millimeter. Each source has **1741 samples at 120 Hz**.

| CAD leg | Physical leg | Flat joint indices |
| --- | --- | --- |
| FL | Rear-left | 0–2 |
| FR | Rear-right | 3–5 |
| RL | Front-left | 6–8 |
| RR | Front-right | 9–11 |

Each triplet is **h/Part002 shoulder, alpha/Part006 carrier,
theta/Part005 input crank**. Passive linkage angles follow four-bar closure.
The parameters and sole hulls retain the measured leg geometry. The body sample
provenance and neutral/rig snapshots are included for reproducibility.

Keep semantic command `{"t":"intent","name":"emote","asset":"pushup"}`.
The 13-phase contract contains entry/completion poses, contacts, source hashes,
phase speeds/accelerations and editable timing profiles. Demonstration timing is
recorded. Operating timing, electrical centers and servo travel remain uncalibrated.
One trajectory clock coordinates all twelve joints, body, contacts and face cues.
The existing Pushup face is retained, with Stand restored at 14 seconds.

PWM pulse staggering and controlled initial engagement follow the shared
`execution-policy.json` independently of geometric trajectory time. Do not
independently delay joint tracks. Entry from arbitrary poses is not provided;
on interruption, return along the coordinated path through the raised crouch
before standing. The full finite command includes all five repetitions.

## Focused results and limits

- 16 evaluated Blender poses including subframes: maximum four-bar joint
  connection error **0.0000335 mm**, foot prediction error
  **0.0000380 mm**.
- Minimum evaluated sole Z **-0.0000493 mm**, numerical floor residue.
- Minimum assumed-COM support margin **35.586 mm**. COM is
  assumed at the body datum; moving-leg mass effects are not modeled. Battery
  and optional Q6A mass/placement remain configurable.
- All five cycles have identical joint samples, all four contacts stay active,
  and final standing joint error is zero.
- Maximum sampled rolling normal correction **0.000404 mm**;
  planted material-contact error **9.81e-14 mm**.
- Peak interpolated demand **117.545°/s** and
  **648.903°/s²**. Monotone Hermite interpolation has
  bounded interval midpoints and continuous position/velocity. Full acceleration
  continuity is not established.
- All 298 compared model meshes are unchanged; earlier 60 animation curves match
  at 12 sampled frames, including the preserved Nod sequence.

The existing `CRAWL | Face - OV5647 Camera - 25x24 reference` still flags the
full-scene floor check at −2.2 mm. That reference is preserved; complete-model
floor clearance is not a pass. Leg-sole results are reported independently.
Full collisions, wiring clearance, measured masses, calibrated travel and loaded
servo/electrical capability are **unverified**. Before hardware execution,
measure those limits and current/voltage under load. Kinematic support margin
does not establish physical stability.

Detailed files: `validation.json`, `blender-validation.json`,
`interpolation-validation.json`, `depth-and-repeat-validation.json`,
`preservation-validation.json`, `stance-candidates.json`.
No firmware, gateway, Body Control code or V1 assets were changed.

## Reproduce

With Python 3 and NumPy, from this package directory:

```bash
python3 generate_pushup.py
python3 export_pushup.py
python3 timing.py execution-contract.json --profile research_candidate --scale 2 --time 3
```

The timing example is a **7.25-second offline candidate**, not a qualified
operating profile. It doubles speeds and quadruples accelerations.

Open `Before-Deep-Pushup.blend` or the saved Nod file, then in Blender:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-pushup-deep-20260916/apply_pushup.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

The script appends the new Pushup and saves its working copy. Configuration
controls rear stance, pitch range, repetitions and timing. Invalid trajectories
raise an error; angles are not independently clamped. `check_blender.py` compares
evaluated geometry, and `render_preview.py` renders in background Blender.
The portable ZIP includes scripts, geometry, source data, preview and timing
contract. Large Blender files remain in the workspace.
