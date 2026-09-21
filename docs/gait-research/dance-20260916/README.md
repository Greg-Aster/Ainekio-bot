# Dance — twelve-servo motion

Five alternating left/right paired-leg beats with shoulder sway, body bob, roll
and twist, followed by a return to standing. All four soles remain grounded.
The existing command is preserved:

```json
{"t":"intent","name":"emote","asset":"dance"}
```

The eight-servo source alternates right channels R4/R3 and left L3/L4 five times,
with the original Dance face and a final Stand face. This adaptation preserves
that rhythm and intent. Its twelve coordinated geometric tracks are solved for
the current four-bar mechanism; the V1 electrical angles and sequential servo
timing are not copied into the V2 mechanism.

## Animation

| Time | Motion |
| --- | --- |
| 0–1.5 s | Settle 9 mm below the neutral standing body height |
| 1.5–10.5 s | Five 1.8-second left/right beats |
| 10.5–12 s | Return to the exact initial standing pose |
| 12–12.5 s | Recorded standing hold; continue holding after completion |

Each beat has four 0.45-second phases: rock left, rebound, rock right, rebound.
At either side the body shifts 12 mm laterally and 3 mm fore/aft, dips another
6 mm, rolls 6°, pitches 3° and twists 5°. Shoulders reach approximately −19.5°
to +19.8° across the four legs. `config.json` exposes these amplitudes and timing.
The existing two Dance bitmaps loop at 1 fps; Stand returns at 12 s.

Blender file:
`/home/greggles/blender-5.0.0-linux-x64/robot-dance-20260916/Ainekio-Dance.blend`.
Dance is appended at **frames 937–1237**, after Wave's end at 913. The saved
preview range selects Dance. Earlier animation curves and model meshes remain
intact; `Before-Dance.blend` preserves the live source including unsaved changes.
The original range-test scene is retained in the file.

- [Short preview](dance-preview.mp4)
- [Preview still](dance-preview.png)
- [Command manifest](manifest.json)
- [Twelve-joint CSV](source.csv)
- [Full timestamped source](source.json)

## Firmware and Body Control handoff

There are **1501 samples at 120 Hz**, containing body position/orientation, all
twelve actuator angles, passive linkage angles, foot-bolt positions, sole
contacts, contact states and assumed COM. World axes are X forward, Y left, Z up.
Positions are millimeters, times seconds, actuator angles signed geometric
radians, quaternion order w,x,y,z. CSV also includes integer microseconds.

Leg-major order is CAD **FL, FR, RL, RR**, each **h/Part002, alpha/Part006,
theta/Part005**. CAD FL/FR are physical rear-left/rear-right; RL/RR are physical
front-left/front-right. `schema.json` contains the mapping and units.

`sample_reference.py` provides the established monotone cubic sampler in
geometric centidegrees, with velocity and acceleration. These values require
the V2 calibration mapping before physical output. The source uses the current
approximately **40 mm coupler on all four legs** and preserves assembly branches.

The [execution contract](execution-contract.json) provides separately editable
duration settings for all 23 phases and binds the exact source hashes. It uses
the [shared execution policy](execution-policy.json) introduced for the preceding
commands: one clock for joints/body/contacts/face cues, coordinated entry and
interruption, and separately configured initial engagement and PWM phase offsets.
Demonstration timing is recorded; research timing is adjustable; operating values
remain null pending loaded calibration. No arbitrary per-joint motion delays
are inserted.

```bash
python3 timing.py execution-contract.json --profile research_candidate --scale 2 --time 1
python3 sample_reference.py 1950
```

The 2× example gives a **6.25-second offline research schedule**, with twice the
requested joint speed and four times the acceleration. It does not change the
saved demonstration or establish hardware capability. Keep the semantic Dance
request in Body Control; the selected V2 model owns calibration and execution.
V1 assets, firmware and gateway code are unchanged.

Entry assumes the recorded standing pose. Transitions from Sit, Rest, walking or
an interrupted motion belong to the existing calibrated executor. Finish by
holding the recorded standing endpoint. Dance is finite: five beats then stand.
Repeated beats match exactly at their ready-pose boundaries; different repeat
counts can be generated through `cycles` in `generate_dance.py` settings.

## Focused validation

- Nine evaluated Blender poses, including between keys: maximum joint connection
  error **0.0000378 mm**, maximum foot prediction error **0.0000225 mm**.
- Lowest evaluated sole Z **−0.0000235 mm**, numerical residue at the floor;
  sampled chassis clearance **31.378 mm**.
- Minimum support margin **38.140 mm**, using the explicitly assumed body-datum
  COM. This does not establish physical balance under load.
- Peak interpolated joint demand **82.626°/s**, **714.090°/s²**; all 1500
  interpolation intervals have bounded midpoint positions. Position and velocity
  are continuous; acceleration continuity is unqualified.
- Exact return to initial joint angles; all five beats reuse identical solved
  contact/pose data. The all-four-contact rolling model retains a material vertex
  until a supporting-feature transfer; largest finite-step normal correction is
  **0.0156 mm**. Contact transfer is not a claim of zero physical foot slip.
- All 298 model mesh vertex hashes match the preserved live source. Earlier
  command curves match at all five sampled comparison frames.

Details: `validation.json`, `interpolation-validation.json`,
`blender-validation.json`, `preservation-validation.json`. Full collisions,
measured masses, wiring clearance, electrical calibration, servo loading and
power behavior remain unverified. Existing intended center mounts are retained.

## Reproduction

With Python 3 and NumPy, from this directory:

```bash
python3 generate_dance.py
python3 export_dance.py
```

The package includes the measured geometry, sole/body samples, rig references,
generator, curve writer, sampler, face bitmaps and validation scripts. Start
Blender from the preserved `Before-Dance.blend` after saving any other work.
In Blender's Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-dance-20260916/apply_dance.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

`apply_dance.py` appends the generated motion and saves `Ainekio-Dance.blend`.
The portable source ZIP excludes the large Blender files and rendered frame
directory; their workspace paths are listed above.
