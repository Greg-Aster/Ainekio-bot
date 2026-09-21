# Rest — twelve-servo motion source

The robot lowers all four legs into a level crouch in three seconds, then holds the pose. This is the twelve-servo interpretation of the existing Rest command. The original rest face bitmaps are included unchanged.

## Command and playback

```json
{"t":"intent","name":"emote","asset":"rest"}
```

Body Control already exposes this as `data-emote="rest"`. Preserve that command path. The V1 asset targets all eight electrical joints at 90 degrees with sequential timing; those electrical values are reference behavior, not twelve-servo geometric angles.

- 0–3 s: smooth descent from corrected neutral standing.
- 3–5 s: held rest pose; continue holding after the source ends until another command.
- Face: `rest`, 128 × 64, 1 fps, boomerang. Blender frame sequence 0, 1, 2, 1 repeats.
- Body datum lowers from 80.962 mm to **32 mm**, with zero translation in X/Y and zero pitch/roll/yaw.
- All four soles remain on the floor. Lowest chassis point: **6.750 mm** above it.
- Final angles on each leg: shoulder h = 0°, carrier alpha ≈ +43.873°, crank theta ≈ −31.481°. Exact per-leg values are in the source and manifest.
- This is a servo-held posture. It does not request motor disable or assume the chassis is supported by the floor.

The three-second descent and 32 mm height are adjustable research choices. Four shoulders hold geometric zero because this is a symmetric lowering motion with unchanged lateral stance. All twelve channels are recorded.

## Source and integration

`source.json` and `source.csv` contain **601 samples at 120 Hz**, including body pose, foot-bolt targets, actual sole contacts, contact flags and all twelve actuator angles. `schema.json` defines columns and units; `manifest.json` records the command, face, terminal pose and source hashes. `config.json` contains pose, timing and provisional limits.

Order: CAD **FL, FR, RL, RR**, each **h002, alpha006, theta005**. CAD FL/FR are physical rear-left/rear-right; RL/RR are physical front-left/front-right. Angles are signed geometric radians, positions millimeters, timestamps seconds (`time_us` is rounded microseconds). World X is forward, Y left, Z up; quaternion order is w,x,y,z. The corrected CAD zero includes Part005 re-clocking.

Use monotone cubic Hermite interpolation with harmonic same-sign secants and zero endpoint tangents, as implemented by `sample_reference.py`. It outputs geometric CAD centidegrees and derivatives; these are not servo commands. Use rational timestamp indexing (`elapsed_us * 120 / 1000000`), retain the terminal position and zero velocity after completion. Keep the existing V1 asset independent.

Entry assumes the recorded standing neutral. Entry from Sit, walking, interrupted commands or arbitrary current positions still requires the firmware agent's transition handling. Electrical channel/sign/center/pulse mapping and physical travel/load limits remain uncalibrated. No firmware or gateway code was changed by this package.

## Focused results

Five evaluated Blender poses, including between source keys:

- Maximum linkage joint disconnection: 0.00003259 mm.
- Maximum independent foot-prediction error: 0.00002246 mm.
- Minimum evaluated sole height: -0.00001592 mm (numerical floor residue).
- Minimum assumed-COM support margin: 39.116 mm.
- Peak interpolated joint speed: 26.006°/s; acceleration: 33.775°/s².
- Bounded interpolation and terminal hold checked across all 600 source intervals.

The rounded-sole model fixes a sole material vertex in world space until the supporting feature changes. Maximum normal correction at such transfers was 0.00026286 mm. Contact positions are not foot bolts or a fixed bolt offset.

COM is explicitly assumed at the body datum. Mass balance, full part-to-part collisions, physical stability, servo capability and dynamics remain unverified. Existing intended center mounts are preserved. Position and velocity are continuous; acceleration continuity is not established. Detailed results: `validation.json`, `blender-validation.json`, `interpolation-validation.json`.

## Blender and reproduction

Working file: `/home/greggles/blender-5.0.0-linux-x64/robot-rest-20260915/Ainekio-Rest.blend`.

The command is at **frames 529–649**, after the original range tests. The saved file opens on the held rest pose. Set frame 529 and play to review. Manual timeline looping replays the demonstration; the command itself holds its final pose. `Before-Rest.blend` preserves the live scene, including unsaved changes, before this command. Prior command files remain separate.

From this package directory, with Python and NumPy:

```bash
python3 generate_rest.py
python3 export_rest.py
python3 sample_reference.py 3000
```

Optional generator arguments: `--height` (mm), `--pitch` (degrees), `--x` (mm). Infeasible trajectories are rejected rather than clamping individual actuators. The measured solver/geometry and sole hulls are included.

With the existing research rig open, run in Blender's Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-rest-20260915/apply_rest.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p)})
```

This reapplies the command to the research rig, saves the Rest copy and demonstrates it once. `check_blender.py` is the focused mechanism comparison. `render_preview.py` renders a short preview in background Blender. `rest-preview.mp4` is the exported preview; the full .blend is kept in the workspace rather than duplicated into the source ZIP.
