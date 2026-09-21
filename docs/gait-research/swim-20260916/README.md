# Swim — twelve-servo motion

The robot lowers its belly onto the floor, turns all four shoulders outward to
90°, makes four continuous, overlapping breaststroke cycles, folds and replaces the feet,
then returns to standing. This is a belly-supported swimming gesture.

Existing command:

```json
{"t":"intent","name":"emote","asset":"swim"}
```

The original eight-servo Swim holds its lower joints at mid-pose while the four
upper joints alternate through a 45° arc four times. The twelve-servo adaptation
adapts the gesture into continuous, overlapping front-arm and rear-leg strokes,
with a quarter-cycle phase offset. Both Part005 and Part006 move through each stroke. V1 electrical angles and sequential output timing remain independent.

## Pose and timing

| Time | Action |
| --- | --- |
| 0–2.5 s | Lower with four grounded feet until the bottom cover reaches the floor |
| 2.5–4 s | Raise all shoulders outward to 90°, with the belly supporting the body |
| 4–5 s | Set the upper carriers and crank inputs to the paddle pose |
| 5–5.8 s | Ease into the continuous strokes |
| 5.8–17 s | Both pairs keep moving, with a 3-second period and quarter-cycle rear offset |
| 17–17.8 s | Ease out of the final stroke |
| 17.8–18.8 s | Fold the carriers/cranks for touchdown |
| 18.8–20.3 s | Lower shoulders and replace all four feet |
| 20.3–22.8 s | Reverse the lowering path to exact standing |
| 22.8–23.5 s | Recorded standing hold; retain this pose after completion |

During paddling:

- **Part002 / shoulder:** CAD FL and RL **+90°**; FR and RR **−90°**.
- **Part006 / upper carrier:** each pair sweeps **−20° to +25° and back**, with separate timing.
- **Part005 / four-bar input crank:** each pair bends/extends through **−15° to +45°**, phased with Part006 to form a closed stroke.
- Lower-link orientation remains determined by four-bar closure.

These are signed geometric angles. The mirrored shoulder signs raise both sides
outward; they do not mean different physical poses on left and right. The existing
Swim face appears at the start and Stand returns at 22.8 s. `config.json` exposes
amplitudes, stroke count and phase durations.

### Continuous overlap

Both front arms (CAD RL/RR) and rear legs (CAD FL/FR) move throughout the steady
swimming section. The period is **3 seconds** and the rear phase lags by
**one quarter cycle, equivalent to 0.75 seconds** at cruising speed. There are
no pair rest windows or per-cycle glide holds. Each limb's pull/kick and recovery
follow different paths through the coordinated Part006/Part005 motion.

One phase clock advances continuously across cycle boundaries. An integrated
quintic rate ramp eases only the start and end of the entire swimming section;
the phase speed stays constant during the steady portion. Pair phase offset is
intentional choreography, separate from firmware PWM staggering.

The full finite command retains its standing entry and exit. The short preview
shows **three steady cycles (9 seconds)** so the continuous movement is easy to
inspect. `Before-Continuous-Breaststroke.blend` and the `phased-breaststroke`
workspace folder preserve the preceding version with alternating activity windows.

## Blender and preservation

Saved file:
`/home/greggles/blender-5.0.0-linux-x64/robot-swim-20260916/Ainekio-Swim.blend`.
Swim is appended at **frames 1261–1825**, after Dance ends at 1237. The preview
range selects Swim. `Before-Swim.blend` preserves the previous live Dance file,
including its unsaved changes. `Before-Swim-Stroke-Refinement.blend` also preserves
the initial simple paddle. The `first-paddle` and `synchronous-two-joint-paddle`
workspace folders retain intermediate source data. Earlier Wave/Dance curves and the range-test scene
remain present. No robot geometry was remodeled or mirrored.

- [Preview](swim-preview.mp4)
- [Preview still](swim-preview.png)
- [Command manifest](manifest.json)
- [Timestamped twelve-joint CSV](source.csv)
- [Full source with body-contact polygons](source.json)
- [Timing and execution contract](execution-contract.json)

## Contact and support

The bottom-cover contact plane is measured from evaluated geometry at the prior
Dance standing endpoint, frame 1237. That active-animation pose defines a body
datum height of **25.250007 mm** when the bottom cover touches world Z=0.
`body-sample-provenance.json` records the extraction pose. Frame 1 belongs to the
earlier range-test setup and is not used to infer the active rig's support height.

