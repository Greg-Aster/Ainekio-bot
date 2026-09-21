# Seated Wave — twelve-servo source

The robot adopts the existing **Sit** pose, lifts the physical front-left leg (CAD RL), sets Part006 to −34.24° and Part005 to +45°, and waves the extended foot using a modest shoulder sweep. This 2026-09-16 revision turns Part005 inward by 35° from the previous +80° wave pose.

Existing command: `{"t":"intent","name":"emote","asset":"wave"}`. Body Control already exposes `data-emote="wave"`.

## Pose and timing

| Time | Action |
| --- | --- |
| 0–3 s | Existing Sit motion: rear legs crouched, body pitched 27.5° nose up |
| 3–4.2 s | Lift front-left shoulder to 80° |
| 4.2–5.8 s | Extend carrier and crank |
| 5.8–9.4 s | Three waves: shoulder 80 → 95 → 65 → 95 → 65 → 95 → 80°, 0.6 s per interval |
| 9.4–11 s | Retract carrier and crank |
| 11–12.2 s | Replace foot into Sit |
| 12.2–15.2 s | Reverse Sit to standing |
| 15.2–16 s | Hold standing; retain this pose after completion |

During the wave, **Part006 = −34.24°**, **Part005 = +45°** in signed geometric coordinates. These are geometric pose settings, not calibrated hardware end stops. The generator retains approximately **26.4° of linkage bend** and does not enforce a perfectly straight limb. Planar pivot-O to foot-bolt reach is **97.474 mm**. Shoulder maximum is **95°**, with a 65–95° wave arc.

The other three soles remain grounded. Sit body datum is X = −8 mm, Z = 63.415 mm, with a 27.5° nose-up pitch. The existing `wave` bitmap starts at time zero; `stand` returns at 15.2 s. Both original face assets are included unchanged.

## Pose vocabulary

| Part / variable | Useful name | What to ask for |
| --- | --- | --- |
| Part002 / h | Shoulder roll or side lift | Raise/lower the whole leg sideways; widen/narrow the wave sweep |
| Part006 / alpha | Upper-arm pitch or upper carrier angle | Move the upper link forward/backward |
| Part005 / theta | Elbow drive or four-bar input crank | Bend/extend the lower link through the linkage |
| Passive lower link / beta | Forearm or lower-leg orientation | Describe the desired hand/foot direction; the solver closes the linkage |

“Elbow” is a useful visual term. Its bend is determined by the relationship between the upper and lower links; it is not a directly driven hinge. Part005 crank degrees do not map one-for-one to elbow degrees. Here −35° at Part005 changes the passive lower-link orientation by approximately −7.57° and increases elbow bend by approximately 7.57°.

A precise request is: **“Physical front-left: reduce Part005 by 35° from this pose so the foot points farther forward; keep the upper arm and shoulder sweep.”** Include the physical leg, desired direction relative to the face/body, and whether an angle is a change or an absolute setpoint.

The changed pose moves the foot bolt **5.90–6.61 mm farther forward** throughout the wave. `revision.json` records the comparison. All eleven other actuator tracks and the body trajectory match the preceding version exactly.

## Firmware handoff

`source.json` and `source.csv` contain **1921 samples at 120 Hz**, with body pose, foot-bolt positions, sole positions/contact states and all twelve angles. `schema.json` defines units/order; `config.json` defines motion settings; `manifest.json` records the command, face cues, completion and provenance hashes.

Order: CAD **FL, FR, RL, RR**, each **h002, alpha006, theta005**. FL/FR are physical rear-left/rear-right; RL/RR are front-left/front-right. Positions are millimeters, actuator angles signed geometric radians, timestamps seconds (`time_us` rounded microseconds), quaternions w,x,y,z. World X is forward, Y left, Z up. Geometric zero includes the existing Part005 re-clocking.

Use the provided monotone cubic Hermite interpolation and rational 120 Hz indexing. `sample_reference.py` outputs geometric CAD centidegrees and derivatives; these are not electrical servo commands. Preserve continuous angles and hold the terminal standing position. The raised foot has `contact_active=false`; its lowest sole position is not a supporting ground contact.

Entry assumes standing neutral. The firmware owner must handle calibrated transitions from Rest, Sit, walking or interrupted commands. Electrical channel/sign/center/pulse mapping, real servo travel and loaded timing remain unqualified. No firmware, gateway or Body Control code is changed. Keep the V1 motion independent; `reference-v1-wave.json` is behavior reference only.

## Focused results

- Nine evaluated Blender poses, including between source keys: maximum joint disconnection 0.00003237 mm; foot prediction error 0.00003452 mm.
- Lowest evaluated sole Z: -0.00003135 mm, numerical residue at the floor. Chassis clearance: 2.000 mm.
- Assumed-COM support margin: minimum **15.790 mm**; peak raised sole height: 117.425 mm.
- Peak interpolated joint speed **125.000°/s**, acceleration **551.262°/s²**.
- All 1920 interpolation intervals bounded; exact joint return to recorded neutral. Position and velocity continuous; acceleration continuity unqualified.

COM is assumed at the body datum and does not account for measured moving-leg mass. Full collisions, wiring clearance, actual servo stops, loads and physical stability remain unverified. Existing intended mounts are retained. The sole model follows the measured Sit rolling contacts and holds the three support contacts while waving. Detailed numbers are in the three validation JSON files.

## Files and reproduction

Blender: `/home/greggles/blender-5.0.0-linux-x64/robot-wave-seated-20260916/Ainekio-Wave-Seated.blend`.

Frames **529–913**, after the original range tests. Saved at **683**, during the seated wave. Set frame 529 to play the whole command. `Before-Wave-Refinement.blend` preserves the preceding live scene; earlier command files remain separate. `wave-preview.mp4` is the preview.

With Python and NumPy, from this package:

```bash
python3 generate_wave.py
python3 export_wave.py
python3 sample_reference.py 6400
```

`generate_sit_reference.py` reproduces the accepted Sit entry/exit. `gait_kinematics.py`, `plan_crawl.py`, geometry JSON, sole hulls and body samples are included. `generate_wave.generate(settings)` accepts timing, posture and reach-setting overrides and rejects trajectories that violate its configured bounds.

In Blender's Python console, with the existing research rig open:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-wave-seated-20260916/apply_wave.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p)})
```

The script reapplies/saves the command and plays it once. `check_blender.py` provides the focused evaluated comparison; `render_preview.py` renders in background Blender. The full .blend stays in the workspace rather than the source ZIP.