During lowering and standing, the measured convex soles follow the existing
rolling-contact model. During shoulder lift and paddling, the body stays fixed
on its measured bottom-cover footprint. Each raised foot has
`contact_active=false`; its `contact_world_mm` field then identifies the lowest
sole point, **not** a ground-support contact. Additional source fields are:

- `body_contact_active`: whether the bottom cover supports the body.
- `support_source`: `feet`, `belly_and_feet`, or `belly`.
- `body_contact_polygon_world_mm`: measured bottom-cover footprint while active.

The viewport hides airborne foot contact markers and foot support polygons,
and shows an amber bottom-cover support polygon. COM remains explicitly assumed
at the body datum. Cover strength, contact load distribution, friction and
dynamic stability are unverified; no buoyancy or water model is used.

## Firmware handoff

The source contains **2821 samples at 120 Hz**, including body pose, twelve
actuator angles, passive linkage angles, foot positions, sole/contact states,
body support state and assumed COM. Leg-major order is CAD **FL, FR, RL, RR**,
each **h/Part002, alpha/Part006, theta/Part005**. CAD FL/FR are physical
rear-left/rear-right; RL/RR are front-left/front-right.

World axes: X forward, Y left, Z up. Positions are millimeters, angles signed
geometric radians, times seconds; CSV adds rounded integer microseconds.
Quaternion order is w,x,y,z. All four couplers retain their measured
approximately 40 mm lengths.

`sample_reference.py` implements monotone cubic joint interpolation and outputs
geometric centidegrees with derivatives. `execution-contract.json` supplies
independent duration settings for all 10 phases and contact/support events,
bound to exact source hashes. It uses the shared `execution-policy.json`:
coordinated joint/body/face timing, contact-aware transitions/interruption,
controlled initial engagement and separately configured PWM pulse phases.

```bash
python3 sample_reference.py 5600
python3 timing.py execution-contract.json --profile research_candidate --scale 2 --time 3
```

The second command previews a **11.75-second research clock**, with twice the
joint speed and four times the acceleration; it does not alter the Blender
demonstration or qualify that speed for hardware. Operating timing and physical
servo limits remain uncalibrated. Entry assumes the recorded standing pose.
While the feet are raised, retain belly support through a coordinated stop and
foot-replacement path; do not jump directly to the last standing sample.

Body Control keeps the existing semantic Swim command. The V2 model/firmware
owner must implement calibration and physical execution. No V1 assets, gateway
or firmware code were changed by this handoff.

## Focused results

- Sixteen evaluated Blender poses, including between keys: maximum joint
  connection error **0.0000399 mm**; foot prediction error **0.0000291 mm**.
- Evaluated bottom-cover clearance **0.0000025 mm** during belly support;
  lowest sole Z **−0.0000159 mm**, numerical floor residue.
- All soles remain about **41.950 mm above the floor during paddling**.
- Minimum assumed-COM support margin **39.116 mm** across the complete motion;
  bottom-cover support margin **51.500 mm** during the raised-foot portion.
- Peak interpolated demand **146.833°/s**, **491.482°/s²**. All 2820
  interpolation intervals have bounded midpoints; final standing joint angles
  match the initial pose exactly. Position and velocity are continuous;
  acceleration continuity is unqualified.
- All four legs change their Part006/Part005 pose at every sampled interval of
  the steady segment; Part005 traverses 60° on each leg. Consecutive steady
  cycles repeat within 3e-15 radians, without a seam hold.
- All 296 remaining compared model meshes retain their vertex hashes. Earlier command
  curves match at seven sampled Wave/Dance frames. The preservation report lists
  two previously referenced Cylinder objects absent at final comparison; this
  motion does not restore removed objects.

Detailed results are in `validation.json`, `blender-validation.json`,
`interpolation-validation.json`, `breaststroke-validation.json` and
`preservation-validation.json`. Full
collisions, wiring clearance, calibrated travel, measured masses, support-cover
strength and loaded servo/electrical capability remain unverified.

## Reproduction

With Python 3 and NumPy, from this source directory:

```bash
python3 generate_swim.py
python3 export_swim.py
python3 validate_breaststroke.py
```

The package includes geometry and body/sole samples, rig references, generation
and application scripts, face bitmaps, sampler and timing contract. Start
Blender from `Before-Swim.blend` after saving other work. In the Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-swim-20260916/apply_swim.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

The script appends Swim and saves its working copy. The portable source archive
excludes the large Blender files and raw rendered frame directory; the Blender
files remain at the workspace paths above.
